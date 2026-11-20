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
Diff and apply a parsed local negative-lists workbook (screening.local_lists.workbook) to the internal list.

Where the records live: internal_blacklist (the institution's own / local lists: national ID, legal_status for
a lifted order, the generic category shown on a hit). The hourly internal-list sync copies them into
screening_watchlist (source 'internal_blacklist') and the search index picks them up; apply() runs that sync,
the search-index sync and the EMLCU <-> Public Prosecution date-of-birth link right after it commits.

Identity across editions: local_list_records.record_key (workbook.record_key: kind + hash of the identity).
plan() compares the workbook with the previous import and gives, per record, one change:

  ADDED      new identity                             ADOPTED   an existing internal-list row (loaded before this
  CHANGED    same identity, content differs                     importer, e.g. by hand or CSV) taken over:
  LIFTED     was LISTED, every order now lifted                 same full national ID, or the same name when
  RELISTED   was LIFTED / REMOVED, now in force again           exactly one untracked row has it
  REMOVED    no longer in the workbook (delisted: is_active = 0, never deleted)
  (unchanged records are only stamped with the import number)

A lifted record keeps its internal-list row active with legal_status = 'LIFTED' (the hit stays visible,
labelled «إنهاء أثر», as the platform does for lifted orders) unless lifted_mode = 'inactive'.

