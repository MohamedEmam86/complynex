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

"""Pure KYB rules — no Flask, no database."""

import hashlib
from decimal import Decimal, InvalidOperation

CONTROL_TYPES = ('ownership', 'control', 'senior_manager')
SIGNING_AUTHORITIES = ('sole', 'joint')
ID_TYPES = ('NATIONAL_ID', 'PASSPORT', 'RESIDENCE_PERMIT')
LEGAL_FORMS = ('SOLE_PROPRIETORSHIP', 'PARTNERSHIP', 'LIMITED_PARTNERSHIP', 'LLC', 'ONE_PERSON_COMPANY',
               'JOINT_STOCK', 'BRANCH_FOREIGN', 'NGO', 'GOVERNMENT', 'OTHER')
UBO_THRESHOLD = Decimal('25')


def M(msgid, **params):
    """An untranslated message with its parameters; the page translates it."""
    return (msgid, params)

# entity fields every KYB file needs (licence fields are optional)
REQUIRED_ENTITY_FIELDS = (
    ('cr_number', 'Commercial register number'),
    ('tax_card_number', 'Tax card number'),
    ('legal_form', 'Legal form'),
    ('incorporation_date', 'Incorporation date'),
    ('incorporation_country', 'Country of incorporation'),
)


def pct(v):
    """Ownership percentage as Decimal, None when blank; raises ValueError when not a number."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return Decimal(str(v).strip().replace('%', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        raise ValueError('not a number')


def validate_ubos(ubos):
    """Validate a complete set of beneficial owners.

    ubos: dicts with full_name, ownership_pct, control_type.
    Returns (errors, warnings), untranslated.
    """
    errors, warnings = [], []
    total = Decimal('0')
    for u in ubos:
        name = (u.get('full_name') or '').strip()
        if not name:
            errors.append(M('Every beneficial owner needs a name.'))
        if (u.get('control_type') or 'ownership') not in CONTROL_TYPES:
            errors.append(M('Invalid control type for %(name)s.', name=name))
        try:
            p = pct(u.get('ownership_pct'))
        except ValueError:
            errors.append(M('Ownership of %(name)s is not a number.', name=name))
            continue
        if p is None:
            continue
        if p < 0 or p > 100:
            errors.append(M('Ownership of %(name)s must be between 0 and 100.', name=name))
        else:
            total += p
    if total > Decimal('100.001'):
        errors.append(M('Total ownership is %(total)s%%; it cannot exceed 100%%.', total=_fmt(total)))
    if ubos and not errors:
        owners_25 = [u for u in ubos if (pct(u.get('ownership_pct')) or 0) >= UBO_THRESHOLD]
        controllers = [u for u in ubos if (u.get('control_type') or 'ownership') in ('control', 'senior_manager')]
        if not owners_25 and not controllers:
            warnings.append(M('No owner holds 25%% or more and no controlling person is named.'))
    return errors, warnings


def _fmt(d):
    return format(d.normalize(), 'f') if isinstance(d, Decimal) else str(d)


def total_ownership(ubos):
    t = Decimal('0')
    for u in ubos:
        try:
            t += pct(u.get('ownership_pct')) or 0
        except ValueError:
            pass
    return t


def screen_key(person):
    """Fingerprint of the identity data that screening uses; a change means re-screen."""
    raw = '|'.join(str(person.get(k) or '').strip().lower()
                   for k in ('full_name', 'date_of_birth', 'nationality', 'id_number'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


# screening states shown per person
NOT_SCREENED, CLEAR, CLEARED, OPEN, CONFIRMED, PEP, ERROR = (
    'not_screened', 'clear', 'cleared', 'open', 'confirmed', 'pep', 'error')
INCOMPLETE = 'incomplete'          # P4-1: a screening source was unavailable; screen again
BLOCKING_STATES = (NOT_SCREENED, OPEN, CONFIRMED, ERROR, INCOMPLETE)
# worst first (G10: a company's status is the worst of its own and its parties')
SEVERITY = (CONFIRMED, OPEN, INCOMPLETE, ERROR, NOT_SCREENED, PEP, CLEARED, CLEAR)


def worst_state(states):
    """The most severe of several screening states (None for an empty list)."""
    rank = {s: i for i, s in enumerate(SEVERITY)}
    states = [s for s in states or [] if s]
    return min(states, key=lambda s: rank.get(s, len(SEVERITY))) if states else None


def screening_state(person, history, queue_items):
    """State of one person's latest screening.

    person: row with screening_history_id, screening_error, screened_key (+ identity fields).
    history: the screening_history row (or None). queue_items: its screening_queue rows.
    """
    if person.get('screening_error') and not person.get('screening_history_id'):
        return ERROR
    if not person.get('screening_history_id') or not history:
        return NOT_SCREENED
    if person.get('screened_key') and person.get('screened_key') != screen_key(person):
        return NOT_SCREENED          # identity changed since the last screening
    has_pep = False
    has_fp = False
    for q in queue_items or []:
        if (q.get('status') or '') != 'Resolved':
            return OPEN
        res = (q.get('resolution') or '').lower()
        if 'true match' in res or 'block' in res:
            return CONFIRMED
        if 'pep' in res:
            has_pep = True
        else:
            has_fp = True
    if (history.get('screening_result') or '') == 'INCOMPLETE':
        return INCOMPLETE            # a source was down: "no open hit" is not proven
    if has_pep:
        return PEP
    if (history.get('screening_result') or '') == 'POTENTIAL_MATCH' and not queue_items:
        return OPEN
    return CLEARED if has_fp else CLEAR


def entity_missing(entity):
    """Required entity fields that are empty (untranslated labels)."""
    return [label for key, label in REQUIRED_ENTITY_FIELDS if not str(entity.get(key) or '').strip()]


def approval_blockers(entity, ubos, signatories, states):
    """Everything that stops a legal entity from being approved (untranslated).

    states: {('ubo'|'signatory', id): screening state}.
    """
    out = []
    missing = entity_missing(entity)
    if missing:
        out.append(M('KYB file incomplete: %(fields)s', fields=missing))
    if not ubos:
        out.append(M('No beneficial owner recorded.'))
    else:
        errs, _w = validate_ubos(ubos)
        out.extend(errs)
    if not signatories:
        out.append(M('No authorised signatory recorded.'))
    so = sanctioned_ownership(ubos, states)
    if so['deemed_sanctioned']:
        out.append(M('Aggregate sanctioned ownership is %(pct)s%% (threshold %(threshold)s%%, 50%% rule): escalate to '
                     'the MLRO immediately with the evidence; decisions and any action on the relationship are '
                     'taken outside this system.', pct=_fmt(so['pct']), threshold=_fmt(so['threshold'])))
    for kind, rows in (('ubo', ubos), ('signatory', signatories)):
        for r in rows:
            st = states.get((kind, r['id']), NOT_SCREENED)
            if st in BLOCKING_STATES:
                msg = {('ubo', NOT_SCREENED): 'Beneficial owner %(name)s has not been screened.',
                       ('ubo', OPEN): 'Screening hit on beneficial owner %(name)s is still open.',
                       ('ubo', CONFIRMED): 'Beneficial owner %(name)s is a confirmed sanctions match.',
                       ('ubo', ERROR): 'Screening of beneficial owner %(name)s failed; screen again.',
                       ('signatory', NOT_SCREENED): 'Signatory %(name)s has not been screened.',
                       ('signatory', OPEN): 'Screening hit on signatory %(name)s is still open.',
                       ('signatory', CONFIRMED): 'Signatory %(name)s is a confirmed sanctions match.',
                       ('signatory', ERROR): 'Screening of signatory %(name)s failed; screen again.',
                       ('ubo', INCOMPLETE): 'Screening of beneficial owner %(name)s was incomplete (a source was unavailable); screen again.',
                       ('signatory', INCOMPLETE): 'Screening of signatory %(name)s was incomplete (a source was unavailable); screen again.'}[(kind, st)]
                out.append(M(msg, name=r.get('full_name')))
    return out


# OFAC 50% rule: an entity owned 50% or more, directly and in aggregate, by sanctioned
# persons is itself covered. ComplyNex only ALERTS: the page and the approval blockers tell
# the user to escalate to the MLRO; nothing is frozen or blocked here.
# TODO(compliance-review): indirect ownership through intermediate companies is not modelled;
# the page tells the user to record the owning company as an owner with its stake.
OFAC_AGGREGATE_THRESHOLD = Decimal('50')


def sanctioned_ownership(ubos, states, threshold=OFAC_AGGREGATE_THRESHOLD):
    """Aggregate sanctioned ownership: the recorded stakes of the owners who are
    confirmed sanctions matches. Every recorded stake counts, whatever the control
    type (a person recorded as 'control' or 'senior_manager' with a stake still
    owns it; control types are CONTROL_TYPES, and an unexpected value is not a
    reason to drop a stake). Returns {'pct', 'owners', 'deemed_sanctioned', 'threshold'}."""
    total, owners = Decimal('0'), []
    for u in ubos or []:
        if states.get(('ubo', u['id'])) != CONFIRMED:
            continue
        try:
            p = pct(u.get('ownership_pct')) or Decimal('0')
        except ValueError:
            p = Decimal('0')
        if p <= 0:
            continue                   # control without a recorded stake: not ownership
        total += p                 # a person on two rows holds both stakes (aggregate)
        if u.get('full_name') not in owners:
            owners.append(u.get('full_name'))
    return {'pct': total, 'owners': owners, 'deemed_sanctioned': total >= threshold, 'threshold': threshold}


PALESTINE_KEYS = ('PS', 'PSE', 'PALESTINE', 'PALESTINIAN', 'STATE OF PALESTINE', 'فلسطين', 'فلسطيني', 'فلسطينية')


def palestinian_parties(entity, people):
    """Names of the entity / owners / signatories tied to Palestine (incorporation or nationality),
    for whom the supervisor's regulatory-measures list (PMA) is relevant."""
    def tied(v):
        return str(v or '').strip().upper() in PALESTINE_KEYS
    out = []
    if entity and tied(entity.get('incorporation_country')):
        out.append(entity.get('name'))
    out += [p.get('full_name') for p in people or [] if tied(p.get('nationality'))]
    return [n for n in out if n]


def main_owner(ubos):
    """The owner with the largest stake (for older single-UBO consumers)."""
    best, best_p = None, Decimal('-1')
    for u in ubos:
        try:
            p = pct(u.get('ownership_pct'))
        except ValueError:
            p = None
        p = p if p is not None else Decimal('-0.5')
        if p > best_p:
            best, best_p = u, p
    return best


def sanctions_summary(entity_checked, people):
    """Sanctions check of a corporate file: the entity itself and every
    beneficial owner / signatory (each with 'screening_state'). Checked only
    when the entity and all persons (at least one declared) have a current
    screening."""
    total = len(people or [])
    screened = sum(1 for p in people or [] if p.get('screening_state') not in (NOT_SCREENED, ERROR, INCOMPLETE, None))
    open_ = sum(1 for p in people or [] if p.get('screening_state') in (OPEN, CONFIRMED))
    return {'entity': bool(entity_checked), 'people_total': total, 'people_screened': screened,
            'people_open': open_, 'complete': bool(entity_checked) and total > 0 and screened == total}
