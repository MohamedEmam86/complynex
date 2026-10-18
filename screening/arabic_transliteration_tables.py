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
Arabic Transliteration Tables
==============================
Native implementation of multiple Arabic→English transliteration schemes.
Replaces CAMeL Tools dependency. Pure Python, no external libraries.

Schemes implemented:
- Buckwalter (BW) - standard academic scheme
- Safe Buckwalter (SafeBW) - ASCII-safe variant  
- ODNI/IC - US Intelligence Community standard
- BGN/PCGN - US/UK official geographic names
- ALA-LC - Library of Congress standard
"""

# ── Buckwalter Transliteration ─────────────────────────────────────────
BW_MAP = {
    'ء': "'", 'آ': '|', 'أ': '>', 'ؤ': '&', 'إ': '<',
    'ئ': '}', 'ا': 'A', 'ب': 'b', 'ة': 'p', 'ت': 't',
    'ث': 'v', 'ج': 'j', 'ح': 'H', 'خ': 'x', 'د': 'd',
    'ذ': '*', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': '$',
    'ص': 'S', 'ض': 'D', 'ط': 'T', 'ظ': 'Z', 'ع': 'E',
    'غ': 'g', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l',
    'م': 'm', 'ن': 'n', 'ه': 'h', 'و': 'w', 'ى': 'Y',
    'ي': 'y', 'ً': 'F', 'ٌ': 'N', 'ٍ': 'K', 'َ': 'a',
    'ُ': 'u', 'ِ': 'i', 'ّ': '~', 'ْ': 'o', 'ـ': '_',
}

# ── Safe Buckwalter (ASCII-only) ───────────────────────────────────────
SAFEBW_MAP = {
    'ء': 'C', 'آ': 'M', 'أ': 'O', 'ؤ': 'W', 'إ': 'I',
    'ئ': 'Q', 'ا': 'A', 'ب': 'b', 'ة': 'p', 'ت': 't',
    'ث': 'v', 'ج': 'j', 'ح': 'H', 'خ': 'x', 'د': 'd',
    'ذ': 'V', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'c',
    'ص': 'S', 'ض': 'D', 'ط': 'T', 'ظ': 'Z', 'ع': 'E',
    'غ': 'g', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l',
    'م': 'm', 'ن': 'n', 'ه': 'h', 'و': 'w', 'ى': 'Y',
    'ي': 'y',
}

# ── ODNI/IC Romanization (US Intelligence Community standard) ──────────
ODNI_MAP = {
    'ء': "'", 'آ': 'a', 'أ': 'a', 'ؤ': 'w', 'إ': 'i',
    'ئ': 'y', 'ا': 'a', 'ب': 'b', 'ة': 'a', 'ت': 't',
    'ث': 'th', 'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd',
    'ذ': 'dh', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'sh',
    'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': "'",
    'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l',
    'م': 'm', 'ن': 'n', 'ه': 'h', 'و': 'w', 'ى': 'a',
    'ي': 'y',
}

# ── BGN/PCGN (US Board on Geographic Names) ───────────────────────────
BGN_MAP = {
    'ء': "'", 'آ': 'a', 'أ': 'a', 'ؤ': 'u', 'إ': 'i',
    'ئ': 'i', 'ا': 'a', 'ب': 'b', 'ة': 'at', 'ت': 't',
    'ث': 'th', 'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd',
    'ذ': 'dh', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'sh',
    'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': "'",
    'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l',
    'م': 'm', 'ن': 'n', 'ه': 'h', 'و': 'w', 'ى': 'a',
    'ي': 'y',
}

# ── ALA-LC (Library of Congress) ──────────────────────────────────────
ALALC_MAP = {
    'ء': "'", 'آ': 'ā', 'أ': "'", 'ؤ': "'", 'إ': "'",
    'ئ': "'", 'ا': 'ā', 'ب': 'b', 'ة': 'h', 'ت': 't',
    'ث': 'th', 'ج': 'j', 'ح': 'ḥ', 'خ': 'kh', 'د': 'd',
    'ذ': 'dh', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'sh',
    'ص': 'ṣ', 'ض': 'ḍ', 'ط': 'ṭ', 'ظ': 'ẓ', 'ع': "'",
    'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l',
    'م': 'm', 'ن': 'n', 'ه': 'h', 'و': 'w', 'ى': 'ā',
    'ي': 'y',
}


def transliterate(arabic_text: str, scheme: str = 'odni') -> str:
    """
    Transliterate Arabic text to English using specified scheme.
    
    Args:
        arabic_text: Arabic input string
        scheme: 'bw', 'safebw', 'odni', 'bgn', 'alalc'
    
    Returns:
        English transliteration string
    """
    maps = {
        'bw': BW_MAP,
        'safebw': SAFEBW_MAP,
        'odni': ODNI_MAP,
        'bgn': BGN_MAP,
        'alalc': ALALC_MAP,
    }
    
    char_map = maps.get(scheme.lower(), ODNI_MAP)
    result = []
    for char in arabic_text:
        result.append(char_map.get(char, char if char == ' ' else ''))
    return ''.join(result).strip()


def get_all_transliterations(arabic_text: str) -> list:
    """
    Generate transliterations in all supported schemes.
    Returns deduplicated list of English variants.
    """
    variants = set()
    for scheme in ['odni', 'bgn', 'bw', 'safebw']:
        t = transliterate(arabic_text, scheme)
        if t and t != arabic_text:
            # Clean up empty chars
            t = ' '.join(t.split())
            if len(t) > 2:
                variants.add(t.upper())
                variants.add(t.lower())
    return list(variants)


if __name__ == '__main__':
    test = 'عبد الملك دروكدال'
    print(f"Input: {test}")
    print(f"ODNI:   {transliterate(test, 'odni')}")
    print(f"BGN:    {transliterate(test, 'bgn')}")
    print(f"BW:     {transliterate(test, 'bw')}")
    print(f"SafeBW: {transliterate(test, 'safebw')}")
    print(f"\nAll variants:")
    for v in get_all_transliterations(test):
        print(f"  {v}")
