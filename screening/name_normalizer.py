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
Arabic name canonical normalizer — Tier-1 style bidirectional scoring.
"""
import re
import json
from functools import lru_cache

from rapidfuzz.distance import Indel, Jaro

ABD_COMPOUNDS = re.compile(
    r'\b(abdel|abdoul|abdal|abdol|abdil|abdo|abdul|abdu)\s*', re.I
)
ARTICLE_RE = re.compile(
    r'\b(al|el|ul|il|at|et|ut|ad|ed|ud|as|es|ash|esh|az|ez|an|en|ar|er|'
    r'att|ett|add|edd|ass|ess|azz|ezz|arr|err|ann|enn)\b[\s\-]*',
    re.I
)
PHONETIC_MAP = [
    (r'(ee|iy|ei|ie|ea|ey)(?=[^aeiou\s]|$)', 'i'),
    (r'(oo|ou|uw|ue)(?=[^aeiou\s]|$)', 'u'),
    (r'(aa|ah)(?=[^aeiou\s]|$)', 'a'),
    (r'kh', 'x'),
    (r'gh', 'g'),
    (r'sh', 'c'),
    (r'th', 't'),
    (r'dh', 'd'),
    (r'ph', 'f'),
    (r"['\u2018\u2019`]", ''),
    (r'([bcdfghjklmnpqrstvwxyz])\1+', r'\1'),
    (r'e\b', ''),
]
EQUIV_TABLE = {
    'mohamad': 'muhammad', 'mohammed': 'muhammad', 'mohamed': 'muhammad',
    'mohd': 'muhammad', 'mhmd': 'muhammad', 'mahomed': 'muhammad',
    'mehmed': 'muhammad',
    'hameed': 'hamid', 'hamed': 'hamid', 'hamd': 'hamid',
    'hmid': 'hamid', 'hmyd': 'hamid', 'alhmyd': 'hamid', 'alhmid': 'hamid',
    'alsyd': 'sayed', 'alsaid': 'sayed', 'alsayd': 'sayed',
    'said': 'sayed', 'saeed': 'sayed', 'sayd': 'sayed',
    'elsayed': 'sayed', 'elsaid': 'sayed',
    'nwrhan': 'nourhan', 'norhan': 'nourhan', 'noorhan': 'nourhan',
    'nurhan': 'nourhan',
    'alshykh': 'sheikh', 'alsheikh': 'sheikh', 'shaikh': 'sheikh',
    'shikh': 'sheikh', 'alshikh': 'sheikh',
    'ebrahim': 'ibrahim', 'ibraheem': 'ibrahim', 'ibrahem': 'ibrahim',
    'bin': 'ibn', 'bint': 'ibn', 'bent': 'ibn',
    'aly': 'ali',
    'raman': 'rahman',  # phonetic: ah->a causes rahman->raman
    # Post-phonetic forms (sh→c runs before EQUIV lookup)
    # nashwa→nacwa, noshwa→nocwa, nshwy→ncwy — all map to same canonical form
    'nacwa': 'ncwy', 'nocwa': 'ncwy',
    # Pre-phonetic forms kept as fallback
    'nashwa': 'nshwy', 'noshwa': 'nshwy', 'nashwaa': 'nshwy',
    'akl': 'aql', 'aqel': 'aql',
    'ela': 'elah', 'ala': 'elah',  # Abd + Allah suffix
    'abd': 'abd', 'abdel': 'abd', 'abdal': 'abd',
}

# Raw common names — will be normalized into _COMMON_NORMED after normalise() defined
_COMMON_RAW = {
    'ahmed','ali','hassan','hussein','ibrahim','khalid','omar',
    'muhammad','ahmad','mahmoud','yusuf','khaled','mostafa',
    'mustafa','abdo','samir','amr','hany','walid','tarek',
    'islam','essam','sherif','wael','hossam','ayman','kamal',
    'sami','nabil','adel','ashraf','osama','hazem','ramy',
    'aly','ali','mohamed','mohamad','mohammed','hamid','hameed',
    'sayed','saeed','said','salah','salem','fathy','fathi',
    'ramadan','abd','nasser','nasir','alaa','amira','mona',
    'farid','gamal','hosny','ragai','ragab','hany','wael',
    'khaled','fayek','fayd','gawysh','hlmy',
}

# Populated at module load after normalise() is defined
_COMMON_NORMED = set()


def _apply_phonetic(s):
    for pattern, repl in PHONETIC_MAP:
        s = re.sub(pattern, repl, s)
    return s


def normalise(name):
    if not name:
        return ''
    s = name.lower().strip()
    if re.search(r'[\u0600-\u06FF]', s):
        return s
    s = re.sub(r'[-_/\\]', ' ', s)
    s = re.sub(r'[,\.;:\(\)]', '', s)
    s = ABD_COMPOUNDS.sub('abd ', s)
    s = ARTICLE_RE.sub(' ', s)
    tokens = s.split()
    normed = []
    for tok in tokens:
        tok = _apply_phonetic(tok)
        tok = EQUIV_TABLE.get(tok, tok)
        if len(tok) >= 2:
            normed.append(tok)
    return ' '.join(normed)


# rapidfuzz (C++) replaces the previous hand-rolled Jaro-Winkler and
# difflib.SequenceMatcher here — this function runs ~285K times per
# screening against the internal PEP table's auto-generated alias fan-out
# and was 78% of total screen time in pure Python.
#
# Parity with the old scorer (validated 2026-07-11, 49,772 real
# query x record pairs + 200K random token pairs):
# - The Winkler prefix boost is applied UNCONDITIONALLY, as the old
#   hand-rolled code did. rapidfuzz's JaroWinkler.similarity must NOT be
#   used here: it follows Winkler's boost_threshold variant (bonus only
#   when jaro > 0.7), which scores low-similarity token pairs LOWER than
#   the old code and dropped 54 real borderline hits below search's 0.80
#   threshold when tried.
# - rapidfuzz's Jaro finds an equal-or-better match assignment than the
#   old greedy loop (never lower, 0/200K), and Indel.normalized_similarity
#   is difflib.ratio()'s 2M/(len1+len2) with an optimal alignment instead
#   of difflib's heuristic one (also never lower) — so scores can only be
#   equal or marginally higher: no existing hit can be lost.
@lru_cache(maxsize=1 << 16)
def _token_sim_cached(t1, t2):
    j = Jaro.similarity(t1, t2)
    prefix = 0
    for a, b in zip(t1[:4], t2[:4]):
        if a != b:
            break
        prefix += 1
    jw = j + prefix * 0.1 * (1 - j)
    return max(jw, Indel.normalized_similarity(t1, t2))


def token_sim(t1, t2):
    if t1 == t2:
        return 1.0
    # Both metrics are symmetric — order-normalize so (a,b) and (b,a)
    # share one cache slot. Name tokens repeat heavily across a screen's
    # 550 candidates x their alias variants, so hit rates are high.
    if t1 > t2:
        t1, t2 = t2, t1
    return _token_sim_cached(t1, t2)


def _score_pair(qn, cn, all_common_query=False):
    """
    Bidirectional Jaro-Winkler with post-score guards.
    all_common_query: True when ALL pre-normalization query tokens are common names.
    """
    if not qn or not cn:
        return 0.0

    q_tok = qn.split()
    c_tok = cn.split()
    if not q_tok or not c_tok:
        return 0.0

    # One all-pairs similarity matrix, shared by the forward pass, the
    # reverse pass and the common-name guard below — token_sim is
    # symmetric, so computing it per-direction (as this used to) just
    # produced the same numbers up to three times.
    sims = [[token_sim(qt, ct) for ct in c_tok] for qt in q_tok]

    # Base bidirectional score
    fwd_bests = [max(row) for row in sims]
    fwd_score = sum(fwd_bests) / len(q_tok)
    fwd_coverage = sum(1 for b in fwd_bests if b >= 0.78) / len(q_tok)

    rev_bests = [max(row[j] for row in sims) for j in range(len(c_tok))]
    rev_score = sum(rev_bests) / len(c_tok)
    rev_coverage = sum(1 for b in rev_bests if b >= 0.78) / len(c_tok)

    if fwd_score + rev_score == 0:
        return 0.0
    base = 2 * fwd_score * rev_score / (fwd_score + rev_score)

    # Coverage penalty
    if fwd_coverage < 0.60 or rev_coverage < 0.40:
        base *= min(fwd_coverage, rev_coverage) * 1.5

    # Guard 1: length imbalance
    # Short queries (2 tokens = first+last name) should not be heavily penalized
    # against longer records that include middle names
    len_ratio = min(len(q_tok), len(c_tok)) / max(len(q_tok), len(c_tok))
    if len_ratio < 0.70 and len(q_tok) >= 3:
        # Only penalize if query itself has 3+ tokens (not a short first+last name)
        base *= (0.5 + len_ratio * 0.7)

    # Guard 2: common-name saturation
    # When ALL query tokens are common names (checked pre-normalization by caller),
    # any extra DISTINGUISHING token in the candidate means a different person.
    if all_common_query and len(q_tok) >= 2:
        # Candidate tokens that don't appear in the query (reuses rev_bests
        # — this is the same per-candidate-token max the reverse pass took)
        unmatched_c = [ct for j, ct in enumerate(c_tok) if rev_bests[j] < 0.78]

        if unmatched_c:
            # Any unmatched candidate token = distinguishing name not in query
            # Hard penalty — this is almost certainly a different person
            base *= 0.25

    return min(base, 1.0)


def _is_arabic(text):
    return bool(re.search(r'[\u0600-\u06FF]', text))


def _transliterate_for_scoring(text):
    if not _is_arabic(text):
        return text
    try:
        from screening.complynex_engine import transliterate_arabic
        r = transliterate_arabic(text)
        return r if r else text
    except Exception:
        pass
    try:
        from screening.arabic_transliteration_enhanced import prepare_name_for_screening
        eng, _ = prepare_name_for_screening(text)
        return eng if eng else text
    except Exception:
        return text


def score_match(query, candidate_name, candidate_aliases=None):
    """Score query against candidate. Returns 0.0–1.0."""
    qr = _transliterate_for_scoring(query)
    cr = _transliterate_for_scoring(candidate_name)

    # Check common-name saturation on RAW tokens (pre-normalization)
    # This catches forms like "ahmed", "aly", "mohamed" before EQUIV collapses them
    q_raw = [t for t in re.sub(r'[-_]', ' ', qr.lower()).split() if len(t) >= 2]
    all_common = (
        len(q_raw) >= 2 and
        all(t in _COMMON_RAW or normalise(t) in _COMMON_NORMED for t in q_raw)
    )

    qn = normalise(qr)
    cn = normalise(cr)
    best = _score_pair(qn, cn, all_common_query=all_common)
    full_tok_count = len(cn.split()) if cn else 0

    if candidate_aliases:
        if isinstance(candidate_aliases, str):
            try:
                aliases = json.loads(candidate_aliases)
            except Exception:
                aliases = []
        else:
            aliases = candidate_aliases or []

        # Auto-generated spelling variants mostly collapse to the same
        # canonical form after normalise() (hassan/hasan/hasaan/...), and
        # identical normalized input always yields the identical score —
        # score each distinct form once instead of dozens of times.
        seen_normed = {cn}
        for alias in aliases:
            if best >= 1.0:
                break  # scores cap at 1.0; further aliases can only tie
            if not alias or not isinstance(alias, str):
                continue
            ar = _transliterate_for_scoring(alias)
            clean = ar.encode('ascii', 'ignore').decode().strip()
            if len(clean) < 4:
                continue
            an = normalise(clean)
            if not an or an in seen_normed:
                continue
            seen_normed.add(an)
            s = _score_pair(qn, an, all_common_query=all_common)
            alias_tok = len(an.split())
            if full_tok_count > 0 and alias_tok < full_tok_count:
                ratio = alias_tok / full_tok_count
                s *= (0.6 + ratio * 0.4)
            best = max(best, s)

    return best


# Build normalized COMMON set now that normalise() is defined
for _raw in _COMMON_RAW:
    _n = normalise(_raw)
    if _n:
        _COMMON_NORMED.add(_n)
