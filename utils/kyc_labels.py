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
Display labels (English msgids, translated with gettext) for KYC / KYB / EDD
codes stored in the database, plus a translator for the (msgid, params)
messages that the pure rule modules return.

Templates:  {{ customer.risk_classification|kyc_label('risk') }}
            {{ message|kyc_msg }}
"""

from flask_babel import gettext


def N_(s):
    return s


LABELS = {
    'risk': {'LOW': N_('Low'), 'MEDIUM': N_('Medium'), 'HIGH': N_('High'), 'CRITICAL': N_('Critical')},
    'entity_type': {'INDIVIDUAL': N_('Individual'), 'CORPORATE': N_('Corporate'), 'ENTITY': N_('Entity')},
    'customer_status': {'ACTIVE': N_('Active'), 'PENDING': N_('Pending'), 'UNDER_REVIEW': N_('Under review'),
                        'SUSPENDED': N_('Suspended'), 'CLOSED': N_('Closed'), 'BLOCKED': N_('Blocked'),
                        'REJECTED': N_('Rejected'), 'INACTIVE': N_('Inactive')},
    'kyc_status': {'PENDING': N_('Pending'), 'SENT': N_('Link sent'), 'SUBMITTED': N_('Submitted for approval'),
                   'UNDER_REVIEW': N_('Under review'), 'APPROVED': N_('Approved'), 'REJECTED': N_('Rejected')},
    'screening_status': {'Clear': N_('Clear'), 'Pending Review': N_('Pending review'), 'Not Screened': N_('Not screened'),
                         'Blocked': N_('Blocked'), 'PEP': N_('PEP'), 'Whitelisted': N_('Whitelisted'),
                         'Cleared': N_('Cleared (false positive)')},
    'edd': {'not_required': N_('Not required'), 'not_started': N_('EDD not started'),
            'in_preparation': N_('EDD in preparation'), 'awaiting_approval': N_('EDD awaiting approval'),
            'returned': N_('EDD returned'), 'approved': N_('EDD approved')},
    'edd_status': {'OPEN': N_('In preparation'), 'SUBMITTED': N_('Awaiting approval'), 'RETURNED': N_('Returned'),
                   'APPROVED': N_('Approved')},
    'edd_action': {'opened': N_('Opened'), 'saved': N_('Saved'), 'submitted': N_('Submitted for approval'),
                   'approved': N_('Approved'), 'returned': N_('Returned')},
    'screening': {'not_screened': N_('Not screened'), 'clear': N_('Clear'), 'cleared': N_('Cleared (false positive)'),
                  'open': N_('Potential match - open'), 'confirmed': N_('Confirmed match'), 'pep': N_('PEP'),
                  'error': N_('Screening failed')},
    'legal_form': {'SOLE_PROPRIETORSHIP': N_('Sole proprietorship'), 'PARTNERSHIP': N_('General partnership'),
                   'LIMITED_PARTNERSHIP': N_('Limited partnership'), 'LLC': N_('Limited liability company'),
                   'ONE_PERSON_COMPANY': N_('One-person company'), 'JOINT_STOCK': N_('Joint stock company'),
                   'BRANCH_FOREIGN': N_('Branch of a foreign company'), 'NGO': N_('NGO / foundation'),
                   'GOVERNMENT': N_('Government entity'), 'OTHER': N_('Other')},
    'control_type': {'ownership': N_('Ownership'), 'control': N_('Control by other means'),
                     'senior_manager': N_('Senior managing official')},
    'signing_authority': {'sole': N_('Sole signatory'), 'joint': N_('Joint signatory')},
    'id_type': {'NATIONAL_ID': N_('National ID'), 'PASSPORT': N_('Passport'),
                'RESIDENCE_PERMIT': N_('Residence permit'), 'COMMERCIAL_REG': N_('Commercial Register')},
    'monitoring': {'Monthly': N_('Monthly'), 'Quarterly': N_('Quarterly'), 'Semi-annual': N_('Semi-annual')},
    'merchant_action': {'created': N_('Created'), 'link_sent': N_('KYB link sent'),
                        'submitted': N_('Submitted for approval'), 'resubmitted': N_('Resubmitted after rejection'), 'public_submitted': N_('Submitted by the merchant'),
                        'approved': N_('Approved'), 'rejected': N_('Rejected'), 'status_changed': N_('Status changed')},
    'hr_category': {'CALL_FOR_ACTION': N_('Call for action (black list)'),
                    'INCREASED_MONITORING': N_('Increased monitoring (grey list)'), 'INTERNAL': N_('Internal decision')},
}


def label(code, category):
    if code is None or code == '':
        return ''
    table = LABELS.get(category, {})
    s = table.get(code)
    if s is None and isinstance(code, str):
        s = table.get(code.upper()) or table.get(code.lower()) or table.get(code.title())
    return gettext(s) if s else str(code)


def tr(msg):
    """Translate an untranslated rule message: str, or (msgid, params)."""
    if isinstance(msg, (tuple, list)) and len(msg) == 2 and isinstance(msg[0], str):
        msgid, params = msg
        if isinstance(params, dict):
            params = {k: (', '.join(gettext(x) for x in v) if isinstance(v, (list, tuple)) else v)
                      for k, v in params.items()}
            return gettext(msgid, **params)
        if isinstance(params, (list, tuple)):        # ('... %(items)s', [labels])
            return gettext(msgid, items=', '.join(gettext(x) for x in params))
    return gettext(str(msg))


def register(bp):
    bp.app_template_filter('kyc_label')(label)
    bp.app_template_filter('kyc_msg')(tr)
