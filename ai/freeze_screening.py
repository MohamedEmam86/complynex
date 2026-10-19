# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

"""
Freeze-order screening of intake subjects against the organisation's OWN
records: customers, merchants, beneficial owners, other KYC subjects that
modules or packs register in amlkyc.subjects, and the counterparties of the
last N days of transactions.

DB-only and synchronous (freeze turnaround is time-critical): no
Elasticsearch, no semantic service. Matching reuses the screening module's
name scorer (Arabic/English transliteration + bidirectional Jaro-Winkler,
screening/name_normalizer.py) after a fast rapidfuzz pre-filter, and exact
identification-number comparison (plain value or the same hash
customers.national_id_hash uses).

A match is only a lead: the user decides "freeze" (recorded, AML candidate
created / updated, audit log) or "false positive" (with a reason). Core
customer state is never changed here — no freeze API exists in the core.
"""

import json
import logging
import re
from datetime import date, datetime, time, timedelta

from database.db import get_db

from . import text as T

logger = logging.getLogger(__name__)

# Generic core tables. Missing tables / columns are skipped (installations differ).
SOURCES = [
    {'source': 'customer', 'table': 'customers', 'key': 'customers',
     'names': ('full_name', 'full_name_arabic', 'company_name', 'company_name_arabic'),
     'ids': ('id_number', 'registration_number'), 'hash': 'national_id_hash',
     'endpoint': ('aml.view_customer', 'id')},
    {'source': 'merchant', 'table': 'merchants', 'key': 'merchants',
     'names': ('merchant_name', 'trade_name'), 'ids': ('cr_number', 'tax_id'),
     'endpoint': ('merchant_kyc.view_merchant', 'id')},
    {'source': 'beneficial_owner', 'table': 'merchants', 'key': 'merchants.ubo',
     'names': ('ubo_name',), 'ids': ('ubo_id_number',), 'endpoint': ('merchant_kyc.view_merchant', 'id')},
    {'source': 'beneficial_owner', 'table': 'beneficial_owners', 'key': 'beneficial_owners',
     'names': ('owner_name', 'owner_name_arabic'), 'ids': ('id_number',), 'ref': 'customer_id',
     'endpoint': ('aml.view_customer', 'ref')},
    {'source': 'beneficial_owner', 'table': 'kyc_beneficial_owners', 'key': 'kyc_beneficial_owners',
     'names': ('full_name',), 'ids': (), 'ref': ('subject', 'subject_id'), 'endpoint': ('amlkyc.kyc_file', 'subject')},
]
_SUBJECT_ID_COLS = ('national_id', 'id_number', 'cr_number', 'registration_number', 'commercial_register')
SOURCE_LABELS = {'customer': ('Customer', 'عميل'), 'merchant': ('Merchant', 'تاجر'),
                 'beneficial_owner': ('Beneficial owner', 'مستفيد حقيقي'), 'counterparty': ('Counterparty', 'طرف مقابل'),
                 'kyc_subject': ('KYC subject', 'خاضع لاعرف عميلك')}
PREFILTER_CUTOFF = 60          # rapidfuzz token_set_ratio (0-100) before the precise scorer
PREFILTER_LIMIT = 200


# ------------------------------------------------------------------ pure matching
def norm_id(v):
    s = re.sub(r'[^0-9A-Za-z]', '', str(v or '').translate(T._DIGITS)).upper()
    return s if len(s) >= 5 else ''


def split_names(v):
    return [n.strip(' .-–') for n in re.split(r'[,،;\n]+', v or '') if len(n.strip(' .-–')) >= 3]


def _clean(name):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s\'-]', ' ', name or '')).strip()


def _key(name):
    """Latin, phonetically normalised form used by the pre-filter (Arabic is transliterated first)."""
    from screening.name_normalizer import _transliterate_for_scoring, normalise
    n = _clean(name)
    return normalise(_transliterate_for_scoring(n)) or T.normalise(n)


def name_score(query, candidate):
    """0..1 — the screening module's scorer; identical normalised text is 1.0."""
    if T.normalise(query) == T.normalise(candidate):
        return 1.0
    try:
        from screening.name_normalizer import score_match
        return float(score_match(_clean(query), _clean(candidate)))
    except Exception:          # scorer unavailable: character n-grams (ai/text.py)
        return T.cosine(T.ngrams(query), T.ngrams(candidate))


