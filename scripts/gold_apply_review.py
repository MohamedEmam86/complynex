#!/usr/bin/env python3
"""Apply the owner's Gold Set review decisions (2 Nov 2026) to the Gold Set — a reviewed step, never automatic.

Owner decision after reviewing the v1 sample (709 pairs, 39 marked "wrong"):
  * A first name ONE letter away from the listed first name (one substitution, insertion, deletion or
    adjacent swap: سامي / سامح، محمود / محمد، احمد / حامد) with every other element identical, in chains of
    3+ elements of the same script, is the same person for screening purposes: a LOW alert to review
    (possible typo in the customer data or in the list). Such pairs, wherever the builder put them as
    "different person", become positives in their own category (pos_lookalike_first_typo).
  * Siblings with a completely different first name and Latin names with a different surname stay
    different persons: those "wrong" review decisions are recorded as overruled by the owner.
  * The pair "Hussein Mohamed Mahmoud Abdellatif" / "الحسين محمد محمود عبد اللطيف" was mislabelled
    "different person": it is the same name (positive, cross_egyptian_latin).

The rule here is written independently of the matcher (only the shared tokeniser is used), so the
Gold Set keeps measuring the engine instead of copying it.

    python scripts/gold_apply_review.py                 # dry run (v1), prints what would change
    python scripts/gold_apply_review.py --apply         # backs up, then writes gold_v1.* files
    python scripts/gold_apply_review.py --version 2 --apply
"""
import argparse
import collections
import hashlib
import json
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from screening import match_intel as mi          # noqa: E402  (tokeniser / script test only)

GOLD_DIR = os.path.join(BASE, 'screening', 'data', 'gold')
DECIDED = '2026-11-02'
HUSSEIN = ('Hussein Mohamed Mahmoud Abdellatif', 'الحسين محمد محمود عبد اللطيف')
OVERRULED_NOTE = (f'owner decision {DECIDED}: siblings / different surnames stay different persons '
                  '(only a one-letter first-name difference with the rest identical is a low alert)')
CONFIRMED = '2026-11-07'
LOOKALIKE_NOTE = (f'owner decision {CONFIRMED}: any one-letter first-name difference with the rest identical '
                  'is a low alert (confirmed after seeing these pairs)')


def osa1(a, b):
    """True when a and b are one edit apart (substitution, insertion, deletion or adjacent swap)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    s, l = (a, b) if len(a) < len(b) else (b, a)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def lookalike_pair(query, listed):
    q, c = mi.tokens(query), mi.tokens(listed)
    if len(q) < 3 or len(q) != len(c) or q[1:] != c[1:] or q[0] == c[0]:
        return False
    if mi.is_arabic(q[0]) != mi.is_arabic(c[0]):
        return False
    if min(len(q[0]), len(c[0])) < (3 if mi.is_arabic(q[0]) else 4):
        return False
    return osa1(q[0], c[0])


def new_cat(p):
    t = p.get('tier', 'core')
    return 'pos_lookalike_first_typo' if t == 'core' else f'{t[:3]}_pos_lookalike_first_typo'


def load_jsonl(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path, rows):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def relabel(rows):
    changes = []
    for p in rows:
        if p['label'] == 0 and (p['query'], p['listed']) in (HUSSEIN, HUSSEIN[::-1]):
            changes.append((p['id'], p['cat'], 'cross_egyptian_latin', 'mislabelled: same name'))
            p.update({'label': 1, 'cat': 'cross_egyptian_latin', 'tier': 'core',
                      'note': (p.get('note') or '') + f' | relabelled {DECIDED}: same name (owner review)'})
        elif p['label'] == 0 and lookalike_pair(p['query'], p['listed']):
            cat = new_cat(p)
            changes.append((p['id'], p['cat'], cat, 'first name one letter away, rest identical'))
            p.update({'label': 1, 'cat': cat,
                      'note': (p.get('note') or '') + f" | was {p['cat']}; relabelled {DECIDED} (owner rule)"})
    return changes


def update_meta(version, rows, path):
    mp = os.path.join(GOLD_DIR, f'gold_v{version}.meta.json')
    meta = json.load(open(mp, encoding='utf-8'))
    by = collections.OrderedDict()
    for p in sorted(rows, key=lambda r: r['cat']):
        d = by.setdefault(p['cat'], {'label': p['label'], 'tier': p.get('tier', 'core'), 'n': 0, 'holdout': 0})
        d['n'] += 1
        d['holdout'] += bool(p.get('holdout'))
    meta.update({'pairs': len(rows), 'holdout': sum(1 for p in rows if p.get('holdout')), 'by_category': by,
                 'sha256': hashlib.sha256(open(path, 'rb').read()).hexdigest(),
                 'review_applied': DECIDED})
    write_json(mp, meta)
    return meta


def update_decisions(version, sample_by_id, changed_ids):
    dp = os.path.join(GOLD_DIR, f'gold_v{version}.review_decisions.json')
    if not os.path.exists(dp):
        return None
    doc = json.load(open(dp, encoding='utf-8'))
    n = collections.Counter()
    for rid, d in doc.get('decisions', {}).items():
        if d.get('decision') != 'wrong':
            continue
        if rid in changed_ids:
            d['decision'], n['applied'] = 'applied', n['applied'] + 1
            d['applied_at'] = DECIDED
        else:
            d['original_note'] = d.get('note', '')
            d['decision'], d['note'] = 'correct', OVERRULED_NOTE
            n['overruled'] += 1
    n['overruled_lookalike'] = overrule_lookalike(doc, sample_by_id)
    return dp, doc, n


def overrule_lookalike(doc, sample_by_id):
    """A 'correct' decision on a review pair that was relabelled from neg_lookalike_first to a look-alike
    positive is overruled by the owner (confirmed 7 Nov after seeing the pairs). Idempotent: a decision
    already overruled is no longer 'correct' and is left alone; the reviewer's note is kept."""
    n = 0
    for rid, d in doc.get('decisions', {}).items():
        p = sample_by_id.get(rid)
        if not p or d.get('decision') != 'correct' or not p['cat'].endswith('pos_lookalike_first_typo'):
            continue
        if 'neg_lookalike_first;' not in (p.get('note') or ''):
            continue
        d['original_note'] = d.get('note', '')
        d['decision'], d['note'], d['overruled_at'] = 'overruled', LOOKALIKE_NOTE, CONFIRMED
        n += 1
    return n


