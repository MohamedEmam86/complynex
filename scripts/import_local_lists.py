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
Import the local negative-lists workbook (Public Prosecutor asset-freeze orders, local terrorist lists and
entities, UN sheets) into the internal list with a precise diff against the previous import.

    python scripts/import_local_lists.py <workbook.xlsx>                  # dry run: counts only
    python scripts/import_local_lists.py <workbook.xlsx> --apply          # write (one transaction)
    python scripts/import_local_lists.py <workbook.xlsx> --apply --allow-shrink   # a sheet shrank on purpose
    python scripts/import_local_lists.py <workbook.xlsx> --add-new-only [--apply] [--include-un]
        # existing rows are only linked (never changed), lifted records and records already screenable
        # (internal list, EMLCU, UN feed: same national ID / passport / UN reference / name) are not added

Sheets are recognised by their header content; each sheet is mapped to a generic category shown on hits.
Output is made of counts only (per sheet, per category, per change type) - never a name or an ID.
Exit codes: 0 done / dry run, 2 blocked by a safety check or another import running, 1 error.
See screening/local_lists/importer.py for the diff rules.
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, '.env'))
except ImportError:
    pass


def _print(out, as_json=False):
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return
    from screening.local_lists.categories import label
    from screening.local_lists.workbook import KIND_LABEL
    print(f"Edition date (from the sheets): {out.get('edition_date') or 'unknown'}")
    print('Sheets:')
    for i, s in enumerate(out['sheets'], 1):
        if not s.get('kind'):
            print(f"  {i:>2}. [not a list sheet{' - LOOKS LIKE DATA' if s.get('looks_like_data') else ''}]"
                  f" rows {s.get('rows', 0)}")
            continue
        cats = ', '.join(f"{label(c, 'en')}: {v['records']} ({v['listed']} listed, {v['lifted']} lifted; "
                         f"{v['persons']} persons, {v['entities']} entities)" for c, v in s['categories'].items())
        extra = []
        if s.get('skipped_rows'):
            extra.append(f"{s['skipped_rows']} rows skipped")
        if s.get('duplicates'):
            extra.append(f"{s['duplicates']} duplicate records")
        if s.get('lift_unmatched'):
            extra.append(f"{s['lift_unmatched']} lifts not tied to one order (kept listed)")
        if s.get('missing_columns'):
            extra.append('columns not found: ' + ', '.join(s['missing_columns']))
        print(f"  {i:>2}. {KIND_LABEL[s['kind']]} - rows {s['data_rows']} -> records {s['records']}: {cats}"
              + (f" [{'; '.join(extra)}]" if extra else ''))
    print('Mode: ' + ('ADD NEW ONLY (existing rows only linked, lifted and already-screenable records not added)'
                      if out.get('mode') == 'add_new_only' else 'full sync'))
    print('Changes per category:')
    for c, v in out['counts'].items():
        print(f"  {label(c, 'en')}: " + ', '.join(f'{k} {n}' for k, n in v.items() if n))
    t = out['totals']
    print('Totals: ' + ', '.join(f'{k} {v}' for k, v in t.items()))
    if out.get('dob_linked'):
        print(f"Dates of birth linked to masked IDs: {out['dob_linked']}")
    if out.get('legacy_unmatched') and out.get('mode') != 'add_new_only':
        print(f"Older internal-list rows of the same lists not matched to the workbook: {out['legacy_unmatched']}"
              f" (left as they are; --retire-legacy deactivates them)")
    for r in out.get('reasons') or []:
        print(('BLOCKING: ' if r in (out.get('blocking') or []) else 'note: ') + r)
    print(f"Result: {out['result']}" + (f" (import #{out['import_id']})" if out.get('import_id') else ''))
    if out.get('sync'):
        print('After the import: ' + ', '.join(f'{k} {v}' for k, v in out['sync'].items()))
    if out.get('verify'):
        print('Screening check of added names: ' + ', '.join(f'{k} {v}' for k, v in out['verify'].items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path')
    ap.add_argument('--apply', action='store_true', help='write (default: dry run)')
    ap.add_argument('--allow-shrink', action='store_true', help='apply although a sheet / category shrank')
    ap.add_argument('--allow-unknown', action='store_true', help='apply although a data sheet was not recognised')
    ap.add_argument('--shrink-pct', type=float, default=10.0, help='largest allowed drop per category (percent)')
    ap.add_argument('--shrink-min', type=int, default=25, help='smallest drop (records) that can block')
    ap.add_argument('--lifted', choices=('history', 'inactive'), default='history',
                    help="lifted records: kept visible labelled 'lifted' (history, default) or deactivated")
    ap.add_argument('--retire-legacy', action='store_true',
                    help='deactivate older internal-list rows of the same lists that the workbook does not back')
    ap.add_argument('--no-adopt', action='store_true', help='do not take over matching older internal-list rows')
    ap.add_argument('--no-sync', action='store_true', help='skip the internal-list / search-index sync after it')
    ap.add_argument('--user-id', type=int, default=None, help='user recorded on the version and the audit')
    ap.add_argument('--json', action='store_true', help='print the counts as JSON')
    ap.add_argument('--add-new-only', action='store_true',
                    help='do not rewrite existing rows: link them, add only new listed records not already screenable')
    ap.add_argument('--include-un', action='store_true',
                    help='with --add-new-only: also add UN-sheet records not already in the UN feed (default: skipped)')
    ap.add_argument('--verify', type=int, default=10, help='names screened after an add-new-only import (0: none)')
    a = ap.parse_args()
    if not os.path.isfile(a.path):
        print('file not found')
        return 1
    import psycopg2
    from config import Config
    from screening.local_lists import importer as I
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    try:
        out = I.run(conn, a.path, do_apply=a.apply, user_id=a.user_id, trigger='cli', allow_shrink=a.allow_shrink,
                    allow_unknown=a.allow_unknown, shrink_pct=a.shrink_pct, shrink_min=a.shrink_min,
                    lifted_mode=a.lifted, retire_legacy=a.retire_legacy, adopt_legacy=not a.no_adopt,
                    sync=not a.no_sync, add_new_only=a.add_new_only, include_un=a.include_un, verify=a.verify)
    except I.ImportBusy as e:
        print(f'STOP: {e}')
        return 2
    finally:
        conn.close()
    _print(out, a.json)
    return 2 if out['result'] == 'BLOCKED' else 0


if __name__ == '__main__':
    sys.exit(main())
