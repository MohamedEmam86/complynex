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
import pyarabic.araby as araby

def normalize_arabic_text(text):
    """
    Normalizes Arabic text:
    - Removes diacritics (Harakaat)
    - Unifies Alef variants (إ, أ, آ -> ا)
    - Unifies Teh Marbuta and Heh (ة -> ه)
    - Unifies Yeh and Alef Maksura (ى -> ي)
    - Removes extra whitespaces
    """
    if not text:
        return ""
    
    # Remove diacritics
    text = araby.strip_tashkeel(text)
    
    # Unify Alef
    text = re.sub("[إأآ]", "ا", text)
    
    # Unify Teh Marbuta
    text = re.sub("ة", "ه", text)
    
    # Unify Yeh/Alef Maksura
    text = re.sub("ى", "ي", text)
    
    # Remove extra spaces
    text = " ".join(text.split())
    
    return text

def normalize_name_canonical(name):
    """
    Generic canonical normalization for any language:
    - Lowercase
    - Remove punctuation
    - Sort tokens alphabetically to handle name reversals
    """
    if not name:
        return ""
    
    # Lowercase and remove common punctuation
    name = name.lower()
    name = re.sub(r'[^\w\s]', '', name)
    
    # Handle Arabic specifics if detected
    if any('\u0600' <= c <= '\u06FF' for c in name):
        name = normalize_arabic_text(name)
    
    # Split into tokens, sort and rejoin
    tokens = name.split()
    tokens.sort()
    
    return " ".join(tokens)
