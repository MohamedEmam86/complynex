#!/usr/bin/env python3
"""
Gold Set evaluation and quality gate (Phase 0, P0-3 / P0-4).

Scores every Gold Set pair with the live matching code and counts, per category:
  Miss = a pair that is the same person / entity (label 1) scored below the alert threshold
  FP   = a pair that is a different person / entity (label 0) scored at or above it
The alert threshold is match_intel.LOW (the score from which a hit is shown).

Headline rates use the 'core' tier only (realistic Egyptian / list data); 'supplementary'
categories (chat-style Franco-Arabic, Maghrebi spelling, Persian script, small sets) are
reported and gated but kept out of the headline.
Holdout pairs (~20 % of base names) are only ever reported as totals.
A retrieval check confirms that internal-list names are actually recalled by search_internal.

    python scripts/gold_set_eval.py                    # report
    python scripts/gold_set_eval.py --write-baseline   # store the reference result (first time / new Gold Set)
    python scripts/gold_set_eval.py --gate             # exit 1 if any category is worse than the baseline
    python scripts/gold_set_eval.py --ratchet          # after a clean deploy: keep the best of baseline and now
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

import logging  # noqa: E402
logging.disable(logging.WARNING)

from screening import match_intel as mi  # noqa: E402

GOLD = os.path.join(BASE, 'screening', 'data', 'gold')
RETRIEVAL_N = 300


def commit():
    try:
        return subprocess.check_output(['git', '-c', 'safe.directory=*', '-C', BASE, 'rev-parse', '--short', 'HEAD'],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return 'unknown'


def write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def evaluate(version, retrieval=True):
    from screening import thresholds
    in_force = thresholds.apply(force=True)
    path = os.path.join(GOLD, f'gold_v{version}.jsonl')
    raw = open(path, 'rb').read()
    pairs = [json.loads(l) for l in raw.decode('utf-8').splitlines() if l.strip()]
    t0 = time.time()
    dev = defaultdict(lambda: {'n': 0, 'miss': 0, 'fp': 0, 'labels': set(), 'tier': None})
    hold = {'n': 0, 'miss': 0, 'fp': 0}
    for p in pairs:
        s = mi.name_match(p['query'], p['listed'])['score']
        miss = p['label'] == 1 and s < mi.LOW
        fp = p['label'] == 0 and s >= mi.LOW
        if p['holdout']:
            d = hold
        else:
            d = dev[p['cat']]
            d['labels'].add(p['label'])
            d['tier'] = p.get('tier', 'core')
        d['n'] += 1
        d['miss'] += miss
        d['fp'] += fp
    res = {'gold_version': version, 'gold_sha256': hashlib.sha256(raw).hexdigest(), 'commit': commit(),
           'threshold': mi.LOW, 'thresholds': in_force, 'pairs': len(pairs), 'categories': {}, 'holdout': hold, 'mixed_labels': []}
    for c, d in sorted(dev.items()):
        if len(d['labels']) != 1:
            res['mixed_labels'].append(c)
            continue
        lab = next(iter(d['labels']))
        k = 'miss' if lab == 1 else 'fp'
        res['categories'][c] = {'type': 'positive' if lab == 1 else 'negative', 'tier': d['tier'], 'n': d['n'],
                                'errors': d[k], 'rate': round(100.0 * d[k] / d['n'], 2) if d['n'] else None}
    for tier in ('core', 'supplementary'):
        pos = [v for v in res['categories'].values() if v['type'] == 'positive' and v['tier'] == tier]
        neg = [v for v in res['categories'].values() if v['type'] == 'negative' and v['tier'] == tier]
        res[f'{tier}_miss_rate'] = round(100.0 * sum(v['errors'] for v in pos) / max(1, sum(v['n'] for v in pos)), 2)
        res[f'{tier}_fp_rate'] = round(100.0 * sum(v['errors'] for v in neg) / max(1, sum(v['n'] for v in neg)), 2)
    res['seconds_scoring'] = round(time.time() - t0, 1)
    if retrieval:
        res['retrieval'] = retrieval_check(pairs)
    return res


def preview_scores(version):
    """Sorted name scores of the core dev pairs (positives / negatives) for the threshold preview."""
    pos, neg = [], []
    with open(os.path.join(GOLD, f'gold_v{version}.jsonl'), encoding='utf-8') as f:
        for line in f:
            p = json.loads(line)
            if p['holdout'] or p.get('tier', 'core') != 'core':
                continue
            (pos if p['label'] == 1 else neg).append(round(mi.name_match(p['query'], p['listed'])['score'], 3))
    return {'version': version, 'commit': commit(), 'positive': sorted(pos), 'negative': sorted(neg)}


def retrieval_check(pairs):
    """Positive Arabic pairs from the internal lists: is the listed record recalled?"""
    import psycopg2
    import psycopg2.extras
    from config import Config
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor,
                            connect_timeout=15, options='-c statement_timeout=20000')
    rnd = random.Random(7)
    cand = sorted((p for p in pairs if p['label'] == 1 and p['src'] == 'ar_lists' and not p['holdout']
                   and mi.is_arabic(p['query']) and mi.is_arabic(p['listed'])), key=lambda p: p['id'])
    sample = rnd.sample(cand, min(RETRIEVAL_N, len(cand)))
    target = lambda n: ' '.join(mi.tokens(n))  # noqa: E731
    found, by = 0, defaultdict(lambda: [0, 0])
    t0 = time.time()
    cur = conn.cursor()
    for p in sample:
        cur.execute("SELECT 1 FROM screening_watchlist WHERE source='emlcu' AND full_name=%s LIMIT 1", (p['listed'],))
        if cur.fetchone():
            continue     # EMLCU names live in screening_watchlist, not an internal-list record
        tl = target(p['listed'])
        ok = any(target(m.get('original_name') or m.get('full_name') or '') == tl
                 for m in mi.search_internal(conn, 'internal_blacklist', p['query'], limit=50))
        by[p['cat']][0] += 1
        by[p['cat']][1] += ok
        found += ok
    n = sum(v[0] for v in by.values())
    return {'n': n, 'found': found, 'recall': round(100.0 * found / max(1, n), 2),
            'by_category': {k: {'n': v[0], 'found': v[1]} for k, v in sorted(by.items())},
            'seconds': round(time.time() - t0, 1)}


def gate(res, base):
    problems = []
    if res['gold_sha256'] != base['gold_sha256']:
        problems.append('Gold Set file differs from the one the baseline was measured on (rebuild the baseline on purpose)')
    if res['mixed_labels']:
        problems.append(f"categories mixing positive and negative labels: {res['mixed_labels']}")
    for c, b in base['categories'].items():
        r = res['categories'].get(c)
        if not r:
            problems.append(f'{c}: category missing')
        elif r['errors'] > b['errors']:
            problems.append(f"{c}: {b['errors']} -> {r['errors']} {'misses' if b['type'] == 'positive' else 'false positives'}")
    new = set(res['categories']) - set(base['categories'])
    if new:
        problems.append(f'categories not in the baseline: {sorted(new)}')
    for k in ('miss', 'fp'):
        if res['holdout'][k] > base['holdout'][k]:
            problems.append(f"holdout {k}: {base['holdout'][k]} -> {res['holdout'][k]}")
    rb, rr = base.get('retrieval'), res.get('retrieval')
    if rb and not rr:
        problems.append('retrieval check did not run but the baseline has one')
    # retrieval also depends on the list data, which changes daily: allow a 1 % wobble
    if rb and rr and rr['found'] < rb['found'] - max(1, round(0.01 * rb['n'])):
        problems.append(f"retrieval: {rb['found']} -> {rr['found']} of {rr['n']} recalled")
    return problems


def ratchet(res, base):
    """Best of both: per category the lower error count and the lower holdout errors.
    Only ever tightens the baseline; never loosens it."""
    if res['gold_sha256'] != base['gold_sha256'] or res['mixed_labels']:
        return base, False
    out = json.loads(json.dumps(base))
    changed = False
    for c, b in out['categories'].items():
        r = res['categories'].get(c)
        if r and r['errors'] < b['errors']:
            b['errors'], b['rate'] = r['errors'], r['rate']
            changed = True
    for k in ('miss', 'fp'):
        if res['holdout'][k] < out['holdout'][k]:
            out['holdout'][k] = res['holdout'][k]
            changed = True
    # retrieval is NOT ratcheted: it moves with the list data, a lucky day must not raise the bar
    out['ratcheted_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    out['ratcheted_from_commit'] = res['commit']
    return out, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', type=int, default=1)
    ap.add_argument('--write-baseline', action='store_true')
    ap.add_argument('--gate', action='store_true')
    ap.add_argument('--ratchet', action='store_true')
    ap.add_argument('--no-retrieval', action='store_true')
    a = ap.parse_args()
    res = evaluate(a.version, retrieval=not a.no_retrieval)
    try:
        os.makedirs(os.path.join(GOLD, 'results'), exist_ok=True)
        write_json(os.path.join(GOLD, 'results', f'{time.strftime("%Y%m%d_%H%M%S")}_{res["commit"]}.json'), res)
    except OSError as ex:
        print(f'note: result file not saved ({ex})')
    bpath = os.path.join(GOLD, f'baseline_v{a.version}.json')
    print(json.dumps({k: res[k] for k in ('commit', 'pairs', 'core_miss_rate', 'core_fp_rate',
                                          'supplementary_miss_rate', 'supplementary_fp_rate', 'holdout')}, indent=1))
    for c, v in res['categories'].items():
        print(f"  {c:32s} {v['tier'][:4]} {v['type']:8s} n={v['n']:5d} errors={v['errors']:5d} rate={v['rate']}%")
    if res.get('retrieval'):
        r = res['retrieval']
        print(f"  retrieval (internal lists): {r['found']}/{r['n']} = {r['recall']}%  ({r['seconds']}s)")
    if a.write_baseline:
        write_json(bpath, res)
        write_json(os.path.join(GOLD, f'preview_scores_v{a.version}.json'), preview_scores(a.version))
        print(f'baseline written: {bpath}')
    if a.ratchet:
        if os.path.exists(bpath):
            new, changed = ratchet(res, json.load(open(bpath)))
            if changed:
                write_json(bpath, new)
            print('baseline tightened' if changed else 'baseline unchanged (nothing better)')
    if a.gate:
        if not os.path.exists(bpath):
            print('GATE: no baseline yet -> FAIL (write one with --write-baseline)')
            sys.exit(1)
        base = json.load(open(bpath))
        if float(base.get('threshold', mi.LOW)) != float(res['threshold']):
            # never re-base inside the gate (a code regression would become the reference):
            # the baseline is re-measured on the deployed code when the MLRO saves a new threshold
            print(f"GATE FAILED: the alert threshold is {res['threshold']} but the baseline was measured at "
                  f"{base.get('threshold')}. Re-measure on the deployed code first: "
                  f"python scripts/gold_set_eval.py --write-baseline")
            sys.exit(1)
        problems = gate(res, base)
        if problems:
            print('GATE FAILED:')
            for p in problems:
                print('  - ' + p)
            sys.exit(1)
        print('GATE PASSED: no category is worse than the baseline')


if __name__ == '__main__':
    main()
