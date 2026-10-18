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
Advanced Deduplication Engine
Handles Arabic ↔ English transliteration matching with fuzzy logic
"""

import jellyfish
from fuzzywuzzy import fuzz
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import logging
import re

logger = logging.getLogger(__name__)


class ArabicEnglishTransliterator:
    """
    Handle Arabic-English transliteration mapping
    Based on Egyptian naming conventions
    """
    
    # Comprehensive transliteration map
    ARABIC_TO_ENGLISH = {
        # Common first names
        'محمد': ['Mohamed', 'Mohammed', 'Mohammad', 'Mohamad', 'Muhammed', 'Muhammad'],
        'أحمد': ['Ahmed', 'Ahmad', 'Ahamed', 'Ahmeed'],
        'علي': ['Ali', 'Aly', 'Alee', 'Aliy'],
        'حسن': ['Hassan', 'Hasan', 'Hasaan', 'Hassen'],
        'حسين': ['Hussein', 'Hussain', 'Husein', 'Hussien', 'Hossein'],
        'خالد': ['Khaled', 'Khalid', 'Khaalid', 'Khaleed'],
        'عمر': ['Omar', 'Omer', 'Umar'],
        'عمرو': ['Amr', 'Amro', 'Omr'],
        'يوسف': ['Youssef', 'Yousef', 'Yusuf', 'Yusef', 'Youseff', 'Joseph'],
        'إبراهيم': ['Ibrahim', 'Ebrahim', 'Ibraheem', 'Abraham'],
        'مصطفى': ['Mostafa', 'Mustafa', 'Mostaffa', 'Mustapha'],
        'محمود': ['Mahmoud', 'Mahmud', 'Mahmood'],
        'عبد الله': ['Abdullah', 'Abdallah', 'Abd Allah', 'Abdalla', 'Abdollah'],
        'عبد الرحمن': ['Abdulrahman', 'Abdelrahman', 'Abd Elrahman', 'Abdel Rahman'],
        'عبد العزيز': ['Abdelaziz', 'Abdul Aziz', 'Abdel Aziz'],
        'عبد الفتاح': ['Abdel Fattah', 'Abdul Fattah', 'Abdelfattah'],
        'السيد': ['Elsayed', 'Al Sayed', 'Alsayed', 'El-Sayed', 'El Sayed', 'Sayed'],
        'الدين': ['Eldin', 'Aldin', 'El-Din', 'Al-Din', 'Eddin'],
        'سعد': ['Saad', 'Saed', "Sa'ad", 'Saeed', 'Said'],
        'فتحي': ['Fathy', 'Fathi', 'Fathie'],
        'طارق': ['Tarek', 'Tarik', 'Tariq'],
        'وليد': ['Waleed', 'Walid', 'Walied'],
        'ياسر': ['Yasser', 'Yaser', 'Yasir'],
        'رامي': ['Ramy', 'Rami', 'Ramee'],
        'عادل': ['Adel', 'Adil', 'Aadel'],
        'كريم': ['Karim', 'Kareem', 'Kariem'],
        'هشام': ['Hisham', 'Hesham', 'Heshaam'],
        'سامي': ['Sami', 'Samee', 'Samy'],
        'شريف': ['Sherif', 'Shareef', 'Sharif'],
        'رضا': ['Reda', 'Rida', 'Reza'],
        'منصور': ['Mansour', 'Mansoor', 'Mansor'],
        'شاهين': ['Shaheen', 'Shahin', 'Chahine'],
        
        # Common titles/positions
        'وزير': ['Minister', 'Wazir'],
        'محافظ': ['Governor', 'Mohafez'],
        'نائب': ['Deputy', 'Vice', 'Naeb'],
        'رئيس': ['President', 'Chairman', 'Chief', 'Raees'],
    }
    
    # Build reverse mapping
    ENGLISH_TO_ARABIC = {}
    for arabic, english_list in ARABIC_TO_ENGLISH.items():
        for eng in english_list:
            if eng.lower() not in ENGLISH_TO_ARABIC:
                ENGLISH_TO_ARABIC[eng.lower()] = []
            ENGLISH_TO_ARABIC[eng.lower()].append(arabic)
    
    @classmethod
    def get_english_variants(cls, arabic_name: str) -> List[str]:
        """Get all possible English transliterations of an Arabic name"""
        variants = set()
        
        # Split name into parts
        parts = arabic_name.split()
        
        # For each part, get variants
        part_variants = []
        for part in parts:
            if part in cls.ARABIC_TO_ENGLISH:
                part_variants.append(cls.ARABIC_TO_ENGLISH[part])
            else:
                # Unknown word, keep as is
                part_variants.append([part])
        
        # Generate all combinations
        if not part_variants:
            return []
        
        def combine_variants(lists):
            if not lists:
                return [[]]
            first = lists[0]
            rest = combine_variants(lists[1:])
            result = []
            for item in first:
                for combo in rest:
                    result.append([item] + combo)
            return result
        
        combinations = combine_variants(part_variants)
        variants = [' '.join(combo) for combo in combinations]
        
        return list(set(variants))[:50]  # Limit to 50 variants
    
    @classmethod
    def get_arabic_variants(cls, english_name: str) -> List[str]:
        """Get possible Arabic versions of an English name"""
        variants = set()
        
        # Split and normalize
        parts = english_name.lower().split()
        
        # For each part, get Arabic variants
        part_variants = []
        for part in parts:
            if part in cls.ENGLISH_TO_ARABIC:
                part_variants.append(cls.ENGLISH_TO_ARABIC[part])
            else:
                # Unknown word, skip
                part_variants.append([])
        
        # Generate combinations
        if not part_variants or not any(part_variants):
            return []
        
        def combine_variants(lists):
            if not lists:
                return [[]]
            first = lists[0]
            if not first:
                return combine_variants(lists[1:])
            rest = combine_variants(lists[1:])
            result = []
            for item in first:
                for combo in rest:
                    result.append([item] + combo)
            return result
        
        combinations = combine_variants(part_variants)
        variants = [' '.join(combo) for combo in combinations if combo]
        
        return list(set(variants))[:50]
    
    @classmethod
    def is_arabic(cls, text: str) -> bool:
        """Check if text contains Arabic characters"""
        return any('\u0600' <= c <= '\u06FF' for c in text)


class NameMatcher:
    """
    Advanced name matching with transliteration support
    """
    
    def __init__(self):
        self.transliterator = ArabicEnglishTransliterator()
    
    def calculate_similarity(self, name1: str, name2: str) -> float:
        """
        Calculate similarity between two names
        Handles Arabic-English transliteration
        
        Returns: Score from 0.0 to 1.0
        """
        if not name1 or not name2:
            return 0.0
        
        # Normalize
        name1 = self._normalize_name(name1)
        name2 = self._normalize_name(name2)
        
        # Direct comparison
        direct_score = self._fuzzy_match(name1, name2)
        
        # Check if cross-script (Arabic vs English)
        is_arabic_1 = self.transliterator.is_arabic(name1)
        is_arabic_2 = self.transliterator.is_arabic(name2)
        
        if is_arabic_1 != is_arabic_2:
            # Different scripts - try transliteration
            translit_score = self._transliteration_match(name1, name2)
            return max(direct_score, translit_score)
        
        return direct_score
    
    def _normalize_name(self, name: str) -> str:
        """Normalize name for comparison"""
        # Remove extra spaces
        name = ' '.join(name.split())
        
        # Remove common prefixes/suffixes for Arabic names
        prefixes = ['ال', 'Al-', 'El-', 'Al ', 'El ']
        for prefix in prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):]
        
        return name.strip()
    
    def _fuzzy_match(self, name1: str, name2: str) -> float:
        """Calculate fuzzy match score using multiple algorithms"""
        # Use multiple algorithms and take weighted average
        
        # 1. Token Sort Ratio (good for name parts in different order)
        token_sort = fuzz.token_sort_ratio(name1, name2) / 100.0
        
        # 2. Token Set Ratio (ignores duplicate words)
        token_set = fuzz.token_set_ratio(name1, name2) / 100.0
        
        # 3. Partial Ratio (good for partial matches)
        partial = fuzz.partial_ratio(name1, name2) / 100.0
        
        # 4. Jaro-Winkler (good for typos)
        jaro = jellyfish.jaro_winkler_similarity(name1, name2)
        
        # Weighted combination
        score = (
            token_sort * 0.3 +
            token_set * 0.3 +
            partial * 0.2 +
            jaro * 0.2
        )
        
        return score
    
    def _transliteration_match(self, name1: str, name2: str) -> float:
        """Match across Arabic-English transliteration"""
        is_arabic_1 = self.transliterator.is_arabic(name1)
        
        if is_arabic_1:
            # name1 is Arabic, name2 is English
            variants = self.transliterator.get_english_variants(name1)
        else:
            # name1 is English, name2 is Arabic
            variants = self.transliterator.get_arabic_variants(name1)
        
        if not variants:
            return 0.0
        
        # Compare name2 with all variants
        scores = [self._fuzzy_match(variant, name2) for variant in variants[:20]]
        
        return max(scores) if scores else 0.0
    
    def calculate_component_similarity(self, name1: str, name2: str) -> Dict[str, float]:
        """
        Calculate similarity for name components (first, middle, last)
        
        Returns:
            {
                'first_name': float,
                'last_name': float,
                'full_name': float
            }
        """
        parts1 = name1.split()
        parts2 = name2.split()
        
        result = {
            'first_name': 0.0,
            'last_name': 0.0,
            'full_name': self.calculate_similarity(name1, name2)
        }
        
        # First name comparison
        if parts1 and parts2:
            result['first_name'] = self.calculate_similarity(parts1[0], parts2[0])
        
        # Last name comparison
        if len(parts1) >= 2 and len(parts2) >= 2:
            result['last_name'] = self.calculate_similarity(parts1[-1], parts2[-1])
        
        return result


class DateMatcher:
    """
    Compare dates with tolerance for data entry errors
    """
    
    @staticmethod
    def calculate_similarity(date1: Optional[datetime], date2: Optional[datetime]) -> float:
        """
        Calculate date similarity
        
        Returns: 0.0 to 1.0
        """
        if not date1 or not date2:
            return 0.0
        
        # Exact match
        if date1 == date2:
            return 1.0
        
        # Calculate difference in days
        diff_days = abs((date1 - date2).days)
        
        # Scoring based on difference
        if diff_days == 0:
            return 1.0
        elif diff_days <= 7:  # Within a week (data entry error)
            return 0.9
        elif diff_days <= 30:  # Within a month
            return 0.7
        elif diff_days <= 365:  # Within a year (year might be correct)
            return 0.5
        elif diff_days <= 1825:  # Within 5 years
            return 0.3
        else:
            return 0.0
    
    @staticmethod
    def year_matches(date1: Optional[datetime], date2: Optional[datetime]) -> bool:
        """Check if years match"""
        if not date1 or not date2:
            return False
        return date1.year == date2.year


class PositionMatcher:
    """
    Compare political positions to detect overlaps
    """
    
    def __init__(self):
        self.name_matcher = NameMatcher()
    
    def calculate_overlap(self, positions1: List[Dict], positions2: List[Dict]) -> float:
        """
        Calculate overlap between two lists of positions
        
        Returns: 0.0 to 1.0
        """
        if not positions1 or not positions2:
            return 0.0
        
        matches = 0
        total_comparisons = 0
        
        for pos1 in positions1:
            for pos2 in positions2:
                total_comparisons += 1
                
                # Compare position titles
                title_sim = self._compare_positions(pos1, pos2)
                
                # Compare dates
                date_overlap = self._date_overlap(pos1, pos2)
                
                # If both title and dates match, it's a strong match
                if title_sim > 0.7 and date_overlap > 0.5:
                    matches += 1
        
        if total_comparisons == 0:
            return 0.0
        
        return matches / total_comparisons
    
    def _compare_positions(self, pos1: Dict, pos2: Dict) -> float:
        """Compare position titles"""
        title1_en = pos1.get('title_en', '')
        title1_ar = pos1.get('title_ar', '')
        title2_en = pos2.get('title_en', '')
        title2_ar = pos2.get('title_ar', '')
        
        scores = []
        
        if title1_en and title2_en:
            scores.append(self.name_matcher.calculate_similarity(title1_en, title2_en))
        
        if title1_ar and title2_ar:
            scores.append(self.name_matcher.calculate_similarity(title1_ar, title2_ar))
        
        if title1_en and title2_ar:
            scores.append(self.name_matcher.calculate_similarity(title1_en, title2_ar))
        
        if title1_ar and title2_en:
            scores.append(self.name_matcher.calculate_similarity(title1_ar, title2_en))
        
        return max(scores) if scores else 0.0
    
    def _date_overlap(self, pos1: Dict, pos2: Dict) -> float:
        """Calculate temporal overlap between positions"""
        start1 = pos1.get('start_date')
        end1 = pos1.get('end_date')
        start2 = pos2.get('start_date')
        end2 = pos2.get('end_date')
        
        if not start1 or not start2:
            return 0.0
        
        # Convert to datetime if strings
        if isinstance(start1, str):
            start1 = datetime.fromisoformat(start1)
        if isinstance(start2, str):
            start2 = datetime.fromisoformat(start2)
        if end1 and isinstance(end1, str):
            end1 = datetime.fromisoformat(end1)
        if end2 and isinstance(end2, str):
            end2 = datetime.fromisoformat(end2)
        
        # If no end dates, assume current
        if not end1:
            end1 = datetime.now()
        if not end2:
            end2 = datetime.now()
        
        # Calculate overlap
        latest_start = max(start1, start2)
        earliest_end = min(end1, end2)
        
        if latest_start <= earliest_end:
            # There is overlap
            overlap_days = (earliest_end - latest_start).days
            total_days = max((end1 - start1).days, (end2 - start2).days)
            
            if total_days > 0:
                return overlap_days / total_days
        
        return 0.0


class DeduplicationEngine:
    """
    Main deduplication engine
    Combines all matching strategies to find duplicates
    """
    
    def __init__(self, db_connection):
        self.db = db_connection
        self.name_matcher = NameMatcher()
        self.date_matcher = DateMatcher()
        self.position_matcher = PositionMatcher()
    
    def find_duplicates(self, pep_record: Dict, threshold: float = 0.75) -> List[Tuple[int, float, str]]:
        """
        Find potential duplicates for a PEP record
        
        Args:
            pep_record: New PEP record to check
            threshold: Minimum similarity score (0.0 to 1.0)
        
        Returns:
            List of (pep_id, similarity_score, match_reason)
        """
        logger.info(f"Searching for duplicates of: {pep_record.get('canonical_name_en')}")
        
        # Step 1: Find candidates using fast filters
        candidates = self._get_candidates(pep_record)
        
        logger.info(f"Found {len(candidates)} candidates to check")
        
        # Step 2: Calculate detailed similarity for each candidate
        matches = []
        for candidate in candidates:
            score, reason = self._calculate_match_score(pep_record, candidate)
            
            if score >= threshold:
                matches.append((candidate['id'], score, reason))
        
        # Sort by score
        matches.sort(key=lambda x: x[1], reverse=True)
        
        logger.info(f"Found {len(matches)} potential duplicates above threshold {threshold}")
        
        return matches
    
    def _get_candidates(self, pep_record: Dict) -> List[Dict]:
        """
        Fast pre-filtering to get potential duplicate candidates
        Uses indexes for speed
        """
        candidates = []
        
        name_en = pep_record.get('canonical_name_en', '')
        name_ar = pep_record.get('canonical_name_ar', '')
        dob = pep_record.get('date_of_birth')
        
        # Strategy 1: Trigram similarity on English name
        if name_en:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT id, canonical_name_en, canonical_name_ar, date_of_birth
                FROM pep_master
                WHERE similarity(canonical_name_en, %s) > 0.3
                LIMIT 50
            """, (name_en,))
            candidates.extend([dict(row) for row in cursor.fetchall()])
        
        # Strategy 2: Trigram similarity on Arabic name
        if name_ar:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT id, canonical_name_en, canonical_name_ar, date_of_birth
                FROM pep_master
                WHERE similarity(canonical_name_ar, %s) > 0.3
                LIMIT 50
            """, (name_ar,))
            candidates.extend([dict(row) for row in cursor.fetchall()])
        
        # Strategy 3: Same date of birth
        if dob:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT id, canonical_name_en, canonical_name_ar, date_of_birth
                FROM pep_master
                WHERE date_of_birth = %s
                   OR ABS(date_of_birth - %s) <= 365
                LIMIT 50
            """, (dob, dob))
            candidates.extend([dict(row) for row in cursor.fetchall()])
        
        # Strategy 4: Check aliases
        if name_en or name_ar:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT DISTINCT p.id, p.canonical_name_en, p.canonical_name_ar, p.date_of_birth
                FROM pep_master p
                JOIN pep_aliases a ON p.id = a.pep_id
                WHERE a.alias_name % %s OR a.alias_name % %s
                LIMIT 50
            """, (name_en or '', name_ar or ''))
            candidates.extend([dict(row) for row in cursor.fetchall()])
        
        # Remove duplicates (by id)
        seen_ids = set()
        unique_candidates = []
        for candidate in candidates:
            if candidate['id'] not in seen_ids:
                seen_ids.add(candidate['id'])
                unique_candidates.append(candidate)
        
        return unique_candidates
    
    def _calculate_match_score(self, record1: Dict, record2: Dict) -> Tuple[float, str]:
        """
        Calculate comprehensive match score between two records
        
        Returns: (score, reason)
        """
        scores = {}
        reasons = []
        
        # 1. Name similarity (weight: 0.4)
        name_sim = self._compare_names(record1, record2)
        scores['name'] = name_sim
        if name_sim > 0.8:
            reasons.append(f'name_match:{name_sim:.2f}')
        
        # 2. Date of birth similarity (weight: 0.3)
        dob_sim = self.date_matcher.calculate_similarity(
            record1.get('date_of_birth'),
            record2.get('date_of_birth')
        )
        scores['dob'] = dob_sim
        if dob_sim > 0.9:
            reasons.append(f'dob_match:{dob_sim:.2f}')
        
        # 3. Position overlap (weight: 0.3)
        # Fetch positions from database
        positions1 = self._get_positions(record1.get('id'))
        positions2 = self._get_positions(record2.get('id'))
        
        position_sim = self.position_matcher.calculate_overlap(positions1, positions2)
        scores['position'] = position_sim
        if position_sim > 0.5:
            reasons.append(f'position_overlap:{position_sim:.2f}')
        
        # Calculate weighted score
        final_score = (
            scores['name'] * 0.4 +
            scores['dob'] * 0.3 +
            scores['position'] * 0.3
        )
        
        reason_str = ', '.join(reasons) if reasons else 'low_similarity'
        
        return final_score, reason_str
    
    def _compare_names(self, record1: Dict, record2: Dict) -> float:
        """Compare names between two records"""
        name1_en = record1.get('canonical_name_en', '')
        name1_ar = record1.get('canonical_name_ar', '')
        name2_en = record2.get('canonical_name_en', '')
        name2_ar = record2.get('canonical_name_ar', '')
        
        scores = []
        
        # Compare all combinations
        if name1_en and name2_en:
            scores.append(self.name_matcher.calculate_similarity(name1_en, name2_en))
        
        if name1_ar and name2_ar:
            scores.append(self.name_matcher.calculate_similarity(name1_ar, name2_ar))
        
        if name1_en and name2_ar:
            scores.append(self.name_matcher.calculate_similarity(name1_en, name2_ar))
        
        if name1_ar and name2_en:
            scores.append(self.name_matcher.calculate_similarity(name1_ar, name2_en))
        
        return max(scores) if scores else 0.0
    
    def _get_positions(self, pep_id: Optional[int]) -> List[Dict]:
        """Fetch positions from database"""
        if not pep_id:
            return []
        
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT position_title_en, position_title_ar, start_date, end_date
            FROM pep_positions
            WHERE pep_id = %s
        """, (pep_id,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def merge_records(self, primary_id: int, duplicate_id: int) -> bool:
        """
        Merge duplicate PEP records
        
        Args:
            primary_id: ID to keep
            duplicate_id: ID to merge into primary
        
        Returns:
            Success status
        """
        logger.info(f"Merging PEP {duplicate_id} into {primary_id}")
        
        try:
            cursor = self.db.cursor()
            
            # 1. Move aliases
            cursor.execute("""
                UPDATE pep_aliases
                SET pep_id = %s
                WHERE pep_id = %s
            """, (primary_id, duplicate_id))
            
            # 2. Move positions
            cursor.execute("""
                UPDATE pep_positions
                SET pep_id = %s
                WHERE pep_id = %s
            """, (primary_id, duplicate_id))
            
            # 3. Move corporate links
            cursor.execute("""
                UPDATE pep_corporate_links
                SET pep_id = %s
                WHERE pep_id = %s
            """, (primary_id, duplicate_id))
            
            # 4. Move sources
            cursor.execute("""
                UPDATE pep_sources
                SET pep_id = %s
                WHERE pep_id = %s
            """, (primary_id, duplicate_id))
            
            # 5. Update duplicate candidates table
            cursor.execute("""
                UPDATE pep_duplicate_candidates
                SET status = 'merged',
                    merged_into = %s,
                    reviewed_at = NOW()
                WHERE pep_id_1 = %s OR pep_id_2 = %s
            """, (primary_id, duplicate_id, duplicate_id))
            
            # 6. Delete the duplicate record
            cursor.execute("""
                DELETE FROM pep_master
                WHERE id = %s
            """, (duplicate_id,))
            
            # 7. Update source count and confidence for primary
            cursor.execute("""
                UPDATE pep_master
                SET source_count = (
                        SELECT COUNT(DISTINCT source_name)
                        FROM pep_sources
                        WHERE pep_id = %s AND is_active = 1
                    ),
                    last_updated = NOW()
                WHERE id = %s
            """, (primary_id, primary_id))
            
            self.db.commit()
            
            logger.info(f"Successfully merged PEP {duplicate_id} into {primary_id}")
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error merging records: {str(e)}")
            return False
