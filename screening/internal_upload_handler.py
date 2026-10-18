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
Handle internal blacklist and PEP file uploads
"""
import csv
import hashlib
import logging
import os
import sys
import psycopg2
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from config import Config


def _generate_source_id(prefix, full_name):
    """
    Deterministic source_id from the (normalized) name, so re-uploading the
    same CSV — even from a different file — maps to the same row instead of
    inserting a fresh duplicate. Matches the IBL-/PEP- convention used by
    scripts/sync_internal_to_watchlist.py.
    """
    h = hashlib.md5(full_name.strip().lower().encode('utf-8')).hexdigest()
    return f"{prefix}-{h[:12].upper()}"


def handle_internal_upload(file_path, source):
    """
    Import CSV file to internal_blacklist or internal_pep table

    Expected CSV columns:
    - full_name (English)
    - original_name (Arabic)
    - risk_level
    - category/list_type
    - entity_type
    - date_of_birth (optional)
    - nationality (optional)
    - aliases (optional)
    """
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()

    table_name = 'internal_blacklist' if source == 'internal_blacklist' else 'internal_pep'
    source_prefix = 'IBL' if source == 'internal_blacklist' else 'PEP'

    added = 0
    updated = 0

    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                full_name = row.get('full_name', '').strip()
                if not full_name:
                    continue
                source_id = _generate_source_id(source_prefix, full_name)

                # Both tables have a UNIQUE constraint on source_id — without
                # it set (it used to never be populated here), ON CONFLICT
                # had nothing to match and every re-upload inserted fresh
                # duplicate rows instead of updating the existing entry.
                cur.execute(f"""
                    INSERT INTO {table_name} (
                        full_name, original_name, risk_level, category,
                        entity_type, date_of_birth, nationality, aliases,
                        source, source_id,
                        is_active, added_date, modified_date, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_id) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        original_name = EXCLUDED.original_name,
                        risk_level = EXCLUDED.risk_level,
                        category = EXCLUDED.category,
                        entity_type = EXCLUDED.entity_type,
                        date_of_birth = EXCLUDED.date_of_birth,
                        nationality = EXCLUDED.nationality,
                        aliases = EXCLUDED.aliases,
                        is_active = 1,
                        modified_date = EXCLUDED.modified_date,
                        updated_at = EXCLUDED.updated_at
                    RETURNING (xmax = 0) AS inserted
                """, (
                    full_name,
                    row.get('original_name', ''),
                    row.get('risk_level', 'HIGH'),
                    row.get('category', 'Manual Upload'),
                    row.get('entity_type', 'INDIVIDUAL'),
                    row.get('date_of_birth'),
                    row.get('nationality'),
                    row.get('aliases'),
                    'INTERNAL_BULK_UPLOAD',
                    source_id,
                    1,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                ))

                if cur.fetchone()[0]:
                    added += 1
                else:
                    updated += 1

            except Exception as e:
                logger.error(f"Error importing row {row.get('full_name', '?')!r}: {e}")
                continue

    conn.commit()
    cur.close()
    conn.close()

    return {
        'source': source,
        'added': added,
        'updated': updated,
        'total_processed': added + updated
    }

if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3:
        result = handle_internal_upload(sys.argv[1], sys.argv[2])
        print(f"Import complete: {result}")
