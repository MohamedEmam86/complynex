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
Retention/purge job: permanently deletes captured eKYC media (encrypted
files on disk) once their session's retention_expires_at has passed,
per the brief's "don't store raw biometrics longer than needed."

The ekyc_document row itself is KEPT (with purged_at set) — the decision,
audit trail, and screening result remain for regulatory record-keeping;
only the raw image bytes are deleted. This is intentional: Law 80/2002-
style retention obligations are about the compliance record, not the
biometric data itself.

Runs as a daily systemd timer (complynex-ekyc-purge.timer). Safe to run
manually: python scripts/ekyc_purge_expired.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def purge_expired():
    from app import create_app
    from database.db import get_db
    from ekyc.secure_storage import delete_frame
    from models.ekyc import EkycAuditLog

    app = create_app()
    with app.app_context():
        db = get_db()
        rows = db.execute('''
            SELECT d.id, d.session_id, d.stored_path, d.doc_role
            FROM ekyc_document d
            JOIN ekyc_session s ON s.id = d.session_id
            WHERE d.purged_at IS NULL AND s.retention_expires_at < CURRENT_TIMESTAMP
        ''').fetchall()

        purged_count = 0
        for row in rows:
            try:
                delete_frame(row['stored_path'])
            except OSError as exc:
                print(f"WARNING: could not delete {row['stored_path']}: {exc}")
            db.execute('UPDATE ekyc_document SET purged_at = CURRENT_TIMESTAMP WHERE id = %s', (row['id'],))
            db.commit()
            EkycAuditLog.log(row['session_id'], 'MEDIA_PURGED',
                              details=f"doc_id={row['id']} doc_role={row['doc_role']}")
            purged_count += 1

        print(f"Purged {purged_count} expired document(s).")

    # ekyc/debug_capture.py's per-attempt diagnostic images (logs/ekyc_debug/)
    # are a separate, unencrypted, short-lived debugging aid — not the
    # compliance-record store above — so they get a much shorter retention
    # (DEBUG_RETENTION_DAYS) and don't need an app context or DB row.
    from ekyc.debug_capture import purge_expired_debug_captures
    debug_purged = purge_expired_debug_captures()
    print(f"Purged {debug_purged} expired eKYC debug capture folder(s).")


if __name__ == '__main__':
    purge_expired()