Safety: plan() blocks when a sheet kind / category would shrink by more than shrink_pct (and at least
shrink_min records, or more than HARD_PCT whatever the size) compared with the previous import, when a
category disappears, when an unrecognised data sheet is present or when nothing was read - unless
allow_shrink / allow_unknown. apply() writes everything in ONE transaction (advisory lock, version row,
records, change log, internal_blacklist rows and their audit) and is idempotent: the same workbook again
gives zero changes.
"""
import datetime as _dt
import hashlib
import json
import logging
import os
import re
import subprocess
import sys

from screening.local_lists import workbook as W
from screening.local_lists.categories import CATEGORIES, label

logger = logging.getLogger(__name__)

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE = 'LOCAL_LISTS'                 # internal_blacklist.source of rows owned by this importer
CONFIRMATION = 'OFFICIAL_LIST'
LOCK = 'cx_local_lists_import'
SHRINK_PCT = 10.0
SHRINK_MIN = 25
HARD_PCT = 50.0
CHANGES = ('ADDED', 'ADOPTED', 'CHANGED', 'LIFTED', 'RELISTED', 'REMOVED')
# keywords that tell an untracked internal-list row belongs to one of the workbook's families
_FAMILY_WORDS = ('النائب العام', 'منع من التصرف', 'ارهاب', 'إرهاب', 'كيانات', 'مجلس الأمن', 'مجلس الامن', '1718',
                 '1988', '1267', 'داعش', 'القاعدة', 'ايران', 'إيران', 'prosecutor', 'terror', 'security council')


class ImportBusy(RuntimeError):
    pass


# ----------------------------------------------------------------------------- helpers
def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def content_sha(records):
    h = hashlib.sha256()
    for k, s in sorted((W.record_key(r), W.content_sha(r)) for r in records):
        h.update(f'{k}:{s}\n'.encode())
    return h.hexdigest()


def _cur(conn):
    from psycopg2.extras import RealDictCursor
    return conn.cursor(cursor_factory=RealDictCursor)


def _has_col(conn, table, col):
    c = conn.cursor()
    c.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s", (table, col))
    return c.fetchone() is not None


def _diff_fields(old, new):
    keys = sorted(set(old or {}) | set(new or {}))
    return [k for k in keys if (old or {}).get(k) != (new or {}).get(k)]


def link_masked_dobs(records):
    """Date of birth for a site record published with a masked national ID: decoded from the full national ID
    of a register record with the same name whose ID shows the same digits (one date only). Derived, so kept
    out of the content hash ('_dob_linked')."""
    full = {}
    for r in records:
        nid = W.valid_nid(r.get('national_id'))
        if nid and r['entity_type'] == 'INDIVIDUAL':
            full.setdefault(W.name_key(r['name']), set()).add(nid)
    n = 0
    for r in records:
        mid = str(r.get('national_id') or '')
        if r['kind'] != 'FIU_PERSONS' or '*' not in mid or r.get('dob'):
            continue
        vis = W.digits(mid)
        if len(vis) < 3:
            continue
        cands = {x for x in full.get(W.name_key(r['name']), ()) if x.endswith(vis) or x.startswith(vis)}
        dobs = {W.nid_dob(x) for x in cands} - {''}
        if len(dobs) == 1:
            r['_dob_linked'] = dobs.pop()
            n += 1
    return n


# ----------------------------------------------------------------------------- previous state
def previous_state(conn):
    c = _cur(conn)
    c.execute("""SELECT record_key, kind, category, status, blacklist_id, content_sha256, content
                 FROM local_list_records""")
    return {r['record_key']: r for r in c.fetchall()}


def _legacy_index(conn, tracked_ids):
    """Untracked internal_blacklist rows (loaded before this importer): by full national ID and by name."""
    c = _cur(conn)
    c.execute("""SELECT id, full_name, original_name, national_id, entity_type, category, source, is_active
                 FROM internal_blacklist WHERE COALESCE(source, '') <> %s""", (SOURCE,))
    by_nid, by_name, rows = {}, {}, {}
    for r in c.fetchall():
        if r['id'] in tracked_ids:
            continue
        rows[r['id']] = r
        nid = W.valid_nid(r['national_id'])
        if nid:
            by_nid.setdefault(nid, []).append(r['id'])
        for n in {W.name_key(r['original_name']), W.name_key(r['full_name'])}:
            if n:
                by_name.setdefault(n, []).append(r['id'])
    return rows, by_nid, by_name


def _family(text):
    t = str(text or '').lower()
    return any(w.lower() in t for w in _FAMILY_WORDS)


def _adopt(rec, legacy, claimed):
    rows, by_nid, by_name = legacy
    nk = W.name_key(rec['name'])
    nid = W.valid_nid(rec.get('national_id'))
    if nid:
        cands = [i for i in by_nid.get(nid, []) if i not in claimed]
        named = [i for i in cands if nk in {W.name_key(rows[i]['original_name']), W.name_key(rows[i]['full_name'])}]
        pick = named[0] if len(named) == 1 else (cands[0] if len(cands) == 1 else None)
        if pick:
            return pick
    cands = [i for i in set(by_name.get(nk, [])) if i not in claimed]
    if len(cands) != 1:
        return None
    r = rows[cands[0]]
    rn = W.valid_nid(r['national_id'])
    if rn and nid and rn != nid:
        return None
    if rn and not nid and str(rec.get('national_id') or '').strip('*'):
        vis = W.digits(rec.get('national_id'))
        if vis and not (rn.endswith(vis) or rn.startswith(vis)):
            return None
    et = str(r['entity_type'] or '').upper()
    if et in ('ENTITY', 'ORGANIZATION') and rec['entity_type'] == 'INDIVIDUAL':
        return None
    return cands[0]


# ----------------------------------------------------------------------------- plan
def plan(conn, parsed, allow_shrink=False, allow_unknown=False, shrink_pct=SHRINK_PCT, shrink_min=SHRINK_MIN,
         adopt_legacy=True):
    """Compare the parsed workbook with the previous import. Writes nothing."""
    records = parsed['records']
    prev = previous_state(conn)
    tracked_ids = {p['blacklist_id'] for p in prev.values() if p['blacklist_id']}
    legacy = _legacy_index(conn, tracked_ids) if adopt_legacy else ({}, {}, {})
    claimed = set()
    items = []
    counts = {}
    seen = set()

    def bump(cat, ch):
        counts.setdefault(cat, {k.lower(): 0 for k in CHANGES + ('UNCHANGED',)})[ch.lower()] += 1

    for rec in records:
        k = W.record_key(rec)
        seen.add(k)
        sha = W.content_sha(rec)
        p = prev.get(k)
        if p is None:
            bid = _adopt(rec, legacy, claimed) if adopt_legacy else None
            if bid:
                claimed.add(bid)
            ch = 'ADOPTED' if bid else 'ADDED'
            items.append({'change': ch, 'key': k, 'rec': rec, 'sha': sha, 'blacklist_id': bid, 'old_status': None})
        else:
            if p['status'] == 'LISTED' and rec['status'] == 'LIFTED':
                ch = 'LIFTED'
            elif p['status'] in ('LIFTED', 'REMOVED') and rec['status'] == 'LISTED':
                ch = 'RELISTED'
            elif p['status'] != rec['status'] or p['content_sha256'] != sha:
                ch = 'CHANGED'
            else:
                ch = 'UNCHANGED'
            items.append({'change': ch, 'key': k, 'rec': rec, 'sha': sha, 'blacklist_id': p['blacklist_id'],
                          'old_status': p['status'],
                          'fields': _diff_fields(p['content'], W.content_of(rec)) if ch != 'UNCHANGED' else []})
        bump(rec['category'], items[-1]['change'])
    for k, p in prev.items():
        if k not in seen and p['status'] != 'REMOVED':
            items.append({'change': 'REMOVED', 'key': k, 'rec': None, 'sha': p['content_sha256'],
                          'blacklist_id': p['blacklist_id'], 'old_status': p['status'], 'category': p['category'],
                          'kind': p['kind']})
            bump(p['category'], 'REMOVED')

    # ---- guard: shrink per (sheet kind, category) against the previous import
    reasons = []
    before, after = {}, {}
    for p in prev.values():
        if p['status'] != 'REMOVED':
            before[(p['kind'], p['category'])] = before.get((p['kind'], p['category']), 0) + 1
    for r in records:
        after[(r['kind'], r['category'])] = after.get((r['kind'], r['category']), 0) + 1
    shrink = []
    for key, b in sorted(before.items()):
        a = after.get(key, 0)
        drop = b - a
        pct = round(100.0 * drop / b, 2) if b else 0.0
        if drop > 0 and pct > shrink_pct and (drop >= shrink_min or pct > HARD_PCT):
            shrink.append({'kind': key[0], 'category': key[1], 'before': b, 'after': a, 'drop_pct': pct})
            reasons.append(f'{W.KIND_LABEL.get(key[0], key[0])} / {label(key[1], "en")}: {b:,} -> {a:,} records '
                           f'(-{pct:g}%; limit {shrink_pct:g}%)')
    if not records:
        reasons.append('the workbook has no list records (no sheet was recognised)')
    unknown = parsed.get('unknown') or []
    if unknown and not allow_unknown:
        reasons.append(f'{len(unknown)} sheet(s) look like list data but were not recognised')
    blocking = [r for r in reasons if not allow_shrink or not any(
        r.startswith(f"{W.KIND_LABEL.get(x['kind'], x['kind'])} / ") for x in shrink)]
    if unknown and allow_unknown:
        blocking = [r for r in blocking if 'not recognised' not in r]
    legacy_left = 0
    if adopt_legacy:
        rows = legacy[0]
        legacy_left = sum(1 for i, r in rows.items() if i not in claimed and int(r['is_active'] or 0) != 0
                          and (_family(r['category']) or str(r['source'] or '').upper() == 'INTERNAL_BULK_UPLOAD'))
    totals = {ch.lower(): sum(c[ch.lower()] for c in counts.values()) for ch in CHANGES + ('UNCHANGED',)}
    totals['records'] = len(records)
    totals['changes'] = sum(totals[ch.lower()] for ch in CHANGES)
    totals['lift_unmatched'] = sum(int((r.get('_flags') or {}).get('lift_unmatched', 0)) for r in records)
    return {'items': items, 'counts': counts, 'totals': totals, 'reasons': reasons, 'blocked': bool(blocking),
            'blocking': blocking, 'shrink': shrink, 'legacy_unmatched': legacy_left,
            'claimed_legacy': sorted(claimed), 'content_sha': content_sha(records),
            'unknown_sheets': len(unknown),
            '_prev_sig': {k: (p['status'], p['content_sha256']) for k, p in prev.items()}}


# ----------------------------------------------------------------------------- add-new-only mode
# The owner's default for an installation whose lists were already loaded: the database is NOT rewritten from
# the workbook. Existing rows are only linked to their identity (no content change), lifted records are not
# added, and a record already screenable (internal list, EMLCU site list, UN feed, by national ID, passport,
# UN reference or the same name with no conflicting ID / date of birth) is not added again.
DUP_REASONS = ('national_id', 'passport', 'un_reference', 'name', 'in_workbook')
SCREENABLE_SOURCES = ('emlcu', 'un', 'internal_blacklist')
ADD_KEYS = ('new_persons', 'new_entities', 'skipped_lifted') + tuple(f'dup_{r}' for r in DUP_REASONS) + \
    ('adopted_linked', 'un_skipped', 'unchanged', 'tracked_changes_not_applied')
_REF_KEYS = ('un_reference', 'reference_number', 'reference', 'un_ref', 'ref')


def _json_list(v):
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x not in (None, '')]
    s = str(v or '').strip()
    if s.startswith('['):
        try:
            return [str(x) for x in json.loads(s) if x not in (None, '')]
        except ValueError:
            pass
    return [p.strip() for p in s.split(',') if p.strip()] if s else []


def _json_dict(v):
    if isinstance(v, dict):
        return v
    try:
        d = json.loads(v) if str(v or '').strip().startswith('{') else {}
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


class Screenable:
    """What screening can already find: national IDs, passports, UN references and names (with the IDs / date
    of birth that tell two people with one name apart)."""

    def __init__(self):
        self.nid, self.pp, self.ref, self.name = set(), set(), set(), {}

    def add(self, names, nids=(), pps=(), dob='', refs=()):
        ent = {'nid': '', 'masked': [], 'dob': str(dob or '')[:10]}
        for n in nids:
            full = W.valid_nid(n)
            if full:
                self.nid.add(full)
                ent['nid'] = ent['nid'] or full
            elif len(W.digits(n)) >= 3:
                ent['masked'].append(W.digits(n))
        for p in pps:
            d = W.digits(p)
            if len(d) >= 6:
                self.pp.add(d)
        for r in refs:
            r = re.sub(r'\s+', '', str(r or '')).upper()
            if r:
                self.ref.add(r)
        for n in names:
            k = W.name_key(n)
            if k and len(k) > 2:
                self.name.setdefault(k, []).append(ent)

    @staticmethod
    def consistent(rec_nid, rec_masked, rec_dob, ent):
        if rec_nid and ent['nid'] and rec_nid != ent['nid']:
            return False
        if rec_nid and ent['masked'] and not any(rec_nid.endswith(m) or rec_nid.startswith(m) for m in ent['masked']):
            return False
        if rec_masked and ent['nid'] and not (ent['nid'].endswith(rec_masked) or ent['nid'].startswith(rec_masked)):
            return False
        if rec_masked and ent['masked'] and rec_masked not in ent['masked']:
            return False
        if len(rec_dob) == 10 and len(ent['dob']) == 10 and rec_dob != ent['dob']:
            return False
        return True

    def duplicate(self, rec):
        """The reason the record is already screenable, or None."""
        nid = W.valid_nid(rec.get('national_id'))
        if nid and nid in self.nid:
            return 'national_id'
        pp = W.digits(rec.get('passport'))
        if len(pp) >= 6 and pp in self.pp:
            return 'passport'
        for o in rec.get('listings') or []:
            r = re.sub(r'\s+', '', str(o.get('ref') or '')).upper()
            if r and r in self.ref:
                return 'un_reference'
        masked = '' if nid else W.digits(rec.get('national_id')) if '*' in str(rec.get('national_id') or '') else ''
        dob = str(rec.get('dob') or rec.get('_dob_linked') or '')[:10]
        for n in {rec.get('name'), rec.get('name_latin')}:
            for ent in self.name.get(W.name_key(n), []):
                if self.consistent(nid, masked, dob, ent):
                    return 'name'
        return None

    def add_record(self, rec):
        self.add([rec.get('name'), rec.get('name_latin')], [rec.get('national_id') or ''], [rec.get('passport') or ''],
                 rec.get('dob') or rec.get('_dob_linked') or '', [o.get('ref') for o in rec.get('listings') or []])


def screenable_index(conn):
    idx = Screenable()
    c = _cur(conn)
    c.execute("""SELECT original_name, full_name, national_id, passport_number, date_of_birth
                 FROM internal_blacklist WHERE COALESCE(is_active, 1) <> 0""")
    for r in c.fetchall():
        idx.add([r['original_name'], r['full_name']], [r['national_id'] or ''], [r['passport_number'] or ''],
                r['date_of_birth'])
    c.execute("""SELECT full_name, original_name, full_name_arabic, national_id_numbers, passport_numbers, date_of_birth,
                        properties, details
                 FROM screening_watchlist WHERE is_active = 1 AND source = ANY(%s)""", (list(SCREENABLE_SOURCES),))
    for r in c.fetchall():
        refs = []
        for d in (_json_dict(r['properties']), _json_dict(r['details'])):
            refs += [d[k] for k in _REF_KEYS if isinstance(d.get(k), str)]
        idx.add([r['full_name'], r['original_name'], r['full_name_arabic']], _json_list(r['national_id_numbers']),
                _json_list(r['passport_numbers']), r['date_of_birth'], refs)
    return idx


def plan_add_new(conn, parsed, base, include_un=False):
    """Turn a full plan into the add-new-only plan (writes nothing)."""
    idx = screenable_index(conn)
    batch = Screenable()
    items, counts = [], {}

    def bump(cat, k):
        counts.setdefault(cat, {x: 0 for x in ADD_KEYS})[k] += 1
    for it in base['items']:
        rec, ch = it['rec'], it['change']
        cat = rec['category'] if rec else it.get('category')
        if rec is not None and rec['kind'] == 'UN' and ch in ('ADDED', 'ADOPTED') and not include_un:
            bump(cat, 'un_skipped')
            continue
        if ch == 'ADOPTED':
            items.append(dict(it, change='LINK'))
            bump(cat, 'adopted_linked')
        elif ch == 'ADDED':
            if rec['status'] != 'LISTED':
                bump(cat, 'skipped_lifted')
                continue
            why = idx.duplicate(rec) or ('in_workbook' if batch.duplicate(rec) else None)
            if why:
                bump(cat, f'dup_{why}')
                continue
            batch.add_record(rec)
            items.append(it)
            bump(cat, 'new_entities' if rec['entity_type'] == 'ENTITY' else 'new_persons')
        elif ch == 'UNCHANGED':
            items.append(it)
            bump(cat, 'unchanged')
        else:
            bump(cat, 'tracked_changes_not_applied')
    totals = {k: sum(c[k] for c in counts.values()) for k in ADD_KEYS}
    totals['new'] = totals['new_persons'] + totals['new_entities']
    totals['skipped_duplicate'] = sum(totals[f'dup_{r}'] for r in DUP_REASONS)
    totals['records'] = len(parsed['records'])
    totals['added'], totals['adopted'] = totals['new'], totals['adopted_linked']
    totals['changes'] = totals['new'] + totals['adopted_linked']
    blocking = [r for r in base['reasons'] if not any(r.startswith(f"{W.KIND_LABEL.get(s['kind'], s['kind'])} / ")
                                                       for s in base['shrink'])]
    blocking = [r for r in blocking if r in base['blocking']]     # nothing is removed in this mode: no shrink stop
    return dict(base, items=items, counts=counts, totals=totals, mode='add_new_only', blocking=blocking,
                blocked=bool(blocking), include_un=bool(include_un))


def verify_new(conn, import_id, n=10):
    """Screen up to n random names added by an import through the real engine, in Arabic and in the stored Latin
    form; counts only: how many come back as a hit on the added record."""
    c = _cur(conn)
    c.execute("""SELECT b.id, b.source_id, b.original_name, b.full_name FROM local_list_changes ch
                 JOIN internal_blacklist b ON b.id = ch.blacklist_id
                 WHERE ch.import_id = %s AND ch.change = 'ADDED' ORDER BY random() LIMIT %s""", (import_id, n))
    rows = c.fetchall()
    conn.rollback()
    out = {'checked': len(rows), 'arabic_hit': 0, 'arabic_no_hit': 0, 'latin_hit': 0, 'latin_no_hit': 0, 'errors': 0}
    if not rows:
        return out
    from screening.routes import get_engine
    from screening import match_intel as mi
    engine = get_engine()
    try:
        engine.local_engine.metrics.log = lambda *x, **k: None     # a check, not a screening of a customer
    except Exception:
        return dict(out, errors=len(rows), note='screening metrics logging could not be switched off')
    for r in rows:
        for q, k in ((r['original_name'], 'arabic'), (r['full_name'], 'latin')):
            if not q:
                out[f'{k}_no_hit'] += 1
                continue
            try:
                res = engine.screen_person(q, include_media=False)
            except Exception:
                out['errors'] += 1
                continue
            hit = any(str(m.get('source') or '').lower().startswith('internal') and
                      (str(m.get('watchlist_id') or m.get('source_id') or '') == r['source_id'] or
                       str(m.get('entity_id') or '') == str(r['id'])) and
                      float(m.get('match_score') or 0) >= mi.POTENTIAL for m in res.get('matches') or [])
            out[f'{k}_hit' if hit else f'{k}_no_hit'] += 1
    return out


# ----------------------------------------------------------------------------- row building
_TRANSLIT = None


def _latin(name):
    global _TRANSLIT
    if not W.AR.search(name or ''):
        return W.one_line(name).upper()
    if _TRANSLIT is None:
        try:
            from screening.arabic_transliteration_enhanced import prepare_name_for_screening
            _TRANSLIT = prepare_name_for_screening
        except Exception:
            _TRANSLIT = False
    if _TRANSLIT:
        try:
            return _TRANSLIT(name)[0] or name
        except Exception:
            pass
    return name


def _variants(name):
    try:
        from screening.arabic_transliteration_enhanced import generate_all_spelling_variants
        return generate_all_spelling_variants(name) or []
    except Exception:
        return []


def _reason(rec):
    cat = rec['category']
    parts = []
    if rec['kind'] in ('PP_ORDER', 'TERROR_REGISTER'):
        word = 'أمر منع' if rec['kind'] == 'PP_ORDER' else 'قرار إدراج'
        for o in rec['listings'][:6]:
            bits = [f'{word} {o["order"]}' if o.get('order') else '', f'قضية {o["case"]}' if o.get('case') else '',
                    'إنهاء أثر' if o.get('state') == 'LIFTED' else '']
            parts.append(' – '.join(b for b in bits if b))
    elif rec['kind'] == 'UN':
        parts = [f'UN ref. {o["ref"]}' + (f' – listed {o["listed"]}' if o.get('listed') else '')
                 for o in rec['listings'] if o.get('ref')]
    else:
        for o in rec['listings'][:4]:
            bits = [f'قضية {o["case"]}' if o.get('case') else '', o.get('decision') and f'قرار {o["decision"]}' or '',
                    o.get('publication') or '']
            parts.append(' – '.join(b for b in bits if b))
    txt = label(cat) + (': ' + '; '.join(p for p in parts if p) if any(parts) else '')
    return txt[:2000]


def _notes(rec):
    bits = list(rec.get('notes') or [])
    if rec.get('person_type'):
        bits.append(f'نوع الشخص: {rec["person_type"]}')
    if rec.get('occupation'):
        bits.append(f'النشاط / الوظيفة: {rec["occupation"]}')
    if rec.get('owner'):
        bits.append(f'المالك: {rec["owner"]}')
    if rec.get('unified_codes'):
        bits.append('الكود الموحد: ' + ', '.join(rec['unified_codes']))
    if rec.get('aliases_weak'):
        bits.append('Low-quality aliases: ' + '; '.join(rec['aliases_weak']))
    if rec.get('_dob_linked'):
        bits.append('تاريخ الميلاد من الرقم القومي لسجل مطابق في نفس الملف')
    return '\n'.join(bits)[:4000] or None


def row_values(rec, lifted_mode='history'):
    name = rec['name']
    latin = rec.get('name_latin') or _latin(name)
    arabic = name if W.AR.search(name or '') else (rec.get('name_latin') and name) or name
    aliases = []
    for a in [name if latin != name else None] + list(rec.get('aliases') or []) + list(rec.get('aliases_weak') or []):
        if a and a not in aliases and a != latin:
            aliases.append(a)
    if W.AR.search(name or ''):
        low = {a.lower() for a in aliases}
        aliases += [v for v in _variants(name) if v.lower() not in low and v.lower() != latin.lower()][:20]
    lifted = rec['status'] == 'LIFTED'
    return {
        'full_name': latin, 'original_name': arabic, 'entity_type': rec['entity_type'],
        'national_id': rec.get('national_id') or None, 'passport_number': rec.get('passport') or None,
        'date_of_birth': rec.get('dob') or rec.get('_dob_linked') or None, 'place_of_birth': rec.get('pob') or None,
        'nationality': rec.get('nationality') or None, 'registration_number': rec.get('registration') or None,
        'address': rec.get('address') or None, 'country': rec.get('country') or None,
        'reason': _reason(rec), 'risk_level': 'HIGH', 'category': label(rec['category']),
        'aliases': json.dumps(aliases, ensure_ascii=False), 'notes': _notes(rec),
        'legal_status': 'LIFTED' if lifted else None,
        'legal_status_note': (rec.get('lift_note') or 'إنهاء أثر') if lifted else None,
        'legal_status_date': (rec.get('lifted_on') or None) if lifted else None,
        'is_active': 0 if (lifted and lifted_mode == 'inactive') else 1,
        'confirmation_type': CONFIRMATION,
    }


_COLS = ('full_name', 'original_name', 'entity_type', 'national_id', 'passport_number', 'date_of_birth',
         'place_of_birth', 'nationality', 'registration_number', 'address', 'country', 'reason', 'risk_level',
         'category', 'aliases', 'notes', 'legal_status', 'legal_status_note', 'legal_status_date', 'is_active',
         'confirmation_type')


def _source_id(key):
    kind, h = key.split(':', 1)
    return f'IBL-LL-{kind}-{h[:16].upper()}'


# ----------------------------------------------------------------------------- apply
def _audit_bl(c, bid, action, fields, user_id, reason, now):
    c.execute("""INSERT INTO internal_blacklist_audit (blacklist_id, action, field_changed, old_value, new_value,
                                                        changed_by, reason, changed_at)
                 VALUES (%s, %s, %s, NULL, NULL, %s, %s, %s)""",
              (bid, action, ','.join(fields)[:500] if fields else None, user_id, reason, now))


def record_blocked(conn, parsed, pl, file_name, sha, user_id=None, trigger='cli', allow_shrink=False):
    c = _cur(conn)
    c.execute("""INSERT INTO local_list_imports (status, trigger, triggered_by, finished_at, file_name, file_sha256,
                     content_sha256, edition_date, allow_shrink, sheets, counts, totals, reason)
                 VALUES ('BLOCKED', %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
              (trigger, user_id, file_name, sha, pl['content_sha'], parsed.get('date'), allow_shrink,
               json.dumps(parsed['sheets'], ensure_ascii=False), json.dumps(pl['counts']),
               json.dumps(pl['totals']), '; '.join(pl['reasons'])[:2000]))
    vid = c.fetchone()['id']
    conn.commit()
    try:
        from screening import list_versions as LV
        LV.alert(conn, 'local_lists', 'blocked', 'Local lists import blocked',
                 'The local negative-lists workbook was not imported: ' + '; '.join(pl['blocking'])[:600] +
                 '. The lists in force stay. If the change is genuine, import again with the shrink allowed.',
                 force=True)
    except Exception as e:
        logger.warning('could not alert on the blocked local lists import: %s', e)
    return vid


