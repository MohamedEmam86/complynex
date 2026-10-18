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

"""Evaluation harness for the Compliance Copilot (intake classification + playbook selection).

Runs the labelled synthetic dataset (tests/ai_eval/dataset.json) against each
provider and prints accuracy overall, per language and per intent:

    python scripts/ai_eval.py                       # rules_only on the generic seed catalog
    python scripts/ai_eval.py --url http://127.0.0.1:11434 --model qwen2.5:7b-instruct
    python scripts/ai_eval.py --embeddings http://127.0.0.1:8100     # rules + semantic-service embeddings
    python scripts/ai_eval.py --db                  # use this installation's catalog and AI settings

Only local / private-network servers are accepted (same guard as the app).
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ai import seed, tasks  # noqa: E402
from ai.providers import LocalEmbeddings, LocalHTTP, RulesOnly  # noqa: E402


def evaluate(name, gen, emb, intents, playbooks, data, limit=None):
    rows = data['intake'][:limit] if limit else data['intake']
    ok, by_lang, by_intent, confusion, statuses, ms = 0, defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), Counter(), Counter(), []
    for d in rows:
        t0 = time.monotonic()
        res, meta = tasks.classify(d['text'], intents, gen, emb)
        ms.append((time.monotonic() - t0) * 1000)
        statuses[meta['status']] += 1
        hit = res['intent'] == d['intent']
        ok += hit
        by_lang[d['lang']][0] += hit
        by_lang[d['lang']][1] += 1
        by_intent[d['intent'] or '(none)'][0] += hit
        by_intent[d['intent'] or '(none)'][1] += 1
        if not hit:
            confusion[(d['intent'] or '(none)', res['intent'] or '(none)')] += 1
    pb_rows = data['playbooks'] + [d for d in data['intake'] if d.get('playbook')]
    pb_rows = pb_rows[:limit] if limit else pb_rows
    pb_ok = 0
    for d in pb_rows:
        res, _ = tasks.select_playbooks(d['text'], playbooks, gen, emb)
        pb_ok += bool(res['playbooks']) and res['playbooks'][0]['code'] == d['playbook']
    return {'provider': name, 'n': len(rows), 'accuracy': ok / len(rows), 'by_lang': {k: v[0] / v[1] for k, v in by_lang.items()},
            'by_intent': {k: f'{v[0]}/{v[1]}' for k, v in sorted(by_intent.items())}, 'confusion': confusion.most_common(8),
            'playbook_n': len(pb_rows), 'playbook_accuracy': pb_ok / len(pb_rows) if pb_rows else None,
            'status': dict(statuses), 'avg_ms': sum(ms) / len(ms) if ms else 0}


def show(r):
    print(f"\n## {r['provider']}")
    print(f"Intake classification: {r['accuracy']:.1%} of {r['n']}  (" +
          ', '.join(f'{k} {v:.1%}' for k, v in sorted(r['by_lang'].items())) + f")  avg {r['avg_ms']:.0f} ms, status {r['status']}")
    if r['playbook_accuracy'] is not None:
        print(f"Playbook selection (top-1): {r['playbook_accuracy']:.1%} of {r['playbook_n']}")
    print('Per intent: ' + ', '.join(f'{k} {v}' for k, v in r['by_intent'].items()))
    if r['confusion']:
        print('Most frequent errors (expected → got): ' + '; '.join(f'{a} → {b} ×{n}' for (a, b), n in r['confusion']))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dataset', default=os.path.join(ROOT, 'tests', 'ai_eval', 'dataset.json'))
    ap.add_argument('--url', help='local inference server (Ollama / llama.cpp)')
    ap.add_argument('--model', help='model name on the local server')
    ap.add_argument('--api-style', default='ollama', choices=['ollama', 'openai_compat'])
    ap.add_argument('--embeddings', help='semantic service URL for embeddings (optional)')
    ap.add_argument('--db', action='store_true', help="use this installation's catalog and AI settings")
    ap.add_argument('--limit', type=int)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    data = json.load(open(a.dataset, encoding='utf-8'))
    intents, playbooks = seed.INTENTS, seed.PLAYBOOKS
    emb = LocalEmbeddings('semantic_service', url=a.embeddings) if a.embeddings else None
    runs = [('rules_only', RulesOnly(), emb)]
    ctx = None
    if a.db:
        from app import app
        ctx = app.app_context()
        ctx.push()
        from ai import catalog, settings
        catalog.ensure_seeded()
        intents, playbooks = catalog.intents(), catalog.playbooks()
        cfg = settings.get_config()
        emb = settings.embedder(cfg) or emb
        runs = [('rules_only', RulesOnly(), emb)]
        gen = settings.generator(cfg)
        if gen.can_generate:
            runs.append((f'local_http · {gen.model}', gen, emb))
    if a.url:
        runs.append((f'local_http · {a.model}', LocalHTTP(a.url, a.model, a.api_style, timeout=120), emb))
    out = [evaluate(n, g, e, intents, playbooks, data, a.limit) for n, g, e in runs]
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    else:
        print(f"Dataset: {len(data['intake'])} intake items, {len(data['playbooks'])} playbook situations "
              f"(synthetic, AR + EN); catalog: {len(intents)} intents, {len(playbooks)} playbooks")
        for r in out:
            show(r)
    if ctx:
        ctx.pop()


if __name__ == '__main__':
    main()