def match(names, ids, candidates, threshold=0.80, id_hash=None):
    """Pure function. candidates: [{source, key, record_id, label, names: [..], ids: [..], id_hashes: [..], ref}]
    → [{source, key, record_id, matched_name, match_type, score, query_name, query_id, ref}] best first, one per
    (key, record_id, match_type)."""
    from rapidfuzz import fuzz, process
    best = {}

    def add(c, mtype, score, qname=None, qid=None, matched=None):
        k = (c['key'], c['record_id'], mtype)
        if k not in best or score > best[k]['score']:
            best[k] = {'source': c['source'], 'key': c['key'], 'record_id': c['record_id'], 'ref': c.get('ref'),
                       'matched_name': (matched or c.get('label') or '')[:300], 'match_type': mtype, 'score': round(score, 3),
                       'query_name': qname, 'query_id': qid, 'detail': c.get('detail')}

    q_ids = {norm_id(x): x for x in ids or [] if norm_id(x)}
    q_hashes = {}
    if id_hash and q_ids:
        for n, raw in q_ids.items():
            try:
                h = id_hash(n)
                if h:
                    q_hashes[h] = raw
            except Exception:
                break
    for c in candidates:
        for v in c.get('ids') or []:
            if norm_id(v) in q_ids:
                add(c, 'id', 1.0, qid=q_ids[norm_id(v)])
        for h in c.get('id_hashes') or []:
            if h and h in q_hashes:
                add(c, 'id', 1.0, qid=q_hashes[h])

    flat = [(i, n) for i, c in enumerate(candidates) for n in c.get('names') or [] if n and len(n.strip()) >= 3]
    keys = [_key(n) for _, n in flat]
    for q in names or []:
        qk = _key(q)
        if not qk:
            continue
        for _, _pre, j in process.extract(qk, keys, scorer=fuzz.token_set_ratio, score_cutoff=PREFILTER_CUTOFF,
                                          limit=PREFILTER_LIMIT):
            ci, cname = flat[j]
            s = name_score(q, cname)
            if s >= threshold:
                add(candidates[ci], 'name', s, qname=q, matched=cname)
    return sorted(best.values(), key=lambda m: (m['match_type'] != 'id', -m['score']))


# ------------------------------------------------------------------ loading candidates (DB, defensive)
def _columns(db, table):
    try:
        if not db.execute("SELECT to_regclass(%s) AS t", (table,)).fetchone()['t']:
            return set()
        return {r['column_name'] for r in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = current_schema()",
            (table,)).fetchall()}
    except Exception:
        db.rollback()
        return set()


def _hash_fn():
    try:
        from data_protection.encryption_service import EncryptionService
        EncryptionService.hash_value('0')
        return EncryptionService.hash_value
    except Exception:
        return None


def load_candidates(db=None, counterparty_days=90, today=None):
    """→ (candidates, sources_searched [{source, table, rows}], skipped [table])."""
    db = db or get_db()
    out, searched, skipped = [], [], []
    for spec in SOURCES:
        cols = _columns(db, spec['table'])
        names = [c for c in spec['names'] if c in cols]
        if 'id' not in cols or not names:
            skipped.append(spec['key'])
            continue
        idc = [c for c in spec['ids'] if c in cols]
        hc = [spec['hash']] if spec.get('hash') in cols else []
        ref = spec.get('ref')
        refc = [c for c in ((ref,) if isinstance(ref, str) else (ref or ())) if c in cols]
        sel = ', '.join(dict.fromkeys(['id'] + names + idc + hc + refc))
        try:
            rows = db.execute(f"SELECT {sel} FROM {spec['table']}").fetchall()
        except Exception:
            db.rollback()
            skipped.append(spec['key'])
            continue
        for r in rows:
            nm = [r[c] for c in names if r[c]]
            if not nm and not any(r[c] for c in idc):
                continue
            out.append({'source': spec['source'], 'key': spec['key'], 'record_id': r['id'], 'label': nm[0] if nm else '',
                        'names': nm, 'ids': [r[c] for c in idc if r[c]], 'id_hashes': [r[c] for c in hc if r[c]],
                        'ref': {c: r[c] for c in refc} or None})
        searched.append({'source': spec['source'], 'table': spec['key'], 'rows': len(rows)})
    _load_subjects(db, out, searched)
    _load_counterparties(db, out, searched, skipped, counterparty_days, today)
    return out, searched, skipped


def _load_subjects(db, out, searched):
    """KYC subjects registered by other modules or packs (amlkyc.subjects) whose table is not covered above."""
    try:
        from amlkyc import subjects as S
    except Exception:
        return
    covered = {s['table'] for s in SOURCES}
    for code, s in list(S.SUBJECTS.items()):
        if s.table in covered:
            continue
        rows = S.rows(code, db)
        for r in rows:
            try:
                nm = s.name(r)
            except Exception:
                nm = None
            idv = [r[c] for c in _SUBJECT_ID_COLS if r.get(c)]
            if nm or idv:
                out.append({'source': 'kyc_subject', 'key': s.table, 'record_id': r['id'], 'label': nm or '',
                            'names': [nm] if nm else [], 'ids': idv, 'ref': {'subject': code}})
        searched.append({'source': 'kyc_subject', 'table': s.table, 'rows': len(rows)})
        covered.add(s.table)


