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

path = 'c:/Users/Dina/Downloads/ComplyNex_CMS/screening/complynex_engine.py'
with open(path, 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Update _recall_candidates signature
code = code.replace(
    'def _recall_candidates(self, processed_name, english_variants, \n                          soundex, metaphone, entity_type, is_arabic=False, arabic_variants=None):',
    'def _recall_candidates(self, processed_name, english_variants, \n                          soundex, metaphone, entity_type, country=None, is_arabic=False, arabic_variants=None):'
)
code = code.replace(
    'def _recall_candidates(self, processed_name, english_variants, \r\n                          soundex, metaphone, entity_type, is_arabic=False, arabic_variants=None):',
    'def _recall_candidates(self, processed_name, english_variants, \r\n                          soundex, metaphone, entity_type, country=None, is_arabic=False, arabic_variants=None):'
)

# 2. Update screen_person call
screen_person_old = '''        candidates = self._recall_candidates(
            processed_name, 
            english_variants,
            soundex_code,
            metaphone_code,
            entity_type,
            is_arabic=is_arabic,
            arabic_variants=arabic_variants
        )'''
screen_person_new = '''        candidates = self._recall_candidates(
            processed_name, 
            english_variants,
            soundex_code,
            metaphone_code,
            entity_type,
            country=nationality,
            is_arabic=is_arabic,
            arabic_variants=arabic_variants
        )'''
code = code.replace(screen_person_old, screen_person_new)


# 3. Update the semantic search logic block inside _recall_candidates
semantic_old = '''                # --- SEMANTIC SEARCH PATH ---
                semantic_candidates = []
                if getattr(self, 'semantic_matcher', None) and self.semantic_matcher.enabled:
                    try:
                        s_results = self.semantic_matcher.search_index(processed_name, top_k=10)
                        for res in s_results:
                            raw_id = res.get('id', '')
                            # Strip _AR suffix if it was an Arabic embedded record
                            clean_id = str(raw_id).replace('_AR', '') 
                            candidate = {
                                'id': clean_id,
                                'full_name': res.get('name', ''),
                                'original_name': res.get('original_name', ''),
                                'name_normalized': res.get('name', ''),
                                'dataset': res.get('dataset', 'UNKNOWN'),
                                'list_type': 'SANCTIONS',
                                'semantic_score': res.get('semantic_score', 0.0),
                                'is_semantic': True
                            }
                            semantic_candidates.append(candidate)
                    except Exception as e:
                        logger.error(f"Semantic search error: {e}")'''

semantic_new = '''                # --- SEMANTIC SEARCH PATH ---
                semantic_candidates = []
                self.low_candidate_count = False
                if getattr(self, 'semantic_matcher', None) and self.semantic_matcher.enabled:
                    try:
                        s_results = self.semantic_matcher.search_index(processed_name, top_k=25, country=country)
                        
                        # Apply SQLite country post-filter if country provided
                        if country and s_results:
                            country_lower = country.lower()
                            s_ids = [str(r.get('id', '')).replace('_AR', '') for r in s_results]
                            s_ids = [sid for sid in s_ids if sid]
                            
                            if s_ids:
                                cursor = getattr(self, 'db_conn', None).cursor() if getattr(self, 'db_conn', None) else None
                                if cursor:
                                    placeholders = ','.join('?' * len(s_ids))
                                    query = f"SELECT id FROM screening_watchlist WHERE id IN ({placeholders}) AND (LOWER(countries) LIKE ? OR LOWER(nationality) LIKE ? OR country_code = ?)"
                                    params = tuple(s_ids) + (f"%{country_lower}%", f"%{country_lower}%", country_lower.upper() if len(country_lower)==2 else 'EG')
                                    cursor.execute(query, params)
                                    valid_ids = set([str(row[0]) for row in cursor.fetchall()])
                                    
                                    s_results = [r for r in s_results if str(r.get('id', '')).replace('_AR', '') in valid_ids]
                                    if len(s_results) < 5:
                                        self.low_candidate_count = True
                                        
                        for res in s_results:
                            raw_id = res.get('id', '')
                            # Strip _AR suffix if it was an Arabic embedded record
                            clean_id = str(raw_id).replace('_AR', '') 
                            candidate = {
                                'id': clean_id,
                                'full_name': res.get('name', ''),
                                'original_name': res.get('original_name', ''),
                                'name_normalized': res.get('name', ''),
                                'dataset': res.get('dataset', 'UNKNOWN'),
                                'list_type': 'SANCTIONS',
                                'semantic_score': res.get('semantic_score', 0.0),
                                'is_semantic': True
                            }
                            semantic_candidates.append(candidate)
                    except Exception as e:
                        logger.error(f"Semantic search error: {e}")'''

code = code.replace(semantic_old, semantic_new)

with open(path, 'w', encoding='utf-8') as f:
    f.write(code)

print("Patch applied to complynex_engine.py")
