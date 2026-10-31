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
"""Screening work reports (P4-10) and hit breakdown by list / country (G11).

Every function takes ``q(sql, params) -> list[dict]`` so the aggregation can be
tested without a database. Periods are [date_from, date_to] inclusive, as
'YYYY-MM-DD' strings. Text dates (screening_history.screening_date,
screening_queue.resolved_date) are ISO 'YYYY-MM-DD HH:MM:SS', so string
comparison is a date comparison; timestamp columns use real comparisons.
Rows are aggregated in Python: the inputs are small per period and malformed
legacy values (empty strings, odd date formats) must never break the page.
"""
import io
import json
import re
from datetime import date, datetime, timedelta

_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


# ---------------------------------------------------------------------------- period
def period(date_from=None, date_to=None, default_days=30, today=None):
    """(from, to, to_exclusive) as 'YYYY-MM-DD'; bad or missing input -> last N days."""
    today = today or date.today()
    dt = _parse_day(date_to) or today
    df = _parse_day(date_from) or (dt - timedelta(days=default_days - 1))
    if df > dt:
        df, dt = dt, df
    if (dt - df).days > 366 * 3:
        df = dt - timedelta(days=366 * 3)
    return df.isoformat(), dt.isoformat(), (dt + timedelta(days=1)).isoformat()


def _parse_day(v):
    v = (v or '').strip()
    if not _DATE.match(v):
        return None
    try:
        return datetime.strptime(v, '%Y-%m-%d').date()
    except ValueError:
        return None


def _ts(v):
    """datetime from a timestamp or an ISO-ish text; None when unreadable."""
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v).strip().replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    return None


def _hours(a, b):
    a, b = _ts(a), _ts(b)
    if not a or not b:
        return None
    h = (b - a).total_seconds() / 3600.0
    return h if h >= 0 else None


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _is_tm(resolution):
    r = (resolution or '').strip().lower()
    return r.startswith('true match') or r.startswith('pep')


def _is_fp(resolution):
    return (resolution or '').strip().lower().startswith('false positive')


# ---------------------------------------------------------------------------- P4-10
def _blank(uid):
    return {'user_id': uid, 'name': '', 'email': '',
            'screenings': 0, 'incomplete': 0, 'rescreens': 0,
            'hits_handled': 0, 'true_matches': 0, 'false_positives': 0, 'bulk_resolved': 0,
            'hit_hours': [], 'hits_overdue': 0,
            'proposed': 0, 'proposed_approved': 0, 'proposed_rejected': 0, 'proposed_pending': 0,
            'proposed_pending_overdue': 0,
            'decided': 0, 'approved': 0, 'rejected': 0, 'decision_hours': [], 'decided_overdue': 0,
            'evidence_packs': 0}


