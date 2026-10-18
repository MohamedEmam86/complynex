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
import json

# Add parent dir to path so we can import screening modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from screening.semantic_matcher import SemanticSequenceMatcher

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('RescueMetadata')

def rescue_metadata():
    logger.info("Rescuing metadata without re-running models...")
    
    db_path = os.path.join(os.path.dirname(__file__), '..', 'complynex_cms.db')
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("SELECT id, name_normalized, original_name, dataset FROM screening_watchlist WHERE is_active = 1")
        rows = cur.fetchall()
        
        records = []
        for row in rows:
            base_id = row['id']
            dataset = row['dataset']
            
            if row['name_normalized']:
                records.append({
                    'id': base_id,
                    'name': row['name_normalized'],
                    'original_name': row['original_name'],
                    'dataset': dataset,
                    'type': 'latin'
                })
            
            if row['original_name'] and any('\u0600' <= c <= '\u06FF' for c in row['original_name']):
                records.append({
                    'id': f"{base_id}_AR",
                    'name': row['original_name'],
                    'original_name': row['original_name'],
                    'dataset': dataset,
                    'type': 'arabic'
                })
                
        # Must match exactly `[r for r in records if r.get('name')]` from build_index
        metadata = [r for r in records if r.get('name')]
        
        METADATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screening', 'watchlist_semantic_metadata.json')
        
        with open(METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(metadata, f)
            
        logger.info(f"Successfully wrote {len(metadata)} metadata records to {METADATA_FILE}")
        logger.info("You do NOT need to run build_semantic_index.py again! Proceed to train_ml_model.py")
        
    except Exception as e:
        logger.error(f"Error rescuing metadata: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    rescue_metadata()
