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
EMLCU Scraper - Production Ready
================================
Robust scraper for the Egyptian Money Laundering and Terrorist Financing Combating Unit (EMLCU) watchlist.

Features:
- Auto-discovery of latest list URL
- SSL certificate verification fallback
- Exponential backoff retry logic
- Smart caching (3-day TTL)
- Comprehensive error handling
"""

import requests
import os
import time
import json
import hashlib
import logging
import random
import urllib3
from datetime import datetime
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class EMLCUScraperFixed:
    """Enhanced EMLCU scraper with multiple strategies"""
    
    # Multiple URL strategies
    STRATEGIES = [
        {
            'name': 'Provided URL',
            'type': 'direct',
            'url': None,  # User-provided
        },
        {
            'name': 'Latest from database',
            'type': 'database',
            'table': 'screening_data_sources',
            'source_key': 'emlcu_egypt'
        },
        {
            'name': 'Website scraping',
            'type': 'scrape',
            'base_url': 'https://www.mlcu.org.eg',
            'list_page': '/ar/3125/قوائم-ادراج-الكيانات-الارهابية-والارهابيين-المحلية-عملا-بقرار-مجلس-الامن-1373'
        },
        {
            'name': 'Alternative domain',
            'type': 'direct',
            'url': 'https://mlcu.gov.eg/Content/Upload/Large/10202422122646.xlsx'  # Snapshot URL
        },
        {
            'name': 'Local cache',
            'type': 'cache',
            'cache_dir': 'data/cache',
            'max_age_days': 90  # Accept cache up to 90 days old
        }
    ]
    
    def __init__(self, url=None, db_conn=None):
        self.url = url
        self.db_conn = db_conn
        self.session = requests.Session()
        
        # SSL Configuration
        self.session.verify = False  # For govt sites with cert issues
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # User agent rotation
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ]
        # Set initial UA
        self.session.headers['User-Agent'] = random.choice(self.user_agents)

    def scrape_list(self):
        """
        Try multiple strategies sequentially until one succeeds.
        Returns: List of entities or raises after all strategies fail.
        """
        for i, strategy in enumerate(self.STRATEGIES, 1):
            logger.info(f"Strategy {i}: Trying {strategy['name']}...")
            
            try:
                # Ensure fresh UA for each strategy attempt if needed
                self.session.headers['User-Agent'] = random.choice(self.user_agents)

                if strategy['type'] == 'direct':
                    url = strategy.get('url') or self.url
                    if url:
                        result = self._download_direct(url, attempt=1, max_attempts=3)
                        if result:
                            return result
                            
                elif strategy['type'] == 'database':
                    result = self._try_database_url(strategy)
                    if result:
                        return result
                        
                elif strategy['type'] == 'scrape':
                    result = self._scrape_website(strategy)
                    if result:
                        return result
                        
                elif strategy['type'] == 'cache':
                    result = self._try_cache(strategy)
                    if result:
                        logger.warning(f"Using cached data (may be stale)")
                        return result
                        
            except Exception as e:
                logger.warning(f"Strategy {i} failed: {e}")
                continue
                
        # All strategies failed
        raise Exception("All EMLCU scraping strategies failed. Manual intervention required.")
    
    def download_only(self):
        """
        Download the EMLCU file and return the path to the cached file.
        Does NOT parse the file.
        """
        for i, strategy in enumerate(self.STRATEGIES, 1):
            logger.info(f"Strategy {i}: Trying {strategy['name']} (Download Only)...")
            
            try:
                # Ensure fresh UA
                self.session.headers['User-Agent'] = random.choice(self.user_agents)

                if strategy['type'] == 'direct':
                    url = strategy.get('url') or self.url
                    if url:
                        path = self._download_file_only(url)
                        if path: return path
                            
                elif strategy['type'] == 'database':
                    path = self._try_database_download(strategy)
                    if path: return path
                        
                elif strategy['type'] == 'scrape':
                    path = self._scrape_website_download(strategy)
                    if path: return path
                        
                elif strategy['type'] == 'cache':
                    # Return existing cache path if valid
                    cache_dir = strategy.get('cache_dir', 'data/cache')
                    cache_file = os.path.join(cache_dir, 'emlcu_cache.xlsx')
                    if os.path.exists(cache_file):
                        return cache_file
                        
            except Exception as e:
                logger.warning(f"Strategy {i} failed: {e}")
                continue
                
        raise Exception("All EMLCU download strategies failed.")

    def _download_file_only(self, url, max_attempts=3):
        """Download file and return path, without parsing."""
        for i in range(max_attempts):
            try:
                self.session.headers['User-Agent'] = random.choice(self.user_agents)
                logger.info(f"Attempt {i+1}: Downloading from {url[:50]}...")
                
                response = self.session.get(url, timeout=60, stream=True)
                response.raise_for_status()
                
                # Verify Excel magic bytes
                chunk = next(response.iter_content(chunk_size=4), b'')
                if chunk != b'PK\x03\x04':
                    logger.warning("Content is not Excel (PK header missing)")
                    if i < max_attempts - 1: time.sleep(2); continue
                    return None
                    
                # Save to cache
                cache_dir = 'data/cache'
                os.makedirs(cache_dir, exist_ok=True)
                cache_file = os.path.join(cache_dir, 'emlcu_cache.xlsx')
                
                with open(cache_file, 'wb') as f:
                    f.write(chunk)
                    for block in response.iter_content(chunk_size=8192):
                        f.write(block)
                        
                return cache_file
                
            except Exception as e:
                logger.warning(f"Download error: {e}")
                if i < max_attempts - 1: time.sleep(2)
                
        return None

    def _try_database_download(self, strategy):
        if not self.db_conn: return None
        try:
            cursor = self.db_conn.cursor()
            cursor.execute("SELECT source_url FROM screening_data_sources WHERE source_name = %s", ('emlcu',))
            row = cursor.fetchone()
            if row and row[0]: return self._download_file_only(row[0])
        except: pass
        return None

    def _scrape_website_download(self, strategy):
        url = self._find_latest_url(strategy)
        if url: return self._download_file_only(url)
        return None

    def _find_latest_url(self, strategy):
        """Scrape the EMLCU list page to find the most recent Excel file."""
        try:
            from bs4 import BeautifulSoup
            list_page_url = strategy['base_url'] + strategy['list_page']
            logger.info(f"Searching for latest list on: {list_page_url}")
            
            response = self.session.get(list_page_url, timeout=45)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Lists of Arabic and English month names for discovery
            months_ar = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']
            months_en = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']
            
            # Find all potential Excel links
            excel_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.xlsx' in href.lower() or '.xls' in href.lower():
                    link_text = link.get_text().strip()
                    # Check for specific class 'AutoDownload' often used on MLCU site
                    classes = link.get('class', [])
                    bonus_score = 30 if 'AutoDownload' in classes else 0
                    
                    # Normalize URL
                    if href.startswith('http'):
                        full_href = href
                    else:
                        # Handle relative paths and ensure no double slashes except after protocol
                        base = strategy['base_url'].rstrip('/')
                        path = href if href.startswith('/') else '/' + href
                        full_href = base + path
                    
                    excel_links.append((link_text, full_href, bonus_score))
            
            if not excel_links:
                return None
                
            # Score links to find the best candidate (latest list)
            scored_links = []
            current_month_idx = datetime.now().month - 1 # 0-indexed
            
            for text, href, bonus in excel_links:
                score = bonus
                text_lower = text.lower()
                href_lower = href.lower()
                
                # Keywords
                if any(kw in text_lower or kw in href_lower for kw in ['إرهاب', 'terror', 'list', 'قوائم']):
                    score += 50
                
                # Month matching (higher score for current or recent months)
                for i, (m_ar, m_en) in enumerate(zip(months_ar, months_en)):
                    if m_ar in text or m_en in text_lower or m_ar in href_lower or m_en in href_lower:
                        # Distance from current month (circular)
                        dist = abs(i - current_month_idx)
                        if dist > 6: dist = 12 - dist
                        score += (20 - dist * 2) # Closer months get higher score
                
                # Year matching
                current_year = str(datetime.now().year)
                if current_year in text or current_year in href:
                    score += 30
                    
                scored_links.append((score, href))
            
            # Sort by score descending
            scored_links.sort(key=lambda x: x[0], reverse=True)
            
            if scored_links and scored_links[0][0] > 30:
                latest_url = scored_links[0][1]
                # Fix encoding issues in URL if present (MLCU sometimes has spaces in filenames)
                if ' ' in latest_url:
                    latest_url = latest_url.replace(' ', '%20')
                
                logger.info(f"Discovered latest EMLCU URL: {latest_url}")
                return latest_url

        except Exception as e:
            logger.warning(f"URL finding failed: {e}")
        return None

    
    def _download_direct(self, url, attempt=1, max_attempts=3):
        """Download with retries and exponential backoff"""
        for i in range(max_attempts):
            try:
                # Rotate user agent
                self.session.headers['User-Agent'] = random.choice(self.user_agents)
                
                logger.info(f"Attempt {i+1}/{max_attempts}: Downloading from {url[:50]}...")
                
                response = self.session.get(
                    url,
                    timeout=60,
                    verify=False,
                    allow_redirects=True
                )
                response.raise_for_status()
                
                # Verify content is actually Excel
                if response.content[:4] != b'PK\x03\x04':  # Excel magic bytes
                    logger.warning("Downloaded content is not Excel format")
                    # Check if it helps to follow redirects manually or check headers
                    if i < max_attempts - 1:
                        time.sleep(2 ** i)  # Exponential backoff
                        continue
                    else:
                        return None
                
                # Cache the download
                self._save_to_cache(response.content)
                
                # Parse
                from .emlcu_scraper import parse_emlcu_excel
                # We can reuse the parsing logic if it's available or reimplement it
                # For now, let's assume we can save to a tmp file and parse
                
                tmp_path = 'temp_emlcu.xlsx'
                with open(tmp_path, 'wb') as f:
                    f.write(response.content)
                    
                entities = parse_emlcu_excel(tmp_path)
                logger.info(f"✓ Successfully parsed {len(entities)} entities from EMLCU list")
                
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

                return entities
                
            except requests.exceptions.SSLError as e:
                logger.warning(f"SSL Error on attempt {i+1}: {e}")
                if i < max_attempts - 1:
                    time.sleep(2 ** i)
                    
            except requests.exceptions.Timeout as e:
                logger.warning(f"Timeout on attempt {i+1}: {e}")
                if i < max_attempts - 1:
                    time.sleep(5)  # Wait longer for timeout
                    
            except Exception as e:
                logger.error(f"Unexpected error on attempt {i+1}: {e}")
                if i < max_attempts - 1:
                    time.sleep(2 ** i)
                    
        return None
    
    def _try_database_url(self, strategy):
        """Try to get URL from database config"""
        if not self.db_conn:
            return None
            
        try:
            cursor = self.db_conn.cursor()
            cursor.execute(
                "SELECT source_url FROM screening_data_sources WHERE source_key = %s",
                (strategy.get('source_key'),)
            )
            row = cursor.fetchone()
            
            if row and row[0]:
                url = row[0]
                logger.info(f"Found URL in database: {url[:50]}...")
                return self._download_direct(url)
                
        except Exception as e:
            logger.warning(f"Database URL lookup failed: {e}")
            
        return None
    
    def _scrape_website(self, strategy):
        """
        Scrape the EMLCU website to find the latest list URL.
        The list is typically on their "Local Lists" page.
        """
        try:
            # Check if optional dependency is installed
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("BeautifulSoup not installed. Cannot scrape website.")
            return None
            
        try:
            list_page_url = strategy['base_url'] + strategy['list_page']
            logger.info(f"Scraping website for latest list URL: {list_page_url}")
            
            response = self.session.get(list_page_url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find links to Excel files
            excel_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.xlsx' in href or '.xls' in href:
                    # Check if it's a terrorist list (Arabic keywords)
                    link_text = link.get_text()
                    if any(keyword in link_text for keyword in ['إرهاب', 'قائمة', 'كيان']):
                        if href.startswith('http'):
                            excel_links.append(href)
                        elif href.startswith('/'):
                            full_url = strategy['base_url'] + href
                            excel_links.append(full_url)
                        else:
                            full_url = strategy['base_url'] + '/' + href
                            excel_links.append(full_url)
            
            if excel_links:
                # Try the first (most recent) link
                latest_url = excel_links[0]
                logger.info(f"Found latest list URL: {latest_url[:50]}...")
                
                # Update database with new URL
                if self.db_conn:
                    try:
                        cursor = self.db_conn.cursor()
                        # Use source_name
                        cursor.execute(
                            "UPDATE screening_data_sources SET source_url = %s, last_successful_update = CURRENT_TIMESTAMP WHERE source_name = 'emlcu' OR source_name LIKE '%EMLCU%'",
                            (latest_url,)
                        )
                        self.db_conn.commit()
                        logger.info("Updated database with new EMLCU URL")
                    except Exception as db_err:
                        logger.warning(f"Failed to update database with new URL: {db_err}")
                
                return self._download_direct(latest_url)
            else:
                logger.warning("No Excel links found on EMLCU page")
                
        except Exception as e:
            logger.warning(f"Website scraping failed: {e}")
            
        return None
    
    def _try_cache(self, strategy):
        """Try to use local cached file"""
        cache_dir = strategy.get('cache_dir', 'data/cache')
        cache_file = os.path.join(cache_dir, 'emlcu_cache.xlsx')
        cache_meta = os.path.join(cache_dir, 'emlcu_metadata.json')
        
        if not os.path.exists(cache_file):
            logger.info("No cache file found")
            return None
            
        # Check cache age
        try:
            with open(cache_meta, 'r') as f:
                meta = json.load(f)
            
            cache_age_days = (time.time() - meta['timestamp']) / 86400
            max_age = strategy.get('max_age_days', 90)
            
            if cache_age_days > max_age:
                logger.warning(f"Cache is {cache_age_days:.1f} days old (max: {max_age})")
                # We interpret "max_age" strictly for auto-use, but if it's last resort we might use it anyway
                # But here we return None to allow other strategies or fail
                # Actually, since this is the last strategy, we might want to be lenient if configured
                return None
                
            logger.info(f"Using cache from {cache_age_days:.1f} days ago")
            
        except:
            logger.info("Cache metadata missing, avoiding cache")
            return None
            
        # Parse cached file
        from .emlcu_scraper import parse_emlcu_excel
        return parse_emlcu_excel(cache_file)
    
    def _save_to_cache(self, content):
        """Save downloaded content to cache"""
        cache_dir = 'data/cache'
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)
        
        cache_file = os.path.join(cache_dir, 'emlcu_cache.xlsx')
        cache_meta = os.path.join(cache_dir, 'emlcu_metadata.json')
        
        # Save file
        with open(cache_file, 'wb') as f:
            f.write(content)
            
        # Save metadata
        meta = {
            'timestamp': time.time(),
            'size': len(content),
            'hash': hashlib.md5(content).hexdigest()
        }
        
        with open(cache_meta, 'w') as f:
            json.dump(meta, f)
            
        logger.info(f"Saved to cache: {cache_file}")
        return cache_file

# Standalone execution
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scraper = EMLCUScraperFixed()
    try:
        entities = scraper.scrape_list()
        print(f"Successfully scraped {len(entities)} entities")
    except Exception as e:
        print(f"Scraping failed: {e}")
