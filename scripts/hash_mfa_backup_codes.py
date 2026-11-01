#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""One-off (P6-6): re-store MFA backup codes written in clear text by older versions
as salted hashes. The codes themselves do not change; users keep their sheets.
Dry run by default; --apply writes."""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    import psycopg2
    from config import Config
    from auth.mfa_policy import hash_legacy
    conn = psycopg2.connect(**dict(Config.POSTGRES_CONFIG))
    c = conn.cursor()
    c.execute("SELECT id, mfa_backup_codes FROM users WHERE mfa_backup_codes IS NOT NULL AND mfa_backup_codes <> ''")
    todo = [(uid, hash_legacy(v)) for uid, v in c.fetchall()]
    todo = [(uid, v) for uid, v in todo if v]
    print(f'users with clear-text backup codes: {len(todo)}')
    if a.apply and todo:
        for uid, v in todo:
            c.execute("UPDATE users SET mfa_backup_codes = %s WHERE id = %s", (v, uid))
        conn.commit()
        print('hashed')
    elif not a.apply:
        print('dry run (add --apply)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
