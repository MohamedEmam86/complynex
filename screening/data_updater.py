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
Data Updater for ComplyNex Screening
Fetches and updates sanctions lists from OpenSanctions.
Updated for Advanced AML Module with Arabic support.
"""

import os
import sys
import requests
import sqlite3
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
import json
import logging
import jellyfish
from datetime import datetime
import re
from .complynex_engine import normalize_arabic_text
from .emlcu_scraper_production import EMLCUScraperFixed

logger = logging.getLogger(__name__)

def _parse_ofac_xml(xml_content):
    """Parse OFAC SDN XML into normalized entity dicts."""
    from lxml import etree
    entities = []
    try:
        root = etree.fromstring(xml_content)
        ns = {'ofac': 'https://sanctionslistservice.ofac.treas.gov/api/publicationpreview/exports/'}
        # Try with namespace first, then without
        entries = root.findall('.//sdnEntry') or root.findall('.//{*}sdnEntry')
        for entry in entries:
            def g(tag):
                el = entry.find(tag) or entry.find(f'{{*}}{tag}')
                return el.text.strip() if el is not None and el.text else None
            
            first = g('firstName') or ''
            last = g('lastName') or ''
            name = f"{first} {last}".strip() if first or last else g('lastName')
            if not name:
                continue
            
            # Aliases
            aliases = []
            for aka in entry.findall('.//aka') or entry.findall('.//{*}aka'):
                fn = (aka.find('firstName') or aka.find('{*}firstName'))
                ln = (aka.find('lastName') or aka.find('{*}lastName'))
                fn_text = fn.text.strip() if fn is not None and fn.text else ''
                ln_text = ln.text.strip() if ln is not None and ln.text else ''
                alias = f"{fn_text} {ln_text}".strip()
                if alias:
                    aliases.append(alias)
            
            dob_el = entry.find('.//dateOfBirthItem/dateOfBirth') or entry.find('.//{*}dateOfBirth')
            nationality_el = entry.find('.//nationality/country') or entry.find('.//{*}country')
            uid = g('uid')
            
            entities.append({
                'name': name,
                'aliases': aliases,
                'dob': dob_el.text.strip() if dob_el is not None and dob_el.text else None,
                'nationality': nationality_el.text.strip() if nationality_el is not None and nationality_el.text else None,
                'entity_type': 'INDIVIDUAL' if g('sdnType') == 'Individual' else 'ENTITY',
                'source_id': f"ofac-{uid}",
                'list_type': 'SANCTIONS',
                'source_name': 'OFAC SDN',
                'source_url': f"https://sanctionslistservice.ofac.treas.gov/api/publicationpreview/exports/sdn.xml",
            })
    except Exception as e:
        logger.error(f"OFAC XML parse error: {e}")
    return entities

def _parse_un_xml(xml_content):
    """Parse UN Security Council consolidated list XML."""
    from lxml import etree
    entities = []
    try:
        root = etree.fromstring(xml_content)
        for individual in root.findall('.//INDIVIDUAL'):
            def g(tag):
                el = individual.find(tag)
                return el.text.strip() if el is not None and el.text else None
            
            first = g('FIRST_NAME') or ''
            second = g('SECOND_NAME') or ''
            third = g('THIRD_NAME') or ''
            fourth = g('FOURTH_NAME') or ''
            name = ' '.join(filter(None, [first, second, third, fourth])).strip()
            if not name:
                continue
            
            aliases = []
            for aka in individual.findall('.//ALIAS'):
                quality = aka.find('QUALITY')
                if quality is not None and quality.text:
                    alias_name = ' '.join(filter(None, [
                        (aka.find('ALIAS_NAME') or aka.find('FIRST_NAME') or type('', (), {'text': ''})()).text or ''
                    ])).strip()
                    if alias_name:
                        aliases.append(alias_name)
            
            dob_el = individual.find('.//DATE_OF_BIRTH/VALUE') or individual.find('DATE_OF_BIRTH')
            nationality_el = individual.find('.//NATIONALITY/VALUE')
            dataid = g('DATAID') or g('UN_LIST_TYPE')
            
            entities.append({
                'name': name,
                'aliases': aliases,
                'dob': dob_el.text.strip() if dob_el is not None and dob_el.text else None,
                'nationality': nationality_el.text.strip() if nationality_el is not None and nationality_el.text else None,
                'entity_type': 'INDIVIDUAL',
                'source_id': f"un-individual-{dataid}-{name[:30]}",
                'list_type': 'SANCTIONS',
                'source_name': 'UN Security Council',
                'source_url': 'https://scsanctions.un.org',
            })
        
        for entity in root.findall('.//ENTITY'):
            def g(tag):
                el = entity.find(tag)
                return el.text.strip() if el is not None and el.text else None
            name = g('FIRST_NAME') or g('ENTITY_NAME') or g('SECOND_NAME')
            if not name:
                continue
            dataid = g('DATAID')
            entities.append({
                'name': name,
                'aliases': [],
                'dob': None,
                'nationality': None,
                'entity_type': 'ENTITY',
                'source_id': f"un-entity-{dataid}-{name[:30]}",
                'list_type': 'SANCTIONS',
                'source_name': 'UN Security Council',
                'source_url': 'https://scsanctions.un.org',
            })
    except Exception as e:
        logger.error(f"UN XML parse error: {e}")
    return entities

def _parse_hmt_xml(xml_content):
    """Parse UK HMT sanctions list XML."""
    from lxml import etree
    entities = []
    try:
        root = etree.fromstring(xml_content)
        for entry in root.findall('.//{*}DesignatedPerson') or root.findall('.//DesignatedPerson'):
            def g(tag):
                el = entry.find(f'{{*}}{tag}') or entry.find(tag)
                return el.text.strip() if el is not None and el.text else None
            
            name6 = g('Name6') or ''
            name1 = g('Name1') or ''
            name = f"{name6} {name1}".strip() or g('GroupID')
            if not name:
                continue
            
            aliases = []
            for alias_el in entry.findall('.//{*}Alias') or entry.findall('.//Alias'):
                a = alias_el.text.strip() if alias_el.text else None
                if a:
                    aliases.append(a)
            
            uid = g('GroupID') or g('AliasID')
            dob = g('DateOfBirth')
            nationality = g('Nationality') or g('CountryOfBirth')
            regime = g('RegimeName') or 'UK Sanctions'
            
            entities.append({
                'name': name,
                'aliases': aliases,
                'dob': dob,
                'nationality': nationality,
                'entity_type': 'INDIVIDUAL' if g('IndividualEntityShip') == 'Individual' else 'ENTITY',
                'source_id': f"hmt-{uid}-{name[:30]}",
                'list_type': 'SANCTIONS',
                'source_name': regime,
                'source_url': 'https://sanctionslist.fcdo.gov.uk',
            })
    except Exception as e:
        logger.error(f"HMT XML parse error: {e}")
    return entities

class DataUpdater:
    """
    Production-ready Data Updater for ComplyNex Screening.
    Supports PostgreSQL and multiple data formats.
    """
    
    def __init__(self, db_config):
        self.db_config = db_config
        self.db_conn = None
        # Detect DB Type
        if isinstance(db_config, dict) and 'database' in db_config and len(db_config) == 1:
            self.db_type = 'sqlite'
            self.placeholder = '%s'
        elif isinstance(db_config, str):
             self.db_type = 'sqlite'
             self.db_config = {'database': db_config}
             self.placeholder = '%s'
        else:
            self.db_type = 'postgresql'
            self.placeholder = '%s'

    def connect_db(self):
        if self.db_type == 'sqlite':
            if not self.db_conn:
                self.db_conn = db_pool.checkout_connection()
                def dict_factory(cursor, row):
                    d = {}
                    for idx, col in enumerate(cursor.description):
                        d[col[0]] = row[idx]
                    return d
                self.db_conn.row_factory = dict_factory
        else:
            if not self.db_conn or (hasattr(self.db_conn, 'closed') and self.db_conn.closed):
                if psycopg2 is None:
                    raise ImportError("psycopg2 is required for PostgreSQL support")
                self.db_conn = psycopg2.connect(
                    **self.db_config,
                    cursor_factory=RealDictCursor
                )

    def is_arabic(self, text):
        if not text: return False
        arabic_pattern = re.compile(r'[\u0600-\u06FF]')
        return bool(arabic_pattern.search(text))

    def update_watchlist(self, source_id=None, user_id=1):
        """Update database from configured sources (default: all active)."""
        self.connect_db()
        cursor = self.db_conn.cursor()
        
        if source_id:
            cursor.execute(f"SELECT * FROM screening_data_sources WHERE id = {self.placeholder}", (source_id,))
            sources = cursor.fetchall()
        else:
            cursor.execute("SELECT * FROM screening_data_sources WHERE is_active = 1")
            sources = cursor.fetchall()
            
        if not sources:
            logger.warning("No active screening sources found.")
            return 0
            
        total_count = 0
        for source in sources:
            logger.info(f"Updating from source: {source['source_name']} ({source['source_type']})")
            
            try:
                if source['source_type'] in ['EMLCU_SCRAPER', 'EMLCU']:
                    # Auto-discover and download the current file (its filename
                    # changes with every EMLCU update), then parse+import via
                    # the same tested pipeline the manual-upload UI already
                    # uses (scripts/import_sanctions_file.py) — not this
                    # class's own scrape_list()/_download_direct(), which
                    # depends on a parse_emlcu_excel() function that doesn't
                    # exist anywhere in this codebase and would always crash.
                    scraper = EMLCUScraperFixed(db_conn=self.db_conn)
                    file_path = scraper.download_only()
                    if not file_path:
                        raise Exception("Failed to download EMLCU file")
                    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts')
                    if scripts_dir not in sys.path:
                        sys.path.append(scripts_dir)
                    from import_sanctions_file import import_sanctions_file
                    stats = import_sanctions_file(file_path, 'emlcu')
                    count = stats.get('added', 0) + stats.get('updated', 0)
                    logger.info(f"EMLCU Scraper completed: {count} records.")
                else:
                    url = source.get('source_url') or source.get('url')
                    if not url:
                        logger.warning(f"No URL for source {source['source_name']}")
                        continue

                    source_type = source.get('source_type', '').upper()
                    source_name = source.get('source_name', '').lower()

                    # Route to correct parser based on source type
                    if source_type in ['OFAC'] or 'ofac' in source_name:
                        logger.info(f"Using OFAC XML parser for {source['source_name']}")
                        r = requests.get(url, timeout=120, headers={'User-Agent': 'ComplyNex-CMS/2.0'})
                        r.raise_for_status()
                        entities = _parse_ofac_xml(r.content)
                        count = 0
                        for entity in entities:
                            if self._import_xml_entity(entity, self.db_conn):
                                count += 1
                            if count % 500 == 0:
                                self.db_conn.commit()
                        self.db_conn.commit()
                        logger.info(f"OFAC XML completed: {count} records.")

                    elif source_type in ['UN'] or 'un' in source_name:
                        logger.info(f"Using UN XML parser for {source['source_name']}")
                        r = requests.get(url, timeout=120, headers={'User-Agent': 'ComplyNex-CMS/2.0'})
                        r.raise_for_status()
                        entities = _parse_un_xml(r.content)
                        count = 0
                        for entity in entities:
                            if self._import_xml_entity(entity, self.db_conn):
                                count += 1
                            if count % 500 == 0:
                                self.db_conn.commit()
                        self.db_conn.commit()
                        logger.info(f"UN XML completed: {count} records.")

                    elif source_type in ['HMT'] or 'hmt' in source_name:
                        logger.info(f"Using HMT XML parser for {source['source_name']}")
                        r = requests.get(url, timeout=120, headers={'User-Agent': 'ComplyNex-CMS/2.0'})
                        r.raise_for_status()
                        entities = _parse_hmt_xml(r.content)
                        count = 0
                        for entity in entities:
                            if self._import_xml_entity(entity, self.db_conn):
                                count += 1
                            if count % 500 == 0:
                                self.db_conn.commit()
                        self.db_conn.commit()
                        logger.info(f"HMT XML completed: {count} records.")

                    else:
                        # FTM JSON (OpenSanctions)
                        with requests.get(url, stream=True, timeout=300) as r:
                            r.raise_for_status()
                            count = 0
                            for line in r.iter_lines():
                                if not line: continue
                                if self._process_ftjson_line(line, self.db_conn):
                                    count += 1
                                if count % 1000 == 0:
                                    self.db_conn.commit()
                        self.db_conn.commit()
                        logger.info(f"FTM JSON completed for {source['source_name']}: {count} records.")
                
                # Update source metadata
                cursor.execute(f"""
                    UPDATE screening_data_sources 
                    SET last_successful_update = CURRENT_TIMESTAMP, last_updated_by = {self.placeholder}
                    WHERE id = {self.placeholder}
                """, (user_id, source['id']))
                self.db_conn.commit()
                total_count += count
                
            except Exception as e:
                logger.error(f"Failed source {source['source_name']}: {e}")
                self.db_conn.rollback()
                
        cursor.close()
        return total_count

    def _import_xml_entity(self, entity, conn):
        """Import a normalized entity dict (from XML parsers) into watchlist."""
        try:
            name = entity.get('name', '').strip()
            if not name:
                return False

            name_ar = entity.get('name_ar', '')
            aliases = entity.get('aliases', [])
            aliases_str = json.dumps(aliases, ensure_ascii=False) if aliases else '[]'
            source_id = entity.get('source_id', '')
            list_type = entity.get('list_type', 'SANCTIONS')
            entity_type = entity.get('entity_type', 'INDIVIDUAL')
            dob = entity.get('dob')
            nationality = entity.get('nationality')
            source_name = entity.get('source_name', '')
            source_url = entity.get('source_url', '')

            # Normalize Arabic if present
            if name_ar:
                try:
                    name_ar = normalize_arabic_text(name_ar)
                except Exception:
                    pass

            p = self.placeholder
            cursor = conn.cursor()

            # Upsert — insert or update if source_id exists
            cursor.execute(f"""
                INSERT INTO screening_watchlist 
                    (full_name, full_name_arabic, aliases, list_type, entity_type, 
                     date_of_birth, nationality, source_id, source, source_url, 
                     is_active, created_at, updated_at)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                ON CONFLICT(source_id) DO UPDATE SET
                    full_name=excluded.full_name,
                    full_name_arabic=excluded.full_name_arabic,
                    aliases=excluded.aliases,
                    nationality=excluded.nationality,
                    updated_at=CURRENT_TIMESTAMP
            """, (name, name_ar, aliases_str, list_type, entity_type,
                  dob, nationality, source_id, source, source_url))
            return True
        except Exception as e:
            logger.warning(f"XML entity import error: {e}")
            return False

    def _process_ftjson_line(self, line, conn):
        """Process a single FTJSON entity line and import it."""
        try:
            entity = json.loads(line)
            schema = entity.get('schema')
            if schema not in ['Person', 'Organization', 'Company', 'LegalEntity', 'Vessel', 'Airplane']:
                return False
                
            props = entity.get('properties', {})
            all_names = props.get('name', []) + props.get('alias', []) + props.get('previousName', [])
            
            names_en = []
            names_ar = []
            for n in all_names:
                if self.is_arabic(n):
                    names_ar.append(n)
                else:
                    names_en.append(n)
            
            primary_name = names_en[0] if names_en else (names_ar[0] if names_ar else None)
            if not primary_name: return False
            
            primary_name_ar = names_ar[0] if names_ar else None
            country = props.get('country', [])
            topics = props.get('topics', [])
            dob_list = props.get('birthDate', [])
            dob = dob_list[0] if dob_list else None
            
            nationality_list = props.get('nationality', [])
            nationality = nationality_list[0] if nationality_list else None
            
            gender_list = props.get('gender', [])
            gender = gender_list[0] if gender_list else None
            
            source_url = entity.get('referents', [None])[0] or f"https://www.opensanctions.org/entities/{entity.get('id')}/"
            datasets = entity.get('datasets', [])
            dataset = datasets[0] if datasets else 'unknown'
            
            # Determine Entity Type
            entity_type = 'ENTITY'
            if schema == 'Person':
                entity_type = 'INDIVIDUAL'
            
            # Extract additional bio/context
            bio_parts = []
            if props.get('notes'): bio_parts.append(f"Notes: {'; '.join(props.get('notes', []))}")
            if props.get('program'): bio_parts.append(f"Program: {'; '.join(props.get('program', []))}")
            if props.get('reason'): bio_parts.append(f"Reason: {'; '.join(props.get('reason', []))}")
            if props.get('status'): bio_parts.append(f"Status: {'; '.join(props.get('status', []))}")
            if props.get('position'): bio_parts.append(f"Position: {'; '.join(props.get('position', []))}")
            
            # Map to standard format
            mapped_entity = {
                'source_id': entity.get('id'),
                'full_name': primary_name,
                'original_name': primary_name_ar,
                'list_type': schema,
                'entity_type': entity_type,
                'dataset': dataset,
                'source': dataset,
                'source_url': source_url,
                'risk_level': 'HIGH' if any(t in topics for t in ['sanction', 'pep', 'crime']) else 'MEDIUM',
                'topics': json.dumps(topics),
                'countries': json.dumps(country),
                'date_of_birth': dob,
                'nationality': nationality,
                'gender': gender,
                'aliases': json.dumps(names_en[1:] + names_ar[1:]),
                'details': " | ".join(bio_parts)
            }
            
            return self._import_mapped_entity(mapped_entity, conn)
        except Exception as e:
            logger.error(f"FTJSON parse error: {e}")
            return False

    def _import_mapped_entity(self, entity, conn):
        """Final DB import for a mapped entity (PostgreSQL)."""
        try:
            cursor = conn.cursor()
            
            name_norm = normalize_arabic_text(entity['full_name'])
            soundex = jellyfish.soundex(name_norm) if name_norm else None
            metaphone = jellyfish.metaphone(name_norm) if name_norm else None
            
            yob = None
            if entity.get('date_of_birth'):
                try:
                    yob = int(str(entity['date_of_birth'])[:4])
                except: pass

            if self.db_type == 'sqlite':
                cursor.execute("""
                    INSERT OR REPLACE INTO screening_watchlist (
                        source_id, full_name, original_name, name_normalized, name_soundex, name_metaphone,
                        dataset, list_type, entity_type, topics, countries, 
                        date_of_birth, year_of_birth, nationality, gender,
                        source_url, risk_level, aliases, details, is_active, last_updated
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                """, (
                    entity['source_id'], entity['full_name'], entity['original_name'], 
                    name_norm, soundex, metaphone,
                    entity['dataset'], entity['list_type'], entity['entity_type'], 
                    entity['topics'], entity.get('countries'), 
                    entity.get('date_of_birth'), yob, 
                    entity.get('nationality'), entity.get('gender'),
                    entity['source_url'], entity['risk_level'], entity.get('aliases'),
                    entity.get('details')
                ))
            else:
                cursor.execute("""
                    INSERT INTO screening_watchlist (
                        source_id, full_name, original_name, name_normalized, name_soundex, name_metaphone,
                        dataset, list_type, entity_type, topics, countries, 
                        date_of_birth, year_of_birth, nationality, gender,
                        source_url, risk_level, aliases, details, is_active, last_updated
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                    ON CONFLICT(source_id) DO UPDATE SET
                        full_name=EXCLUDED.full_name,
                        original_name=EXCLUDED.original_name,
                        name_normalized=EXCLUDED.name_normalized,
                        name_soundex=EXCLUDED.name_soundex,
                        name_metaphone=EXCLUDED.name_metaphone,
                        entity_type=EXCLUDED.entity_type,
                        topics=EXCLUDED.topics,
                        countries=EXCLUDED.countries,
                        date_of_birth=EXCLUDED.date_of_birth,
                        year_of_birth=EXCLUDED.year_of_birth,
                        nationality=EXCLUDED.nationality,
                        gender=EXCLUDED.gender,
                        aliases=EXCLUDED.aliases,
                        details=EXCLUDED.details,
                        risk_level=EXCLUDED.risk_level,
                        last_updated=CURRENT_TIMESTAMP
                """, (
                    entity['source_id'], entity['full_name'], entity['original_name'], 
                    name_norm, soundex, metaphone,
                    entity['dataset'], entity['list_type'], entity['entity_type'], 
                    entity['topics'], entity.get('countries'), 
                    entity.get('date_of_birth'), yob, 
                    entity.get('nationality'), entity.get('gender'),
                    entity['source_url'], entity['risk_level'], entity.get('aliases'),
                    entity.get('details')
                ))
            return True
        except Exception as e:
            logger.debug(f"Import error: {e}")
            return False
            
    def close(self):
        if self.db_conn:
            try:
                self.db_conn.close()
            except Exception as e:
                logger.debug(f"[SWALLOWED] db connection close (cleanup) failed: {e}")
            self.db_conn = None

if __name__ == "__main__":
    import os
    db = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex.db')
    updater = DataUpdater(db)
    updater.update_watchlist()
    updater.close()
