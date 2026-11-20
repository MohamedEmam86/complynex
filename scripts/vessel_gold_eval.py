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

Owner policy decision (round 3, recorded here because it changes what the Gold Set expects):
  a name-only search must return the applicable matches. An EXACT one-word name of a sanctioned ship is a
  POTENTIAL match (alert, "confirm with the IMO number, flag and owner") unless it is a common ship name:
  carried now by >= common_name_hulls (default 3) distinct hulls across every vessel record held (sanctions,
  bans, port-state control, analysis: ~10k hulls in production), or a common ship word (common_ship_words,
  maritime vocabulary such as ADMIRAL, MARINA, STAR). Common names stay review ("IMO needed").
  The Gold Set labels every listed one-word name (generic_name_listed) "review"; the cases whose name is rare
  now come out "match". That is the owner's policy, not an engine error: such a category may score below the
  v1 baseline, and the round-3 baseline (written with --write-baseline) records the new reference. With a
  local database that holds only the sanctions lists, pass --fleet-sample <ship CSV> to measure name
  frequency against a world-fleet sample as production does.

Re-verifying the labels on production-like data (round 4): the Gold Set was built from fewer lists than
production holds (production adds ua_war_sanctions, ch / ca / au lists, the ban and port-inspection datasets of
the OpenSanctions DEFAULT collection). Build a local database with production's vessel data - the public DEFAULT
collection's Vessel / Ownership / UnknownLink entities merged with the sanctions collection - load it through
the normal list update, then run this script with --label-audit: every failure is reported as "coverage" (the
ship or exact name IS listed there: the label must follow the policy for listed ships) or "engine".
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
# deploy gate: VESSEL_GOLD / VESSEL_GOLD_BASELINE point at the server's copies (data never in git)
DEFAULT_GOLD = os.environ.get('VESSEL_GOLD') or os.path.join(GOLD_DIR, 'vessel_gold_v1.jsonl')
DEFAULT_BASELINE = os.environ.get('VESSEL_GOLD_BASELINE') or os.path.join(GOLD_DIR, 'vessel_baseline.json')


def _runner(gold_path, runner_path=None):
    path = runner_path or os.path.join(os.path.dirname(os.path.abspath(gold_path)), 'evaluate.py')
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location('vessel_gold_runner', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fleet_sample(path):
    """{normalised one-word name: {hull keys}} from a CSV of ships (columns name or caption, imo, optional
    type: only VESSEL rows). Measures how common a one-word name is the way production does (production holds
    ~10k ship records of every class); the file is data, never in git. Only the ship's current name counts
    (alias columns of exports mix in former names), and only rows with a valid IMO (a row without one cannot
    be told apart from the same hull listed elsewhere)."""
    import csv
    from screening import vessel_utils as VU
    out = {}
    with open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            if (r.get('type') or 'VESSEL').upper() != 'VESSEL':
                continue
            imo = VU.norm_imo(r.get('imo'))
            if not (imo and VU.imo_valid(imo)):
                continue
            k = VU.norm_name(r.get('name') or r.get('caption') or '')
            if k and ' ' not in k:
                out.setdefault(k, set()).add('IMO:' + imo)
    return out


def label_audit(conn, failures):
    """For each failure: is it a LABEL COVERAGE question (the ship / name IS on the lists this database holds,
    e.g. production lists the Gold Set builder did not use) or an ENGINE question? Printed next to the report.
    coverage: the screened IMO is a listed ship's IMO, or the screened name is exactly a listed name (current
    name or alias) of a sanctioned / banned ship - the label must then follow the policy for listed ships."""
    from screening import vessel_store as VS
    from screening import vessel_utils as VU
    from screening import vessel_provenance as VP
    cands = [c for c in VS.load_candidates(conn) if VP.alerts(c.get('provenance') or VP.SANCTION)]
    by_name, by_imo = {}, {}
    for c in cands:
        for n in c.get('names') or []:
            by_name.setdefault(VU.norm_name(n), []).append(c)
        if c.get('imo'):
            by_imo.setdefault(c['imo'], []).append(c)
    out = []
    for f in failures:
        q = f.get('query') or {}
        imo = VU.norm_imo(q.get('imo'))
        hits = by_imo.get(imo, []) if imo else []
        why = 'IMO listed' if hits else ''
        if not hits and q.get('name'):
            hits = by_name.get(VU.norm_name(q['name']), [])
            why = 'name listed exactly' if hits else ''
        verdict = 'coverage' if hits else 'engine'
        detail = sorted({f"{c['name']} IMO {c.get('imo') or '-'} {c.get('provenance')}"
                         + ('' if VU.norm_name(q.get('name') or '') == VU.norm_name(c['name']) else ' (alias)')
                         for c in hits})[:3]
        out.append((f['id'], f.get('category'), f.get('expected'), f.get('got'), verdict, why, detail))
    print('\nlabel audit (coverage = the ship / name is on the lists held here; engine = look at the engine):')
    for row in out:
        print('   %s %-26s expected %-8s got %-8s -> %-8s %s %s' % (row[0], row[1], row[2], row[3], row[4], row[5],
                                                                  '; '.join(row[6])))
    return out


def make_screen(conn, with_owner=True, sample=None):
    """screen(query) -> {decision, vessel_imo, score} for the Gold Set runner."""
    from screening import vessel_engine as VE
    party = VE.party_screener() if with_owner else None

    def screen(q):
        res = VE.screen_vessel(name=q.get('name'), imo=q.get('imo'), mmsi=q.get('mmsi'), call_sign=q.get('call_sign'),
                               flag=q.get('flag'), owner=q.get('owner'), conn=conn, whitelist={},
                               screen_party=party if (q.get('owner') or '').strip() else None,
                               fleet_sample=sample)
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
    ap.add_argument('--label-audit', action='store_true', help='tell label coverage from engine questions '
                                                                 'for each failure (see label_audit)')
    ap.add_argument('--fleet-sample', metavar='CSV', help='more ship records to measure how common a one-word '
                                                          'name is (see fleet_sample)')
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
        sample = fleet_sample(a.fleet_sample) if a.fleet_sample else None
        res = ev.evaluate(make_screen(conn, with_owner=not a.no_owner, sample=sample), a.gold)
        try:
            from screening.routes import get_engine
            from api.screening_v1 import _release_engine_conn
            _release_engine_conn(get_engine())
        except Exception:
            pass
    ev.print_report(res, a.show_failures)
    if a.label_audit and res.get('failures'):
        with app.app_context():
            from database.db import get_db
            label_audit(get_db(), res['failures'])
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