def user_stats(q, date_from, date_to_excl, sla_hours=24.0, user_id=None, now=None):
    """Per-user work in the period. user_id limits every figure to that user (analyst view)."""
    now = now or datetime.now()
    users = {}

    def u(uid):
        if uid is None:
            return None
        return users.setdefault(int(uid), _blank(int(uid)))

    only = " AND {col} = %s" if user_id is not None else ""
    p_extra = (int(user_id),) if user_id is not None else ()

    # screenings run; a re-screen = an earlier screening of the same name exists (any user)
    rows = q("""SELECT h.initiated_by AS uid, h.screening_result AS res,
                       EXISTS (SELECT 1 FROM screening_history p
                                WHERE lower(btrim(p.entity_name)) = lower(btrim(h.entity_name))
                                  AND p.id < h.id) AS again
                  FROM screening_history h
                 WHERE ((h.screening_date >= %s AND h.screening_date < %s)
                        OR (NULLIF(h.screening_date, '') IS NULL
                            AND h.created_at >= %s::date AND h.created_at < %s::date))"""
             + only.format(col='h.initiated_by'), (date_from, date_to_excl, date_from, date_to_excl) + p_extra)
    for r in rows:
        x = u(r.get('uid'))
        if x is None:
            continue
        x['screenings'] += 1
        if (r.get('res') or '').upper() == 'INCOMPLETE':
            x['incomplete'] += 1
        if r.get('again'):
            x['rescreens'] += 1

    # hits handled in the review queue (resolved in the period)
    rows = q("""SELECT q.resolved_by AS uid, q.resolution, q.created_at, q.resolved_date
                  FROM screening_queue q
                 WHERE q.resolved_by IS NOT NULL
                   AND NULLIF(q.resolved_date, '') >= %s AND NULLIF(q.resolved_date, '') < %s"""
             + only.format(col='q.resolved_by'), (date_from, date_to_excl) + p_extra)
    for r in rows:
        x = u(r.get('uid'))
        if x is None:
            continue
        x['hits_handled'] += 1
        res = r.get('resolution')
        if _is_tm(res):
            x['true_matches'] += 1
        elif _is_fp(res):
            x['false_positives'] += 1
        if '(bulk)' in (res or '').lower():
            x['bulk_resolved'] += 1
        h = _hours(r.get('created_at'), r.get('resolved_date'))
        x['hit_hours'].append(h)
        if h is not None and h > sla_hours:
            x['hits_overdue'] += 1

    # clearances proposed (maker)
    rows = q("""SELECT r.requested_by AS uid, r.status, r.requested_at
                  FROM screening_clearance_requests r
                 WHERE r.requested_at >= %s::date AND r.requested_at < %s::date"""
             + only.format(col='r.requested_by'), (date_from, date_to_excl) + p_extra)
    for r in rows:
        x = u(r.get('uid'))
        if x is None:
            continue
        x['proposed'] += 1
        st = (r.get('status') or '').lower()
        if st == 'approved':
            x['proposed_approved'] += 1
        elif st == 'rejected':
            x['proposed_rejected'] += 1        # four-eyes override of this maker's proposal
        elif st == 'pending':
            x['proposed_pending'] += 1
            h = _hours(r.get('requested_at'), now)
            if h is not None and h > sla_hours:
                x['proposed_pending_overdue'] += 1

    # clearances decided (checker)
    rows = q("""SELECT r.decided_by AS uid, r.status, r.requested_at, r.decided_at
                  FROM screening_clearance_requests r
                 WHERE r.decided_by IS NOT NULL
                   AND r.decided_at >= %s::date AND r.decided_at < %s::date"""
             + only.format(col='r.decided_by'), (date_from, date_to_excl) + p_extra)
    for r in rows:
        x = u(r.get('uid'))
        if x is None:
            continue
        x['decided'] += 1
        st = (r.get('status') or '').lower()
        if st == 'approved':
            x['approved'] += 1
        elif st == 'rejected':
            x['rejected'] += 1
        h = _hours(r.get('requested_at'), r.get('decided_at'))
        x['decision_hours'].append(h)
        if h is not None and h > sla_hours:
            x['decided_overdue'] += 1

    # evidence packs issued
    rows = q("""SELECT e.generated_by AS uid, count(*) AS n
                  FROM screening_evidence_packs e
                 WHERE e.generated_at >= %s::date AND e.generated_at < %s::date"""
             + only.format(col='e.generated_by') + " GROUP BY e.generated_by",
             (date_from, date_to_excl) + p_extra)
    for r in rows:
        x = u(r.get('uid'))
        if x is not None:
            x['evidence_packs'] += int(r.get('n') or 0)

    if user_id is not None:
        u(user_id)          # an analyst always sees a row for themselves, even if empty
    if users:
        names = q("""SELECT id, TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS name, email
                       FROM users WHERE id = ANY(%s)""", (sorted(users),))
        for n in names:
            x = users.get(int(n['id']))
            if x is not None:
                x['name'] = (n.get('name') or '').strip() or (n.get('email') or '')
                x['email'] = n.get('email') or ''
    out = []
    for x in users.values():
        x['avg_hit_hours'] = _avg(x.pop('hit_hours'))
        x['avg_decision_hours'] = _avg(x.pop('decision_hours'))
        x['name'] = x['name'] or ('#%d' % x['user_id'])
        decided_own = x['proposed_approved'] + x['proposed_rejected']
        x['override_rate'] = round(100.0 * x['proposed_rejected'] / decided_own, 1) if decided_own else None
        out.append(x)
    out.sort(key=lambda r: (-(r['screenings'] + r['hits_handled'] + r['decided']), r['name'].lower()))
    return out


