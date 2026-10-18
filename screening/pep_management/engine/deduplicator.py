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

import logging
from typing import Dict, List, Tuple
from datetime import datetime
import psycopg2
from psycopg2.extras import DictCursor

# Assuming the engine will import the existing transliterator 
# from screening.arabic_transliteration_enhanced import ArabicTransliterator

logger = logging.getLogger(__name__)

class PEPDeduplicator:
    """
    Core engine for entity resolution, finding duplicates, and merging PEP records.
    Uses precise DB matching combined with fuzzy evaluations.
    """
    
    def __init__(self, db_config: Dict):
        self.db_config = db_config
    
    def _get_connection(self):
        return psycopg2.connect(**self.db_config)
    
    def find_potential_matches(self, new_record: Dict) -> List[Dict]:
        """
        Search for potential matches in the database using trigram distance and strict overlap.
        Returns a list of candidate PEP master records with a match score.
        """
        name_en = new_record.get('canonical_name_en', '')
        name_ar = new_record.get('canonical_name_ar', '')
        dob = new_record.get('date_of_birth')
        
        candidates = []
        
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=DictCursor) as cur:
                    # Strategy 1: Exact DOB + Fuzzy Name Match
                    if dob:
                        query = """
                            SELECT id, canonical_name_en, canonical_name_ar, date_of_birth,
                                   similarity(canonical_name_en, %s) as sim_en,
                                   similarity(canonical_name_ar, %s) as sim_ar
                            FROM pep_master
                            WHERE date_of_birth = %s
                              AND (similarity(canonical_name_en, %s) > 0.6 
                                   OR similarity(canonical_name_ar, %s) > 0.6)
                        """
                        cur.execute(query, (name_en, name_ar, dob, name_en, name_ar))
                        
                        for row in cur.fetchall():
                            match_score = max(row['sim_en'] or 0, row['sim_ar'] or 0)
                            candidates.append({
                                'pep_id': row['id'],
                                'score': match_score,
                                'reason': 'exact_dob_fuzzy_name',
                                'record': dict(row)
                            })
                    
                    # Strategy 2: High Confidence Fuzzy Name Match (No DOB overlap required)
                    # We search using GIN trigrams for speed
                    query = """
                        SELECT id, canonical_name_en, canonical_name_ar, date_of_birth,
                               similarity(canonical_name_en, %s) as sim_en,
                               similarity(canonical_name_ar, %s) as sim_ar
                        FROM pep_master
                        WHERE similarity(canonical_name_en, %s) > 0.85
                           OR similarity(canonical_name_ar, %s) > 0.85
                    """
                    cur.execute(query, (name_en, name_ar, name_en, name_ar))
                    
                    for row in cur.fetchall():
                        # Exclude already found candidates
                        if any(c['pep_id'] == row['id'] for c in candidates):
                            continue
                            
                        # If DB record has a DOB and new record has a DOB, and they conflict severely, penalize
                        db_dob = row['date_of_birth']
                        if db_dob and dob and db_dob != dob:
                            continue # Strict DOB conflict implies different person despite name
                            
                        match_score = max(row['sim_en'] or 0, row['sim_ar'] or 0)
                        candidates.append({
                            'pep_id': row['id'],
                            'score': match_score,
                            'reason': 'high_fuzzy_name_match',
                            'record': dict(row)
                        })
                        
        except Exception as e:
            logger.error(f"Error finding matches: {e}")
            
        # Sort candidates by descending score
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates
        
    def flag_duplicate(self, pep_id_1: int, pep_id_2: int, score: float, reason: str):
        """
        Record a potential duplicate pair for manual review in the `pep_duplicate_candidates` table.
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Ensure ordered insertion to avoid (A,B) and (B,A) dupes
                    id_a, id_b = min(pep_id_1, pep_id_2), max(pep_id_1, pep_id_2)
                    
                    # Check if already flagged
                    cur.execute("""
                        SELECT id FROM pep_duplicate_candidates 
                        WHERE pep_id_1 = %s AND pep_id_2 = %s
                    """, (id_a, id_b))
                    
                    if not cur.fetchone():
                        cur.execute("""
                            INSERT INTO pep_duplicate_candidates 
                            (pep_id_1, pep_id_2, match_score, match_reason)
                            VALUES (%s, %s, %s, %s)
                        """, (id_a, id_b, score, reason))
                        conn.commit()
                        logger.info(f"Flagged potential duplicate: PEP {id_a} & PEP {id_b}")
        except Exception as e:
            logger.error(f"Error flagging duplicate: {e}")
            
    def process_new_record_deduplication(self, new_pep_id: int):
        """
        After inserting a new PEP, run this to scan the DB for duplicates and flag them.
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=DictCursor) as cur:
                    cur.execute("""
                        SELECT canonical_name_en, canonical_name_ar, date_of_birth
                        FROM pep_master WHERE id = %s
                    """, (new_pep_id,))
                    record = cur.fetchone()
                    
            if not record:
                return
                
            candidates = self.find_potential_matches(dict(record))
            
            for candidate in candidates:
                # Do not flag oneself
                if candidate['pep_id'] != new_pep_id:
                    self.flag_duplicate(
                        new_pep_id, 
                        candidate['pep_id'], 
                        candidate['score'], 
                        candidate['reason']
                    )
        except Exception as e:
            logger.error(f"Error processing deduplication for PEP {new_pep_id}: {e}")
