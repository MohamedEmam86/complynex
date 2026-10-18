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
Periodic reconciliation for the unified `cases` table (see models/case.py).

The 4 source tables (tm_alerts, whistleblowing_cases, consumer_complaints,
cyber_incidents) get an inline Case.sync_from_source() call at their one
creation choke point each, so a case appears in the rollup immediately on
creation. But status/assignment changes after creation happen through
several update call sites per table that aren't individually hooked (higher
regression risk than it's worth chasing down every one) — this script
re-syncs all of them on a timer instead, trading instant consistency for
"eventually consistent within one run interval" (see
complynex-case-sync.timer), the same trade-off complynex-risk-audit-
escalation.timer already makes for risk/audit notifications.

Also runs SLA overdue escalation, mirroring risk_audit_escalation.py's
style exactly: notify the assignee, escalate to all compliance officers once
more than 7 days overdue, at-most-once-per-user-per-link-per-day. Only
cases opened on/after case_escalation_settings.cutover_at are eligible —
see escalate_overdue_cases()'s docstring for why.

Safe to run manually: python scripts/sync_cases.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _already_notified_today(db, user_id, link):
    row = db.execute(
        "SELECT 1 FROM notifications WHERE user_id = %s AND link = %s "
        "AND created_at LIKE (CURRENT_DATE::text || '%%') LIMIT 1",
        (user_id, link)
    ).fetchone()
    return row is not None


def _notify_once_per_day(db, user_id, title, message, link, n_type):
    from models.notification import Notification
    if not user_id or _already_notified_today(db, user_id, link):
        return False
    Notification.create(user_id=user_id, title=title, message=message, link=link, n_type=n_type)
    return True


def resync_all_cases():
    from database.db import get_db
    from models.case import Case

    db = get_db()
    counts = {'TM_ALERT': 0, 'WHISTLEBLOWING': 0, 'CONSUMER_COMPLAINT': 0, 'CYBER_INCIDENT': 0}

    for row in db.execute("SELECT id FROM tm_alerts").fetchall():
        Case.sync_from_source('TM_ALERT', row['id'])
        counts['TM_ALERT'] += 1

    for row in db.execute("SELECT id FROM whistleblowing_cases").fetchall():
        Case.sync_from_source('WHISTLEBLOWING', row['id'])
        counts['WHISTLEBLOWING'] += 1

    for row in db.execute("SELECT id FROM consumer_complaints").fetchall():
        Case.sync_from_source('CONSUMER_COMPLAINT', row['id'])
        counts['CONSUMER_COMPLAINT'] += 1

    for row in db.execute("SELECT id FROM cyber_incidents").fetchall():
        Case.sync_from_source('CYBER_INCIDENT', row['id'])
        counts['CYBER_INCIDENT'] += 1

    return counts


def escalate_overdue_cases():
    """
    Only escalates cases opened on/after case_escalation_settings.cutover_at
    (see database/schema_case_escalation.sql). Without this filter,
    backfilled historical cases would all read as instantly overdue against
    a freshly-applied SLA clock and fire one large notification burst the
    first time this runs — a known issue found during P2 validation against
    real production data, not a hypothetical.
    """
    from database.db import get_db
    from models.user import User

    db = get_db()
    counts = {'case_overdue': 0, 'case_overdue_escalated': 0}

    cutover_row = db.execute("SELECT cutover_at FROM case_escalation_settings WHERE id = 1").fetchone()
    if not cutover_row:
        raise RuntimeError(
            "case_escalation_settings has no row — run scripts/migrate_case_escalation_schema.py first."
        )
    cutover_at = cutover_row['cutover_at']

    overdue = db.execute("""
        SELECT * FROM cases
        WHERE status NOT IN ('RESOLVED', 'CLOSED') AND due_date IS NOT NULL AND due_date < NOW()
          AND opened_at >= %s
    """, (cutover_at,)).fetchall()

    for c in overdue:
        link = f'/cases/{c["id"]}'
        title = f"Case overdue: {c['reference'] or c['case_type']}"
        message = f"{c['title'] or c['case_type']} was due on {c['due_date']}."
        if _notify_once_per_day(db, c['assigned_to'], title, message, link, 'case_overdue'):
            counts['case_overdue'] += 1

        days_overdue_row = db.execute(
            "SELECT EXTRACT(DAY FROM NOW() - %s) AS days_overdue", (c['due_date'],)
        ).fetchone()
        if days_overdue_row and days_overdue_row['days_overdue'] and days_overdue_row['days_overdue'] > 7:
            for officer in User.get_all_compliance_officers():
                if _notify_once_per_day(db, officer.id, f"Escalation: {title}",
                                         f"{message} (more than 7 days overdue)", link, 'case_overdue_escalated'):
                    counts['case_overdue_escalated'] += 1

    return counts


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        sync_counts = resync_all_cases()
        for key, value in sync_counts.items():
            print(f"synced {key}: {value}")

        escalation_counts = escalate_overdue_cases()
        for key, value in escalation_counts.items():
            print(f"{key}: {value}")
