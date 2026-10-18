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

from screening.db_pool import db_pool
"""
Ultimate Hybrid Screening Engine v2.0
Core matching logic with Arabic support and Cross-lingual intelligence.
"""

import jellyfish
import json
import sqlite3
import logging
from datetime import datetime
from rapidfuzz import fuzz
from .config import ScreeningConfig
from .utils.normalization import normalize_name_canonical
from .utils.normalization import normalize_name_canonical
from .utils.transliteration import transliterate_arabic_to_english

try:
    from .semantic_matcher import SemanticSequenceMatcher
except ImportError:
    SemanticSequenceMatcher = None

logger = logging.getLogger(__name__)

class HybridScreeningEngine:
    def __init__(self, db_path):
        self.db_path = db_path
        self.db_conn = None
        self.db_path = db_path
        self.db_conn = None
        self.settings = self._load_settings()
        
        if SemanticSequenceMatcher:
            self.semantic_matcher = SemanticSequenceMatcher()
        else:
            self.semantic_matcher = None

    def _load_settings(self):
        """Load settings from DB or fallback to config.py defaults."""
        settings = {
            'FUZZY_RATIO_WEIGHT': ScreeningConfig.FUZZY_RATIO_WEIGHT,
            'JARO_WINKLER_WEIGHT': ScreeningConfig.JARO_WINKLER_WEIGHT,
            'PHONETIC_WEIGHT': ScreeningConfig.PHONETIC_WEIGHT,
            'PARTIAL_RATIO_WEIGHT': ScreeningConfig.PARTIAL_RATIO_WEIGHT,
            'AUTO_MATCH_THRESHOLD': ScreeningConfig.AUTO_MATCH_THRESHOLD,
            'POTENTIAL_MATCH_THRESHOLD': ScreeningConfig.POTENTIAL_MATCH_THRESHOLD,
            'LOW_MATCH_MIN': ScreeningConfig.LOW_MATCH_MIN
        }
        
        conn = None
        try:
            conn = db_pool.checkout_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM screening_settings")
            rows = cursor.fetchall()
            for row in rows:
                key = row['key']
                val = row['value']
                if key in settings:
                    settings[key] = float(val)
        except Exception as e:
            logger.warning(f"Could not load settings from DB: {e}. Using defaults.")
        finally:
            if conn:
                db_pool.return_connection(conn)
            
        return settings
    
    def connect_db(self):
        if not self.db_conn:
            self.db_conn = db_pool.checkout_connection()
            self.db_conn.row_factory = sqlite3.Row

    def is_arabic(self, text):
        if not text: return False
        return any('\u0600' <= c <= '\u06FF' for c in text)

    def screen_person(self, name, date_of_birth=None, country=None, 
                     nationality=None, gender=None):
        """
        Advanced screening with Arabic/English intelligence.
        """
        start_time = datetime.now()
        self.connect_db()
        
        # 1. Normalize Input
        # We detect script and normalize accordingly
        is_input_arabic = self.is_arabic(name)
        norm_input = normalize_name_canonical(name)
        
        # Generation of phonetic/transliterated candidates for matching
        # If English, we might want to check against Arabic records too.
        # If Arabic, we definitely want to check against English records.
        trans_input = None
        if is_input_arabic:
            trans_input = normalize_name_canonical(transliterate_arabic_to_english(name))
        else:
            # We can't easily auto-transliterate English to Arabic without camel_tools,
            # so we rely completely on Semantic Matcher for English->Arabic retrieval.
            pass
            
        soundex_input = jellyfish.soundex(norm_input) if not is_input_arabic else None
        metaphone_input = jellyfish.metaphone(norm_input) if not is_input_arabic else None

        logger.info(f"Screening: {name} (Arabic: {is_input_arabic})")
        
        # 2. Candidate Selection (Recall Phase)
        candidates = self._get_candidates(norm_input, trans_input, soundex_input, metaphone_input, date_of_birth, country)
        
        # 3. Scoring (Precision Phase)
        scored_matches = []
        for cand in candidates:
            score_data = self._calculate_match_score(
                norm_input, trans_input, cand, 
                date_of_birth, country, nationality, gender
            )
            
            if score_data['match_score'] >= self.settings['LOW_MATCH_MIN']:
                scored_matches.append(score_data)

        # Sort by score
        scored_matches.sort(key=lambda x: x['match_score'], reverse=True)
        
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        highest_score = scored_matches[0]['match_score'] if scored_matches else 0.0
        
        # Result classification
        result = 'CLEAR'
        if highest_score >= self.settings['AUTO_MATCH_THRESHOLD']:
            result = 'CONFIRMED_HIT'
        elif highest_score >= self.settings['POTENTIAL_MATCH_THRESHOLD']:
            result = 'POTENTIAL_MATCH'
        elif scored_matches:
            result = 'LOW_MATCH'

        return {
            'screening_result': result,
            'total_matches': len(scored_matches),
            'highest_score': highest_score,
            'matches': scored_matches[:20], # Return top 20
            'processing_time_ms': int(processing_time),
            'recommendation': self._get_recommendation(result)
        }

    def _get_candidates(self, norm_input, trans_input, soundex, metaphone, dob=None, country=None):
        """Fetch potential matches from Elasticsearch in 200ms using Multi-Attribute Scoring."""
        try:
            from elasticsearch import Elasticsearch
            es = Elasticsearch("http://localhost:9200", request_timeout=3)
            
            search_query = norm_input
            if trans_input:
                search_query += f" {trans_input}"
                
            # Must match the name (Fuzzy)
            must_clauses = [
                {
                    "multi_match": {
                        "query": search_query,
                        "fields": ["search_names^3", "full_name^2"],
                        "fuzziness": "AUTO"
                    }
                }
            ]
            
            # Should match DOB/Country (Massive score boost if they match!)
            should_clauses = []
            if dob:
                should_clauses.append({"match": {"date_of_birth": {"query": str(dob), "boost": 3.0}}})
            if country:
                should_clauses.append({"match": {"nationality": {"query": str(country), "boost": 2.0}}})
                
            query = {
                "size": 100,
                "query": {
                    "bool": {
                        "must": must_clauses,
                        "should": should_clauses
                    }
                }
            }
            
            res = es.search(index="aml_watchlist", body=query)
            
            candidates = []
            for hit in res['hits']['hits']:
                s = hit['_source']
                # Rebuild the dictionary exactly as the ML Precision Engine expects it
                candidates.append({
                    'id': s.get('db_id'),
                    'full_name': s.get('full_name') or '',
                    'name_normalized': s.get('search_names') or '',
                    'dataset': s.get('source') or '',
                    'list_type': 'SANCTIONS',
                    'topics': '',
                    'countries': s.get('nationality') or '',
                    'date_of_birth': s.get('date_of_birth') or '',
                    'year_of_birth': '',
                    'nationality': s.get('nationality') or '',
                    'risk_level': s.get('risk_level') or 'UNKNOWN',
                    'source': s.get('source') or '',
                    'original_name': s.get('full_name') or '',
                    'aliases': s.get('search_names') or '',
                    'entity_type': 'INDIVIDUAL',
                    'properties': '',
                    'gender': '',
                    'details': '',
                    'full_name_arabic': '',
                    'aliases_arabic': '',
                    'name_soundex': '',
                    'name_metaphone': ''
                })
            return candidates
            
        except Exception as e:
            import logging
            logging.error(f"Elasticsearch failed, returning empty list: {e}")
            return []


    def _calculate_match_score(self, norm_input, trans_input, cand, 
                               dob, country, nationality, gender):
        """Detailed scoring for a candidate."""
        
        # Primary name to match against
        cand_name_norm = cand['name_normalized'] or ''
        cand_name_ar = cand['full_name_arabic'] or cand['original_name'] or ''
        
        # 1. Phonetic Score
        phonetic_match = 0
        if cand['name_soundex'] and jellyfish.soundex(norm_input) == cand['name_soundex']:
            phonetic_match = 1
        elif cand['name_metaphone'] and jellyfish.metaphone(norm_input) == cand['name_metaphone']:
            phonetic_match = 1
            
        # 2. Fuzzy Ratio (Levenshtein)
        # Match English vs English, Arabic vs Arabic
        ratio = 0.0
        if self.is_arabic(norm_input) and cand_name_ar:
            # Arabic to Arabic match
            norm_cand_ar = normalize_name_canonical(cand_name_ar)
            ratio = fuzz.ratio(norm_input, norm_cand_ar) / 100.0
        else:
            # English (or transliterated) match
            ratio = fuzz.ratio(norm_input, cand_name_norm) / 100.0
            # ALWAYS check the original name just in case it's a cross-lingual hit
            if cand_name_ar:
                ar_ratio = fuzz.ratio(norm_input, normalize_name_canonical(cand_name_ar)) / 100.0
                ratio = max(ratio, ar_ratio)
            
        if trans_input:
             trans_r = fuzz.ratio(trans_input, cand_name_norm) / 100.0
             if cand_name_ar:
                 trans_r = max(trans_r, fuzz.ratio(trans_input, normalize_name_canonical(cand_name_ar)) / 100.0)
             ratio = max(ratio, trans_r)
        
        # 3. Jaro-Winkler
        jw = 0.0
        if self.is_arabic(norm_input) and cand_name_ar:
             jw = jellyfish.jaro_winkler_similarity(norm_input, normalize_name_canonical(cand_name_ar))
        else:
             jw = jellyfish.jaro_winkler_similarity(norm_input, cand_name_norm)
             
        if trans_input:
            jw = max(jw, jellyfish.jaro_winkler_similarity(trans_input, cand_name_norm))
            
        # 4. Partial Ratio
        partial = fuzz.partial_ratio(norm_input, cand['full_name']) / 100.0
        
        # Ensemble Base Score
        semantic_score = cand.get('semantic_score', 0.0) / 100.0
        base_score = 0.0
        
        if semantic_score > 0:
            if semantic_score >= 0.95 and (ratio >= 0.55 or jw >= 0.65 or partial >= 0.70):
                # Absolute undeniable semantic match WITH baseline string similarity
                # Overrides everything else. This IS the person.
                base_score = max(0.95, semantic_score * 0.90 + ratio * 0.10)
            elif semantic_score >= 0.88 and (ratio >= 0.45 or jw >= 0.55 or partial >= 0.60):
                # Strong semantic correlation, mixed with string distance
                base_score = (
                    semantic_score * 0.70 +
                    ratio * 0.15 +
                    jw * 0.15
                )
            else:
                # Semantic vectors disagree with the strings (e.g. Aliyu vs Ali -> sem 96% but string is different!)
                traditional_score = (
                    ratio * self.settings['FUZZY_RATIO_WEIGHT'] +
                    jw * self.settings['JARO_WINKLER_WEIGHT'] +
                    phonetic_match * self.settings['PHONETIC_WEIGHT'] +
                    partial * self.settings['PARTIAL_RATIO_WEIGHT']
                )
                base_score = min(traditional_score, 0.74) # Cap severely below auto-hit threshold if semantic is unsupported by string rules
        else:
            base_score = (
                ratio * self.settings['FUZZY_RATIO_WEIGHT'] +
                jw * self.settings['JARO_WINKLER_WEIGHT'] +
                phonetic_match * self.settings['PHONETIC_WEIGHT'] +
                partial * self.settings['PARTIAL_RATIO_WEIGHT']
            )
        
        # Exact match favoritism
        # Check against English normalized OR Arabic normalized
        is_exact = (norm_input == cand_name_norm)
        if not is_exact and cand_name_ar:
            if norm_input == normalize_name_canonical(cand_name_ar):
                is_exact = True
                
        if is_exact:
            base_score = max(1.0, base_score + ScreeningConfig.EXACT_MATCH_FAVORITISM)

        # Attribute Adjustments
        dob_adj = self._calculate_dob_adjustment(dob, cand)
        country_adj = self._calculate_country_adjustment(country or nationality, cand)
        gender_adj = self._calculate_gender_adjustment(gender, cand)
        
        final_score = min(1.0, base_score + dob_adj + country_adj + gender_adj)
        
        return {
            'watchlist_id': cand['id'],
            'watchlist_name': cand['full_name'],
            'watchlist_name_ar': cand['full_name_arabic'] or cand['original_name'],
            'match_score': round(final_score * 100, 2), # Convert back to 100-scale for UI
            'dataset': cand['dataset'],
            'list_type': cand['list_type'],
            'risk_level': cand['risk_level'],
            'details': json.loads(cand.get('details') or '{}'),
            'score_breakdown': {
                'fuzzy_ratio': round(ratio * 100, 2),
                'jaro_winkler': round(jw * 100, 2),
                'phonetic': phonetic_match * 100,
                'partial': round(partial * 100, 2),
                'semantic_score': round(cand.get('semantic_score', 0.0), 2),
                'dob_adj': dob_adj,
                'country_adj': country_adj
            }
        }

    def _calculate_dob_adjustment(self, dob, cand):
        if not dob: return 0.0
        cand_dob = cand['date_of_birth']
        cand_yob = cand['year_of_birth']
        
        # Convert dob to string for comparison if it's a date object
        dob_str = dob if isinstance(dob, str) else dob.isoformat()
        
        if cand_dob and dob_str[:10] == cand_dob[:10]:
            return ScreeningConfig.DOB_EXACT_MATCH_BONUS
        elif cand_yob:
            input_year = int(dob_str[:4])
            if input_year == cand_yob:
                return ScreeningConfig.YEAR_MATCH_BONUS
            else:
                return ScreeningConfig.YEAR_MISMATCH_PENALTY
        return 0.0

    def _calculate_country_adjustment(self, country, cand):
        if not country: return 0.0
        cand_countries = json.loads(cand['countries']) if cand['countries'] else []
        cand_nat = cand['nationality']
        
        search_vals = [country.lower()]
        if cand_nat: search_vals.append(cand_nat.lower())
        
        if any(c.lower() in search_vals for c in cand_countries):
            return ScreeningConfig.COUNTRY_MATCH_BONUS
        return 0.0

    def _calculate_gender_adjustment(self, gender, cand):
        if not gender or not cand['gender']: return 0.0
        if gender.lower()[0] == cand['gender'].lower()[0]:
            return ScreeningConfig.GENDER_MATCH_BONUS
        return ScreeningConfig.GENDER_MISMATCH_PENALTY

    def _get_recommendation(self, result):
        if result == 'CONFIRMED_HIT': return '🚨 BLOCK_IMMEDIATELY'
        if result == 'POTENTIAL_MATCH': return '⚠️ MANUAL_REVIEW_REQUIRED'
        return '✅ APPROVE'

    def close(self):
        if self.db_conn:
            db_pool.return_connection(self.db_conn)
            self.db_conn = None
