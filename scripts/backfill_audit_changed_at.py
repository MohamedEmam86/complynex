#!/usr/bin/env python3
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
One-off backfill: populate changed_at for legacy internal_blacklist_audit/
internal_pep_audit rows. _log_audit() never included changed_at in its
INSERT column list, so every row had a NULL timestamp, which 500s
templates/blacklist/view.html's audit.changed_at[:16].

For each NULL row, approximates the real timestamp from the linked entry:
added_date for an ADDED row, modified_date otherwise, falling back to
whichever of those is set, then NOW() as a last resort. Only fills NULLs.
"""
import os
import sys
import psycopg2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass
from config import Config


def backfill(audit_table, parent_table, fk_column):
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()
    cur.execute(f"""
        UPDATE {audit_table} a
        SET changed_at = COALESCE(
            CASE WHEN a.action = 'ADDED' THEN p.added_date ELSE NULL END,
            p.modified_date,
            p.added_date,
            NOW()::text
        )
        FROM {parent_table} p
        WHERE a.{fk_column} = p.id AND a.changed_at IS NULL
    """)
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    print(f"{audit_table}: backfilled {updated} rows")


if __name__ == '__main__':
    backfill('internal_blacklist_audit', 'internal_blacklist', 'blacklist_id')
    backfill('internal_pep_audit', 'internal_pep', 'blacklist_id')
