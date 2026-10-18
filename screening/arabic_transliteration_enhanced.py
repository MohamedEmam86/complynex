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
Enhanced Arabic Transliteration Assurance Wrapper.
Centralizes the preprocessing logic so Watchlist Imports, UI inputs, and 
Batch screening hit exactly the same canonical pipeline.
"""
from screening.utils.normalization import normalize_arabic_text
import re
import logging

logger = logging.getLogger(__name__)

# Basic dictionary map for robust transliteration
ARABIC_TO_ENGLISH_MAP = {
    'ا': 'a', 'أ': 'a', 'إ': 'e', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
    'ج': 'g', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'z', 'ر': 'r', 'ز': 'z',
    'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
    'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
    'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ة': 'a', 'ؤ': 'o', 'ئ': 'e',
    'ء': 'a'
}

COMPOUND_NAMES = {
    "عبد ال": "abdel ",
    "ابو ": "abou ",
    "ابن ": "ibn ",
    "ام ": "om "
}


def _is_arabic(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r'[\u0600-\u06FF]', text))

_MERGED_VARIANTS = None


def _get_name_variant_dict():
    """Merges the two curated Arabic->English name-variant dictionaries
    (ARABIC_NAME_VARIANTS in complynex_engine.py, EGYPTIAN_ARABIC_VARIANTS
    in arabic_utils.py — together ~180 entries covering most common
    Egyptian/Arabic first and last names). Lazily imported and cached at
    module level: importing complynex_engine at this module's top level
    would create a circular import (complynex_engine already imports from
    arabic_utils), and re-merging ~180 entries on every call would be
    wasteful given this function runs on every internal blacklist/PEP
    entry saved."""
    global _MERGED_VARIANTS
    if _MERGED_VARIANTS is not None:
        return _MERGED_VARIANTS
    merged = {}
    try:
        from screening.complynex_engine import ARABIC_NAME_VARIANTS
        merged.update(ARABIC_NAME_VARIANTS)
    except Exception:
        pass
    try:
        from screening.arabic_utils import EGYPTIAN_ARABIC_VARIANTS
        for k, v in EGYPTIAN_ARABIC_VARIANTS.items():
            merged[k] = list(dict.fromkeys(merged.get(k, []) + v))
    except Exception:
        pass
    # Third source: EGYPTIAN_NAME_SUPPLEMENT — ~300 additional tokens derived
    # from a frequency analysis of the Egyptian local negative lists, where 760
    # distinct tokens (11.8%% of all occurrences) were falling through to the
    # consonant-only fallback and coming out vowel-less (نسرين -> 'NSRYN').
    try:
        from screening.egyptian_name_supplement import EGYPTIAN_NAME_SUPPLEMENT
        for k, v in EGYPTIAN_NAME_SUPPLEMENT.items():
            merged[k] = list(dict.fromkeys(merged.get(k, []) + v))
    except Exception:
        pass
    # The lookup in transliterate_to_english() happens AFTER
    # normalize_arabic_text(), so a key written with taa-marbuta or
    # alef-maqsura ('حمزة', 'منى') could never be reached. Register the
    # normalised spelling of every key as an alias so each entry is
    # actually reachable.
    for key in list(merged.keys()):
        try:
            nk = normalize_arabic_text(key)
        except Exception:
            continue
        if nk and nk != key and nk not in merged:
            merged[nk] = merged[key]

    _MERGED_VARIANTS = merged
    return merged


def transliterate_to_english(arabic_text: str) -> str:
    """Core transliterator based on ComplyNex ML internal rules.

    Per-token lookup against the curated ~180-entry variant dictionary
    (see _get_name_variant_dict) picks the first/primary listed spelling
    for any known name component — e.g. 'حسن' -> 'hassan', not a bare
    character-map fallback. That fallback (Phase 3 below) used to be the
    *only* path for anything outside a 5-word hardcoded list (ahmed,
    mohamed, mahmoud, mostafa, ibrahim), which is why 'حسن يوسف محمود محمد
    منصور' transliterated to 'HSN YWSF MAHMOUD MOHAMED MNSWR' — only the
    two names that happened to be in that list got a real spelling; every
    other name silently lost its vowels (soundex-style skeleton, not an
    actual English spelling), and every internal blacklist/PEP entry saved
    with any other name got this same treatment on every save. The
    character map remains as the fallback for names genuinely outside the
    dictionary — better than nothing, but no longer the default outcome
    for common names.
    """
    if not arabic_text:
        return ""

    # Phase 1: Canonicalize
    text = normalize_arabic_text(arabic_text)

    # Phase 2: Compound Prefixes & Special Names
    for ar_prefix, en_prefix in COMPOUND_NAMES.items():
        if text.startswith(ar_prefix):
            text = text.replace(ar_prefix, en_prefix, 1)

    # Phase 3: Per-token dictionary lookup (primary spelling), character
    # map as fallback only for tokens not in the dictionary.
    variant_dict = _get_name_variant_dict()
    tokens = text.split()
    out_tokens = []
    for token in tokens:
        variants = variant_dict.get(token)
        if variants:
            out_tokens.append(variants[0])
            continue

        # Definite article: Egyptian surnames are nearly always written
        # الحفناوي / الكيلاني. If the stem is known, emit the conventional
        # 'el-' form (El-Hefnawy) instead of dropping to the character map.
        if len(token) > 3 and token.startswith('ال'):
            stem = token[2:]
            stem_variants = variant_dict.get(stem)
            if stem_variants:
                out_tokens.append('el-' + stem_variants[0])
                continue

        # Fallback: character-level mapping for unknown tokens
        chars = []
        for char in token:
            if char in ARABIC_TO_ENGLISH_MAP:
                chars.append(ARABIC_TO_ENGLISH_MAP[char])
            elif char.isascii():
                chars.append(char)
        out_tokens.append(''.join(chars))

    return re.sub(r'\s+', ' ', ' '.join(out_tokens)).strip().upper()

def prepare_name_for_screening(raw_name: str) -> tuple:
    """
    Returns: (standardized_english_name, standardized_arabic_name)
    Ensures bidirectional data structures are always populated.
    """
    if not raw_name:
         return ("", "")
         
    raw_name = str(raw_name).strip()
    
    english_name = ""
    arabic_name = ""
    
    if _is_arabic(raw_name):
        arabic_name = normalize_arabic_text(raw_name)
        english_name = transliterate_to_english(arabic_name)
    else:
        # Assume it's English/Latin
        english_name = re.sub(r'\s+', ' ', raw_name).strip().upper()
        # We cannot reverse-transliterate with certainty here dynamically,
        # ML engine handles `generate_arabic_variants` at scale.
        arabic_name = ""

    return (english_name, arabic_name)


def generate_all_spelling_variants(raw_name: str) -> list:
    """
    Every known spelling of raw_name — e.g. for 'حسن' (or 'Hassan'/'Hasan'),
    returns ['hassan', 'hasan', 'hasaan', 'hassaan', ...]. Meant to be
    stored as a record's `aliases`, not just used for the primary
    full_name/original_name spelling picked by prepare_name_for_screening,
    so a search using ANY of these spellings still hits the record
    directly (via name_normalizer.score_match's alias scoring) rather than
    relying solely on fuzzy tolerance between two different spellings.

    Uses complynex_engine.py's generate_english_variants (Arabic input) /
    arabic_utils.py's generate_arabic_variants (English input) — the same
    curated ~180-entry dictionary transliterate_to_english draws from,
    lazy-imported to avoid a circular import at module load time.
    """
    if not raw_name:
        return []
    raw_name = str(raw_name).strip()
    variants = set()
    try:
        if _is_arabic(raw_name):
            from screening.complynex_engine import generate_english_variants
            variants.update(v for v in generate_english_variants(raw_name) if v)
        else:
            from screening.arabic_utils import generate_arabic_variants
            variants.update(v for v in generate_arabic_variants(raw_name) if v)
    except Exception:
        logger.warning(f"generate_all_spelling_variants failed for {raw_name!r}", exc_info=True)
    variants.discard(raw_name.lower())
    return sorted(variants)
