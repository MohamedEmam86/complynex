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
Unified Sanctions File Importer
Parses and imports 5 sanctions list formats:
  - UN Security Council Consolidated List (XML)
  - OFAC SDN Enhanced List (XML)
  - EU Consolidated Sanctions List (XML)
  - HMT/UK Sanctions List (XML)
  - EMLCU Egyptian List (Excel)

Each parser returns a list of entity dicts.
import_sanctions_file() orchestrates the full pipeline.
"""

import os
import sys
import json
import logging
import hashlib
import sqlite3
from datetime import date, datetime
import openpyxl
from lxml import etree as ET
from io import BytesIO

# Add parent dir to path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# DB Support
try:
    import psycopg
    from psycopg.rows import dict_row
    PG_AVAILABLE = True
except ImportError:
    try:
        import psycopg2 as psycopg
        from psycopg2.extras import RealDictCursor
        PG_AVAILABLE = True
    except ImportError:
        PG_AVAILABLE = False

try:
    import jellyfish
    HAS_JELLYFISH = True
except ImportError:
    HAS_JELLYFISH = False

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
except ImportError:
    pass

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'complynex_cms.db')

# Single source of truth for Postgres connection params — same dict the live
# app uses (config.Config.POSTGRES_CONFIG), so this can't drift from the app's
# actual DB again. Requires BASE_DIR on sys.path (see import below).
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from config import Config
DB_CONFIG = dict(Config.POSTGRES_CONFIG)

# Check if we should use Postgres
USE_POSTGRES = PG_AVAILABLE and os.getenv('DB_TYPE') == 'postgresql'

# Valid source keys mapping to DB source identifier
VALID_SOURCES = {
    'un': {
        'label': 'UN Security Council Sanctions',
        'db_source': 'un', # Matches screening_data_sources.name
        'accept': '.xml',
    },
    'ofac': {
        'label': 'OFAC SDN Enhanced List',
        'db_source': 'ofac',
        'accept': '.xml',
    },
    'eu': {
        'label': 'EU Consolidated Sanctions',
        'db_source': 'eu',
        'accept': '.xml',
    },
    'hmt': {
        'label': 'UK/HMT Sanctions List',
        'db_source': 'hmt',
        'accept': '.xml',
    },
    'emlcu': {
        'label': 'EMLCU Egyptian List',
        'db_source': 'emlcu',
        'accept': '.xlsx',
    },
    'opensanctions': {
        'label': 'OpenSanctions PEPs',
        'db_source': 'opensanctions',
        'accept': '.json',
    }
}


def _gen_source_id(prefix, name, extra=''):
    """Generate deterministic source_id from name"""
    raw = f"{prefix}_{name}_{extra}".strip('_')
    h = hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]
    return f"{prefix}_{h}"


def _safe_parse_xml(filepath):
    """Parse XML with encoding fallback for malformed files."""
    # Try standard parse first
    try:
        tree = ET.parse(filepath)
        return tree.getroot()
    except ET.ParseError:
        pass
    
    # Fallback: read as bytes, strip bad chars, try again
    logger.warning(f"XML parse failed, trying encoding fallback for {filepath}")
    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
        # Try decoding with different encodings
        for enc in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
            try:
                text = raw.decode(enc, errors='replace')
                # Remove control characters except tabs/newlines
                import re as _re
                text = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
                root = ET.fromstring(text.encode('utf-8'))
                logger.info(f"  XML parsed successfully using {enc} encoding")
                return root
            except ET.ParseError:
                continue
    except Exception as e:
        logger.error(f"All XML parse attempts failed: {e}")
    
    raise ET.ParseError(f"Cannot parse XML file: {filepath}. The file may be corrupted or not valid XML.")


def parse_un_xml(filepath):
    logger.info(f"Parsing UN XML (Iterative): {filepath}")
    entities = []
    
    # Use iterparse to handle potentially large files with constant memory
    try:
        context = ET.iterparse(filepath, events=('end',), tag=('INDIVIDUAL', 'ENTITY'))
        
        for event, elem in context:
            try:
                if elem.tag == 'INDIVIDUAL':
                    first = (elem.findtext('FIRST_NAME') or '').strip()
                    second = (elem.findtext('SECOND_NAME') or '').strip()
                    third = (elem.findtext('THIRD_NAME') or '').strip()
                    fourth = (elem.findtext('FOURTH_NAME') or '').strip()
                    name_parts = [p for p in [first, second, third, fourth] if p]
                    full_name = ' '.join(name_parts)
                    if not full_name or len(full_name) < 2: 
                        elem.clear()
                        continue
                    
                    dataid = (elem.findtext('DATAID') or '').strip()
                    un_list = (elem.findtext('UN_LIST_TYPE') or 'UNKNOWN').strip()
                    gender = (elem.findtext('GENDER') or '').strip()
                    listed_on = (elem.findtext('LISTED_ON') or '').strip()
                    comments = (elem.findtext('COMMENTS1') or '').strip()
                    
                    aliases = []
                    for alias_el in elem.iter('INDIVIDUAL_ALIAS'):
                        alias_name = (alias_el.findtext('ALIAS_NAME') or '').strip()
                        if alias_name: aliases.append(alias_name)
                        
                    dob, yob = None, None
                    for dob_el in elem.iter('INDIVIDUAL_DATE_OF_BIRTH'):
                        d = (dob_el.findtext('DATE') or '').strip()
                        y = (dob_el.findtext('YEAR') or '').strip()
                        if d: dob = d
                        if y:
                            try: yob = int(y)
                            except: pass
                    
                    pob = None
                    for pob_el in elem.iter('INDIVIDUAL_PLACE_OF_BIRTH'):
                        city = (pob_el.findtext('CITY') or '').strip()
                        country = (pob_el.findtext('COUNTRY') or '').strip()
                        if city or country: 
                            pob = ', '.join(filter(None, [city, country]))
                            break
                            
                    nationality = None
                    for nat in elem.iter('NATIONALITY'):
                        val = (nat.findtext('VALUE') or '').strip()
                        if val: nationality = val; break
                        
                    passport_numbers, national_id_numbers = [], []
                    for doc in elem.iter('INDIVIDUAL_DOCUMENT'):
                        doc_type = (doc.findtext('TYPE_OF_DOCUMENT') or '').upper()
                        doc_num = (doc.findtext('NUMBER') or '').strip()
                        if doc_num:
                            if 'PASSPORT' in doc_type: passport_numbers.append(doc_num)
                            else: national_id_numbers.append(doc_num)
                            
                    addresses = []
                    for addr in elem.iter('INDIVIDUAL_ADDRESS'):
                        country = (addr.findtext('COUNTRY') or '').strip()
                        if country: addresses.append(country)
                        
                    entities.append({
                        'full_name': full_name, 'original_name': full_name, 'aliases': aliases[:10],
                        'entity_type': 'PERSON', 'list_type': 'SANCTIONS', 'dataset': f'un_{un_list.lower()}',
                        'topics': ['sanctions', 'un', un_list.lower()], 'date_of_birth': dob, 'year_of_birth': yob,
                        'place_of_birth': pob, 'gender': gender.upper() if gender else None, 'nationality': nationality,
                        'passport_numbers': passport_numbers[:5], 'national_id_numbers': national_id_numbers[:5],
                        'countries': list(set(([nationality] if nationality else []) + addresses)),
                        'source_id': f'un_ind_{dataid}', 'source_url': 'https://www.un.org/securitycouncil/sanctions',
                        'risk_level': 'EXTREME', 
                        'properties': {
                            'un_list': un_list, 'dataid': dataid, 'listed_on': listed_on, 
                            'comments': comments[:500] if comments else None
                        }
                    })
                    
                elif elem.tag == 'ENTITY':
                    first = (elem.findtext('FIRST_NAME') or '').strip()
                    full_name = first
                    if not full_name or len(full_name) < 2: 
                        elem.clear()
                        continue
                    
                    dataid = (elem.findtext('DATAID') or '').strip()
                    un_list = (elem.findtext('UN_LIST_TYPE') or 'UNKNOWN').strip()
                    listed_on = (elem.findtext('LISTED_ON') or '').strip()
                    comments = (elem.findtext('COMMENTS1') or '').strip()
                    
                    aliases = []
                    for alias_el in elem.iter('ENTITY_ALIAS'):
                        alias_name = (alias_el.findtext('ALIAS_NAME') or '').strip()
                        if alias_name: aliases.append(alias_name)
                        
                    entities.append({
                        'full_name': full_name, 'original_name': full_name, 'aliases': aliases[:10],
                        'entity_type': 'ORGANIZATION', 'list_type': 'SANCTIONS', 'dataset': f'un_{un_list.lower()}',
                        'topics': ['sanctions', 'un', un_list.lower(), 'organization'], 'countries': [],
                        'source_id': f'un_ent_{dataid}', 'source_url': 'https://www.un.org/securitycouncil/sanctions',
                        'risk_level': 'EXTREME', 
                        'properties': {
                            'un_list': un_list, 'dataid': dataid, 'listed_on': listed_on, 
                            'comments': comments[:500] if comments else None
                        }
                    })
                
                # Memory management: clear the element and all previous neighbors
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
                    
            except Exception as e:
                logger.error(f"Error parsing UN record: {e}")
                elem.clear()
                continue
                
    except Exception as e:
        logger.error(f"UN iterative parse failed: {e}")
        # Fallback to safe parse if iterparse fails early
        try:
            root = _safe_parse_xml(filepath)
            # ... process legacy style if needed, but iterparse is preferred
        except: pass

    logger.info(f"  UN: parsed {len(entities)} entries")
    return entities

def parse_ofac_xml(filepath):
    logger.info(f"Parsing OFAC SDN Enhanced XML (Iterative): {filepath}")
    entities = []
    count = 0
    
    # OFAC XML formats vary. We support:
    # 1. Standard SDN.XML (uses 'sdnEntry')
    # 2. Enhanced/Alternative format (uses 'entity')
    try:
        # Determine namespace
        ns = ''
        target_tag = ''
        
        # Peek at first few tags to find out format
        for event, elem in ET.iterparse(filepath, events=('start',)):
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local in ('sdnEntry', 'entity', 'sdn_entry'):
                target_tag = elem.tag
                if '}' in elem.tag:
                    ns = elem.tag.split('}')[0] + '}'
                break
        
        if not target_tag:
            logger.error("  OFAC: Could not find 'sdnEntry' or 'entity' tag in XML. Parsing aborted.")
            return []
            
        logger.info(f"  OFAC: Detected '{target_tag}' format. Parsing...")
        context = ET.iterparse(filepath, events=('end',), tag=target_tag)
        ns_prefix = ns
        
        for event, elem in context:
            try:
                tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                
                if tag_local in ('sdnEntry', 'sdn_entry'):
                    # Handle Standard SDN.XML
                    uid = (elem.findtext(f"{ns_prefix}uid") or '').strip()
                    first = (elem.findtext(f"{ns_prefix}firstName") or '').strip()
                    last = (elem.findtext(f"{ns_prefix}lastName") or '').strip()
                    full_name = ' '.join(filter(None, [first, last]))
                    
                    if not full_name:
                        elem.clear()
                        continue
                        
                    sdn_type = (elem.findtext(f"{ns_prefix}sdnType") or '').strip().upper()
                    entity_type = 'PERSON' if 'INDIVIDUAL' in sdn_type else 'ORGANIZATION'
                    
                    # Programs
                    programs = []
                    prog_list = elem.find(f"{ns_prefix}programList")
                    if prog_list is not None:
                        for p in prog_list:
                            if p.text: programs.append(p.text.strip())
                    
                    # Aliases
                    aliases = []
                    aka_list = elem.find(f"{ns_prefix}akaList")
                    if aka_list is not None:
                        for aka in aka_list:
                            a_f = (aka.findtext(f"{ns_prefix}firstName") or '').strip()
                            a_l = (aka.findtext(f"{ns_prefix}lastName") or '').strip()
                            a_full = ' '.join(filter(None, [a_f, a_l]))
                            if a_full and a_full != full_name:
                                aliases.append(a_full)
                    
                    # ID numbers and Address Countries
                    address_countries = []
                    id_list = elem.find(f"{ns_prefix}idList")
                    passport_numbers, national_id_numbers = [], []
                    if id_list is not None:
                        for idx in id_list:
                            i_type = (idx.findtext(f"{ns_prefix}idType") or '').lower()
                            i_num = (idx.findtext(f"{ns_prefix}idNumber") or '').strip()
                            if i_num:
                                if 'passport' in i_type: passport_numbers.append(i_num)
                                else: national_id_numbers.append(i_num)
                    
                    addr_list = elem.find(f"{ns_prefix}addressList")
                    if addr_list is not None:
                        for addr in addr_list:
                            country = (addr.findtext(f"{ns_prefix}country") or '').strip()
                            if country: address_countries.append(country)

                    remarks = (elem.findtext(f"{ns_prefix}remarks") or '').strip()

                    entities.append({
                        'full_name': full_name, 'original_name': full_name, 'aliases': aliases[:15],
                        'entity_type': entity_type, 'list_type': 'SANCTIONS', 'dataset': 'ofac_sdn',
                        'topics': ['sanctions', 'ofac', 'us'] + [p.lower() for p in programs[:3]],
                        'countries': list(set(address_countries)),
                        'passport_numbers': passport_numbers[:5], 'national_id_numbers': national_id_numbers[:5],
                        'source_id': f'ofac_sdn_{uid}', 'source_url': 'https://www.treasury.gov/ofac/downloads/sdn.xml',
                        'risk_level': 'EXTREME', 'properties': {'uid': uid, 'programs': programs[:5]},
                        'details': remarks or None
                    })
                
                elif tag_local == 'entity':
                    # Handle Enhanced format (keeping existing logic)
                    gi = elem.find(f"{ns_prefix}generalInfo")
                    if gi is None: 
                        elem.clear()
                        continue
                    
                    identity_id = (gi.findtext(f"{ns_prefix}identityId") or '').strip()
                    entity_type_raw = (gi.findtext(f"{ns_prefix}entityType") or '').strip()
                    entity_type = 'PERSON' if entity_type_raw.lower() in ('individual',) else 'ORGANIZATION'
                    
                    names_el = elem.find(f"{ns_prefix}names")
                    primary_name, aliases = '', []
                    if names_el is not None:
                        for name_el in names_el:
                            is_primary = (name_el.findtext(f"{ns_prefix}isPrimary") or '').lower() == 'true'
                            translations = name_el.find(f"{ns_prefix}translations")
                            if translations is None: continue
                            for trans in translations:
                                formatted = (trans.findtext(f"{ns_prefix}formattedFullName") or '').strip()
                                if not formatted:
                                    first = (trans.findtext(f"{ns_prefix}formattedFirstName") or '').strip()
                                    last = (trans.findtext(f"{ns_prefix}formattedLastName") or '').strip()
                                    formatted = ' '.join(filter(None, [first, last]))
                                if not formatted or len(formatted) < 2: continue
                                
                                script = (trans.get('script') or trans.findtext(f"{ns_prefix}script") or '').strip()
                                if is_primary and (script == 'Latin' or not primary_name):
                                    primary_name = formatted
                                else:
                                    if formatted != primary_name and formatted not in aliases:
                                        aliases.append(formatted)
                    
                    if not primary_name or len(primary_name) < 2: 
                        elem.clear()
                        continue
                    
                    programs = []
                    progs_el = elem.find(f"{ns_prefix}sanctionsPrograms")
                    if progs_el is not None:
                        for prog in progs_el:
                            prog_name = (prog.findtext(f"{ns_prefix}name") or '').strip()
                            if prog_name: programs.append(prog_name)
                    
                    address_countries = []
                    addrs_el = elem.find(f"{ns_prefix}addresses")
                    if addrs_el is not None:
                        for addr in addrs_el:
                            country = (addr.findtext(f"{ns_prefix}country") or '').strip()
                            if country: address_countries.append(country)
                            
                    dob, yob, nationality, gender = None, None, None, None
                    passport_numbers, national_id_numbers = [], []
                    features_el = elem.find(f"{ns_prefix}features")
                    if features_el is not None:
                        for feat in features_el:
                            feat_type = (feat.findtext(f"{ns_prefix}featureType") or '').strip().upper()
                            feat_val = (feat.findtext(f"{ns_prefix}value") or '').strip()
                            if 'DATE OF BIRTH' in feat_type and feat_val: dob = feat_val
                            elif 'NATIONALITY' in feat_type and feat_val: nationality = feat_val
                            elif 'GENDER' in feat_type and feat_val: gender = feat_val.upper()
                            elif 'PASSPORT' in feat_type and feat_val: passport_numbers.append(feat_val)
                            elif 'IDENTIFICATION' in feat_type and feat_val: national_id_numbers.append(feat_val)
                            
                    entities.append({
                        'full_name': primary_name, 'original_name': primary_name, 'aliases': aliases[:10],
                        'entity_type': entity_type, 'list_type': 'SANCTIONS', 'dataset': 'ofac_sdn',
                        'topics': ['sanctions', 'ofac', 'us'] + [p.lower() for p in programs[:3]],
                        'date_of_birth': dob, 'year_of_birth': yob, 'gender': gender, 'nationality': nationality,
                        'passport_numbers': passport_numbers[:5], 'national_id_numbers': national_id_numbers[:5],
                        'countries': list(set(address_countries + ([nationality] if nationality else []))),
                        'source_id': f'ofac_sdn_{identity_id}', 'source_url': 'https://sanctionslistservice.ofac.treas.gov/',
                        'risk_level': 'EXTREME', 'properties': {'identity_id': identity_id, 'programs': programs[:5]}
                    })
                    count += 1
                    if count % 5000 == 0: logger.info(f"  OFAC: ...parsed {count:,} entries")
                    
                    elem.clear()
                    while elem.getprevious() is not None:
                        del elem.getparent()[0]
                    
            except Exception as e:
                logger.error(f"Error parsing OFAC entity: {e}")
                elem.clear()
                continue
                
    except Exception as e:
        logger.error(f"OFAC iterative parse failed: {e}")

    logger.info(f"  OFAC: parsed {len(entities)} entries total")
    return entities

def parse_eu_xml(filepath):
    logger.info(f"Parsing EU Sanctions XML (Iterative): {filepath}")
    entities, count = [], 0
    
    try:
        # Determine namespace
        ns = ''
        for event, elem in ET.iterparse(filepath, events=('start',)):
            if '}' in elem.tag:
                ns = elem.tag.split('}')[0] + '}'
            break
        
        ns_prefix = str(ns)
        context = ET.iterparse(filepath, events=('end',), tag=f"{ns_prefix}sanctionEntity")
        
        for event, elem in context:
            try:
                logical_id = elem.get('logicalId', '')
                subject_el = elem.find(f"{ns_prefix}subjectType")
                subject_code = (subject_el.get('code') or '').lower() if subject_el is not None else ''
                entity_type = 'PERSON' if 'person' in subject_code else 'ORGANIZATION'
                
                primary_name, aliases = '', []
                for na in elem.iter(f"{ns_prefix}nameAlias"):
                    whole = (na.get('wholeName') or '').strip()
                    is_strong = (na.get('strong') or '').lower() == 'true'
                    if not whole or len(whole) < 2: continue
                    if not primary_name and is_strong:
                        primary_name = whole
                    elif whole != primary_name:
                        aliases.append(whole)
                
                if not primary_name:
                    if aliases: primary_name = aliases.pop(0)
                    else: 
                        elem.clear()
                        continue
                    
                programme = ''
                reg_el = elem.find(f"{ns_prefix}regulation")
                if reg_el is not None:
                    programme = (reg_el.get('programme') or '').strip()
                    
                dob, yob, pob = None, None, None
                for bd in elem.iter(f"{ns_prefix}birthdate"):
                    bd_str = (bd.get('birthdate') or '').strip()
                    yr = (bd.get('year') or '').strip()
                    city = (bd.get('city') or '').strip()
                    country_desc = (bd.get('countryDescription') or '').strip()
                    if bd_str: dob = bd_str
                    if yr:
                        try: yob = int(yr)
                        except: pass
                    if city or country_desc:
                        pob = ', '.join(filter(None, [city, country_desc]))
                        
                nationality, countries = None, []
                for cit in elem.iter(f"{ns_prefix}citizenship"):
                    country_desc = (cit.get('countryDescription') or '').strip()
                    if country_desc:
                        nationality = country_desc
                        countries.append(country_desc)
                        break
                        
                passport_numbers, national_id_numbers = [], []
                for ident in elem.iter(f"{ns_prefix}identification"):
                    number = (ident.get('number') or '').strip()
                    desc = (ident.get('identificationTypeDescription') or '').lower()
                    if number:
                        if 'passport' in desc: passport_numbers.append(number)
                        else: national_id_numbers.append(number)
                        
                for addr in elem.iter(f"{ns_prefix}address"):
                    country_desc = (addr.get('countryDescription') or '').strip()
                    if country_desc and country_desc not in countries:
                        countries.append(country_desc)
                        
                gender = None
                for g in elem.iter(f"{ns_prefix}gender"):
                    gv = (g.get('gender') or g.text or '').strip()
                    if gv: gender = gv.upper(); break

                # <remark> holds real identifying context (e.g. "Saddam's second
                # son", "UNSC RESOLUTION 1483") — a nameAlias's `function`
                # attribute sometimes carries a useful role description too, so
                # combine both when present.
                remark = ''
                remark_el = elem.find(f"{ns_prefix}remark")
                if remark_el is not None and remark_el.text:
                    remark = remark_el.text.strip()
                function_text = ''
                for na in elem.iter(f"{ns_prefix}nameAlias"):
                    fn = (na.get('function') or '').strip()
                    if fn:
                        function_text = fn
                        break
                bio_parts = [p for p in (remark, function_text) if p]

                entities.append({
                    'full_name': primary_name, 'original_name': primary_name, 'aliases': aliases[:10],
                    'entity_type': entity_type, 'list_type': 'SANCTIONS', 'dataset': 'eu_sanctions',
                    'topics': ['sanctions', 'eu'] + ([programme.lower()] if programme else []),
                    'date_of_birth': dob, 'year_of_birth': yob, 'place_of_birth': pob, 'gender': gender,
                    'nationality': nationality, 'passport_numbers': passport_numbers[:5],
                    'national_id_numbers': national_id_numbers[:5],
                    'countries': list(set(countries)), 'source_id': f'eu_{logical_id}',
                    'source_url': 'https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions',
                    'risk_level': 'HIGH', 'properties': {'logical_id': logical_id, 'programme': programme},
                    'details': ' — '.join(bio_parts) if bio_parts else None
                })
                count += 1
                if count % 5000 == 0: logger.info(f"  EU: ...parsed {count:,} entries")
                
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
                    
            except Exception as e:
                logger.error(f"Error parsing EU entity: {e}")
                elem.clear()
                continue
                
    except Exception as e:
        logger.error(f"EU iterative parse failed: {e}")

    logger.info(f"  EU: parsed {len(entities)} entries total")
    return entities

def parse_hmt_xml(filepath):
    logger.info(f"Parsing UK/HMT Sanctions XML (Iterative): {filepath}")
    entities, count = [], 0
    
    try:
        # Determine namespace
        ns = ''
        for event, elem in ET.iterparse(filepath, events=('start',)):
            if '}' in elem.tag:
                ns = elem.tag.split('}')[0] + '}'
            break
        
        ns_prefix = str(ns)
        context = ET.iterparse(filepath, events=('end',), tag=f"{ns_prefix}Designation")
        
        for event, elem in context:
            try:
                unique_id = (elem.findtext(f"{ns_prefix}UniqueID") or '').strip()
                last_updated = (elem.findtext(f"{ns_prefix}LastUpdated") or '').strip()
                regime = (elem.findtext(f"{ns_prefix}Regime") or '').strip()
                if not regime:
                    for reg in elem.iter(f"{ns_prefix}RegimeName"):
                        regime = (reg.text or '').strip()
                        if regime: break
                        
                group_desc_el = elem.find(f"{ns_prefix}GroupTypeDescription")
                group_type = (group_desc_el.text if group_desc_el is not None else '').strip()
                entity_type = 'PERSON' if 'individual' in group_type.lower() else 'ORGANIZATION'
                
                primary_name, aliases = '', []
                names_el = elem.find(f"{ns_prefix}Names")
                if names_el is not None:
                    for name_el in names_el.iter(f"{ns_prefix}Name"):
                        name6 = (name_el.findtext(f"{ns_prefix}Name6") or '').strip()
                        name_type = (name_el.findtext(f"{ns_prefix}NameType") or '').strip()
                        if not name6:
                            parts = []
                            for i in range(1, 7):
                                part = (name_el.findtext(f"{ns_prefix}Name{i}") or '').strip()
                                if part: parts.append(part)
                            name6 = ' '.join(parts)
                        if not name6 or len(name6) < 2: continue
                        
                        if name_type.lower() == 'primary name' or not primary_name:
                            if not primary_name: primary_name = name6
                            elif name6 != primary_name: aliases.append(name6)
                        else:
                            if name6 != primary_name: aliases.append(name6)
                
                if not primary_name: 
                    elem.clear()
                    continue
                
                dob, yob, nationality = None, None, None
                for dob_el in elem.iter(f"{ns_prefix}IndividualDateOfBirth"):
                    d = (dob_el.text or '').strip()
                    if d: dob = d; break
                if not dob:
                    dob = (elem.findtext(f"{ns_prefix}DOB") or '').strip()
                    
                for nat in elem.iter(f"{ns_prefix}IndividualNationality"):
                    val = (nat.text or '').strip()
                    if val: nationality = val; break
                    
                passport_numbers = []
                for pp in elem.iter(f"{ns_prefix}IndividualPassport"):
                    pp_detail = (pp.findtext(f"{ns_prefix}PassportDetails") or pp.text or '').strip()
                    if pp_detail: passport_numbers.append(pp_detail)
                    
                countries = []
                for addr in elem.iter(f"{ns_prefix}Address"):
                    for child_tag in ['AddressCountry', 'Country']:
                        val = (addr.findtext(f"{ns_prefix}{child_tag}") or '').strip()
                        if val and val not in countries: countries.append(val)
                        
                if nationality and nationality not in countries:
                    countries.append(nationality)

                other_info = (elem.findtext(f"{ns_prefix}OtherInformation") or '').strip()
                if not other_info:
                    other_info = (elem.findtext(f"{ns_prefix}UKStatementofReasons") or '').strip()

                entities.append({
                    'full_name': primary_name, 'original_name': primary_name, 'aliases': aliases[:10],
                    'entity_type': entity_type, 'list_type': 'SANCTIONS', 'dataset': 'hmt_uk_sanctions',
                    'topics': ['sanctions', 'uk', 'hmt'] + ([regime.lower()] if regime else []),
                    'date_of_birth': dob, 'year_of_birth': yob, 'nationality': nationality,
                    'passport_numbers': passport_numbers[:5], 'national_id_numbers': [], 'countries': countries,
                    'source_id': f'hmt_{unique_id}', 'source_url': 'https://sanctionslist.fcdo.gov.uk/',
                    'risk_level': 'HIGH', 'properties': {'unique_id': unique_id, 'regime': regime, 'last_updated': last_updated},
                    'details': other_info or None
                })
                count += 1
                if count % 5000 == 0: logger.info(f"  HMT: ...parsed {count:,} entries")
                
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
                    
            except Exception as e:
                logger.error(f"Error parsing HMT entity: {e}")
                elem.clear()
                continue
                
    except Exception as e:
        logger.error(f"HMT iterative parse failed: {e}")

    logger.info(f"  HMT: parsed {len(entities)} entries total")
    return entities

def _normalize_arabic_name(name):
    """Normalize Arabic name using engine-standard logic"""
    if not name: return None
    from screening.complynex_engine import normalize_arabic_text
    return normalize_arabic_text(name)

def _normalize_english_name(name):
    """Normalize English name using engine-standard logic"""
    if not name: return ""
    name = name.upper().strip()
    # Simple normalization: keep alnum and spaces
    import re
    name = re.sub(r'[^A-Z0-9\s]', ' ', name)
    return ' '.join(name.split())

def parse_emlcu_xlsx(filepath):
    if not HAS_OPENPYXL: raise ImportError("openpyxl is required. Install with: pip install openpyxl")
    logger.info(f"Parsing EMLCU Excel: {filepath}")
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    all_entities = []
    
    # Header keywords for mapping
    KEYWORDS = {
        'name': ['الاسم', 'اسم'],
        'alias': ['الشهرة', 'الاسم الحركي', 'اسم الشهرة'],
        'national_id': ['الرقم القومي', 'رقم البطاقة', 'القومي'],
        'passport': ['الجواز', 'رقم الجواز', 'سفر'],
        'nationality': ['الجنسية'],
        'case': ['القضية', 'رقم القضية', 'سنة']
    }

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        logger.info(f"  Reading sheet: {sheet_name}")
        
        # Detect column mapping by scanning first 10 rows
        mapping = {}
        header_row_idx = -1
        
        for row_idx, row in enumerate(ws.iter_rows(max_row=10, values_only=True), 1):
            if not row: continue
            matches = 0
            temp_mapping = {}
            for col_idx, cell in enumerate(row):
                if not cell or not isinstance(cell, str): continue
                cell_norm = cell.strip()
                for key, words in KEYWORDS.items():
                    if any(w in cell_norm for w in words) and key not in temp_mapping:
                        temp_mapping[key] = col_idx
                        matches += 1
            
            # If we found at least 'name' and one more field, or just 'name' in a likely spot
            if 'name' in temp_mapping:
                mapping = temp_mapping
                header_row_idx = row_idx
                break
        
        if not mapping:
            logger.warning(f"  Could not detect headers in sheet {sheet_name}. Using fallback indices.")
            # Fallback based on sheet name if possible
            if 'الإرهابيين' in sheet_name or 'الارهابيين' in sheet_name:
                mapping = {'name': 0, 'alias': 1, 'national_id': 2, 'passport': 3, 'nationality': 4, 'case': 5}
                header_row_idx = 1
            else:
                mapping = {'name': 1, 'case': 2} if 'الكيانات' in sheet_name or 'الاعتبارية' in sheet_name else {'name': 0}
                header_row_idx = 2
        
        logger.info(f"  Mapping for {sheet_name}: {mapping} (Header row: {header_row_idx})")
        
        # Process rows
        is_terrorists = 'الإرهابيين' in sheet_name or 'الارهابيين' in sheet_name
        is_entities = 'الكيانات' in sheet_name
        is_legal = 'الشخصيات' in sheet_name or 'الاعتبارية' in sheet_name
        
        empty_row_count = 0
        for row_idx, row in enumerate(ws.iter_rows(min_row=header_row_idx + 1, values_only=True), header_row_idx + 1):
            if not row or all(v is None for v in row):
                empty_row_count += 1
                if empty_row_count > 10: break
                continue
            
            empty_row_count = 0
            
            name_idx = mapping.get('name')
            if name_idx is None or name_idx >= len(row) or not row[name_idx]: continue
            
            name = _normalize_arabic_name(str(row[name_idx]))
            if not name or len(name) < 2: continue
            
            # Extract other fields
            alias_idx = mapping.get('alias')
            alias = _normalize_arabic_name(str(row[alias_idx])) if alias_idx is not None and alias_idx < len(row) and row[alias_idx] else None
            
            id_idx = mapping.get('national_id')
            national_id = str(row[id_idx]).strip() if id_idx is not None and id_idx < len(row) and row[id_idx] else None
            
            pp_idx = mapping.get('passport')
            passport = str(row[pp_idx]).strip() if pp_idx is not None and pp_idx < len(row) and row[pp_idx] else None
            
            nat_idx = mapping.get('nationality')
            nationality = str(row[nat_idx]).strip() if nat_idx is not None and nat_idx < len(row) and row[nat_idx] else None
            
            case_idx = mapping.get('case')
            case_number = str(row[case_idx]).strip() if case_idx is not None and case_idx < len(row) and row[case_idx] else None
            
            # Determine entity type and prefix
            e_type = 'PERSON'
            prefix = 'emlcu_person'
            topics = ['terrorism', 'egypt', 'local']
            
            if is_entities:
                e_type = 'ORGANIZATION'
                prefix = 'emlcu_entity'
                topics.append('organization')
            elif is_legal:
                e_type = 'ORGANIZATION'
                prefix = 'emlcu_legal'
                topics.append('legal_person')
            
            # Disambiguate same-name entries by ID digits (position-independent —
            # the sheet sometimes renders the same masked national ID with
            # visible digits at the start vs the end, e.g. '**********0979' vs
            # '0979**********' for the SAME person, so comparing raw strings
            # would wrongly treat one person as two). Without this, source_id
            # was name-only, silently merging distinct people who share a
            # common full name into a single watchlist row.
            id_digits = ''.join(c for c in (national_id or '') if c.isdigit())
            passport_digits = ''.join(c for c in (passport or '') if c.isdigit())
            disambiguator = id_digits or passport_digits or (case_number or '')

            all_entities.append({
                'full_name': name, 'original_name': name, 'aliases': [alias] if alias else [],
                'entity_type': e_type, 'list_type': 'SANCTIONS', 'dataset': 'emlcu_egypt',
                'topics': topics, 'countries': ['Egypt'], 'nationality': nationality or ('Egyptian' if e_type == 'PERSON' else None),
                'national_id_numbers': [national_id] if national_id and national_id != 'None' else [],
                'passport_numbers': [passport] if passport and passport != 'None' else [],
                'source_id': _gen_source_id(prefix, name, extra=disambiguator),
                'source_url': 'https://www.mlcu.org.eg', 'risk_level': 'EXTREME',
                'properties': {'case_number': case_number, 'sheet': sheet_name}
            })
    
    logger.info(f"  EMLCU: parsed {len(all_entities)} entries")
    # In read_only mode, we should close the workbook
    try: wb.close()
    except: pass
    return all_entities

# Helper functions
def _safe_date(date_str):
    """Parse various date formats into ISO string for SQLite"""
    if not date_str: return None
    s = str(date_str).strip()
    # Try common formats
    from datetime import datetime as dt_parse
    for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%Y/%m/%d', '%d.%m.%Y']:
        try:
            return dt_parse.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    # Try just year
    try:
        y = int(s[:4])
        if 1900 <= y <= 2100: return f"{y}-01-01"
    except: pass
    return None

def _safe_year(date_str):
    if not date_str: return None
    s = str(date_str).strip()
    # Try to extract 4-digit year
    import re
    match = re.search(r'(\d{4})', s)
    if match:
        year = int(match.group(1))
        if 1900 <= year <= 2100: return year
    return None

def import_to_database(entities, source_name, db_config=None, progress_callback=None):
    if not entities:
        return {'added': 0, 'updated': 0, 'total_processed': 0}

    logger.info(f"Importing {len(entities)} entities for {source_name} to {DB_PATH if not USE_POSTGRES else 'Postgres'}")
    
    if progress_callback:
        progress_callback('starting_import', {'total': len(entities), 'processed': 0})

    conn = None
    if USE_POSTGRES:
        config = db_config or DB_CONFIG
        conn = psycopg.connect(**config)
    else:
        conn = sqlite3.connect(DB_PATH)

    try:
        cursor = conn.cursor()
        
        # Placeholder style
        ph = '%s' if USE_POSTGRES else '?'

        # Get count before
        cursor.execute(f"SELECT COUNT(*) FROM screening_watchlist WHERE source = {ph}", (source_name,))
        before_count = cursor.fetchone()[0]

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        today_str = datetime.now().strftime('%Y-%m-%d')

        added_count = 0
        updated_count = 0

        # Process in batches to avoid memory issues
        batch_size = 500
        total_processed = 0
        
        for i in range(0, len(entities), batch_size):
            batch = entities[i:i+batch_size]
            records = []
            for entity in batch:
                name = entity.get('full_name', '')
                is_arabic = any('\u0600' <= c <= '\u06FF' for c in name)
                
                if is_arabic:
                    name_normalized = _normalize_arabic_name(name)
                else:
                    name_normalized = _normalize_english_name(name)
                
                name_upper = name_normalized.upper() if name_normalized else ''
                soundex, metaphone = None, None
                if HAS_JELLYFISH and name_upper and name_upper.isascii():
                    try: 
                        soundex = jellyfish.soundex(name_upper)
                        metaphone = jellyfish.metaphone(name_upper)
                    except: pass
                
                name_tokens = name_upper.split() if name_upper else []

                # 1-2 line bio/notability text, when the source has one (OFAC
                # remarks, EU remark, HMT OtherInformation, EMLCU case updates,
                # etc.) — wrapped as a JSON array to match the format already
                # used by the large pre-existing OpenSanctions/UN import, so
                # complynex_engine.py's extract_bio_snippet() handles both
                # uniformly.
                bio = entity.get('details')

                record = (
                    name,
                    entity.get('original_name'),
                    json.dumps(entity.get('aliases', [])),
                    entity.get('entity_type'),
                    entity.get('list_type'),
                    entity.get('dataset'),
                    json.dumps(entity.get('topics', [])),
                    _safe_date(entity.get('date_of_birth')),
                    entity.get('year_of_birth') or _safe_year(entity.get('date_of_birth')),
                    entity.get('place_of_birth'),
                    entity.get('gender'),
                    json.dumps(entity.get('countries', [])),
                    entity.get('nationality'),
                    json.dumps(entity.get('passport_numbers', [])),
                    json.dumps(entity.get('national_id_numbers', [])),
                    json.dumps(entity.get('addresses', {})) if entity.get('addresses') else None,
                    source_name,
                    entity.get('source_id'),
                    entity.get('source_url'),
                    today_str, today_str, now_str,  # first_seen, last_seen, last_updated
                    name_normalized, soundex, metaphone,
                    json.dumps(name_tokens),
                    entity.get('risk_level'),
                    json.dumps(entity.get('properties', {})),
                    json.dumps([bio]) if bio else None,
                    now_str, now_str, 1  # created_at, updated_at, is_active
                )
                records.append(record)

            # Upsert SQL
            sql = f"""INSERT INTO screening_watchlist (
                full_name, original_name, aliases, entity_type, list_type, dataset, topics,
                date_of_birth, year_of_birth, place_of_birth, gender, countries, nationality,
                passport_numbers, national_id_numbers, addresses,
                source, source_id, source_url, first_seen, last_seen, last_updated,
                name_normalized, name_soundex, name_metaphone, name_tokens,
                risk_level, properties, details, created_at, updated_at, is_active
            ) VALUES ({', '.join([ph]*32)})
            ON CONFLICT (source, source_id) DO UPDATE SET
                full_name = excluded.full_name,
                original_name = excluded.original_name,
                aliases = excluded.aliases,
                last_seen = excluded.last_seen,
                last_updated = excluded.last_updated,
                updated_at = excluded.updated_at,
                properties = excluded.properties,
                details = excluded.details"""
            
            cursor.executemany(sql, records)
            total_processed += len(records)
            
            if progress_callback:
                progress_callback('importing', {'processed': total_processed, 'total': len(entities)})
                
            logger.info(f"  Batch {i//batch_size + 1}: inserted/updated {len(records)} records")

        conn.commit()

        # Update screening_data_sources
        cursor.execute(f"""UPDATE screening_data_sources
            SET last_successful_update = {ph}, total_records = (
                SELECT COUNT(*) FROM screening_watchlist WHERE source = {ph}
            ), last_updated_by = 1
            WHERE source_name = {ph}""", (now_str, source_name, source_name))
        conn.commit()

        # Get count after
        cursor.execute(f"SELECT COUNT(*) FROM screening_watchlist WHERE source = {ph}", (source_name,))
        after_count = cursor.fetchone()[0]

        added_count = after_count - before_count
        updated_count = len(entities) - added_count
        if updated_count < 0: updated_count = 0

        stats = {'added': added_count, 'updated': updated_count, 'total_processed': len(entities)}
        logger.info(f"  DB import: source={source_name}, added={added_count}, updated={updated_count}, total={len(entities)}")
        return stats

    except Exception as e:
        conn.rollback()
        logger.error(f"Database import failed for {source_name}: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        conn.close()

def import_sanctions_file(filepath, source_key, db_config=None, progress_callback=None):
    if source_key not in VALID_SOURCES:
        raise ValueError(f"Unknown source: {source_key}")
    
    source_info = VALID_SOURCES[source_key]
    source_name = source_info['db_source']
    label = source_info['label']
    
    logger.info(f"Importing {label} from: {filepath}")
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    if progress_callback:
        progress_callback('parsing', {'message': f"Parsing {label}..."})

    if source_key == 'emlcu':
        entities = parse_emlcu_xlsx(filepath)
    elif source_key == 'un':
        entities = parse_un_xml(filepath)
    elif source_key == 'ofac':
        entities = parse_ofac_xml(filepath)
    elif source_key == 'eu':
        entities = parse_eu_xml(filepath)
    elif source_key == 'hmt':
        entities = parse_hmt_xml(filepath)
    else:
        raise ValueError(f"No parser for {source_key}")
        
    stats = import_to_database(entities, source_name, db_config, progress_callback)
    stats['source'] = source_name
    stats['label'] = label
    return stats

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('source', choices=list(VALID_SOURCES.keys()))
    parser.add_argument('filepath')
    args = parser.parse_args()
    import_sanctions_file(args.filepath, args.source)

if __name__ == "__main__":
    main()
