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
G10 — a company is screened together with its related parties.

The KYB register (kyb/service.py) already holds each legal entity's beneficial owners
(ownership, control and senior managers) and authorised signatories, and screens each
person when their identity data changes. This module makes the PARENT's screening cover
them:

  after_parent_screening()  called when a merchant or a corporate customer is screened
                            (merchant screening, customer CDD / onboarding, scheduled
                            re-screening): every related party is screened again, each as a
                            normal stored screening (its own result, queue items, evidence
                            pack and clearances), and the parent's screening status becomes
                            the worst of its own and its parties' (a party hit -> the parent
                            needs review; a party screening that was incomplete or failed ->
                            the parent is "Incomplete").
  overview() / for_result() the parties section of the parent's result and record pages.

Fails safe for the parent: an error here never clears the parent; it is logged and the
parent keeps the status its own screening gave.
"""
import logging
from collections import Counter

from . import logic

log = logging.getLogger(__name__)

SUBJECT_BY_MODULE = {'Merchant KYC': 'merchant', 'Customer KYC': 'aml_customer'}
STATUS_TABLE = {'merchant': 'merchants', 'aml_customer': 'customers'}
ROLE_LABEL = {'ubo': 'Beneficial owner', 'signatory': 'Authorised signatory'}
CONTROL_LABEL = {'ownership': 'Ownership', 'control': 'Control', 'senior_manager': 'Senior manager'}
MAX_PARTIES = 60                  # a larger register is screened from its KYB page, not inline


def is_corporate(subject, record):
    if not record:
        return False
    if subject == 'merchant':
        return True
    return str(record.get('customer_type') or '').upper() not in ('INDIVIDUAL', '')


def combined_status(own_status, worst):
    """Parent screening status (the merchants / customers screening_status wording)
    combined with the worst state of its related parties."""
    own = own_status or 'Clear'
    if worst in (logic.OPEN, logic.CONFIRMED):
        return 'Pending Review'
    if worst in (logic.INCOMPLETE, logic.ERROR, logic.NOT_SCREENED) and own in ('Clear', 'Whitelisted'):
        return 'Incomplete'
    return own


def overview(subject, subject_id, db=None):
    """{'people': [...], 'worst': state, 'counts': {state: n}, 'total': n} for one register record."""
    from . import service
    db = db or service.get_db()
    ubos, sigs, _states = service.with_states(subject, subject_id, db)
    people = []
    for kind, rows in (('ubo', ubos), ('signatory', sigs)):
        for p in rows:
            h = p.get('screening') or {}
            people.append({
                'kind': kind, 'id': p.get('id'), 'name': p.get('full_name'),
                'role': ROLE_LABEL[kind],
                'detail': (CONTROL_LABEL.get(p.get('control_type') or 'ownership', '')
                           + (f" {p.get('ownership_pct')}%" if p.get('ownership_pct') is not None else ''))
                          if kind == 'ubo' else ' '.join(x for x in (p.get('position'), p.get('signing_authority')) if x),
                'state': p.get('screening_state') or logic.NOT_SCREENED,
                'history_id': p.get('screening_history_id'),
                'screened_at': p.get('screened_at'),
                'result': h.get('screening_result'),
                'score': h.get('highest_score'),
            })
    hids = [x['history_id'] for x in people if x['history_id']]
    if hids:
        try:
            for r in db.execute("SELECT id, screening_result_id FROM screening_history WHERE id = ANY(%s)",
                                (hids,)).fetchall():
                for x in people:
                    if x['history_id'] == r['id']:
                        x['result_id'] = r['screening_result_id']
        except Exception:
            db.rollback()
    states = [x['state'] for x in people]
    return {'people': people, 'worst': logic.worst_state(states) if people else None,
            'counts': dict(Counter(states)), 'total': len(people)}


def after_parent_screening(source_module, source_record_id, user_id, db=None):
    """Screen the related parties of the record that was just screened and fold their worst
    state into its screening status. Returns {'subject', 'overview', 'status'} or None."""
    subject = SUBJECT_BY_MODULE.get(source_module)
    if not subject or not source_record_id:
        return None
    from . import service
    db = db or service.get_db()
    try:
        rec = service.record(subject, source_record_id, db)
        if not is_corporate(subject, rec):
            return None
        n = 0
        for kind in ('ubo', 'signatory'):
            n += len(service.people(kind, subject, source_record_id, db))
        if not n:
            return None
        if n <= MAX_PARTIES:
            service.screen_all(subject, source_record_id, user_id, only_needed=False, db=db)
        else:
            log.info('G10: %s %s has %s parties; only changed ones are screened inline', subject, source_record_id, n)
            service.screen_all(subject, source_record_id, user_id, only_needed=True, db=db)
        ov = overview(subject, source_record_id, db)
        rec = service.record(subject, source_record_id, db) or rec
        own = rec.get('screening_status')
        new = combined_status(own, ov['worst'])
        if new != own:
            db.execute(f"UPDATE {STATUS_TABLE[subject]} SET screening_status = %s WHERE id = %s",
                       (new, source_record_id))
            db.commit()
        return {'subject': subject, 'overview': ov, 'status': new}
    except Exception:
        log.exception('G10: related-party screening failed for %s %s', subject, source_record_id)
        try:
            db.rollback()
            # the parties were not proven clear: the parent cannot read clear
            db.execute(f"UPDATE {STATUS_TABLE[subject]} SET screening_status = 'Incomplete' "
                       f"WHERE id = %s AND screening_status IN ('Clear', 'Whitelisted')", (source_record_id,))
            db.commit()
        except Exception:
            pass
        return None


def for_result(results_id, db=None):
    """Parties section of a screening result page: the parent record behind the result
    (merchant / corporate customer) with every related party's latest state."""
    from . import service
    db = db or service.get_db()
    try:
        h = db.execute("""SELECT source_module, source_record_id FROM screening_history
                           WHERE screening_result_id = %s ORDER BY id DESC LIMIT 1""", (results_id,)).fetchone()
        if not h:
            return None
        subject = SUBJECT_BY_MODULE.get(h['source_module'])
        if not subject or not h['source_record_id']:
            return None
        rec = service.record(subject, h['source_record_id'], db)
        if not is_corporate(subject, rec):
            return None
        ov = overview(subject, h['source_record_id'], db)
        if not ov['people']:
            return {'subject': subject, 'record_id': h['source_record_id'], 'overview': ov,
                    'name': service.SUBJECTS[subject]['name'](rec), 'status': rec.get('screening_status')}
        return {'subject': subject, 'record_id': h['source_record_id'], 'overview': ov,
                'name': service.SUBJECTS[subject]['name'](rec), 'status': rec.get('screening_status')}
    except Exception:
        log.exception('G10: parties section unavailable for result %s', results_id)
        try:
            db.rollback()
        except Exception:
            pass
        return None
