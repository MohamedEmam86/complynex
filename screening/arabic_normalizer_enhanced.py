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
Enhanced Arabic Name Normalizer for Sanctions Screening
========================================================
Tier 1-grade Arabic normalization using pyarabic + custom phonetic matching.
Designed to catch name variants across Arabic dialects and transliteration schemes.
"""

import re
import unicodedata

# pyarabic for core normalization
try:
    import pyarabic.araby as araby
    PYARABIC_AVAILABLE = True
except ImportError:
    PYARABIC_AVAILABLE = False

# Native transliteration tables (replaces CAMeL Tools)
try:
    from screening.arabic_transliteration_tables import get_all_transliterations as _get_translit
    CAMEL_AVAILABLE = True  # Keep same flag name for compatibility
except ImportError:
    CAMEL_AVAILABLE = False

# Module-level flag for engine import check
ARABIC_ENHANCED = True


# ── Arabic Phoneme Groups (for phonetic matching) ──────────────────────
ARABIC_PHONEME_MAP = {
    # Alef variants → normalized alef
    'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ٳ': 'ا',
    # Hamza variants
    'ئ': 'ي', 'ؤ': 'و',
    # Teh marbuta → teh (end of word equivalence)
    'ة': 'ه',
    # Waw variants
    'ۥ': 'و',
    # Yeh variants
    'ى': 'ي', 'ۦ': 'ي', 'ي': 'ي',
    # Kaf variants (Urdu kaf)
    'ک': 'ك',
    # Heh variants
    'ه': 'ه', 'ھ': 'ه', 'ہ': 'ه',
    # Alef Maqsura
    'ى': 'ي',
}

# Phoneme equivalence classes for fuzzy matching
PHONEME_CLASSES = [
    {'ث', 'س', 'ص'},          # S-class sibilants
    {'ذ', 'ز', 'ظ'},          # Z-class
    {'ح', 'ه', 'خ'},          # H-class gutturals  
    {'ع', 'ء', 'أ', 'إ'},     # Glottal class
    {'ق', 'ك', 'غ'},          # K-class velars
    {'ط', 'ت'},               # T-class
    {'ض', 'د'},               # D-class
    {'ن', 'م'},               # Nasal class (weak)
]

# Arabic definite article and common prefixes to strip for comparison
ARABIC_PREFIXES = ['ال', 'وال', 'بال', 'كال', 'فال', 'لل', 'و', 'ب', 'ف', 'ك', 'ل']

# Common Arabic name component normalizations
NAME_NORMALIZATIONS = {
    'عبد الملك': 'عبد المالك',   # Common variant
    'عبد المالك': 'عبد المالك',
    'عبدالملك': 'عبد المالك',
    'عبدالمالك': 'عبد المالك',
    'ابو': 'أبو',
    'ابن': 'ابن',
    'بن': 'بن',
}


def normalize_arabic_comprehensive(text: str) -> str:
    """
    Full Arabic normalization pipeline for sanctions screening.
    Enhanced version with correct hamza handling.
    """
    if not text:
        return text

    # Step 1: Strip diacritics and tatweel only (NOT normalize_hamza - it corrupts أ→ء)
    if PYARABIC_AVAILABLE:
        text = araby.strip_tashkeel(text)      # Remove diacritics/vowels
        text = araby.strip_tatweel(text)       # Remove tatweel (kashida)
        text = araby.normalize_ligature(text)  # Normalize lam-alef ligatures (لا etc)

    # Step 2: Normalize ALL alef variants → bare alef (must come after strip_tashkeel)
    text = re.sub('[أإآٱأإ]', 'ا', text)

    # Step 3: Normalize hamza variants (waw/yeh with hamza above)
    text = text.replace('ؤ', 'و')
    text = text.replace('ئ', 'ي')
    text = text.replace('ء', 'ا')  # standalone hamza → alef for name matching

    # Step 4: Normalize teh marbuta → heh (end of word)
    text = re.sub(r'ة(?=\s|$)', 'ه', text)

    # Step 5: Normalize yeh variants
    text = re.sub('[ىی]', 'ي', text)

    # Step 6: Normalize كاف variants
    text = text.replace('ک', 'ك')

    # Step 7: Normalize spaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def strip_arabic_articles(text: str) -> str:
    """
    Strip definite articles and common prefixes for comparison.
    Only strips ال prefix (definite article) and وال/بال compounds.
    Does NOT strip standalone particles like بن، ابن، أبو.
    """
    words = text.split()
    result = []
    # Only strip these prefixes — keep بن/ابن/أبو as they are name components
    SAFE_PREFIXES = ['وال', 'بال', 'كال', 'فال', 'لل', 'ال']
    for word in words:
        stripped = word
        for prefix in SAFE_PREFIXES:
            if word.startswith(prefix) and len(word) > len(prefix) + 2:
                stripped = word[len(prefix):]
                break
        result.append(stripped)
    return ' '.join(result)


def normalize_name_components(text: str) -> str:
    """
    Normalize Arabic name components for consistent matching.
    Handles: بن/ابن/ibn, أبو/ابو/abu, attached عبد compounds.
    """
    # Normalize alef first
    text = re.sub('[أإآ]', 'ا', text)

    # Normalize بن/ابن variants → بن
    text = re.sub(r'\bابن\b', 'بن', text)
    text = re.sub(r'\bبن\b', 'بن', text)

    # Normalize أبو/ابو → ابو
    text = re.sub(r'\b[اأ]بو\b', 'ابو', text)

    # Normalize attached عبد compounds → separated
    # عبدالله → عبد الله, عبدالملك → عبد الملك
    text = re.sub(r'عبد([^ ])', r'عبد \1', text)

    # Normalize أم/ام → ام
    text = re.sub(r'\b[أا]م\b', 'ام', text)

    return text.strip()


def get_arabic_phonetic_key(text: str) -> str:
    """
    Generate a phonetic key for Arabic text by collapsing phoneme classes.
    Similar to Soundex but for Arabic phonemes.
    """
    normalized = normalize_arabic_comprehensive(text)
    result = []
    for char in normalized:
        mapped = char
        for phoneme_class in PHONEME_CLASSES:
            if char in phoneme_class:
                mapped = sorted(phoneme_class)[0]  # Use first member as canonical
                break
        result.append(mapped)
    return ''.join(result)


def generate_arabic_name_variants(name: str) -> list:
    """
    Generate multiple normalized variants of an Arabic name for screening.
    Returns list of variants to search against the database.
    """
    variants = set()
    
    # Original
    variants.add(name.strip())
    
    # Comprehensive normalization
    normalized = normalize_arabic_comprehensive(name)
    variants.add(normalized)
    
    # Strip articles
    no_articles = strip_arabic_articles(normalized)
    variants.add(no_articles)
    
    # Apply name normalizations
    for old_pat, new_pat in NAME_NORMALIZATIONS.items():
        if old_pat in name:
            variants.add(name.replace(old_pat, new_pat))
        if old_pat in normalized:
            variants.add(normalized.replace(old_pat, new_pat))

    # Apply component normalization
    try:
        comp_normalized = normalize_name_components(normalized)
        variants.add(comp_normalized)
        variants.add(strip_arabic_articles(comp_normalized))
    except Exception:
        pass
    
    # Remove empty strings
    variants.discard('')
    variants.discard(' ')
    
    return list(variants)


def arabic_similarity_score(name1: str, name2: str) -> float:
    """
    Compute similarity between two Arabic names using multiple methods.
    Returns score 0.0-1.0.
    """
    if not name1 or not name2:
        return 0.0
    
    # Normalize both
    n1 = normalize_arabic_comprehensive(name1)
    n2 = normalize_arabic_comprehensive(name2)
    
    # Exact match after normalization
    if n1 == n2:
        return 1.0
    
    # Strip articles and compare
    s1 = strip_arabic_articles(n1)
    s2 = strip_arabic_articles(n2)
    if s1 == s2:
        return 0.95
    
    # Token-level comparison
    tokens1 = set(s1.split())
    tokens2 = set(s2.split())
    if tokens1 and tokens2:
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        jaccard = intersection / union if union > 0 else 0.0
        if jaccard >= 0.6:
            return 0.85 + (jaccard - 0.6) * 0.375
    
    # Character trigram overlap
    def trigrams(s):
        return set(s[i:i+3] for i in range(len(s)-2))
    
    t1, t2 = trigrams(n1), trigrams(n2)
    if t1 and t2:
        overlap = len(t1 & t2) / max(len(t1), len(t2))
        if overlap >= 0.5:
            return overlap * 0.8
    
    return 0.0


def get_camel_transliterations(arabic_text: str) -> list:
    """
    Generate English transliterations using native tables (ODNI, BGN, BW, SafeBW).
    Native implementation - no external dependencies.
    Returns list of English variants.
    """
    if not CAMEL_AVAILABLE:
        return []
    try:
        return _get_translit(arabic_text)
    except Exception:
        return []


if __name__ == '__main__':
    # Test
    test_names = [
        'عبد الملك دروكدال',
        'عبد المالك دروكدال',
        'عبدالملك دروكدال',
        'أسامة بن لادن',
        'اسامة بن لادن',
    ]
    
    print("Arabic Name Normalizer Test")
    print("=" * 50)
    for name in test_names:
        normalized = normalize_arabic_comprehensive(name)
        variants = generate_arabic_name_variants(name)
        print(f"Input:      {name}")
        print(f"Normalized: {normalized}")
        print(f"Variants:   {variants}")
        print()
