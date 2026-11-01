# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""MFA rules that are not the TOTP check itself (P6-6).

Enrolment grace period
    A user who must use MFA but has not enrolled yet is asked to enrol at every
    login. During the grace period (counted from the first time they were asked)
    they may choose "remind me later"; after it, enrolment is the only way in.
    Privileged roles (admin / compliance) have their own setting, default 0 days:
    they enrol at once, exactly as before. Nobody is ever locked out by this
    rule: the enrolment screen is always reachable with the right password.
    Settings: MFA_ENROLL_GRACE_DAYS (7), MFA_ENROLL_GRACE_DAYS_PRIVILEGED (0).

Backup codes
    Stored as salted PBKDF2 hashes (never in clear). Codes written by older
    versions (clear text) still work once and are re-stored hashed.
"""
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

PRIVILEGED_ROLES = ('admin', 'compliance_officer', 'compliance_manager')
_HASH_METHOD = 'pbkdf2:sha256:60000'      # 8 codes x ~30 ms per check
_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'   # no 0/O, 1/I


def _int_env(name, default):
    try:
        return max(0, min(90, int(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


def grace_days(role, override=None):
    if override is True:      # MFA required for this user by an administrator: no grace
        return 0
    if role in PRIVILEGED_ROLES:
        return _int_env('MFA_ENROLL_GRACE_DAYS_PRIVILEGED', 0)
    return _int_env('MFA_ENROLL_GRACE_DAYS', 7)


def grace_deadline(prompted_at, role, override=None):
    """When the grace period ends (None = no grace at all). No recorded prompt time (column
    missing / not written) means no grace: enrol now, as before P6-6."""
    days = grace_days(role, override)
    if days <= 0 or prompted_at is None:
        return None
    if prompted_at.tzinfo is None:
        prompted_at = prompted_at.replace(tzinfo=timezone.utc)
    return prompted_at + timedelta(days=days)


def can_defer(prompted_at, role, now=None, override=None):
    deadline = grace_deadline(prompted_at, role, override)
    if deadline is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now < deadline


def days_left(prompted_at, role, now=None, override=None):
    deadline = grace_deadline(prompted_at, role, override)
    if deadline is None:
        return 0
    now = now or datetime.now(timezone.utc)
    return max(0, (deadline - now).days + (1 if (deadline - now).seconds else 0))


def mark_prompted(user_id):
    """Start the grace period the first time the user is asked to enrol. Returns prompted_at."""
    from database.db import get_db
    db = get_db()
    try:
        row = db.execute("UPDATE users SET mfa_prompted_at = COALESCE(mfa_prompted_at, NOW()) "
                         "WHERE id = %s RETURNING mfa_prompted_at", (user_id,)).fetchone()
        db.commit()
        return row['mfa_prompted_at'] if row else None
    except Exception:
        db.rollback()      # column not there yet: no grace (enrol now), as before
        return None


# ── backup codes ────────────────────────────────────────────────────────────────

def _norm(code):
    return str(code or '').strip().upper().replace('-', '').replace(' ', '')


def new_backup_codes(n=8):
    """(codes to show once, JSON of their hashes to store). 10 characters = 50 bits each."""
    codes = [''.join(secrets.choice(_ALPHABET) for _ in range(10)) for _ in range(n)]
    shown = [f'{c[:5]}-{c[5:]}' for c in codes]
    return shown, json.dumps([generate_password_hash(c, method=_HASH_METHOD) for c in codes])


def is_hashed(entry):
    return isinstance(entry, str) and entry.startswith(('pbkdf2:', 'scrypt:'))


def consume_backup_code(stored_json, code):
    """Check a code against the stored list. Returns (ok, new_json_to_store or None).
    A used code is removed; clear-text codes from older versions are hashed on the way."""
    try:
        entries = json.loads(stored_json) if stored_json else []
    except Exception:
        return False, None
    c = _norm(code)
    if not c or not isinstance(entries, list):
        return False, None
    hit = None
    for i, e in enumerate(entries):
        if is_hashed(e):
            if check_password_hash(e, c):
                hit = i
                break
        elif isinstance(e, str) and secrets.compare_digest(_norm(e), c):
            hit = i
            break
    if hit is None:
        return False, None
    rest = [e for i, e in enumerate(entries) if i != hit]
    rest = [e if is_hashed(e) else generate_password_hash(_norm(e), method=_HASH_METHOD) for e in rest]
    return True, json.dumps(rest)


def hash_legacy(stored_json):
    """Re-store clear-text codes as hashes (one-off script). Returns new JSON or None if nothing to do."""
    try:
        entries = json.loads(stored_json) if stored_json else []
    except Exception:
        return None
    if not isinstance(entries, list) or all(is_hashed(e) for e in entries):
        return None
    return json.dumps([e if is_hashed(e) else generate_password_hash(_norm(e), method=_HASH_METHOD)
                       for e in entries])


def remaining(stored_json):
    try:
        return len(json.loads(stored_json or '[]'))
    except Exception:
        return 0
