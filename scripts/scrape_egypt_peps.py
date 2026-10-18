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

import json
import csv
import logging
import requests
import sqlite3
import os
import re
from datetime import datetime, date
from collections import defaultdict
import pyarabic.araby as araby

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
        print("psycopg (v3) or psycopg2 not found, PostgreSQL support disabled.")

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, '.env')
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
DB_PATH = os.path.join(INSTANCE_DIR, 'complynex.sqlite')

OPENSANCTIONS_URL = "https://data.opensanctions.org/datasets/latest/default/entities.ftm.json"
WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
DATA_DIR = os.path.join(BASE_DIR, 'data')

# Load .env manually to avoid dependency
DB_CONFIG = {}
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                DB_CONFIG[k] = v

# Determine DB connection
USE_POSTGRES = PG_AVAILABLE and 'DB_NAME' in DB_CONFIG and 'DB_USER' in DB_CONFIG

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# PEP Classification Definitions
PEP_LEVELS = {
    'PEP-1': ['president', 'prime minister', 'minister', 'ambassador', 'governor', 'head of state', 'chief of staff', 'army general'],
    'PEP-2': ['member of parliament', 'senator', 'judge', 'deputy minister', 'mayor', 'senior official'],
    'PEP-3': ['spouse', 'child', 'parent', 'sibling', 'associate'],
    'PEP-4': ['advisor', 'assistant', 'local official', 'party member']
}

def normalize_arabic_text(text):
    """
    Standard normalization for Arabic text
    """
    if not text:
        return ""
    
    # Strip diacritics
    text = araby.strip_tashkeel(text)
    
    # Normalize Alef variants
    text = re.sub(r'[أإآٱ]', 'ا', text)
    
    # Normalize Yeh/Maksura
    text = text.replace('ى', 'ي')
    
    # Normalize Teh Marbuta
    text = text.replace('ة', 'ه')
    
    # Remove Tatweel and extra spaces
    text = araby.strip_tatweel(text)
    text = ' '.join(text.split())
    
    return text.strip()

