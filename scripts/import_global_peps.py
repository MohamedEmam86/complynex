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


import csv
import io
import json
import logging
import requests
import os
import re
import sqlite3
from datetime import datetime
from collections import defaultdict

try:
    import pyarabic.araby as araby
    HAS_ARABY = True
except ImportError:
    HAS_ARABY = False

try:
    import jellyfish
    HAS_JELLYFISH = True
except ImportError:
    HAS_JELLYFISH = False

# DB Support
try:
    import psycopg
    from psycopg.rows import dict_row
    PG_AVAILABLE = True
    PG_VERSION = 3
except ImportError:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        PG_AVAILABLE = True
        PG_VERSION = 2
    except ImportError:
        PG_AVAILABLE = False

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, '.env')
DB_PATH = os.path.join(BASE_DIR, 'complynex_cms.db')

# ── OpenSanctions PEP Data Sources ──
# CSV is ~30x faster than FTM JSON for import
OPENSANCTIONS_PEPS_CSV = "https://data.opensanctions.org/datasets/latest/peps/targets.simple.csv"
OPENSANCTIONS_PEPS_JSON = "https://data.opensanctions.org/datasets/latest/peps/entities.ftm.json"
OPENSANCTIONS_PEPS_XLSX = "https://data.opensanctions.org/datasets/latest/peps/targets.nested.xlsx"

# Load .env manually
DB_CONFIG = {}
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                DB_CONFIG[k] = v

# Determine DB connection
USE_POSTGRES = False  # Force SQLite for local dev

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def normalize_text(text):
    """Normalize text (Arabic and general)"""
    if not text:
        return ""
    if HAS_ARABY:
        text = araby.strip_tashkeel(text)
        text = re.sub(r'[أإآٱ]', 'ا', text)
        text = text.replace('ى', 'ي')
        text = text.replace('ة', 'ه')
        text = araby.strip_tatweel(text)
    text = ' '.join(text.split())
    return text.strip().upper()