def apply(conn, parsed, pl, file_name, sha, user_id=None, trigger='cli', allow_shrink=False,
          lifted_mode='history', retire_legacy=False, commit=True):
    """Write the plan in ONE transaction. Returns the import id. Raises ImportBusy when another import runs."""
    if pl['blocked']:
        raise ValueError('the plan is blocked: ' + '; '.join(pl['blocking']))
    c = _cur(conn)
    c.execute("SET LOCAL lock_timeout = '10s'")
    c.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s)) AS ok", (LOCK,))
    if not c.fetchone()['ok']:
        conn.rollback()
        raise ImportBusy('another local lists import is running')
    # the state may have moved since plan(): re-plan inside the lock
    cur_prev = previous_state(conn)
    if pl.get('_prev_sig') is not None and \
            {k: (p['status'], p['content_sha256']) for k, p in cur_prev.items()} != pl['_prev_sig']:
        conn.rollback()
        raise ValueError('the lists changed since the preview; run the preview again')
    now = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tenant_col = _has_col(conn, 'internal_blacklist', 'tenant_id')
    c.execute("""INSERT INTO local_list_imports (status, trigger, triggered_by, file_name, file_sha256, content_sha256,
                     edition_date, allow_shrink, sheets)
                 VALUES ('RUNNING', %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
              (trigger, user_id, file_name, sha, pl['content_sha'], parsed.get('date'), allow_shrink,
               json.dumps(parsed['sheets'], ensure_ascii=False)))
    vid = c.fetchone()['id']
    why = f'Local lists import #{vid}'
    unchanged = []
    written = {ch: 0 for ch in CHANGES}
    for it in pl['items']:
        ch, key, rec = it['change'], it['key'], it['rec']
        if ch == 'UNCHANGED':
            unchanged.append(key)
            continue
        if ch == 'LINK':        # add-new-only: an existing row is tied to its identity, its content is not touched
            prov = {'sheet': rec.get('_sheet'), 'rows': (rec.get('_rows') or [])[:50], 'import': vid, 'linked_only': True}
            c.execute("""INSERT INTO local_list_records (record_key, kind, category, status, blacklist_id,
                             content_sha256, content, provenance, first_import, last_import, last_change_import)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (record_key) DO NOTHING""",
                      (key, rec['kind'], rec['category'], rec['status'], it['blacklist_id'], it['sha'],
                       json.dumps(W.content_of(rec), ensure_ascii=False), json.dumps(prov, ensure_ascii=False),
                       vid, vid, vid))
            c.execute("""INSERT INTO local_list_changes (import_id, record_key, category, change, blacklist_id,
                             old_status, new_status, fields) VALUES (%s, %s, %s, 'ADOPTED', %s, NULL, %s, %s)""",
                      (vid, key, rec['category'], it['blacklist_id'], rec['status'], json.dumps(['linked_only'])))
            written['ADOPTED'] += 1
            continue
        if ch == 'REMOVED':
            if it['blacklist_id']:
                c.execute("""UPDATE internal_blacklist SET is_active = 0, modified_by = %s, modified_date = %s,
                                 updated_at = %s,
                                 legal_status_note = COALESCE(legal_status_note || ' | ', '') || %s
                             WHERE id = %s""",
                          (user_id, now, now, f'لم يعد في ملف القوائم المحلية (استيراد {vid}) / no longer in the '
                                              f'local lists workbook (import {vid})', it['blacklist_id']))
                _audit_bl(c, it['blacklist_id'], 'DEACTIVATED', [], user_id, why, now)
            c.execute("""UPDATE local_list_records SET status = 'REMOVED', last_change_import = %s, updated_at = now()
                         WHERE record_key = %s""", (vid, key))
            c.execute("""INSERT INTO local_list_changes (import_id, record_key, category, change, blacklist_id,
                             old_status, new_status) VALUES (%s, %s, %s, 'REMOVED', %s, %s, 'REMOVED')""",
                      (vid, key, it['category'], it['blacklist_id'], it['old_status']))
            written['REMOVED'] += 1
            continue
        vals = row_values(rec, lifted_mode)
        bid = it['blacklist_id']
        if bid:
            sets = ', '.join(f'{k} = %s' for k in _COLS)
            c.execute(f"""UPDATE internal_blacklist SET {sets}, modified_by = %s, modified_date = %s, updated_at = %s
                          {', source = %s' if ch == 'ADOPTED' else ''}
                          WHERE id = %s""",
                      [vals[k] for k in _COLS] + [user_id, now, now] + ([SOURCE] if ch == 'ADOPTED' else []) + [bid])
            if c.rowcount == 0:
                bid = None          # the row was deleted by hand: write it again
        if not bid:
            cols = list(_COLS) + ['source', 'source_id', 'added_by', 'added_date', 'created_at', 'updated_at']
            args = [vals[k] for k in _COLS] + [SOURCE, _source_id(key), user_id, now, now, now]
            if tenant_col:
                try:
                    from database.tenancy import DEFAULT_TENANT
                    cols.append('tenant_id')
                    args.append(int(os.getenv('LOCAL_LISTS_TENANT') or DEFAULT_TENANT))
                except Exception:
                    pass
            c.execute(f"""INSERT INTO internal_blacklist ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})
                          ON CONFLICT (source_id) DO UPDATE SET
                          {', '.join(f'{k} = EXCLUDED.{k}' for k in _COLS)}, updated_at = EXCLUDED.updated_at
                          RETURNING id""", args)
            bid = c.fetchone()['id']
        action = {'ADDED': 'ADDED', 'ADOPTED': 'UPDATED', 'CHANGED': 'UPDATED', 'LIFTED': 'LIFTED',
                  'RELISTED': 'ACTIVATED'}[ch]
        _audit_bl(c, bid, action, it.get('fields') or [], user_id, why, now)
        prov = {'sheet': rec.get('_sheet'), 'rows': (rec.get('_rows') or [])[:50], 'import': vid}
        c.execute("""INSERT INTO local_list_records (record_key, kind, category, status, blacklist_id, content_sha256,
                         content, provenance, first_import, last_import, last_change_import)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                     ON CONFLICT (record_key) DO UPDATE SET kind = EXCLUDED.kind, category = EXCLUDED.category,
                         status = EXCLUDED.status, blacklist_id = EXCLUDED.blacklist_id,
                         content_sha256 = EXCLUDED.content_sha256, content = EXCLUDED.content,
                         provenance = EXCLUDED.provenance, last_import = EXCLUDED.last_import,
                         last_change_import = EXCLUDED.last_change_import, updated_at = now()""",
                  (key, rec['kind'], rec['category'], rec['status'], bid, it['sha'],
                   json.dumps(W.content_of(rec), ensure_ascii=False), json.dumps(prov, ensure_ascii=False),
                   vid, vid, vid))
        c.execute("""INSERT INTO local_list_changes (import_id, record_key, category, change, blacklist_id, old_status,
                         new_status, fields) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                  (vid, key, rec['category'], ch, bid, it.get('old_status'), rec['status'],
                   json.dumps(it.get('fields') or [])))
        written[ch] += 1
    if unchanged:
        c.execute("UPDATE local_list_records SET last_import = %s WHERE record_key = ANY(%s)", (vid, unchanged))
    retired = 0
    if retire_legacy:
        retired = _retire_legacy(c, pl, vid, user_id, now, why)
    totals = dict(pl['totals'], retired_legacy=retired)
    c.execute("""UPDATE local_list_imports SET status = 'APPLIED', finished_at = now(), counts = %s, totals = %s
                 WHERE id = %s""", (json.dumps(pl['counts']), json.dumps(totals), vid))
    c.execute("""INSERT INTO audit_logs (user_id, action, module, item_id, details, ip_address, created_at)
                 VALUES (%s, %s, 'Screening', %s, %s, NULL, %s)""",
              (user_id, 'Local lists workbook imported', vid,
               f'import {vid}: ' + ', '.join(f'{k} {v}' for k, v in written.items()) +
               f', unchanged {len(unchanged)}' + (f', legacy rows retired {retired}' if retired else ''), now))
    if commit:
        conn.commit()
    return vid


