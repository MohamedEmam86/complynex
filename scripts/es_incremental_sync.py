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

import os, sys, time, logging, re, psycopg2
from datetime import datetime, timezone, timedelta
from psycopg2.extras import RealDictCursor
from elasticsearch import Elasticsearch
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from screening.es_client import get_es_client  # noqa: E402  (credentials from .env)
from elasticsearch.helpers import bulk, BulkIndexError

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass
from config import Config

# Single source of truth — same dict the live app connects with (psycopg2
# accepts 'database' as an alias for 'dbname').
PG = dict(Config.POSTGRES_CONFIG)
log = logging.getLogger("es_sync")
INDEX = "aml_watchlist"


def build_doc(row):
    """Index document for one screening_watchlist row (shared with es_reconcile)."""
    doc = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in dict(row).items() if v is not None}
    if row.get("original_name") or row.get("full_name"):
        raw = row.get("original_name") or row.get("full_name")
        doc["name_normalized"] = re.sub(r' {2,}', ' ', re.sub(r'عبدال([\u0600-\u06FF])', lambda m: 'عبد ال' + m.group(1), raw)).strip().lower()
    doc["watchlist_id"] = row["id"]
    return doc


def run():
    from utils.demo import skip_in_demo
    if skip_in_demo("search index sync", log):
        return
    from screening.update_lock import held
    if held():
        # A list update is writing in long transactions: rows written early but
        # committed late would fall behind this run's checkpoint and be missed.
        # Skip without moving the checkpoint; the first run after the update
        # picks everything up.
        log.info("Sanctions list update in progress - sync skipped, checkpoint unchanged.")
        return
    from screening.es_client import guard_es_write
    guard_es_write('incremental sync', PG.get('database') or PG.get('dbname'))   # raises: exit code 1
    log.info("Starting Incremental Sync...")
    es = get_es_client(timeout=60)
    if not es.indices.exists(index="aml_watchlist"): log.error("Index missing. Run full migration first."); return
    
    try: res = es.get(index="aml_sync_meta", id="last_incremental_sync"); last_sync = datetime.fromisoformat(res["_source"]["timestamp"].replace("Z", "+00:00"))
    except: 
        try: res = es.get(index="aml_sync_meta", id="last_full_migration"); last_sync = datetime.fromisoformat(res["_source"]["timestamp"].replace("Z", "+00:00"))
        except: last_sync = datetime.now(timezone.utc) - timedelta(hours=24)
    
    sync_start = datetime.now(timezone.utc)
    pg_conn = psycopg2.connect(**PG)
    with pg_conn.cursor() as cur: cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'screening_watchlist' ORDER BY ordinal_position"); cols = [r[0] for r in cur.fetchall()]
    
    if "updated_at" not in cols: log.error("No updated_at column. Run setup first."); pg_conn.close(); return
    
    with pg_conn.cursor() as cur: cur.execute("SELECT COUNT(*) FROM screening_watchlist WHERE updated_at::timestamp >= %s", (last_sync,)); changes = cur.fetchone()[0]
    log.info(f"Records changed since last sync: {changes:,}")
    
    if changes > 0:
        batch = []; upserted = 0
        with pg_conn.cursor("sync_cursor", cursor_factory=RealDictCursor) as cur:
            cur.itersize = 500
            cur.execute(f"SELECT {', '.join(cols)} FROM screening_watchlist WHERE updated_at::timestamp >= %s ORDER BY id", (last_sync,))
            for row in cur:
                doc = build_doc(row)
                if row.get("is_active") == 0:
                    # delisted / deactivated: must stop matching
                    batch.append({"_op_type": "delete", "_index": "aml_watchlist", "_id": str(row["id"])})
                else:
                    batch.append({"_op_type": "index", "_index": "aml_watchlist", "_id": str(row["id"]), "_source": doc})
                if len(batch) >= 500:
                    try:
                        ok, errs = bulk(es, batch, raise_on_error=False); upserted += ok
                        if errs: log.error(f"{len(errs)} documents rejected by ES, first: {str(errs[0])[:400]}")
                    except Exception as e: log.error(f"bulk failed: {e}")
                    batch = []
            if batch:
                try:
                    ok, errs = bulk(es, batch, raise_on_error=False); upserted += ok
                    if errs: log.error(f"{len(errs)} documents rejected by ES, first: {str(errs[0])[:400]}")
                except Exception as e: log.error(f"bulk failed: {e}")
        log.info(f"Upserted {upserted:,} records.")
    
    es.index(index="aml_sync_meta", id="last_incremental_sync", body={"event": "incremental_sync", "timestamp": sync_start.isoformat(), "detail": {"upserted": changes}})
    pg_conn.close(); es.indices.refresh(index="aml_watchlist")
    log.info("Incremental Sync Complete.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(BASE_DIR, "logs", "es_incremental_sync.log"))])
    run()
