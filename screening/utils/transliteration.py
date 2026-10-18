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

# Simple Arabic-English transliteration mapping
# This is a basic rule-based mapper useful for fallback fuzzy matching

TRANS_MAP = {
    'أ': 'a', 'إ': 'a', 'آ': 'a', 'ا': 'a',
    'ب': 'b',
    'ت': 't',
    'ث': 'th',
    'ج': 'j', 'ج': 'g', # variants
    'ح': 'h',
    'خ': 'kh',
    'د': 'd',
    'ذ': 'dh',
    'ر': 'r',
    'ز': 'z',
    'س': 's',
    'ش': 'sh',
    'ص': 's',
    'ض': 'd',
    'ط': 't',
    'ظ': 'z',
    'ع': 'a',
    'غ': 'gh',
    'ف': 'f',
    'ق': 'q', 'ق': 'k',
    'ك': 'k',
    'ل': 'l',
    'م': 'm',
    'ن': 'n',
    'ه': 'h',
    'و': 'w', 'و': 'o', 'و': 'u',
    'ي': 'y', 'ي': 'i',
    'ى': 'a',
    'ة': 'a', 'ة': 't',
    ' ': ' '
}

def transliterate_arabic_to_english(text):
    """
    Very basic transliteration of Arabic text to English.
    Used to generate English-like candidates from Arabic names.
    """
    if not text:
        return ""
    
    # Simple character by character mapping
    # Note: This doesn't handle Shadda or complex vowel rules
    res = []
    for char in text:
        res.append(TRANS_MAP.get(char, ""))
    
    return "".join(res)
