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
EMLCU (Egyptian Money Laundering & Terrorism Financing Unit) Scraper
=====================================================================

Fetches and parses the Egyptian local terrorist list published by EMLCU.
The list is published as an Excel file (XLSX) and updated monthly/bi-monthly.

URL Pattern: https://www.mlcu.org.eg/upload/uploadeditor/files/[path]/[filename with date].xlsx

Current URL (as of Jan 2026):
https://www.mlcu.org.eg/upload/uploadeditor/files/%D8%A7%D9%84%D9%82%D9%88%D8%A7%D8%A6%D9%85%20%D8%A7%D9%84%D9%85%D8%AD%D9%84%D9%8A%D8%A9/%D9%82%D8%A7%D8%A6%D9%85%D8%A9%20%D8%A5%D8%AF%D8%B1%D8%A7%D8%AC%20%D8%A7%D9%84%D9%83%D9%8A%D8%A7%D9%86%D8%A7%D8%AA%20%D8%A7%D9%84%D8%A5%D8%B1%D9%87%D8%A7%D8%A8%D9%8A%D8%A9%20%D9%88%D8%A7%D9%84%D8%A5%D8%B1%D9%87%D8%A7%D8%A8%D9%8A%D9%8A%D9%86%206%20%D9%8A%D9%86%D8%A7%D9%8A%D8%B1%202026.xlsx
"""

import requests
import logging
from datetime import datetime
import re
import io
import hashlib

logger = logging.getLogger(__name__)

try:
    import openpyxl
except ImportError:
    openpyxl = None
    logger.warning("openpyxl not installed. EMLCU scraper will not work. Install: pip install openpyxl")

try:
    from openpyxl import load_workbook
except ImportError:
    pass


class EMLCUScraper:
    """
    Scraper for Egyptian Money Laundering & Terrorism Financing Unit (EMLCU) terrorist list.
    """
    
    # Default URL (will be overridden by database config)
    DEFAULT_URL = "https://www.mlcu.org.eg/upload/uploadeditor/files/%D8%A7%D9%84%D9%82%D9%88%D8%A7%D8%A6%D9%85%20%D8%A7%D9%84%D9%85%D8%AD%D9%84%D9%8A%D8%A9/%D9%82%D8%A7%D8%A6%D9%85%D8%A9%20%D8%A5%D8%AF%D8%B1%D8%A7%D8%AC%20%D8%A7%D9%84%D9%83%D9%8A%D8%A7%D9%86%D8%A7%D8%AA%20%D8%A7%D9%84%D8%A5%D8%B1%D9%87%D8%A7%D8%A8%D9%8A%D8%A9%20%D9%88%D8%A7%D9%84%D8%A5%D8%B1%D9%87%D8%A7%D8%A8%D9%8A%D9%8A%D9%86%206%20%D9%8A%D9%86%D8%A7%D9%8A%D8%B1%202026.xlsx"
    
    def __init__(self, url=None):
        """
        Initialize EMLCU scraper.
        
        Args:
            url: Custom URL for EMLCU list (uses DEFAULT_URL if not provided)
        """
        if openpyxl is None:
            raise ImportError("openpyxl is required for EMLCU scraper. Install: pip install openpyxl")
            
        self.url = url or self.DEFAULT_URL
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,application/octet-stream,*/*',
            'Accept-Language': 'ar,en-US;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Referer': 'https://www.mlcu.org.eg/',
            'Cache-Control': 'no-cache'
        })
        
    def scrape_list(self):
        """
        Download and parse the EMLCU terrorist list.
        Uses caching to avoid redundant downloads and provides fallback to local file.
        
        Returns:
            List of standardized entity dictionaries
        """
        import os
        import json
        import time
        
        # Cache configuration
        CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'cache')
        CACHE_FILE = os.path.join(CACHE_DIR, 'emlcu_cache.xlsx')
        CACHE_META = os.path.join(CACHE_DIR, 'emlcu_metadata.json')
        CACHE_DURATION = 86400 * 3  # 3 days cache
        
        os.makedirs(CACHE_DIR, exist_ok=True)
        
        # Check cache first
        if os.path.exists(CACHE_FILE) and os.path.exists(CACHE_META):
            try:
                with open(CACHE_META, 'r') as f:
                    meta = json.load(f)
                
                if time.time() - meta.get('timestamp', 0) < CACHE_DURATION:
                    logger.info(f"Using cached EMLCU list from {time.ctime(meta['timestamp'])}")
                    return self._parse_local_file(CACHE_FILE)
            except Exception as e:
                logger.warning(f"Cache check failed: {e}")

        logger.info(f"Fetching EMLCU list from: {self.url}")
        
        try:
            # Download with retry logic
            max_retries = 3
            last_error = None
            response = None
            
            for attempt in range(max_retries):
                try:
                    logger.info(f"EMLCU download attempt {attempt + 1}/{max_retries}")
                    
                    # Try with SSL verification first
                    try:
                        response = self.session.get(self.url, timeout=90, verify=True)
                    except requests.exceptions.SSLError as ssl_error:
                        logger.warning(f"SSL verification failed: {ssl_error}")
                        logger.warning("Retrying without SSL verification (not recommended)")
                        response = self.session.get(self.url, timeout=90)
                    
                    response.raise_for_status()
                    
                    # Validate content
                    if len(response.content) < 1024:
                        raise ValueError(f"Downloaded file too small: {len(response.content)} bytes")
                    
                    logger.info(f"Successfully downloaded {len(response.content)} bytes")
                    break  # Success!
                    
                except Exception as e:
                    last_error = e
                    logger.warning(f"Attempt {attempt + 1} failed: {e}")
                    
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                        logger.info(f"Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"All {max_retries} attempts failed")
                        raise last_error
            
            # Save to cache
            with open(CACHE_FILE, 'wb') as f:
                f.write(response.content)
            
            # Update metadata
            with open(CACHE_META, 'w') as f:
                json.dump({
                    'timestamp': time.time(),
                    'url': self.url,
                    'size': len(response.content),
                    'hash': hashlib.md5(response.content).hexdigest()
                }, f)
            
            logger.info("Updated EMLCU cache file")
            
            return self._parse_local_file(CACHE_FILE)
            
        except Exception as e:
            logger.error(f"Failed to download EMLCU list: {e}")
            
            # Fallback to cache even if old
            if os.path.exists(CACHE_FILE):
                logger.warning("Falling back to stale local cache")
                try:
                    return self._parse_local_file(CACHE_FILE)
                except Exception as parse_err:
                    logger.error(f"Fallback parsing failed: {parse_err}")
                    raise e
            else:
                raise

    def _parse_local_file(self, file_path):
        """Parse entity list from a local Excel file"""
        try:
            workbook = load_workbook(file_path, read_only=True)
            sheet = workbook.active
            entities = self._parse_sheet(sheet)
            workbook.close()
            logger.info(f"Successfully parsed {len(entities)} entities from EMLCU list")
            return entities
        except Exception as e:
            logger.error(f"Error parsing local file {file_path}: {e}")
            raise
            
    def _parse_sheet(self, sheet):
        """
        Parse Excel sheet and extract entities.
        
        The EMLCU list typically has columns like:
        - Serial Number (م)
        - Name (Arabic) (الاسم)
        - Name (English) (if available)
        - Type (individual/entity)
        - ID/Passport Number
        - Date of Birth
        - Nationality
        - Address
        - Reason for Listing
        - Date Added
        
        Structure may vary, so we auto-detect columns.
        """
        entities = []
        
        # Read all rows to detect structure
        rows = list(sheet.iter_rows(values_only=True))
        
        if len(rows) < 2:
            logger.warning("EMLCU sheet has fewer than 2 rows")
            return []
            
        # Detect header row (usually row 1 or 2)
        header_row = None
        header_row_index = 0
        
        for i, row in enumerate(rows[:5]):  # Check first 5 rows
            if row and any(cell for cell in row if cell):
                # Check if this looks like a header
                if self._is_header_row(row):
                    header_row = row
                    header_row_index = i
                    break
                    
        if header_row is None:
            logger.warning("Could not detect header row in EMLCU sheet")
            # Assume first row is header
            header_row = rows[0]
            header_row_index = 0
            
        # Map columns
        column_map = self._map_columns(header_row)
        
        logger.info(f"Detected columns: {column_map}")
        
        # Parse data rows
        for i, row in enumerate(rows[header_row_index + 1:], start=header_row_index + 2):
            if not row or not any(cell for cell in row if cell):
                continue  # Skip empty rows
                
            try:
                entity = self._parse_row(row, column_map, i)
                if entity:
                    entities.append(entity)
            except Exception as e:
                logger.warning(f"Failed to parse row {i}: {e}")
                continue
                
        return entities
        
    def _is_header_row(self, row):
        """
        Check if a row looks like a header row.
        """
        if not row:
            return False
            
        # Check for common Arabic header keywords
        header_keywords = ['اسم', 'رقم', 'تاريخ', 'جنسية', 'عنوان', 'name', 'number', 'date', 'nationality']
        
        row_text = ' '.join(str(cell).lower() for cell in row if cell)
        
        return any(keyword in row_text for keyword in header_keywords)
        
    def _map_columns(self, header_row):
        """
        Map column indices to field names based on header text.
        """
        column_map = {}
        
        for i, cell in enumerate(header_row):
            if not cell:
                continue
                
            cell_text = str(cell).strip().lower()
            
            # Serial number
            if any(keyword in cell_text for keyword in ['م', 'serial', 'number', 'رقم متسلسل']):
                column_map['serial'] = i
                
            # Name (Arabic)
            elif any(keyword in cell_text for keyword in ['الاسم', 'اسم', 'name (ar)', 'arabic name']):
                if 'name_ar' not in column_map:  # First name column is Arabic
                    column_map['name_ar'] = i
                    
            # Name (English)
            elif any(keyword in cell_text for keyword in ['name (en)', 'english name', 'name in english']):
                column_map['name_en'] = i
                
            # Entity Type
            elif any(keyword in cell_text for keyword in ['نوع', 'type', 'فرد', 'كيان', 'entity type']):
                column_map['entity_type'] = i
                
            # ID/Passport
            elif any(keyword in cell_text for keyword in ['رقم قومي', 'رقم جواز', 'passport', 'national id', 'id number']):
                column_map['id_number'] = i
                
            # Date of Birth
            elif any(keyword in cell_text for keyword in ['تاريخ الميلاد', 'date of birth', 'dob', 'birth date']):
                column_map['dob'] = i
                
            # Nationality
            elif any(keyword in cell_text for keyword in ['جنسية', 'nationality', 'الجنسية']):
                column_map['nationality'] = i
                
            # Address
            elif any(keyword in cell_text for keyword in ['عنوان', 'address', 'العنوان']):
                column_map['address'] = i
                
            # Reason
            elif any(keyword in cell_text for keyword in ['سبب', 'reason', 'السبب', 'تفاصيل']):
                column_map['reason'] = i
                
            # Date Added/Listed
            elif any(keyword in cell_text for keyword in ['تاريخ الإدراج', 'date added', 'listed date']):
                column_map['date_listed'] = i
                
        return column_map
        
    def _parse_row(self, row, column_map, row_number):
        """
        Parse a single data row into a standardized entity dictionary.
        """
        # Extract fields based on column map
        name_ar = self._get_cell_value(row, column_map.get('name_ar'))
        name_en = self._get_cell_value(row, column_map.get('name_en'))
        
        # Use Arabic name as primary, English as alias if available
        if not name_ar and not name_en:
            return None  # No name, skip
            
        full_name = name_en if name_en else name_ar
        original_name = name_ar if name_ar else None
        
        # Determine entity type
        entity_type_val = self._get_cell_value(row, column_map.get('entity_type'))
        entity_type = self._detect_entity_type(entity_type_val, full_name)
        
        # Extract other fields
        id_number = self._get_cell_value(row, column_map.get('id_number'))
        dob = self._parse_date(self._get_cell_value(row, column_map.get('dob')))
        nationality = self._get_cell_value(row, column_map.get('nationality'))
        address = self._get_cell_value(row, column_map.get('address'))
        reason = self._get_cell_value(row, column_map.get('reason'))
        date_listed = self._parse_date(self._get_cell_value(row, column_map.get('date_listed')))
        
        # Generate unique source ID (use ID number if available, else hash of name)
        if id_number:
            source_id = f"EMLCU-{id_number}"
        else:
            # Hash name to create stable ID
            name_hash = hashlib.md5(full_name.encode('utf-8')).hexdigest()[:12]
            source_id = f"EMLCU-{name_hash}"
            
        # Build aliases list
        aliases = []
        if name_en and name_ar and name_en != name_ar:
            aliases.append(name_ar if name_en == full_name else name_en)
            
        # Build standardized entity
        entity = {
            'source_id': source_id,
            'full_name': full_name,
            'original_name': original_name,
            'list_type': 'SANCTIONS',
            'entity_type': entity_type,
            'dataset': 'EMLCU_Egypt',
            'source': 'emlcu_egypt',
            'source_url': self.url,
            'risk_level': 'HIGH',  # All EMLCU entries are high risk
            'topics': ['terrorism', 'egypt'],
            'countries': ['Egypt'],
            'date_of_birth': dob,
            'nationality': nationality or 'Egypt',
            'aliases': aliases,
            'details': {
                'id_number': id_number,
                'address': address,
                'reason': reason,
                'date_listed': date_listed,
                'row_number': row_number
            }
        }
        
        return entity
        
    def _get_cell_value(self, row, index):
        """
        Safely get cell value from row.
        """
        if index is None or index >= len(row):
            return None
            
        value = row[index]
        
        if value is None:
            return None
            
        # Convert to string and clean
        value_str = str(value).strip()
        
        # Handle Excel None/empty values
        if value_str in ['None', '', 'N/A', 'n/a', '-']:
            return None
            
        return value_str
        
    def _detect_entity_type(self, type_value, name):
        """
        Detect if entity is Individual or Organization.
        """
        if type_value:
            type_lower = str(type_value).lower()
            if any(keyword in type_lower for keyword in ['فرد', 'individual', 'person', 'شخص']):
                return 'INDIVIDUAL'
            elif any(keyword in type_lower for keyword in ['كيان', 'entity', 'organization', 'شركة', 'مؤسسة']):
                return 'ENTITY'
                
        # Fallback: detect from name structure
        # Organizations typically have keywords like: شركة, مؤسسة, جمعية, etc.
        if name:
            name_lower = name.lower()
            org_keywords = ['شركة', 'مؤسسة', 'جمعية', 'company', 'organization', 'foundation', 
                          'association', 'corporation', 'ltd', 'inc', 'llc']
            if any(keyword in name_lower for keyword in org_keywords):
                return 'ENTITY'
                
        # Default to INDIVIDUAL
        return 'INDIVIDUAL'
        
    def _parse_date(self, date_value):
        """
        Parse date from various formats.
        """
        if not date_value:
            return None
            
        # If already a date object (from Excel)
        if isinstance(date_value, datetime):
            return date_value.strftime('%Y-%m-%d')
            
        # Try parsing string
        date_str = str(date_value).strip()
        
        # Common formats
        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d']:
            try:
                parsed = datetime.strptime(date_str, fmt)
                return parsed.strftime('%Y-%m-%d')
            except ValueError:
                continue
                
        # If we can't parse, return as-is
        return date_str
        

def scrape_emlcu_list(url=None):
    """
    Convenience function to scrape EMLCU list.

    Args:
        url: Optional custom URL (uses default if not provided)

    Returns:
        List of standardized entity dictionaries
    """
    scraper = EMLCUScraper(url=url)
    return scraper.scrape_list()


def parse_emlcu_excel(file_path):
    """
    Parse an already-downloaded EMLCU Excel file into standardized entities.

    Used by emlcu_scraper_production.py's EMLCUScraperFixed (which downloads
    the file itself and needs a separate parse step). Delegates to
    scripts/import_sanctions_file.py's parse_emlcu_xlsx, which reads all 3
    sheets (individuals, terrorist entities, legal/corporate persons) by
    scanning for them rather than depending on exact sheet names — the same
    parser the manual-upload UI and the scheduled EMLCU sync both use, so
    every EMLCU code path in this app now agrees on one implementation.
    """
    import os
    import sys
    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts')
    if scripts_dir not in sys.path:
        sys.path.append(scripts_dir)
    from import_sanctions_file import parse_emlcu_xlsx
    return parse_emlcu_xlsx(file_path)


if __name__ == "__main__":
    # Test the scraper
    logging.basicConfig(level=logging.INFO)
    
    print("Testing EMLCU Scraper...")
    print(f"URL: {EMLCUScraper.DEFAULT_URL}")
    
    try:
        entities = scrape_emlcu_list()
        print(f"\nSuccessfully scraped {len(entities)} entities")
        
        if entities:
            print("\nFirst entity:")
            import json
            print(json.dumps(entities[0], indent=2, ensure_ascii=False))
            
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
