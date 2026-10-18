#!/usr/bin/env python3
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

import os
import sys
import logging
import sqlite3

# Add parent dir to path so we can import screening modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from screening.semantic_matcher import SemanticSequenceMatcher

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('BuildSemanticIndex')

def build_index():
    matcher = SemanticSequenceMatcher()
    if not matcher.enabled:
        logger.error("Semantic Sequence Matcher is disabled (missing deps: faiss-cpu or sentence-transformers).")
        return
        
    db_path = os.path.join(os.path.dirname(__file__), '..', 'complynex_cms.db')
    if not os.path.exists(db_path):
        logger.error(f"Database not found at {db_path}")
        return
        
    logger.info("Fetching all active watchlist entries from the database...")
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # We want to embed the normalized latin name as well as the arabic name to ensure total coverage
        cur.execute("SELECT id, name_normalized, original_name, dataset, country_code, nationality FROM screening_watchlist WHERE is_active = 1")
        rows = cur.fetchall()
        
        # Set new paths for v2 index so we don't overwrite current production
        matcher.INDEX_FILE = os.path.join(os.path.dirname(__file__), '..', 'screening', 'watchlist_semantic_v2.index')
        matcher.METADATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'screening', 'watchlist_semantic_metadata_v2.json')
        
        records = []
        for row in rows:
            base_id = row['id']
            dataset = row['dataset']
            
            latin_name = row['name_normalized'] or ''
            arabic_name = row['original_name'] or ''
            
            # Only append if we actually have text in at least one
            if not latin_name and not arabic_name:
                continue
                
            # Concatenate Arabic name + English name per record as specified
            name_parts = []
            if arabic_name:
                name_parts.append(arabic_name.strip())
            if latin_name and latin_name.strip() != arabic_name.strip():
                name_parts.append(latin_name.strip())
                
            combined_name = " ".join(name_parts)
            
            records.append({
                'id': base_id,
                'name': combined_name,
                'original_name': arabic_name,
                'dataset': dataset,
                'type': 'combined',
                'country_code': row['country_code'],
                'nationality': row['nationality']
            })
                
        logger.info(f"Loaded {len(records)} specific name records to embed.")
        
        # Build!
        if matcher.build_index(records):
            logger.info("Success! FAISS Semantic Index is ready for use.")
        else:
            logger.error("Failed to build semantic index.")
            
    except Exception as e:
        logger.error(f"Error building index: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    build_index()
