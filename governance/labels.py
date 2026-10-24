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
Readable, translated labels for the status / type codes stored by the
governance, policies, training, COI and fit & proper screens.

Templates call the global ``code_label(code, kind)``; an unknown code falls
back to the code itself made readable ("SOME_CODE" -> "Some code"), so a new
value never shows up as a raw constant and never breaks a page.
"""

from flask_babel import gettext, lazy_gettext as _l

MEETING_TYPES = {
    'BOARD': _l('Board meeting'),
    'REGULAR': _l('Regular meeting'),
    'EXTRAORDINARY': _l('Extraordinary meeting'),
    'EMERGENCY': _l('Emergency meeting'),
    'AUDIT_COMMITTEE': _l('Audit Committee'),
    'RISK_COMMITTEE': _l('Risk Committee'),
    'COMPLIANCE_COMMITTEE': _l('Compliance Committee'),
    'NOMREM_COMMITTEE': _l('Nomination & Remuneration Committee'),
    'COMMITTEE': _l('Committee meeting'),
    'AGM': _l('General assembly'),
}

MEETING_STATUSES = {
    'SCHEDULED': _l('Scheduled'),
    'IN_PROGRESS': _l('In progress'),
    'COMPLETED': _l('Completed'),
    'CANCELED': _l('Cancelled'),
    'CANCELLED': _l('Cancelled'),
    'POSTPONED': _l('Postponed'),
}

COMMITTEE_TYPES = {
    'AUDIT': _l('Audit'),
    'RISK': _l('Risk'),
    'COMPLIANCE': _l('Compliance'),
    'NOMREM': _l('Nomination & Remuneration'),
    'GOVERNANCE': _l('Governance'),
    'EXECUTIVE': _l('Executive'),
    'INVESTMENT': _l('Investment'),
    'IT': _l('Information technology'),
    'CREDIT': _l('Credit'),
    'OTHER': _l('Other'),
}

MINUTES_STATUSES = {
    'draft': _l('Draft'),
    'circulated': _l('Circulated'),
    'approved': _l('Approved'),
    'superseded': _l('Superseded'),
}

ATTENDANCE_STATUSES = {
    'INVITED': _l('Invited'),
    'PRESENT': _l('Present'),
    'ABSENT': _l('Absent'),
    'ABSENT_WITH_APOLOGY': _l('Absent with apology'),
    'REPRESENTED_BY_PROXY': _l('Represented by proxy'),
}

RESOLUTION_RESULTS = {
    'passed': _l('Adopted'),
    'rejected': _l('Not adopted'),
    'deferred': _l('Deferred'),
}

ACTION_STATUSES = {
    'PENDING': _l('Pending'),
    'OPEN': _l('Open'),
    'IN_PROGRESS': _l('In progress'),
    'COMPLETED': _l('Completed'),
    'DELAYED': _l('Delayed'),
    'OVERDUE': _l('Overdue'),
    'CARRIED_FORWARD': _l('Carried forward'),
    'CANCELLED': _l('Cancelled'),
}

MEETING_EVENTS = {
    'minutes_drafted': _l('Minutes drafted'),
    'minutes_edited': _l('Minutes draft edited'),
    'minutes_circulate': _l('Minutes circulated'),
    'minutes_return': _l('Minutes returned for changes'),
    'minutes_approve': _l('Minutes approved'),
    'minutes_superseded': _l('Minutes version superseded'),
    'resolution_recorded': _l('Resolution recorded'),
    'resolution_changed': _l('Resolution corrected'),
    'action_assigned': _l('Action assigned'),
    'action_status': _l('Action status changed'),
    'action_carried': _l('Action carried to a later meeting'),
    'action_received': _l('Action carried from an earlier meeting'),
    'external_invited': _l('External participant invited'),
    'external_removed': _l('External participant removed'),
    'external_attendance': _l('External attendance recorded'),
    'member_invited': _l('Member added to attendees'),
    'member_uninvited': _l('Member removed from attendees'),
}

PRIORITIES = {'HIGH': _l('High'), 'MEDIUM': _l('Medium'), 'LOW': _l('Low'), 'CRITICAL': _l('Critical')}

POLICY_STATUSES = {
    'draft': _l('Draft'),
    'pending_approval': _l('Pending approval'),
    'pending': _l('Pending'),
    'under_review': _l('Under review'),
    'approved': _l('Approved'),
    'rejected': _l('Rejected'),
    'published': _l('Published'),
    'archived': _l('Archived'),
    'skipped': _l('Skipped'),
}

COI_STATUSES = {
    'pending': _l('Pending'),
    'submitted': _l('Submitted'),
    'under_review': _l('Under review'),
    'requires_clarification': _l('Clarification requested'),
    'mitigation_in_progress': _l('Mitigation in progress'),
    'escalated': _l('Escalated'),
    'approved': _l('Approved'),
    'rejected': _l('Rejected'),
    'clarification_requested': _l('Clarification requested'),
    'mitigation_created': _l('Mitigation plan created'),
}

# Company sector / licence type codes (company profile, fit & proper item 1.3,
# regulatory licence types). Packs may add their own codes in the rc_licence_types
# table; those fall back to the table's own bilingual name (see sector_label).
SECTORS = {
    'bank': _l('Bank'),
    'banking': _l('Banking'),
    'microfinance': _l('Microfinance'),
    'consumer_finance': _l('Consumer finance'),
    'leasing': _l('Financial leasing'),
    'factoring': _l('Factoring'),
    'mortgage_finance': _l('Mortgage finance'),
    'sme_finance': _l('SME finance'),
    'insurance': _l('Insurance'),
    'payments': _l('Payment services'),
    'psp': _l('Payment services'),
    'fintech': _l('Financial technology'),
    'securities': _l('Securities / capital markets'),
    'other': _l('Other'),
    'all': _l('All licence types'),
}

KINDS = {
    'meeting_type': MEETING_TYPES,
    'meeting_status': MEETING_STATUSES,
    'committee_type': COMMITTEE_TYPES,
    'minutes_status': MINUTES_STATUSES,
    'attendance': ATTENDANCE_STATUSES,
    'resolution': RESOLUTION_RESULTS,
    'action_status': ACTION_STATUSES,
    'priority': PRIORITIES,
    'meeting_event': MEETING_EVENTS,
    'policy_status': POLICY_STATUSES,
    'coi_status': COI_STATUSES,
    'sector': SECTORS,
}


def humanize(code):
    """'SOME_CODE' / 'some-code' -> 'Some code'."""
    s = str(code or '').replace('_', ' ').replace('-', ' ').strip()
    return s[:1].upper() + s[1:].lower() if s else ''


def code_label(code, kind=None):
    """Translated label for a stored code; '' for an empty value."""
    if code in (None, ''):
        return ''
    raw = str(code).strip()
    tables = [KINDS[kind]] if kind in KINDS else list(KINDS.values())
    for table in tables:
        for key in (raw, raw.upper(), raw.lower()):
            if key in table:
                return str(table[key])
    if kind == 'sector':
        return sector_label(raw)
    return gettext(humanize(raw)) if humanize(raw) else raw


def sector_label(code):
    """Sector / licence type label: built-in table, else the bilingual name of
    a pack's licence type (rc_licence_types), else the readable code."""
    if code in (None, ''):
        return ''
    raw = str(code).strip()
    norm = raw.lower().replace(' ', '_').replace('-', '_')
    if norm in SECTORS:
        return str(SECTORS[norm])
    try:
        from database.db import get_db
        from flask_babel import get_locale
        row = get_db().execute("SELECT name_en, name_ar FROM rc_licence_types WHERE code = %s",
                               (raw,)).fetchone()
        if row:
            ar = str(get_locale() or '').startswith('ar')
            return (row['name_ar'] if ar else row['name_en']) or row['name_en'] or humanize(raw)
    except Exception:
        try:
            from database.db import get_db
            get_db().rollback()
        except Exception:
            pass
    return humanize(raw)


def sector_choices(current=None):
    """[(code, label)] of the licence types / sectors defined in the system
    (rc_licence_types, active), plus the current value when it is not one of them."""
    out = []
    try:
        from database.db import get_db
        rows = get_db().execute("SELECT code FROM rc_licence_types WHERE is_active AND code <> 'all' ORDER BY code").fetchall()
        out = [(r['code'], sector_label(r['code'])) for r in rows]
    except Exception:
        try:
            from database.db import get_db
            get_db().rollback()
        except Exception:
            pass
    if not out:
        out = [(k, str(v)) for k, v in SECTORS.items() if k not in ('all', 'psp', 'banking')]
    if current and current not in {c for c, _ in out}:
        out.append((current, sector_label(current)))
    return out


def choices(kind):
    """[(code, label)] for a select box."""
    return [(k, str(v)) for k, v in KINDS[kind].items()]


def register(app_or_bp):
    """Expose code_label / sector_label / code_choices to every template."""
    app_or_bp.add_app_template_global(code_label, 'code_label')
    app_or_bp.add_app_template_global(sector_label, 'sector_label')
    app_or_bp.add_app_template_global(choices, 'code_choices')
    app_or_bp.add_app_template_global(sector_choices, 'sector_choices')
