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

import sys
import time
from datetime import datetime
sys.path.append('c:/Users/Dina/Downloads/ComplyNex_CMS')
from run import app
from screening.routes import get_engine
import sqlite3
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')

print("Checking Elasticsearch...")
for _ in range(20):
    try:
        urllib.request.urlopen("http://localhost:9200", timeout=1)
        print("Elasticsearch is UP and responding.\n")
        break
    except:
        time.sleep(1.5)
else:
    print("Failed to connect to Elasticsearch.")
    sys.exit(1)

with app.app_context():
    engine = get_engine()
    
    test_cases = [
        {"name": "أحمد محمود", "country": None, "desc": "Arabic name"},
        {"name": "Ahmed Mahmoud", "country": "EG", "desc": "English name with country=Egypt"},
        {"name": "محمد", "country": None, "desc": "Common name alone"}
    ]
    
    for case in test_cases:
        print(f"\n--- Testing {case['desc']} ('{case['name']}') ---")
        t1 = datetime.now()
        print(f"[{t1.strftime('%H:%M:%S')}] POST /screening/screen HTTP/1.1 302")
        
        start_time = time.time()
        res = engine.screen_person(case['name'], entity_type='INDIVIDUAL', nationality=case['country'])
        proc_time_ms = int((time.time() - start_time) * 1000)
        
        # Mimic DB insertion
        conn = sqlite3.connect('C:/Users/Dina/Downloads/ComplyNex_CMS/complynex_cms.db')
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO screening_results (
                screening_type, screened_name, screening_method, total_matches_found, 
                highest_match_score, screening_result, processing_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ('ADHOC', case['name'], 'MANUAL', res['total_matches'], res['highest_score'], res['screening_result'], proc_time_ms))
        conn.commit()
        result_id = cur.lastrowid
        conn.close()
        
        t2 = datetime.now()
        print(f"[{t2.strftime('%H:%M:%S')}] GET /screening/result/{result_id} HTTP/1.1 200")
        print(f"\nTotal Processing Time: {proc_time_ms/1000:.3f} seconds")
        print(f"Total Matches: {res['total_matches']}")
        
    engine.close()
