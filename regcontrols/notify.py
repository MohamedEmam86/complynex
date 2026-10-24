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
Reviewer notifications for regcontrols: when evidence is submitted for review
and when verification of a finding is requested. In-app always; email only
when mail is configured, sent in the background so the request never waits
on SMTP (utils.email.send_mail_async; nothing is sent on the demo instance).
"""

import logging

from database.db import get_db

logger = logging.getLogger(__name__)
MODULE = 'regcontrols'


def reviewers(exclude=(), db=None):
    """Active users who can review in this module (module edit / admin
    permission, or site administrators), minus the people excluded (the
    submitter, or whoever must not verify their own work)."""
    db = db or get_db()
    excluded = {int(u) for u in exclude if u}
    rows = db.execute("""SELECT id FROM users WHERE is_active = 1
                         AND (role = 'admin' OR COALESCE(perm_regcontrols, 'none') IN ('use', 'edit', 'admin'))
                         ORDER BY id""").fetchall()
    return [r['id'] for r in rows if r['id'] not in excluded]


def _email(user_ids, subject, body, db):
    try:
        from services.notification_service import email_enabled
        if not email_enabled():
            return 0
        from flask import current_app
        from flask_mail import Message
        from utils.email import send_mail_async
        sent = 0
        for r in db.execute("SELECT email FROM users WHERE id = ANY(%s) AND email IS NOT NULL", (list(user_ids),)).fetchall():
            msg = Message(subject=subject, recipients=[r['email']], body=body,
                          sender=current_app.config.get('MAIL_USERNAME', 'noreply@complynex.online'))
            if send_mail_async(msg, r['email']):
                sent += 1
        return sent
    except Exception:
        logger.exception('regcontrols: reviewer email failed')
        return 0


def notify_reviewers(title, message, link, exclude=(), db=None):
    """Returns {'inapp': n, 'email': n}. Never raises."""
    db = db or get_db()
    try:
        ids = reviewers(exclude, db)
        if not ids:
            return {'inapp': 0, 'email': 0}
        from services.notification_service import notify
        res = notify(ids, title, message, link=link, category=MODULE, channels=('inapp',))
        sent = _email(ids, title, f'{message}\n\n{link}', db)
        return {'inapp': res.get('inapp', 0), 'email': sent}
    except Exception:
        logger.exception('regcontrols: reviewer notification failed')
        try:
            db.rollback()
        except Exception:
            pass
        return {'inapp': 0, 'email': 0}


def evidence_submitted(evidence_id, db=None):
    db = db or get_db()
    row = db.execute("""SELECT e.id, e.title, e.submitted_by, c.control_code
                        FROM rc_evidence e JOIN rc_controls c ON c.id = e.control_id WHERE e.id = %s""",
                     (evidence_id,)).fetchone()
    if not row:
        return None
    from flask_babel import gettext as _
    return notify_reviewers(
        _('Evidence awaiting review: %(code)s', code=row['control_code']),
        _('"%(title)s" was submitted as evidence for control %(code)s and needs review by someone other than the submitter.',
          title=row['title'], code=row['control_code']),
        f'/regcontrols/evidence/{evidence_id}', exclude=[row['submitted_by']], db=db)


def verification_requested(finding_id, requested_by, db=None):
    db = db or get_db()
    row = db.execute("SELECT id, reference, title, owner_user_id FROM rc_findings WHERE id = %s",
                     (finding_id,)).fetchone()
    if not row:
        return None
    done_by = [r['completed_by'] for r in db.execute(
        "SELECT completed_by FROM rc_corrective_actions WHERE finding_id = %s", (finding_id,)).fetchall()
        if r.get('completed_by')]
    from flask_babel import gettext as _
    ref = row.get('reference') or f'#{finding_id}'
    return notify_reviewers(
        _('Verification requested: finding %(ref)s', ref=ref),
        _('The corrective actions for finding %(ref)s (%(title)s) are complete. Please verify the remediation.',
          ref=ref, title=row.get('title') or ''),
        f'/regcontrols/findings/{finding_id}', exclude=[requested_by] + done_by, db=db)