def _retire_legacy(c, pl, vid, user_id, now, why):
    """Deactivate untracked internal-list rows of the same families that the workbook no longer backs."""
    claimed = set(pl.get('claimed_legacy') or [])
    c.execute("""SELECT id, category, source FROM internal_blacklist
                 WHERE COALESCE(source, '') <> %s AND COALESCE(is_active, 1) <> 0
                   AND id NOT IN (SELECT blacklist_id FROM local_list_records WHERE blacklist_id IS NOT NULL)""",
              (SOURCE,))
    ids = [r['id'] for r in c.fetchall() if r['id'] not in claimed and
           (_family(r['category']) or str(r['source'] or '').upper() == 'INTERNAL_BULK_UPLOAD')]
    for i in ids:
        c.execute("""UPDATE internal_blacklist SET is_active = 0, modified_by = %s, modified_date = %s, updated_at = %s,
                         notes = COALESCE(notes || E'\n', '') || %s WHERE id = %s""",
                  (user_id, now, now, f'Retired by local lists import {vid}: not in the official workbook', i))
        _audit_bl(c, i, 'DEACTIVATED', [], user_id, why + ' (legacy row not in the workbook)', now)
        c.execute("""INSERT INTO local_list_changes (import_id, record_key, category, change, blacklist_id,
                         old_status, new_status) VALUES (%s, %s, 'LEGACY', 'RETIRED', %s, 'LISTED', 'REMOVED')""",
                  (vid, f'legacy:{i}', i))
    return len(ids)


