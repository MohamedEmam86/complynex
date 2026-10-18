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
One-off backfill: populate added_date/created_at/updated_at for legacy
internal_blacklist/internal_pep rows that predate timestamp tracking.
Only fills NULLs — never overwrites an existing value.
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


def backfill(table):
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()
    cur.execute(f"""
        UPDATE {table}
        SET created_at = COALESCE(created_at, added_date, modified_date, NOW()::text),
            added_date = COALESCE(added_date, created_at, modified_date, NOW()::text),
            updated_at = COALESCE(updated_at, created_at, added_date, NOW()::text)
        WHERE created_at IS NULL OR added_date IS NULL OR updated_at IS NULL
    """)
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    print(f"{table}: backfilled {updated} rows")


if __name__ == '__main__':
    backfill('internal_blacklist')
    backfill('internal_pep')
