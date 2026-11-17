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
Vessel identifiers and names (vessel screening, V1).

IMO number   7 digits; the last digit is a check digit (weights 7-6-5-4-3-2 on the first six,
             sum mod 10). It is the ship's permanent number: names, flags, MMSI and call signs change.
MMSI         9 digits; a ship station starts with a Maritime Identification Digit 2-7.
Names        ship names are compared without their prefixes (M/V, MT, ...), and every number in a
             name must be the same on both sides: STAR 1 and STAR 2 are two ships.
"""
import hashlib
import re
import unicodedata

_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')

# words in front of (or behind) a ship name that are not part of the name
_PREFIXES = {'MV', 'MT', 'MY', 'SS', 'FV', 'MS', 'MSV', 'LNG', 'LPG', 'RV', 'TS', 'SV', 'HMS'}
_FILLER = {'VESSEL', 'SHIP', 'TANKER', 'THE', 'M', 'V', 'T'}
_AR_FILLER = {'سفينه', 'سفينة', 'الناقله', 'الناقلة', 'ناقله', 'ناقلة', 'السفينه', 'السفينة', 'باخره', 'باخرة',
              'الباخره', 'الباخرة'}

_ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10,
          'XI': 11, 'XII': 12, 'XIII': 13, 'XIV': 14, 'XV': 15, 'XVI': 16, 'XVII': 17, 'XVIII': 18,
          'XIX': 19, 'XX': 20}


def digits_only(v):
    return re.sub(r'\D', '', str(v or '').translate(_DIGITS))


def norm_imo(v):
    """'IMO 9004700' / 'IMO: 9004700' / '9004700' -> '9004700'; anything that is not 7 digits -> None."""
    d = digits_only(v)
    return d if len(d) == 7 else None


def imo_valid(v):
    """True when the 7-digit IMO ship number passes its check digit."""
    d = norm_imo(v)
    if not d:
        return False
    s = sum(int(d[i]) * (7 - i) for i in range(6))
    return s % 10 == int(d[6])


def norm_mmsi(v):
    d = digits_only(v)
    return d if len(d) == 9 else None


def mmsi_valid(v):
    d = norm_mmsi(v)
    return bool(d) and d[0] in '234567'


def norm_call_sign(v):
    s = re.sub(r'[^A-Z0-9]', '', str(v or '').upper().translate(_DIGITS))
    return s or None


def _strip_accents(s):
    return ''.join(ch for ch in unicodedata.normalize('NFKD', s) if not unicodedata.combining(ch))


def is_arabic(s):
    return any('؀' <= ch <= 'ۿ' for ch in str(s or ''))


def norm_name(name):
    """Upper-case Latin (or normalised Arabic) ship name without prefixes, punctuation and filler words.
    'M/V "Ocean Star-1"' -> 'OCEAN STAR 1'."""
    s = str(name or '').translate(_DIGITS)
    if is_arabic(s):
        s = re.sub('[ً-ٰٟـ]', '', s)          # diacritics, tatweel
        s = s.translate(str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ة': 'ه'}))
        s = re.sub(r'[^\w\s]', ' ', s)
        toks = [t for t in s.split() if t not in _AR_FILLER]
        return ' '.join(toks)
    s = _strip_accents(s).upper()
    s = re.sub(r'\b([A-Z])[/.]([A-Z])\b\.?', r'\1\2', s)         # M/V, M.V. -> MV
    s = re.sub(r'(?<=[A-Z])-(?=\d)|(?<=\d)-(?=[A-Z])', ' ', s)    # STAR-1 -> STAR 1
    s = re.sub(r'(?<=[A-Z])(?=\d)|(?<=\d)(?=[A-Z])', ' ', s)      # STAR1 -> STAR 1
    s = re.sub(r"[^A-Z0-9 ]", ' ', s)
    toks = s.split()
    while toks and (toks[0] in _PREFIXES or toks[0] in _FILLER):
        toks.pop(0)
    while len(toks) > 1 and toks[-1] in _FILLER:
        toks.pop()
    return ' '.join(toks)


def name_numbers(norm):
    """The numbers in a normalised name, Roman numerals included (II = 2), as a sorted tuple."""
    out = []
    for t in str(norm or '').split():
        if t.isdigit():
            out.append(int(t))
        elif t in _ROMAN and len(t) > 1:      # II, III, IV ... (a lone I / V / X stays a letter)
            out.append(_ROMAN[t])
    return tuple(sorted(out))


def name_words(norm):
    """The non-number words of a normalised name."""
    return [t for t in str(norm or '').split() if not t.isdigit() and not (t in _ROMAN and len(t) > 1)]


def clean_flag(v):
    s = re.sub(r'\s+', ' ', str(v or '').strip())
    s = re.sub(r'^(flag of|flag)\s*:?\s*', '', s, flags=re.I)
    return s or None


def fingerprint(*parts):
    """Stable short hash of a vessel identity (used to re-open a cleared hit when it changes)."""
    blob = '|'.join(str(p or '').strip().upper() for p in parts)
    return hashlib.sha1(blob.encode('utf-8')).hexdigest()


def query_key(name=None, imo=None, mmsi=None, flag=None):
    """What a cleared decision is tied to on the query side: the IMO when given, else name + flag."""
    i = norm_imo(imo)
    if i:
        return 'IMO:' + i
    m = norm_mmsi(mmsi)
    if m:
        return 'MMSI:' + m
    return 'NAME:' + norm_name(name) + '|' + (clean_flag(flag) or '').upper()
