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
Periodic customer review driven by risk (F2).

The interval per classification comes from the risk model
(aml_risk.DEFAULT_MODEL['review_months'], changed by the MLRO on
/aml/risk-scoring). A review re-rates the customer (model + HIGH floor + EDD,
aml/services.calculate_customer_risk), records the outcome in
aml_customer_reviews and sets the next review date.

Reminders of reviews coming due are OFF until the MLRO switches them on in
the model; nothing here runs on a timer — scripts/aml_review_reminders.py is
run by hand or by a timer the owner decides to install.
"""
from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from database.db import get_db
from utils import aml_risk

OUTCOMES = [  # code, EN, AR
    ('no_change', 'Reviewed — no change', 'تمت المراجعة — بدون تغيير'),
    ('updated', 'Reviewed — file updated', 'تمت المراجعة — تم تحديث الملف'),
    ('edd_required', 'Reviewed — enhanced due diligence needed', 'تمت المراجعة — مطلوب عناية مشددة'),
    ('exit_recommended', 'Reviewed — exit of the relationship recommended', 'تمت المراجعة — يوصى بإنهاء العلاقة'),
]
OUTCOME_CODES = tuple(c for c, _e, _a in OUTCOMES)
CLOSED_STATUSES = ('CLOSED', 'EXITED', 'REJECTED', 'TERMINATED', 'INACTIVE')


class ReviewError(ValueError):
    pass


def parse_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or '').strip()[:10]
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def due_date(customer, model):
    """When the customer's next review is due (None when nothing to count from)."""
    explicit = parse_date(customer.get('next_review_date'))
    if explicit:
        return explicit
    base = (parse_date(customer.get('last_review_date')) or parse_date(customer.get('risk_classification_date'))
            or parse_date(customer.get('onboarding_date')) or parse_date(customer.get('created_at')))
    if not base:
        return None
    cls = (customer.get('risk_classification') or 'LOW').upper()
    months = (aml_risk.merged(model)['review_months'] or {}).get(cls if cls in aml_risk.CLASSES else 'HIGH')
    return base + relativedelta(months=int(months)) if months else None


def review_state(due, today, days_before):
    if not due:
        return 'unknown'
    if due < today:
        return 'overdue'
    if (due - today).days <= int(days_before or 0):
        return 'due_soon'
    return 'ok'


def next_after(review_day, classification, model):
    months = aml_risk.merged(model)['review_months'].get((classification or 'LOW').upper(), 12)
    return review_day + relativedelta(months=int(months))


# ----------------------------------------------------------------------------- database side

def portfolio(db=None, model=None, today=None, state=None, risk=None):
    """Active customers with their review due date and state, most urgent first."""
    from .risk_config import current_model
    db = db or get_db()
    model = model or current_model(db)
    today = today or date.today()
    days = model['reminders']['days_before']
    out = []
    for r in db.execute("""SELECT id, customer_reference, full_name, company_name, risk_classification,
                                  risk_classification_date, last_review_date, next_review_date, onboarding_date,
                                  created_at, status
                             FROM customers""").fetchall():
        c = dict(r)
        if (c.get('status') or 'ACTIVE').upper() in CLOSED_STATUSES:
            continue
        due = due_date(c, model)
        st = review_state(due, today, days)
        if state and st != state:
            continue
        if risk and (c.get('risk_classification') or 'LOW').upper() != risk:
            continue
        c.update(due=due, state=st, days=(due - today).days if due else None,
                 name=c.get('full_name') or c.get('company_name') or c.get('customer_reference'))
        out.append(c)
    order = {'overdue': 0, 'due_soon': 1, 'unknown': 2, 'ok': 3}
    out.sort(key=lambda c: (order[c['state']], c['due'] or date.max))
    return out


def summary(rows):
    s = {'overdue': 0, 'due_soon': 0, 'unknown': 0, 'ok': 0}
    for r in rows:
        s[r['state']] += 1
    return s


def record_review(customer_id, outcome, notes, user_id, db=None, today=None):
    """Record one review: re-rate, store it, set the next review date. Returns the review row."""
    from .services import calculate_customer_risk
    from .risk_config import current_model
    db = db or get_db()
    today = today or date.today()
    if outcome not in OUTCOME_CODES:
        raise ReviewError('Choose the outcome of the review.')
    notes = (notes or '').strip()
    if len(notes) < 10:
        raise ReviewError('Write what was reviewed (at least 10 characters).')
    c = db.execute("SELECT id, risk_classification, customer_reference FROM customers WHERE id = %s",
                   (customer_id,)).fetchone()
    if not c:
        raise ReviewError('Customer not found.')
    old = c['risk_classification']
    _score, new = calculate_customer_risk(customer_id, user_id)
    nxt = next_after(today, new, current_model(db))
    db.execute("UPDATE customers SET last_review_date = %s, next_review_date = %s WHERE id = %s",
               (today.isoformat(), nxt.isoformat(), customer_id))
    rid = db.execute("""INSERT INTO aml_customer_reviews (customer_id, review_date, outcome, notes, old_classification,
                        new_classification, next_review_date, reviewed_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (customer_id, today, outcome, notes, old, new, nxt, user_id)).fetchone()['id']
    db.commit()
    try:
        from flask import request
        ip = request.remote_addr
    except Exception:
        ip = None
    from models.audit import AuditLog
    AuditLog.log(user_id, 'Customer periodic review', 'AML', customer_id,
                 f'{c["customer_reference"]}: {outcome}; rating {old} -> {new}; next review {nxt}', ip)
    return {'id': rid, 'old': old, 'new': new, 'next': nxt}


def reviews_of(customer_id, db=None):
    db = db or get_db()
    return [dict(r) for r in db.execute(
        """SELECT r.*, trim(coalesce(u.first_name, '') || ' ' || coalesce(u.last_name, '')) AS by_name
             FROM aml_customer_reviews r LEFT JOIN users u ON u.id = r.reviewed_by
            WHERE r.customer_id = %s ORDER BY r.review_date DESC, r.id DESC""", (customer_id,)).fetchall()]


def send_reminders(db=None, today=None, dry_run=False):
    """Notify AML staff of reviews overdue or coming due. Does nothing while the
    model's reminders are off. Returns (enabled, count)."""
    from .risk_config import current_model
    from .str_register import aml_staff
    db = db or get_db()
    model = current_model(db, force=True)
    if not model['reminders']['enabled']:
        return False, 0
    rows = [r for r in portfolio(db, model, today) if r['state'] in ('overdue', 'due_soon')]
    if rows and not dry_run:
        from services.notification_service import notify
        overdue = sum(1 for r in rows if r['state'] == 'overdue')
        notify([u['id'] for u in aml_staff(db)], 'Customer reviews due',
               f'{overdue} customer review(s) overdue and {len(rows) - overdue} due within '
               f'{model["reminders"]["days_before"]} days.', link='/aml/periodic-reviews', category='warning')
    return True, len(rows)
