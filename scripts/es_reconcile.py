#!/usr/bin/env python3
"""Make the search index match the watchlist exactly, by record id.

- removes index entries whose record is inactive (delisted / merged) or gone
- indexes active records that are missing from the index

The incremental sync handles day-to-day changes; this is the full check run
after every scheduled list update, and on demand:
    venv/bin/python scripts/es_reconcile.py            # report + fix
    venv/bin/python scripts/es_reconcile.py --dry-run  # report only
"""
import os
import sys
import argparse
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

import psycopg2
from psycopg2.extras import RealDictCursor
from elasticsearch.helpers import scan, bulk
from config import Config
from screening.es_client import get_es_client
from es_incremental_sync import build_doc, INDEX

log = logging.getLogger("es_reconcile")


def _bulk(es, actions):
    ok, errs = bulk(es, actions, raise_on_error=False, chunk_size=1000)
    # deleting an entry that is already gone is fine
    errs = [e for e in errs if not (e.get('delete', {}).get('status') == 404)]
    if errs:
        log.error(f"{len(errs)} index operations failed, first: {str(errs[0])[:300]}")
    return ok, len(errs)


def run(dry_run=False):
    from utils.demo import skip_in_demo
    if skip_in_demo("search index check", log):
        return {}
    es = get_es_client(timeout=120)
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT id FROM screening_watchlist WHERE COALESCE(is_active, 1) <> 0")
    active = {r[0] for r in cur.fetchall()}
    indexed = set()
    for h in scan(es, index=INDEX, query={"query": {"match_all": {}}, "_source": False}, size=5000, scroll="5m"):
        try:
            indexed.add(int(h["_id"]))
        except ValueError:
            pass
    stale = indexed - active
    missing = active - indexed
    log.info(f"database active={len(active):,} index={len(indexed):,} "
             f"stale_in_index={len(stale):,} missing_from_index={len(missing):,}")
    if dry_run or (not stale and not missing):
        conn.close()
        return {"active": len(active), "indexed": len(indexed), "stale": len(stale), "missing": len(missing)}

    removed = failed = 0
    ids = sorted(stale)
    for i in range(0, len(ids), 5000):
        ok, bad = _bulk(es, ({"_op_type": "delete", "_index": INDEX, "_id": str(x)} for x in ids[i:i + 5000]))
        removed += ok; failed += bad

    added = 0
    if missing:
        cols_cur = conn.cursor()
        cols_cur.execute("SELECT column_name FROM information_schema.columns "
                         "WHERE table_name = 'screening_watchlist' ORDER BY ordinal_position")
        cols = [r[0] for r in cols_cur.fetchall()]
        mids = sorted(missing)
        for i in range(0, len(mids), 2000):
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute(f"SELECT {', '.join(cols)} FROM screening_watchlist WHERE id = ANY(%s)", (mids[i:i + 2000],))
            ok, bad = _bulk(es, ({"_op_type": "index", "_index": INDEX, "_id": str(r["id"]),
                                  "_source": build_doc(r)} for r in c.fetchall()))
            added += ok; failed += bad
    es.indices.refresh(index=INDEX)
    conn.close()
    log.info(f"removed {removed:,} stale entries, indexed {added:,} missing records, {failed} failures")
    return {"removed": removed, "added": added, "failed": failed}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("elastic_transport").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    r = run(dry_run=ap.parse_args().dry_run)
    sys.exit(1 if r.get("failed") else 0)
