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
Sync internal_blacklist and internal_pep to screening_watchlist
Run hourly via cron. Deactivation handled by admin UI, not this script.
"""
import os
import psycopg2
import hashlib
import re
import sys
import logging
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass
from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Single source of truth — this used to be a fully hardcoded literal dict
# (port=6432) that ignored the environment entirely, so it could never
# connect regardless of .env.
DB_CONFIG = dict(Config.POSTGRES_CONFIG)

def normalize_name(name):
    if not name:
        return ''
    n = name.upper().strip()
    n = re.sub(r'[^A-Z0-9\u0600-\u06FF\s]', ' ', n)
    return ' '.join(n.split())

def gen_source_id(prefix, name):
    h = hashlib.md5(name.strip().lower().encode()).hexdigest()
    return f"{prefix}-{h[:12].upper()}"

def sync_table(cur, source_table, source_prefix, watchlist_source, now):
    cur.execute(f"""
        SELECT id, full_name, original_name, risk_level, category,
               entity_type, is_active, added_date, modified_date,
               date_of_birth, nationality, aliases, source_id
        FROM {source_table}
        WHERE COALESCE(is_active, 1) != 0
    """)
    rows = cur.fetchall()
    count = 0
    for row in rows:
        (rid, full_name, orig_name, risk_level, category, entity_type,
         is_active, added_date, modified_date, dob, nationality,
         aliases, existing_sid) = row

        if not full_name:
            continue

        # Use existing valid source_id if present, else generate
        if existing_sid and existing_sid.startswith(f'{source_prefix}-'):
            sid = existing_sid
        else:
            sid = gen_source_id(source_prefix, full_name)

        name_norm = normalize_name(full_name)

        cur.execute(f"""
            INSERT INTO screening_watchlist (
                full_name, original_name, source, source_id, risk_level,
                list_type, entity_type, is_active, created_at, updated_at,
                last_updated, date_of_birth, nationality, aliases, name_normalized
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source, source_id) DO UPDATE SET
                full_name       = EXCLUDED.full_name,
                original_name   = EXCLUDED.original_name,
                risk_level      = EXCLUDED.risk_level,
                name_normalized = EXCLUDED.name_normalized,
                is_active       = 1,
                updated_at      = NOW()
        """, (full_name, orig_name or full_name, watchlist_source, sid,
              risk_level or 'HIGH', category or source_prefix,
              entity_type or 'PERSON',
              str(added_date or now), str(modified_date or now),
              str(modified_date or now), dob, nationality, aliases, name_norm))
        count += 1

    # Mark inactive: watchlist rows whose source entry is now is_active=0
    cur.execute(f"""
        UPDATE screening_watchlist w SET is_active = 0
        WHERE w.source = %s
        AND EXISTS (
            SELECT 1 FROM {source_table} b
            WHERE b.source_id = w.source_id
            AND COALESCE(b.is_active, 1) = 0
        )
    """, (watchlist_source,))

    return count

def sync_internal_lists():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        logger.info('Syncing internal_blacklist...')
        bl_count = sync_table(cur, 'internal_blacklist', 'IBL',
                               'internal_blacklist', now)

        logger.info('Syncing internal_pep...')
        pep_count = sync_table(cur, 'internal_pep', 'IPEP',
                                'internal_pep', now)

        conn.commit()
        cur.close()
        conn.close()
        logger.info(f'Sync complete — Blacklist: {bl_count}, PEP: {pep_count}')
        return True

    except Exception as e:
        logger.error(f'Sync failed: {e}')
        import traceback; traceback.print_exc()
        return False

if __name__ == '__main__':
    success = sync_internal_lists()
    sys.exit(0 if success else 1)
