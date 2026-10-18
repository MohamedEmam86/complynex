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

print('\n--- BASELINE SCORE TEST (MOHAMED ALI) ---')
sys.path.append('C:/Users/Dina/Downloads/ComplyNex_CMS')
from run import app
from screening.complynex_engine import ComplyNexScreeningEngine

with app.app_context():
    engine = ComplyNexScreeningEngine()
    
    print('\nTest 1: NO COUNTRY, NO DOB')
    res1 = engine.screen_entity('محمد علي', entity_type='INDIVIDUAL')
    print('Matches:', res1['total_matches'])
    for r in res1['matches'][:5]:
        print(f"ID: {r.get('id', 'N/A')}, Score: {r['match_score']}, Name: {r['watchlist_name_ar']}, Country: {r.get('nationality','')}")
        
    print('\nTest 2: COUNTRY=Egypt, NO DOB')
    res2 = engine.screen_entity('محمد علي', entity_type='INDIVIDUAL', nationality='Egypt', dob=None)
    print('Matches:', res2['total_matches'])
    for r in res2['matches'][:5]:
        print(f"ID: {r.get('id', 'N/A')}, Score: {r['match_score']}, Name: {r['watchlist_name_ar']}, Country: {r.get('nationality','')}")
