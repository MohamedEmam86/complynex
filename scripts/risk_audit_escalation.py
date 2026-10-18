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
Daily escalation job for the Risk Management and Internal Audit modules:
  - overdue risk reviews (+ escalation to compliance officers after +7 days)
  - risk treatments due soon / overdue
  - risk treatments awaiting independent verification
  - a pending-suggestions digest for the Suggested-Risks inbox
  - overdue audit findings
  - audit findings awaiting independent verification

Each check is idempotent per calendar day (guarded by a check against
existing notifications with the same link/user created today), so re-running
this script manually or after a missed run never double-notifies. Overdue
items are reminded daily until resolved — that is intentional, not a bug.

Runs as a daily systemd timer (complynex-risk-audit-escalation.timer),
mirroring the existing complynex-ekyc-purge.timer/.service pattern.
Safe to run manually: python scripts/risk_audit_escalation.py
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


def run_all_escalation_checks():
    # Plain relative paths, not url_for() — this script runs outside any
    # request context and Flask's url_for requires SERVER_NAME to build URLs
    # without one. These must stay in sync with the blueprint url_prefixes.
    def _risk_url(risk_pk):
        return f'/risk-management/register/{risk_pk}'

    def _treatment_url(treatment_id):
        return f'/risk-management/treatments/{treatment_id}'

    def _suggestions_url():
        return '/risk-management/suggestions'

    def _finding_url(finding_id):
        return f'/internal-audit/findings/{finding_id}'

    from database.db import get_db
    from models.user import User
    from models.risk import get_pending_risk_suggestions
    from models.internal_audit import AuditTeamMember, AuditProject

    db = get_db()
    counts = {'risk_review_overdue': 0, 'risk_review_escalated': 0, 'treatment_due_soon': 0,
              'treatment_overdue': 0, 'treatment_pending_verification': 0, 'suggestions_digest': 0,
              'finding_overdue': 0, 'finding_pending_verification': 0}

    # --- Overdue risk reviews ---
    overdue_risks = db.execute(
        "SELECT id, risk_id, risk_title, risk_owner_id, next_review_date FROM risks "
        "WHERE status = 'ACTIVE' AND next_review_date < CURRENT_DATE"
    ).fetchall()
    for r in overdue_risks:
        link = _risk_url(r['id'])
        if _notify_once_per_day(db, r['risk_owner_id'], f"Risk review overdue: {r['risk_id']}",
                                 f"The review for {r['risk_id']} ({r['risk_title']}) was due on {r['next_review_date']}.",
                                 link, 'risk_review_overdue'):
            counts['risk_review_overdue'] += 1
        # Escalate to compliance officers once the review is more than 7 days overdue.
        row = db.execute("SELECT (CURRENT_DATE - %s::date) AS days_overdue", (r['next_review_date'],)).fetchone()
        if row and row['days_overdue'] and row['days_overdue'] > 7:
            for officer in User.get_all_compliance_officers():
                if _notify_once_per_day(db, officer.id, f"Escalation: risk review overdue {r['risk_id']}",
                                         f"{r['risk_id']} ({r['risk_title']}) review is more than 7 days overdue.",
                                         link, 'risk_review_escalated'):
                    counts['risk_review_escalated'] += 1

    # --- Risk treatments: due soon (T-7) / overdue / pending verification ---
    due_soon = db.execute(
        "SELECT rt.id, rt.treatment_owner_id, rt.risk_id, r.risk_id AS risk_ref, r.risk_title FROM risk_treatments rt "
        "JOIN risks r ON r.id = rt.risk_id "
        "WHERE rt.status IN ('PROPOSED','APPROVED','IN_PROGRESS') AND rt.target_date = CURRENT_DATE + INTERVAL '7 days'"
    ).fetchall()
    for t in due_soon:
        link = _treatment_url(t['id'])
        if _notify_once_per_day(db, t['treatment_owner_id'], f"Treatment due in 7 days: {t['risk_ref']}",
                                 f"Your treatment for {t['risk_ref']} ({t['risk_title']}) is due in 7 days.",
                                 link, 'treatment_due_soon'):
            counts['treatment_due_soon'] += 1

    overdue_treatments = db.execute(
        "SELECT rt.id, rt.treatment_owner_id, rt.risk_id, r.risk_id AS risk_ref, r.risk_title, r.risk_owner_id "
        "FROM risk_treatments rt JOIN risks r ON r.id = rt.risk_id "
        "WHERE rt.status IN ('PROPOSED','APPROVED','IN_PROGRESS') AND rt.target_date < CURRENT_DATE"
    ).fetchall()
    for t in overdue_treatments:
        link = _treatment_url(t['id'])
        for uid in {t['treatment_owner_id'], t['risk_owner_id']}:
            if _notify_once_per_day(db, uid, f"Treatment overdue: {t['risk_ref']}",
                                     f"The treatment for {t['risk_ref']} ({t['risk_title']}) is overdue.",
                                     link, 'treatment_overdue'):
                counts['treatment_overdue'] += 1

    completed_treatments = db.execute(
        "SELECT id, risk_id FROM risk_treatments WHERE status = 'COMPLETED'"
    ).fetchall()
    for t in completed_treatments:
        link = _treatment_url(t['id'])
        for officer in User.get_all_compliance_officers():
            if _notify_once_per_day(db, officer.id, 'Treatment awaiting independent verification',
                                     'A completed risk treatment is awaiting independent verification.',
                                     link, 'treatment_pending_verification'):
                counts['treatment_pending_verification'] += 1

    # --- Suggested Risks digest (batched, not per-item) ---
    suggestions = get_pending_risk_suggestions()
    if suggestions:
        link = _suggestions_url()
        risk_editors = [u for u in User.get_all() if u.can_edit('risk_management')]
        for u in risk_editors:
            if _notify_once_per_day(db, u.id, f"{len(suggestions)} suggested risk(s) pending review",
                                     'New high-severity records from other modules are awaiting risk review.',
                                     link, 'risk_suggestion_pending'):
                counts['suggestions_digest'] += 1

    # --- Overdue audit findings ---
    from models.internal_audit import AuditFinding
    overdue_findings = AuditFinding.get_overdue()
    for f in overdue_findings:
        link = _finding_url(f.id)
        project = AuditProject.get_by_id(f.project_id)
        recipients = {f.responsible_person_id}
        if project and project.lead_auditor_id:
            recipients.add(project.lead_auditor_id)
        for uid in recipients:
            if _notify_once_per_day(db, uid, f"Audit finding overdue: {f.finding_number}",
                                     f"{f.finding_number} ({f.finding_title}) is past its target date.",
                                     link, 'finding_overdue'):
                counts['finding_overdue'] += 1

    pending_verification = [f for f in AuditFinding.get_all(status='REMEDIATED_PENDING_VERIFICATION')]
    for f in pending_verification:
        link = _finding_url(f.id)
        for m in AuditTeamMember.get_for_project(f.project_id):
            if m.role_on_engagement in ('LEAD', 'REVIEWER'):
                if _notify_once_per_day(db, m.user_id, f"Finding awaiting verification: {f.finding_number}",
                                         f"{f.finding_number} ({f.finding_title}) has been remediated and needs independent verification.",
                                         link, 'finding_pending_verification'):
                    counts['finding_pending_verification'] += 1

    return counts


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        results = run_all_escalation_checks()
        for key, value in results.items():
            print(f"{key}: {value}")
