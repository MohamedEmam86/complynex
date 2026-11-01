# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Per-account brute-force protection (complements the per-IP rate limit).

After LOCK_AFTER consecutive failures (wrong password OR wrong MFA code) the
account is locked. The lock grows with every further lock (back-off):
LOCK_MINUTES, then x2, x4 ... up to LOCK_MAX_MINUTES. A successful login, or an
administrator's unlock, resets the counter and the back-off.

Settings (environment): LOGIN_LOCK_AFTER (5), LOGIN_LOCK_MINUTES (15),
LOGIN_LOCK_MAX_MINUTES (1440).
"""
import os

from database.db import get_db


def _int_env(name, default, lo, hi):
    try:
        v = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


LOCK_AFTER = _int_env('LOGIN_LOCK_AFTER', 5, 3, 20)
LOCK_MINUTES = _int_env('LOGIN_LOCK_MINUTES', 15, 1, 240)
LOCK_MAX_MINUTES = _int_env('LOGIN_LOCK_MAX_MINUTES', 1440, LOCK_MINUTES, 10080)


def lock_minutes(previous_locks):
    """Length of the next lock: LOCK_MINUTES doubled for each earlier lock, capped."""
    n = max(0, int(previous_locks or 0))
    return min(LOCK_MAX_MINUTES, LOCK_MINUTES * (2 ** min(n, 16)))


def is_locked(user_id):
    row = get_db().execute(
        "SELECT locked_until > NOW() AS locked FROM users WHERE id = %s", (user_id,)).fetchone()
    return bool(row and row['locked'])


def minutes_left(user_id):
    row = get_db().execute(
        "SELECT CEIL(EXTRACT(EPOCH FROM (locked_until - NOW())) / 60) AS m FROM users "
        "WHERE id = %s AND locked_until > NOW()", (user_id,)).fetchone()
    return int(row['m']) if row and row['m'] is not None else 0


def register_failure(user_id):
    """Count one failure; returns True when this failure locked the account."""
    db = get_db()
    row = db.execute(
        "UPDATE users SET failed_login_count = COALESCE(failed_login_count, 0) + 1 "
        "WHERE id = %s RETURNING failed_login_count", (user_id,)).fetchone()
    locked = False
    if row and row['failed_login_count'] >= LOCK_AFTER:
        try:
            prev = db.execute("SELECT COALESCE(lock_count, 0) AS n FROM users WHERE id = %s",
                              (user_id,)).fetchone()['n']
            db.execute("UPDATE users SET locked_until = NOW() + (%s * INTERVAL '1 minute'), "
                       "failed_login_count = 0, lock_count = COALESCE(lock_count, 0) + 1 WHERE id = %s",
                       (lock_minutes(prev), user_id))
        except Exception:
            # lock_count column not there yet (code deployed before the migration): plain lock
            db.rollback()
            db.execute("UPDATE users SET locked_until = NOW() + (%s * INTERVAL '1 minute'), "
                       "failed_login_count = 0 WHERE id = %s", (LOCK_MINUTES, user_id))
        locked = True
    db.commit()
    return locked


def reset_failures(user_id):
    """Successful login: clear the counter, the lock and the back-off."""
    db = get_db()
    try:
        db.execute("UPDATE users SET failed_login_count = 0, locked_until = NULL, lock_count = 0 "
                   "WHERE id = %s", (user_id,))
    except Exception:
        db.rollback()
        db.execute("UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE id = %s", (user_id,))
    db.commit()


def unlock(user_id):
    reset_failures(user_id)
