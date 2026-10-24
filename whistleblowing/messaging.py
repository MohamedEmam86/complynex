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
Two-way messaging between the compliance team and the (anonymous) reporter.

Confidentiality rules:
- The reporter only ever sees "Compliance team" as the sender of staff messages;
  ``public_thread()`` strips every staff identifier before it reaches a template.
- Staff never see who the anonymous reporter is — the thread is keyed on the case only.
- A reporter reply notifies the current assignee in-app (or, if the case is
  unassigned, the whistleblowing editors) without quoting the message.
"""
from datetime import datetime, timedelta

from database.db import get_db

MAX_MESSAGE = 5000
DUPLICATE_WINDOW = timedelta(minutes=2)


def clean_body(body):
    """Trimmed message text, or None when empty. Over-long text is cut at MAX_MESSAGE."""
    body = (body or '').strip()
    return body[:MAX_MESSAGE] if body else None


def thread(case_id):
    """Full thread for staff (includes the staff author's name)."""
    rows = get_db().execute("""
        SELECT m.*, NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '') AS staff_name
        FROM whistleblowing_messages m LEFT JOIN users u ON u.id = m.staff_user_id
        WHERE m.case_id = %s ORDER BY m.created_at, m.id""", (case_id,)).fetchall()
    return [dict(r) for r in rows]


def to_public(messages):
    """What the reporter may see: sender role, text, time — nothing about staff identity."""
    return [{'sender': m['sender'], 'body': m['body'], 'created_at': m['created_at']} for m in messages]


def public_thread(case_id):
    return to_public(thread(case_id))


def unread_count(case_id):
    row = get_db().execute("""SELECT COUNT(*) AS n FROM whistleblowing_messages
                              WHERE case_id = %s AND sender = 'REPORTER' AND read_by_staff_at IS NULL""",
                           (case_id,)).fetchone()
    return row['n'] if row else 0


def mark_read(case_id, user_id):
    db = get_db()
    db.execute("""UPDATE whistleblowing_messages SET read_by_staff_at = NOW(), read_by_staff = %s
                  WHERE case_id = %s AND sender = 'REPORTER' AND read_by_staff_at IS NULL""", (user_id, case_id))
    db.commit()


def is_duplicate(last, sender, body, now=None):
    """Same sender re-posting the same text within the window (e.g. a browser refresh)."""
    if not last:
        return False
    now = now or datetime.now()
    return (last.get('sender') == sender and (last.get('body') or '').strip() == body
            and last.get('created_at') and now - last['created_at'] < DUPLICATE_WINDOW)


def _last(case_id):
    row = get_db().execute("SELECT * FROM whistleblowing_messages WHERE case_id = %s ORDER BY id DESC LIMIT 1",
                           (case_id,)).fetchone()
    return dict(row) if row else None


def post_reporter_message(case, body):
    """Store a reply from the reporter and notify staff. Returns True if stored."""
    if is_duplicate(_last(case['id']), 'REPORTER', body):
        return False
    db = get_db()
    db.execute("INSERT INTO whistleblowing_messages (case_id, sender, body) VALUES (%s, 'REPORTER', %s)",
               (case['id'], body))
    db.commit()
    _notify_staff(case)
    return True


def post_staff_message(case_id, body, user_id):
    if is_duplicate(_last(case_id), 'STAFF', body):
        return False
    db = get_db()
    db.execute("INSERT INTO whistleblowing_messages (case_id, sender, body, staff_user_id) VALUES (%s, 'STAFF', %s, %s)",
               (case_id, body, user_id))
    db.commit()
    return True


def _notify_staff(case):
    from services.notification_service import notify
    targets = [case['assigned_to']] if case.get('assigned_to') else [
        r['id'] for r in get_db().execute(
            """SELECT id FROM users WHERE is_active = 1
               AND (role = 'admin' OR perm_whistleblowing IN ('edit', 'admin'))""").fetchall()]
    ref = case.get('case_number') or case['id']
    notify(targets, f'New message from the reporter on whistleblowing case {ref}',
           'The reporter replied through the secure tracking page. Open the case to read it.',
           link=f"/whistleblowing/case/{case['id']}", category='warning')
