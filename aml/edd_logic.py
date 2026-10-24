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
Pure decision logic for customer risk floors and Enhanced Due Diligence (EDD).
No Flask, no database: callers pass rows and lists in, so the rules can be
unit-tested and reused by any onboarding path (form, API, eKYC).

Rules
- A customer is HIGH risk, whatever the scoring model says, when
  (a) the customer (or, for an entity, a beneficial owner / signatory) is a PEP,
  (b) screening links the customer to a sanctions / PEP list entry that is not
      cleared as a false positive, or
  (c) the customer is connected to a country on the configurable high-risk list
      (nationality, residence, registration, or an owner's nationality).
- A HIGH customer needs an approved EDD record before it can be activated.
- EDD is prepared by one person and approved by another (MLRO / senior
  manager): four-eyes.
"""

import re
import unicodedata
from datetime import date

# ----------------------------------------------------------------------------- countries

def norm_country(value):
    s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode() \
        if re.search(r'[A-Za-z]', str(value or '')) else str(value or '')
    s = re.sub(r"[^\w\s]", ' ', s.upper())
    return re.sub(r'\s+', ' ', s).strip()


def country_keys(row):
    """Every spelling that identifies a high-risk country row."""
    keys = {row.get('country_code'), row.get('country_name'), row.get('name_ar')}
    keys.update((row.get('aliases') or '').split('|'))
    return {norm_country(k) for k in keys if k and str(k).strip()}


def match_country(value, rows):
    """The active high-risk country row that `value` names, or None."""
    v = norm_country(value)
    if not v:
        return None
    for r in rows:
        if r.get('is_active') in (0, False):
            continue
        if v in country_keys(r):
            return r
    return None


# ----------------------------------------------------------------------------- risk floor

# Screening queue resolutions that do NOT link the customer to a list entry.
_CLEARED = ('false positive',)


def screening_link(queue_items):
    """Classify screening queue items of one subject.

    queue_items: dicts with status, resolution, list_source.
    Returns 'open' (a potential match still being worked), 'confirmed'
    (true match), 'pep' (accepted as a PEP), or None (no link / all cleared).
    """
    state = None
    for q in queue_items or []:
        res = (q.get('resolution') or '').lower()
        if (q.get('status') or '') != 'Resolved':
            return 'open'
        if 'true match' in res or 'block' in res:
            state = 'confirmed'
        elif 'pep' in res and state != 'confirmed':
            state = 'pep'
    return state


def forced_high_reasons(customer, hr_rows, screening_state=None, owners=()):
    """Reasons that force a customer to HIGH risk (untranslated, short).

    customer: dict with is_pep, nationality, country, registration_country.
    hr_rows: high-risk country rows. screening_state: result of screening_link()
    for the customer itself. owners: beneficial owners / signatories as dicts
    with full_name, nationality, is_pep, screening_state.
    Returns a list of (code, detail) tuples.
    """
    out = []
    if customer.get('is_pep') in (1, True, '1', 'on'):
        out.append(('pep', 'politically exposed person'))
    if screening_state in ('open', 'confirmed', 'pep'):
        out.append(('screening', {'open': 'potential sanctions / PEP match under review',
                                  'confirmed': 'confirmed sanctions match',
                                  'pep': 'screening identified a PEP'}[screening_state]))
    seen = set()
    for field in ('nationality', 'country', 'registration_country'):
        r = match_country(customer.get(field), hr_rows)
        if r and r.get('country_name') not in seen:
            seen.add(r.get('country_name'))
            out.append(('country', r.get('country_name')))
    for o in owners or ():
        name = o.get('full_name') or ''
        if o.get('is_pep') in (1, True):
            out.append(('owner_pep', name))
        if o.get('screening_state') in ('open', 'confirmed', 'pep'):
            out.append(('owner_screening', name))
        r = match_country(o.get('nationality'), hr_rows)
        if r:
            out.append(('owner_country', f"{name} ({r.get('country_name')})"))
    return out


def final_classification(model_class, reasons, override_class=None):
    """HIGH when any forcing reason exists; otherwise a manual override wins
    over the model."""
    if reasons:
        return 'HIGH'
    return (override_class or model_class or 'LOW').upper()


# ----------------------------------------------------------------------------- EDD record

EDD_OPEN = 'OPEN'            # being prepared
EDD_SUBMITTED = 'SUBMITTED'  # waiting for MLRO / senior manager approval
EDD_RETURNED = 'RETURNED'    # sent back to the preparer with a reason
EDD_APPROVED = 'APPROVED'
# statuses written by older code / the demo seed
_LEGACY = {'IN_PROGRESS': EDD_OPEN, 'PENDING': EDD_OPEN, 'NEW': EDD_OPEN, 'COMPLETED': EDD_APPROVED}

MONITORING_FREQUENCIES = ('Monthly', 'Quarterly', 'Semi-annual')

CHECKLIST = (
    ('source_of_wealth', 'Source of wealth'),
    ('source_of_funds', 'Source of funds with evidence'),
    ('purpose_nature', 'Purpose and intended nature of the relationship'),
    ('monitoring', 'Enhanced monitoring frequency'),
    ('next_review', 'Next review date'),
    ('senior_approval', 'Senior management approval'),
)


def edd_status(case):
    if not case:
        return None
    s = (case.get('status') or EDD_OPEN).upper()
    return _LEGACY.get(s, s)


def _filled(v, n=3):
    return bool(v) and len(str(v).strip()) >= n


def checklist(case, evidence_count=0, today=None):
    """[(key, label, done)] for an EDD record. Source of funds counts only with
    evidence: an attached document or a written description of what is held."""
    today = today or date.today()
    case = case or {}
    nr = case.get('next_review_date')
    if isinstance(nr, str):
        try:
            nr = date.fromisoformat(nr[:10])
        except ValueError:
            nr = None
    done = {
        'source_of_wealth': _filled(case.get('source_of_wealth')),
        'source_of_funds': _filled(case.get('source_of_funds')) and (evidence_count > 0 or _filled(case.get('sof_evidence'))),
        'purpose_nature': _filled(case.get('purpose_nature')),
        'monitoring': (case.get('enhanced_monitoring_frequency') or '') in MONITORING_FREQUENCIES,
        'next_review': bool(nr and nr > today),
        'senior_approval': edd_status(case) == EDD_APPROVED and bool(case.get('approved_by')),
    }
    return [(k, label, done[k]) for k, label in CHECKLIST]


def missing_for_submission(case, evidence_count=0, today=None):
    """Checklist items (labels) still open before the preparer can submit."""
    return [label for k, label, ok in checklist(case, evidence_count, today) if not ok and k != 'senior_approval']


def can_edit(case):
    return edd_status(case) in (EDD_OPEN, EDD_RETURNED)


def four_eyes_error(approver_id, preparer_id):
    if approver_id is not None and preparer_id is not None and approver_id == preparer_id:
        return 'you prepared this EDD; another person must approve it'
    return None


def approver_role_ok(role, can_view_aml):
    """MLRO (compliance manager), administrator, or a senior manager who can see AML."""
    return role in ('compliance_manager', 'admin') or (role == 'manager' and bool(can_view_aml))


def display_status(requires_edd, case):
    """One code for lists and badges."""
    s = edd_status(case)
    if s == EDD_APPROVED:
        return 'approved'
    if not requires_edd and not s:
        return 'not_required'
    return {None: 'not_started', EDD_OPEN: 'in_preparation', EDD_SUBMITTED: 'awaiting_approval',
            EDD_RETURNED: 'returned'}.get(s, 'in_preparation')


def is_pending(requires_edd, case):
    return bool(requires_edd) and edd_status(case) != EDD_APPROVED


def activation_blockers(customer, requires_edd, case, kyb_blockers=()):
    """Why a customer cannot be activated (untranslated)."""
    out = []
    if requires_edd and edd_status(case) != EDD_APPROVED:
        out.append('high risk: EDD must be completed and approved first')
    out.extend(kyb_blockers or ())
    return out