class EgyptPEPScraper:
    def __init__(self):
        self.peps = {} # Key: Normalized Name -> PEP Object
        self.stats = {
            'opensanctions_raw': 0,
            'wikidata_raw': 0,
            'total_unique': 0,
            'source_breakdown': defaultdict(int) 
        }

    def fetch_opensanctions(self, limit=None):
        """Fetch and filter OpenSanctions data for Egypt PEPs"""
        logger.info("Fetching OpenSanctions data...")
        count = 0
        try:
            with requests.get(OPENSANCTIONS_URL, stream=True) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        count += 1
                        if limit and count > limit:
                            logger.info(f"Reached limit of {limit} lines.")
                            break
                        
                        if count % 10000 == 0:
                            logger.info(f"Processed {count} lines...")
                            
                        try:
                            entity = json.loads(line)
                            properties = entity.get('properties', {})
                            countries = properties.get('country', [])
                            topics = properties.get('topics', [])
                            
                            is_egypt = 'eg' in countries or 'egypt' in [c.lower() for c in countries]
                            is_pep = 'role.pep' in topics or 'pep' in topics
                            
                            if is_egypt and is_pep:
                                self.stats['opensanctions_raw'] += 1
                                self._process_opensanctions_entity(entity)
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"Error fetching OpenSanctions: {e}")

    def _process_opensanctions_entity(self, entity):
        properties = entity.get('properties', {})
        name = properties.get('name', [''])[0]
        aliases = properties.get('alias', [])
        birth_date = properties.get('birthDate', [None])[0]
        positions = properties.get('position', [])
        role = properties.get('role', [None])[0]
        nationality = properties.get('nationality', ['Egypt'])[0]
        
        normalized_name = normalize_arabic_text(name)
        
        pep_record = {
            'pep_id': entity['id'],
            'name': name,
            'aliases': aliases,
            'birth_date': birth_date,
            'position': ', '.join(positions) if positions else role,
            'nationality': nationality,
            'source': 'OpenSanctions',
            'list_name': 'Egypt PEP Database - OpenSanctions',
            'dataset': 'opensanctions',
            'last_updated': datetime.now().strftime('%Y-%m-%d')
        }
        
        self._add_or_merge_pep(normalized_name, pep_record)

    def fetch_wikidata(self):
        """Fetch Wikidata regarding Egyptian politicians"""
        logger.info("Fetching Wikidata...")
        query = """
        SELECT ?item ?itemLabel ?dob ?positionLabel ?partyLabel
        WHERE {
          ?item wdt:P27 wd:Q79. # Nationality: Egypt
          { ?item wdt:P106 wd:Q82955. } UNION # Politician
          { ?item wdt:P106 wd:Q193391. } UNION # Diplomat
          { ?item wdt:P39 ?position. } # Holds position
          
          OPTIONAL { ?item wdt:P569 ?dob. }
          OPTIONAL { ?item wdt:P102 ?party. }
          
          SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en,ar". }
        }
        LIMIT 200
        """
        
        try:
            response = requests.get(WIKIDATA_SPARQL_ENDPOINT, params={'query': query, 'format': 'json'})
            response.raise_for_status()
            data = response.json()
            
            for item in data['results']['bindings']:
                self.stats['wikidata_raw'] += 1
                name = item['itemLabel']['value']
                dob = item.get('dob', {}).get('value', '').split('T')[0] if 'dob' in item else None
                position = item.get('positionLabel', {}).get('value', '')
                party = item.get('partyLabel', {}).get('value', '')
                
                normalized_name = normalize_arabic_text(name)
                
                pep_record = {
                    'pep_id': item['item']['value'],
                    'name': name,
                    'aliases': [],
                    'birth_date': dob,
                    'position': position,
                    'party': party,
                    'nationality': 'Egypt',
                    'source': 'Wikidata',
                    'list_name': 'Egypt PEP Database - Wikidata',
                    'dataset': 'wikidata',
                    'last_updated': datetime.now().strftime('%Y-%m-%d')
                }
                
                self._add_or_merge_pep(normalized_name, pep_record)
                
        except Exception as e:
            logger.error(f"Error fetching Wikidata: {e}")

    def _add_or_merge_pep(self, normalized_name, record):
        if normalized_name in self.peps:
            # Merge logic: Prefer longer name, combine aliases, keep earliest DOB
            existing = self.peps[normalized_name]
            existing['aliases'].extend(record['aliases'])
            existing['aliases'] = list(set(existing['aliases']))
            
            if not existing['birth_date'] and record['birth_date']:
                existing['birth_date'] = record['birth_date']
            
            if not existing['position'] and record['position']:
                existing['position'] = record['position']
                
            # Update source to reflect multi-source
            if record['source'] not in existing['source']:
                existing['source'] += f", {record['source']}"
                
            self.peps[normalized_name] = existing
        else:
            # Classification
            record['pep_classification'] = self._classify_pep(record['position'])
            self.peps[normalized_name] = record

    def _classify_pep(self, position):
        if not position:
            return 'PEP-4'
        
        pos_lower = position.lower()
        for level, keywords in PEP_LEVELS.items():
            for kw in keywords:
                if kw in pos_lower:
                    return level
        return 'PEP-4' # Default

    def save_data(self):
        """Save collected data to JSON/CSV (flat files)"""
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
            
        json_path = os.path.join(DATA_DIR, 'egypt_peps.json')
        csv_path = os.path.join(DATA_DIR, 'egypt_peps.csv')
        
        data_list = list(self.peps.values())
        self.stats['total_unique'] = len(data_list)
        
        # Save JSON
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data_list, f, ensure_ascii=False, indent=2)
            
        # Save CSV
        if data_list:
            keys = data_list[0].keys()
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(data_list)
                
        logger.info(f"Saved {len(data_list)} records to {json_path} and {csv_path}")

    def import_to_db(self):
        """Import unique PEPs to screening_watchlist"""
        logger.info("Importing to database...")
        
        if USE_POSTGRES:
            try:
                if PG_VERSION == 3:
                    # Connection info for psycopg v3
                    # It can take kwargs like dbname, user, etc.
                    conn = psycopg.connect(
                        dbname=DB_CONFIG.get('DB_NAME'),
                        user=DB_CONFIG.get('DB_USER'),
                        password=DB_CONFIG.get('DB_PASSWORD'),
                        host=DB_CONFIG.get('DB_HOST'),
                        port=DB_CONFIG.get('DB_PORT', 5432),
                        row_factory=dict_row
                    )
                else: # PG_VERSION == 2
                    conn = psycopg2.connect(
                        dbname=DB_CONFIG.get('DB_NAME'),
                        user=DB_CONFIG.get('DB_USER'),
                        password=DB_CONFIG.get('DB_PASSWORD'),
                        host=DB_CONFIG.get('DB_HOST'),
                        port=DB_CONFIG.get('DB_PORT', 5432)
                    )
                ph = '%s'
            except Exception as e:
                logger.error(f"PostgreSQL connection failed: {e}")
                return
        else:
            conn = sqlite3.connect(DB_PATH)
            ph = '?'
            
        cursor = conn.cursor()
        
        added = 0
        updated = 0
        
        for p in self.peps.values():
            normalized_name = normalize_arabic_text(p['name'])
            
            # Upsert logic
            cursor.execute(f"SELECT id FROM screening_watchlist WHERE name_normalized = {ph}", (normalized_name,))
            existing = cursor.fetchone()
            
            properties = json.dumps({
                'pep_classification': p['pep_classification'],
                'position': p['position'],
                'party': p.get('party'),
                'source_id': p['pep_id']
            })
            
            aliases_json = json.dumps(p['aliases'])
            
            if existing:
                query = f"""
                    UPDATE screening_watchlist 
                    SET full_name={ph}, date_of_birth={ph}, aliases={ph}, properties={ph}, source={ph}, list_type='PEP', updated_at=CURRENT_TIMESTAMP
                    WHERE id={ph}
                """
                # Handle different cursor types
                if USE_POSTGRES:
                    # psycopg3 (dict_row) or psycopg2 (RealDictCursor) both support 'id' key
                    eid = existing['id']
                else:
                    # sqlite3.Row or default tuple
                    try:
                        eid = existing['id']
                    except (TypeError, IndexError):
                        eid = existing[0]
            
                cursor.execute(query, (p['name'], p['birth_date'], aliases_json, properties, p['dataset'], eid))
                updated += 1
            else:
                query = f"""
                    INSERT INTO screening_watchlist 
                    (full_name, name_normalized, list_type, dataset, risk_level, entity_type, nationalities, date_of_birth, aliases, properties, source)
                    VALUES ({ph}, {ph}, 'PEP', {ph}, 'MEDIUM', 'INDIVIDUAL', {ph}, {ph}, {ph}, {ph}, {ph})
                """
                cursor.execute(query, (
                    p['name'], 
                    normalized_name, 
                    p['list_name'],
                    p['nationality'],
                    p['birth_date'],
                    aliases_json,
                    properties,
                    p['dataset']  # source
                ))
                added += 1
                
        conn.commit()

        # Update screening_data_sources for visibility in UI
        try:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(f"""
                UPDATE screening_data_sources
                SET last_successful_update = {ph}, 
                    total_records = (SELECT COUNT(*) FROM screening_watchlist WHERE dataset = 'egypt_peps' OR dataset LIKE 'opensanctions' OR dataset LIKE 'wikidata'),
                    last_updated_by = 1
                WHERE source_name = 'egypt_pep_excel' OR source_name = 'pep'
            """, (now_str,))
            conn.commit()
        except Exception as e:
            logger.warning(f"Failed to update screening_data_sources: {e}")

        conn.close()
        logger.info(f"Database Import: Added {added}, Updated {updated}")

if __name__ == "__main__":
    print(f"Starting Egypt PEP Scraper... (DB: {'PostgreSQL' if USE_POSTGRES else 'SQLite'})")
    scraper = EgyptPEPScraper()
    scraper.fetch_opensanctions(limit=50000)
    scraper.fetch_wikidata()
    scraper.save_data()
    scraper.import_to_db()
    print("Scraping Completed.")
    print(f"Stats: {scraper.stats}")
