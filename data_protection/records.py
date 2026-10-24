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
Data protection records: reference lists and DB-free validation for DSR intake,
ROPA (record of processing) entries, the consent register and breach
notification records. Error values are message keys mapped to translated text
by the routes, so these functions stay testable without an app context.
"""
import re
from datetime import date, datetime

DSR_TYPES = ('ACCESS', 'RECTIFICATION', 'ERASURE', 'RESTRICTION', 'PORTABILITY', 'OBJECTION')
DSR_CHANNELS = ('EMAIL', 'PHONE', 'BRANCH', 'WEBSITE', 'MOBILE_APP', 'LETTER', 'IN_PERSON')
VERIFY_METHODS = ('ID_CARD', 'PASSPORT', 'EMAIL_TOKEN', 'SMS_OTP', 'IN_PERSON', 'KYC_RECORD')
CONSENT_CHANNELS = ('PAPER_FORM', 'WEBSITE', 'MOBILE_APP', 'EMAIL', 'SMS', 'RECORDED_CALL', 'BRANCH')
SUBJECT_NOTICE_METHODS = ('EMAIL', 'SMS', 'LETTER', 'PHONE', 'IN_APP', 'PUBLIC_NOTICE')
ROPA_FIELDS = ('activity_name', 'activity_description', 'processing_purpose', 'legal_basis',
               'data_subject_categories', 'data_categories', 'recipients', 'international_transfer',
               'transfer_countries', 'transfer_safeguards', 'retention_period', 'retention_justification',
               'security_measures', 'system_name', 'data_owner', 'dpo_review_date', 'next_review_date', 'is_active')

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_PHONE_RE = re.compile(r'^\+?[0-9 ()\-]{7,20}$')


def parse_day(value):
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def validate_dsr_intake(f, today=None):
    """f: dict of form values. Returns (error_key, cleaned)."""
    today = today or date.today()
    name = (f.get('subject_name') or '').strip()
    if not name:
        return 'name', None
    rtype = (f.get('request_type') or '').strip().upper()
    if rtype not in DSR_TYPES:
        return 'type', None
    email = (f.get('email') or '').strip()
    phone = (f.get('phone') or '').strip()
    if not email and not phone:
        return 'contact', None
    if email and not _EMAIL_RE.match(email):
        return 'email', None
    if phone and not _PHONE_RE.match(phone):
        return 'phone', None
    channel = (f.get('channel') or '').strip().upper()
    if channel not in DSR_CHANNELS:
        return 'channel', None
    received = parse_day(f.get('received_date')) if f.get('received_date') else today
    if not received:
        return 'received', None
    if received > today:
        return 'received_future', None
    method = (f.get('verification_method') or '').strip().upper() or None
    if method and method not in VERIFY_METHODS:
        return 'method', None
    return None, {'data_subject_name': name, 'request_type': rtype, 'data_subject_email': email or None,
                  'data_subject_phone': phone or None, 'request_channel': channel, 'received_date': received,
                  'verification_method': method,
                  'request_description': (f.get('description') or '').strip() or None}


def validate_ropa(f, legal_bases, today=None):
    if not (f.get('activity_name') or '').strip():
        return 'name', None
    if not (f.get('processing_purpose') or '').strip():
        return 'purpose', None
    if f.get('legal_basis') not in legal_bases:
        return 'legal_basis', None
    transfer = 1 if f.get('international_transfer') in ('1', 'on', 'true', 1, True) else 0
    if transfer and not (f.get('transfer_countries') or '').strip():
        return 'transfer_countries', None
    if transfer and not (f.get('transfer_safeguards') or '').strip():
        return 'transfer_safeguards', None
    if not (f.get('retention_period') or '').strip():
        return 'retention', None
    out = {}
    for k in ROPA_FIELDS:
        v = f.get(k)
        out[k] = (v.strip() if isinstance(v, str) else v) or None
    for k in ('dpo_review_date', 'next_review_date'):
        if out[k]:
            d = parse_day(out[k])
            if not d:
                return 'date', None
            out[k] = d.isoformat()
    try:
        out['data_owner'] = int(out['data_owner']) if out['data_owner'] else None
    except (TypeError, ValueError):
        out['data_owner'] = None
    out['international_transfer'] = transfer
    if not transfer:
        out['transfer_countries'] = out['transfer_safeguards'] = None
    out['is_active'] = 0 if f.get('is_active') in ('0', 0) else 1
    return None, out


def ropa_changes(old, new):
    """Readable list of 'field: old -> new' for the change history."""
    changes = []
    for k, v in new.items():
        before = old.get(k)
        b = '' if before is None else str(before)
        a = '' if v is None else str(v)
        if b != a:
            changes.append(f'{k}: {b or "-"} -> {a or "-"}')
    return changes


def validate_consent(f, purpose_ids, today=None):
    today = today or date.today()
    subject = (f.get('subject') or '').strip()
    if not subject:
        return 'subject', None
    try:
        pid = int(f.get('purpose_id'))
    except (TypeError, ValueError):
        return 'purpose', None
    if pid not in purpose_ids:
        return 'purpose', None
    channel = (f.get('channel') or '').strip().upper()
    if channel not in CONSENT_CHANNELS:
        return 'channel', None
    d = parse_day(f.get('consent_date'))
    if not d:
        return 'date', None
    if d > today:
        return 'date_future', None
    evidence = (f.get('evidence') or '').strip()
    if not evidence:
        return 'evidence', None
    return None, {'data_subject_id': subject, 'data_subject_identifier': (f.get('subject_ref') or '').strip() or None,
                  'purpose_id': pid, 'consent_method': channel, 'consent_date': d, 'evidence_ref': evidence,
                  'consent_text': (f.get('consent_text') or '').strip() or None}


def validate_withdrawal(f, consent_date, today=None):
    today = today or date.today()
    d = parse_day(f.get('withdrawal_date'))
    if not d:
        return 'date', None
    if d > today:
        return 'date_future', None
    cd = parse_day(consent_date)
    if cd and d < cd:
        return 'before_consent', None
    reason = (f.get('reason') or '').strip()
    if not reason:
        return 'reason', None
    channel = (f.get('channel') or '').strip().upper() or None
    if channel and channel not in CONSENT_CHANNELS:
        return 'channel', None
    return None, {'withdrawal_date': d, 'withdrawal_reason': reason, 'withdrawal_method': channel}


def validate_breach_notification(f, discovery_date, today=None):
    """Regulator notification (date + reference) and data-subject notification (date + method)."""
    today = today or date.today()
    disc = parse_day(discovery_date)
    out = {'notification_notes': (f.get('notification_notes') or '').strip() or None}
    reg_date = parse_day(f.get('regulator_date')) if f.get('regulator_date') else None
    if f.get('regulator_date') and not reg_date:
        return 'date', None
    ref = (f.get('regulator_reference') or '').strip()
    if reg_date:
        if reg_date > today:
            return 'date_future', None
        if disc and reg_date < disc:
            return 'before_discovery', None
        if not ref:
            return 'reference', None
    elif ref:
        return 'regulator_date', None
    out.update({'pdpc_notified': 1 if reg_date else 0, 'pdpc_notification_date': reg_date.isoformat() if reg_date else None,
                'pdpc_reference': ref or None})
    sub_date = parse_day(f.get('subjects_date')) if f.get('subjects_date') else None
    if f.get('subjects_date') and not sub_date:
        return 'date', None
    method = (f.get('subjects_method') or '').strip().upper() or None
    if sub_date:
        if sub_date > today:
            return 'date_future', None
        if disc and sub_date < disc:
            return 'before_discovery', None
        if method not in SUBJECT_NOTICE_METHODS:
            return 'method', None
    elif method:
        return 'subjects_date', None
    count = None
    if f.get('subjects_count'):
        try:
            count = int(f.get('subjects_count'))
        except (TypeError, ValueError):
            return 'count', None
        if count < 0:
            return 'count', None
    out.update({'individuals_notified': 1 if sub_date else 0,
                'individuals_notification_date': sub_date.isoformat() if sub_date else None,
                'individuals_notification_method': method if sub_date else None,
                'individuals_notification_count': count})
    return None, out
