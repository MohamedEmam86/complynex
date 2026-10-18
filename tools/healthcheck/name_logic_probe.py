#!/usr/bin/env python3
"""
Probe the name-matching logic against labelled pairs.

Each pair is tagged with the answer a compliance officer would give, and with
the specific reasoning step it tests. Scoring them through the engine's own
similarity path shows exactly which steps the engine performs and which it
does not.

The reasoning a human applies to an Arabic name, in order:
  1. ORTHOGRAPHY   ي/ى, ه/ة, أ/إ/ا are the same letter written differently
  2. COMPOUNDS     عبدالله and عبد الله are one name written two ways
  3. STRUCTURE     ism + father + grandfather + family; first and last carry
                   identity, middles are patronymics
  4. RARITY        محمد is noise (45% of names), عواجه is signal
  5. ORDER         names should align in sequence, not merely as a bag
  6. COVERAGE      how much of A is in B AND how much of B is in A
  7. PHONETICS     Arabic sounds, not English soundex
"""
import os
import sys

sys.path.insert(0, '/var/www/complynex')
os.chdir('/var/www/complynex')
from dotenv import load_dotenv
load_dotenv('/var/www/complynex/.env')

from rapidfuzz import fuzz
from screening.complynex_engine import (_distinctive_fuzzy,
                                        calculate_exact_match_boost,
                                        NON_DISTINCTIVE_NAME_TOKENS)
from screening.utils.normalization import normalize_arabic_text as N

try:
    import jellyfish
    HAVE_J = True
except Exception:
    HAVE_J = False

# (name A, name B, should_match, what it tests)
PAIRS = [
    # 1. ORTHOGRAPHY - same person, different letter forms
    ('حمدى محمد رمضان محمد', 'حمدي محمد رمضان محمد', True, 'orthography ى/ي'),
    ('سلامه بسيوني محمد', 'سلامة بسيوني محمد', True, 'orthography ه/ة'),
    ('احمد محمد', 'أحمد محمد', True, 'orthography أ/ا'),
    ('بيشوي القس ساويرس', 'بيشوى القس ساويرس', True, 'orthography ى/ي'),

    # 2. COMPOUND NAMES written joined vs separated
    ('محمود عبدالمنعم موسي احمد', 'محمود عبد المنعم موسى احمد', True,
     'compound عبدالمنعم / عبد المنعم'),
    ('عبدالله احمد سعيد', 'عبد الله احمد سعيد', True, 'compound عبدالله'),
    ('عبدالرحمن محمد على', 'عبد الرحمن محمد على', True, 'compound عبدالرحمن'),

    # 3. STRUCTURE - patronymic chains, short vs long form
    ('Osama Bin Laden', 'Usama Bin Muhammed Bin Awad Bin Laden', True,
     'short form vs full patronymic chain'),
    ('يوسف رفيق عبدالوهاب معوض البساطي', 'يوسف رفيق عبد الوهاب معوض', True,
     'truncated patronymic chain'),
    ('احمد محمد سعيد الغالى على', 'احمد محمد سعيد الغالي علي', True,
     'full name, orthography only'),

    # 4. RARITY - overlap on common tokens only = different people
    ('احمد صبره احمد عواجه', 'احمد احمد احمد', False,
     'overlap on common tokens only'),
    ('احمد نظمى محمد', 'احمد محمد احمد', False, 'common tokens only'),
    ('محمد علي حسن', 'محمد علي ابراهيم', False,
     'shares 2 common, differs on family name'),
    ('اشرف محمد احمد منصور', 'اشرف محمد احمد الصعيدي', False,
     'same first 3, DIFFERENT family name'),

    # 5. ORDER - reordered name is the same person
    ('Saddam Hussein', 'Hussein Saddam', True, 'reordered'),
    ('حسن محمود ابراهيم', 'ابراهيم محمود حسن', True, 'reordered Arabic'),

    # 6. FAMILY NAME is decisive
    ('محمد احمد الشربيني', 'محمد احمد الحفناوي', False,
     'same given names, different family'),
    ('سمير محمد عفيفي الكيلاني', 'سمير محمد عفيفي الكيلاني', True, 'identical'),

    # 7. PHONETIC / transliteration variants
    ('Mohamed Hassan', 'Muhammad Hasan', True, 'transliteration variants'),
    ('Gamal Abdel Nasser', 'Jamal Abd al-Nasir', True, 'transliteration g/j'),
]


