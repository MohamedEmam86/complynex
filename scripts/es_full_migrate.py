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

import os, sys, time, json, argparse, logging, re
from datetime import datetime, timezone
import psycopg2
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

ES_HOST = "http://localhost:9200"
ES_INDEX = "aml_watchlist"
META_INDEX = "aml_sync_meta"
BATCH_SIZE = 1000
LOG_EVERY = 50000

# Single source of truth — same dict the live app connects with.
PG = dict(Config.POSTGRES_CONFIG)
CHECKPOINT_FILE = os.path.join(BASE_DIR, "logs", "es_migration_checkpoint.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(BASE_DIR, "logs", "es_migration.log"))])
log = logging.getLogger("es_migrate")

def get_es():
    es = get_es_client(timeout=120)
    if not es.ping(): log.error("Cannot reach ES"); sys.exit(1)
    return es

def ensure_index(es):
    sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
    from es_create_index import create_index, MAPPING
    if not es.indices.exists(index=ES_INDEX):
        log.info("Creating index..."); es.indices.create(index=ES_INDEX, body=MAPPING); log.info("Index created ✓")

def ensure_meta_index(es):
    if not es.indices.exists(index=META_INDEX):
        es.indices.create(index=META_INDEX, body={"mappings": {"properties": {"event": {"type": "keyword"}, "timestamp": {"type": "date"}, "detail": {"type": "object", "enabled": False}}}})

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE) as f: return json.load(f)
        except Exception: pass
    return {"last_id": 0, "indexed": 0}

def save_checkpoint(last_id, indexed):
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f: json.dump({"last_id": last_id, "indexed": indexed, "saved_at": datetime.now(timezone.utc).isoformat()}, f)

def build_doc(row):
    doc = {}
    for k, v in row.items():
        if v is None: continue
        if isinstance(v, datetime): doc[k] = v.isoformat()
        else: doc[k] = v
    raw = row.get("original_name") or row.get("full_name") or ""
    if raw:
        normalized = re.sub(r'عبدال([\u0600-\u06FF])', lambda m: 'عبد ال' + m.group(1), raw)
        doc["name_normalized"] = re.sub(r' {2,}', ' ', normalized).strip().lower()
    doc["watchlist_id"] = row["id"]
    doc["es_indexed_at"] = datetime.now(timezone.utc).isoformat()
    if row.get("updated_at"):
        _val = row["updated_at"]
        if isinstance(_val, datetime):
            doc["pg_updated_at"] = _val.isoformat()
        else:
            try:
                from dateutil import parser as _dtparser
                doc["pg_updated_at"] = _dtparser.parse(str(_val)).isoformat()
            except Exception:
                pass  # FIX (Contabo migration): skip malformed/text-as-date value rather than send unparseable string and fail the whole ES bulk item
    return doc

def run(fresh=False):
    es = get_es(); ensure_index(es); ensure_meta_index(es)
    checkpoint = {"last_id": 0, "indexed": 0} if fresh else load_checkpoint()
    start_id, total_done = checkpoint["last_id"], checkpoint["indexed"]
    
    pg_conn = psycopg2.connect(**PG)
    with pg_conn.cursor() as cur: cur.execute("SELECT COUNT(*) FROM screening_watchlist"); total = cur.fetchone()[0]
    with pg_conn.cursor() as cur: cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'screening_watchlist' ORDER BY ordinal_position"); cols = [r[0] for r in cur.fetchall()]
    
    log.info(f"Total records in PG: {total:,} | Resuming from ID > {start_id}")
    t_start = time.time(); batch_buf = []; errors = 0; last_id = start_id
    
    with pg_conn.cursor("migrate_cursor", cursor_factory=RealDictCursor) as cur:
        cur.itersize = BATCH_SIZE
        cur.execute(f"SELECT {', '.join(cols)} FROM screening_watchlist WHERE id > %s ORDER BY id", (start_id,))
        for row in cur:
            row = dict(row); doc = build_doc(row)
            batch_buf.append({"_index": ES_INDEX, "_id": str(row["id"]), "_source": doc})
            last_id = row["id"]
            if len(batch_buf) >= BATCH_SIZE:
                try:
                    ok, errs = bulk(es, batch_buf, raise_on_error=False, chunk_size=BATCH_SIZE, request_timeout=60)
                    total_done += ok; errors += len(errs)
                except BulkIndexError as e: errors += len(batch_buf)
                batch_buf = []; save_checkpoint(last_id, total_done)
                if total_done % LOG_EVERY < BATCH_SIZE:
                    elapsed = time.time() - t_start; rate = total_done / elapsed if elapsed > 0 and total_done > 0 else 1
                    log.info(f"Progress: {total_done:,} / {total:,} ({100 * total_done / total:.1f}%) rate={rate:.0f}/s ETA={(total - total_done) / rate / 60:.0f}min")
        if batch_buf:
            try:
                ok, errs = bulk(es, batch_buf, raise_on_error=False, chunk_size=BATCH_SIZE, request_timeout=60)
                total_done += ok; errors += len(errs)
            except BulkIndexError as e: pass
            save_checkpoint(last_id, total_done)
    
    pg_conn.close(); es.indices.refresh(index=ES_INDEX)
    elapsed = time.time() - t_start
    log.info(f"MIGRATION COMPLETE. Indexed: {total_done:,} | Errors: {errors:,} | Time: {elapsed / 60:.1f} minutes")
    
    es.index(index=META_INDEX, id="last_full_migration", body={"event": "full_migration", "timestamp": datetime.now(timezone.utc).isoformat(), "detail": {"total_indexed": total_done, "errors": errors, "duration_min": round(elapsed / 60, 1)}})
    if os.path.exists(CHECKPOINT_FILE): os.remove(CHECKPOINT_FILE)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    run(fresh=args.fresh)
