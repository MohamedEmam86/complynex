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

import os, sys, psycopg2, subprocess
from elasticsearch import Elasticsearch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass
from config import Config

# Single source of truth — same dict the live app connects with.
PG = dict(Config.POSTGRES_CONFIG)

print("=== ES SYNC STATUS ===")
try:
    conn = psycopg2.connect(**PG); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM screening_watchlist"); pg_total = cur.fetchone()[0]
    print(f"📦 PG Total Records: {pg_total:,}")
    conn.close()
except: print("📦 PG: Cannot connect")

es = Elasticsearch("http://localhost:9200")
if es.indices.exists(index="aml_watchlist"):
    stats = es.indices.stats(index="aml_watchlist")
    es_docs = stats["_all"]["primaries"]["docs"]["count"]
    print(f"🔍 ES Total Records: {es_docs:,}")
    if 'pg_total' in locals():
        gap = pg_total - es_docs
        print(f"⚖️  Sync Gap: {gap:,} records")
else: print("🔍 ES: aml_watchlist index DOES NOT EXIST")

res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
if "es_incremental_sync" in res.stdout: print("⏰ Cron: Active ✓")
else: print("⏰ Cron: Not installed ✗")
