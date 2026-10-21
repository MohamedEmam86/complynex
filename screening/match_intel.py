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
Match intelligence: how an experienced screening analyst decides whether a
name hit is the listed person.

Three pieces, all pure functions except the candidate search:

1. ``name_match(query, listed)`` — token-by-token alignment of two names after
   Arabic/Latin normalisation. Each element is weighted by rarity (name_idf),
   coverage is measured BOTH ways (how much of the listed name is in the query
   and how much of the query is in the listed name), order and first/family
   name agreement are checked. A two-word listed name inside a four-word
   customer name is therefore a partial match, not a 100% hit.

2. ``identity_verdict(...)`` / ``decide(...)`` — secondary identifiers settle
   what names cannot: an Egyptian national ID encodes birth date, governorate
   and gender; an exact ID match confirms, a different valid ID contradicts.
   Without an ID on the listed record the decision rests on the name and the
   country / nationality, as agreed with Compliance (2026-10-21).
   CONFIRMED_HIT is reserved for an identifier match, or a complete name match
   (both directions, in order, at least three elements) with nothing
   contradicting it. Everything else is at most a POTENTIAL match for review.

3. ``search_internal(table, name)`` — candidate recall for the internal lists
   (asset-freeze orders, local terrorist lists, internal PEPs). Replaces the
   old "whole query string contained in the record" ILIKE, which missed every
   customer whose ID name is longer than the listed name and every spelling
   variant of hamza / taa marbuta / alef maqsura.