def totals(rows):
    keys = ('screenings', 'incomplete', 'rescreens', 'hits_handled', 'true_matches', 'false_positives',
            'bulk_resolved', 'hits_overdue', 'proposed', 'proposed_approved', 'proposed_rejected',
            'proposed_pending', 'proposed_pending_overdue', 'decided', 'approved', 'rejected',
            'decided_overdue', 'evidence_packs')
    return {k: sum(r.get(k) or 0 for r in rows) for k in keys}


# ---------------------------------------------------------------------------- G11
def _json(v):
    if isinstance(v, dict):
        return v
    if not v or not isinstance(v, str) or not v.lstrip().startswith('{'):
        return {}
    try:
        d = json.loads(v)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


_SRC_ALIASES = {'un list': 'un', 'un': 'un', 'hmt_uk_sanctions': 'uk', 'hmt': 'uk', 'eu': 'eu',
                'internal_blacklist': 'internal_blacklist', 'internal_pep': 'internal_pep'}


def norm_source(s):
    k = re.sub(r'\s+', ' ', str(s or '').strip().lower())
    return _SRC_ALIASES.get(k, k) or 'unknown'


def category(md, source):
    """List category for a hit: the OpenSanctions category, else the kind of local list."""
    try:
        from screening import list_category as LC
        m = dict(md)
        m.setdefault('source', source)
        code = LC.for_match(m)
        if code:
            return code
    except Exception:
        pass
    src = norm_source(source)
    if src in ('internal_blacklist', 'emlcu', 'pma_ps'):
        return 'LOCAL_LIST'
    if src == 'internal_pep':
        return 'PEP'
    if src.endswith('_reg'):
        return 'REGULATORY'
    lt = str(md.get('list_type') or '').upper()
    if 'PEP' in lt or 'POLITICALLY' in lt:
        return 'PEP'
    return 'SANCTIONS'


def _countries(*vals):
    try:
        from screening.country_codes import to_iso2
        c = to_iso2(*vals)
    except Exception:
        c = set()
    return sorted({str(x).upper() for x in c}) or ['—']


def _bucket():
    return {'hits': 0, 'true_matches': 0, 'false_positives': 0, 'pending': 0}


def _add(b, resolution, pending):
    b['hits'] += 1
    if pending:
        b['pending'] += 1
    elif _is_tm(resolution):
        b['true_matches'] += 1
    elif _is_fp(resolution):
        b['false_positives'] += 1


def _finish(d, label_key):
    out = []
    for k, b in d.items():
        decided = b['true_matches'] + b['false_positives']
        b['fp_rate'] = round(100.0 * b['false_positives'] / decided, 1) if decided else None
        b[label_key] = k
        out.append(b)
    out.sort(key=lambda r: (-r['hits'], str(r[label_key])))
    return out


def list_breakdown(q, date_from, date_to_excl):
    """Hits raised in the period by list, list category, customer country and listed country."""
    rows = q("""SELECT q.list_source, q.status, q.resolution, q.match_details,
                       h.source_module, h.source_record_id, r.match_details AS result_details
                  FROM screening_queue q
                  LEFT JOIN screening_history h ON h.id = q.screening_history_id
                  LEFT JOIN screening_results r ON r.id = h.screening_result_id
                 WHERE q.created_at >= %s::date AND q.created_at < %s::date""",
             (date_from, date_to_excl))
    # customer nationality kept on the customer record (Customer KYC screenings)
    cust_ids = sorted({int(r['source_record_id']) for r in rows
                       if r.get('source_record_id') and (r.get('source_module') or '') == 'Customer KYC'})
    cust_nat = {}
    if cust_ids:
        try:
            for c in q("SELECT id, nationality FROM customers WHERE id = ANY(%s)", (cust_ids,)):
                cust_nat[int(c['id'])] = c.get('nationality')
        except Exception:
            cust_nat = {}
    by_list, by_cat, by_cc, by_lc = {}, {}, {}, {}
    sources = {}
    for r in rows:
        md = _json(r.get('match_details'))
        res = r.get('resolution')
        pending = (r.get('status') or '').lower() != 'resolved' or not (res or '').strip()
        raw_src = r.get('list_source') or md.get('source') or ''
        src = norm_source(raw_src)
        sources.setdefault(src, raw_src)
        _add(by_list.setdefault(src, _bucket()), res, pending)
        _add(by_cat.setdefault(category(md, raw_src), _bucket()), res, pending)
        inputs = _json(r.get('result_details')).get('inputs') or {}
        nat = inputs.get('nationality') if isinstance(inputs, dict) else None
        if not nat and r.get('source_record_id') and (r.get('source_module') or '') == 'Customer KYC':
            nat = cust_nat.get(int(r['source_record_id']))
        for cc in _countries(nat):
            _add(by_cc.setdefault(cc, _bucket()), res, pending)
        for lc in _countries(md.get('nationality'), md.get('countries'), md.get('country')):
            _add(by_lc.setdefault(lc, _bucket()), res, pending)
    out_list = _finish(by_list, 'list')
    for b in out_list:
        b['raw_source'] = sources.get(b['list'], b['list'])
    return {'by_list': out_list,
            'by_category': _finish(by_cat, 'category'),
            'by_customer_country': _finish(by_cc, 'country'),
            'by_listed_country': _finish(by_lc, 'country'),
            'total': len(rows)}


