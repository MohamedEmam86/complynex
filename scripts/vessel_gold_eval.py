#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Vessel Gold Set evaluation and deploy gate (adapter around the independent vessel Gold Set).

The Gold Set (vessel_gold_v1.jsonl + its runner evaluate.py) is DATA kept outside git, next to the names
Gold Set in screening/data/gold/ (or anywhere: give the path). This script screens every case with the live
vessel engine (screening.vessel_engine.screen_vessel, real lists from the database, the owner layer through
the person / entity engine) and maps the result with vessel_engine.decision():
    CONFIRMED / POTENTIAL -> match,  LOW -> review,  nothing at or above the alert threshold -> no_match
using the thresholds in force (screening/thresholds.py) and the vessel weights (screening_config
'vessel_engine'). The whitelist is ignored (a Gold Set run must not depend on earlier decisions).

    python scripts/vessel_gold_eval.py                                     # report
    python scripts/vessel_gold_eval.py --gold /path/vessel_gold_v1.jsonl   # another location
    python scripts/vessel_gold_eval.py --write-baseline                    # store the reference result
    python scripts/vessel_gold_eval.py --gate                              # exit 1 if any category got worse
    python scripts/vessel_gold_eval.py --json out.json --show-failures 200
Exit codes: 0 ok, 1 gate failed, 2 Gold Set / runner missing (the deploy gate treats 2 as "skipped").

Deploy gate (proposal for deploy.sh, next to the names Gold Set gate; not wired in yet):
    # vessel Gold Set gate: block the deploy when any category got worse than the stored baseline
    if [ -f screening/data/gold/vessel_gold_v1.jsonl ]; then
        sudo -u www-data venv/bin/python scripts/vessel_gold_eval.py --gate --show-failures 10
        rc=$?
        if [ $rc -eq 1 ]; then echo "VESSEL GOLD SET GATE FAILED - deploy stopped"; rollback_and_exit; fi
        [ $rc -eq 2 ] && echo "vessel Gold Set gate skipped (no Gold Set / baseline)"
    fi
  First time / after a new Gold Set on purpose: scripts/vessel_gold_eval.py --write-baseline.
  The gate reads the lists from the live database, so run it after the list tables are current.
"""
import argparse
import importlib.util
import json
import logging
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
GOLD_DIR = os.path.join(BASE, 'screening', 'data', 'gold')
DEFAULT_GOLD = os.path.join(GOLD_DIR, 'vessel_gold_v1.jsonl')
DEFAULT_BASELINE = os.path.join(GOLD_DIR, 'vessel_baseline.json')


def _runner(gold_path, runner_path=None):
    path = runner_path or os.path.join(os.path.dirname(os.path.abspath(gold_path)), 'evaluate.py')
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location('vessel_gold_runner', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_screen(conn, with_owner=True):
    """screen(query) -> {decision, vessel_imo, score} for the Gold Set runner."""
    from screening import vessel_engine as VE
    party = VE.party_screener() if with_owner else None

    def screen(q):
        res = VE.screen_vessel(name=q.get('name'), imo=q.get('imo'), mmsi=q.get('mmsi'), call_sign=q.get('call_sign'),
                               flag=q.get('flag'), owner=q.get('owner'), conn=conn, whitelist={},
                               screen_party=party if (q.get('owner') or '').strip() else None)
        dec, imo, score = VE.decision(res)
        return {'decision': dec, 'vessel_imo': imo, 'score': score}
    return screen


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--gold', default=DEFAULT_GOLD)
    ap.add_argument('--runner', help='evaluate.py of the Gold Set (default: next to the JSONL)')
    ap.add_argument('--write-baseline', nargs='?', const=DEFAULT_BASELINE, metavar='FILE')
    ap.add_argument('--gate', nargs='?', const=DEFAULT_BASELINE, metavar='FILE')
    ap.add_argument('--json', metavar='FILE')
    ap.add_argument('--show-failures', type=int, default=25)
    ap.add_argument('--no-owner', action='store_true', help='skip the owner layer (no person / entity engine)')
    a = ap.parse_args()
    if not os.path.exists(a.gold):
        print(f'vessel Gold Set not found: {a.gold} (skipped)')
        sys.exit(2)
    ev = _runner(a.gold, a.runner)
    if ev is None:
        print('vessel Gold Set runner (evaluate.py) not found (skipped)')
        sys.exit(2)
    logging.disable(logging.WARNING)
    from app import create_app
    app = create_app()
    with app.app_context():
        from database.db import get_db
        conn = get_db()
        res = ev.evaluate(make_screen(conn, with_owner=not a.no_owner), a.gold)
        try:
            from screening.routes import get_engine
            from api.screening_v1 import _release_engine_conn
            _release_engine_conn(get_engine())
        except Exception:
            pass
    ev.print_report(res, a.show_failures)
    if a.json:
        with open(a.json, 'w') as f:
            json.dump(res, f, indent=1, ensure_ascii=False)
    if a.write_baseline:
        with open(a.write_baseline, 'w') as f:
            json.dump({k: v for k, v in res.items() if k != 'failures'}, f, indent=1)
        print(f'baseline written: {a.write_baseline}')
    if a.gate:
        if not os.path.exists(a.gate):
            print(f'no vessel baseline at {a.gate}: write one with --write-baseline (skipped)')
            sys.exit(2)
        problems = ev.gate(res, json.load(open(a.gate)))
        if problems:
            print('\nVESSEL GATE FAILED:')
            for p in problems:
                print('  -', p)
            sys.exit(1)
        print('\nvessel gate OK: no category worse than the baseline')


if __name__ == '__main__':
    main()
