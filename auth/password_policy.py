# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Password rules beyond strength (P6-6): no re-use of the last PASSWORD_HISTORY
(default 5) passwords and no password built on the user's own e-mail name.
Strength itself stays in User.validate_password_strength."""
import os
import re

HISTORY = max(0, min(24, int(os.environ.get('PASSWORD_HISTORY', 5) or 5)))


def contains_identity(password, email):
    local = re.sub(r'[^a-z0-9]', '', (email or '').split('@')[0].lower())
    pw = re.sub(r'[^a-z0-9]', '', (password or '').lower())
    return len(local) >= 4 and local in pw


def reused(user_id, password, current_hash=None):
    """True when password equals the current one or one of the last HISTORY ones."""
    from models.user import User
    hashes = [current_hash] if current_hash else []
    try:
        from database.db import get_db
        rows = get_db().execute("SELECT password_hash FROM password_history WHERE user_id = %s "
                                "ORDER BY created_at DESC LIMIT %s", (user_id, HISTORY)).fetchall()
        hashes += [r['password_hash'] for r in rows]
    except Exception:
        try:
            from database.db import get_db
            get_db().rollback()
        except Exception:
            pass
    probe = User.__new__(User)
    for h in hashes:
        if not h:
            continue
        probe.password_hash = h
        try:
            if probe.verify_password(password):
                return True
        except Exception:
            continue
    return False


def remember(user_id, old_hash):
    """Keep the password being replaced; prune to HISTORY entries. Never raises."""
    if not old_hash or HISTORY <= 0:
        return
    from database.db import get_db
    db = get_db()
    try:
        db.execute("INSERT INTO password_history (user_id, password_hash) VALUES (%s, %s)", (user_id, old_hash))
        db.execute("""DELETE FROM password_history WHERE user_id = %s AND id NOT IN (
                        SELECT id FROM password_history WHERE user_id = %s ORDER BY created_at DESC LIMIT %s)""",
                   (user_id, user_id, HISTORY))
        db.commit()
    except Exception:
        db.rollback()
