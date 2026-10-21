# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Per-account brute-force protection (complements the per-IP rate limit).

After LOCK_AFTER consecutive failures (wrong password OR wrong MFA code) the
account is locked for LOCK_MINUTES. A successful login resets the counter.
"""
from database.db import get_db

LOCK_AFTER = 5
LOCK_MINUTES = 15


def is_locked(user_id):
    row = get_db().execute(
        "SELECT locked_until > NOW() AS locked FROM users WHERE id = %s", (user_id,)).fetchone()
    return bool(row and row['locked'])


def register_failure(user_id):
    """Count one failure; returns True when this failure locked the account."""
    db = get_db()
    row = db.execute(
        "UPDATE users SET failed_login_count = COALESCE(failed_login_count, 0) + 1 "
        "WHERE id = %s RETURNING failed_login_count", (user_id,)).fetchone()
    locked = False
    if row and row['failed_login_count'] >= LOCK_AFTER:
        db.execute("UPDATE users SET locked_until = NOW() + (%s * INTERVAL '1 minute'), "
                   "failed_login_count = 0 WHERE id = %s", (LOCK_MINUTES, user_id))
        locked = True
    db.commit()
    return locked


def reset_failures(user_id):
    db = get_db()
    db.execute("UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE id = %s", (user_id,))
    db.commit()


def unlock(user_id):
    reset_failures(user_id)
