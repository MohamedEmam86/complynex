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
One-off backfill of the unified case registry from every source module
(whistleblowing, consumer complaints, cyber incidents, data subject requests,
data breaches, TM alerts, opened control failures, unusual transactions).

Idempotent: it upserts on (source_table, source_record_id), so running it
again only refreshes status / owner / dates. Needs migration
20261110_cases_dp_case_sources.sql for the DSR / DATA_BREACH case types.

    python scripts/backfill_cases.py              # all sources
    python scripts/backfill_cases.py DSR DATA_BREACH
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv):
    from app import create_app
    from models.case import Case, resync_all
    wanted = [a.upper() for a in argv if a.upper() in Case.SOURCES] or None
    app = create_app()
    with app.app_context():
        for case_type, n in resync_all(wanted).items():
            print(f"{case_type}: {n}")


if __name__ == '__main__':
    main(sys.argv[1:])
