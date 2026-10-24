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
Meetings workflow on the governance blueprint: minutes (draft -> circulated ->
approved by the chair or secretary, with versions), resolutions with votes,
tracked action items carried to later meetings, external committee members
who are not system users, and printable minutes (Arabic / English).
"""

from datetime import date, datetime

from flask import render_template, request, redirect, url_for, flash, abort, session
from flask_login import login_required, current_user
from flask_babel import gettext as _

from database.db import get_db
from models.audit import AuditLog
from models.governance import BoardMeeting, BoardCommittee, MeetingAttendance
from utils.decorators import permission_required
from governance.routes import governance_bp
from governance import meeting_logic as L

ACTION_SELECT = """
    SELECT a.*, NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '') AS owner_name,
           m.meeting_reference, m.meeting_date, m.meeting_type,
           cm.meeting_reference AS carried_reference, cm.meeting_date AS carried_date
    FROM meeting_action_items a
    JOIN board_meetings m ON m.id = a.meeting_id
    LEFT JOIN users u ON u.id = a.owner_user_id
    LEFT JOIN board_meetings cm ON cm.id = a.carried_to_meeting_id
"""


def _meeting_or_404(mid):
    m = BoardMeeting.get_by_id(mid)
    if not m:
        abort(404)
    return m


def _event(db, meeting_id, subject, subject_id, event, from_status=None, to_status=None, note=None):
    db.execute("""INSERT INTO meeting_events (meeting_id, subject, subject_id, event, from_status, to_status, note, user_id)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
               (meeting_id, subject, subject_id, event, from_status, to_status, note, current_user.id))


def _audit(action, mid, details):
    try:
        AuditLog.log(current_user.id, action, 'Governance', mid, details, request.remote_addr)
    except Exception:
        pass


def _flash_rule_errors(errors):
    for e in errors:
        flash(_(e[:1].upper() + e[1:] + '.'), 'danger')


def _active_users(db):
    return [dict(r) for r in db.execute(
        """SELECT id, NULLIF(TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')), '') AS name, email
           FROM users WHERE is_active = 1 ORDER BY first_name, last_name""").fetchall()]


def _decorate_actions(rows, today=None):
    out = []
    for r in rows:
        r = dict(r)
        r['overdue'] = L.is_overdue(r, today)
        r['owner_display'] = r.get('owner_name') or r.get('responsible_person') or '-'
        out.append(r)
    return out


def _notify(user_ids, title, message, link):
    try:
        from services.notification_service import notify
        notify([u for u in user_ids if u and u != current_user.id], title, message, link=link, category='governance')
    except Exception:
        pass


