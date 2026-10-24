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
Readable, translated labels for the codes the screening module stores
(statuses, decisions, entity types, list names), so no page shows a raw code
such as FALSE_POSITIVE or ofac_sdn. Used in templates as
``{{ value|scr_label }}`` or ``{{ value|scr_label('source') }}``.
"""
from flask_babel import lazy_gettext as _l

STATUS = {
    # queue
    'pending': _l('Pending'), 'in review': _l('In Review'), 'resolved': _l('Resolved'),
    'pending mlro approval': _l('Pending MLRO approval'),
    # results / history
    'pending_approval': _l('Pending MLRO approval'), 'true_hit': _l('True match'),
    'false_positive': _l('False positive'), 'completed': _l('Completed'),
    'pending review': _l('Pending review'), 'clear': _l('Clear'),
    # screening outcome
    'confirmed_hit': _l('Confirmed hit'), 'potential_match': _l('Potential match'),
    'low_match': _l('Low match'), 'review_required': _l('Review required'),
    'white_listed': _l('Whitelisted'), 'whitelisted': _l('Whitelisted'), 'blocked': _l('Blocked'),
    'error': _l('Error'),
    # whitelist
    'active': _l('Active'), 'pending approval': _l('Pending MLRO approval'), 'rejected': _l('Rejected'),
    'expired': _l('Review due'), 'revoked': _l('Revoked'), 'requires review': _l('Requires review'),
    'confirmed match': _l('Confirmed match'), 'under investigation': _l('Under investigation'),
    # alerts / findings / confirmed matches
    'open': _l('Open'), 'closed': _l('Closed'), 'escalated': _l('Escalated'), 'reviewed': _l('Reviewed'),
    'accepted': _l('Accepted'), 'reported': _l('Reported'),
    # clearance requests
    'approved': _l('Approved'),
    # resolutions
    'false positive': _l('False positive'), 'false positive (bulk)': _l('False positive (bulk)'),
    'true match - block': _l('True match — blocked'), 'true match - block (bulk)': _l('True match — blocked (bulk)'),
    'pep - flag': _l('PEP — flagged'),
    # priority
    'high': _l('High'), 'medium': _l('Medium'), 'low': _l('Low'), 'critical': _l('Critical'),
}

DECISION = {
    'false_positive': _l('False positive (clear)'), 'FALSE_POSITIVE': _l('False positive (clear)'),
    'true_match': _l('True match (block)'), 'TRUE_HIT': _l('True match (block)'),
    'pep': _l('PEP (enhanced due diligence)'), 'escalate': _l('Escalate'),
}

ACTION = {
    'proposed': _l('Decision submitted for MLRO approval'), 'approved': _l('Approved by MLRO'),
    'rejected': _l('Rejected by MLRO'), 'decided': _l('Decided'), 'confirmed_match': _l('Confirmed match'),
    'escalated': _l('Escalated'),
    # whitelist audit
    'requested': _l('Requested'), 'renewed': _l('Renewed'), 'revoked': _l('Revoked'),
    'reinstated': _l('Reinstated'), 'reinstate_requested': _l('Reinstatement requested'),
    'confirm_false_positive': _l('Confirmed false positive'), 'confirm_true_match': _l('Confirmed true match'),
    'hold': _l('Held for investigation'), 'reopen': _l('Reopened for review'),
}

ENTITY = {
    'individual': _l('Individual'), 'person': _l('Individual'), 'entity': _l('Entity'),
    'organization': _l('Organisation'), 'organisation': _l('Organisation'), 'company': _l('Company'),
    'corporate': _l('Company'), 'vessel': _l('Vessel'), 'aircraft': _l('Aircraft'), 'unknown': _l('Unknown'),
}

SOURCE = {
    'ofac': _l('OFAC SDN (US Treasury)'), 'ofac_sdn': _l('OFAC SDN (US Treasury)'),
    'un': _l('UN Security Council Consolidated List'), 'un_consolidated': _l('UN Security Council Consolidated List'),
    'eu': _l('EU Financial Sanctions'), 'eu_sanctions': _l('EU Financial Sanctions'),
    'uk_hmt': _l('UK HM Treasury (OFSI)'), 'hmt': _l('UK HM Treasury (OFSI)'), 'uk': _l('UK HM Treasury (OFSI)'),
    'emlcu': _l('EMLCU — Egyptian terrorist lists'), 'emlcu_egypt': _l('EMLCU — Egyptian terrorist lists'),
    'internal_blacklist': _l('Internal list (asset-freeze orders / local & UN terrorist lists)'),
    'internal blacklist': _l('Internal list (asset-freeze orders / local & UN terrorist lists)'),
    'internal_pep': _l('Internal PEP list'), 'opensanctions': _l('OpenSanctions'),
    'opensanctions_pep': _l('Global PEP database (OpenSanctions)'),
    'open_sanctions_pep_eg': _l('Egypt PEP (OpenSanctions)'), 'wikidata_pep_eg': _l('Egypt PEP (Wikidata)'),
    'adverse media': _l('Adverse media'), 'unknown': _l('Unknown list'),
    'screening adjudication': _l('Screening adjudication'),
}

MODULE = {
    'merchant kyc': _l('Merchant KYC'), 'customer kyc': _l('Customer KYC'), 'ekyc': _l('eKYC'),
    'manual': _l('Manual'), 'api': _l('API'), 'bulk': _l('Bulk'),
    'manual_ad-hoc': _l('Manual (ad hoc)'), 'manual ad-hoc': _l('Manual (ad hoc)'), 'manual_ad_hoc': _l('Manual (ad hoc)'),
}

_KINDS = {'status': STATUS, 'decision': DECISION, 'action': ACTION, 'entity': ENTITY,
          'source': SOURCE, 'module': MODULE}


def label(value, kind='status'):
    """Translated label for a stored code; the value itself when unknown."""
    if value is None or value == '':
        return value
    table = _KINDS.get(kind, STATUS)
    v = str(value)
    hit = table.get(v)
    if hit is None:
        k = v.strip().lower()
        hit = table.get(k) or table.get(k.replace('_', ' ')) or table.get(k.replace(' ', '_'))
    if hit is None and kind == 'source':
        # list codes the module knows a long name for
        try:
            from screening.result_view import SOURCE_LABEL
            name = SOURCE_LABEL.get(v) or SOURCE_LABEL.get(v.lower())
            if name:
                return name
        except Exception:
            pass
    if hit is not None:
        return str(hit)
    from utils.labels import label as _generic_label
    out = _generic_label(v)      # unknown code -> readable, translated form (never the raw code)
    return out if isinstance(out, str) else v
