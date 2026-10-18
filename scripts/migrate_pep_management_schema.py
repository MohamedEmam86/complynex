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
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
One-time migration: applies database/schema_pep.sql to create the 7 tables
the screening/pep_management/ subsystem needs (pep_master, pep_aliases,
pep_positions, pep_corporate_links, pep_sources, pep_update_logs,
pep_duplicate_candidates). Idempotency check: exits cleanly if pep_master
already exists rather than re-running (schema_pep.sql has no IF NOT EXISTS).
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

SCHEMA_FILE = os.path.join(BASE_DIR, 'database', 'schema_pep.sql')


def run():
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.pep_master')")
            if cur.fetchone()[0] is not None:
                print("pep_master already exists — migration already applied, nothing to do.")
                return

            with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
                sql = f.read()

            print(f"Applying {SCHEMA_FILE} ...")
            cur.execute(sql)
        conn.commit()
        print("Migration committed successfully.")
    except Exception:
        conn.rollback()
        print("Migration failed, rolled back. No tables were created.")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