class GlobalPEPImporter:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.stats = {
            'processed': 0,
            'peps_found': 0,
            'added': 0,
            'updated': 0,
            'errors': 0
        }
        self.BATCH_SIZE = 500

    def get_db_connection(self):
        if USE_POSTGRES:
            try:
                if PG_VERSION == 3:
                    return psycopg.connect(
                        dbname=DB_CONFIG.get('DB_NAME'),
                        user=DB_CONFIG.get('DB_USER'),
                        password=DB_CONFIG.get('DB_PASSWORD'),
                        host=DB_CONFIG.get('DB_HOST'),
                        port=DB_CONFIG.get('DB_PORT', 5432),
                        row_factory=dict_row
                    )
                else:
                    return psycopg2.connect(
                        dbname=DB_CONFIG.get('DB_NAME'),
                        user=DB_CONFIG.get('DB_USER'),
                        password=DB_CONFIG.get('DB_PASSWORD'),
                        host=DB_CONFIG.get('DB_HOST'),
                        port=DB_CONFIG.get('DB_PORT', 5432)
                    )
            except Exception as e:
                logger.error(f"PostgreSQL connection failed: {e}")
                return None
        else:
            return sqlite3.connect(self.db_path)

    def import_peps(self, limit=None):
        """
        Import PEPs from OpenSanctions CSV format.
        CSV is much faster than streaming FTM JSON (~30x speedup).
        """
        logger.info(f"Starting CSV import from {OPENSANCTIONS_PEPS_CSV}...")

        conn = self.get_db_connection()
        if not conn:
            logger.error("Failed to connect to database")
            return

        try:
            # Download CSV with streaming to avoid blocking on huge files and reduce memory usage
            logger.info(f"Downloading PEP CSV data from {OPENSANCTIONS_PEPS_CSV}...")
            # Increase timeout to 300s for slow connections
            response = requests.get(OPENSANCTIONS_PEPS_CSV, stream=True, timeout=300)
            response.raise_for_status()
            
            # Use response.iter_lines to stream the CSV content
            lines = (line.decode('utf-8') for line in response.iter_lines())
            reader = csv.DictReader(lines)

            batch_records = []
            ph = '%s' if USE_POSTGRES else '?'
            cursor = conn.cursor()
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            today_str = datetime.now().strftime('%Y-%m-%d')

            for row in reader:
                self.stats['processed'] += 1

                if limit and self.stats['peps_found'] >= limit:
                    break

                # Extract fields from CSV columns
                entity_id = row.get('id', '').strip()
                schema = row.get('schema', '').strip()
                name = row.get('name', '').strip()
                
                if not name or len(name) < 2:
                    continue

                # Only import Person entities
                if schema and schema != 'Person':
                    continue

                self.stats['peps_found'] += 1

                # Parse CSV fields
                aliases_str = row.get('aliases', '') or ''
                aliases = [a.strip() for a in aliases_str.split(';') if a.strip()] if aliases_str else []

                birth_date = row.get('birth_date', '') or None
                yob = None
                if birth_date:
                    match = re.search(r'(\d{4})', birth_date)
                    if match:
                        yob = int(match.group(1))

                countries_str = row.get('countries', '') or ''
                countries = [c.strip() for c in countries_str.split(';') if c.strip()] if countries_str else []
                
                # Get first country as nationality
                nationality = countries[0] if countries else None

                # Build normalized name for search
                name_upper = normalize_text(name) or name.upper()
                
                # Soundex/metaphone for search optimization
                soundex, metaphone = None, None
                if HAS_JELLYFISH and name.isascii():
                    try:
                        soundex = jellyfish.soundex(name_upper)
                        metaphone = jellyfish.metaphone(name_upper)
                    except:
                        pass
                
                name_tokens = name_upper.split() if name_upper else []

                # Build properties from extra CSV columns
                topics_str = row.get('topics', '') or ''
                topics = [t.strip() for t in topics_str.split(';') if t.strip()] if topics_str else ['role.pep']
                dataset = row.get('datasets', 'opensanctions_peps') or 'opensanctions_peps'
                
                # Gender, addresses, identifiers
                addresses_str = row.get('addresses', '') or ''
                identifiers_str = row.get('identifiers', '') or ''

                properties = {
                    'topics': topics,
                    'datasets': dataset,
                    'addresses': addresses_str,
                    'identifiers': identifiers_str,
                    'caption': row.get('caption', ''),
                    'first_seen': row.get('first_seen', ''),
                    'last_seen': row.get('last_seen', ''),
                    'last_change': row.get('last_change', ''),
                }

                source_id = f"os_pep_{entity_id}" if entity_id else f"os_pep_{hash(name) & 0xFFFFFFFF:08x}"

                record = (
                    name,                                    # full_name
                    name,                                    # original_name
                    json.dumps(aliases[:10]),                 # aliases (JSON array)
                    'PERSON',                                # entity_type
                    'PEP',                                   # list_type
                    'opensanctions_peps',                    # dataset
                    json.dumps(topics[:5]),                   # topics (JSON array)
                    birth_date if birth_date and len(birth_date) == 10 else None,  # date_of_birth
                    yob,                                     # year_of_birth
                    None,                                    # place_of_birth
                    None,                                    # gender
                    json.dumps(countries[:5]),                # countries (JSON array)
                    nationality,                             # nationality
                    json.dumps([]),                           # passport_numbers
                    json.dumps([]),                           # national_id_numbers
                    None,                                    # addresses
                    'opensanctions',                         # source
                    source_id,                               # source_id
                    'https://www.opensanctions.org/',         # source_url
                    today_str, today_str, now_str,            # first_seen, last_seen, last_updated
                    name_upper,                              # name_normalized
                    soundex,                                 # name_soundex
                    metaphone,                               # name_metaphone
                    json.dumps(name_tokens),                  # name_tokens
                    'MEDIUM',                                # risk_level (PEPs = MEDIUM)
                    json.dumps(properties),                   # properties
                    now_str, now_str, 1                       # created_at, updated_at, is_active
                )
                batch_records.append(record)

                # Flush batch
                if len(batch_records) >= self.BATCH_SIZE:
                    self._flush_batch(cursor, batch_records, ph)
                    conn.commit()
                    batch_records = []
                    logger.info(f"  Batch committed: {self.stats['peps_found']} PEPs processed so far...")

                if self.stats['processed'] % 10000 == 0:
                    logger.info(f"  Read {self.stats['processed']} CSV rows... ({self.stats['peps_found']} PEPs)")

            # Flush remaining records
            if batch_records:
                self._flush_batch(cursor, batch_records, ph)
                conn.commit()

            # Update screening_data_sources
            cursor.execute(f"""
                UPDATE screening_data_sources
                SET last_successful_update = CURRENT_TIMESTAMP,
                    total_records = (SELECT COUNT(*) FROM screening_watchlist WHERE source = 'opensanctions_pep')
                WHERE source_name = 'opensanctions_pep'
            """)
            conn.commit()

            # Get final count
            cursor.execute("SELECT COUNT(*) FROM screening_watchlist WHERE source = 'opensanctions_pep'")
            final_count = cursor.fetchone()[0]
            self.stats['added'] = max(0, final_count - (final_count - self.stats['peps_found']))

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error downloading PEP data: {e}")
            self.stats['errors'] += 1
            raise
        except Exception as e:
            logger.error(f"Import failed: {e}")
            import traceback
            traceback.print_exc()
            self.stats['errors'] += 1
            raise
        finally:
            conn.close()

        logger.info(f"Import finished. Stats: {self.stats}")

    def _flush_batch(self, cursor, records, ph):
        """Insert/update a batch of records into screening_watchlist"""
        sql = f"""INSERT INTO screening_watchlist (
            full_name, original_name, aliases, entity_type, list_type, dataset, topics,
            date_of_birth, year_of_birth, place_of_birth, gender, countries, nationality,
            passport_numbers, national_id_numbers, addresses,
            source, source_id, source_url, first_seen, last_seen, last_updated,
            name_normalized, name_soundex, name_metaphone, name_tokens,
            risk_level, properties, created_at, updated_at, is_active
        ) VALUES ({', '.join([ph]*31)})
        ON CONFLICT (source_id) DO UPDATE SET
            full_name = excluded.full_name,
            original_name = excluded.original_name,
            aliases = excluded.aliases,
            countries = excluded.countries,
            nationality = excluded.nationality,
            last_seen = excluded.last_seen,
            last_updated = excluded.last_updated,
            updated_at = excluded.updated_at,
            properties = excluded.properties"""

        try:
            cursor.executemany(sql, records)
            # Count as added (approximate — real count updated at end)
            self.stats['added'] += len(records)
        except Exception as e:
            logger.error(f"Batch insert error: {e}")
            self.stats['errors'] += len(records)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Import Global PEPs from OpenSanctions')
    parser.add_argument('--limit', type=int, help='Limit number of PEP records to import', default=None)
    args = parser.parse_args()

    importer = GlobalPEPImporter()
    print(f"Starting Global PEP Import (CSV)... (Source: {OPENSANCTIONS_PEPS_CSV})")
    if args.limit:
        print(f"Limit set to {args.limit} records.")

    importer.import_peps(limit=args.limit)
    print(f"\nFinal stats: {importer.stats}")