def _load_counterparties(db, out, searched, skipped, days, today):
    cols = _columns(db, 'transactions')
    if not {'id', 'counterparty_name', 'transaction_date'} <= cols:
        skipped.append('transactions')
        return
    since = ((today or date.today()) - timedelta(days=int(days))).isoformat()
    acct = 'counterparty_account' if 'counterparty_account' in cols else 'NULL'
    try:
        rows = db.execute(f"""SELECT max(id) AS id, counterparty_name, {acct} AS account, count(*) AS n,
                                     max(transaction_date) AS last_date
                              FROM transactions WHERE transaction_date >= %s AND coalesce(counterparty_name, '') <> ''
                              GROUP BY counterparty_name, {acct}""", (since,)).fetchall()
    except Exception:
        db.rollback()
        skipped.append('transactions')
        return
    for r in rows:
        out.append({'source': 'counterparty', 'key': 'transactions', 'record_id': r['id'], 'label': r['counterparty_name'],
                    'names': [r['counterparty_name']], 'ids': [r['account']] if r['account'] else [],
                    'detail': f"{r['n']} transaction(s) in {days} days, last {str(r['last_date'])[:10]}"})
    searched.append({'source': 'counterparty', 'table': 'transactions', 'rows': len(rows)})


# ------------------------------------------------------------------ intake integration
def subjects_of(item, final=None):
    """Names and identification numbers named in the order (confirmed fields first, then the text)."""
    f = (final or item.get('final') or {}).get('fields') or {}
    names = split_names(f.get('subject_names')) + split_names(f.get('subject_name'))
    ids = [x for x in re.split(r'[,،;\s]+', (f.get('national_id') or '').translate(T._DIGITS)) if norm_id(x)]
    ids += T.identifiers(item.get('body') or '')['national_id']
    return list(dict.fromkeys(names)), list(dict.fromkeys(ids))


def order_date(text, created_at):
    """The order's own date (issued / dated …) when it is earlier than the submission (max 30 days back)."""
    from .tasks import _DATE_HINTS, _date_near
    d = _date_near(text or '', _DATE_HINTS['issue_date'])
    if not d or not created_at:
        return None
    dt = datetime.combine(d, time())
    return dt if created_at - timedelta(days=30) <= dt < created_at else None


def receipt_time(item):
    """When the order was received: the earlier of created_at and received_at."""
    c, r = item.get('created_at'), item.get('received_at')
    return min(x for x in (c, r) if x) if (c or r) else None


def hours_since(item, now=None):
    t = receipt_time(item)
    return round(((now or datetime.now()) - t).total_seconds() / 3600, 3) if t else None


def should_screen(intent):
    return bool((intent or {}).get('handler_params', {}).get('screen_subjects'))


def run_for_item(item_id, db=None, today=None):
    """Screen the item's subjects now and store the matches. → summary dict."""
    from . import settings
    db = db or get_db()
    it = dict(db.execute("SELECT * FROM ai_intake_items WHERE id = %s", (item_id,)).fetchone() or {})
    if not it:
        raise LookupError('intake item not found')
    cfg = settings.get_config()
    names, ids = subjects_of(it)
    cands, searched, skipped = load_candidates(db, cfg['ai.freeze_counterparty_days'], today)
    found = match(names, ids, cands, cfg['ai.freeze_match_threshold'], _hash_fn()) if (names or ids) else []
    for m in found:
        db.execute("""INSERT INTO ai_screening_matches (item_id, query_name, query_id, source, source_table, record_id, matched_name,
                      match_type, score, detail) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT (item_id, source_table, record_id, match_type) DO UPDATE SET
                        score = GREATEST(ai_screening_matches.score, EXCLUDED.score),
                        query_name = COALESCE(EXCLUDED.query_name, ai_screening_matches.query_name),
                        query_id = COALESCE(EXCLUDED.query_id, ai_screening_matches.query_id),
                        detail = COALESCE(EXCLUDED.detail, ai_screening_matches.detail)""",
                   (item_id, (m['query_name'] or '')[:300] or None, (m['query_id'] or '')[:40] or None, m['source'], m['key'],
                    m['record_id'], m['matched_name'], m['match_type'], m['score'],
                    json.dumps({'ref': m.get('ref'), 'note': m.get('detail')}, default=str)))
    received = it.get('received_at') or order_date(it.get('body'), it.get('created_at'))
    summary = {'names': names, 'ids': [i[:4] + '…' + i[-3:] if len(i) > 8 else i for i in ids], 'matches': len(found),
               'searched': searched, 'skipped': skipped, 'threshold': cfg['ai.freeze_match_threshold'],
               'counterparty_days': cfg['ai.freeze_counterparty_days']}
    db.execute("""UPDATE ai_intake_items SET screened_at = %s, received_at = COALESCE(received_at, %s),
                  proposal = COALESCE(proposal, '{}'::jsonb) || jsonb_build_object('screening', %s::jsonb) WHERE id = %s""",
               (datetime.now(), received, json.dumps(summary, default=str), item_id))
    db.commit()
    return summary


