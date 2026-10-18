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
import logging
from pyarabic import araby
from .arabic_utils import EGYPTIAN_ARABIC_VARIANTS, normalize_arabizi, normalize_prefixes, get_english_variants, generate_compound_variants

logger = logging.getLogger(__name__)

class ArabicNameHandler:
    """
    Intelligent Arabic Name Handler for screening and ML calibrator.
    Provides normalization, similarity calculation, and variation generation.
    """
    
    def __init__(self):
        self.arabic_pattern = re.compile(r'[\u0600-\u06FF]')
        logger.info("ArabicNameHandler initialized.")

    def is_arabic(self, text):
        """Detect if text contains Arabic characters."""
        if not text:
            return False
        return bool(self.arabic_pattern.search(text))

    def normalize_arabic(self, text):
        """Canonical normalization for Arabic text."""
        if not text:
            return ""
            
        # Strip diacritics
        text = araby.strip_tashkeel(text)
        
        # Normalize Alef variants
        text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ٱ', 'ا')
        
        # Normalize Yeh/Maksura
        text = text.replace('ى', 'ي')
        
        # Normalize Teh Marbuta
        text = text.replace('ة', 'ه')
        
        # Normalize Hamza variants
        text = text.replace('ؤ', 'ء').replace('ئ', 'ء')
        
        # Remove Tatweel
        text = araby.strip_tatweel(text)
        
        return ' '.join(text.split()).strip()

    def calculate_arabic_similarity(self, name1, name2):
        """
        Calculate similarity score (0-100) between two Arabic names.
        """
        if not name1 or not name2:
            return 0.0
            
        from rapidfuzz import fuzz
        
        n1 = self.normalize_arabic(name1)
        n2 = self.normalize_arabic(name2)
        
        # Exact match after normalization
        if n1 == n2:
            return 100.0
            
        # Fuzzy ratio
        return float(fuzz.ratio(n1, n2))

    def get_all_variations(self, name):
        """
        Generate comprehensive variations (Arabic & English) for a name.
        """
        variations = {name}
        
        # 1. Normalize Arabic if applicable
        if self.is_arabic(name):
            variations.add(self.normalize_arabic(name))
            
        # 2. English Arabizi/Prefix normalization if Latin
        else:
            variations.add(normalize_arabizi(name))
            variations.add(normalize_prefixes(name))
            
        # 3. Add compound variants
        compounds = generate_compound_variants(name)
        variations.update(compounds)
        
        # 4. Add known English variants (e.g. Gamal/Jamal)
        eng_variants = get_english_variants(name)
        variations.update(eng_variants)
        
        return list(variations)

    def extract_name_components(self, name):
        """
        Extract components (First, Middle, Last) from a name string.
        """
        if not name:
            return {}
            
        parts = name.strip().split()
        if not parts:
            return {}
            
        result = {
            'first_name': parts[0],
            'full_name': name
        }
        
        if len(parts) > 1:
            result['last_name'] = parts[-1]
        if len(parts) > 2:
            result['middle_names'] = parts[1:-1]
            
        return result
