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

from screening.db_pool import db_pool
"""
Elasticsearch indexer for ComplyNex Screening Engine.
Loads all watchlist and internal blacklist records into Elasticsearch.
Uses arabic_name_analyzer and latin_name_analyzer for robust searching.
"""
from elasticsearch import Elasticsearch, helpers
import sqlite3
import os
import json
import time
from dotenv import load_dotenv

# Ensure env vars are loaded
load_dotenv()

from screening.es_client import get_es_client

def get_db_connection():
    conn = db_pool.checkout_connection()
    conn.row_factory = sqlite3.Row
    return conn

def setup_indices(es: Elasticsearch, wl_index: str, bl_index: str):
    from screening.es_client import guard_es_write
    guard_es_write('es_indexer')
    """Create indices with specific analyzers for Arabic and Latin text."""
    
    settings = {
        "analysis": {
            "analyzer": {
                "arabic_name_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "arabic_normalization", "edge_ngram_filter"]
                },
                "latin_name_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding", "edge_ngram_filter"]
                }
            },
            "filter": {
                "edge_ngram_filter": {
                    "type": "edge_ngram",
                    "min_gram": 3,
                    "max_gram": 15
                }
            }
        }
    }

    mapping = {
        "properties": {
            "name": {
                "type": "text",
                "fields": {
                    "raw": {"type": "keyword"}
                }
            },
            "name_arabic": {
                "type": "text",
                "analyzer": "arabic_name_analyzer"
            },
            "name_latin": {
                "type": "text",
                "analyzer": "latin_name_analyzer"
            },
            "source": {"type": "keyword"},
            "entity_type": {"type": "keyword"},
            "list_date": {"type": "date"},
            "is_internal_blacklist": {"type": "boolean"}
        }
    }

    # Setup Watchlist Index
    if es.indices.exists(index=wl_index):
        es.indices.delete(index=wl_index)
    es.indices.create(index=wl_index, settings=settings, mappings=mapping)
    
    # Setup Blacklist Index
    if es.indices.exists(index=bl_index):
        es.indices.delete(index=bl_index)
    es.indices.create(index=bl_index, settings=settings, mappings=mapping)

def index_watchlist(es: Elasticsearch, wl_index: str):
    from screening.es_client import guard_es_write
    guard_es_write('es_indexer')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM screening_watchlist WHERE is_active = 1")
    except sqlite3.OperationalError:
        print("Table screening_watchlist not found. Skipping watchlist indexing.")
        conn.close()
        return 0, {}

    rows = cursor.fetchall()
    actions = []
    stats = {}
    
    for row in rows:
        source_key = str(row['source']).upper() if row['source'] else 'UNKNOWN'
        
        # Categorize for the summary
        if 'OFAC' in source_key: cat = 'OFAC'
        elif 'UN' in source_key: cat = 'UN'
        elif 'EU' in source_key: cat = 'EU'
        elif 'HMT' in source_key: cat = 'HMT'
        elif 'EMLCU' in source_key: cat = 'EMLCU'
        else: cat = 'Custom'
        
        stats[cat] = stats.get(cat, 0) + 1
        
        doc = {
            "name": row['full_name'],
            "name_arabic": row['original_name'] if row['original_name'] else "",
            "name_latin": row['full_name'],
            "source": source_key,
            "entity_type": row['entity_type'] if row['entity_type'] else "UNKNOWN",
            "list_date": row['first_seen'] if 'first_seen' in row.keys() else None,
            "is_internal_blacklist": False,
            "original_id": row['id']
        }
        
        action = {
            "_index": wl_index,
            "_id": f"wl_{row['id']}",
            "_source": doc
        }
        actions.append(action)

    if actions:
        helpers.bulk(es, actions)
        
    conn.close()
    return len(actions), stats

def index_blacklist(es: Elasticsearch, bl_index: str):
    from screening.es_client import guard_es_write
    guard_es_write('es_indexer')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM internal_blacklist WHERE is_active = 1")
    except sqlite3.OperationalError:
        print("Table internal_blacklist not found. Skipping blacklist indexing.")
        conn.close()
        return 0
        
    rows = cursor.fetchall()
    actions = []
    
    for row in rows:
        raw_date = row['created_at'] if 'created_at' in row.keys() else None
        if raw_date and isinstance(raw_date, str):
            raw_date = raw_date.replace(' ', 'T')
            
        doc = {
            "name": row['full_name'],
            "name_arabic": row['original_name'] if row['original_name'] else "",
            "name_latin": row['full_name'],
            "source": "INTERNAL",
            "entity_type": row['entity_type'] if row['entity_type'] else "UNKNOWN",
            "list_date": raw_date,
            "is_internal_blacklist": True,
            "original_id": row['id']
        }
        
        action = {
            "_index": bl_index,
            "_id": f"bl_{row['id']}",
            "_source": doc
        }
        actions.append(action)

    if actions:
        helpers.bulk(es, actions)
        
    conn.close()
    return len(actions)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Load Watchlist data into Elasticsearch")
    parser.add_argument("--source", type=str, default="all", help="Source to index (all)")
    parser.add_argument("--confirm", action="store_true", help="Confirm execution")
    args = parser.parse_args()

    if not args.confirm:
        print("Please rerun with --confirm flag to execute.")
        return

    print("── Elasticsearch Indexer — ComplyNex Screening ──")
    start_time = time.time()
    
    try:
        es = get_es_client()
        host = os.getenv('ES_HOST', 'localhost')
        port = os.getenv('ES_PORT', 9200)
        
        if not es.ping():
            print(f"FAILED: Cannot connect to Elasticsearch at {host}:{port}")
            return
            
        print(f"Connecting to: {host}:{port} ... OK")
        
        wl_index = os.getenv('ES_INDEX_WATCHLIST', 'complynex_watchlist')
        bl_index = os.getenv('ES_INDEX_BLACKLIST', 'complynex_blacklist')
        
        setup_indices(es, wl_index, bl_index)
        
        print(f"\nIndex: {wl_index}")
        total_wl, stats = index_watchlist(es, wl_index)
        
        for k, v in stats.items():
            print(f"  {k} records indexed: {v:>10,}")
            
        print(f"  Total watchlist records: {total_wl:>10,}")
        
        print(f"\nIndex: {bl_index}")
        total_bl = index_blacklist(es, bl_index)
        print(f"  Internal blacklist records: {total_bl:>4,}")
        print(f"  is_internal_blacklist = true: {total_bl:>3,}")
        
        elapsed = time.time() - start_time
        print(f"\n✅ Indexing complete. Total time: {elapsed:.1f} seconds")
        
    except helpers.BulkIndexError as e:
        print(f"\n❌ Bulk Index Error: {e}")
        for err in e.errors[:5]:
            print(f"Sample Rejected Doc: {err}")
    except Exception as e:
        print(f"\n❌ Error during indexing: {e}")

if __name__ == "__main__":
    main()
