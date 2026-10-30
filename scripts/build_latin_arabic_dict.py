#!/usr/bin/env python3
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
"""Learn how Arabic name elements are written in Latin script, from records
that carry both forms: official sanctions lists (OFAC, UN, EU, OpenSanctions
— real-world transliterations) and the internal lists (original Arabic name +
its transliterations). Output: screening/data/latin_arabic_dict.json

    {"mohamed": [["محمد", 5120], ["محمود", 3]], ...}

Only single name ELEMENTS are stored (counts per element pair), never full
names. Rebuilt weekly so new list data keeps improving it.
"""
import collections
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
import psycopg2  # noqa: E402
from config import Config  # noqa: E402
from screening.match_intel import tokens, is_arabic, _as_list, _uncomma, loose_ratio  # noqa: E402


def _plausible(lat, ar):
    """Could these two elements be the same name? Their consonant skeletons, with the sounds languages write
    differently merged (match_intel.loose_ratio), must be at least half alike. Keeps misaligned pairs (a list
    writing 'SURNAME Given' against an Arabic 'Given Surname') out of the dictionary: they taught it that
    SVYATENKO is يننا."""
    return loose_ratio(lat, ar) >= 0.5

OUT = os.path.join(BASE, 'screening', 'data', 'latin_arabic_dict.json')


def main():
    pairs = collections.defaultdict(collections.Counter)
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor('pairs')
    cur.itersize = 5000

    def learn(ar_name, lat_name, w=1):
        a, l = tokens(ar_name), tokens(_uncomma(lat_name))
        if not a or len(a) != len(l) or len(a) > 7:
            return
        # the Latin form may put the surname first: take the order in which most elements agree
        orders = [l] + ([l[1:] + l[:1], l[-1:] + l[:-1]] if len(l) > 1 else [])
        best = max(orders, key=lambda o: sum(_plausible(x, y) for x, y in zip(o, a)))
        for x, y in zip(best, a):
            if len(x) >= 2 and len(y) >= 2 and not is_arabic(x) and is_arabic(y) and _plausible(x, y):
                pairs[x][y] += w

    cur.execute("""SELECT full_name_arabic, full_name, aliases FROM screening_watchlist
                   WHERE is_active = 1 AND full_name_arabic ~ '[ء-ي]'
                     AND source NOT IN ('internal_blacklist', 'internal_pep')""")
    n = 0
    for ar, lat, aliases in cur:
        n += 1
        if lat and not is_arabic(lat):
            learn(ar, lat, 3)                       # official transliteration: strongest
        for al in _as_list(aliases)[:20]:
            if al and not is_arabic(al):
                learn(ar, al, 1)
    cur.close()
    cur = conn.cursor('internal')
    cur.itersize = 5000
    cur.execute("SELECT original_name, full_name, aliases FROM internal_blacklist WHERE original_name ~ '[ء-ي]'")
    for ar, lat, aliases in cur:
        n += 1
        if lat and not is_arabic(lat):
            learn(ar, lat, 1)
        for al in _as_list(aliases)[:30]:
            if al and not is_arabic(al):
                learn(ar, al, 1)
    out = {}
    for lat, c in pairs.items():
        total = sum(c.values())
        top = [[a, k] for a, k in c.most_common(6) if k >= 2 and k / total >= 0.03]
        if top:
            out[lat] = top
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, OUT)
    print(f'records read: {n:,}  latin elements learned: {len(out):,}  -> {OUT}')


if __name__ == '__main__':
    main()