def meeting_context(mid, db=None):
    """Everything the meeting page and the printed minutes show."""
    db = db or get_db()
    meeting = _meeting_or_404(mid)
    committee = BoardCommittee.get_by_id(meeting.committee_id) if meeting.committee_id else None
    attendance = BoardMeeting.get_attendance_summary(mid)
    externals = [dict(r) for r in db.execute(
        "SELECT * FROM meeting_external_attendees WHERE meeting_id = %s ORDER BY id", (mid,)).fetchall()]
    minutes = [dict(r) for r in db.execute(
        "SELECT * FROM meeting_minutes WHERE meeting_id = %s ORDER BY version_no DESC", (mid,)).fetchall()]
    current = next((v for v in minutes if v['status'] == 'draft'), None) or \
        next((v for v in minutes if v['status'] == 'circulated'), None)
    approved = next((v for v in minutes if v['status'] == 'approved'), None)
    resolutions = [dict(r) for r in db.execute(
        "SELECT * FROM board_decisions WHERE meeting_id = %s ORDER BY id", (mid,)).fetchall()]
    actions = _decorate_actions(db.execute(ACTION_SELECT + " WHERE a.meeting_id = %s ORDER BY a.action_number, a.id",
                                           (mid,)).fetchall())
    # Open actions of earlier meetings of the same body (the board, or this committee).
    body_clause = "m.committee_id = %s" if meeting.committee_id else "m.committee_id IS NULL"
    body_args = (meeting.committee_id,) if meeting.committee_id else ()
    outstanding = _decorate_actions(db.execute(
        ACTION_SELECT + " WHERE a.meeting_id <> %s AND " + body_clause +
        " AND UPPER(COALESCE(a.status, 'PENDING')) NOT IN ('COMPLETED', 'CANCELLED')"
        " AND (a.carried_to_meeting_id = %s OR (m.meeting_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'"
        "      AND %s ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' AND left(m.meeting_date, 10) < left(%s, 10)))"
        " ORDER BY a.due_date NULLS LAST, a.id",
        (mid,) + body_args + (mid, meeting.meeting_date or '', meeting.meeting_date or '')).fetchall())
    events = [dict(r) for r in db.execute(
        """SELECT e.*, NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '') AS user_name
           FROM meeting_events e LEFT JOIN users u ON u.id = e.user_id
           WHERE e.meeting_id = %s ORDER BY e.created_at DESC, e.id DESC""", (mid,)).fetchall()]
    later_meetings = [dict(r) for r in db.execute(
        "SELECT id, meeting_reference, meeting_date, meeting_type FROM board_meetings WHERE id <> %s AND "
        + ("committee_id = %s" if meeting.committee_id else "committee_id IS NULL") +
        " AND meeting_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' AND left(meeting_date, 10) >= %s"
        " ORDER BY meeting_date LIMIT 12",
        (mid,) + body_args + ((meeting.meeting_date or '')[:10] or date.today().isoformat(),)).fetchall()]
    return dict(meeting=meeting, committee=committee, attendance=attendance, externals=externals,
                minutes=minutes, current_minutes=current, approved_minutes=approved,
                resolutions=resolutions, actions=actions, outstanding=outstanding, events=events,
                later_meetings=later_meetings, today=date.today())


