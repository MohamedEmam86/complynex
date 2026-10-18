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

import sqlite3
import os
from datetime import datetime

def fix_sqlite_sources():
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex_cms.db')
    print(f"Connecting to SQLite DB: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Clear existing legacy sources
    print("Clearing legacy sources...")
    cursor.execute("DELETE FROM screening_data_sources")
    
    # 2. Insert new sources with correct schema columns
    # Schema: id, name, display_name, source_url, type, is_official, is_active, update_frequency_hours, last_successful_update, total_records, last_updated_by
    
    sources = [
        {
            'name': 'opensanctions',
            'display_name': 'OpenSanctions (Global Sanctions)',
            'source_url': 'https://data.opensanctions.org/datasets/latest/sanctions/entities.ftm.json',
            'type': 'JSON',
            'is_official': 0,
            'is_active': 1
        },
        {
            'name': 'opensanctions_pep',
            'display_name': 'OpenSanctions (Global PEPs)',
            'source_url': 'https://data.opensanctions.org/datasets/latest/peps/entities.ftm.json',
            'type': 'JSON',
            'is_official': 0,
            'is_active': 1
        },
        {
            'name': 'internal_blacklist',
            'display_name': 'Internal Blacklist',
            'source_url': 'internal',
            'type': 'CUSTOM',
            'is_official': 0,
            'is_active': 1
        }
    ]
    
    print("Inserting new sources...")
    for s in sources:
        cursor.execute("""
            INSERT INTO screening_data_sources 
            (name, display_name, source_url, type, is_official, is_active, update_frequency_hours, total_records)
            VALUES (?, ?, ?, ?, ?, ?, 24, 0)
        """, (s['name'], s['display_name'], s['source_url'], s['type'], s['is_official'], s['is_active']))
        
    conn.commit()
    print("SQLite sources updated successfully.")
    
    # Verify
    cursor.execute("SELECT name, is_active FROM screening_data_sources")
    rows = cursor.fetchall()
    print("Current Sources in SQLite:", rows)
    
    conn.close()

if __name__ == "__main__":
    fix_sqlite_sources()
