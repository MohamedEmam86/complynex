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

import sys, argparse
from elasticsearch import Elasticsearch
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from screening.es_client import get_es_client  # noqa: E402  (credentials from .env)

ES_HOST  = "http://localhost:9200"
ES_INDEX = "aml_watchlist"

MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "refresh_interval": "30s",
        "analysis": {
            "analyzer": {
                "arabic_custom": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "arabic_normalization", "arabic_stemmer"]
                },
                "trigram": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "shingle"]
                }
            },
            "filter": {
                "arabic_stemmer": {"type": "stemmer", "language": "arabic"},
                "shingle": {"type": "shingle", "min_shingle_size": 2, "max_shingle_size": 3, "output_unigrams": True}
            }
        }
    },
    "mappings": {
        "properties": {
            "original_name": {
                "type": "text", "analyzer": "arabic_custom",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}, "trigram": {"type": "text", "analyzer": "trigram"}}
            },
            "full_name": {"type": "text", "analyzer": "arabic_custom", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "name_ar": {"type": "text", "analyzer": "arabic_custom", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "name_en": {"type": "text", "analyzer": "english", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "name_normalized": {"type": "text", "analyzer": "arabic_custom"},
            "national_id": {"type": "keyword"}, "passport_number": {"type": "keyword"},
            "date_of_birth": {"type": "keyword"}, "nationality": {"type": "keyword"},
            "gender": {"type": "keyword"}, "source": {"type": "keyword"},
            "list_type": {"type": "keyword"}, "entity_type": {"type": "keyword"},
            "category": {"type": "keyword"}, "program": {"type": "keyword"},
            "watchlist_id": {"type": "long"},
            "pg_updated_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "es_indexed_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "remarks": {"type": "text"}, "aliases": {"type": "text", "analyzer": "arabic_custom"}
        }
    }
}

def create_index(force: bool = False):
    from screening.es_client import guard_es_write
    guard_es_write('es_create_index')
    es = get_es_client()
    if not es.ping():
        print("FATAL: Cannot reach Elasticsearch at", ES_HOST); sys.exit(1)
    if es.indices.exists(index=ES_INDEX):
        if force:
            print(f"  --force: Deleting existing index '{ES_INDEX}' ...")
            es.indices.delete(index=ES_INDEX)
        else:
            print(f"  Index '{ES_INDEX}' already exists. Use --force to recreate.")
            return False
    print(f"  Creating index '{ES_INDEX}' ...")
    es.indices.create(index=ES_INDEX, body=MAPPING)
    print(f"  Index '{ES_INDEX}' created successfully ✓")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    create_index(force=args.force)