# ------------------------------------------------------------------ minutes
@governance_bp.route('/meeting/<int:id>/minutes/save', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def minutes_save(id):
    _meeting_or_404(id)
    db = get_db()
    body = (request.form.get('body') or '').strip()
    note = (request.form.get('change_note') or '').strip() or None
    if not body:
        flash(_('The minutes text is required.'), 'danger')
        return redirect(url_for('governance.meeting_summary', id=id) + '#minutes')
    versions = [dict(r) for r in db.execute(
        "SELECT id, version_no, status FROM meeting_minutes WHERE meeting_id = %s", (id,)).fetchall()]
    if L.change_note_required(versions) and not note:
        flash(_('Describe what changed in this revision of the minutes.'), 'danger')
        return redirect(url_for('governance.meeting_summary', id=id) + '#minutes')
    mode, n, supersede = L.new_minutes_version(versions)
    if mode == 'update':
        db.execute("""UPDATE meeting_minutes SET body = %s, change_note = COALESCE(%s, change_note), updated_at = NOW()
                      WHERE meeting_id = %s AND version_no = %s AND status = 'draft'""", (body, note, id, n))
        _event(db, id, 'minutes', n, 'minutes_edited', 'draft', 'draft', note)
    else:
        for vid in supersede:
            db.execute("UPDATE meeting_minutes SET status = 'superseded' WHERE id = %s", (vid,))
            _event(db, id, 'minutes', vid, 'minutes_superseded', 'circulated', 'superseded', note)
        db.execute("""INSERT INTO meeting_minutes (meeting_id, version_no, body, change_note, status, created_by)
                      VALUES (%s,%s,%s,%s,'draft',%s)""", (id, n, body, note, current_user.id))
        _event(db, id, 'minutes', n, 'minutes_drafted', None, 'draft', note)
    db.commit()
    _audit('Meeting Minutes Saved', id, f'Minutes v{n} ({mode})')
    flash(_('Minutes version %(n)s saved as draft.', n=n), 'success')
    return redirect(url_for('governance.meeting_summary', id=id) + '#minutes')


@governance_bp.route('/meeting/<int:id>/minutes/<int:vid>/<action>', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def minutes_transition(id, vid, action):
    _meeting_or_404(id)
    db = get_db()
    v = db.execute("SELECT * FROM meeting_minutes WHERE id = %s AND meeting_id = %s", (vid, id)).fetchone()
    if not v or action not in L.MINUTES_FLOW:
        abort(404)
    v = dict(v)
    note = (request.form.get('note') or '').strip() or None
    capacity = request.form.get('capacity')
    err = L.minutes_transition_error(action, v['status'], actor_id=current_user.id, drafted_by=v['created_by'],
                                     capacity=capacity, note=note)
    if err:
        _flash_rule_errors([err])
        return redirect(url_for('governance.meeting_summary', id=id) + '#minutes')
    to = L.minutes_target(action)
    if action == 'circulate':
        db.execute("UPDATE meeting_minutes SET status = %s, circulated_by = %s, circulated_at = NOW() WHERE id = %s",
                   (to, current_user.id, vid))
    elif action == 'approve':
        db.execute("""UPDATE meeting_minutes SET status = 'superseded'
                      WHERE meeting_id = %s AND id <> %s AND status IN ('approved', 'circulated')""", (id, vid))
        db.execute("""UPDATE meeting_minutes SET status = %s, approved_by = %s, approved_at = NOW(), approver_capacity = %s
                      WHERE id = %s""", (to, current_user.id, capacity, vid))
    else:  # return to draft for changes
        db.execute("UPDATE meeting_minutes SET status = %s, circulated_by = NULL, circulated_at = NULL WHERE id = %s",
                   (to, vid))
    _event(db, id, 'minutes', v['version_no'], 'minutes_' + action, v['status'], to,
           (f'[{capacity}] ' if capacity and action == 'approve' else '') + (note or ''))
    db.commit()
    _audit('Meeting Minutes ' + action.title(), id, f"Minutes v{v['version_no']}: {v['status']} -> {to}")
    if action == 'circulate':
        _notify([v['created_by']], _('Meeting minutes circulated'),
                _('Version %(n)s of the minutes has been circulated for approval.', n=v['version_no']),
                url_for('governance.meeting_summary', id=id))
    flash(_('Minutes updated: %(status)s.', status=_(to.title())), 'success')
    return redirect(url_for('governance.meeting_summary', id=id) + '#minutes')


@governance_bp.route('/meeting/<int:id>/minutes/print')
@login_required
@permission_required('governance')
def minutes_print(id):
    ctx = meeting_context(id)
    vid = request.args.get('v', type=int)
    version = next((v for v in ctx['minutes'] if v['id'] == vid), None) if vid else \
        (ctx['approved_minutes'] or ctx['current_minutes'])
    lang = 'ar' if (request.args.get('lang') or session.get('lang')) == 'ar' else 'en'
    from flask_babel import force_locale
    with force_locale(lang):
        # Lists computed with the UI locale are plain data; labels render in the print language.
        return render_template('governance/meeting_minutes_print.html', version=version, print_lang=lang, **ctx)


# ------------------------------------------------------------------ resolutions
def _resolution_data():
    f = request.form
    data = {k: (f.get(k) or '').strip() for k in ('decision_number', 'decision_title', 'decision_text',
                                                  'votes_for', 'votes_against', 'votes_abstain',
                                                  'vote_result', 'dissent_notes')}
    if not data['vote_result']:
        data['vote_result'] = L.vote_result(data['votes_for'], data['votes_against'], data['votes_abstain'])
    return data


def _minutes_locked(db, mid):
    return bool(db.execute("SELECT 1 FROM meeting_minutes WHERE meeting_id = %s AND status = 'approved'",
                           (mid,)).fetchone())


@governance_bp.route('/meeting/<int:id>/resolutions/add', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def resolution_add(id):
    meeting = _meeting_or_404(id)
    db = get_db()
    data = _resolution_data()
    errors = L.resolution_errors(data)
    if errors:
        _flash_rule_errors(errors)
        return redirect(url_for('governance.meeting_summary', id=id) + '#resolutions')
    if not data['decision_number']:
        nums = [r['decision_number'] for r in db.execute(
            "SELECT decision_number FROM board_decisions WHERE meeting_id = %s", (id,)).fetchall()]
        data['decision_number'] = L.next_reference(meeting.meeting_reference or f'M{id}', nums)
    to_int = lambda v: int(v) if str(v).strip().isdigit() else 0  # noqa: E731
    vf, va, vb = to_int(data['votes_for']), to_int(data['votes_against']), to_int(data['votes_abstain'])
    rid = db.execute("""
        INSERT INTO board_decisions (meeting_id, decision_reference, decision_number, decision_date, decision_title,
            decision_description, decision_text, vote_type, votes_for, votes_against, votes_abstain, vote_result,
            dissent_notes, dissenting_reasons, status, recorded_by, recorded_at, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s,NOW(),%s) RETURNING id""",
        (id, data['decision_number'], data['decision_number'], meeting.meeting_date, data['decision_title'] or None,
         data['decision_text'], data['decision_text'],
         'UNANIMOUS' if va == 0 and vb == 0 and vf > 0 else 'MAJORITY', vf, va, vb, data['vote_result'],
         data['dissent_notes'] or None, data['dissent_notes'] or None, current_user.id,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'))).fetchone()['id']
    _event(db, id, 'resolution', rid, 'resolution_recorded', None, data['vote_result'],
           f"{data['decision_number']}: {vf}/{va}/{vb}")
    db.commit()
    _audit('Meeting Resolution Recorded', id, f"{data['decision_number']} ({data['vote_result']})")
    flash(_('Resolution %(ref)s recorded.', ref=data['decision_number']), 'success')
    return redirect(url_for('governance.meeting_summary', id=id) + '#resolutions')


@governance_bp.route('/meeting/<int:id>/resolutions/<int:rid>/edit', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def resolution_edit(id, rid):
    _meeting_or_404(id)
    db = get_db()
    row = db.execute("SELECT * FROM board_decisions WHERE id = %s AND meeting_id = %s", (rid, id)).fetchone()
    if not row:
        abort(404)
    if _minutes_locked(db, id):
        flash(_('The minutes of this meeting are approved; resolutions can no longer be changed.'), 'danger')
        return redirect(url_for('governance.meeting_summary', id=id) + '#resolutions')
    data = _resolution_data()
    reason = (request.form.get('reason') or '').strip()
    errors = L.resolution_errors(data)
    if not reason:
        errors.append('give the reason for changing a recorded resolution')
    if errors:
        _flash_rule_errors(errors)
        return redirect(url_for('governance.meeting_summary', id=id) + '#resolutions')
    to_int = lambda v: int(v) if str(v).strip().isdigit() else 0  # noqa: E731
    db.execute("""UPDATE board_decisions SET decision_title = %s, decision_text = %s, decision_description = %s,
                  votes_for = %s, votes_against = %s, votes_abstain = %s, vote_result = %s, dissent_notes = %s,
                  dissenting_reasons = %s WHERE id = %s""",
               (data['decision_title'] or row['decision_title'], data['decision_text'], data['decision_text'],
                to_int(data['votes_for']), to_int(data['votes_against']), to_int(data['votes_abstain']),
                data['vote_result'], data['dissent_notes'] or None, data['dissent_notes'] or None, rid))
    _event(db, id, 'resolution', rid, 'resolution_changed', row['vote_result'], data['vote_result'], reason)
    db.commit()
    _audit('Meeting Resolution Changed', id, f"{row['decision_number']}: {reason}")
    flash(_('Resolution updated.'), 'success')
    return redirect(url_for('governance.meeting_summary', id=id) + '#resolutions')


# ------------------------------------------------------------------ action items
@governance_bp.route('/meeting/<int:id>/actions/add', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def action_add(id):
    meeting = _meeting_or_404(id)
    db = get_db()
    f = request.form
    data = {'action_description': (f.get('action_description') or '').strip(),
            'owner_user_id': f.get('owner_user_id', type=int),
            'responsible_person': (f.get('responsible_person') or '').strip(),
            'due_date': (f.get('due_date') or '').strip(),
            'priority': f.get('priority') if f.get('priority') in ('HIGH', 'MEDIUM', 'LOW') else 'MEDIUM',
            'resolution_id': f.get('resolution_id', type=int)}
    errors = L.action_errors(data)
    if errors:
        _flash_rule_errors(errors)
        return redirect(url_for('governance.meeting_summary', id=id) + '#actions')
    n = db.execute("SELECT COALESCE(MAX(action_number), 0) + 1 AS n FROM meeting_action_items WHERE meeting_id = %s",
                   (id,)).fetchone()['n']
    owner_name = data['responsible_person']
    if data['owner_user_id']:
        u = db.execute("SELECT first_name, last_name FROM users WHERE id = %s", (data['owner_user_id'],)).fetchone()
        owner_name = f"{u['first_name'] or ''} {u['last_name'] or ''}".strip() if u else owner_name
    aid = db.execute("""
        INSERT INTO meeting_action_items (meeting_id, action_number, action_description, action_category,
            responsible_person, responsible_committee_id, due_date, priority, status, owner_user_id, resolution_id,
            created_by, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s,%s,%s,NOW()) RETURNING id""",
        (id, n, data['action_description'], 'STRATEGIC' if not meeting.committee_id else 'OPERATIONAL',
         owner_name, meeting.committee_id, data['due_date'], data['priority'], data['owner_user_id'],
         data['resolution_id'], current_user.id)).fetchone()['id']
    _event(db, id, 'action', aid, 'action_assigned', None, 'PENDING', f'#{n} -> {owner_name} ({data["due_date"]})')
    db.commit()
    _audit('Meeting Action Assigned', id, f'Action #{n} to {owner_name}')
    if data['owner_user_id']:
        _notify([data['owner_user_id']], _('Meeting action assigned to you'),
                _('An action from meeting %(ref)s is assigned to you, due %(due)s.',
                  ref=meeting.meeting_reference or meeting.meeting_date, due=data['due_date']),
                url_for('governance.meeting_summary', id=id) + '#actions')
    flash(_('Action item added.'), 'success')
    return redirect(url_for('governance.meeting_summary', id=id) + '#actions')


def _action_or_404(db, aid):
    row = db.execute("SELECT * FROM meeting_action_items WHERE id = %s", (aid,)).fetchone()
    if not row:
        abort(404)
    return dict(row)


def _back_to(default_mid):
    nxt = request.form.get('next') or ''
    if nxt.startswith('/governance/') and '//' not in nxt:
        return redirect(nxt)
    return redirect(url_for('governance.meeting_summary', id=default_mid) + '#actions')


@governance_bp.route('/meeting-actions/<int:aid>/update', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def action_update(aid):
    db = get_db()
    a = _action_or_404(db, aid)
    new_status = (request.form.get('status') or '').upper()
    note = (request.form.get('note') or '').strip()
    err = L.action_update_error(a['status'], new_status, note)
    if err:
        _flash_rule_errors([err])
        return _back_to(a['meeting_id'])
    done = new_status == 'COMPLETED'
    db.execute("""UPDATE meeting_action_items SET status = %s, completion_date = %s,
                  completion_notes = CASE WHEN %s THEN %s ELSE completion_notes END, updated_by = %s, updated_at = NOW()
                  WHERE id = %s""",
               (new_status, date.today().isoformat() if done else None, bool(note), note, current_user.id, aid))
    _event(db, a['meeting_id'], 'action', aid, 'action_status', a['status'], new_status, note or None)
    db.commit()
    _audit('Meeting Action Updated', a['meeting_id'], f"Action #{a['action_number']}: {a['status']} -> {new_status}")
    flash(_('Action updated.'), 'success')
    return _back_to(a['meeting_id'])


@governance_bp.route('/meeting-actions/<int:aid>/carry', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def action_carry(aid):
    """Carry an open action to a later meeting: it is listed on that meeting's
    agenda as a follow-up item and stays open until it is completed."""
    db = get_db()
    a = _action_or_404(db, aid)
    target = request.form.get('target_meeting_id', type=int)
    tm = BoardMeeting.get_by_id(target) if target else None
    if not tm or tm.id == a['meeting_id']:
        flash(_('Choose the later meeting to carry this action to.'), 'danger')
        return _back_to(a['meeting_id'])
    if (a['status'] or '').upper() in L.CLOSED_ACTION_STATUSES:
        flash(_('This action is already closed.'), 'danger')
        return _back_to(a['meeting_id'])
    n = db.execute("SELECT COALESCE(MAX(item_number), 0) + 1 AS n FROM meeting_agenda_items WHERE meeting_id = %s",
                   (tm.id,)).fetchone()['n']
    src = BoardMeeting.get_by_id(a['meeting_id'])
    title = _('Follow-up action from %(ref)s: %(text)s', ref=(src.meeting_reference or src.meeting_date) if src else '',
              text=a['action_description'])[:500]
    db.execute("""INSERT INTO meeting_agenda_items (meeting_id, item_number, item_title, item_description, item_type,
                  presenter_name, display_order) VALUES (%s,%s,%s,%s,'FOLLOW_UP',%s,%s)""",
               (tm.id, n, title, a['action_description'], a['responsible_person'], n))
    # keep the free-text agenda shown on the meeting page in step
    db.execute("UPDATE board_meetings SET agenda = COALESCE(NULLIF(agenda, ''), '') || %s WHERE id = %s",
               (('\n' if tm.agenda else '') + f'- {title}', tm.id))
    db.execute("UPDATE meeting_action_items SET carried_to_meeting_id = %s, updated_by = %s, updated_at = NOW() WHERE id = %s",
               (tm.id, current_user.id, aid))
    _event(db, a['meeting_id'], 'action', aid, 'action_carried', a['status'], a['status'],
           f'-> {tm.meeting_reference or tm.meeting_date}')
    _event(db, tm.id, 'action', aid, 'action_received', None, a['status'],
           f'<- {(src.meeting_reference or src.meeting_date) if src else ""}')
    db.commit()
    _audit('Meeting Action Carried Forward', a['meeting_id'], f"Action #{a['action_number']} -> meeting {tm.id}")
    flash(_('Action carried to the agenda of %(ref)s.', ref=tm.meeting_reference or tm.meeting_date), 'success')
    return _back_to(a['meeting_id'])


@governance_bp.route('/meeting-actions')
@login_required
@permission_required('governance')
def action_tracker():
    db = get_db()
    show = request.args.get('show', 'open')
    where = {"open": "UPPER(COALESCE(a.status, 'PENDING')) NOT IN ('COMPLETED', 'CANCELLED')",
             "all": "TRUE"}.get(show if show != 'overdue' else 'open', 'TRUE')
    rows = _decorate_actions(db.execute(ACTION_SELECT + " WHERE " + where +
                                        " ORDER BY a.due_date NULLS LAST, a.id").fetchall())
    if show == 'overdue':
        rows = [r for r in rows if r['overdue']]
    return render_template('governance/meeting_actions.html', actions=rows, show=show,
                           overdue_count=sum(1 for r in rows if r['overdue']))


# ------------------------------------------------------------------ external members
@governance_bp.route('/meeting/<int:id>/external/add', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def external_add(id):
    _meeting_or_404(id)
    db = get_db()
    data = {k: (request.form.get(k) or '').strip() for k in ('full_name', 'email', 'role', 'organisation')}
    errors = L.external_errors(data)
    if errors:
        _flash_rule_errors(errors)
        return redirect(url_for('governance.meeting_summary', id=id) + '#attendees')
    eid = db.execute("""INSERT INTO meeting_external_attendees (meeting_id, full_name, email, role, organisation, invited_by)
                        VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (id, data['full_name'][:200], data['email'][:200] or None, data['role'][:200],
                      data['organisation'][:200] or None, current_user.id)).fetchone()['id']
    _event(db, id, 'attendee', eid, 'external_invited', None, 'INVITED', f"{data['full_name']} ({data['role']})")
    db.commit()
    _audit('Meeting External Invitee Added', id, data['full_name'])
    flash(_('%(name)s added as an external participant.', name=data['full_name']), 'success')
    return redirect(url_for('governance.meeting_summary', id=id) + '#attendees')


@governance_bp.route('/meeting/<int:id>/external/<int:eid>/remove', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def external_remove(id, eid):
    db = get_db()
    row = db.execute("SELECT * FROM meeting_external_attendees WHERE id = %s AND meeting_id = %s", (eid, id)).fetchone()
    if not row:
        abort(404)
    if row['attendance_status'] != 'INVITED':
        flash(_('Attendance is already recorded for this participant; it cannot be removed.'), 'danger')
        return redirect(url_for('governance.meeting_summary', id=id) + '#attendees')
    db.execute("DELETE FROM meeting_external_attendees WHERE id = %s", (eid,))
    _event(db, id, 'attendee', eid, 'external_removed', 'INVITED', None, row['full_name'])
    db.commit()
    flash(_('Participant removed.'), 'info')
    return redirect(url_for('governance.meeting_summary', id=id) + '#attendees')


def save_external_attendance(db, mid, form):
    """Called by the attendance sheet: one status per external participant."""
    for r in db.execute("SELECT id, attendance_status FROM meeting_external_attendees WHERE meeting_id = %s",
                        (mid,)).fetchall():
        st = form.get(f'ext_status_{r["id"]}')
        if st in L.EXTERNAL_STATUSES and st != r['attendance_status']:
            db.execute("""UPDATE meeting_external_attendees SET attendance_status = %s, attendance_notes = %s,
                          recorded_by = %s, recorded_at = NOW() WHERE id = %s""",
                       (st, (form.get(f'ext_notes_{r["id"]}') or '').strip() or None, current_user.id, r['id']))
            _event(db, mid, 'attendee', r['id'], 'external_attendance', r['attendance_status'], st)


def sync_member_attendees(db, mid, member_ids):
    """Edit the invited board/committee members after scheduling. Rows whose
    attendance is already recorded are kept; returns the names that could not
    be removed for that reason."""
    wanted = {int(x) for x in member_ids if str(x).isdigit()}
    rows = [dict(r) for r in db.execute(
        """SELECT ma.*, bm.member_name FROM meeting_attendance ma JOIN board_members bm ON bm.id = ma.member_id
           WHERE ma.meeting_id = %s""", (mid,)).fetchall()]
    have = {r['member_id']: r for r in rows}
    kept = []
    for member_id in wanted - set(have):
        db.execute("INSERT INTO meeting_attendance (meeting_id, member_id, attended) VALUES (%s,%s,0) "
                   "ON CONFLICT (meeting_id, member_id) DO NOTHING", (mid, member_id))
        _event(db, mid, 'attendee', member_id, 'member_invited')
    for member_id, r in have.items():
        if member_id in wanted:
            continue
        if r.get('recorded_at'):
            kept.append(r['member_name'])
            continue
        db.execute("DELETE FROM meeting_attendance WHERE id = %s", (r['id'],))
        _event(db, mid, 'attendee', member_id, 'member_uninvited', note=r['member_name'])
    return kept