"""
import json
import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- normalisation
_AR_DIACRITICS = re.compile(r'[ً-ْٰـ]')
_ARABIC = re.compile(r'[؀-ۿ]')
_PARTICLES = {'ال', 'بن', 'ابن', 'بنت', 'ابو', 'عبد', 'ال', 'al', 'el', 'bin', 'ben', 'ibn',
              'abu', 'abou', 'abo', 'abd', 'abdel', 'abdul', 'abdal'}
# legal-form words in company names carry no identity (شركة ... ش.م.م / ... LLC)
_LEGAL_FORMS = {'شركه', 'شركة', 'ش', 'م', 'ذ', 'ق', 'مؤسسه', 'منشاه', 'co', 'company', 'llc', 'ltd', 'limited',
                'inc', 'corp', 'corporation', 'sae', 's', 'a', 'e', 'plc', 'llp', 'gmbh', 'sa', 'sarl', 'fzco',
                'fze', 'the', 'and', 'for', 'of', 'و',
                # titles
                'دكتور', 'الدكتور', 'مهندس', 'المهندس', 'الحاج', 'الحاجه', 'لواء', 'اللواء', 'المستشار',
                'mr', 'mrs', 'ms', 'dr', 'eng', 'haj', 'hajj', 'sheikh'}
# Arabic sound classes for phonetic equality of one element (ث/س/ص, ذ/ز/ظ, ...)
_AR_SOUND = str.maketrans({'ث': 'س', 'ص': 'س', 'ذ': 'ز', 'ظ': 'ز', 'ض': 'د', 'ط': 'ت',
                           'ق': 'ك', 'غ': 'خ', 'ح': 'ه', 'ع': 'ا', 'ء': 'ا', 'ؤ': 'و', 'ئ': 'ي'})
_LATIN_CANON = [
    (r'\b(mo|mu)ha?mm?[ae]d\b', 'mohamed'), (r'\bahm[ae]d\b', 'ahmed'), (r'\bma[hk]m[ou]+d\b', 'mahmoud'),
    (r'\b(mo|mu|mou)st?[ae]fa\b', 'mostafa'), (r'\bh[ou]ss?[ae]i?n\b', 'hussein'), (r'\bh[ae]ss?an\b', 'hassan'),
    (r'\b(a|e)l[iy]\b', 'ali'), (r'\baly\b', 'ali'), (r'\by[ou]ss?[eo]f\b', 'youssef'), (r'\bkh?al[ei]d\b', 'khaled'),
    (r'\b(g|j)amal\b', 'gamal'), (r'\bibrah[ie]m\b', 'ibrahim'), (r'\bism[ae]e?il\b', 'ismail'),
    (r'\b(o|u)sa?ma\b', 'osama'), (r'\bom[ae]r\b', 'omar'), (r'\bs[ae]y+[ie]?d\b', 'sayed'),
    (r'\beb?rahim\b', 'ibrahim'), (r'ou', 'u'), (r'ee', 'i'), (r'oo', 'u'),
]


def is_arabic(text):
    return bool(_ARABIC.search(str(text or '')))


def normalize(text):
    """One canonical spelling for comparison (both scripts)."""
    t = str(text or '').strip()
    if not t:
        return ''
    if is_arabic(t):
        t = _AR_DIACRITICS.sub('', t)
        t = re.sub('[إأآٱ]', 'ا', t)
        t = t.replace('ة', 'ه').replace('ى', 'ي')
        # fused compounds: عبدالرحمن / ابوبكر -> عبد الرحمن / ابو بكر
        t = re.sub(r'\b(عبد|ابو)(?=ال|[ء-ي]{3,})', r'\1 ', t)
        t = re.sub(r'[^ء-ي\s]', ' ', t)
    else:
        t = t.lower()
        t = re.sub(r"['`’\-\.]", ' ', t)
        t = re.sub(r'\b(abd|abdel|abdul)(?=[a-z]{3,})', r'\1 ', t)
        t = re.sub(r'[^a-z\s]', ' ', t)
        for pat, rep in _LATIN_CANON:
            t = re.sub(pat, rep, t)
    return re.sub(r'\s+', ' ', t).strip()


def tokens(text):
    """Identity-bearing elements of a name, in order, particles dropped and
    the leading ال of a family element removed (الشاذلي == شاذلي)."""
    out = []
    for tok in normalize(text).split():
        if tok in _PARTICLES or tok in _LEGAL_FORMS:
            continue
        if is_arabic(tok) and tok.startswith('ال') and len(tok) > 4:
            tok = tok[2:]
        if not is_arabic(tok) and tok.startswith(('el', 'al')) and len(tok) > 5:
            tok = tok[2:]
        out.append(tok)
    return out


def _weight(tok):
    try:
        from screening import name_idf
        w = name_idf.weight(tok)
    except Exception:
        w = 6.0
    return max(0.6, min(float(w), 12.0))


# --------------------------------------------------------------------------- Latin <-> Arabic
_XS_DICT = None
_AR_TO_KEY = str.maketrans({'ب': 'b', 'ت': 't', 'ث': 's', 'ج': 'g', 'ح': 'h', 'خ': 'k', 'د': 'd', 'ذ': 'z',
                            'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'x', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z',
                            'ع': '', 'غ': 'g', 'ف': 'f', 'ق': 'k', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
                            'ه': 'h', 'و': '', 'ي': '', 'ا': '', 'ء': '', 'ئ': '', 'ؤ': '', 'ة': ''})
# most likely Arabic letter for a Latin consonant (recall only; scoring uses keys)
_LAT_TO_AR = [('sh', 'ش'), ('kh', 'خ'), ('gh', 'غ'), ('th', 'ث'), ('dh', 'ذ'), ('ou', 'و'), ('oo', 'و'),
              ('ee', 'ي'), ('b', 'ب'), ('t', 'ت'), ('g', 'ج'), ('j', 'ج'), ('h', 'ه'), ('d', 'د'),
              ('r', 'ر'), ('z', 'ز'), ('s', 'س'), ('f', 'ف'), ('q', 'ق'), ('k', 'ك'), ('l', 'ل'),
              ('m', 'م'), ('n', 'ن'), ('w', 'و'), ('y', 'ي'), ('i', 'ي'), ('u', 'و'), ('o', 'و'),
              ('a', 'ا'), ('e', ''), ('p', 'ب'), ('v', 'ف'), ('c', 'ك'), ('x', 'كس')]


def _xs_dict():
    """Latin element -> Arabic elements, learned from records that carry both
    (scripts/build_latin_arabic_dict.py). Missing file -> empty dictionary."""
    global _XS_DICT
    if _XS_DICT is None:
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'latin_arabic_dict.json')
        try:
            with open(path, encoding='utf-8') as f:
                _XS_DICT = json.load(f)
        except Exception:
            _XS_DICT = {}
    return _XS_DICT


def _xs_key(t):
    """Consonant key shared by both scripts (vowels dropped, sound classes merged)."""
    if is_arabic(t):
        k = t[:-1] + ('' if t.endswith('ه') and len(t) > 2 else t[-1]) if t else ''
        k = k.translate(_AR_TO_KEY)
    else:
        k = t.lower()
        for a, b in (('sh', 'x'), ('kh', 'k'), ('gh', 'g'), ('th', 's'), ('dh', 'z'), ('ph', 'f'),
                     ('q', 'k'), ('c', 'k'), ('j', 'g'), ('v', 'f'), ('p', 'b')):
            k = k.replace(a, b)
        k = re.sub('[aeiouwy]', '', k)
        if k.endswith('h') and len(k) > 2:
            k = k[:-1]
    return re.sub(r'(.)\1+', r'\1', k)


def _xs_same(lat, ar):
    """Same name element written in Latin and in Arabic?"""
    cands = _xs_dict().get(lat)
    if cands:
        total = sum(c for _, c in cands)
        for a, c in cands:
            if a == ar or (len(a) == len(ar) and a.translate(_AR_SOUND) == ar.translate(_AR_SOUND)):
                return 0.95 if c / total >= 0.1 else 0.85
        if total >= 8:
            return 0.0          # a well-known element that is written otherwise (Mohamed is not محمود)
    kl, ka = _xs_key(lat), _xs_key(ar)
    if len(kl) >= 2 and kl == ka:
        return 0.85
    if min(len(kl), len(ka)) >= 4 and _osa(kl, ka) <= 1:
        return 0.75
    return 0.0


def to_arabic(name):
    """Most likely Arabic spelling of a Latin name (used to search Arabic-only lists)."""
    out = []
    for t in tokens(name):
        if is_arabic(t):
            out.append(t)
            continue
        cands = _xs_dict().get(t)
        if cands:
            out.append(cands[0][0])
            continue
        w, i = '', 0
        while i < len(t):
            for lat, ar in _LAT_TO_AR:
                if t.startswith(lat, i):
                    w += ar
                    i += len(lat)
                    break
            else:
                i += 1
        out.append(w)
    return ' '.join(x for x in out if x)


def _same_token(a, b):
    """Are two name elements the same name, allowing for spelling?

    Arabic is stricter than Latin on purpose: inserting a long vowel changes
    the name (محمد/محمود, حسن/حسين, سعد/سعيد), so Arabic only tolerates a
    same-length substitution or swap, or near-identity on long elements.
    """
    if a == b:
        return 1.0
    if is_arabic(a) != is_arabic(b):                 # Latin vs Arabic
        return _xs_same(b, a) if is_arabic(a) else _xs_same(a, b)
    ar = is_arabic(a) and is_arabic(b)
    if ar and a.translate(_AR_SOUND) == b.translate(_AR_SOUND):
        return 0.95
    try:
        from rapidfuzz import fuzz
        r = fuzz.ratio(a, b)
    except Exception:
        import difflib
        r = difflib.SequenceMatcher(None, a, b).ratio() * 100
    if ar:
        if len(a) == len(b) >= 4 and _osa(a, b) <= 1:
            return 0.88
        if min(len(a), len(b)) >= 6 and r >= 88:
            return 0.85
        return 0.0
    if min(len(a), len(b)) >= 4 and r >= 85:
        return 0.9
    if min(len(a), len(b)) >= 5 and _osa(a, b) <= 1:
        return 0.88
    sa, sb = _skeleton(a), _skeleton(b)
    if len(sa) >= 3 and sa == sb:
        return 0.85
    return 0.0


def _skeleton(t):
    s = re.sub('[aeiouwy]', '', t).replace('kh', 'k').replace('gh', 'g').replace('q', 'k')
    return re.sub(r'(.)\1+', r'\1', s)


def _osa(a, b):
    """Optimal-string-alignment distance (Levenshtein + adjacent swaps)."""
    try:
        from rapidfuzz.distance import OSA
        return OSA.distance(a, b)
    except Exception:
        pass
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


# --------------------------------------------------------------------------- name match
def name_match(query, listed):
    """Analyst-style comparison of two names. Returns a dict with ``score``
    (0-100) and the evidence behind it."""
    q, c = tokens(query), tokens(listed)
    res = {'score': 0.0, 'q_tokens': q, 'l_tokens': c, 'matched': [], 'missing_from_query': [],
           'extra_in_query': [], 'cov_listed': 0.0, 'cov_query': 0.0, 'order_ok': False,
           'first_ok': False, 'family_ok': False, 'complete': False, 'partial': True}
    if not q or not c:
        return res
    used, pairs = set(), []
    for ci, ct in enumerate(c):
        best, bj = 0.0, None
        for qi, qt in enumerate(q):
            if qi in used:
                continue
            s = _same_token(ct, qt)
            if s > best:
                best, bj = s, qi
                if s == 1.0:
                    break
        if bj is not None and best > 0:
            used.add(bj)
            pairs.append((ci, bj, best))
    wl = [_weight(t) for t in c]
    wq = [_weight(t) for t in q]
    got_l = sum(wl[ci] * s for ci, qi, s in pairs)
    got_q = sum(wq[qi] * s for ci, qi, s in pairs)
    cov_l = got_l / sum(wl)
    cov_q = got_q / sum(wq)
    qidx = [qi for ci, qi, s in sorted(pairs)]
    order_ok = qidx == sorted(qidx)
    matched_c = {ci for ci, _, _ in pairs}
    first_ok = 0 in matched_c and dict((ci, qi) for ci, qi, _ in pairs).get(0) == 0
    family_ok = (len(c) - 1) in matched_c
    score = 100.0 * (0.55 * cov_l + 0.45 * cov_q)
    if not order_ok:
        score -= 5
    if not first_ok:
        score -= 10
    if len(c) >= 3 and len(q) >= 3 and not family_ok and (len(q) - 1) not in used:
        # neither side's family element is matched: different families
        score = min(score, 74.0)
    complete = (len(pairs) == len(c) and len(used) == len(q) and order_ok and first_ok)
    missing = [c[i] for i in range(len(c)) if i not in matched_c]
    extra = [q[i] for i in range(len(q)) if i not in used]
    if len(c) >= 3 and len(q) >= 3 and missing and extra:
        # both names carry an element the other lacks at the same place in the
        # chain (a different father / grandfather): different people unless an
        # identifier says otherwise
        score = min(score, 74.0)
    res.update({
        'score': round(max(0.0, min(100.0, score)), 2),
        'matched': [(c[ci], q[qi]) for ci, qi, _ in sorted(pairs)],
        'missing_from_query': missing,
        'extra_in_query': extra,
        'cov_listed': round(cov_l, 3), 'cov_query': round(cov_q, 3),
        'order_ok': order_ok, 'first_ok': first_ok, 'family_ok': family_ok,
        'complete': complete, 'partial': not complete,
    })
    return res


# --------------------------------------------------------------------------- identifiers
_GOVERNORATES = {
    '01': 'Cairo', '02': 'Alexandria', '03': 'Port Said', '04': 'Suez', '11': 'Damietta',
    '12': 'Dakahlia', '13': 'Sharqia', '14': 'Qalyubia', '15': 'Kafr El Sheikh', '16': 'Gharbia',
    '17': 'Monufia', '18': 'Beheira', '19': 'Ismailia', '21': 'Giza', '22': 'Beni Suef',
    '23': 'Fayoum', '24': 'Minya', '25': 'Asyut', '26': 'Sohag', '27': 'Qena', '28': 'Aswan',
    '29': 'Luxor', '31': 'Red Sea', '32': 'New Valley', '33': 'Matrouh', '34': 'North Sinai',
    '35': 'South Sinai', '88': 'Born abroad',
}


def decode_egyptian_nid(nid):
    """14-digit Egyptian national ID -> {'valid', 'dob', 'governorate', 'gender'}.
    Digit 1 = century (2: 1900s, 3: 2000s), 2-7 = YYMMDD, 8-9 = governorate,
    13 = gender (odd male, even female)."""
    d = re.sub(r'\D', '', str(nid or ''))
    out = {'valid': False, 'nid': d}
    if len(d) != 14 or d[0] not in '23':
        return out
    try:
        y = (1900 if d[0] == '2' else 2000) + int(d[1:3])
        dob = date(y, int(d[3:5]), int(d[5:7]))
    except ValueError:
        return out
    out.update({'valid': True, 'dob': dob.isoformat(), 'year': y,
                'governorate': _GOVERNORATES.get(d[7:9], d[7:9]),
                'gender': 'M' if int(d[12]) % 2 else 'F'})
    return out


def _as_list(v):
    if v is None or v == '':
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v if x not in (None, '')]
    s = str(v).strip()
    if s.startswith('['):
        try:
            return [str(x) for x in json.loads(s) if x]
        except Exception:
            pass
    return [p.strip() for p in re.split(r'[;,|]', s) if p.strip()]


def _years(v):
    ys = set()
    for p in _as_list(v):
        for m in re.findall(r'(19\d{2}|20\d{2})', p):
            ys.add(int(m))
    return ys


_COUNTRY_ALIASES = {
    'eg': 'egypt', 'egy': 'egypt', 'egyptian': 'egypt', 'مصر': 'egypt', 'مصري': 'egypt', 'مصرى': 'egypt',
    'ps': 'palestine', 'palestinian': 'palestine', 'فلسطيني': 'palestine', 'فلسطين': 'palestine',
    'sy': 'syria', 'syrian': 'syria', 'iq': 'iraq', 'iraqi': 'iraq', 'ly': 'libya', 'libyan': 'libya',
    'sd': 'sudan', 'sudanese': 'sudan', 'sa': 'saudi arabia', 'saudi': 'saudi arabia', 'ye': 'yemen',
    'yemeni': 'yemen', 'af': 'afghanistan', 'afghan': 'afghanistan', 'ir': 'iran', 'iranian': 'iran',
    'kp': 'north korea', "democratic people's republic of korea": 'north korea', 'tr': 'turkey', 'qa': 'qatar',
}


def _countries(*vals):
    out = set()
    for v in vals:
        for p in _as_list(v):
            k = p.strip().lower()
            if not k or k in ('na', 'none', 'unknown'):
                continue
            out.add(_COUNTRY_ALIASES.get(k, k))
    return out


def identity_verdict(query_nid=None, query_dob=None, query_country=None,
                     listed_nids=None, listed_dob=None, listed_countries=None, listed_gender=None):
    """Compare secondary identifiers. Returns {'verdict', 'reasons', ...}.

    verdict: id_match | id_conflict | dob_conflict | country_conflict |
             corroborated | unknown
    """
    reasons, qd = [], decode_egyptian_nid(query_nid) if query_nid else {'valid': False}
    lids = [re.sub(r'\D', '', x) for x in _as_list(listed_nids)]
    lids = [x for x in lids if len(x) >= 6 and not set(x) <= {'0'}]
    qn = re.sub(r'\D', '', str(query_nid or ''))
    if qn and lids:
        if qn in lids:
            return {'verdict': 'id_match', 'reasons': ['national ID matches the listed record']}
        valid14 = [x for x in lids if len(x) == 14]
        if qd.get('valid') and valid14:
            return {'verdict': 'id_conflict',
                    'reasons': ['listed record carries a different national ID']}
    # gender: the 13th digit of an Egyptian national ID, on either side
    q_gender = qd.get('gender') if qd.get('valid') else None
    l_gender = None
    for x in lids:
        d = decode_egyptian_nid(x)
        if d.get('valid'):
            l_gender = d['gender']
            break
    if not l_gender and listed_gender:
        g = str(listed_gender).strip().lower()
        l_gender = 'M' if g in ('m', 'male', 'ذكر') else ('F' if g in ('f', 'female', 'انثى', 'أنثى') else None)
    if q_gender and l_gender and q_gender != l_gender:
        return {'verdict': 'gender_conflict', 'reasons': ['gender differs (from the national ID)']}
    # date of birth: given, or decoded from the customer's national ID
    q_years = _years(query_dob)
    if not q_years and qd.get('valid'):
        q_years = {qd['year']}
    l_years = _years(listed_dob)
    for x in lids:
        d = decode_egyptian_nid(x)
        if d.get('valid'):
            l_years.add(d['year'])
    corroborated = False
    if q_years and l_years:
        if min(abs(a - b) for a in q_years for b in l_years) > 2:
            return {'verdict': 'dob_conflict',
                    'reasons': [f'birth year differs ({sorted(q_years)[0]} vs {sorted(l_years)[0]})']}
        reasons.append('birth year agrees')
        corroborated = True
    # country / nationality (the decisive check when the record has no ID)
    qc = _countries(query_country, 'egypt' if qd.get('valid') else None)
    lc = _countries(listed_countries)
    if qc and lc:
        if qc & lc:
            reasons.append('nationality / country agrees')
            corroborated = True
        else:
            return {'verdict': 'country_conflict',
                    'reasons': [f"nationality differs ({', '.join(sorted(qc))} vs {', '.join(sorted(lc))})"]}
    if not lids and not l_years and not lc:
        reasons.append('listed record has no identifiers: decision rests on the name')
    return {'verdict': 'corroborated' if corroborated else 'unknown', 'reasons': reasons}


# --------------------------------------------------------------------------- decision
CONFIRMED = 95.0
POTENTIAL = 80.0
LOW = 75.0


def _listed_name(m, query):
    """The listed name to judge against: the record's form in the query's
    script when it has one, otherwise its other-script form (compared
    element by element across scripts)."""
    names = [m.get('watchlist_name_ar'), m.get('original_name'), m.get('full_name_arabic'),
             m.get('full_name'), m.get('candidate_name')]
    names = [n for n in names if n]
    q_ar = is_arabic(query)
    same = [n for n in names if is_arabic(n) == q_ar]
    if same:
        return same[0]
    return names[0] if names else ''


def _best_listed(m, query):
    names = [m.get('watchlist_name_ar'), m.get('original_name'), m.get('full_name_arabic'),
             m.get('full_name'), m.get('candidate_name')]
    names = [n for n in dict.fromkeys(names) if n and str(n).strip()]
    best = (None, None, False)
    q_ar = is_arabic(query)
    for n in names:
        nm = name_match(query, n)
        cross = is_arabic(n) != q_ar
        if cross:
            nm['score'] = round(nm['score'] * 0.97, 2)   # transliteration is never certain
        if best[1] is None or nm['score'] > best[1]['score'] or (
                nm['score'] == best[1]['score'] and best[2] and not cross):
            best = (n, nm, cross)
    return best


def decide(m, query, national_id=None, dob=None, nationality=None):
    """Apply the analyst decision to one match dict (mutates and returns it)."""
    score = float(m.get('match_score') or 0.0)
    original = score
    reasons = []
    # judge against every form the record carries (Arabic original, Latin
    # rendering, aliases) and keep the best: a listed Latin spelling made by
    # a machine must not hide an Arabic original the query matches
    listed, nm, cross = _best_listed(m, query)
    if nm is not None and cross:
        reasons.append('compared across scripts (Latin / Arabic)')
    idv = identity_verdict(
        national_id, dob, nationality,
        m.get('national_id') or m.get('national_id_numbers'),
        m.get('date_of_birth') or m.get('year_of_birth'),
        [m.get('nationality'), m.get('countries'), m.get('country')],
        m.get('gender'))
    tier = None
    if idv['verdict'] == 'id_match':
        score, tier = 100.0, 'CONFIRMED'
    elif idv['verdict'] == 'id_conflict':
        score = min(score, LOW + 1)
    elif idv['verdict'] == 'dob_conflict':
        score = min(score - 15, POTENTIAL - 1)
    elif idv['verdict'] == 'gender_conflict':
        score = min(score - 20, LOW + 1)
    elif idv['verdict'] == 'country_conflict':
        score = min(score - 10, POTENTIAL - 1)
    reasons += idv['reasons']

    if nm is not None and tier != 'CONFIRMED':
        # the structural name verdict may lower a generous fuzzy score, never raise it
        if nm['score'] < score - 10:
            reasons.append(f"name structure: {nm['score']:.0f}")
            score = (score + nm['score']) / 2
        if nm['partial']:
            if len(nm['l_tokens']) <= 2 and len(nm['q_tokens']) >= 3:
                # a two-word listed name inside a longer name: a lead, not an alert,
                # unless an identifier agrees
                cap = POTENTIAL + 5 if idv['verdict'] == 'corroborated' else POTENTIAL - 1
                score = min(score, cap)
                reasons.append('listed name is a short form inside a longer name')
            if nm['missing_from_query']:
                reasons.append('not in the customer name: ' + ' '.join(nm['missing_from_query'][:4]))
            if nm['extra_in_query']:
                reasons.append('extra in the customer name: ' + ' '.join(nm['extra_in_query'][:4]))
            score = min(score, CONFIRMED - 1)          # a partial name never auto-confirms
        elif len(nm['l_tokens']) < 3:
            score = min(score, CONFIRMED - 1)          # two-word names are too common to confirm
            reasons.append('complete but short name')
        elif cross and idv['verdict'] != 'corroborated':
            score = min(score, CONFIRMED - 1)          # across scripts the name alone does not confirm
            reasons.append('complete match across scripts: confirm with an identifier')
        else:
            reasons.append('complete name match, same order')
    elif nm is None and tier != 'CONFIRMED':
        # different scripts and no same-script form on the record: identifiers decide
        if idv['verdict'] not in ('corroborated',):
            score = min(score, CONFIRMED - 1)
            reasons.append('cross-script match without a corroborating identifier')

    if tier is None:
        if score >= CONFIRMED and idv['verdict'] in ('corroborated', 'unknown'):
            tier = 'CONFIRMED'
        elif score >= POTENTIAL:
            tier = 'POTENTIAL'
        elif score >= LOW:
            tier = 'LOW'
        else:
            tier = 'BELOW'
    m['match_score'] = round(max(0.0, min(100.0, score)), 2)
    m['decision'] = {
        'tier': tier, 'original_score': round(original, 2), 'final_score': m['match_score'],
        'identity': idv['verdict'], 'reasons': reasons,
        'name': ({k: nm[k] for k in ('matched', 'missing_from_query', 'extra_in_query',
                                     'cov_listed', 'cov_query', 'order_ok', 'complete')}
                 if nm else None),
    }
    return m


def _dedupe_key(m):
    name = m.get('watchlist_name_ar') or m.get('original_name') or m.get('full_name') or ''
    nid = re.sub(r'\D', '', str(m.get('national_id') or ''))
    return (' '.join(tokens(name)), nid if len(nid) == 14 else '')


def dedupe(matches):
    """One row per listed person: keep the best-scored occurrence and list the
    other sources it also appears in."""
    best, order = {}, []
    for m in sorted(matches, key=lambda x: -float(x.get('match_score') or 0)):
        k = _dedupe_key(m)
        if not k[0]:
            order.append(m)
            continue
        src = f"{m.get('source_name') or m.get('source') or ''} · {m.get('category') or m.get('dataset') or ''}".strip(' ·')
        if k in best:
            also = best[k].setdefault('also_listed_in', [])
            if src and src not in also:
                also.append(src)
            continue
        best[k] = m
        order.append(m)
    return order


def apply_decisions(matches, query, national_id=None, dob=None, nationality=None):
    out = []
    for m in matches:
        try:
            out.append(decide(m, query, national_id, dob, nationality))
        except Exception as e:                       # never drop a hit because of this layer
            logger.warning('[MATCH-INTEL] decision failed: %s', e)
            out.append(m)
    # The same listed name often sits on several records (asset-freeze order,
    # terrorist list, semantic index) and only some carry the national ID. If
    # one of them proves a DIFFERENT ID and none proves the same ID, the
    # ID-less copies must not auto-confirm on the name alone.
    by_name = {}
    for m in out:
        k = _dedupe_key(m)[0]
        if k:
            by_name.setdefault(k, []).append(m)
    for k, group in by_name.items():
        ids = {(g.get('decision') or {}).get('identity') for g in group}
        if 'id_conflict' in ids and 'id_match' not in ids:
            for g in group:
                d = g.get('decision') or {}
                if d.get('identity') != 'id_conflict' and d.get('tier') == 'CONFIRMED':
                    g['match_score'] = min(float(g['match_score']), POTENTIAL + 5)
                    d['tier'] = 'POTENTIAL'
                    d['final_score'] = g['match_score']
                    d.setdefault('reasons', []).append(
                        'another record of this listed name carries a different national ID')
    return dedupe(out)


def overall_status(matches):
    tiers = [((m.get('decision') or {}).get('tier'), float(m.get('match_score') or 0)) for m in matches]
    if any(t == 'CONFIRMED' for t, _ in tiers):
        return 'CONFIRMED_HIT'
    top = max([s for _, s in tiers] or [0.0])
    if top >= POTENTIAL:
        return 'POTENTIAL_MATCH'
    if top >= LOW:
        return 'LOW_MATCH'
    return 'CLEAR'


# --------------------------------------------------------------------------- internal list recall
_TRANSLATE = "translate(lower(coalesce({c},'')), 'أإآٱةى', 'اااايهي')"
_COLS_CACHE = {}


def _columns(cur, table):
    if table not in _COLS_CACHE:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,))
        _COLS_CACHE[table] = {r['column_name'] if isinstance(r, dict) else r[0] for r in cur.fetchall()}
    return _COLS_CACHE[table]


def _recall(cur, table, cols, field, q, limit):
    norm_q = [normalize(t) for t in q]
    frags = []
    for t in dict.fromkeys(norm_q):
        if t:
            frags.append((t, t if len(t) <= 4 else t[:len(t) - 1]))   # tolerate a changed last letter
    if not frags:
        return []
    ranked = sorted(frags, key=lambda x: -_weight(x[0]))
    distinctive = [f for t, f in ranked if _weight(t) >= 2.5 and len(f) >= 3][:3] or \
                  [f for t, f in ranked if len(f) >= 3][:2] or [ranked[0][1]]
    count_frags = [f for t, f in ranked][:6]
    need = 1 if len(q) <= 1 else 2
    where = ' OR '.join([f'{field} LIKE %s'] * len(distinctive))
    hits = ' + '.join([f'(CASE WHEN {field} LIKE %s THEN 1 ELSE 0 END)'] * len(count_frags))
    active = 'COALESCE(is_active,1) != 0' if 'is_active' in cols else 'TRUE'
    sql = (f"SELECT * FROM (SELECT *, ({hits}) AS _tok_hits FROM {table} "
           f"WHERE {active} AND ({where})) s WHERE _tok_hits >= %s ORDER BY _tok_hits DESC LIMIT %s")
    params = [f'%{f}%' for f in count_frags] + [f'%{f}%' for f in distinctive] + [min(need, len(count_frags)), limit]
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def search_internal(conn, table, name, limit=150, min_score=LOW):
    """Token-based recall + analyst scoring over an internal list table.
    Returns rows (dicts) with ``_match_score`` in 0..1 and ``_name_match``.

    Recall uses the trigram-indexed ``name_search`` column (migration
    20261027_internal_list_search) on the query's most identifying elements,
    then counts how many of its elements each candidate carries. A Latin
    query is also searched through its most likely Arabic spelling, because
    the local lists are Arabic first."""
    q = tokens(name)
    if not q:
        return []
    cur = conn.cursor()
    cols = _columns(cur, table)
    if 'name_search' in cols:
        field = 'name_search'
    else:                                   # before the migration: slower expression
        field = _TRANSLATE.format(c="coalesce(original_name,'') || ' ' || coalesce(full_name,'')")
    q_ar = is_arabic(name)
    rows = {r['id']: r for r in _recall(cur, table, cols, field, q, limit)}
    if not q_ar:
        ar = to_arabic(name)
        if ar:
            for r in _recall(cur, table, cols, field, tokens(ar), limit):
                rows.setdefault(r['id'], r)
    out = []
    for r in rows.values():
        primary = r.get('original_name') if q_ar else r.get('full_name')
        forms = [primary, r.get('full_name') if q_ar else r.get('original_name')]
        forms += [a for a in _as_list(r.get('aliases')) if is_arabic(a) == q_ar][:12]
        best = None
        for f in dict.fromkeys(x for x in forms if x):
            nm = name_match(name, f)
            if is_arabic(f) != q_ar:
                nm['score'] = round(nm['score'] * 0.97, 2)       # across scripts
            if best is None or nm['score'] > best['score']:
                best = nm
                if nm['score'] >= 99.9:
                    break
        if best and best['score'] >= min_score:
            r.pop('_tok_hits', None)
            r.pop('name_search', None)
            r['_match_score'] = best['score'] / 100.0
            r['match_score'] = best['score']
            r['_name_match'] = best
            out.append(r)
    out.sort(key=lambda x: -x['_match_score'])
    return out[:100]
