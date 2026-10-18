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
Scrape OpenSanctions data sources (Sanctions & PEPs) with Smart Updates
"""

import os
import sys
import requests
import json
import hashlib
import sqlite3
import logging
from datetime import datetime
import psycopg2
import jellyfish
from pyarabic import araby

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass
from config import Config

# Setup logging
log_dir = os.path.join(BASE_DIR, 'logs')
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'data_scraping.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Database config — single source of truth (config.Config.POSTGRES_CONFIG,
# the same dict the live app connects with), not an ad-hoc DB_HOST/DB_NAME/...
# dict with its own (wrong) defaults.
DB_CONFIG = dict(Config.POSTGRES_CONFIG)
DB_CONFIG['type'] = Config.DB_TYPE
DB_CONFIG['sqlite_path'] = os.path.join(BASE_DIR, 'complynex_cms.db')

def get_db_connection():
    if DB_CONFIG['type'] == 'postgresql':
        return psycopg2.connect(
            host=DB_CONFIG['host'],
            dbname=DB_CONFIG['database'],
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


# OpenSanctions Configuration
OPENSANCTIONS_DATASETS = {
    'sanctions': {
        'url': 'https://data.opensanctions.org/datasets/latest/sanctions/entities.ftm.json',
        'metadata_url': 'https://data.opensanctions.org/datasets/latest/sanctions/index.json',
        'type': 'SANCTIONS'
    },
    'pep': {
        'url': 'https://data.opensanctions.org/datasets/latest/peps/entities.ftm.json',
        'metadata_url': 'https://data.opensanctions.org/datasets/latest/peps/index.json',
        'type': 'PEP'
    }
}


def normalize_arabic(text):
    """Standardized Arabic normalization"""
    if not text:
        return ""
    from pyarabic import araby
    text = araby.strip_tashkeel(text)
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ٱ', 'ا')
    text = text.replace('ى', 'ي')
    text = text.replace('ة', 'ه')
    text = text.replace('ؤ', 'ء').replace('ئ', 'ء')
    text = araby.strip_tatweel(text)
    return ' '.join(text.split()).strip()


def normalize_english(text):
    """Normalize English text"""
    if not text:
        return ""
    STOP_WORDS = {'MR', 'MRS', 'MS', 'DR', 'PROF', 'SIR', 'LADY', 'THE', 'AND', 'OF', 'LLC', 'INC', 'LTD'}
    text_upper = text.upper()
    tokens = text_upper.split()
    filtered = [t for t in tokens if t not in STOP_WORDS]
    processed = ''.join(c for c in ' '.join(filtered) if c.isalnum() or c.isspace())
    return ' '.join(processed.split()).strip()


class DataSourceScraper:
    """Base class for scrapers"""
    
    def __init__(self, db_conn):
        self.db_conn = db_conn
        self.source_name = None
    
    def log_update_start(self):
        cursor = self.db_conn.cursor()
        param = get_param()
        cursor.execute(f"""
            INSERT INTO screening_update_logs (source_name, update_status, triggered_by)
            VALUES ({param}, 'IN_PROGRESS', 'MANUAL')
        """, (self.source_name,))
        
        if DB_CONFIG['type'] == 'postgresql':
            update_id = cursor.execute("SELECT LASTVAL()").fetchone()[0]
        else:
            update_id = cursor.lastrowid
            
        self.db_conn.commit()
        return update_id
    
    def log_update_complete(self, update_id, stats, status='SUCCESS', error=None):
        try:
            if status == 'FAILED':
                self.db_conn.rollback()
            cursor = self.db_conn.cursor()
            param = get_param()
            
            # Duration calculation is different for SQLite
            if DB_CONFIG['type'] == 'postgresql':
                duration_sql = "EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - update_started_at))"
            else:
                duration_sql = "(strftime('%s', 'now') - strftime('%s', update_started_at))"

            cursor.execute(f"""
                UPDATE screening_update_logs SET
                    update_completed_at = CURRENT_TIMESTAMP,
                    duration_seconds = {duration_sql},
                    records_added = {param},
                    records_updated = {param},
                    update_status = {param},
                    error_message = {param}
                WHERE id = {param}
            """, (stats.get('added', 0), stats.get('updated', 0), status, error, update_id))

            
            if status == 'SUCCESS':
                # Map internal keys to actual database source_name values
                db_source_name = self.source_name
                if self.source_name == 'sanctions':
                    db_source_name = 'opensanctions'
                elif self.source_name == 'pep':
                    db_source_name = 'opensanctions_pep'

                # Update last successful update timestamp
                param = get_param()
                cursor.execute(f"""
                    UPDATE screening_data_sources SET 
                        last_successful_update = CURRENT_TIMESTAMP,
                        records_added_last_update = {param},
                        records_updated_last_update = {param}
                    WHERE source_name = {param}
                """, (stats.get('added', 0), stats.get('updated', 0), db_source_name))

                
                # Update total record count from the watchlist table to be accurate
                db_source_name = self.source_name
                if self.source_name == 'sanctions':
                    db_source_name = 'opensanctions'
                elif self.source_name == 'pep':
                    db_source_name = 'opensanctions_pep'

                cursor.execute(f"""
                    UPDATE screening_data_sources SET
                        total_records = (SELECT COUNT(*) FROM screening_watchlist WHERE source = {param})
                    WHERE source_name = {param}
                """, (self.source_name, db_source_name))
            self.db_conn.commit()
        except Exception as log_err:
            logger.error(f"Failed to log update completion: {log_err}")
            try:
                self.db_conn.rollback()
            except Exception:
                pass
    
    @staticmethod
    def safe_date(date_str):
        if not date_str:
            return None
        try:
            from datetime import date as date_type
            parts = str(date_str).split('-')
            if len(parts) == 3:
                return date_type(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, TypeError):
            pass
        return None
    
    @staticmethod
    def safe_year(date_str):
        if not date_str:
            return None
        try:
            parts = str(date_str).split('-')
            year = int(parts[0])
            if 1900 <= year <= 2100:
                return year
        except (ValueError, TypeError):
            pass
        return None

    def import_entities(self, entities):
        """Bulk import entities with upsert"""
        if not entities:
            return {'added': 0, 'updated': 0}
        
        cursor = self.db_conn.cursor()
        
        # Get count before
        param = get_param()
        try:
            cursor.execute(f"SELECT COUNT(*) FROM screening_watchlist WHERE source = {param}", (self.source_name,))
            before_count = cursor.fetchone()[0]
        except Exception:
            self.db_conn.rollback()
            before_count = 0

        def to_db_list(val):
            if DB_CONFIG['type'] == 'sqlite':
                return json.dumps(val) if val is not None else None
            return val

        records = []
        for entity in entities:
            full_name = entity.get('full_name', '')
            is_arabic = any('\u0600' <= c <= '\u06FF' for c in full_name)
            
            if is_arabic:
                normalized = normalize_arabic(full_name)
            else:
                normalized = normalize_english(full_name)
            
            soundex = jellyfish.soundex(normalized) if normalized else None
            metaphone = jellyfish.metaphone(normalized) if normalized else None
            
            records.append((
                entity.get('full_name'),
                entity.get('original_name'),
                to_db_list(entity.get('aliases', [])),
                entity.get('entity_type'),
                entity.get('list_type'),
                entity.get('dataset'),
                to_db_list(entity.get('topics', [])),
                self.safe_date(entity.get('date_of_birth')),
                entity.get('year_of_birth') or self.safe_year(entity.get('date_of_birth')),
                entity.get('place_of_birth'),
                entity.get('gender'),
                to_db_list(entity.get('countries', [])),
                entity.get('nationality'),
                to_db_list(entity.get('passport_numbers', [])),
                to_db_list(entity.get('national_id_numbers', [])),
                json.dumps(entity.get('addresses', {})),
                self.source_name,
                entity.get('source_id'),
                entity.get('source_url'),
                datetime.now().date(),
                datetime.now().date(),
                datetime.now(),
                normalized,
                soundex,
                metaphone,
                to_db_list(normalized.split() if normalized else []),
                entity.get('risk_level'),
                json.dumps(entity.get('properties', {})),
                datetime.now(),
                datetime.now(),
                True
            ))
        
        # Upsert query
        param = get_param()
        placeholders = ", ".join([param] * 31)
        cursor.executemany(f"""
            INSERT INTO screening_watchlist (
                full_name, original_name, aliases, entity_type, list_type, dataset, topics,
                date_of_birth, year_of_birth, place_of_birth, gender, countries, nationality,
                passport_numbers, national_id_numbers, addresses,
                source, source_id, source_url, first_seen, last_seen, last_updated,
                name_normalized, name_soundex, name_metaphone, name_tokens,
                risk_level, properties, created_at, updated_at, is_active
            ) VALUES ({placeholders})
            ON CONFLICT (source, source_id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                aliases = EXCLUDED.aliases,
                topics = EXCLUDED.topics,
                countries = EXCLUDED.countries,
                last_seen = EXCLUDED.last_seen,
                last_updated = EXCLUDED.last_updated,
                updated_at = EXCLUDED.updated_at
        """, records)
        
        # Get count after
        cursor.execute(f"SELECT COUNT(*) FROM screening_watchlist WHERE source = {param}", (self.source_name,))
        after_count = cursor.fetchone()[0]
        
        self.db_conn.commit()
        
        stats = {
            'added': after_count - before_count,
            # Estimate updated (total processed - newly added)
            # This is rough because some might be unchanged, but good enough for stats
            'updated': len(entities) - (after_count - before_count)
        }
        
        return stats


class OpenSanctionsScraper(DataSourceScraper):
    """Generic Scraper for OpenSanctions datasets"""
    
    def __init__(self, db_conn, dataset_key, limit=None):
        super().__init__(db_conn)
        self.config = OPENSANCTIONS_DATASETS[dataset_key]
        self.dataset_key = dataset_key
        # source_name in DB will be 'opensanctions' or 'opensanctions_pep'
        self.source_name = 'opensanctions' if dataset_key == 'sanctions' else 'opensanctions_pep'
        self.limit = limit
        
    def check_updates(self):
        """Check metadata for updates"""
        try:
            logger.info(f"Checking for updates: {self.dataset_key}...")
            resp = requests.get(self.config['metadata_url'], timeout=30)
            resp.raise_for_status()
            metadata = resp.json()
            
            last_export = metadata.get('last_export', '')
            version = metadata.get('version', '')
            
            logger.info(f"  Remote version: {version} ({last_export})")
            # In a real sync, we'd compare this to DB stored version.
            # For now, we assume we always want to check/update if running manually.
            return True, version
        except Exception as e:
            logger.warning(f"  Failed to check metadata: {e}")
            return True, "unknown" # Fallback to update

    def scrape(self):
        """Download and parse streaming JSON"""
        should_update, version = self.check_updates()
        if not should_update:
            logger.info("  No updates found.")
            return {'added': 0, 'updated': 0}

        logger.info(f"Starting scrape for {self.dataset_key} (limit={self.limit})...")
        
        update_id = None
        try:
            logger.info(f"  Downloading from {self.config['url']}...")
            response = requests.get(self.config['url'], timeout=300, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            entities = []
            line_count = 0
            skipped = 0
            processed = 0
            total_stats = {'added': 0, 'updated': 0}
            update_id = self.log_update_start()
            
            for line in response.iter_lines(decode_unicode=True):
                if not line: continue
                line_count += 1
                
                # Speed limit: Stop if we've processed too many lines without finding enough matches
                # This ensures the test finishes in reasonable time.
                if self.limit and line_count > self.limit * 5:
                    logger.info(f"  Speed cap reached ({line_count} lines processed). Stopping.")
                    break
                
                if self.limit and processed >= self.limit:
                    logger.info(f"  Record limit reached ({processed} records). Stopping.")
                    break
                
                # Progress calculation
                if total_size > 0:
                    percent = min(90, int((downloaded + len(line) / total_size) * 90))
                elif self.limit:
                    percent = min(90, int((processed / self.limit) * 90))
                else:
                    percent = 0
                
                downloaded += len(line)
                
                if line_count % 100 == 0:
                     print(f"PROGRESS: {percent}", flush=True)
                     print(f"STATUS: Scanned {line_count} lines, found {processed} records...", flush=True)
                
                try:
                    data = json.loads(line)
                    
                    # Filtering
                    schema = data.get('schema')
                    if schema not in ['Person', 'Organization', 'Company', 'LegalEntity']:
                        skipped += 1
                        continue
                        
                    props = data.get('properties', {})
                    names = props.get('name', [])
                    if not names:
                        skipped += 1
                        continue
                    
                    # Determine list type
                    datasets = data.get('datasets', [])
                    

                    entities.append(data)
                    processed += 1
                    
                    if len(entities) >= 1000:
                        batch_stats = self.save_batch(entities)
                        total_stats['added'] += batch_stats.get('added', 0)
                        total_stats['updated'] += batch_stats.get('updated', 0)
                        entities = []
                        
                except json.JSONDecodeError:
                    continue
                    
            # Save remaining
            if entities:
                batch_stats = self.save_batch(entities)
                total_stats['added'] += batch_stats.get('added', 0)
                total_stats['updated'] += batch_stats.get('updated', 0)
                
            if update_id:
                self.log_update_complete(update_id, total_stats, 'SUCCESS', 'Completed successfully')
            print("PROGRESS: 100", flush=True)
            print(f"STATUS: Completed. Added {total_stats['added']}, Updated {total_stats['updated']}", flush=True)
            return total_stats
            
        except Exception as e:
            logger.error(f"  Scrape failed: {e}")
            if update_id:
                self.log_update_complete(update_id, {}, 'FAILED', str(e))
            print(f"STATUS: Failed: {e}", flush=True)
            return {'added': 0, 'updated': 0}

    def transform_entity(self, data):
        """Transform FtM JSON to DB schema"""
        props = data.get('properties', {})
        
        # Primary name
        names = props.get('name', [])
        full_name = names[0] if names else "Unknown"
        
        # Aliases
        aliases = names[1:] if len(names) > 1 else []
        aliases.extend(props.get('alias', []))
        aliases.extend(props.get('previousName', []))
        
        # Entity type mapping
        schema = data.get('schema')
        e_type = 'INDIVIDUAL' if schema == 'Person' else 'ORGANIZATION'
        
        # Date of birth
        dob_list = props.get('birthDate', [])
        dob = dob_list[0] if dob_list else None
        
        # Countries
        countries = props.get('country', [])
        countries.extend(props.get('jurisdiction', []))
        
        return {
            'full_name': full_name,
            'original_name': full_name,
            'aliases': list(set(aliases)),
            'entity_type': e_type,
            'list_type': 'WATCHLIST',
            'dataset': self.dataset_key,
            'topics': props.get('topics', []),
            'date_of_birth': dob,
            'place_of_birth': props.get('birthPlace', [None])[0],
            'gender': props.get('gender', [None])[0],
            'countries': list(set(countries)),
            'nationality': props.get('nationality', [None])[0],
            'passport_numbers': props.get('passportNumber', []),
            'national_id_numbers': props.get('idNumber', []),
            'addresses': props.get('address', []),
            'source_id': data.get('id'),
            'source_url': f"https://www.opensanctions.org/entities/{data.get('id')}/",
            'risk_level': 'HIGH',
            'properties': props,
            'data_source_origin': data.get('datasets', [])
        }

    def save_batch(self, entities):
        """Actually save to DB using base class logic"""
        if not self.db_conn:
            logger.warning("No DB connection, skipping save.")
            return {'added': 0, 'updated': 0}
            
        transformed = [self.transform_entity(e) for e in entities]
        return self.import_entities(transformed)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=1000, help='Max records (default 1000)')
    parser.add_argument('--no-limit', action='store_true', help='Download all records')
    parser.add_argument('--source', help='Specific source to run')
    args = parser.parse_args()
    
    limit = None if args.no_limit else args.limit
    
    logger.info("Starting OpenSanctions Sync...")
    logger.info(f"Config: Limit={limit}, Source={args.source or 'ALL'}")
    
    db_conn = None
    try:
        # Database connection
        try:
            db_conn = get_db_connection()
            logger.info(f"  Database connection ({DB_CONFIG['type']}) established.")
        except Exception as e:
            logger.error(f"  Failed to connect to database: {e}")
            return
        
        sources_to_run = []
        if args.source:
            if args.source.lower() == 'all':
                sources_to_run = list(OPENSANCTIONS_DATASETS.keys())
            elif args.source in OPENSANCTIONS_DATASETS:
                sources_to_run = [args.source]
            elif args.source == 'opensanctions': # Mapping 'opensanctions' name to 'sanctions' key
                sources_to_run = ['sanctions']
            elif args.source == 'opensanctions_pep':
                sources_to_run = ['pep']
        else:
            sources_to_run = ['pep'] # Default to pep

        total = {'added': 0, 'updated': 0}
        
        for key in sources_to_run:
            if key not in OPENSANCTIONS_DATASETS: 
                logger.warning(f"  Source key '{key}' not found in configuration.")
                continue
            
            scraper = OpenSanctionsScraper(db_conn, key, limit)
            stats = scraper.scrape()
            total['added'] += stats.get('added', 0)
            total['updated'] += stats.get('updated', 0)
            
        logger.info(f"ALL DONE. Total Added: {total['added']}, Updated: {total['updated']}")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        if db_conn:
            db_conn.close()

if __name__ == "__main__":
    main()