def fail(conn, parsed, pl, file_name, sha, error, user_id=None, trigger='cli'):
    try:
        conn.rollback()
        c = _cur(conn)
        c.execute("""INSERT INTO local_list_imports (status, trigger, triggered_by, finished_at, file_name, file_sha256,
                         edition_date, sheets, reason) VALUES ('FAILED', %s, %s, now(), %s, %s, %s, %s, %s)""",
                  (trigger, user_id, file_name, sha, (parsed or {}).get('date'),
                   json.dumps((parsed or {}).get('sheets') or [], ensure_ascii=False), str(error)[:1000]))
        conn.commit()
    except Exception as e:
        logger.error('could not record the failed local lists import: %s', e)


# ----------------------------------------------------------------------------- after the commit
def post_sync(link=True):
    """The same steps as after other list updates: internal lists -> screening_watchlist, the search index
    (only where this process may write it), and the EMLCU <-> Public Prosecution date-of-birth link."""
    out = {}
    py = sys.executable
    steps = [('internal_sync', [py, os.path.join(BASE, 'scripts', 'sync_internal_to_watchlist.py')])]
    if link:
        steps.append(('emlcu_link', [py, os.path.join(BASE, 'scripts', 'link_emlcu_internal.py'), '--apply']))
    for name, cmd in steps:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=BASE)
            out[name] = 'ok' if r.returncode == 0 else f'failed (rc={r.returncode})'
        except Exception as e:
            out[name] = f'failed ({e.__class__.__name__})'
    try:
        from utils.demo import is_demo
        demo = is_demo()
    except Exception:
        demo = False
    ok, why = False, 'demo instance'
    if not demo:
        try:
            from screening.es_client import es_write_allowed
            ok, why = es_write_allowed()
        except Exception as e:
            ok, why = False, str(e)
    if ok:
        try:
            r = subprocess.run([py, os.path.join(BASE, 'scripts', 'es_incremental_sync.py')], capture_output=True,
                               text=True, timeout=1800, cwd=BASE)
            out['search_index'] = 'ok' if r.returncode == 0 else f'failed (rc={r.returncode})'
        except Exception as e:
            out['search_index'] = f'failed ({e.__class__.__name__})'
    else:
        out['search_index'] = f'skipped ({why})'
    return out


