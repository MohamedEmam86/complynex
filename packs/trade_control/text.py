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
"""Text handling for dual-use goods search (pure functions, no database).

Arabic and English normalisation, light stemming, recognition of control codes,
HS codes, CAS numbers and model numbers, and unit normalisation so that a query
value ("10 GHz") can be compared with a control threshold ("> 8 GHz").
"""
import re
import unicodedata

# ---------------------------------------------------------------- Arabic
_AR_DIAC = re.compile('[ؐ-ًؚ-ٰٟۖ-ۭـ]')   # harakat, tatweel
_AR_MAP = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ى': 'ي', 'ئ': 'ي', 'ؤ': 'و', 'ة': 'ه',
                         'گ': 'ك', 'ک': 'ك', 'ی': 'ي', 'ڤ': 'ف', 'پ': 'ب', 'چ': 'ج',
                         '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4', '٥': '5', '٦': '6', '٧': '7',
                         '٨': '8', '٩': '9', '٫': '.', '٬': ',', '،': ',', '؛': ';', '؟': '?'})
_AR_PREFIXES = ('وبال', 'وال', 'بال', 'كال', 'فال', 'لل', 'ال', 'و', 'ب', 'ل', 'ف', 'ك')
_AR_SUFFIXES = ('يات', 'ات', 'ون', 'ين', 'ان', 'ها', 'هم', 'يه', 'يه', 'ه', 'ي')
AR_STOP = {'في', 'من', 'الى', 'علي', 'عن', 'او', 'و', 'مع', 'ذو', 'ذات', 'هذا', 'هذه', 'التي', 'الذي', 'ان',
           'لا', 'ما', 'كل', 'اي', 'بها', 'به', 'لها', 'له', 'غير', 'تلك', 'ذلك', 'عند', 'حتي', 'اكثر', 'اقل'}
EN_STOP = {'a', 'an', 'the', 'of', 'for', 'and', 'or', 'with', 'in', 'on', 'to', 'by', 'as', 'at', 'from', 'than',
           'that', 'which', 'any', 'all', 'is', 'are', 'be', 'having', 'not', 'other', 'following', 'specially',
           'designed', 'specified', 'see', 'note', 'notes', 'including', 'used', 'use', 'such', 'their', 'its',
           'this', 'these', 'those', 'into', 'per', 'more', 'less', 'equal', 'greater', 'exceeding', 'but'}


def is_arabic(s):
    return bool(re.search('[؀-ۿ]', s or ''))


def norm_ar(s):
    s = _AR_DIAC.sub('', s or '')
    return s.translate(_AR_MAP)


def stem_ar(t):
    """Light stemmer: strips one common prefix and one common suffix, keeps at least 3 letters."""
    for p in _AR_PREFIXES:
        if t.startswith(p) and len(t) - len(p) >= 3:
            t = t[len(p):]
            break
    for s in _AR_SUFFIXES:
        if t.endswith(s) and len(t) - len(s) >= 3:
            t = t[:-len(s)]
            break
    return t


def stem_en(t):
    """Very light English stemmer: plural and common verb endings only (precision first)."""
    if len(t) <= 3 or t.isdigit():
        return t
    if t.endswith(('ss', 'us', 'is')):
        return t
    for suf, rep in (('ies', 'y'), ('sses', 'ss'), ('xes', 'x'), ('ches', 'ch'), ('shes', 'sh'),
                     ('ing', ''), ('ed', ''), ('es', 'e'), ('s', '')):
        if not t.endswith(suf) or len(t) - len(suf) < 3:
            continue
        if suf == 'ing' and len(t) < 6:
            continue
        if suf == 'ed' and t[-3] == 'e':          # speed, feed, need
            continue
        return t[:-len(suf)] + rep
    return t


