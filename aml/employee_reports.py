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
Internal suspicious-activity reports from employees to the MLRO.

Separate from whistleblowing: any employee reports a suspicion about a customer or
merchant; the MLRO reviews it and either converts it into a case in the STR
register (source = employee report, linked both ways) or closes it with a reason.
The reporter sees only their own reports and their status.

One function per status change (submit_report, start_review, convert_to_str,
close_no_action); each writes an append-only event and ends in
on_report_status_change(), the hook for a central case-tracking sync.
"""

from datetime import date, datetime

from database.db import get_db


def N_(s):
    return s


class ReportError(ValueError):
    pass


STATUSES = [  # code, EN, AR
    ('NEW', N_('New'), 'جديد'),
    ('UNDER_REVIEW', N_('Under review'), 'قيد المراجعة'),
    ('CONVERTED', N_('Converted to STR'), 'تم تحويله إلى إخطار اشتباه'),
    ('CLOSED_NO_ACTION', N_('Closed – no action'), 'مغلق – دون إجراء'),
]
SUBJECT_TYPES = [('customer', N_('Customer'), 'عميل'), ('merchant', N_('Merchant'), 'تاجر'),
                 ('other', N_('Other'), 'أخرى')]
ACTIONS = [('submitted', N_('Submitted'), 'تقديم البلاغ'), ('review', N_('Review started'), 'بدء المراجعة'),
           ('converted', N_('Converted to STR'), 'تحويل إلى إخطار اشتباه'),
           ('closed', N_('Closed – no action'), 'إغلاق دون إجراء')]
ATTACH_TYPE = 'aml_emp_report'


def labels(pairs, ar=False):
    return {c: (a if ar else e) for c, e, a in pairs}


def _d(v):
    try:
        return date.fromisoformat((v or '').strip()) if (v or '').strip() else None
    except ValueError:
        return False


def validate(form, today=None):
    """Errors for a new report (pure)."""
    today = today or date.today()
    errors = []
    if (form.get('subject_type') or '') not in [c for c, _e, _a in SUBJECT_TYPES]:
        errors.append(N_('Choose who the report is about.'))
    if len((form.get('subject_name') or '').strip()) < 2:
        errors.append(N_('Enter the name of the customer or merchant.'))
    if len((form.get('description') or '').strip()) < 30:
        errors.append(N_('Describe what you noticed (at least 30 characters).'))
    d1, d2 = _d(form.get('activity_from')), _d(form.get('activity_to'))
    if d1 is False or d2 is False:
        errors.append(N_('Enter valid dates.'))
    else:
        if (d1 and d1 > today) or (d2 and d2 > today):
            errors.append(N_('Dates cannot be in the future.'))
        if d1 and d2 and d1 > d2:
            errors.append(N_('The start date cannot be after the end date.'))
    return errors


def _event(db, report_id, action, actor_id, from_status, to_status, note=None):
    db.execute("""INSERT INTO aml_employee_report_events (report_id, action, from_status, to_status, note, actor_id)
                  VALUES (%s,%s,%s,%s,%s,%s)""", (report_id, action, from_status, to_status, note, actor_id))


def on_report_status_change(db, report_id, old_status, new_status, actor_id):
    """Called after every status change of an employee report — hook for case tracking."""
    return None


def get_report(db, report_id):
    row = db.execute("""SELECT r.*, u.first_name || ' ' || u.last_name AS reporter_name, u.email AS reporter_email,
                               u.job_title AS reporter_job_title,
                               rv.first_name || ' ' || rv.last_name AS reviewed_by_name,
                               cl.first_name || ' ' || cl.last_name AS closed_by_name,
                               s.sar_reference
                          FROM aml_employee_reports r JOIN users u ON u.id = r.reporter_id
                          LEFT JOIN users rv ON rv.id = r.reviewed_by LEFT JOIN users cl ON cl.id = r.closed_by
                          LEFT JOIN suspicious_activities s ON s.id = r.sar_id
                         WHERE r.id = %s""", (report_id,)).fetchone()
    if not row:
        raise ReportError(N_('Report not found.'))
    return dict(row)


def submit_report(reporter_id, form, db=None):
    db = db or get_db()
    errs = validate(form)
    if errs:
        raise ReportError(errs[0])
    cid = form.get('customer_id')
    cid = int(cid) if cid and str(cid).isdigit() and db.execute(
        "SELECT 1 FROM customers WHERE id = %s", (int(cid),)).fetchone() else None
    rid = db.execute("""
        INSERT INTO aml_employee_reports (reporter_id, subject_type, subject_name, subject_ref, customer_id, description,
                                          related_transactions, activity_from, activity_to)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (reporter_id, form['subject_type'], form['subject_name'].strip()[:255],
         (form.get('subject_ref') or '').strip()[:80] or None, cid, form['description'].strip(),
         (form.get('related_transactions') or '').strip() or None,
         _d(form.get('activity_from')) or None, _d(form.get('activity_to')) or None)).fetchone()['id']
    ref = f'ESR-{datetime.now().year}-{rid:05d}'
    db.execute("UPDATE aml_employee_reports SET reference = %s WHERE id = %s", (ref, rid))
    _event(db, rid, 'submitted', reporter_id, None, 'NEW')
    db.commit()
    on_report_status_change(db, rid, None, 'NEW', reporter_id)
    return rid, ref