def matches(item_id, db=None):
    db = db or get_db()
    rows = [dict(r) for r in db.execute("""SELECT m.*, u.first_name || ' ' || u.last_name AS decided_by_name
                                           FROM ai_screening_matches m LEFT JOIN users u ON u.id = m.decided_by
                                           WHERE m.item_id = %s ORDER BY (m.match_type <> 'id'), m.score DESC, m.id""",
                                        (item_id,)).fetchall()]
    for r in rows:
        try:
            r['detail'] = json.loads(r['detail']) if r.get('detail') else {}
        except ValueError:
            r['detail'] = {'note': r['detail']}
        r['url'] = record_url(r)
    return rows


def record_url(m):
    from .handlers import _url
    spec = next((s for s in SOURCES if s['key'] == m['source_table']), None)
    ref = (m.get('detail') or {}).get('ref') or {}
    if m['source'] == 'counterparty':
        return _url('aml.view_transaction', tx_id=m['record_id'])
    if m['source'] == 'kyc_subject':
        return _url('amlkyc.kyc_file', code=ref.get('subject'), subject_id=m['record_id']) if ref.get('subject') else None
    if not spec:
        return None
    ep, how = spec['endpoint']
    if how == 'id':
        return _url(ep, id=m['record_id'])
    if how == 'ref' and ref.get(spec['ref']):
        return _url(ep, id=ref[spec['ref']])
    if how == 'subject' and ref.get('subject'):
        return _url(ep, code=ref['subject'], subject_id=ref.get('subject_id'))
    return None


def can_decide(user, ai_level):
    return ai_level >= 2 and (user.is_admin() or user.can_edit('aml'))


def decide(match_id, action, user, reason=None, db=None):
    """'freeze' or 'false_positive' on one match. Raises ValueError."""
    from aml.unusual import register_candidate
    from models.audit import AuditLog
    db = db or get_db()
    m = db.execute("SELECT * FROM ai_screening_matches WHERE id = %s", (match_id,)).fetchone()
    if not m:
        raise ValueError('match not found')
    m = dict(m)
    if m['status'] != 'open':
        raise ValueError('this match is already decided')
    reason = (reason or '').strip()
    if action == 'false_positive' and not reason:
        raise ValueError('give the reason for the false positive')
    if action not in ('freeze', 'false_positive'):
        raise ValueError('unknown decision')
    item = dict(db.execute("SELECT * FROM ai_intake_items WHERE id = %s", (m['item_id'],)).fetchone())
    ref = ((item.get('final') or {}).get('fields') or {}).get('order_reference') or f"intake #{item['id']}"
    now = datetime.now()
    uid = None
    if action == 'freeze':
        desc = (f"Freeze order {ref}: {m['source']} #{m['record_id']} {m['matched_name']} matched "
                f"'{m['query_name'] or m['query_id']}' ({m['match_type']}, score {m['score']}). "
                f"Freeze decided by user #{user.id} at {now:%Y-%m-%d %H:%M}. {reason}").strip()
        uid, _ = register_candidate(source_module='ai_intake', detection_rule='freeze_order_match', description=desc,
                                    source_table='ai_screening_matches', source_record_id=m['id'],
                                    subject_name=(m['matched_name'] or '')[:250] or None,
                                    subject_ref=f"{m['source']}:{m['record_id']}"[:80], created_by=user.id, db=db)
        # the order's own candidate (created on confirmation) records the decision too
        db.execute("""UPDATE aml_unusual_transactions SET description = coalesce(description, '') || %s
                      WHERE source_table = 'ai_intake_items' AND source_record_id = %s""",
                   (f"\n[{now:%Y-%m-%d %H:%M}] FREEZE: {m['source']} #{m['record_id']} {m['matched_name']} (see UTR #{uid})",
                    item['id']))
    db.execute("""UPDATE ai_screening_matches SET status = %s, reason = %s, aml_unusual_id = %s, decided_by = %s, decided_at = %s
                  WHERE id = %s""", ('frozen' if action == 'freeze' else 'false_positive', reason or None, uid, user.id, now, m['id']))
    db.commit()
    try:
        AuditLog.log(user.id, f'ai_freeze_match_{action}', 'ai', item['id'],
                     f"match #{m['id']} {m['source']}:{m['record_id']} {action}{': ' + reason if reason else ''}"[:900])
    except Exception:
        db.rollback()
    return {'aml_unusual_id': uid, 'status': 'frozen' if action == 'freeze' else 'false_positive'}
