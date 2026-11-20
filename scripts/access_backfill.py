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
Write every user's CURRENT effective access as explicit per-feature grants (after
database/migrations/20261122_access_control.sql). Idempotent: users that already have grants are skipped;
the superadmin stays unrestricted (no rows). Nothing changes in what anybody can do — the grants are
computed with the same old rules the application applies to users without grants.

    PYTHONPATH=. python scripts/access_backfill.py            # write
    PYTHONPATH=. python scripts/access_backfill.py --dry-run  # only list what would be written
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    logging.disable(logging.WARNING)
    from app import create_app
    app = create_app()
    with app.app_context():
        from access import service
        done = service.backfill(dry_run=args.dry_run)
    for uid, mode, n in done:
        print(f'user {uid}: mode={mode} features={n}' + (' (dry run)' if args.dry_run else ''))
    print(f'{len(done)} user(s) {"would be " if args.dry_run else ""}backfilled')


if __name__ == '__main__':
    main()
