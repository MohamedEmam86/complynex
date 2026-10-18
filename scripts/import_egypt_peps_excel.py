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

"""
Dedicated Importer for Egypt PEP Excel File
Handles specific layout: Title row, Header row, Newline-separated aliases with numbering.
"""

import os
import sys
import json
import hashlib
import logging
import sqlite3
import openpyxl
from datetime import datetime

try:
    import psycopg
except ImportError:
    psycopg = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database config
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'dbname': os.getenv('DB_NAME', 'complynex_dev'),
    'user': os.getenv('DB_USER', 'complynex_dev'),
    'password': os.getenv('DB_PASSWORD', 'dev_password_123'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'type': os.getenv('DB_TYPE', 'sqlite'),
    'sqlite_path': os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex_cms.db')
}

def get_db_connection():
    if DB_CONFIG['type'] == 'postgresql':
        return psycopg.connect(
            host=DB_CONFIG['host'],
            dbname=DB_CONFIG['dbname'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            port=DB_CONFIG['port']
        )
    else:
        conn = sqlite3.connect(DB_CONFIG['sqlite_path'])
        conn.row_factory = sqlite3.Row
        return conn

def get_param():
    return "%s" if DB_CONFIG['type'] == 'postgresql' else "?"

def normalize_arabic(text):
    if not text: return ""
    import re
    # Basic Arabic normalization
    text = str(text)
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ٱ', 'ا')
    text = text.replace('ى', 'ي').replace('ة', 'ه')
    text = text.replace('ؤ', 'ء').replace('ئ', 'ء')
    text = re.sub(r'[\u064B-\u0652]', '', text) # Strip tashkeel
    return ' '.join(text.split()).strip()

def normalize_english(text):
    if not text: return ""
    text = str(text).upper()
    import re
    text = re.sub(r'[^A-Z0-9\s]', '', text)
    return ' '.join(text.split()).strip()

def parse_aliases(alias_text):
    if not alias_text: return []
    aliases = []
    # Split by newline
    raw_lines = str(alias_text).split('\n')
    for line in raw_lines:
        line = line.strip()
        if not line: continue
        # Remove numbers like "1. ", "1- ", "(1) "
        import re
        clean_line = re.sub(r'^[\(\[\d]+\s*[\.\-\)]\s*', '', line)
        if clean_line:
            aliases.append(clean_line.strip())
    return aliases

def import_egypt_peps(file_path, dry_run=False):
    logger.info(f"Starting import of {file_path} (Dry Run: {dry_run})")
    
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    
    # Structure:
    # Row 1: Title (Egypt PEP List Dataset...)
    # Row 2: Headers (Name, Position, Aliases...)
    
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 3:
        logger.error("Excel file doesn't have enough rows.")
        return

    headers = rows[1]
    data_rows = rows[2:]
    
    entities = []
    source_name = 'egypt_pep_excel'
    
    for idx, row in enumerate(data_rows):
        name = row[0]
        position = row[1]
        raw_aliases = row[2]
        
        if not name: continue
        
        name = str(name).strip()
        aliases = parse_aliases(raw_aliases)
        
        # Identity Logic
        is_arabic = any('\u0600' <= c <= '\u06FF' for c in name)
        normalized = normalize_arabic(name) if is_arabic else normalize_english(name)
        
        # Generation
        source_id = f"egypt_pep_{hashlib.md5(name.encode()).hexdigest()[:12]}"
        
        entity = {
            'full_name': name,
            'original_name': name,
            'aliases': aliases,
            'entity_type': 'PERSON',
            'list_type': 'PEP',
            'dataset': 'egypt_pep_manual',
            'topics': ['pep', 'egypt', 'manual_import', position] if position else ['pep', 'egypt'],
            'countries': ['Egypt'],
            'nationality': 'Egyptian',
            'source_id': source_id,
            'normalized': normalized,
            'properties': {
                'position': position,
                'import_date': datetime.now().isoformat()
            }
        }
        entities.append(entity)
        if idx < 3:
            logger.info(f"Parsed: {name} (Aliases: {len(aliases)})")

    logger.info(f"Total parsed: {len(entities)}")
    
    if dry_run or not entities:
        return {'added': 0, 'updated': 0}

    # Database Import
    db_conn = get_db_connection()
    cursor = db_conn.cursor()
    param = get_param()
    
    # Ensure source exists
    cursor.execute(f"""
        INSERT INTO screening_data_sources (source_name, source_display_name, source_type, is_active)
        VALUES ({param}, 'Egypt PEP List (Manual)', 'CUSTOM', TRUE)
        ON CONFLICT (source_name) DO NOTHING
    """, (source_name,))
    
    records = []
    for e in entities:
        # Compatibility with our DB schema
        try:
            import jellyfish
            soundex = jellyfish.soundex(e['normalized']) if e['normalized'] else None
            metaphone = jellyfish.metaphone(e['normalized']) if e['normalized'] else None
        except ImportError:
            soundex, metaphone = None, None
            
        def to_db_list(val):
            if DB_CONFIG['type'] == 'sqlite':
                return json.dumps(val) if val is not None else None
            return val

        records.append((
            e['full_name'],
            e['original_name'],
            to_db_list(e['aliases']),
            e['entity_type'],
            e['list_type'],
            e['dataset'],
            to_db_list(e['topics']),
            None, # DOB
            None, # YOB
            None, # POB
            None, # Gender
            to_db_list(e['countries']),
            e['nationality'],
            to_db_list([]), # Passport
            to_db_list([]), # National ID
            json.dumps({}), # Addresses
            source_name,
            e['source_id'],
            'Egypt PEP.xlsx',
            datetime.now().date(),
            datetime.now().date(),
            datetime.now(),
            e['normalized'],
            soundex,
            metaphone,
            to_db_list(e['normalized'].split()),
            'HIGH',
            json.dumps(e['properties']),
            datetime.now(),
            datetime.now(),
            True
        ))

    placeholder_str = ", ".join([param] * 31)
    
    query = f"""
        INSERT INTO screening_watchlist (
            full_name, original_name, aliases, entity_type, list_type, dataset, topics,
            date_of_birth, year_of_birth, place_of_birth, gender, countries, nationality,
            passport_numbers, national_id_numbers, addresses,
            source, source_id, source_url, first_seen, last_seen, last_updated,
            name_normalized, name_soundex, name_metaphone, name_tokens,
            risk_level, properties, created_at, updated_at, is_active
        ) VALUES ({placeholder_str})
        ON CONFLICT (source_id) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            aliases = EXCLUDED.aliases,
            topics = EXCLUDED.topics,
            last_seen = EXCLUDED.last_seen,
            last_updated = EXCLUDED.last_updated,
            updated_at = EXCLUDED.updated_at
    """
    
    try:
        cursor.executemany(query, records)
        db_conn.commit()
        
        # Update statistics
        cursor.execute(f"UPDATE screening_data_sources SET total_records = (SELECT COUNT(*) FROM screening_watchlist WHERE source = {param}), last_successful_update = {param} WHERE source_name = {param}", (source_name, datetime.now(), source_name))
        db_conn.commit()
    except Exception as ex:
        logger.error(f"Database error: {ex}")
        db_conn.rollback()
    finally:
        db_conn.close()

    logger.info("Import complete.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--path', default=r'C:\Users\Dina\Downloads\Kimi_Agent_Complynexpay Compliance Gem Design\Egypt PEP.xlsx')
    args = parser.parse_args()
    
    import_egypt_peps(args.path, args.dry_run)
