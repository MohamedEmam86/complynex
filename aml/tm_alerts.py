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
Transaction-monitoring alerts: workflow actions and their append-only history.

Every action is one function (assign_alert, start_investigation, escalate_alert,
mark_false_positive, close_alert, mark_sar_created, add_note). Each writes one
row to aml_tm_alert_events (who / when / what — the table refuses UPDATE and
DELETE) and, when the status changes, ends in on_alert_status_change(), the
single hook for a central case-tracking sync.
"""

from datetime import datetime

from database.db import get_db


def N_(s):
    return s


class AlertError(ValueError):
    pass


STATUSES = [  # code, EN, AR
    ('NEW', N_('New'), 'جديد'),
    ('ASSIGNED', N_('Assigned'), 'مُسند'),
    ('INVESTIGATING', N_('Investigating'), 'قيد الفحص'),
    ('ESCALATED', N_('Escalated'), 'مُصعَّد'),
    ('FALSE_POSITIVE', N_('False positive'), 'إيجابي كاذب'),
    ('SAR_CREATED', N_('STR case opened'), 'فُتحت حالة إخطار'),
    ('CLOSED', N_('Closed'), 'مغلق'),
]
CLOSED_STATUSES = ('FALSE_POSITIVE', 'CLOSED', 'SAR_CREATED')
SEVERITIES = [('HIGH', N_('High'), 'مرتفع'), ('MEDIUM', N_('Medium'), 'متوسط'), ('LOW', N_('Low'), 'منخفض'),
              ('CRITICAL', N_('Critical'), 'حرج')]
ACTIONS = [  # event action, EN, AR
    ('assign', N_('Assigned'), 'إسناد'),
    ('investigate', N_('Investigation started'), 'بدء الفحص'),
    ('escalate', N_('Escalated'), 'تصعيد'),
    ('false_positive', N_('Closed as false positive'), 'إغلاق كإيجابي كاذب'),
    ('close', N_('Closed'), 'إغلاق'),
    ('note', N_('Note added'), 'إضافة ملاحظة'),
    ('sar_created', N_('STR case opened'), 'فتح حالة إخطار'),
]
SEVERITY_SCORE = {'CRITICAL': 95, 'HIGH': 80, 'MEDIUM': 50, 'LOW': 20}


def labels(pairs, ar=False):
    return {c: (a if ar else e) for c, e, a in pairs}


def alert_score(severity, tx_scores=()):
    """0-100 score shown and filtered on the queue: the rule's severity weight,
    raised to the highest risk score of the triggering transactions."""
    base = SEVERITY_SCORE.get((severity or '').upper(), 0)
    tx = [int(s) for s in tx_scores or () if s is not None]
    return max([base] + tx) if tx else base


def rule_label(rule_name, rule_name_ar, ar=False):
    return (rule_name_ar if ar and rule_name_ar else rule_name) or ''


# ------------------------------------------------------------------ core
def _get(db, alert_id):
    row = db.execute("SELECT * FROM tm_alerts WHERE id = %s", (alert_id,)).fetchone()
    if not row:
        raise AlertError(N_('Alert not found'))
    return dict(row)


def log_event(db, alert_id, action, actor_id, from_status=None, to_status=None, note=None, assigned_to=None):
    db.execute("""INSERT INTO aml_tm_alert_events (alert_id, action, from_status, to_status, assigned_to, note, actor_id)
                  VALUES (%s,%s,%s,%s,%s,%s,%s)""",
               (alert_id, action, from_status, to_status, assigned_to, (note or '').strip() or None, actor_id))


def events(db, alert_id):
    return [dict(r) for r in db.execute("""
        SELECT e.*, a.first_name || ' ' || a.last_name AS actor_name,
               t.first_name || ' ' || t.last_name AS assignee_name
          FROM aml_tm_alert_events e LEFT JOIN users a ON a.id = e.actor_id LEFT JOIN users t ON t.id = e.assigned_to
         WHERE e.alert_id = %s ORDER BY e.id DESC""", (alert_id,)).fetchall()]


def on_alert_status_change(db, alert_id, old_status, new_status, actor_id):
    """Called after every alert status change — the hook for case tracking."""
    from models.case import sync_case
    sync_case('TM_ALERT', alert_id)


def _set_status(db, alert, new_status, action, actor_id, note, assigned_to=None, require_note=False):
    old = alert.get('status') or 'NEW'
    if old in CLOSED_STATUSES:
        raise AlertError(N_('This alert is closed; only notes can be added.'))
    note = (note or '').strip()
    if require_note and not note:
        raise AlertError(N_('Notes are required to close an alert or mark it as a false positive.'))
    db.execute("""UPDATE tm_alerts SET status = %s, investigation_notes = COALESCE(NULLIF(%s, ''), investigation_notes),
                  assigned_to = COALESCE(%s, assigned_to), disposition = %s, disposition_by = %s, disposition_date = %s
                  WHERE id = %s""",
               (new_status, note, assigned_to, action.upper(), actor_id, datetime.now().date().isoformat(), alert['id']))
    log_event(db, alert['id'], action, actor_id, old, new_status, note, assigned_to)
    db.commit()
    if new_status != old:
        on_alert_status_change(db, alert['id'], old, new_status, actor_id)
    return old


def assign_alert(alert_id, assignee_id, actor_id, note=None, db=None):
    db = db or get_db()
    from aml.str_register import is_aml_staff
    alert = _get(db, alert_id)
    if not assignee_id or not is_aml_staff(db, assignee_id):
        raise AlertError(N_('Choose a compliance user.'))
    if (alert.get('status') or 'NEW') in CLOSED_STATUSES:
        raise AlertError(N_('This alert is closed; only notes can be added.'))
    new = 'ASSIGNED' if (alert.get('status') or 'NEW') == 'NEW' else alert['status']
    return _set_status(db, alert, new, 'assign', actor_id, note, assigned_to=int(assignee_id))


def start_investigation(alert_id, actor_id, note=None, db=None):
    db = db or get_db()
    return _set_status(db, _get(db, alert_id), 'INVESTIGATING', 'investigate', actor_id, note)


def escalate_alert(alert_id, actor_id, note=None, db=None):
    db = db or get_db()
    return _set_status(db, _get(db, alert_id), 'ESCALATED', 'escalate', actor_id, note)


def mark_false_positive(alert_id, actor_id, note, db=None):
    db = db or get_db()
    return _set_status(db, _get(db, alert_id), 'FALSE_POSITIVE', 'false_positive', actor_id, note, require_note=True)


def close_alert(alert_id, actor_id, note, db=None):
    db = db or get_db()
    return _set_status(db, _get(db, alert_id), 'CLOSED', 'close', actor_id, note, require_note=True)


def mark_sar_created(alert_id, sar_id, sar_reference, actor_id, db=None):
    db = db or get_db()
    alert = _get(db, alert_id)
    old = alert.get('status') or 'NEW'
    db.execute("UPDATE tm_alerts SET status = 'SAR_CREATED', sar_id = %s, disposition = 'SAR_CREATED', "
               "disposition_by = %s, disposition_date = %s WHERE id = %s",
               (sar_id, actor_id, datetime.now().date().isoformat(), alert_id))
    log_event(db, alert_id, 'sar_created', actor_id, old, 'SAR_CREATED', f'STR case {sar_reference}')
    db.commit()
    if old != 'SAR_CREATED':
        on_alert_status_change(db, alert_id, old, 'SAR_CREATED', actor_id)


def add_note(alert_id, actor_id, note, db=None):
    db = db or get_db()
    alert = _get(db, alert_id)
    note = (note or '').strip()
    if len(note) < 3:
        raise AlertError(N_('Write the note.'))
    db.execute("UPDATE tm_alerts SET investigation_notes = %s WHERE id = %s", (note, alert_id))
    log_event(db, alert_id, 'note', actor_id, alert.get('status'), alert.get('status'), note)
    db.commit()


def triggered_ids(alert):
    import json
    try:
        ids = json.loads(alert.get('triggered_transactions') or '[]')
        return [int(i) for i in ids if str(i).isdigit()]
    except (ValueError, TypeError):
        return []
