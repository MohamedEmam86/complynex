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


def rating_class(classification):
    """The rating whose review interval applies. A missing or unknown rating is
    not assumed to be low risk: it is reviewed on the HIGH interval."""
    cls = str(classification or '').strip().upper()
    return cls if cls in aml_risk.CLASSES else 'HIGH'


def due_date(customer, model):
    """When the customer's next review is due (None when nothing to count from).

    The earlier of the stored next review date and the last review (else the
    rating / onboarding date) plus the interval of the CURRENT rating: a
    customer re-rated HIGH after the date was stored is not left on the old,
    longer interval."""
    stored = parse_date(customer.get('next_review_date'))
    base = (parse_date(customer.get('last_review_date')) or parse_date(customer.get('risk_classification_date'))
            or parse_date(customer.get('onboarding_date')) or parse_date(customer.get('created_at')))
    computed = None
    if base:
        months = (aml_risk.merged(model)['review_months'] or {}).get(rating_class(customer.get('risk_classification')))
        computed = base + relativedelta(months=int(months)) if months else None
    dates = [d for d in (stored, computed) if d]
    return min(dates) if dates else None


def review_state(due, today, days_before):
    if not due:
        return 'unknown'
    if due < today:
        return 'overdue'
    if (due - today).days <= int(days_before or 0):
        return 'due_soon'
    return 'ok'


def next_after(review_day, classification, model):
    months = aml_risk.merged(model)['review_months'].get(rating_class(classification), 12)
    return review_day + relativedelta(months=int(months))


# ----------------------------------------------------------------------------- database side

STATE_ORDER = {'overdue': 0, 'due_soon': 1, 'unknown': 2, 'ok': 3}

# Due date and state computed in SQL (filters and LIMIT applied there, not on the whole register).
# aml_safe_date() (migration 20261105_p8aml) reads the text date columns and returns NULL on bad text.
_PORTFOLIO_CTE = """
WITH c AS (
    SELECT id, customer_reference, full_name, company_name, risk_classification, risk_classification_date,
           last_review_date, next_review_date, onboarding_date, created_at, status,
           CASE WHEN upper(COALESCE(risk_classification, '')) IN ('HIGH', 'MEDIUM', 'LOW')
                THEN upper(risk_classification) ELSE 'HIGH' END AS rating_class,
           aml_safe_date(next_review_date::text) AS stored_due,
           COALESCE(aml_safe_date(last_review_date::text), aml_safe_date(risk_classification_date::text),
                    aml_safe_date(onboarding_date::text), aml_safe_date(created_at::text)) AS base
      FROM customers
     WHERE upper(COALESCE(status, 'ACTIVE')) NOT IN %(closed)s
), d AS (
    SELECT c.*, LEAST(stored_due, (base + make_interval(months => CASE rating_class WHEN 'HIGH' THEN %(m_high)s
                                                               WHEN 'MEDIUM' THEN %(m_medium)s ELSE %(m_low)s END))::date) AS due
      FROM c
), s AS (
    SELECT d.*, CASE WHEN due IS NULL THEN 'unknown' WHEN due < %(today)s THEN 'overdue'
                     WHEN due - %(today)s <= %(days)s THEN 'due_soon' ELSE 'ok' END AS state
      FROM d
)
"""
_FILTER = "WHERE (%(state)s::text IS NULL OR state = %(state)s) AND (%(risk)s::text IS NULL OR rating_class = %(risk)s)"


def _has_sql_dates(db):
    try:
        r = db.execute("SELECT to_regprocedure('aml_safe_date(text)') AS f").fetchone()
        return bool(r and r['f'])
    except Exception:
        return False


def _decorate(c, today):
    c['days'] = (c['due'] - today).days if c.get('due') else None
    c['name'] = c.get('full_name') or c.get('company_name') or c.get('customer_reference')
    return c


def portfolio_page(db=None, model=None, today=None, state=None, risk=None, limit=500):
    """{'rows': most urgent first (at most `limit`), 'total': rows matching the filters,
    'summary': {state: count} over all active customers}."""
    from .risk_config import current_model
    db = db or get_db()
    model = model or current_model(db)
    today = today or date.today()
    m = aml_risk.merged(model)
    days = int(m['reminders']['days_before'])
    state = state if state in STATE_ORDER else None
    risk = risk if risk in aml_risk.CLASSES else None
    if not _has_sql_dates(db):
        return _portfolio_page_py(db, m, today, days, state, risk, limit)
    args = {'closed': CLOSED_STATUSES, 'today': today, 'days': days, 'state': state, 'risk': risk,
            'm_high': int(m['review_months']['HIGH']), 'm_medium': int(m['review_months']['MEDIUM']),
            'm_low': int(m['review_months']['LOW']), 'limit': int(limit) if limit else None}
    summary = {k: 0 for k in STATE_ORDER}
    for r in db.execute(_PORTFOLIO_CTE + "SELECT state, count(*) AS n FROM s GROUP BY state", args).fetchall():
        summary[r['state']] = int(r['n'])
    total = int(db.execute(_PORTFOLIO_CTE + "SELECT count(*) AS n FROM s " + _FILTER, args).fetchone()['n'])
    rows = [_decorate(dict(r), today) for r in db.execute(
        _PORTFOLIO_CTE + "SELECT * FROM s " + _FILTER + """
         ORDER BY CASE state WHEN 'overdue' THEN 0 WHEN 'due_soon' THEN 1 WHEN 'unknown' THEN 2 ELSE 3 END,
                  due NULLS LAST, id
         LIMIT %(limit)s""", args).fetchall()]
    return {'rows': rows, 'total': total, 'summary': summary}


def _portfolio_page_py(db, model, today, days, state, risk, limit):
    """Same result computed in Python (before the migration adds aml_safe_date)."""
    every = []
    for r in db.execute("""SELECT id, customer_reference, full_name, company_name, risk_classification,
                                  risk_classification_date, last_review_date, next_review_date, onboarding_date,
                                  created_at, status
                             FROM customers""").fetchall():
        c = dict(r)
        if (c.get('status') or 'ACTIVE').upper() in CLOSED_STATUSES:
            continue
        c['due'] = due_date(c, model)
        c['state'] = review_state(c['due'], today, days)
        c['rating_class'] = rating_class(c.get('risk_classification'))
        every.append(c)
    summary = {k: 0 for k in STATE_ORDER}
    for c in every:
        summary[c['state']] += 1
    rows = [c for c in every if (not state or c['state'] == state) and (not risk or c['rating_class'] == risk)]
    rows.sort(key=lambda c: (STATE_ORDER[c['state']], c['due'] or date.max, c['id']))
    return {'rows': [_decorate(c, today) for c in (rows[:limit] if limit else rows)], 'total': len(rows),
            'summary': summary}


def portfolio(db=None, model=None, today=None, state=None, risk=None, limit=500):
    """Active customers with their review due date and state, most urgent first."""
    return portfolio_page(db, model, today, state, risk, limit)['rows']


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
    summ = portfolio_page(db, model, today, limit=1)['summary']
    overdue, soon = summ['overdue'], summ['due_soon']
    if overdue + soon and not dry_run:
        from services.notification_service import notify
        notify([u['id'] for u in aml_staff(db)], 'Customer reviews due',
               f'{overdue} customer review(s) overdue and {soon} due within '
               f'{model["reminders"]["days_before"]} days.', link='/aml/periodic-reviews', category='warning')
    return True, overdue + soon