def fix_decisions(version, review, apply):
    """--fix-decisions on a copy where the relabel was already applied: bring the review decisions
    to the same final state a fresh --apply gives (additive, idempotent)."""
    dp = os.path.join(GOLD_DIR, f'gold_v{version}.review_decisions.json')
    if not os.path.exists(dp):
        print('no review decisions file - nothing to do')
        return
    doc = json.load(open(dp, encoding='utf-8'))
    n = overrule_lookalike(doc, {r['id']: r for r in review})
    kept = sum(1 for d in doc.get('decisions', {}).values() if d.get('note') == OVERRULED_NOTE)
    print(f'review decisions: {n} look-alike decisions to overrule; {kept} other overrides keep the {DECIDED} note')
    if not n:
        print('nothing to change')
        return
    if not apply:
        print('DRY RUN - nothing written (use --apply)')
        return
    ts = time.strftime('%Y%m%d_%H%M%S')
    bdir = os.path.join(GOLD_DIR, f'backup_before_fix_decisions_{ts}')
    os.makedirs(bdir)
    shutil.copy2(dp, bdir)
    write_json(dp, doc)
    print(f'APPLIED; backup in {bdir}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', type=int, default=1)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--fix-decisions', action='store_true',
                    help='relabel already applied: only bring the review decisions up to date')
    a = ap.parse_args()
    gp = os.path.join(GOLD_DIR, f'gold_v{a.version}.jsonl')
    rp = os.path.join(GOLD_DIR, f'gold_v{a.version}.review.jsonl')
    rows = load_jsonl(gp)
    review = load_jsonl(rp) if os.path.exists(rp) else []
    if any(p.get('note', '').find(f'relabelled {DECIDED}') >= 0 for p in rows):
        if a.fix_decisions:
            fix_decisions(a.version, review, a.apply)
        else:
            print('already applied - nothing to do (--fix-decisions brings the review decisions up to date)')
        return
    if a.fix_decisions:
        print('the relabel is not applied yet: run --apply instead (it also brings the review decisions up to date)')
        sys.exit(2)
    changes = relabel(rows)
    rchanges = relabel(review)
    changed_ids = {c[0] for c in changes} | {c[0] for c in rchanges}
    dec = update_decisions(a.version, {r['id']: r for r in review}, changed_ids)
    by = collections.Counter((c[1], c[2]) for c in changes)
    print(f'gold_v{a.version}: {len(changes)} pairs relabelled')
    for (f, t), n in sorted(by.items()):
        print(f'  {f:28s} -> {t:28s} {n}')
    print(f'review sample: {len(rchanges)} pairs relabelled')
    if dec:
        print(f"review decisions: {dict(dec[2])}")
    if not a.apply:
        print('DRY RUN - nothing written (use --apply)')
        return
    ts = time.strftime('%Y%m%d_%H%M%S')
    bdir = os.path.join(GOLD_DIR, f'backup_before_review_{ts}')
    os.makedirs(bdir)
    for f in os.listdir(GOLD_DIR):
        if f.startswith(f'gold_v{a.version}.'):
            shutil.copy2(os.path.join(GOLD_DIR, f), bdir)
    write_jsonl(gp, rows)
    if review:
        write_jsonl(rp, review)
    meta = update_meta(a.version, rows, gp)
    if dec:
        dp, doc, _ = dec
        write_json(dp, doc)
    log = {'applied_at': ts, 'version': a.version, 'decision': DECIDED, 'pairs': len(changes),
           'changes': [{'id': i, 'from': f, 'to': t, 'why': w} for i, f, t, w in changes],
           'new_sha256': meta['sha256'], 'backup': bdir}
    write_json(os.path.join(GOLD_DIR, f'gold_v{a.version}.review_applied_{ts}.json'), log)
    print(f'APPLIED; backup in {bdir}; new sha256 {meta["sha256"][:12]}…')
    print('next: gold_set_eval.py --write-baseline with the code in force, then deploy the new code')


if __name__ == '__main__':
    main()
