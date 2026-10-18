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
Additive backfill: generates Arabic transliterations for individual
records in the high-priority Latin-script sanctions datasets (OFAC, UN,
EU, HMT) that have no full_name_arabic/aliases_arabic at all.

Why scoped this way (not the full 2.49M-row table):
- Only ~54K of 2.49M rows have full_name_arabic populated at all, almost
  entirely the Iraq AML list (which ships bilingually from its source).
  OFAC/UN/EU/HMT are published by Western governments in Latin script
  only — there is no hidden Arabic field being dropped on import, it
  genuinely has to be generated.
- Scoped to entity_type PERSON/person/INDIVIDUAL only: transliterating an
  organization name letter-by-letter produces meaningless text (that's a
  translation problem, not transliteration) and risks polluting search
  with noise.
- Scoped to ASCII/Latin-script full_name only: a large share of
  "EU_Sanctions" PERSON records are actually Cyrillic (Russian sanctions
  targets, e.g. "Ольга Николаевна АНУФРИЕВА") — generating Arabic
  variants for those serves no real screening purpose.

Uses the same generate_arabic_variants() (dictionary lookup + per-token
character fallback) already used at query time for live English-input
screening — this backfill just does in bulk, once, what already happens
per-request today, so it carries no new behavioral risk.

Never touches any other column. Only writes where full_name_arabic is
currently NULL/empty, so it's safe to re-run if interrupted.

Run with: python scripts/backfill_arabic_transliteration.py [--apply]
  (no --apply: dry run, prints what would be written and exits)
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

import psycopg2
from config import Config
from screening.arabic_utils import generate_arabic_variants

DATASET_FILTER = "(dataset ILIKE '%ofac%' OR dataset ILIKE '%un_sc%' OR dataset ILIKE '%eu_sanctions%' OR dataset ILIKE '%hmt%')"
BATCH_SIZE = 500


def backfill(apply: bool):
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, full_name FROM screening_watchlist
        WHERE {DATASET_FILTER}
          AND (full_name_arabic IS NULL OR full_name_arabic = '')
          AND entity_type IN ('PERSON', 'person', 'INDIVIDUAL')
    """)
    rows = cur.fetchall()
    latin_rows = [(rid, name) for rid, name in rows if name and name.isascii()]
    print(f"Candidates: {len(rows)} total, {len(latin_rows)} Latin-script (skipping {len(rows) - len(latin_rows)} non-Latin)")

    updated = 0
    skipped_no_variant = 0
    update_cur = conn.cursor()
    for i in range(0, len(latin_rows), BATCH_SIZE):
        batch = latin_rows[i:i + BATCH_SIZE]
        for rid, name in batch:
            variants = generate_arabic_variants(name)
            if not variants:
                skipped_no_variant += 1
                continue
            primary = variants[0]
            aliases_ar = '|'.join(variants[1:6])  # cap extras, same convention as existing aliases_arabic rows
            if apply:
                update_cur.execute(
                    "UPDATE screening_watchlist SET full_name_arabic = %s, aliases_arabic = %s WHERE id = %s",
                    (primary, aliases_ar, rid)
                )
            updated += 1
        if apply:
            conn.commit()
        print(f"  processed {min(i + BATCH_SIZE, len(latin_rows))}/{len(latin_rows)}")

    print(f"\n{'APPLIED' if apply else 'DRY RUN'}: {updated} rows would get full_name_arabic, {skipped_no_variant} produced no variant")
    cur.close()
    update_cur.close()
    conn.close()
    return updated


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Actually write to the DB (default: dry run)')
    args = parser.parse_args()
    backfill(apply=args.apply)
