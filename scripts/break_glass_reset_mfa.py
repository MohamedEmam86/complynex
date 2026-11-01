#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Break-glass: give a user back access when nobody can sign in to do it in the app
(lost phone AND no backup codes, last administrator locked out ...).

Run on the server, as the app user, with the .env loaded:
    sudo -u complynex bash -c 'set -a; . /var/www/complynex/.env; set +a; cd /var/www/complynex && \
      venv/bin/python scripts/break_glass_reset_mfa.py --email user@example.com --reason "lost phone, ticket 123"'
(dry run: shows what would change) then the same with --apply.

What --apply does, in one transaction:
  * clears the user's second factor (secret, backup codes) -> they enrol again at next login;
  * unlocks the account (failed attempts, lock, back-off);
  * signs the user out everywhere (auth_version + 1);
  * restarts the MFA grace period (mfa_prompted_at) so they are asked to enrol at once;
  * records the action in mfa_audit and in the hash-chained audit_logs.
It never changes the password. Use the normal password reset for that.
"""
import argparse
import os
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--email', required=True)
    ap.add_argument('--reason', required=True, help='why (at least 15 characters; stored in the audit trail)')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    if len(a.reason.strip()) < 15:
        print('give a reason of at least 15 characters')
        return 2
    import psycopg2
    import psycopg2.extras
    from config import Config
    conn = psycopg2.connect(**dict(Config.POSTGRES_CONFIG))
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT id, email, role, is_active, mfa_enabled, locked_until, failed_login_count "
              "FROM users WHERE lower(email) = lower(%s)", (a.email.strip(),))
    u = c.fetchone()
    if not u:
        print('no such user')
        return 2
    print(f"user {u['id']} {u['email']} role={u['role']} active={u['is_active']} mfa={u['mfa_enabled']} "
          f"locked_until={u['locked_until']} failures={u['failed_login_count']}")
    if not a.apply:
        print('dry run: nothing changed (add --apply)')
        return 0
    reason = f'BREAK-GLASS (server script, OS user {os.environ.get("SUDO_USER") or os.environ.get("USER") or "?"}): ' \
             f'{a.reason.strip()}'
    c.execute("""UPDATE users SET mfa_enabled = FALSE, mfa_secret = NULL, mfa_backup_codes = NULL,
                                  mfa_enrolled_at = NULL, mfa_last_reset_at = NOW(), mfa_last_reset_by = NULL,
                                  failed_login_count = 0, locked_until = NULL,
                                  auth_version = COALESCE(auth_version, 0) + 1
                  WHERE id = %s""", (u['id'],))
    for sql in ("UPDATE users SET lock_count = 0, mfa_prompted_at = NULL WHERE id = %s",):
        c.execute("SAVEPOINT sp")
        try:
            c.execute(sql, (u['id'],))
        except Exception:
            c.execute("ROLLBACK TO SAVEPOINT sp")
    c.execute("INSERT INTO mfa_audit (user_id, action, performed_by, reason, ip_address) "
              "VALUES (%s, 'break_glass_reset', NULL, %s, 'server')", (u['id'], reason[:1000]))
    c.execute("INSERT INTO audit_logs (user_id, action, module, item_id, details, ip_address, created_at) "
              "VALUES (NULL, 'Break-glass MFA Reset', 'Security', %s, %s, 'server', %s)",
              (u['id'], f"{reason} - target {u['email']}", datetime.now()))
    conn.commit()
    print('done: MFA cleared, account unlocked, all sessions ended; the user enrols again at next login')
    return 0


if __name__ == '__main__':
    sys.exit(main())