def start_review(report_id, actor_id, db=None):
    db = db or get_db()
    r = get_report(db, report_id)
    if r['status'] != 'NEW':
        raise ReportError(N_('Only a new report can be taken under review.'))
    db.execute("UPDATE aml_employee_reports SET status = 'UNDER_REVIEW', reviewed_by = %s, reviewed_at = %s WHERE id = %s",
               (actor_id, datetime.now(), report_id))
    _event(db, report_id, 'review', actor_id, 'NEW', 'UNDER_REVIEW')
    db.commit()
    on_report_status_change(db, report_id, 'NEW', 'UNDER_REVIEW', actor_id)


def convert_to_str(report_id, actor_id, customer_id=None, amount=None, db=None):
    """Open a case in the STR register from this report (source = employee report)."""
    db = db or get_db()
    from aml.str_register import create_case
    r = get_report(db, report_id)
    if r['status'] not in ('NEW', 'UNDER_REVIEW'):
        raise ReportError(N_('This report is already closed.'))
    if r['reporter_id'] == actor_id:
        raise ReportError(N_('Four-eyes: you cannot process a report you submitted.'))
    cid = customer_id if customer_id and str(customer_id).isdigit() else r.get('customer_id')
    try:
        amount = float(amount) if amount not in (None, '') else 0
        if amount < 0:
            raise ValueError
    except ValueError:
        raise ReportError(N_('The amount must be a number.'))
    desc = r['description'] + (f"\n\n{r['related_transactions']}" if r.get('related_transactions') else '') \
        + f"\n[{r['reference']}]"
    sid, sref = create_case(source='employee_report', reported_by=r['reporter_id'], description=desc,
                            customer_id=int(cid) if cid else None, customer_name=r['subject_name'],
                            activity_date=(r['activity_from'] or r['created_at'].date()).isoformat(),
                            discovery_date=r['created_at'].date().isoformat(), amount=amount,
                            employee_report_id=report_id, db=db)
    old = r['status']
    db.execute("""UPDATE aml_employee_reports SET status = 'CONVERTED', sar_id = %s, closed_by = %s, closed_at = %s,
                  reviewed_by = COALESCE(reviewed_by, %s), reviewed_at = COALESCE(reviewed_at, %s) WHERE id = %s""",
               (sid, actor_id, datetime.now(), actor_id, datetime.now(), report_id))
    _event(db, report_id, 'converted', actor_id, old, 'CONVERTED', sref)
    db.commit()
    on_report_status_change(db, report_id, old, 'CONVERTED', actor_id)
    return sid, sref


def close_no_action(report_id, actor_id, reason, db=None):
    db = db or get_db()
    r = get_report(db, report_id)
    if r['status'] not in ('NEW', 'UNDER_REVIEW'):
        raise ReportError(N_('This report is already closed.'))
    if r['reporter_id'] == actor_id:
        raise ReportError(N_('Four-eyes: you cannot process a report you submitted.'))
    reason = (reason or '').strip()
    if len(reason) < 20:
        raise ReportError(N_('Write the reason for closing without action (at least 20 characters).'))
    old = r['status']
    db.execute("""UPDATE aml_employee_reports SET status = 'CLOSED_NO_ACTION', close_reason = %s, closed_by = %s,
                  closed_at = %s, reviewed_by = COALESCE(reviewed_by, %s), reviewed_at = COALESCE(reviewed_at, %s)
                  WHERE id = %s""", (reason, actor_id, datetime.now(), actor_id, datetime.now(), report_id))
    _event(db, report_id, 'closed', actor_id, old, 'CLOSED_NO_ACTION', reason)
    db.commit()
    on_report_status_change(db, report_id, old, 'CLOSED_NO_ACTION', actor_id)


def report_events(db, report_id):
    return [dict(r) for r in db.execute("""
        SELECT e.*, u.first_name || ' ' || u.last_name AS actor_name FROM aml_employee_report_events e
          LEFT JOIN users u ON u.id = e.actor_id WHERE e.report_id = %s ORDER BY e.id DESC""", (report_id,)).fetchall()]


def inbox(db, status=None):
    where, args = '', ()
    if status == 'OPEN':
        where = "WHERE r.status IN ('NEW', 'UNDER_REVIEW')"
    elif status:
        where, args = 'WHERE r.status = %s', (status,)
    return [dict(x) for x in db.execute(f"""
        SELECT r.*, u.first_name || ' ' || u.last_name AS reporter_name, s.sar_reference
          FROM aml_employee_reports r JOIN users u ON u.id = r.reporter_id
          LEFT JOIN suspicious_activities s ON s.id = r.sar_id {where}
         ORDER BY (r.status IN ('NEW', 'UNDER_REVIEW')) DESC, r.created_at DESC LIMIT 1000""", args).fetchall()]


def my_reports(db, reporter_id):
    """Status only — no MLRO notes, reasons or case references."""
    return [dict(x) for x in db.execute("""
        SELECT id, reference, subject_name, status, created_at FROM aml_employee_reports
         WHERE reporter_id = %s ORDER BY created_at DESC""", (reporter_id,)).fetchall()]


def mlro_user_ids(db):
    return [r['id'] for r in db.execute(
        "SELECT id FROM users WHERE is_active = 1 AND role = 'compliance_manager'").fetchall()]
