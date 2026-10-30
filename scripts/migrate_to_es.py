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
import os
import time

# Tell Python to look in the main folder for the app
sys.path.append('/opt/complynex')

from elasticsearch import Elasticsearch, helpers
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from screening.es_client import get_es_client  # noqa: E402  (credentials from .env)
from app import create_app
from database.db import get_db

es = get_es_client(timeout=120)
INDEX_NAME = "aml_watchlist"

def setup_index():
    from screening.es_client import guard_es_write
    guard_es_write('migrate_to_es')
    if es.indices.exists(index=INDEX_NAME):
        es.indices.delete(index=INDEX_NAME)
        print(f"🗑️ Deleted old index '{INDEX_NAME}'")
    
    mapping = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "db_id": {"type": "integer"},
                "search_names": {"type": "text"},
                "full_name": {"type": "text"},
                "date_of_birth": {"type": "keyword"},
                "nationality": {"type": "keyword"},
                "national_id_numbers": {"type": "keyword"},
                "source": {"type": "keyword"},
                "risk_level": {"type": "keyword"}
            }
        }
    }
    es.indices.create(index=INDEX_NAME, body=mapping)
    print(f"🏗️ Created optimized index '{INDEX_NAME}'")

def generate_actions(rows):
    for r in rows:
        # Safely combine all name variations into one massive search block
        names = [
            r.get('full_name'), 
            r.get('original_name'), 
            r.get('aliases'), 
            r.get('aliases_arabic')
        ]
        # Clean out Nones and empty strings
        search_names = " ".join([str(n) for n in names if n])
        
        yield {
            "_index": INDEX_NAME,
            "_id": str(r['id']),
            "_source": {
                "db_id": r['id'],
                "search_names": search_names,
                "full_name": r.get('full_name'),
                "date_of_birth": r.get('date_of_birth'),
                "nationality": r.get('nationality'),
                "national_id_numbers": r.get('national_id_numbers'),
                "source": r.get('source'),
                "risk_level": r.get('risk_level')
            }
        }

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        setup_index()
        db = get_db()
        print("⏳ Fetching 800,000+ records from PostgreSQL... (Please wait)")
        
        query = """
            SELECT id, full_name, original_name, aliases, aliases_arabic, 
                   date_of_birth, nationality, national_id_numbers, 
                   source, risk_level 
            FROM screening_watchlist
        """
        rows = db.execute(query).fetchall()
        total = len(rows)
        print(f"✅ Loaded {total} records from DB. Pushing to Elasticsearch...")
        
        start_time = time.time()
        # Push to ES in chunks of 5000 to keep RAM usage low
        success, _ = helpers.bulk(es, generate_actions(rows), chunk_size=5000)
        elapsed = time.time() - start_time
        
        print(f"🚀 SUCCESS! Indexed {success} / {total} records into Elasticsearch in {elapsed:.2f} seconds!")