def coverage(a, b):
    ta = {t for t in N(a).lower().split() if t}
    tb = {t for t in N(b).lower().split() if t}
    if not ta or not tb:
        return 0, 0
    inter = ta & tb
    return round(100 * len(inter) / len(ta)), round(100 * len(inter) / len(tb))


def distinctive_overlap(a, b):
    ta = {t for t in N(a).lower().split() if t}
    tb = {t for t in N(b).lower().split() if t}
    inter = ta & tb
    d = {t for t in inter if t not in NON_DISTINCTIVE_NAME_TOKENS}
    return len(d), sorted(d)[:3]


def last_token_match(a, b):
    na, nb = N(a).lower().split(), N(b).lower().split()
    if not na or not nb:
        return False
    return na[-1] == nb[-1]


print('%-38s %-38s %-5s %6s %6s %6s %7s %5s  %s'
      % ('NAME A', 'NAME B', 'ANS', 'fuzzy', 'sort', 'boost', 'cov A/B',
         'lastT', 'TESTS'))
print('-' * 165)

wrong = []
for a, b, should, what in PAIRS:
    na, nb = N(a), N(b)
    f = _distinctive_fuzzy(na.lower(), nb.lower())
    srt = fuzz.token_sort_ratio(na.lower(), nb.lower())
    boost = calculate_exact_match_boost(na.split(), nb.split())
    ca, cb = coverage(a, b)
    lt = last_token_match(a, b)
    nd, dtok = distinctive_overlap(a, b)
    # a crude verdict using only what the engine has today
    engine_like = f >= 85 or (f >= 70 and boost >= 15)
    ok = (engine_like == should)
    if not ok:
        wrong.append((a, b, should, engine_like, what, f, boost))
    print('%-38s %-38s %-5s %6.1f %6.1f %6.1f %4d/%-3d %5s  %s%s'
          % (a[:38], b[:38], 'SAME' if should else 'DIFF', f, srt, boost,
             ca, cb, 'Y' if lt else 'n', what,
             '   <== ENGINE WRONG' if not ok else ''))

print('\nmisjudged by the current logic: %d of %d' % (len(wrong), len(PAIRS)))
for a, b, should, got, what, f, boost in wrong:
    print('   %-34s vs %-34s want=%s got=%s  (fuzzy=%.1f boost=%.0f)  %s'
          % (a[:34], b[:34], 'SAME' if should else 'DIFF',
             'SAME' if got else 'DIFF', f, boost, what))

print('\n--- does normalisation handle compounds? ---')
for x, y in (('عبدالله', 'عبد الله'), ('عبدالمنعم', 'عبد المنعم'),
             ('عبدالرحمن', 'عبد الرحمن')):
    print('   %-12s -> %-14s   |   %-12s -> %-14s   equal after norm: %s'
          % (x, N(x), y, N(y), N(x) == N(y).replace(' ', '')))

print('\n--- is the phonetic step meaningful for Arabic? ---')
if HAVE_J:
    for s in ('محمد', 'أحمد', 'حسن', 'Mohamed', 'Muhammad'):
        try:
            print('   %-10s soundex=%-6s metaphone=%s'
                  % (s, jellyfish.soundex(s), jellyfish.metaphone(s)))
        except Exception as e:
            print('   %-10s ERROR %s' % (s, str(e)[:40]))
else:
    print('   jellyfish not importable here')
