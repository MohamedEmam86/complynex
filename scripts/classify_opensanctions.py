#!/usr/bin/env python3
"""
Store each OpenSanctions record's category in list_type (Phase 2, G1): SANCTIONS, TERROR,
SANCTION_LINKED, CRIME, PEP, EXPORT_CONTROL, DEBARMENT, REG_ACTION, TRADE_RISK, POI, CONTEXT
(see screening/list_category.py). New and updated records get it from the loader; this
script brings the existing ones in line.

Only rows whose category differs are written, in batches, with updated_at moved so the
search-index sync picks them up. Safe to re-run. Dry run unless --apply.

    python scripts/classify_opensanctions.py              # counts per category
    python scripts/classify_opensanctions.py --apply [--batch 20000] [--pause 2]
"""
import argparse
import collections
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--batch', type=int, default=20000)
    ap.add_argument('--pause', type=float, default=2.0)
    a = ap.parse_args()
    import psycopg2
    from config import Config
    from screening.list_category import categorize
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    rd = conn.cursor(name='os_scan')
    rd.itersize = 50000
    rd.execute("SELECT id, list_type, topics, dataset FROM screening_watchlist WHERE source='opensanctions' AND is_active=1")
    change = collections.defaultdict(list)
    per_cat = collections.Counter()
    for i, lt, tp, ds in rd:
        c = categorize(tp, ds)
        per_cat[c] += 1
        if lt != c:
            change[c].append(i)
    rd.close()
    conn.commit()
    print('categories:', dict(per_cat.most_common()))
    print('to change:', sum(len(v) for v in change.values()))
    if not a.apply:
        print('DRY RUN')
        return
    cur = conn.cursor()
    done = 0
    for c, ids in change.items():
        for k in range(0, len(ids), a.batch):
            part = ids[k:k + a.batch]
            cur.execute("""UPDATE screening_watchlist SET list_type=%s,
                           updated_at=now()::text WHERE id = ANY(%s)""", (c, part))
            conn.commit()
            done += len(part)
            print(f'{c}: {done} written', flush=True)
            time.sleep(a.pause)
    print('APPLIED', done)


if __name__ == '__main__':
    main()