# ----------------------------------------------------------------------------- one call
def run(conn, path, do_apply=False, user_id=None, trigger='cli', allow_shrink=False, allow_unknown=False,
        shrink_pct=SHRINK_PCT, shrink_min=SHRINK_MIN, lifted_mode='history', retire_legacy=False,
        adopt_legacy=True, sync=True, file_name=None, commit=True, add_new_only=False, include_un=False,
        verify=10):
    """Parse, plan and (when do_apply) write. Returns a summary made of counts only (no names).
    add_new_only: existing rows are only linked, lifted and already-screenable records are not added, UN
    sheets are skipped unless include_un; after the import `verify` added names are screened (counts)."""
    parsed = W.parse(path)
    linked = link_masked_dobs(parsed['records'])
    sha = file_sha256(path)
    pl = plan(conn, parsed, allow_shrink=allow_shrink, allow_unknown=allow_unknown, shrink_pct=shrink_pct,
              shrink_min=shrink_min, adopt_legacy=adopt_legacy)
    if add_new_only:
        pl = plan_add_new(conn, parsed, pl, include_un=include_un)
        retire_legacy = False
    conn.rollback()
    out = summary(parsed, pl)
    out['mode'] = 'add_new_only' if add_new_only else 'full'
    out['dob_linked'] = linked
    out['file_sha256'] = sha
    if not do_apply:
        out['result'] = 'DRY_RUN'
        return out
    name = file_name or os.path.basename(path)
    if pl['blocked']:
        out['import_id'] = record_blocked(conn, parsed, pl, name, sha, user_id, trigger, allow_shrink)
        out['result'] = 'BLOCKED'
        return out
    try:
        vid = apply(conn, parsed, pl, name, sha, user_id=user_id, trigger=trigger, allow_shrink=allow_shrink,
                    lifted_mode=lifted_mode, retire_legacy=retire_legacy, commit=commit)
    except ImportBusy:
        raise
    except Exception as e:
        logger.exception('local lists import failed')
        if commit:
            fail(conn, parsed, pl, name, sha, e, user_id, trigger)
        raise
    out['import_id'] = vid
    out['result'] = 'APPLIED'
    if sync and commit and pl['totals']['changes']:
        out['sync'] = post_sync()
        if add_new_only and verify and pl['totals'].get('new'):
            try:
                out['verify'] = verify_new(conn, vid, verify)
            except Exception as e:
                logger.warning('verification screening failed: %s', e)
                out['verify'] = {'errors': 1, 'note': e.__class__.__name__}
    return out