# ---------------------------------------------------------------------------- Excel
USER_COLUMNS = [
    ('name', 'Analyst / MLRO'), ('screenings', 'Screenings run'), ('incomplete', 'Incomplete'),
    ('rescreens', 'Re-screens'), ('hits_handled', 'Hits handled'), ('true_matches', 'True matches'),
    ('false_positives', 'False positives'), ('bulk_resolved', 'Bulk-resolved'),
    ('avg_hit_hours', 'Avg hours to resolve a hit'), ('hits_overdue', 'Hits resolved after SLA'),
    ('proposed', 'Clearances proposed'), ('proposed_approved', 'Proposals approved'),
    ('proposed_rejected', 'Proposals overridden (four eyes)'), ('override_rate', 'Override rate (%)'),
    ('proposed_pending', 'Proposals pending'), ('proposed_pending_overdue', 'Pending past SLA'),
    ('decided', 'Clearances decided'), ('approved', 'Approved'), ('rejected', 'Rejected'),
    ('avg_decision_hours', 'Avg hours to decide'), ('decided_overdue', 'Decided after SLA'),
    ('evidence_packs', 'Evidence packs issued'),
]
BREAKDOWN_COLUMNS = [('hits', 'Hits'), ('true_matches', 'True matches'), ('false_positives', 'False positives'),
                     ('pending', 'Pending'), ('fp_rate', 'False-positive rate (%)')]


def workbook(users=None, breakdown=None, meta=None, tr=None):
    """xlsx bytes. tr(text) translates headers (gettext) when given."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    tr = tr or (lambda s: s)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Info'
    for k, v in (meta or {}).items():
        ws.append([tr(k), str(v)])
    bold = Font(bold=True)

    def sheet(title, cols, rows):
        s = wb.create_sheet(title[:31])
        s.append([tr(h) for _, h in cols])
        for c in s[1]:
            c.font = bold
        for r in rows:
            s.append([_cell(r.get(k)) for k, _ in cols])
        for i, (_, h) in enumerate(cols, start=1):
            s.column_dimensions[s.cell(row=1, column=i).column_letter].width = max(12, min(40, len(tr(h)) + 2))

    if users is not None:
        sheet('Users', USER_COLUMNS, users)
    if breakdown:
        sheet('By list', [('list', 'List')] + BREAKDOWN_COLUMNS, breakdown.get('by_list') or [])
        sheet('By category', [('category', 'List category')] + BREAKDOWN_COLUMNS, breakdown.get('by_category') or [])
        sheet('By customer country', [('country', 'Customer country')] + BREAKDOWN_COLUMNS,
              breakdown.get('by_customer_country') or [])
        sheet('By listed country', [('country', 'Listed country')] + BREAKDOWN_COLUMNS,
              breakdown.get('by_listed_country') or [])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell(v):
    if v is None:
        return ''
    if isinstance(v, (int, float)):
        return v
    s = str(v)
    # spreadsheet formula injection: a cell must never start with = + - @
    return "'" + s if s[:1] in ('=', '+', '-', '@') else s
