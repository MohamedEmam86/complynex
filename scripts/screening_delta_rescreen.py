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
Delta re-screening: when names are added to any list, check every EXISTING
customer, merchant (and its beneficial owner) and party against the new names
only — the control an asset-freeze order demands ("freeze without delay"):
a customer onboarded last year must be caught the day his name is listed,
not at his next periodic review.

Runs daily after the list refresh (complynex-screening-delta.timer). Each run
continues from the last list record ids it saw. Hits are stored in
screening_delta_hits, shown on the Screening Quality page, and one compliance
alert is raised while any hit is open.

    python scripts/screening_delta_rescreen.py            # since the last run
    python scripts/screening_delta_rescreen.py --init     # set the starting point only
"""
import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from config import Config  # noqa: E402
from screening import match_intel as mi  # noqa: E402

def _min_score():
    # store potential and confirmed matches only (thresholds in force, set by the MLRO)
    from screening import thresholds
    thresholds.apply()
    return mi.POTENTIAL


def _subjects(cur):
    """Everyone the company deals with, with the identifiers we hold."""
    out = []
    cur.execute("""SELECT id, full_name, full_name_arabic, id_number, date_of_birth, nationality
                   FROM customers""")
    for r in cur.fetchall():
        out.append({'table': 'customers', 'id': r['id'], 'names': [r['full_name'], r['full_name_arabic']],
                    'nid': r['id_number'], 'dob': r['date_of_birth'], 'nat': r['nationality']})
    cur.execute("""SELECT id, merchant_name, trade_name, ubo_name, ubo_id_number, ubo_nationality FROM merchants""")
    for r in cur.fetchall():
        out.append({'table': 'merchants', 'id': r['id'], 'names': [r['merchant_name'], r['trade_name']],
                    'nid': None, 'dob': None, 'nat': None})
        if r['ubo_name']:
            out.append({'table': 'merchants.ubo', 'id': r['id'], 'names': [r['ubo_name']],
                        'nid': r['ubo_id_number'], 'dob': None, 'nat': r['ubo_nationality']})
    cur.execute("SELECT id, full_name, full_name_arabic, date_of_birth, nationality FROM parties")
    for r in cur.fetchall():
        out.append({'table': 'parties', 'id': r['id'], 'names': [r['full_name'], r['full_name_arabic']],
                    'nid': None, 'dob': r['date_of_birth'], 'nat': r['nationality']})
    for s in out:
        s['names'] = [n for n in dict.fromkeys(s['names']) if n and str(n).strip()]
    return [s for s in out if s['names']]


def _index(subjects):
    """element -> subjects carrying it (Arabic and Latin, plus the Arabic
    rendering of Latin names so the two scripts meet)."""
    idx = defaultdict(set)
    for i, s in enumerate(subjects):
        for n in s['names']:
            toks = mi.tokens(n)
            if not mi.is_arabic(n):
                toks += mi.tokens(mi.to_arabic(n))
            for t in toks:
                if len(t) >= 2:
                    idx[t].add(i)
    return idx


def _new_list_names(cur, state):
    """List records added since the last run, with every name form they carry."""
    news = []
    cur.execute("""SELECT id, original_name, full_name, aliases, national_id, date_of_birth, nationality,
                          category, source FROM internal_blacklist
                   WHERE id > %s AND COALESCE(is_active,1) != 0 ORDER BY id""", (state['bl'],))
    for r in cur.fetchall():
        news.append(('internal_blacklist', r['id'], r['original_name'] or r['full_name'],
                     [r['original_name'], r['full_name']], r['national_id'], r['date_of_birth'],
                     r['nationality'], r['category'], 'Internal blacklist'))
    cur.execute("""SELECT id, original_name, full_name, national_id, date_of_birth, nationality, category
                   FROM internal_pep WHERE id > %s AND COALESCE(is_active,1) != 0 ORDER BY id""", (state['pep'],))
    for r in cur.fetchall():
        news.append(('internal_pep', r['id'], r['original_name'] or r['full_name'],
                     [r['original_name'], r['full_name']], r['national_id'], r['date_of_birth'],
                     r['nationality'], r['category'], 'Internal PEP'))
    cur.execute("""SELECT id, full_name, full_name_arabic, national_id_numbers, date_of_birth, nationality,
                          countries, list_type, source FROM screening_watchlist
                   WHERE id > %s AND is_active = 1 AND source NOT IN ('internal_blacklist','internal_pep')
                   ORDER BY id""", (state['wl'],))
    for r in cur.fetchall():
        news.append(('screening_watchlist', r['id'], r['full_name_arabic'] or r['full_name'],
                     [r['full_name_arabic'], r['full_name']], r['national_id_numbers'], r['date_of_birth'],
                     [r['nationality'], r['countries']], r['list_type'], r['source']))
    return news


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--init', action='store_true', help='record the current list ids as the starting point')
    ap.add_argument('--since-bl', type=int, help='re-check internal blacklist records with id above this')
    a = ap.parse_args()
    from screening import thresholds
    thresholds.apply(force=True)
    from utils.demo import skip_in_demo
    if skip_in_demo("delta re-screening"):
        return
    from screening.update_lock import wait_until_free
    wait_until_free()  # names written by a running list update are not all committed yet
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT to_bl_id, to_pep_id, to_wl_id FROM screening_delta_runs ORDER BY id DESC LIMIT 1")
    last = cur.fetchone()
    cur.execute("""SELECT (SELECT COALESCE(max(id),0) FROM internal_blacklist) bl,
                          (SELECT COALESCE(max(id),0) FROM internal_pep) pep,
                          (SELECT COALESCE(max(id),0) FROM screening_watchlist) wl""")
    now_max = cur.fetchone()
    if a.init or not last:
        cur.execute("""INSERT INTO screening_delta_runs (from_bl_id, to_bl_id, from_pep_id, to_pep_id,
                       from_wl_id, to_wl_id, note) VALUES (%s,%s,%s,%s,%s,%s,'starting point')""",
                    (now_max['bl'], now_max['bl'], now_max['pep'], now_max['pep'], now_max['wl'], now_max['wl']))
        conn.commit()
        if a.init or a.since_bl is None:
            print('starting point recorded', dict(now_max))
            return
        last = {'to_bl_id': now_max['bl'], 'to_pep_id': now_max['pep'], 'to_wl_id': now_max['wl']}
    state = {'bl': a.since_bl if a.since_bl is not None else last['to_bl_id'],
             'pep': last['to_pep_id'], 'wl': last['to_wl_id']}
    t0 = time.time()
    subjects = _subjects(cur)
    idx = _index(subjects)
    news = _new_list_names(cur, state)
    cur.execute("""INSERT INTO screening_delta_runs (from_bl_id, to_bl_id, from_pep_id, to_pep_id, from_wl_id,
                   to_wl_id, new_names, subjects) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (state['bl'], now_max['bl'], state['pep'], now_max['pep'], state['wl'], now_max['wl'],
                 len(news), len(subjects)))
    run_id = cur.fetchone()['id']
    hits = 0
    for table, rid, shown, forms, nid, dob, nat, cat, src in news:
        forms = [f for f in forms if f]
        ltoks = set()
        for f in forms:
            ltoks.update(mi.tokens(f))
            if not mi.is_arabic(f):
                ltoks.update(mi.tokens(mi.to_arabic(f)))
        # candidates: subjects sharing at least one identifying element
        distinct = [t for t in ltoks if mi._weight(t) >= 2.5] or list(ltoks)
        cand = set()
        for t in distinct:
            cand |= idx.get(t, set())
        for i in cand:
            s = subjects[i]
            best = None
            for sn in s['names']:
                for f in forms:
                    m = {'match_score': 0, 'original_name': f if mi.is_arabic(f) else None,
                         'full_name': None if mi.is_arabic(f) else f,
                         'national_id': nid if table != 'screening_watchlist' else None,
                         'national_id_numbers': nid if table == 'screening_watchlist' else None,
                         'date_of_birth': dob, 'nationality': nat}
                    nm = mi.name_match(sn, f)
                    if mi.is_arabic(sn) != mi.is_arabic(f):
                        nm['score'] *= 0.97
                    m['match_score'] = nm['score']
                    if nm['score'] < mi.LOW:
                        continue
                    d = mi.decide(m, sn, national_id=s['nid'], dob=s['dob'], nationality=s['nat'])
                    if best is None or d['match_score'] > best[0]['match_score']:
                        best = (d, sn, f)
            if best and best[0]['match_score'] >= _min_score():
                d, sn, f = best
                cur.execute("""INSERT INTO screening_delta_hits (run_id, subject_table, subject_id, subject_name,
                                 list_table, list_record_id, listed_name, list_source, category, score, tier, decision)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (subject_table, subject_id, list_table, list_record_id) DO NOTHING""",
                            (run_id, s['table'], s['id'], sn, table, rid, shown, src, cat, d['match_score'],
                             d['decision']['tier'], json.dumps(d['decision'], ensure_ascii=False, default=str)))
                hits += cur.rowcount
    cur.execute("UPDATE screening_delta_runs SET hits = %s, duration_s = %s WHERE id = %s",
                (hits, round(time.time() - t0, 1), run_id))
    conn.commit()
    cur.execute("SELECT count(*) AS n, count(*) FILTER (WHERE tier = 'CONFIRMED') AS c "
                "FROM screening_delta_hits WHERE status = 'open'")
    open_ = cur.fetchone()
    print(f'run {run_id}: {len(news):,} new list names x {len(subjects):,} subjects -> {hits} new hits '
          f'({open_["n"]} open, {open_["c"]} confirmed) in {time.time() - t0:.1f}s')
    if open_['n']:
        try:
            from app import app
            with app.app_context():
                from regcontrols.alerts import raise_alert
                raise_alert('screening_delta_hit',
                            f'{open_["n"]} existing customers/merchants match newly listed names',
                            f'{open_["c"]} confirmed, {open_["n"] - open_["c"]} potential. Review them on the '
                            f'Screening Quality page (section: new list names vs existing relationships).',
                            severity='critical' if open_['c'] else 'high', link='/screening/quality#delta')
        except Exception as e:
            print('alert not raised:', e)


if __name__ == '__main__':
    main()
