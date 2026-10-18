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
import sys
import json
import time

print("=== 5. Data sources currently active ===")
conn = sqlite3.connect('C:/Users/Dina/Downloads/ComplyNex_CMS/complynex_cms.db')
cur = conn.cursor()
cur.execute('''SELECT dataset, COUNT(*) as count
FROM screening_watchlist
GROUP BY dataset
ORDER BY count DESC;''')
for row in cur.fetchall():
    print(row[0], ":", row[1])

print("\n=== 7. Performance benchmarks ===")
cur.execute("SELECT AVG(processing_time_ms) FROM screening_results WHERE screening_method = 'MANUAL'")
print(f"Average manual screening time (DB): {cur.fetchone()[0]} ms")

print("\n=== 10. Infrastructure ===")
print("Python version:", sys.version)
try:
    import flask
    print("Flask version:", flask.__version__)
except:
    pass

db_size = os.path.getsize('C:/Users/Dina/Downloads/ComplyNex_CMS/complynex_cms.db') / (1024*1024)
print(f"DB size: {db_size:.2f} MB")

faiss_path = 'C:/Users/Dina/Downloads/ComplyNex_CMS/screening/watchlist_semantic_v2.index'
if os.path.exists(faiss_path):
    faiss_size = os.path.getsize(faiss_path) / (1024*1024)
    print(f"FAISS index (V2) size: {faiss_size:.2f} MB")

try:
    with open('C:/Users/Dina/Downloads/ComplyNex_CMS/requirements.txt', 'r') as f:
        print("Requirements:", len(f.readlines()), "lines")
except:
    pass

conn.close()
