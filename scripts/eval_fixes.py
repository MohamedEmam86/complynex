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
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append('c:/Users/Dina/Downloads/ComplyNex_CMS')
from run import app
from screening.routes import get_engine

print('\n--- VERIFICATION TEST (MOHAMED ALI) ---')

with app.app_context():
    engine = get_engine()
    
    print('\nTest 1: NO COUNTRY, NO DOB')
    res1 = engine.screen_person('محمد علي', entity_type='INDIVIDUAL')
    print('Matches:', res1['total_matches'])
    for r in res1['matches'][:3]:
        print(f"ID: {r.get('id', 'N/A')}, Score: {r['match_score']}, Name: {r.get('candidate_name','')}, Country: {r.get('nationality','')}")
        
    print('\nTest 2: COUNTRY=Egypt, NO DOB')
    res2 = engine.screen_person('محمد علي', entity_type='INDIVIDUAL', nationality='Egypt', date_of_birth=None)
    print('Matches:', res2['total_matches'])
    for r in res2['matches'][:3]:
        print(f"ID: {r.get('id', 'N/A')}, Score: {r['match_score']}, Name: {r.get('candidate_name','')}, Country: {r.get('nationality','')}")

    print('\nTest 3: COUNTRY=Saudi Arabia (Mismatch constraint test)')
    res3 = engine.screen_person('محمد علي', entity_type='INDIVIDUAL', nationality='Saudi Arabia', date_of_birth=None)
    print('Matches:', res3['total_matches'])
    for r in res3['matches'][:3]:
        print(f"ID: {r.get('id', 'N/A')}, Score: {r['match_score']}, Name: {r.get('candidate_name','')}, Country: {r.get('nationality','')}")

    print('\nTest 4: Disambiguation EXACT National ID (+25 Boost)')
    first_match = res2['matches'][0]
    nid = first_match.get('details', {}).get('national_id_numbers', '')
    if not nid:
        conn = sqlite3.connect('C:/Users/Dina/Downloads/ComplyNex_CMS/complynex_cms.db')
        cur = conn.cursor()
        cur.execute("SELECT national_id_numbers FROM screening_watchlist WHERE national_id_numbers IS NOT NULL LIMIT 1")
        row = cur.fetchone()
        nid = row[0] if row else '123456789'
        conn.close()
        
    res4 = engine.screen_person('محمد علي', entity_type='INDIVIDUAL', nationality='Egypt', national_id=nid)
    print('Matches:', res4['total_matches'])
    for r in res4['matches'][:3]:
        print(f"ID: {r.get('id', 'N/A')}, Score: {r['match_score']}, Name: {r.get('candidate_name','')}, Cont: {r.get('nationality','')}, NID: {r.get('details', {}).get('national_id_numbers','')}")

    engine.close()
