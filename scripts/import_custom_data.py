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
Import Custom Data (CSV/XLSX) to Watchlist
Supports flexible column mapping and format detection without pandas
"""

import os
import sys
import argparse
import csv
import openpyxl
import psycopg
import json
import logging
import hashlib
from datetime import datetime
import jellyfish
from pyarabic import araby

# Setup logging
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'custom_import.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Database config
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'dbname': os.getenv('DB_NAME', 'complynex_dev'),
    'user': os.getenv('DB_USER', 'complynex_dev'),
    'password': os.getenv('DB_PASSWORD', 'dev_password_123'),
    'port': int(os.getenv('DB_PORT', 5432))
}

def normalize_arabic(text):
    if not text: return ""
    text = araby.strip_tashkeel(str(text))
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ٱ', 'ا')
    text = text.replace('ى', 'ي').replace('ة', 'ه')
    text = text.replace('ؤ', 'ء').replace('ئ', 'ء')
    return ' '.join(text.split()).strip()

def normalize_english(text):
    if not text: return ""
    STOP_WORDS = {'MR', 'MRS', 'MS', 'DR', 'PROF', 'SIR', 'LADY', 'THE', 'AND', 'OF', 'LLC', 'INC', 'LTD'}
    text_upper = str(text).upper()
    tokens = text_upper.split()
    filtered = [t for t in tokens if t not in STOP_WORDS]
    processed = ''.join(c for c in ' '.join(filtered) if c.isalnum() or c.isspace())
    return ' '.join(processed.split()).strip()

class CustomImporter:
    def __init__(self, file_path, source_name, mapping=None):
        self.file_path = file_path
        self.source_name = source_name
        self.mapping = mapping or {}
        self.data = [] # List of dicts
        self.headers = []
        
    def load_file(self):
        """Load file into list of dicts"""
        ext = os.path.splitext(self.file_path)[1].lower()
        try:
            if ext == '.csv':
                with open(self.file_path, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    self.headers = reader.fieldnames
                    self.data = list(reader)
            elif ext in ['.xlsx', '.xls']:
                wb = openpyxl.load_workbook(self.file_path, read_only=True, data_only=True)
                ws = wb.active
                rows = list(ws.rows)
                if not rows:
                    raise ValueError("Empty Excel file")
                
                # Assume first row is header
                self.headers = [str(cell.value).strip() if cell.value else f"col_{i}" for i, cell in enumerate(rows[0])]
                
                for row in rows[1:]:
                    record = {}
                    for i, cell in enumerate(row):
                        if i < len(self.headers):
                            record[self.headers[i]] = cell.value
                    self.data.append(record)
                wb.close()
            else:
                raise ValueError(f"Unsupported file format: {ext}")
            
            # Normalize headers keys in data
            self.headers_normalized = [str(h).strip().lower().replace(' ', '_') for h in self.headers]
            
            # Remap data keys to normalized headers
            normalized_data = []
            for row in self.data:
                new_row = {}
                for k, v in row.items():
                    norm_k = str(k).strip().lower().replace(' ', '_')
                    new_row[norm_k] = v
                normalized_data.append(new_row)
            self.data = normalized_data
            
            logger.info(f"Loaded {len(self.data)} records from {self.file_path}")
            logger.info(f"Columns: {self.headers_normalized}")
            
        except Exception as e:
            logger.error(f"Failed to load file: {e}")
            raise

    def detect_columns(self):
        """Auto-detect column mapping if not provided"""
        # Common variations for key fields
        guesses = {
            'full_name': ['name', 'full_name', 'entity_name', 'client_name', 'party_name'],
            'dob': ['dob', 'date_of_birth', 'birth_date', 'birthdate'],
            'nationality': ['nationality', 'country', 'citizenship'],
            'id_number': ['id', 'national_id', 'passport', 'passport_number', 'identification', 'passport_no'],
            'address': ['address', 'location', 'residence']
        }
        
        detected = {}
        for target, candidates in guesses.items():
            if target in self.mapping:
                continue
            
            for col in self.headers_normalized:
                if col in candidates:
                    detected[target] = col
                    break
            
            # Fuzzy match or contains if simple match fails
            if target not in detected and target not in self.mapping:
                for col in self.headers_normalized:
                    if target.replace('_', '') in col.replace('_', ''):
                         detected[target] = col
                         break
                    
        # Merge detected into mapping
        self.mapping.update(detected)
        logger.info(f"Column mapping: {self.mapping}")
        
        if 'full_name' not in self.mapping:
            raise ValueError(f"Could not detect 'full_name' column. Available: {self.headers_normalized}. Please provide mapping.")

    def import_data(self):
        """Process and import data"""
        conn = psycopg.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        records = []
        skipped = 0
        
        # Prepare source entry
        cursor.execute("""
            INSERT INTO screening_data_sources (source_name, source_display_name, source_url, source_type, is_active)
            VALUES (%s, %s, %s, 'CUSTOM', TRUE)
            ON CONFLICT (source_name) DO NOTHING
        """, (self.source_name, f"Custom: {self.source_name}", 'local_upload'))
        conn.commit()
        
        for idx, row in enumerate(self.data):
            try:
                # Extract fields using mapping
                full_name_col = self.mapping.get('full_name')
                full_name = str(row.get(full_name_col, '')).strip()
                
                if not full_name or len(full_name) < 2:
                    skipped += 1
                    continue
                
                id_col = self.mapping.get('id_number')
                raw_id = str(row.get(id_col)).strip() if id_col and row.get(id_col) else None
                
                # Generate source_id
                if raw_id:
                    source_id = f"{self.source_name}_{raw_id}"
                else:
                    source_id = f"{self.source_name}_{idx}_{hashlib.md5(full_name.encode()).hexdigest()[:8]}"
                
                # Normalization
                is_arabic = any('\u0600' <= c <= '\u06FF' for c in full_name)
                normalized = normalize_arabic(full_name) if is_arabic else normalize_english(full_name)
                
                dob_col = self.mapping.get('dob')
                dob_raw = row.get(dob_col)
                # Basic date parsing could be added
                
                nat_col = self.mapping.get('nationality')
                nationality = str(row.get(nat_col, '')).strip()
                
                # Set list_type based on source
                list_type = 'PEP' if 'pep' in self.source_name.lower() else 'CUSTOM'

                records.append((
                    full_name,
                    full_name,
                    [], 
                    'PERSON',
                    list_type,
                    self.source_name,
                    [],
                    None,
                    None,
                    None,
                    None,
                    [],
                    nationality,
                    [raw_id] if raw_id else [], # passport (simplified storage in passport column)
                    [],
                    '{}',
                    self.source_name,
                    source_id,
                    'custom_upload',
                    datetime.now().date(),
                    datetime.now().date(),
                    datetime.now(),
                    normalized,
                    jellyfish.soundex(normalized) if normalized else None,
                    jellyfish.metaphone(normalized) if normalized else None,
                    normalized.split() if normalized else [],
                    'HIGH',
                    '{}',
                    datetime.now(),
                    datetime.now(),
                    True
                ))
                
            except Exception as e:
                logger.warning(f"Skipped row {idx}: {e}")
                skipped += 1
        
        if records:
            # Bulk upsert
            cursor.executemany("""
                INSERT INTO screening_watchlist (
                    full_name, original_name, aliases, entity_type, list_type, dataset, topics,
                    date_of_birth, year_of_birth, place_of_birth, gender, countries, nationality,
                    passport_numbers, national_id_numbers, addresses,
                    source, source_id, source_url, first_seen, last_seen, last_updated,
                    name_normalized, name_soundex, name_metaphone, name_tokens,
                    risk_level, properties, created_at, updated_at, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    last_seen = EXCLUDED.last_seen,
                    last_updated = EXCLUDED.last_updated,
                    updated_at = EXCLUDED.updated_at
            """, records)
            conn.commit()
            
        conn.close()
        logger.info(f"Import complete. Added/Updated: {len(records)}, Skipped: {skipped}")
        print(json.dumps({'success': True, 'added': len(records), 'skipped': skipped}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('file_path', help='Path to CSV/XLSX file')
    parser.add_argument('--source', required=True, help='Source name (e.g. internal_list)')
    parser.add_argument('--mapping', help='JSON string column mapping')
    args = parser.parse_args()
    
    mapping = json.loads(args.mapping) if args.mapping else None
    
    try:
        importer = CustomImporter(args.file_path, args.source, mapping)
        importer.load_file()
        importer.detect_columns()
        importer.import_data()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(json.dumps({'success': False, 'error': str(e)}))
        sys.exit(1)
