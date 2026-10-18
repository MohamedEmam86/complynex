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
Seed test data for Advanced Screening Engine.
Includes Arabic names and Egyptian PEPs.
"""

import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex_cms.db')

def seed_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    test_data = [
        # 1. Vladimir Putin (Sanctioned)
        (
            'os-putin', 'Vladimir Putin', 'فلاديمير بوتين', 'putin vladimir', 
            'P350', 'FTN', 'sanctions', 'sanction', json.dumps(['sanction']), json.dumps(['ru']),
            '1952-10-07', 1952, 'Russian', 'male', 'http://example.com/putin', 'CRITICAL',
            json.dumps(['Vladimir Vladimirovich Putin']), json.dumps(['فلاديمير فلاديميروفيتش بوتين']),
            'President of Russia', 'Russia', 
            json.dumps({'program': 'EU Sanctions', 'reason': 'Ukraine invasion', 'notes': 'President of Russia'})
        ),
        # 2. Nicolas Maduro (Sanctioned)
        (
            'os-maduro', 'Nicolas Maduro', 'نيكولاس مادورو', 'maduro nicolas',
            'M360', 'MTN', 'sanctions', 'sanction', json.dumps(['sanction']), json.dumps(['ve']),
            '1962-11-23', 1962, 'Venezuelan', 'male', 'http://example.com/maduro', 'CRITICAL',
            json.dumps(['Nicolas Maduro Moros']), json.dumps([]),
            'President of Venezuela', 'Venezuela',
            json.dumps({'program': 'OFAC SDN', 'reason': 'Narcoterrorism', 'notes': 'Controlled by US sanctions'})
        ),
        # 3. Egyptian PEP (Target)
        (
            'eg-pep-1', 'Mostafa Madbouly', 'مصطفى مدبولي', 'madbouly mostafa',
            'M314', 'MTBL', 'pep', 'pep', json.dumps(['pep']), json.dumps(['eg']),
            '1966-04-28', 1966, 'Egyptian', 'male', 'http://example.com/madbouly', 'CRITICAL',
            json.dumps(['Mostafa Kamal Madbouly']), json.dumps(['مصطفى كمال مدبولي']),
            'Prime Minister of Egypt', 'Egypt',
            json.dumps({'program': 'PEPs', 'reason': 'Government Official', 'notes': '[EGYPTIAN PEP] Primary target for AML screening'})
        ),
        # 4. Sameh Shoukry (Arabic Name Variant)
        (
            'eg-pep-2', 'Sameh Shoukry', 'سامح شكري', 'sameh shoukry',
            'S520', 'SMHK', 'pep', 'pep', json.dumps(['pep']), json.dumps(['eg']),
            '1952-10-20', 1952, 'Egyptian', 'male', 'http://example.com/shoukry', 'HIGH',
            json.dumps(['Sameh Hassan Shoukry']), json.dumps(['سامح حسن شكري']),
            'Former Minister of Foreign Affairs', 'Egypt',
            json.dumps({'program': 'PEPs', 'reason': 'Government Official', 'notes': '[EGYPTIAN PEP]'})
        )
    ]
    
    cursor.executemany("""
        INSERT INTO screening_watchlist (
            id, full_name, full_name_arabic, name_normalized, name_soundex, name_metaphone,
            dataset, list_type, topics, countries, 
            date_of_birth, year_of_birth, nationality, gender,
            source_url, risk_level, aliases, aliases_arabic, 
            pep_position, pep_country, details, is_active, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, [d + (datetime.now().isoformat(),) for d in test_data])
    
    conn.commit()
    conn.close()
    print(f"Seeded {len(test_data)} advanced test records.")

if __name__ == "__main__":
    seed_data()
