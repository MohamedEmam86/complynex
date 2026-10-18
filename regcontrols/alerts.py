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
Alerts for regcontrols: one live alert per subject (control / evidence item /
finding), sent in-app and by email through services.notification_service,
re-sent every rc.alert_renotify_days, and escalated to the Head(s) of
Compliance after rc.escalation_days. A failed critical control can also open
a REG_CONTROL case in the unified case list.

Who is "Head of Compliance": Settings 'regcontrols_compliance_head_ids'
(comma-separated user ids) when set, otherwise every active admin /
compliance officer.
"""

import logging
from datetime import datetime

from database.db import get_db

from . import logic, params

logger = logging.getLogger(__name__)

LINKS = {
    'control': '/regcontrols/controls/{id}',
    'evidence': '/regcontrols/evidence/{id}',
    'finding': '/regcontrols/findings/{id}',
}


def _param(key, default, db):
    try:
        return params.get_param(key, default=default, db=db)
    except Exception:
        return default


def compliance_heads(db=None):
    db = db or get_db()
    try:
        from models.settings import Settings
        raw = Settings.get('regcontrols_compliance_head_ids', '') or ''
    except Exception:
        raw = ''
    ids = [int(x) for x in str(raw).replace(';', ',').split(',') if x.strip().isdigit()]
    if ids:
        return ids
    return [r['id'] for r in db.execute(
        "SELECT id FROM users WHERE role IN ('admin', 'compliance_officer') AND is_active = 1").fetchall()]


def _send(user_ids, title, message, link):
    try:
        from services.notification_service import notify
        return notify(user_ids, title, message, link=link, category='regcontrols', channels=('inapp', 'email'))
    except Exception:
        logger.exception('regcontrols: notification failed')
        return None


def raise_alert(alert_type, title, message=None, *, severity='high', control_id=None, evidence_id=None,
                finding_id=None, run_id=None, owner_user_id=None, org_unit_id=None, link=None, db=None):
    """Open (or refresh) the live alert for this subject and notify its owner.

    Returns the rc_alerts id. A refresh does not re-notify until the
    re-notify interval has passed, so a daily failing check sends a reminder
    every few days rather than every day.
    """
    db = db or get_db()
    now = datetime.now()
    existing = db.execute("""
        SELECT * FROM rc_alerts WHERE alert_type = %s AND COALESCE(control_id, 0) = %s
          AND COALESCE(evidence_id, 0) = %s AND COALESCE(finding_id, 0) = %s
          AND status IN ('open', 'acknowledged')
    """, (alert_type, control_id or 0, evidence_id or 0, finding_id or 0)).fetchone()
    recipients = [owner_user_id] if owner_user_id else compliance_heads(db)
    if existing:
        existing = dict(existing)
        db.execute("UPDATE rc_alerts SET run_id = COALESCE(%s, run_id), message = %s, severity = %s WHERE id = %s",
                   (run_id, message, severity, existing['id']))
        db.commit()
        if logic.renotify_due(existing, now, _param('rc.alert_renotify_days', 3, db)) \
                and existing['status'] == 'open':
            _send(recipients, title, message or title, link)
            db.execute("UPDATE rc_alerts SET last_notified_at = %s, notify_count = notify_count + 1 WHERE id = %s",
                       (now, existing['id']))
            db.commit()
        return existing['id']
    alert_id = db.execute("""
        INSERT INTO rc_alerts (alert_type, severity, control_id, evidence_id, finding_id, run_id, org_unit_id,
                               title, message, owner_user_id, raised_at, last_notified_at, notify_count)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1) RETURNING id
    """, (alert_type, severity, control_id, evidence_id, finding_id, run_id, org_unit_id, title[:300],
          message, owner_user_id, now, now)).fetchone()['id']
    db.commit()
    _send(recipients, title, message or title, link)
    return alert_id


def resolve_alerts(alert_types, *, control_id=None, evidence_id=None, finding_id=None, note=None,
                   db=None):
    db = db or get_db()
    if isinstance(alert_types, str):
        alert_types = [alert_types]
    clauses, args = ["status IN ('open', 'acknowledged')", "alert_type = ANY(%s)"], [list(alert_types)]
    for col, val in (('control_id', control_id), ('evidence_id', evidence_id), ('finding_id', finding_id)):
        if val:
            clauses.append(f'{col} = %s')
            args.append(val)
    rows = db.execute(f"UPDATE rc_alerts SET status = 'resolved', resolved_at = %s, resolution_note = %s "
                      f"WHERE {' AND '.join(clauses)} RETURNING id, case_id",
                      (datetime.now(), note, *args)).fetchall()
    db.commit()
    for r in rows:
        if r['case_id']:
            _sync_case(r['id'])
    return len(rows)


def acknowledge(alert_id, user_id, db=None):
    db = db or get_db()
    db.execute("UPDATE rc_alerts SET status = 'acknowledged', acknowledged_by = %s, acknowledged_at = %s "
               "WHERE id = %s AND status = 'open'", (user_id, datetime.now(), alert_id))
    db.commit()
    _sync_case(alert_id)


def resolve(alert_id, user_id, note, db=None):
    db = db or get_db()
    db.execute("UPDATE rc_alerts SET status = 'resolved', resolved_at = %s, resolution_note = %s "
               "WHERE id = %s AND status <> 'resolved'",
               (datetime.now(), f'{note or ""} (user {user_id})'.strip(), alert_id))
    db.commit()
    _sync_case(alert_id)


def _sync_case(alert_id):
    try:
        from models.case import Case
        row = get_db().execute("SELECT case_id FROM rc_alerts WHERE id = %s", (alert_id,)).fetchone()
        if row and row['case_id']:
            Case.sync_from_source('REG_CONTROL', alert_id)
    except Exception:
        logger.warning('regcontrols: case sync failed for alert %s', alert_id, exc_info=True)


def maybe_open_case(alert_id, control, db=None):
    """Open a unified case for a failed control when the control asks for it,
    or when rc.auto_case_on_failure is on and the control is critical."""
    db = db or get_db()
    wanted = bool(control.get('auto_create_case')) or (
        control.get('criticality') == 'critical' and bool(_param('rc.auto_case_on_failure', False, db)))
    if not wanted:
        return None
    try:
        from models.case import Case
        case_id = Case.sync_from_source('REG_CONTROL', alert_id)
        db.execute("UPDATE rc_alerts SET case_id = %s WHERE id = %s", (case_id, alert_id))
        db.commit()
        return case_id
    except Exception:
        logger.exception('regcontrols: could not open case for alert %s', alert_id)
        db.rollback()
        return None


# ------------------------------------------------------------------ hooks
def handle_run(control, run, db=None):
    """Engine post-run hook: open/refresh the failure alert, or clear it on pass."""
    db = db or get_db()
    if run['status'] == 'fail':
        title = f"{control['control_code']} failed: {control['title_en']}"
        alert_id = raise_alert(
            'control_failed', title, run.get('summary') or title, severity=control.get('criticality') or 'high',
            control_id=control['id'], run_id=run['id'], owner_user_id=control.get('owner_user_id'),
            org_unit_id=run.get('org_unit_id'), link=LINKS['control'].format(id=control['id']), db=db)
        if not db.execute("SELECT case_id FROM rc_alerts WHERE id = %s", (alert_id,)).fetchone()['case_id']:
            maybe_open_case(alert_id, control, db)
    elif run['status'] in ('pass', 'not_applicable'):
        resolve_alerts('control_failed', control_id=control['id'], note=f'Control passed (run {run["id"]})', db=db)


def sweep_escalations(now=None, db=None):
    """Escalate stale open alerts to the Head(s) of Compliance and re-notify
    owners. Returns (escalated, reminded)."""
    db = db or get_db()
    now = now or datetime.now()
    esc_days = _param('rc.escalation_days', 5, db)
    renotify_days = _param('rc.alert_renotify_days', 3, db)
    heads = compliance_heads(db)
    escalated = reminded = 0
    for a in [dict(r) for r in db.execute(
            "SELECT * FROM rc_alerts WHERE status IN ('open', 'acknowledged')").fetchall()]:
        link = (LINKS['control'].format(id=a['control_id']) if a['control_id'] else
                LINKS['finding'].format(id=a['finding_id']) if a['finding_id'] else
                LINKS['evidence'].format(id=a['evidence_id']) if a['evidence_id'] else None)
        if logic.escalation_due(a, now, esc_days):
            days = (now - a['raised_at']).days
            _send(heads, f"ESCALATION: {a['title']}",
                  f"Open for {days} day(s) without resolution. {a['message'] or ''}".strip(), link)
            db.execute("UPDATE rc_alerts SET escalated_at = %s, escalated_to = %s WHERE id = %s",
                       (now, heads, a['id']))
            escalated += 1
        elif a['status'] == 'open' and a['owner_user_id'] and logic.renotify_due(a, now, renotify_days):
            _send([a['owner_user_id']], f"Reminder: {a['title']}", a['message'] or a['title'], link)
            db.execute("UPDATE rc_alerts SET last_notified_at = %s, notify_count = notify_count + 1 WHERE id = %s",
                       (now, a['id']))
            reminded += 1
    db.commit()
    return escalated, reminded