def fold(s):
    """Lower case, strip Latin accents, unify Arabic letters and digits."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c) or is_arabic(c))
    return norm_ar(s).lower().replace('µ', 'µ').replace('μ', 'µ')


_TOKEN = re.compile(r'[a-z0-9µ]+(?:[.\-/][a-z0-9µ]+)*|[ء-ي0-9]+')


def tokens(s, stem=True, keep_stop=False):
    """[(token, lang)] after folding; lang is 'ar' or 'en'. Codes keep their dots."""
    out = []
    for t in _TOKEN.findall(fold(s)):
        if is_arabic(t):
            if not keep_stop and t in AR_STOP:
                continue
            out.append((stem_ar(t) if stem else t, 'ar'))
        else:
            if not keep_stop and t in EN_STOP:
                continue
            if '.' in t or '-' in t or '/' in t:
                out.append((t, 'en'))
                # also the pieces, so "5a002.a" finds "5a002" text and "high-speed" finds "speed"
                for p in re.split(r'[.\-/]', t):
                    if p and p not in EN_STOP and len(p) > 1:
                        out.append((stem_en(p) if stem else p, 'en'))
            else:
                out.append((stem_en(t) if stem else t, 'en'))
    return out


# ---------------------------------------------------------------- identifiers
CONTROL_CODE = re.compile(r'^(\d[a-e]\d{3})((?:\.[a-z0-9]{1,3})*)\.?$', re.I)
CAS_RE = re.compile(r'\b(\d{2,7})-(\d{2})-(\d)\b')
HS_RE = re.compile(r'^\d{2}(?:[.\s]?\d{2}){1,4}$')


def control_code(q):
    """'5a002 a 1' / '5A002.a.1' -> '5A002.a.1' or None."""
    q = re.sub(r'\s+', '.', (q or '').strip()).strip('.')
    m = CONTROL_CODE.match(q)
    if not m:
        return None
    head, rest = m.groups()
    return head[0] + head[1].upper() + head[2:] + rest.lower()


def cas_valid(cas):
    m = re.fullmatch(r'(\d{2,7})-(\d{2})-(\d)', (cas or '').strip())
    if not m:
        return False
    digits = (m.group(1) + m.group(2))[::-1]
    return sum((i + 1) * int(d) for i, d in enumerate(digits)) % 10 == int(m.group(3))


def find_cas(s):
    return ['%s-%s-%s' % m.groups() for m in CAS_RE.finditer(s or '')]


def hs_digits(q):
    """HS / CN / tariff code -> digits only (4 to 10 digits) or None."""
    q = (q or '').strip()
    if not q or not HS_RE.match(q.replace('-', '.')):
        return None
    d = re.sub(r'\D', '', q)
    return d if 4 <= len(d) <= 10 else None


def looks_like_model(t):
    """A product / model number: letters and digits mixed, no spaces (e.g. XC7K325T, DS-2CD2143)."""
    t = (t or '').strip()
    return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9\-_/.]{2,30}', t)) and bool(re.search(r'\d', t)) \
        and bool(re.search(r'[A-Za-z]', t)) and not CONTROL_CODE.match(t)


# ---------------------------------------------------------------- units
_PREFIX = {'T': 1e12, 'G': 1e9, 'M': 1e6, 'k': 1e3, '': 1.0, 'm': 1e-3, 'µ': 1e-6, 'n': 1e-9, 'p': 1e-12, 'f': 1e-15}
UNIT_TABLE = {}
for base, names in (('Hz', ['Hz']), ('W', ['W']), ('V', ['V']), ('A', ['A']), ('J', ['J']), ('eV', ['eV']),
                    ('Pa', ['Pa']), ('s', ['s']), ('m', ['m']), ('g', ['g'])):
    for p, f in _PREFIX.items():
        for n in names:
            UNIT_TABLE[p + n] = (base, f)
UNIT_TABLE.update({'bar': ('Pa', 1e5), 'psi': ('Pa', 6894.757), 'min': ('s', 60.0), 'h': ('s', 3600.0),
                   't': ('g', 1e6), 'tonnes': ('g', 1e6), 'Gbit/s': ('bit/s', 1e9), 'Mbit/s': ('bit/s', 1e6),
                   'kbit/s': ('bit/s', 1e3), 'bit/s': ('bit/s', 1.0), 'bit': ('bit', 1.0), 'bits': ('bit', 1.0),
                   'TB': ('byte', 1e12), 'GB': ('byte', 1e9), 'MB': ('byte', 1e6), 'kB': ('byte', 1e3),
                   'byte': ('byte', 1.0), 'Gbyte': ('byte', 1e9), 'Mbyte': ('byte', 1e6), 'kbyte': ('byte', 1e3),
                   '%': ('%', 1.0), 'K': ('K', 1.0), '°C': ('°C', 1.0), 'rpm': ('rpm', 1.0), 'dB': ('dB', 1.0),
                   'dBm': ('dBm', 1.0), 'km/h': ('m/s', 1 / 3.6), 'm/s': ('m/s', 1.0), 'mm/s': ('m/s', 1e-3),
                   'TFLOPS': ('FLOPS', 1e12), 'GFLOPS': ('FLOPS', 1e9), 'FLOPS': ('FLOPS', 1.0),
                   'TOPS': ('OPS', 1e12), 'TeraFLOPS': ('FLOPS', 1e12), 'TeraOPS': ('OPS', 1e12),
                   'Weighted TeraFLOPS': ('WT', 1.0), 'Weighted TeraOPS': ('WT', 1.0), 'channels': ('channels', 1.0),
                   'axes': ('axes', 1.0), 'Mach': ('Mach', 1.0), 'Gy': ('Gy', 1.0), 'Bq': ('Bq', 1.0)})
# Arabic unit words a user may type
AR_UNITS = {'جيجاهرتز': 'GHz', 'ميجاهرتز': 'MHz', 'كيلوهرتز': 'kHz', 'هرتز': 'Hz', 'كيلوواط': 'kW',
            'ميجاواط': 'MW', 'واط': 'W', 'فولت': 'V', 'كيلوفولت': 'kV', 'امبير': 'A', 'ملم': 'mm', 'مم': 'mm',
            'ميكرون': 'µm', 'ميكرومتر': 'µm', 'نانومتر': 'nm', 'سم': 'cm', 'متر': 'm', 'كم': 'km', 'كجم': 'kg',
            'كيلوجرام': 'kg', 'جرام': 'g', 'طن': 't', 'بار': 'bar', 'ميجاباسكال': 'MPa', 'باسكال': 'Pa',
            'ثانيه': 's', 'دقيقه': 'min', 'ساعه': 'h', 'بت': 'bit', 'بايت': 'byte', 'درجه': '°C'}
_UNIT_KEYS = sorted(UNIT_TABLE, key=len, reverse=True)
# a user typing in lower case means the usual unit (10 mhz = 10 MHz, 5 mw = 5 mW is rare in trade text)
_LOWER_PREF = {'mw': 'MW', 'mhz': 'MHz', 'mpa': 'MPa', 'mm': 'mm', 'ms': 'ms', 'mv': 'mV', 'ma': 'mA',
               'gb': 'GB', 'mb': 'MB', 'tb': 'TB', 'kb': 'kB', 'ghz': 'GHz', 'khz': 'kHz', 'kw': 'kW', 'kv': 'kV',
               'gw': 'GW', 'thz': 'THz', 'mg': 'mg', 'kg': 'kg', 'ns': 'ns', 'ps': 'ps', 'nm': 'nm', 'pa': 'Pa',
               'gpa': 'GPa', 'kpa': 'kPa', 'hz': 'Hz', 'w': 'W', 'v': 'V', 'a': 'A', 's': 's', 'm': 'm', 'g': 'g'}
_QV = re.compile(r'(\d+(?:[.,]\d+)?)\s*(' + '|'.join(re.escape(u) for u in _UNIT_KEYS) + r')(?![A-Za-z])', re.I)


def _unit_key(u):
    u = (u or '').strip().replace('μ', 'µ')
    u = AR_UNITS.get(norm_ar(u), u)
    if u in UNIT_TABLE:
        return u
    if u.lower() in _LOWER_PREF:
        return _LOWER_PREF[u.lower()]
    for k in _UNIT_KEYS:
        if k.lower() == u.lower():
            return k
    return None


def to_base(value, unit):
    """(value, unit) -> (value in base unit, base unit) or (None, None) when the unit is unknown."""
    if value is None or not unit:
        return None, None
    u = _unit_key(unit)
    if not u:
        return None, None
    base, f = UNIT_TABLE[u]
    return float(value) * f, base


def quantities(s):
    """Numbers with units in free text (Arabic unit words too) -> [(value_base, base_unit, raw)]."""
    s = norm_ar(s or '').replace('μ', 'µ')
    for ar, en in AR_UNITS.items():
        s = re.sub(r'(\d)\s*' + ar, r'\1 ' + en, s)
    out = []
    for m in _QV.finditer(s):
        unit = m.group(2)
        if unit not in UNIT_TABLE and unit.lower() == unit:      # typed in lower case
            unit = _LOWER_PREF.get(unit, unit)
        v, b = to_base(float(m.group(1).replace(',', '.')), unit)
        if b:
            out.append((v, b, m.group(0)))
    return out


def strip_quantities(s):
    s = norm_ar(s or '').replace('μ', 'µ')
    for ar, en in AR_UNITS.items():
        s = re.sub(r'(\d)\s*' + ar, r'\1 ' + en, s)
    return re.sub(r'\s+', ' ', _QV.sub(' ', s)).strip()


def compare(value, op, threshold):
    if value is None or threshold is None:
        return None
    return {'>': value > threshold, '>=': value >= threshold, '<': value < threshold,
            '<=': value <= threshold}.get(op)


def snippet(text, terms, width=220):
    """Short excerpt of `text` around the first matched term, HTML-escaped, matches wrapped in <mark>."""
    import html as _h
    text = text or ''
    if not text:
        return ''
    ft = fold(text)
    pos = -1
    for t in sorted(terms, key=len, reverse=True):
        if len(t) < 2:
            continue
        i = ft.find(t)
        if i >= 0 and (pos < 0 or i < pos):
            pos = i
    start = max(0, pos - width // 3) if pos >= 0 else 0
    end = min(len(text), start + width)
    piece = text[start:end]
    esc = _h.escape(piece)
    for t in sorted({t for t in terms if len(t) >= 2}, key=len, reverse=True):
        try:
            tail = r'[a-z]*' if re.fullmatch(r'[a-z]+', t) else ''      # a stem marks the whole word
            esc = re.sub(r'(?<![a-z&#])(' + _fold_pattern(t) + tail + ')', r'<mark>\1</mark>', esc, flags=re.I)
        except re.error:
            continue
    esc = re.sub(r'(<mark>)+', '<mark>', re.sub(r'(</mark>)+', '</mark>', esc))
    return ('…' if start > 0 else '') + esc + ('…' if end < len(text) else '')


def _fold_pattern(t):
    """Regex that matches `t` in un-folded Arabic text (any alef / ya / ta marbuta form, optional harakat)."""
    groups = {'ا': '[اأإآٱ]', 'ي': '[يىئ]', 'ه': '[هة]', 'و': '[وؤ]'}
    out = []
    for c in t:
        out.append(groups.get(c, re.escape(c)) + ('[ً-ٟـ]*' if is_arabic(c) else ''))
    return ''.join(out)
