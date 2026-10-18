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
Text helpers for the deterministic (rules_only) path: Arabic/English
normalisation, tokens, character n-gram vectors, and field extractors
(dates, amounts, identifiers, contact details). Pure functions.
"""

import math
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta

_AR = [('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ة', 'ه'), ('ى', 'ي'), ('ؤ', 'و'), ('ئ', 'ي')]
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_STOP = set('''the a an of to and or in on for with is are be this that at by from as it its our your we you
please kindly dear regards hello hi re fw fwd subject
في من على الى إلى عن مع هذا هذه ذلك التي الذي الذين و او أو ان أن تم يتم برجاء رجاء السادة السيد السيدة
'''.split())


def normalise(s):
    s = unicodedata.normalize('NFKC', s or '').lower().translate(_DIGITS)
    for a, b in _AR:
        s = s.replace(a, b)
    s = re.sub(r'[ً-ْـ]', '', s)          # harakat and tatweel
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', s)).strip()


def _strip_al(t):
    return t[2:] if t.startswith('ال') and len(t) > 4 else t


def tokens(s):
    return [_strip_al(t) for t in normalise(s).split() if t not in _STOP and len(t) > 1]


def ngrams(s, n=3):
    """Character n-gram bag over normalised words (robust to Arabic morphology and typos)."""
    out = Counter()
    for w in tokens(s):
        w = f' {w} '
        for i in range(max(1, len(w) - n + 1)):
            out[w[i:i + n]] += 1
    return out


def cosine(a, b):
    if not a or not b:
        return 0.0
    num = sum(v * b.get(k, 0) for k, v in a.items())
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def keyword_hits(text, keywords):
    """Keywords (single words or phrases, any language) present in the text, after normalisation."""
    nt = f' {normalise(text)} '
    toks = set(tokens(text))
    hits = []
    for k in keywords or []:
        nk = normalise(k)
        if not nk:
            continue
        if ' ' in nk:
            if f' {nk} ' in nt:
                hits.append(k)
        elif _strip_al(nk) in toks or any(t.startswith(_strip_al(nk)) and len(nk) >= 4 for t in toks):
            hits.append(k)
    return hits


# --------------------------------------------------------------------------
# Field extractors
# --------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
_AR_MONTHS = {'يناير': 1, 'فبراير': 2, 'مارس': 3, 'ابريل': 4, 'أبريل': 4, 'مايو': 5, 'يونيو': 6, 'يوليو': 7,
              'اغسطس': 8, 'أغسطس': 8, 'سبتمبر': 9, 'اكتوبر': 10, 'أكتوبر': 10, 'نوفمبر': 11, 'ديسمبر': 12}


def _mk(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def dates_pos(text):
    """[(date, start_index)] in the digit-normalised text."""
    t = (text or '').translate(_DIGITS)
    out = []
    for m in re.finditer(r'\b(20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})\b', t):
        out.append((_mk(m.group(1), m.group(2), m.group(3)), m.start()))
    for m in re.finditer(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d\d)\b', t):
        out.append((_mk(m.group(3), m.group(2), m.group(1)), m.start()))
    for m in re.finditer(r'\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(20\d\d)\b', t):
        if m.group(2)[:3].lower() in _MONTHS:
            out.append((_mk(m.group(3), _MONTHS[m.group(2)[:3].lower()], m.group(1)), m.start()))
    for m in re.finditer(r'(\d{1,2})\s+(' + '|'.join(_AR_MONTHS) + r')\s+(20\d\d)', t):
        out.append((_mk(m.group(3), _AR_MONTHS[m.group(2)], m.group(1)), m.start()))
    return sorted([(d, i) for d, i in out if d], key=lambda x: x[1])


def dates(text):
    t = (text or '').translate(_DIGITS)
    out = []
    for y, m, d in re.findall(r'\b(20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})\b', t):
        out.append(_mk(y, m, d))
    for d, m, y in re.findall(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d\d)\b', t):
        out.append(_mk(y, m, d))
    for d, mon, y in re.findall(r'\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(20\d\d)\b', t):
        if mon[:3].lower() in _MONTHS:
            out.append(_mk(y, _MONTHS[mon[:3].lower()], d))
    for d, mon, y in re.findall(r'(\d{1,2})\s+(' + '|'.join(_AR_MONTHS) + r')\s+(20\d\d)', t):
        out.append(_mk(y, _AR_MONTHS[mon], d))
    seen, res = set(), []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            res.append(x)
    return res


def amounts(text):
    """Amounts with an Egyptian / common currency marker. Returns [(value, currency)]."""
    t = (text or '').translate(_DIGITS)
    out = []
    pat = r'(?:(EGP|USD|EUR|LE|L\.E\.?|جنيه|جم|دولار|يورو)\s*)?(\d{1,3}(?:[,٬]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(مليون|million|m\b|ألف|الف|k\b)?\s*(EGP|USD|EUR|LE|L\.E\.?|جنيه(?: مصري)?|جم|دولار|يورو)?'
    for pre, num, mult, post in re.findall(pat, t, re.I):
        cur = (pre or post or '').strip()
        if not cur:
            continue
        v = float(num.replace(',', '').replace('٬', ''))
        if mult.lower() in ('مليون', 'million', 'm'):
            v *= 1_000_000
        elif mult.lower() in ('ألف', 'الف', 'k'):
            v *= 1000
        c = 'USD' if cur.lower() in ('usd', 'دولار') else 'EUR' if cur.lower() in ('eur', 'يورو') else 'EGP'
        out.append((v, c))
    return out


def identifiers(text):
    t = (text or '').translate(_DIGITS)
    return {
        'national_id': re.findall(r'(?<!\d)[23]\d{13}(?!\d)', t),          # Egyptian national ID: 14 digits
        'email': re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', t),
        'phone': re.findall(r'(?<!\d)(?:\+?20|0)1[0125]\d{8}(?!\d)', t),  # Egyptian mobile
        'reference': [x for x in re.findall(r'\b(?:ref|reference|no|رقم|مرجع)\b\.?\s*[:#]?\s*([A-Z0-9][A-Z0-9/\-]{2,30})', t, re.I)
                      if any(c.isdigit() for c in x)],
        'iban': re.findall(r'\bEG\d{27}\b', t),
    }


def relative_deadline(text, today=None):
    """'within 3 days' / 'خلال ٥ أيام' / 'within 24 hours' → a date."""
    today = today or date.today()
    t = normalise(text)
    m = re.search(r'(?:within|خلال|في غضون)\s+(\d{1,3})\s*(hours?|ساعه|ساعات|days?|يوم|ايام|business days|ايام عمل|weeks?|اسبوع|اسابيع)', t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if unit.startswith('hour') or unit.startswith('ساع'):
        return today + timedelta(days=max(0, (n + 23) // 24))
    if unit.startswith('week') or unit.startswith('اسب'):
        return today + timedelta(weeks=n)
    return today + timedelta(days=n)


def excerpt(text, n=280):
    s = re.sub(r'\s+', ' ', text or '').strip()
    return s if len(s) <= n else s[:n - 1] + '…'
