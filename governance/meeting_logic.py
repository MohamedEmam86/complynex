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
Pure rules of the meetings workflow (minutes, resolutions, action items,
external invitees). No database access, so they are unit-tested directly.
Messages are returned untranslated; the routes translate them.
"""

import re
from datetime import date, datetime

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# ------------------------------------------------------------------ minutes
MINUTES_FLOW = {
    # action: (allowed from, to)
    'circulate': (('draft',), 'circulated'),
    'return': (('circulated',), 'draft'),
    'approve': (('circulated',), 'approved'),
}
APPROVER_CAPACITIES = ('chair', 'secretary')


def minutes_transition_error(action, status, *, actor_id=None, drafted_by=None, capacity=None, note=None,
                             present_count=None):
    """Why `action` may not be applied to a minutes version in `status`, or None.
    present_count: participants recorded as present (members, proxies, external
    attendees); minutes cannot be approved while nobody is recorded present."""
    if action not in MINUTES_FLOW:
        return 'unknown action'
    allowed, _to = MINUTES_FLOW[action]
    if status not in allowed:
        return 'this version of the minutes is not in a state that allows this action'
    if action == 'approve':
        if capacity not in APPROVER_CAPACITIES:
            return 'state whether you approve as chair or as secretary'
        if drafted_by is not None and actor_id == drafted_by:
            return 'the person who drafted the minutes cannot approve them'
        if present_count is not None and present_count <= 0:
            return 'record the attendance of the meeting before approving its minutes'
    if action == 'return' and not (note or '').strip():
        return 'give the reason for returning the minutes'
    return None


def minutes_target(action):
    return MINUTES_FLOW[action][1]


def new_minutes_version(versions):
    """What saving the minutes does, given the existing versions (dicts with
    version_no / status, any order).

    Returns (mode, version_no, supersede_ids):
      ('update', n, [])     -> edit the current draft n in place
      ('new', n+1, [ids])   -> create draft n+1; earlier circulated versions are
                              superseded now (they are being revised). An approved
                              version stays in force until the new one is approved.
    """
    if not versions:
        return 'new', 1, []
    latest = max(versions, key=lambda v: v['version_no'])
    if latest['status'] == 'draft':
        return 'update', latest['version_no'], []
    supersede = [v['id'] for v in versions if v['status'] == 'circulated']
    return 'new', latest['version_no'] + 1, supersede


def change_note_required(versions):
    """A revision of minutes that were already circulated or approved needs a change note."""
    mode, n, _ = new_minutes_version(versions)
    return mode == 'new' and n > 1


# ------------------------------------------------------------------ resolutions
def _int(v):
    try:
        n = int(str(v).strip())
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def vote_result(votes_for, votes_against, votes_abstain=0):
    """Simple majority of the votes cast (abstentions are not votes cast)."""
    f, a = _int(votes_for) or 0, _int(votes_against) or 0
    if f == 0 and a == 0:
        return 'deferred'
    return 'passed' if f > a else 'rejected'


def resolution_errors(data):
    errors = []
    if not (data.get('decision_text') or '').strip():
        errors.append('the resolution text is required')
    for key, label in (('votes_for', 'for'), ('votes_against', 'against'), ('votes_abstain', 'abstain')):
        if (data.get(key) or '') != '' and _int(data.get(key)) is None:
            errors.append(f'votes {label} must be a whole number')
    if (_int(data.get('votes_against')) or 0) > 0 and not (data.get('dissent_notes') or '').strip():
        errors.append('record the dissenting members and their reasons when votes were cast against')
    if data.get('vote_result') and data['vote_result'] not in ('passed', 'rejected', 'deferred'):
        errors.append('unknown vote result')
    return errors


def next_reference(prefix, existing_numbers, letter='R'):
    """Next resolution number for a meeting: '<prefix>/R03'."""
    n = 0
    for ref in existing_numbers:
        m = re.search(r'(\d+)\s*$', str(ref or ''))
        if m:
            n = max(n, int(m.group(1)))
    return f'{prefix}/{letter}{n + 1:02d}'


# ------------------------------------------------------------------ action items
CLOSED_ACTION_STATUSES = ('COMPLETED', 'CANCELLED')
ACTION_STATUS_FLOW = ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'DELAYED', 'CANCELLED')


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v or '').strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def is_overdue(action, today=None):
    due = _as_date(action.get('due_date'))
    status = (action.get('status') or 'PENDING').upper()
    return bool(due and status not in CLOSED_ACTION_STATUSES and due < (today or date.today()))


def action_errors(data):
    errors = []
    if not (data.get('action_description') or '').strip():
        errors.append('describe the action')
    if not (data.get('owner_user_id') or (data.get('responsible_person') or '').strip()):
        errors.append('choose an owner (a user, or type the name of an external owner)')
    if not _as_date(data.get('due_date')):
        errors.append('a valid due date is required')
    return errors


def action_update_error(current_status, new_status, note):
    if new_status not in ACTION_STATUS_FLOW:
        return 'unknown status'
    if (current_status or '').upper() in CLOSED_ACTION_STATUSES:
        return 'this action is already closed'
    if new_status in ('COMPLETED', 'CANCELLED', 'DELAYED') and not (note or '').strip():
        return 'a note is required to complete, cancel or delay an action'
    return None


# ------------------------------------------------------------------ external invitees
EXTERNAL_STATUSES = ('INVITED', 'PRESENT', 'ABSENT', 'ABSENT_WITH_APOLOGY')


def external_errors(data):
    errors = []
    if not (data.get('full_name') or '').strip():
        errors.append('the name is required')
    email = (data.get('email') or '').strip()
    if email and not EMAIL_RE.match(email):
        errors.append('the email address is not valid')
    if not (data.get('role') or '').strip():
        errors.append('the role is required (e.g. independent committee member, external auditor)')
    return errors
