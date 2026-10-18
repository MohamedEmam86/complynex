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

import os, sys, subprocess, logging, psycopg2
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

ES_HOST = "http://localhost:9200"
META_INDEX = "aml_sync_meta"
# Single source of truth — same dict the live app connects with.
PG = dict(Config.POSTGRES_CONFIG)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("setup")

def setup():
    log.info("[1/4] Setting up PG timestamps...")
    conn = psycopg2.connect(**PG); cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'screening_watchlist' AND column_name IN ('created_at', 'updated_at')")
    existing = {r[0] for r in cur.fetchall()}
    if "created_at" not in existing: cur.execute("ALTER TABLE screening_watchlist ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW()"); cur.execute("UPDATE screening_watchlist SET created_at = NOW() WHERE created_at IS NULL")
    if "updated_at" not in existing: cur.execute("ALTER TABLE screening_watchlist ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW()"); cur.execute("UPDATE screening_watchlist SET updated_at = NOW() WHERE updated_at IS NULL")
    cur.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_watchlist_updated_at ON screening_watchlist (updated_at)")
    cur.execute("CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;")
    cur.execute("DROP TRIGGER IF EXISTS trg_watchlist_updated_at ON screening_watchlist;")
    cur.execute("CREATE TRIGGER trg_watchlist_updated_at BEFORE UPDATE ON screening_watchlist FOR EACH ROW EXECUTE FUNCTION set_updated_at();")
    conn.commit(); cur.close(); conn.close(); log.info("  PG setup complete ✓")

    log.info("[2/4] Setting up ES meta...")
    es = Elasticsearch(ES_HOST)
    if not es.indices.exists(index=META_INDEX): es.indices.create(index=META_INDEX, body={"mappings": {"properties": {"event": {"type": "keyword"}, "timestamp": {"type": "date"}, "detail": {"type": "object", "enabled": False}}}})
    log.info("  ES meta complete ✓")

    log.info("[3/4] Installing cron...")
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    cron = res.stdout if res.returncode == 0 else ""
    if "es_incremental_sync" not in cron:
        new_cron = cron.rstrip("\n") + "\n0 3 * * * cd /opt/complynex && /opt/complynex/venv/bin/python3 /opt/complynex/scripts/es_incremental_sync.py >> /opt/complynex/logs/es_incremental_sync.log 2>&1 # es_incremental_sync\n"
        subprocess.run(["crontab", "-"], input=new_cron, text=True)
        log.info("  Cron installed at 03:00 AM ✓")
    else: log.info("  Cron already exists ✓")
    log.info("Setup complete! ✅")

if __name__ == "__main__": setup()