def summary(parsed, pl):
    """Counts only: per sheet (kind, category), per category and change type. Sheet names are internal."""
    return {
        'edition_date': parsed.get('date'),
        'sheets': parsed['sheets'],
        'counts': pl['counts'],
        'totals': pl['totals'],
        'blocked': pl['blocked'],
        'reasons': pl['reasons'],
        'blocking': pl['blocking'],
        'legacy_unmatched': pl['legacy_unmatched'],
        'unknown_sheets': pl['unknown_sheets'],
    }


def history(conn, limit=30):
    c = _cur(conn)
    c.execute("""SELECT i.id, i.status, i.trigger, i.started_at, i.finished_at, i.file_name, i.edition_date,
                        i.allow_shrink, i.totals, i.counts, i.sheets, i.reason, u.email AS user_email
                 FROM local_list_imports i LEFT JOIN users u ON u.id = i.triggered_by
                 ORDER BY i.id DESC LIMIT %s""", (limit,))
    return c.fetchall()


def in_force(conn):
    """Records per category and status (what screening uses now)."""
    c = _cur(conn)
    c.execute("""SELECT category, status, count(*) AS n FROM local_list_records GROUP BY 1, 2""")
    out = {}
    for r in c.fetchall():
        out.setdefault(r['category'], {'LISTED': 0, 'LIFTED': 0, 'REMOVED': 0})[r['status']] = r['n']
    return [{'code': k, 'label_en': label(k, 'en'), 'label_ar': label(k, 'ar'), **out[k]}
            for k in CATEGORIES if k in out]
