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
One STR register.

suspicious_activities (SARs) is the single register of suspicion cases, whatever
raised them: a TM alert, a screening hit, an employee's internal report, a manual
entry, or another module's detection (the old unusual-transactions register,
aml_unusual_transactions, which stays and is kept in step with its case).

Each case links to the alerts and transactions behind it (aml_sar_links, many to
many; a removed link is kept with who/when/why). The statutory deadline is a
configurable number of days counted from the detection date or from the MLRO's
decision date (regulatory parameter `aml.str_filing_deadline_days` when a pack
defines it, otherwise the local settings below) — no regulator logic in code.

Status changes go through ONE function each (create_case, assign_case,
record_investigation, record_decision, record_filing); every one of them ends in
on_status_change(), the single place to hook a central case-tracking sync.
"""

import os
from datetime import date, datetime, timedelta

from database.db import get_db


def N_(s):
    """Mark a message for translation (translated where it is shown)."""
    return s


class StrError(ValueError):
    pass


# ------------------------------------------------------------------ labels
SOURCES = [  # code, EN, AR
    ('tm_alert', N_('TM alert'), 'تنبيه مراقبة المعاملات'),
    ('screening', N_('Screening hit'), 'نتيجة فحص القوائم'),
    ('employee_report', N_('Employee report'), 'بلاغ داخلي من موظف'),
    ('manual', N_('Manual entry'), 'إدخال يدوي'),
    ('system', N_('Detected by another module'), 'رصد آلي من وحدة أخرى'),
]
SOURCE_CODES = tuple(c for c, _e, _a in SOURCES)

STATUSES = [  # code, EN, AR
    ('NEW', 'New', 'جديد'),
    ('UNDER_INVESTIGATION', 'Under investigation', 'قيد الفحص'),
    ('PENDING_DECISION', 'Waiting for the MLRO decision', 'بانتظار قرار مسؤول الإبلاغ'),
    ('NO_STR', 'Closed — no report to the unit', 'مغلق — لا يُرفع إخطار'),
    ('FILE_SAR', 'Decided — report to the unit', 'تقرر إخطار الوحدة'),
    ('FILED', 'Filed with the unit', 'تم الإخطار للوحدة'),
]
# values written by older code / seeds, shown with a proper label
LEGACY_LABELS = {
    'CLOSED': ('Closed', 'مغلق'),
    'NO_SAR': ('Closed — no report to the unit', 'مغلق — لا يُرفع إخطار'),
}
CLOSED_STATUSES = ('NO_STR', 'FILED', 'CLOSED')
DECISIONS = ('FILE_SAR', 'NO_STR')

LINK_TYPES = [  # code, EN, AR
    ('tm_alert', N_('TM alert'), 'تنبيه مراقبة المعاملات'),
    ('screening_alert', N_('Screening alert'), 'تنبيه فحص القوائم'),
    ('transaction', N_('Transaction'), 'معاملة'),
]
LINK_CODES = tuple(c for c, _e, _a in LINK_TYPES)


def labels(pairs, ar=False):
    out = {c: (a if ar else e) for c, e, a in pairs}
    return out


def status_labels(ar=False):
    out = labels(STATUSES, ar)
    for code, (en, a) in LEGACY_LABELS.items():
        out.setdefault(code, a if ar else en)
    return out


def source_labels(ar=False):
    return labels(SOURCES, ar)


def link_labels(ar=False):
    return labels(LINK_TYPES, ar)


# ------------------------------------------------------------------ deadline (pure)
DEADLINE_PARAM = 'aml.str_filing_deadline_days'
DEADLINE_DAYS_KEY = 'aml_str_deadline_days'
DEADLINE_BASIS_KEY = 'aml_str_deadline_basis'
DEADLINE_BASES = ('detection', 'decision')


def parse_date(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def case_deadline(case, days, basis='detection'):
    """Statutory deadline of one case, or None (no deadline configured, or the
    clock has not started: decision basis and no decision to report yet)."""
    if not days:
        return None
    if basis == 'decision':
        if (case.get('decision') or '') != 'FILE_SAR':
            return None
        start = parse_date(case.get('decision_date'))
    else:
        start = (parse_date(case.get('discovery_date')) or parse_date(case.get('report_date'))
                 or parse_date(case.get('created_at')))
    return start + timedelta(days=int(days)) if start else None


def deadline_flag(case, days, basis='detection', today=None):
    """{'deadline': date, 'overdue': bool, 'days': n} for an open case with a
    deadline; None when closed or no deadline applies."""
    if (case.get('investigation_status') or 'NEW') in CLOSED_STATUSES:
        return None
    d = case_deadline(case, days, basis)
    if not d:
        return None
    today = today or date.today()
    n = (d - today).days
    return {'deadline': d, 'overdue': n < 0, 'days': abs(n) if n < 0 else n}


def deadline_config(db=None):
    """{'days': int|None, 'basis': 'detection'|'decision', 'origin': 'parameter'|'setting'|None}."""
    days, origin = None, None
    try:
        from regcontrols.api import get_param
        from regcontrols.engine import company_licence_type
        v = get_param(DEADLINE_PARAM, company_licence_type(), default=None)
        if v not in (None, ''):
            days, origin = int(v), 'parameter'
    except Exception:
        (db or get_db()).rollback()
    from models.settings import Settings
    if days is None:
        v = Settings.get(DEADLINE_DAYS_KEY)
        if v not in (None, '') and str(v).strip().isdigit() and int(v) > 0:
            days, origin = int(v), 'setting'
    basis = Settings.get(DEADLINE_BASIS_KEY) or 'detection'
    if basis not in DEADLINE_BASES:
        basis = 'detection'
    return {'days': days, 'basis': basis, 'origin': origin}


def save_deadline_setting(days, basis, actor_id):
    from models.settings import Settings
    days = (str(days or '')).strip()
    if days and (not days.isdigit() or not 0 < int(days) <= 365):
        raise StrError(N_('Enter the number of days (1 to 365), or leave it empty for no deadline.'))
    if basis not in DEADLINE_BASES:
        raise StrError(N_('Choose what the deadline is counted from.'))
    Settings.set(DEADLINE_DAYS_KEY, days, 'STR register: days to the statutory deadline')
    Settings.set(DEADLINE_BASIS_KEY, basis, 'STR register: deadline counted from detection or decision date')
    _audit(actor_id, None, f'STR register deadline setting: {days or "none"} day(s) from {basis}')


# ------------------------------------------------------------------ helpers
def _now():
    return datetime.now().isoformat(sep=' ', timespec='seconds')


def _audit(actor_id, sar_id, details):
    try:
        from flask import request
        ip = request.remote_addr
    except Exception:
        ip = None
    from models.audit import AuditLog
    AuditLog.log(actor_id, 'UPDATE', 'AML', sar_id, details, ip)


def user_name(db, uid):
    if not uid:
        return ''
    u = db.execute("SELECT first_name, last_name, email FROM users WHERE id = %s", (uid,)).fetchone()
    if not u:
        return ''
    return f"{u['first_name'] or ''} {u['last_name'] or ''}".strip() or (u['email'] or '')


def aml_staff(db=None):
    """Active users who work AML cases: site admins and anyone with edit rights on
    the AML or transaction-monitoring module."""
    db = db or get_db()
    return [dict(r) for r in db.execute("""
        SELECT id, first_name, last_name, email FROM users
         WHERE is_active = 1 AND (role IN ('admin', 'superadmin')
               OR perm_aml IN ('use', 'edit', 'admin') OR perm_tm IN ('use', 'edit', 'admin'))
         ORDER BY first_name, last_name""").fetchall()]


def is_aml_staff(db, uid):
    return any(str(u['id']) == str(uid) for u in aml_staff(db))


def get_case(db, sar_id):
    row = db.execute("SELECT * FROM suspicious_activities WHERE id = %s", (sar_id,)).fetchone()
    if not row:
        raise StrError(N_('SAR not found.'))
    return dict(row)


def new_reference(when=None):
    when = when or datetime.now()
    return f"SAR-{when.strftime('%Y%m')}-{os.urandom(2).hex().upper()}"


# ------------------------------------------------------------------ status-change points
def on_status_change(db, sar_id, old_status, new_status, actor_id):
    """Called after EVERY status change of a case (one call per change).
    Keeps the old unusual-transactions entry and the employee report in step.
    This is the single hook for a central case-tracking sync."""
    case = get_case(db, sar_id)
    if case.get('unusual_txn_id'):
        _mirror_to_unusual(db, case)
    else:
        from models.case import sync_case
        sync_case('SAR', sar_id)


UNUSUAL_STATUS = {'NEW': 'candidate', 'UNDER_INVESTIGATION': 'under_study', 'PENDING_DECISION': 'under_study',
                  'FILE_SAR': 'str_filed', 'FILED': 'str_filed', 'NO_STR': 'no_str', 'CLOSED': 'no_str'}


def _mirror_to_unusual(db, case):
    st = UNUSUAL_STATUS.get(case.get('investigation_status') or 'NEW', 'under_study')
    decision = {'FILE_SAR': 'str', 'NO_STR': 'no_str', 'NO_SAR': 'no_str'}.get(case.get('decision') or '')
    db.execute("""UPDATE aml_unusual_transactions SET status = %s, decision = %s, decision_by = %s,
                  decision_at = %s, str_reference = %s, analysis = COALESCE(%s, analysis) WHERE id = %s""",
               (st, decision, case.get('decision_by') if decision else None,
                parse_date(case.get('decision_date')) if decision else None,
                (case.get('emlcu_reference') or case.get('sar_reference')) if decision == 'str' else None,
                case.get('decision_rationale') or case.get('investigation_findings'), case['unusual_txn_id']))
    db.commit()
    try:
        from models.case import Case
        Case.sync_from_source('UNUSUAL_TXN', case['unusual_txn_id'])
    except Exception:
        db.rollback()


def create_case(*, source, reported_by, description, customer_id=None, customer_name=None, activity_date=None,
                discovery_date=None, amount=None, red_flags=None, unusual_txn_id=None, employee_report_id=None,
                links=(), db=None):
    """Open a case in the register (status NEW). links = [(link_type, target_id), ...]. Returns (id, ref)."""
    db = db or get_db()
    if source not in SOURCE_CODES:
        raise StrError(N_('Unknown source.'))
    ref = new_reference()
    today = date.today().isoformat()
    row = db.execute("""
        INSERT INTO suspicious_activities
        (sar_reference, activity_date, discovery_date, customer_id, customer_name, amount_involved, currency,
         activity_description, red_flags_identified, reported_by, report_date, investigation_status, source,
         unusual_txn_id, employee_report_id, sar_filed, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,'EGP',%s,%s,%s,%s,'NEW',%s,%s,%s,0,%s,%s) RETURNING id
    """, (ref, activity_date or discovery_date or today, discovery_date or today, customer_id, customer_name,
          amount or 0, description, red_flags or None, reported_by, today, source, unusual_txn_id,
          employee_report_id, _now(), _now())).fetchone()
    sid = row['id']
    db.commit()
    for lt, tid in links or ():
        try:
            add_link(sid, lt, tid, reported_by, note='opened with the case', db=db)
        except StrError:
            pass
    _audit(reported_by, sid, f'SAR {ref} opened (source {source})')
    on_status_change(db, sid, None, 'NEW', reported_by)
    return sid, ref


def assign_case(sar_id, assignee_id, actor_id, db=None):
    db = db or get_db()
    case = get_case(db, sar_id)
    _require_open(case)
    if not assignee_id or not is_aml_staff(db, assignee_id):
        raise StrError(N_('Choose a compliance user.'))
    old = case.get('investigation_status') or 'NEW'
    new = 'UNDER_INVESTIGATION' if old == 'NEW' else old
    db.execute("""UPDATE suspicious_activities SET assigned_to = %s, assignment_date = %s, investigation_status = %s,
                  updated_at = %s WHERE id = %s""", (assignee_id, date.today().isoformat(), new, _now(), sar_id))
    db.commit()
    _audit(actor_id, sar_id, f'SAR {case["sar_reference"]}: assigned to {user_name(db, assignee_id)}')
    if new != old:
        on_status_change(db, sar_id, old, new, actor_id)


def record_investigation(sar_id, notes, findings, ready, actor_id, actor_name='', db=None):
    db = db or get_db()
    case = get_case(db, sar_id)
    _require_open(case)
    notes = (notes or '').strip()
    if len(notes) < 10:
        raise StrError(N_('Write the investigation note.'))
    old = case.get('investigation_status') or 'NEW'
    if ready:
        new = 'PENDING_DECISION'
    else:
        new = 'UNDER_INVESTIGATION' if old in ('NEW', 'UNDER_INVESTIGATION', 'PENDING_DECISION') else old
    stamp = f"[{_now()} — {actor_name}] {notes}"
    db.execute("""UPDATE suspicious_activities SET
                  investigation_notes = CASE WHEN COALESCE(investigation_notes, '') = '' THEN %s
                                             ELSE investigation_notes || E'\n' || %s END,
                  investigation_findings = COALESCE(NULLIF(%s, ''), investigation_findings),
                  investigation_status = %s, updated_at = %s WHERE id = %s""",
               (stamp, stamp, (findings or '').strip(), new, _now(), sar_id))
    db.commit()
    _audit(actor_id, sar_id, f'SAR {case["sar_reference"]}: investigation note'
           + (' — sent for decision' if ready else ''))
    if new != old:
        on_status_change(db, sar_id, old, new, actor_id)


def record_decision(sar_id, decision, rationale, actor_id, actor_is_mlro, db=None):
    db = db or get_db()
    case = get_case(db, sar_id)
    _require_open(case)
    rationale = (rationale or '').strip()
    if not actor_is_mlro:
        raise StrError(N_('Only the MLRO decides whether to report to the unit.'))
    if case.get('reported_by') == actor_id:
        raise StrError(N_('Four-eyes: the person who raised the SAR cannot decide it.'))
    if decision not in DECISIONS or len(rationale) < 20:
        raise StrError(N_('Choose the decision and write the rationale (at least 20 characters).'))
    old = case.get('investigation_status') or 'NEW'
    db.execute("""UPDATE suspicious_activities SET decision = %s, decision_by = %s, decision_date = %s,
                  decision_rationale = %s, investigation_status = %s, updated_at = %s WHERE id = %s""",
               (decision, actor_id, date.today().isoformat(), rationale, decision, _now(), sar_id))
    db.commit()
    _audit(actor_id, sar_id, f'SAR {case["sar_reference"]}: decision {decision}')
    on_status_change(db, sar_id, old, decision, actor_id)


def record_filing(sar_id, filing_date, unit_reference, actor_id, db=None):
    db = db or get_db()
    case = get_case(db, sar_id)
    _require_open(case)
    if (case.get('investigation_status') or '') != 'FILE_SAR':
        raise StrError(N_('Record the filing after the MLRO has decided to report.'))
    fd = parse_date(filing_date)
    if not fd or fd > date.today():
        raise StrError(N_('Enter a filing date that is not in the future.'))
    ref = (unit_reference or '').strip()
    if not ref:
        raise StrError(N_("Enter the unit's reference number."))
    db.execute("""UPDATE suspicious_activities SET sar_filed = 1, sar_filing_date = %s, emlcu_reference = %s,
                  investigation_status = 'FILED', updated_at = %s WHERE id = %s""", (fd.isoformat(), ref, _now(), sar_id))
    db.commit()
    _audit(actor_id, sar_id, f'SAR {case["sar_reference"]}: filed, reference {ref}')
    on_status_change(db, sar_id, 'FILE_SAR', 'FILED', actor_id)


def _require_open(case):
    if (case.get('investigation_status') or 'NEW') in CLOSED_STATUSES:
        raise StrError(N_('This SAR is closed.'))


# ------------------------------------------------------------------ links
_TARGETS = {
    'tm_alert': ("SELECT id FROM tm_alerts WHERE alert_reference = %s", "SELECT id FROM tm_alerts WHERE id = %s"),
    'screening_alert': (None, "SELECT id FROM aml_alerts WHERE id = %s"),
    'transaction': ("SELECT id FROM transactions WHERE transaction_reference = %s",
                    "SELECT id FROM transactions WHERE id = %s"),
}


def resolve_target(db, link_type, ref):
    """Find an alert / transaction by its reference (or number). Returns id or None."""
    if link_type not in _TARGETS:
        return None
    ref = (str(ref or '')).strip().lstrip('#')
    if not ref:
        return None
    by_ref, by_id = _TARGETS[link_type]
    if by_ref:
        row = db.execute(by_ref, (ref,)).fetchone()
        if row:
            return row['id']
    if ref.isdigit():
        row = db.execute(by_id, (int(ref),)).fetchone()
        if row:
            return row['id']
    return None


def add_link(sar_id, link_type, target_id, actor_id, note=None, db=None):
    db = db or get_db()
    if link_type not in LINK_CODES:
        raise StrError(N_('Unknown link type.'))
    case = get_case(db, sar_id)
    if not target_id or resolve_target(db, link_type, str(target_id)) != int(target_id):
        raise StrError(N_('Alert or transaction not found.'))
    if db.execute("""SELECT 1 FROM aml_sar_links WHERE sar_id = %s AND link_type = %s AND target_id = %s
                     AND unlinked_at IS NULL""", (sar_id, link_type, target_id)).fetchone():
        raise StrError(N_('Already linked to this case.'))
    db.execute("""INSERT INTO aml_sar_links (sar_id, link_type, target_id, note, linked_by)
                  VALUES (%s,%s,%s,%s,%s)""", (sar_id, link_type, target_id, note, actor_id))
    if link_type == 'tm_alert':
        db.execute("UPDATE tm_alerts SET sar_id = COALESCE(sar_id, %s) WHERE id = %s", (sar_id, target_id))
    elif link_type == 'transaction':
        db.execute("UPDATE transactions SET sar_id = COALESCE(sar_id, %s) WHERE id = %s", (sar_id, target_id))
    db.commit()
    _audit(actor_id, sar_id, f'SAR {case["sar_reference"]}: linked {link_type} {_target_label(db, link_type, target_id)}')


def remove_link(link_id, actor_id, reason, db=None):
    db = db or get_db()
    link = db.execute("SELECT * FROM aml_sar_links WHERE id = %s AND unlinked_at IS NULL", (link_id,)).fetchone()
    if not link:
        raise StrError(N_('Link not found.'))
    reason = (reason or '').strip()
    if len(reason) < 5:
        raise StrError(N_('Give the reason for removing the link.'))
    case = get_case(db, link['sar_id'])
    db.execute("""UPDATE aml_sar_links SET unlinked_by = %s, unlinked_at = CURRENT_TIMESTAMP, unlink_reason = %s
                  WHERE id = %s""", (actor_id, reason, link_id))
    db.commit()
    _audit(actor_id, link['sar_id'], f'SAR {case["sar_reference"]}: removed link to {link["link_type"]} '
           f'{_target_label(db, link["link_type"], link["target_id"])} — {reason}')
    return link['sar_id']


def _target_label(db, link_type, target_id):
    if link_type == 'tm_alert':
        r = db.execute("SELECT alert_reference FROM tm_alerts WHERE id = %s", (target_id,)).fetchone()
        return (r and r['alert_reference']) or f'#{target_id}'
    if link_type == 'transaction':
        r = db.execute("SELECT transaction_reference FROM transactions WHERE id = %s", (target_id,)).fetchone()
        return (r and r['transaction_reference']) or f'#{target_id}'
    r = db.execute("SELECT matched_name FROM aml_alerts WHERE id = %s", (target_id,)).fetchone()
    return f'#{target_id}' + (f" {r['matched_name']}" if r and r['matched_name'] else '')


def case_links(db, sar_id, include_removed=True):
    rows = [dict(r) for r in db.execute(f"""
        SELECT l.*, ub.first_name || ' ' || ub.last_name AS linked_by_name,
               uu.first_name || ' ' || uu.last_name AS unlinked_by_name
          FROM aml_sar_links l LEFT JOIN users ub ON ub.id = l.linked_by LEFT JOIN users uu ON uu.id = l.unlinked_by
         WHERE l.sar_id = %s {'' if include_removed else 'AND l.unlinked_at IS NULL'}
         ORDER BY l.unlinked_at IS NOT NULL, l.link_type, l.linked_at""", (sar_id,)).fetchall()]
    for r in rows:
        r['label'] = _target_label(db, r['link_type'], r['target_id'])
        if r['link_type'] == 'transaction':
            t = db.execute("SELECT transaction_date, amount, currency FROM transactions WHERE id = %s",
                           (r['target_id'],)).fetchone()
            r['detail'] = f"{(t['transaction_date'] or '')[:10]} · {float(t['amount'] or 0):,.2f} {t['currency'] or ''}" if t else ''
        elif r['link_type'] == 'tm_alert':
            t = db.execute("SELECT status, alert_severity FROM tm_alerts WHERE id = %s", (r['target_id'],)).fetchone()
            r['detail'] = (t['alert_severity'] or '') if t else ''
            r['alert_status'] = t['status'] if t else None
        else:
            r['detail'] = ''
    return rows


# ------------------------------------------------------------------ the register (list)
def list_cases(db, *, status=None, source=None, assignee=None, overdue=None, q=None, register=None, today=None):
    """Rows for the unified list, each with deadline flag; overdue filtering in Python
    (dates are stored as text)."""
    where, args = [], []
    if status == 'OPEN':
        where.append("COALESCE(s.investigation_status, 'NEW') NOT IN ('NO_STR', 'FILED', 'CLOSED')")
    elif status == 'CLOSED':
        where.append("COALESCE(s.investigation_status, 'NEW') IN ('NO_STR', 'FILED', 'CLOSED')")
    elif status:
        where.append("COALESCE(s.investigation_status, 'NEW') = %s")
        args.append(status)
    if source:
        where.append("s.source = %s")
        args.append(source)
    if register:
        where.append("s.unusual_txn_id IS NOT NULL")
    if assignee == 'none':
        where.append("s.assigned_to IS NULL")
    elif assignee and str(assignee).isdigit():
        where.append("s.assigned_to = %s")
        args.append(int(assignee))
    if q:
        like = f"%{q.strip()}%"
        where.append("""(s.sar_reference ILIKE %s OR COALESCE(c.full_name, s.customer_name, '') ILIKE %s
                         OR COALESCE(c.customer_reference, '') ILIKE %s OR COALESCE(s.activity_description, '') ILIKE %s
                         OR COALESCE(s.emlcu_reference, '') ILIKE %s OR COALESCE(u.reference, '') ILIKE %s)""")
        args += [like] * 6
    sql = f"""
        SELECT s.*, COALESCE(c.full_name, s.customer_name) AS customer_display, c.customer_reference,
               ua.first_name || ' ' || ua.last_name AS assigned_name, u.reference AS unusual_reference,
               (SELECT count(*) FROM aml_sar_links l WHERE l.sar_id = s.id AND l.unlinked_at IS NULL
                   AND l.link_type <> 'transaction') AS alert_links,
               (SELECT count(*) FROM aml_sar_links l WHERE l.sar_id = s.id AND l.unlinked_at IS NULL
                   AND l.link_type = 'transaction') AS tx_links
          FROM suspicious_activities s
          LEFT JOIN customers c ON c.id = s.customer_id
          LEFT JOIN users ua ON ua.id = s.assigned_to
          LEFT JOIN aml_unusual_transactions u ON u.id = s.unusual_txn_id
         {('WHERE ' + ' AND '.join(where)) if where else ''}
         ORDER BY s.id DESC LIMIT 2000"""
    rows = [dict(r) for r in db.execute(sql, tuple(args)).fetchall()]
    cfg = deadline_config(db)
    for r in rows:
        r['due'] = deadline_flag(r, cfg['days'], cfg['basis'], today)
    if overdue == '1':
        rows = [r for r in rows if r['due'] and r['due']['overdue']]
    elif overdue == 'soon':
        rows = [r for r in rows if r['due'] and not r['due']['overdue'] and r['due']['days'] <= 3]
    rows.sort(key=lambda r: (r['due'] is None, r['due']['deadline'] if r['due'] else date.max, -r['id']))
    return rows, cfg


# ------------------------------------------------------------------ old unusual-transactions register
def _source_for_table(table):
    if table == 'tm_alerts':
        return 'tm_alert'
    if table in ('aml_alerts', 'screening_results'):
        return 'screening'
    if table == 'aml_employee_reports':
        return 'employee_report'
    return 'system'


def ensure_case_for_unusual(uid, db=None):
    """Every unusual-transactions entry has exactly one case in the register: an
    existing SAR raised on the same TM alert, or a new case. Returns the case id."""
    db = db or get_db()
    row = db.execute("SELECT id FROM suspicious_activities WHERE unusual_txn_id = %s", (uid,)).fetchone()
    if row:
        return row['id']
    u = db.execute("SELECT * FROM aml_unusual_transactions WHERE id = %s", (uid,)).fetchone()
    if not u:
        return None
    u = dict(u)
    customer_id = None
    if u['source_table'] == 'tm_alerts' and u['source_record_id']:
        a = db.execute("SELECT customer_id, sar_id FROM tm_alerts WHERE id = %s", (u['source_record_id'],)).fetchone()
        if a:
            customer_id = a['customer_id']
            if a['sar_id']:
                hit = db.execute("""UPDATE suspicious_activities SET unusual_txn_id = %s
                                    WHERE id = %s AND unusual_txn_id IS NULL RETURNING id""",
                                 (uid, a['sar_id'])).fetchone()
                if hit:
                    db.commit()
                    return hit['id']
    desc = (u.get('description') or u.get('detection_rule') or '') + (f"\n[{u['reference']}]" if u.get('reference') else '')
    det = u.get('detected_at') or datetime.now()
    links = [('tm_alert', u['source_record_id'])] if u['source_table'] == 'tm_alerts' and u['source_record_id'] else []
    sid, _ref = create_case(source=_source_for_table(u['source_table']), reported_by=u.get('created_by'),
                            description=desc, customer_id=customer_id, customer_name=u.get('subject_name'),
                            activity_date=det.date().isoformat(), discovery_date=det.date().isoformat(),
                            amount=u.get('amount'), unusual_txn_id=uid, links=links, db=db)
    return sid


def refresh_case_from_unusual(uid, db=None):
    """A study recorded directly on the old register (older API callers, seeds):
    bring a still-new case in line with it."""
    db = db or get_db()
    sid = ensure_case_for_unusual(uid, db)
    if not sid:
        return None
    case = get_case(db, sid)
    u = dict(db.execute("SELECT * FROM aml_unusual_transactions WHERE id = %s", (uid,)).fetchone())
    if (case.get('investigation_status') or 'NEW') != 'NEW':
        return sid
    if u.get('reference') and f"[{u['reference']}]" in (case.get('activity_description') or '') and u.get('detected_at'):
        det = parse_date(u['detected_at']).isoformat()
        db.execute("""UPDATE suspicious_activities SET discovery_date = %s, report_date = %s,
                      activity_date = LEAST(COALESCE(activity_date, %s), %s) WHERE id = %s""", (det, det, det, det, sid))
        db.commit()
    if u['status'] == 'candidate':
        return sid
    new = {'under_study': 'UNDER_INVESTIGATION', 'str_filed': 'FILED' if u.get('str_reference') else 'FILE_SAR',
           'no_str': 'NO_STR', 'dismissed': 'NO_STR'}.get(u['status'], 'UNDER_INVESTIGATION')
    decision = {'str': 'FILE_SAR', 'no_str': 'NO_STR'}.get(u.get('decision') or '') or (
        'NO_STR' if u['status'] in ('no_str', 'dismissed') else None)
    dd = parse_date(u.get('decision_at'))
    db.execute("""UPDATE suspicious_activities SET investigation_status = %s, investigation_notes = %s,
                  investigation_findings = %s, decision = %s, decision_by = %s, decision_date = %s,
                  decision_rationale = %s, sar_filed = %s, sar_filing_date = %s, emlcu_reference = %s,
                  updated_at = %s WHERE id = %s""",
               (new, u.get('analysis'), u.get('analysis'), decision, u.get('decision_by') if decision else None,
                dd.isoformat() if dd else None, u.get('analysis') if decision else None,
                1 if new == 'FILED' else 0, dd.isoformat() if new == 'FILED' and dd else None,
                u.get('str_reference') if new == 'FILED' else None, _now(), sid))
    db.commit()
    return sid
