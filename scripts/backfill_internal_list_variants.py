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
One-time backfill for internal_pep and internal_blacklist: re-derives
full_name from original_name using the fixed transliterate_to_english()
(screening/arabic_transliteration_enhanced.py — was a 5-word hardcoded
list + crude vowel-less character map for everything else, e.g. 'حسن'
-> 'HSN' instead of 'HASSAN'), and populates aliases with every known
spelling variant (generate_all_spelling_variants). Confirmed affecting
~55% of internal_pep and ~51% of internal_blacklist records with an
Arabic name.

original_name is never touched — only full_name (replaced with a strictly
better spelling from the same curated dictionary) and aliases (only ever
added to, never removed).

Usage:
    python scripts/backfill_internal_list_variants.py --dry-run
    python scripts/backfill_internal_list_variants.py
"""
import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('backfill_internal_list_variants')


def backfill_table(conn, table, dry_run):
    from screening.arabic_transliteration_enhanced import prepare_name_for_screening, generate_all_spelling_variants
    import psycopg2.extras

    read_cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    read_cur.execute(f"""
        SELECT id, full_name, original_name, aliases FROM {table}
        WHERE original_name IS NOT NULL AND original_name != ''
    """)
    rows = read_cur.fetchall()
    read_cur.close()
    logger.info(f"{table}: {len(rows)} records with an Arabic name to process")

    changed = 0
    write_cur = conn.cursor()
    t0 = time.time()
    for i, row in enumerate(rows):
        new_full_name, _ = prepare_name_for_screening(row['original_name'])
        variants = generate_all_spelling_variants(row['original_name'])

        try:
            existing_aliases = json.loads(row['aliases']) if row['aliases'] else []
            if not isinstance(existing_aliases, list):
                existing_aliases = []
        except Exception:
            existing_aliases = []
        original_alias_count = len(existing_aliases)

        # Nothing gets discarded: if full_name is about to change, the old
        # value moves into aliases rather than being overwritten and lost —
        # it may be exactly how this person appears on some other list, or
        # how someone searches.
        name_changed = new_full_name and new_full_name != row['full_name']
        if name_changed and row['full_name']:
            existing_aliases = existing_aliases + [row['full_name']]

        existing_lower = {a.lower() for a in existing_aliases if isinstance(a, str)}
        merged_aliases = existing_aliases + [v for v in variants if v.lower() not in existing_lower]

        aliases_changed = len(merged_aliases) != original_alias_count
        if not (name_changed or aliases_changed):
            continue

        changed += 1
        if not dry_run:
            write_cur.execute(
                f"UPDATE {table} SET full_name = %s, aliases = %s WHERE id = %s",
                (new_full_name or row['full_name'], json.dumps(merged_aliases), row['id']),
            )
        if (i + 1) % 2000 == 0:
            logger.info(f"  ...{i+1}/{len(rows)} processed, {changed} changed so far")

    if not dry_run:
        conn.commit()
    write_cur.close()
    logger.info(f"{table}: {changed}/{len(rows)} records {'would be' if dry_run else ''} updated "
                f"in {time.time()-t0:.1f}s")
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    from config import Config
    import psycopg2
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)

    total = 0
    total += backfill_table(conn, 'internal_pep', args.dry_run)
    total += backfill_table(conn, 'internal_blacklist', args.dry_run)

    conn.close()
    logger.info(f"Done. {total} total records {'would be' if args.dry_run else ''} updated.")


if __name__ == '__main__':
    main()
