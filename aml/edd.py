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
Customer risk floor and the EDD workflow (database side).

reassess() is called by every onboarding / edit / screening path: it forces
HIGH where edd_logic says so, flags requires_edd, opens an EDD record and,
for a new customer, holds activation. The EDD record lives in edd_cases
(prepared -> submitted -> approved / returned) with edd_case_history.
"""

from datetime import date, datetime

from database.db import get_db
from . import edd_logic as L

ATTACH_TYPE = 'edd_case'


class EddError(Exception):
    pass


# ----------------------------------------------------------------------------- countries

def countries(db=None, active_only=False):
    db = db or get_db()
    q = "SELECT * FROM high_risk_countries" + (" WHERE is_active = 1" if active_only else "")
    return [dict(r) for r in db.execute(q + " ORDER BY is_active DESC, country_name").fetchall()]


def country_for(value, db=None):
    return L.match_country(value, countries(db, active_only=True))


# ----------------------------------------------------------------------------- risk floor

def _queue_items(customer_id, db):
    return [dict(r) for r in db.execute(
        """SELECT status, resolution, list_source FROM screening_queue
           WHERE source_module = 'Customer KYC' AND source_record_id = %s""", (customer_id,)).fetchall()]


def _is_entity(c):
    return (c.get('customer_type') or '').upper() in ('CORPORATE', 'ENTITY')


def forced_reasons(customer, db=None):
    db = db or get_db()
    owners = []
    if _is_entity(customer):
        from kyb import service as kyb
        owners = kyb.risk_people('aml_customer', customer['id'], db)
    return L.forced_high_reasons(customer, countries(db, active_only=True),
                                 L.screening_link(_queue_items(customer['id'], db)), owners)


REASON_TEXT = {
    'pep': 'PEP', 'screening': 'screening link', 'country': 'high-risk country',
    'owner_pep': 'PEP owner/signatory', 'owner_screening': 'owner/signatory screening link',
    'owner_country': 'owner/signatory high-risk country',
}


def reasons_text(reasons):
    return '; '.join(f"{REASON_TEXT.get(c, c)}: {d}" for c, d in reasons)


def reassess(customer_id, user_id=None, model_class=None, on_create=False, db=None):
    """Apply the HIGH floor to one customer and open EDD when needed.

    model_class: the scoring model's result when the caller just recomputed it
    (create / edit); otherwise the stored classification is the base.
    Returns dict(classification, reasons, requires_edd, case).
    """
    db = db or get_db()
    row = db.execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone()
    if not row:
        return None
    c = dict(row)
    reasons = forced_reasons(c, db)
    base = model_class or c.get('risk_classification') or 'LOW'
    if c.get('risk_override_reason') and c.get('risk_classification') and not on_create:
        base = c['risk_classification']          # a documented manual rating is kept
    final = L.final_classification(base, reasons)
    hrc = any(code == 'country' for code, _d in reasons)
    requires = final == 'HIGH'
    reason_txt = ('Forced HIGH - ' + reasons_text(reasons)) if reasons else c.get('risk_classification_reason')
    case = latest_case(customer_id, db)
    if requires and not case:
        case = open_case(customer_id, reasons, user_id, db)
    approved = L.edd_status(case) == L.EDD_APPROVED
    db.execute("""UPDATE customers SET risk_classification = %s, is_high_risk_country = %s, requires_edd = %s,
                  edd_completed = %s, risk_classification_reason = %s,
                  risk_classification_date = CASE WHEN risk_classification IS DISTINCT FROM %s
                                                  THEN to_char(CURRENT_DATE, 'YYYY-MM-DD')
                                                  ELSE risk_classification_date END
                  WHERE id = %s""",
               (final, 1 if hrc else 0, 1 if requires else 0, 1 if approved else 0, reason_txt, final, customer_id))
    if on_create and requires and not approved and (c.get('status') or 'ACTIVE') == 'ACTIVE':
        db.execute("UPDATE customers SET status = 'PENDING', status_reason = %s WHERE id = %s",
                   ('High risk: EDD must be approved before activation', customer_id))
    db.commit()
    return {'classification': final, 'reasons': reasons, 'requires_edd': requires, 'case': case}


# ----------------------------------------------------------------------------- EDD record

def latest_case(customer_id, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM edd_cases WHERE customer_id = %s ORDER BY id DESC LIMIT 1", (customer_id,)).fetchone()
    return dict(r) if r else None


def get_case(case_id, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM edd_cases WHERE id = %s", (case_id,)).fetchone()
    return dict(r) if r else None


def _history(db, case_id, action, from_s, to_s, user_id, reason=None):
    db.execute("""INSERT INTO edd_case_history (edd_case_id, action, from_status, to_status, reason, user_id)
                  VALUES (%s,%s,%s,%s,%s,%s)""", (case_id, action, from_s, to_s, reason, user_id))


def open_case(customer_id, reasons, user_id, db=None, trigger=None):
    db = db or get_db()
    now = datetime.now()
    trig = trigger or (reasons[0][0] if reasons else 'high_risk')
    cid = db.execute("""INSERT INTO edd_cases (case_reference, customer_id, edd_trigger, trigger_description, trigger_date,
                        priority, status, created_at, created_by, updated_at)
                        VALUES (%s,%s,%s,%s,%s,'HIGH',%s,%s,%s,%s) RETURNING id""",
                     (f"EDD-{now:%Y%m%d}-{customer_id:05d}-{now:%H%M%S}", customer_id, trig,
                      reasons_text(reasons) or 'High risk customer', now.strftime('%Y-%m-%d'), L.EDD_OPEN,
                      now.strftime('%Y-%m-%d %H:%M:%S'), user_id, now.strftime('%Y-%m-%d %H:%M:%S'))).fetchone()['id']
    _history(db, cid, 'opened', None, L.EDD_OPEN, user_id, reasons_text(reasons) or None)
    db.commit()
    return get_case(cid, db)


def evidence_count(case_id, db=None):
    db = db or get_db()
    try:
        return db.execute("SELECT count(*) AS n FROM generic_attachments WHERE module = 'aml' AND record_type = %s "
                          "AND record_id = %s", (ATTACH_TYPE, case_id)).fetchone()['n']
    except Exception:
        db.rollback()
        return 0


def save_case(case, form, user_id, db=None):
    db = db or get_db()
    if not L.can_edit(case):
        raise EddError('This EDD record can no longer be changed.')
    freq = form.get('enhanced_monitoring_frequency') or None
    if freq and freq not in L.MONITORING_FREQUENCIES:
        raise EddError('Choose a monitoring frequency from the list.')
    nr = (form.get('next_review_date') or '').strip() or None
    if nr:
        try:
            if date.fromisoformat(nr) <= date.today():
                raise EddError('The next review date must be in the future.')
        except ValueError:
            raise EddError('Enter a valid next review date.')
    vals = {k: ((form.get(k) or '').strip() or None)
            for k in ('source_of_wealth', 'source_of_funds', 'sof_evidence', 'purpose_nature', 'investigation_notes')}
    db.execute("""UPDATE edd_cases SET source_of_wealth = %s, source_of_funds = %s, sof_evidence = %s,
                  purpose_nature = %s, investigation_notes = %s, enhanced_monitoring_frequency = %s,
                  next_review_date = %s, assigned_to = COALESCE(assigned_to, %s), updated_at = %s WHERE id = %s""",
               (vals['source_of_wealth'], vals['source_of_funds'], vals['sof_evidence'], vals['purpose_nature'],
                vals['investigation_notes'], freq, nr, user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                case['id']))
    _history(db, case['id'], 'saved', L.edd_status(case), L.edd_status(case), user_id)
    db.commit()


def submit(case, user_id, db=None):
    db = db or get_db()
    if not L.can_edit(case):
        raise EddError('Only an EDD record in preparation can be submitted.')
    missing = L.missing_for_submission(case, evidence_count(case['id'], db))
    if missing:
        raise EddError(('Complete the checklist first: %(items)s', missing))
    db.execute("""UPDATE edd_cases SET status = %s, prepared_by = %s, submitted_at = CURRENT_TIMESTAMP,
                  returned_reason = NULL, updated_at = %s WHERE id = %s""",
               (L.EDD_SUBMITTED, user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), case['id']))
    _history(db, case['id'], 'submitted', L.edd_status(case), L.EDD_SUBMITTED, user_id)
    db.commit()


def _check_approver(case, user):
    if L.edd_status(case) != L.EDD_SUBMITTED:
        raise EddError('This EDD record is not waiting for approval.')
    if not L.approver_role_ok(user.role, user.can_view('aml')):
        raise EddError('Only the MLRO or a senior manager can decide on EDD.')
    err = L.four_eyes_error(user.id, case.get('prepared_by'))
    if err:
        raise EddError('Four-eyes: you prepared this EDD; another person must approve it.')


def approve(case, user, notes, db=None):
    db = db or get_db()
    _check_approver(case, user)
    if len((notes or '').strip()) < 10:
        raise EddError('Write the approval rationale (at least 10 characters).')
    today = date.today().isoformat()
    db.execute("""UPDATE edd_cases SET status = %s, approved_by = %s, approval_date = %s, approval_notes = %s,
                  senior_management_approval = 1, completion_date = %s, monitoring_enhanced = 1,
                  relationship_continued = 1, outcome = 'Approved - continue with enhanced monitoring',
                  updated_at = %s WHERE id = %s""",
               (L.EDD_APPROVED, user.id, today, notes.strip(), today,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'), case['id']))
    db.execute("""UPDATE customers SET edd_completed = 1, edd_approved_by = %s, edd_approval_date = %s,
                  next_review_date = COALESCE(%s, next_review_date) WHERE id = %s""",
               (user.id, today, case['next_review_date'].isoformat() if case.get('next_review_date') else None,
                case['customer_id']))
    _history(db, case['id'], 'approved', L.EDD_SUBMITTED, L.EDD_APPROVED, user.id, notes.strip())
    db.commit()


def return_case(case, user, reason, db=None):
    db = db or get_db()
    _check_approver(case, user)
    if len((reason or '').strip()) < 10:
        raise EddError('Give the reason for returning the EDD (at least 10 characters).')
    db.execute("UPDATE edd_cases SET status = %s, returned_reason = %s, updated_at = %s WHERE id = %s",
               (L.EDD_RETURNED, reason.strip(), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), case['id']))
    _history(db, case['id'], 'returned', L.EDD_SUBMITTED, L.EDD_RETURNED, user.id, reason.strip())
    db.commit()


def new_review(customer_id, user_id, db=None):
    """Start a fresh EDD review (periodic or trigger) after an approved one."""
    db = db or get_db()
    cur = latest_case(customer_id, db)
    if cur and L.edd_status(cur) != L.EDD_APPROVED:
        raise EddError('An EDD record is already in progress for this customer.')
    return open_case(customer_id, [], user_id, db, trigger='periodic_review')


def history(case_id, db=None):
    db = db or get_db()
    return [dict(r) for r in db.execute(
        """SELECT h.*, TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS user_name
             FROM edd_case_history h LEFT JOIN users u ON u.id = h.user_id
            WHERE h.edd_case_id = %s ORDER BY h.id DESC""", (case_id,)).fetchall()]


def user_name(user_id, db=None):
    if not user_id:
        return None
    db = db or get_db()
    r = db.execute("SELECT first_name, last_name, email FROM users WHERE id = %s", (user_id,)).fetchone()
    if not r:
        return None
    return (f"{r['first_name'] or ''} {r['last_name'] or ''}".strip()) or r['email']


# ----------------------------------------------------------------------------- activation

def activation_blockers(customer, db=None):
    db = db or get_db()
    kyb_b = []
    if _is_entity(customer):
        from kyb import service as kyb
        kyb_b = kyb.blockers('aml_customer', customer['id'], db)
    return L.activation_blockers(customer, customer.get('requires_edd'), latest_case(customer['id'], db), kyb_b)


def activate(customer_id, user, note=None, db=None):
    db = db or get_db()
    row = db.execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone()
    if not row:
        raise EddError('Customer not found.')
    c = dict(row)
    if (c.get('status') or '') == 'ACTIVE':
        raise EddError('The customer is already active.')
    reassess(customer_id, user.id, db=db)
    c = dict(db.execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone())
    b = activation_blockers(c, db)
    if b:
        raise EddError(b)
    db.execute("""UPDATE customers SET status = 'ACTIVE', approved_by = %s, approval_date = %s, status_reason = %s,
                  updated_by = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s""",
               (user.id, date.today().isoformat(), (note or '').strip() or 'Approved for activation', user.id,
                customer_id))
    db.commit()
    return c.get('status')


def list_summary(db=None):
    """{customer_id: latest edd case dict} for the customer list."""
    db = db or get_db()
    return {r['customer_id']: dict(r) for r in db.execute(
        """SELECT DISTINCT ON (customer_id) id, customer_id, status, approved_by
             FROM edd_cases WHERE customer_id IS NOT NULL ORDER BY customer_id, id DESC""").fetchall()}
