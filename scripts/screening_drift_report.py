#!/usr/bin/env python3
"""
Monthly screening drift report (Phase 5, P5-5): collect the month's figures, compare them with
the month before, store them in screening_drift_reports and alert the MLROs on large moves.

    python scripts/screening_drift_report.py                 # the previous month (the monthly timer)
    python scripts/screening_drift_report.py --month 2026-10
    python scripts/screening_drift_report.py --month 2026-10 --dry-run   # print only, store nothing
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--month', default=None, help='YYYY-MM (default: the previous month)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-alert', action='store_true')
    a = ap.parse_args()
    import psycopg2
    import psycopg2.extras
    from config import Config
    from screening import drift as D
    month = (a.month or D.previous_month())[:7]
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor,
                            options='-c statement_timeout=300000')

    def q(sql, params):
        c = conn.cursor()
        c.execute(sql, params)
        rows = c.fetchall()
        conn.rollback()
        return rows
    cfg = {}
    try:
        r = q("SELECT config_value FROM screening_config WHERE config_key = 'drift_thresholds'", ())
        if r and r[0]['config_value']:
            cfg = json.loads(r[0]['config_value'])
    except Exception:
        conn.rollback()
    if a.dry_run:
        m = D.collect(q, month)
        try:
            prev, _ = D.load(conn, D.month_before(month))
        except Exception:
            conn.rollback()
            prev = None
        al = D.compare(m, prev, D.thresholds(cfg))
    else:
        m, al = D.run(conn, q, month, created_by='scheduled', cfg=cfg, alert=not a.no_alert)
    s = m['screening']
    print(f"drift report {month}: {s['screenings']} screenings, INCOMPLETE {s['incomplete_rate']}%, "
          f"{sum(d['hits'] for d in m['hits_by_list'].values())} hits, {len(m['lists'])} lists, "
          f"gold runs {sum(g['runs'] for g in m['gold'].values())}, e2e runs {m['e2e']['runs']}")
    for x in al:
        print('ALERT ' + x['en'])
    if not al:
        print('no alerts')
    if a.dry_run:
        print('DRY RUN: nothing stored')


if __name__ == '__main__':
    main()
