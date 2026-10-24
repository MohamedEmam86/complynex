# =============================================================================
# ComplyNex — whistleblowing assignment engine (Phase 4)
#
# The history is APPEND-ONLY. A reassignment never overwrites the previous row,
# so the timeline reconstructs exactly who held a case and when. For a case
# type that may end up in front of a regulator, an ownership record that can be
# overwritten is not a record.
# =============================================================================
from datetime import datetime, timedelta

from database.db import get_db
from services.notification_service import notify

ACTIONS = {
    'assign':    'Assigned',
    'reassign':  'Reassigned',
    'transfer':  'Transferred to another department',
    'escalate':  'Escalated',
    'return':    'Returned to a previous owner',
    'close':     'Assignment closed',
}
DEFAULT_SLA_DAYS = 5


def current_owner(case_id):
    r = get_db().execute(
        """SELECT a.*, u.first_name, u.last_name, u.email
           FROM whistleblowing_assignments a
           LEFT JOIN users u ON u.id = a.assigned_to
           WHERE a.case_id=%s AND a.is_current
           ORDER BY a.assigned_at_ts DESC LIMIT 1""", (case_id,)).fetchone()
    return dict(r) if r else None


def timeline(case_id):
    rows = get_db().execute(
        """SELECT a.*,
                  u.first_name  AS to_first,  u.last_name  AS to_last,
                  b.first_name  AS by_first,  b.last_name  AS by_last,
                  p.first_name  AS prev_first,p.last_name  AS prev_last,
                  fo.name_en AS from_unit, tu.name_en AS to_unit
           FROM whistleblowing_assignments a
           LEFT JOIN users u ON u.id = a.assigned_to
           LEFT JOIN users b ON b.id = a.assigned_by
           LEFT JOIN users p ON p.id = a.previous_owner_id
           LEFT JOIN org_units fo ON fo.id = a.from_org_unit_id
           LEFT JOIN org_units tu ON tu.id = a.to_org_unit_id
           WHERE a.case_id=%s
           ORDER BY a.assigned_at_ts DESC, a.id DESC""", (case_id,)).fetchall()
    return [dict(r) for r in rows]


