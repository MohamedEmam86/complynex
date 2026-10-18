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

import re
from rapidfuzz import fuzz

def normalize_address(text):
    """
    Normalize address string for comparison.
    - Lowercase
    - Remove special chars
    - Expand common abbreviations
    """
    if not text:
        return ""
        
    # Lowercase and strip
    text = str(text).lower().strip()
    
    # Remove special chars (keep alphanumeric and spaces)
    text = re.sub(r'[^a-zo0-9\s]', ' ', text)
    
    # Common abbreviations
    replacements = {
        r'\bstr\b': 'street',
        r'\bst\b': 'street',
        r'\brd\b': 'road',
        r'\bave\b': 'avenue',
        r'\bblvd\b': 'boulevard',
        r'\bapt\b': 'apartment',
        r'\bno\b': 'number',
        r'\bgov\b': 'governorate',
        r'\bdist\b': 'district'
    }
    
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
        
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def compare_addresses(addr1, addr2):
    """
    Compare two addresses and return a similarity score (0-100).
    Using token sort ratio to handle different component ordering.
    """
    if not addr1 or not addr2:
        return 0
        
    norm1 = normalize_address(addr1)
    norm2 = normalize_address(addr2)
    
    if not norm1 or not norm2:
        return 0
        
    # Use token sort ratio to handle "Cairo, Maadi" vs "Maadi, Cairo"
    return fuzz.token_sort_ratio(norm1, norm2)
