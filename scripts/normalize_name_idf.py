#!/usr/bin/env python3
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
"""Re-key the name rarity table (screening/data/name_idf.json) to the elements the matcher actually looks up.

The table was counted on raw name elements (السيد, عبدالرحمن, abdallah, Mostapha ...), but the matcher asks
for normalised elements (سيد after the article is removed, رحمن after عبد, alah, mostafa ...). A lookup that
misses reads as "rare" (default weight), so the commonest family names and the second part of every Abd-
compound counted as highly identifying.

This script needs no customer data: the table stores idf = ln(total / count), so each count is recovered,
summed per normalised element and turned back into a weight. Original keys are kept; normalised keys are
added or replaced. Run after any change to match_intel.normalize / tokens.

    python scripts/normalize_name_idf.py            # writes screening/data/name_idf.json (backup kept)
    python scripts/normalize_name_idf.py --dry-run  # report only
"""
import collections
import json
import math
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from screening.match_intel import tokens  # noqa: E402

PATH = os.path.join(BASE, 'screening', 'data', 'name_idf.json')


def main():
    dry = '--dry-run' in sys.argv
    with open(PATH, encoding='utf-8') as f:
        blob = json.load(f)
    total = int(blob['total_names'])
    raw = blob.get('raw_idf') or blob['idf']           # always start from the original counts (idempotent)
    counts = collections.Counter()
    for key, idf in raw.items():
        c = total * math.exp(-float(idf))
        for tok in set(tokens(key)):
            counts[tok] += c
    table = dict(raw)
    changed = 0
    for tok, c in counts.items():
        w = round(math.log(total / min(max(c, 1e-9), total)), 4)
        if table.get(tok) != w:
            changed += 1
        table[tok] = w
    print(f'raw keys: {len(raw):,}  normalised elements: {len(counts):,}  keys added / re-weighted: {changed:,}')
    if dry:
        return
    out = dict(blob, idf=table, raw_idf=raw, normalised_at=time.strftime('%Y-%m-%d %H:%M:%S'))
    shutil.copy2(PATH, PATH + '.bak')
    tmp = PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, PATH)
    print(f'written {PATH} (previous file kept as name_idf.json.bak)')


if __name__ == '__main__':
    main()
