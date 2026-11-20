#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Download, parse, version and load the dual-use control lists (command line).

    python scripts/dualuse/import_lists.py                       # dry run: download, parse, show the diff
    python scripts/dualuse/import_lists.py --apply               # load every list that changed
    python scripts/dualuse/import_lists.py --list us_ccl --apply # one list
    python scripts/dualuse/import_lists.py --from-dir DIR        # use files already downloaded (same names)
    python scripts/dualuse/import_lists.py --apply --scheduled   # the timer: also records the run

The work is done by packs/trade_control/loader.py (shared with the superadmin "check now" button and the
upload page). Idempotent: a list whose parsed content equals the current version is skipped (--force reloads
it). Each load is a new version; the previous one stays for replaying past screenings. Arabic texts are carried
over (marked 'stale' when the English text changed). Run with the application's .env loaded.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from packs.trade_control import loader as L  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', default='all', help='all or one of: ' + ', '.join(L.ORDER))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--force', action='store_true', help='reload even when the content is unchanged')
    ap.add_argument('--from-dir', default=None, help='read files from this folder instead of downloading')
    ap.add_argument('--raw-dir', default=None, help='keep a copy of every downloaded file here')
    ap.add_argument('--dbname', default=None, help='override the database name (scratch / test databases)')
    ap.add_argument('--who', default='import_lists')
    ap.add_argument('--scheduled', action='store_true', help='record the run as a scheduled check')
    ap.add_argument('--run-id', type=int, default=None, help='(internal) the run row started by the web button')
    a = ap.parse_args()
    todo = None if a.list == 'all' else [a.list]
    if todo and todo[0] not in L.ORDER:
        sys.exit('unknown list %s' % a.list)
    try:
        res = L.run(todo, apply=a.apply, force=a.force, from_dir=a.from_dir, raw_dir=a.raw_dir, who=a.who,
                    dbname=a.dbname, run_id=a.run_id, mode='scheduled' if a.scheduled else (
                        'command' if a.apply else None))
    except RuntimeError as e:
        sys.exit(str(e))
    for r in res:
        d = r.get('diff') or {}
        print('%-20s %-9s %s' % (r['code'], r['status'], r.get('message') or (
            'added %s, removed %s, changed %s, thresholds changed %s' % (
                d.get('added', 0), d.get('removed', 0), d.get('changed', 0), d.get('thresholds_changed', 0))
            if d else '')))
    if not a.apply:
        print('DRY RUN - nothing written (use --apply)')
    elif any(r['status'] == 'loaded' for r in res):
        print('done - the search index reloads on its own within a minute')
    sys.exit(1 if L.run_status(res) != 'ok' else 0)


if __name__ == '__main__':
    main()
