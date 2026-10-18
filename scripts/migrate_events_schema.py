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
One-time migration: applies database/schema_events.sql to create the
compliance event bus tables (compliance_events, event_routing_rules) plus
three default routing rules. Idempotency check: exits cleanly if
compliance_events already exists rather than re-running.
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

SCHEMA_FILE = os.path.join(BASE_DIR, 'database', 'schema_events.sql')


def run():
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.compliance_events')")
            if cur.fetchone()[0] is not None:
                print("compliance_events already exists — migration already applied, nothing to do.")
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
