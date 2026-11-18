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
_TRAILING_FILLER = {'VESSEL', 'SHIP', 'TANKER'}      # a trailing V / X / I is a hull number, not filler
_AR_FILLER = {'سفينه', 'الناقله', 'ناقله', 'السفينه', 'باخره', 'الباخره', 'المركب', 'مركب',
              'يخت', 'اليخت', 'قاطره', 'القاطره', 'صهريج', 'النفط', 'البضائع', 'الحاويات', 'نفط', 'بضائع'}
# Arabic ship prefixes: م/ن (motor ship), ن/م, س/ن, م.ن ... become one-letter tokens after punctuation removal
_AR_PREFIX_LETTERS = {'م', 'ن', 'س', 'ب', 'ي', 'ق', 'ص', 'ك'}

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


_CS_LABEL = re.compile(r'^\s*(?:C\s*/\s*S|C\.\s*S\.|CALL\s*-?\s*SIGN|CS\s*[:#])\s*[:#.-]?\s*', re.I)


def norm_call_sign(v):
    """'C/S 3E2333', 'Call sign: 3E2333' -> '3E2333' (a bare 'CS...' is kept: real call signs start with CS)."""
    s = _CS_LABEL.sub('', str(v or '').translate(_DIGITS))
    s = re.sub(r'[^A-Z0-9]', '', s.upper())
    return s or None


def imo_neighbours(v):
    """Valid IMO numbers one keying error away from an IMO that fails its check digit: one digit changed,
    or two adjacent digits swapped. Used to point a mistyped IMO to a listed ship for review."""
    d = norm_imo(v)
    if not d or imo_valid(d):
        return []
    out = set()
    for i in range(7):
        for c in '0123456789':
            if c != d[i]:
                x = d[:i] + c + d[i + 1:]
                if imo_valid(x):
                    out.add(x)
    for i in range(6):
        x = d[:i] + d[i + 1] + d[i] + d[i + 2:]
        if x != d and imo_valid(x):
            out.add(x)
    return sorted(out)


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
        s = re.sub(r'(?<=[\u0600-\u06ff])(?=\d)|(?<=\d)(?=[\u0600-\u06ff])', ' ', s)
        toks = s.split()
        # leading descriptors ('السفينة', 'ناقلة النفط') and one-letter prefixes (م/ن, ن/م ...) are not the name
        while len(toks) > 1 and (toks[0] in _AR_FILLER or toks[0] in _AR_PREFIX_LETTERS or toks[0] in _PREFIXES):
            toks.pop(0)
        out = ' '.join(toks)
        if not is_arabic(out):          # an Arabic prefix in front of a Latin name ('ناقلة Zal Pars 3')
            return norm_name(out)
        return out
    s = _strip_accents(s).upper()
    s = re.sub(r'\b([A-Z])[/.]([A-Z])\b\.?', r'\1\2', s)         # M/V, M.V. -> MV
    s = re.sub(r'(?<=[A-Z])-(?=\d)|(?<=\d)-(?=[A-Z])', ' ', s)    # STAR-1 -> STAR 1
    s = re.sub(r'(?<=[A-Z])(?=\d)|(?<=\d)(?=[A-Z])', ' ', s)      # STAR1 -> STAR 1
    s = re.sub(r"[^A-Z0-9 ]", ' ', s)
    toks = s.split()
    while toks and (toks[0] in _PREFIXES or toks[0] in _FILLER):
        toks.pop(0)
    while len(toks) > 1 and toks[-1] in _TRAILING_FILLER:
        toks.pop()
    return ' '.join(toks)


def name_numbers(norm):
    """The numbers in a normalised name, Roman numerals included (II = 2), as a sorted tuple."""
    out = []
    toks = str(norm or '').split()
    for i, t in enumerate(toks):
        if t.isdigit():
            out.append(int(t))
        elif t in _ROMAN and (len(t) > 1 or (i == len(toks) - 1 and i > 0)):
            # II, III, IV ...; a lone I / V / X counts only as the last word after a name (PROGRESS V)
            out.append(_ROMAN[t])
    return tuple(sorted(out))


def _is_numeral(t, i, n):
    return t.isdigit() or (t in _ROMAN and (len(t) > 1 or (i == n - 1 and i > 0)))


def name_words(norm):
    """The non-number words of a normalised name."""
    toks = str(norm or '').split()
    return [t for i, t in enumerate(toks) if not _is_numeral(t, i, len(toks))]


def clean_flag(v):
    """One spelling per flag state ('pa', 'PANAMA', 'بنما' -> 'Panama'); unknown text kept as written."""
    s = re.sub(r'\s+', ' ', str(v or '').strip())
    s = re.sub(r'^(flag of|flag)\s*:?\s*', '', s, flags=re.I)
    if not s:
        return None
    from screening.vessel_flags import canonical
    return canonical(s)


def flag_code(v):
    from screening.vessel_flags import iso2
    return iso2(v)


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