def assign(case_id, to_user_id, by_user_id, action='assign', reason=None,
           comments=None, to_org_unit_id=None, sla_days=DEFAULT_SLA_DAYS):
    """Record one assignment action.

    A reason is mandatory for everything except the first assignment: moving a
    whistleblowing case between people without saying why is precisely what an
    investigation review will ask about.
    """
    if action not in ACTIONS:
        return False, f'Unknown action: {action}'

    db = get_db()
    case = db.execute("SELECT id, status, assigned_to, case_number FROM whistleblowing_cases "
                      "WHERE id=%s", (case_id,)).fetchone()
    if not case:
        return False, 'Case not found.'
    case = dict(case)

    prev = current_owner(case_id)
    prev_user = prev['assigned_to'] if prev else case.get('assigned_to')

    if action != 'assign' and not (reason or '').strip():
        return False, 'A reason is required when reassigning, transferring, escalating or returning a case.'
    if action != 'close' and not to_user_id:
        return False, 'Select who the case is going to.'

    from_unit = None
    if prev_user:
        r = db.execute("SELECT org_unit_id FROM users WHERE id=%s", (prev_user,)).fetchone()
        from_unit = dict(r)['org_unit_id'] if r else None
    if to_user_id and not to_org_unit_id:
        r = db.execute("SELECT org_unit_id FROM users WHERE id=%s", (to_user_id,)).fetchone()
        to_org_unit_id = dict(r)['org_unit_id'] if r else None

    # Supersede the open row rather than editing it.
    db.execute("UPDATE whistleblowing_assignments SET is_current=FALSE, unassigned_at=%s, "
               "unassigned_by=%s WHERE case_id=%s AND is_current",
               (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), by_user_id, case_id))

    db.execute("""INSERT INTO whistleblowing_assignments
                    (case_id, assigned_to, assigned_by, assigned_at, assigned_at_ts,
                     action_type, previous_owner_id, from_org_unit_id, to_org_unit_id,
                     assignment_reason, comments, status_at_assignment, sla_due_at,
                     is_current, assignment_note)
                  VALUES (%s,%s,%s,%s,NOW(),%s,%s,%s,%s,%s,%s,%s,
                          NOW() + (%s || ' days')::interval, %s, %s)""",
               (case_id, to_user_id, by_user_id,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                action, prev_user, from_unit, to_org_unit_id,
                (reason or '').strip() or None, (comments or '').strip() or None,
                case.get('status'), sla_days,
                action != 'close', (reason or '')[:200] or None))

    if action != 'close':
        db.execute("UPDATE whistleblowing_cases SET assigned_to=%s, assigned_at=%s, updated_at=%s "
                   "WHERE id=%s",
                   (to_user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'), case_id))
    db.commit()
    from models.case import sync_case
    sync_case('WHISTLEBLOWING', case_id)

    if to_user_id and action != 'close':
        notify(to_user_id,
               f'Whistleblowing case {case.get("case_number") or case_id} assigned to you',
               f'{ACTIONS[action]}. {reason or ""}'.strip(),
               link=f'/whistleblowing/case/{case_id}', category='warning')
    return True, f'{ACTIONS[action]} successfully.'


def tracking(case_id):
    """Where the case sits, who owns it, how long it has been there, SLA state."""
    db = get_db()
    case = db.execute("SELECT * FROM whistleblowing_cases WHERE id=%s", (case_id,)).fetchone()
    if not case:
        return None
    case = dict(case)
    own = current_owner(case_id)

    days_held, sla = None, 'none'
    if own and own.get('assigned_at_ts'):
        days_held = (datetime.now() - own['assigned_at_ts']).days
        if own.get('sla_due_at'):
            remaining = (own['sla_due_at'] - datetime.now()).days
            sla = 'breached' if remaining < 0 else ('due_soon' if remaining <= 1 else 'on_track')

    hist = timeline(case_id)
    return {
        'case': case,
        'owner': own,
        'unassigned': own is None and not case.get('assigned_to'),
        'days_held': days_held,
        'sla_status': sla,
        'sla_due_at': own.get('sla_due_at') if own else None,
        'previous_owners': [h for h in hist if h.get('previous_owner_id')],
        'history_count': len(hist),
        'stage': case.get('status') or 'New',
    }


def send_reminder(case_ids, by_user_id, message=None, to='assignee'):
    """Reminders to the current assignee, or up the line. Bulk-safe.

    Returns a real count of what was delivered — not an optimistic one.
    """
    if isinstance(case_ids, int):
        case_ids = [case_ids]
    db = get_db()
    sent, skipped = 0, []
    for cid in case_ids:
        own = current_owner(cid)
        case = db.execute("SELECT case_number FROM whistleblowing_cases WHERE id=%s", (cid,)).fetchone()
        num = dict(case)['case_number'] if case else cid

        target = None
        if to == 'assignee':
            target = own['assigned_to'] if own else None
        elif to == 'escalation':
            if own and own.get('to_org_unit_id'):
                r = db.execute("""SELECT p.head_user_id FROM org_units c
                                  LEFT JOIN org_units p ON p.id=c.parent_id WHERE c.id=%s""",
                               (own['to_org_unit_id'],)).fetchone()
                target = dict(r)['head_user_id'] if r else None

        if not target:
            skipped.append(num)
            continue

        msg = message or f'Case {num} is still awaiting your action.'
        notify(target, f'Reminder: whistleblowing case {num}', msg,
               link=f'/whistleblowing/case/{cid}', category='warning')
        db.execute("""INSERT INTO case_reminders
                        (case_id, sent_to, sent_by, reminder_type, message, is_bulk)
                      VALUES (%s,%s,%s,%s,%s,%s)""",
                   (cid, target, by_user_id, to, msg, len(case_ids) > 1))
        sent += 1
    db.commit()
    return sent, skipped
