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

import requests
import feedparser
import asyncio
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
import logging
import json

logger = logging.getLogger(__name__)


# ============================================================================
# ABSTRACT BASE CLASS
# ============================================================================

class NewsSource(ABC):
    """Abstract base class for all news sources"""
    
    def __init__(self, config: dict):
        self.config = config
        self.name = self.__class__.__name__
        self.enabled = config.get('enabled', True)
        self.priority = config.get('priority', 999)
    
    @abstractmethod
    async def search(self, query: str, **kwargs) -> List[Dict]:
        """
        Search for news articles
        
        Args:
            query: Search term (person/company name)
            **kwargs: Additional filters (date_from, date_to, language, etc.)
        
        Returns:
            List of articles in standardized format
        """
        pass
    
    def is_available(self) -> bool:
        """Check if source is enabled and available"""
        return self.enabled
    
    def standardize_article(self, raw_article: dict) -> Dict:
        """
        Convert API-specific format to standard format
        
        Standard format:
        {
            'title': str,
            'description': str,
            'url': str,
            'published_at': datetime,
            'source': str,
            'language': str,
            'relevance_score': float,
            'snippet': str
        }
        """
        pass


# ============================================================================
# SOURCE 1: NewsAPI.org
# ============================================================================

class NewsAPISource(NewsSource):
    """
    Primary source: NewsAPI.org via newsapi-python
    """
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config['newsapi_key']
        self.language = config.get('newsapi_language', 'ar,en')
        self.page_size = config.get('newsapi_page_size', 20)
        self.timeout = config.get('newsapi_timeout', 8)
        
    async def search(self, query: str, **kwargs) -> List[Dict]:
        try:
            from newsapi import NewsApiClient
            client = NewsApiClient(api_key=self.api_key)
            
            logger.info(f"[NewsAPI.org] Searching for: {query}")
            
            loop = asyncio.get_event_loop()
            
            def do_search():
                return client.get_everything(
                    q=f'"{query}"',
                    language='en',
                    sort_by='relevancy',
                    page_size=self.page_size
                )
                
            response = await loop.run_in_executor(None, do_search)
            
            if response and response.get('status') == 'ok':
                articles = response.get('articles', [])
                logger.info(f"[NewsAPI.org] Found {len(articles)} articles")
                return [self.standardize_article(a) for a in articles]
            else:
                logger.error(f"[NewsAPI.org] Error response: {response}")
                raise Exception("NewsAPI error")
                
        except Exception as e:
            logger.error(f"[NewsAPI.org] Failed: {str(e)}")
            raise
    
    def standardize_article(self, article: dict) -> Dict:
        return {
            'title': article.get('title', ''),
            'description': article.get('description', ''),
            'url': article.get('url', ''),
            'published_at': datetime.fromisoformat(
                article.get('publishedAt', '').replace('Z', '+00:00')
            ) if article.get('publishedAt') else None,
            'source': article.get('source', {}).get('name', 'NewsAPI.org'),
            'language': 'en',
            'relevance_score': 0.8,
            'snippet': article.get('description', '')[:200] if article.get('description') else ''
        }


# ============================================================================
# SOURCE 2: Google News RSS
# ============================================================================

class GoogleNewsRSSSource(NewsSource):
    def __init__(self, config: dict):
        super().__init__(config)
        self.timeout = config.get('timeout', 8)
        
    async def search(self, query: str, **kwargs) -> List[Dict]:
        from urllib.parse import quote_plus
        import requests
        import feedparser
        # The exact phrase first (precise), then the loose query (catches the
        # name written with other words between its elements). Relevance to
        # the screened person is judged afterwards (adverse_relevance).
        loop = asyncio.get_event_loop()
        articles, errors = [], []
        for q in (f'"{query}"', query):
            url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=ar&gl=EG&ceid=EG:ar"
            def do_fetch(url=url):
                resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}, timeout=self.timeout)
                resp.raise_for_status()
                return feedparser.parse(resp.content)
            try:
                feed = await loop.run_in_executor(None, do_fetch)
                articles += [self.standardize_article(e) for e in feed.entries]
            except Exception as e:
                errors.append(str(e))
                logger.error(f"[GoogleNewsRSS] Failed for {q!r}: {e}")
        if errors and not articles:
            raise Exception('; '.join(errors)[:200])
        logger.info(f"[GoogleNewsRSS] Found {len(articles)} articles")
        return articles
            
    def _strip_html(self, text: str) -> str:
        if not text:
            return ''
        import re
        clean = re.sub(r'<[^>]+>', '', text)
        clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        return clean.strip()
            
    def standardize_article(self, entry: dict) -> Dict:
        pub_date = None
        if 'published_parsed' in entry and entry.published_parsed:
            pub_date = datetime(*entry.published_parsed[:6])
        
        summary = entry.get('description', entry.get('summary', ''))
        clean_desc = self._strip_html(summary)
            
        return {
            'title': entry.get('title', ''),
            'description': clean_desc,
            'url': entry.get('link', ''),
            'published_at': pub_date,
            'source': entry.get('source', {}).get('title', 'Google News'),
            'language': 'ar',
            'relevance_score': 0.6,
            'snippet': clean_desc[:200] if clean_desc else ''
        }


# ============================================================================
# SOURCE 3: Yahoo Finance RSS
# ============================================================================

class YahooFinanceRSSSource(NewsSource):
    def __init__(self, config: dict):
        super().__init__(config)
        self.timeout = config.get('timeout', 8)
        
    async def search(self, query: str, **kwargs) -> List[Dict]:
        from urllib.parse import quote_plus
        import requests
        import feedparser
        try:
            encoded_name = quote_plus(query)
            url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={encoded_name}&region=EG"
            logger.info(f"[YahooFinanceRSS] URL: {url}")
            
            loop = asyncio.get_event_loop()
            def do_fetch():
                resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}, timeout=self.timeout)
                resp.raise_for_status()
                return feedparser.parse(resp.content)
                
            feed = await loop.run_in_executor(None, do_fetch)
            articles = []
            for entry in feed.entries:
                articles.append(self.standardize_article(entry))
            logger.info(f"[YahooFinanceRSS] Found {len(articles)} articles")
            return articles
        except Exception as e:
            logger.error(f"[YahooFinanceRSS] Failed: {str(e)}")
            return []
            
    def _strip_html(self, text: str) -> str:
        if not text:
            return ''
        import re
        clean = re.sub(r'<[^>]+>', '', text)
        clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        return clean.strip()
            
    def standardize_article(self, entry: dict) -> Dict:
        pub_date = None
        if 'published_parsed' in entry and entry.published_parsed:
            pub_date = datetime(*entry.published_parsed[:6])
            
        summary = entry.get('description', entry.get('summary', ''))
        clean_desc = self._strip_html(summary)
            
        return {
            'title': entry.get('title', ''),
            'description': clean_desc,
            'url': entry.get('link', ''),
            'published_at': pub_date,
            'source': 'Yahoo Finance',
            'language': 'en',
            'relevance_score': 0.6,
            'snippet': clean_desc[:200] if clean_desc else ''
        }


# ============================================================================
# SOURCE 4: Direct RSS Feeds
# ============================================================================

class RSSFeedSource(NewsSource):
    """
    Fallback 3: Direct RSS feeds from Egyptian news outlets
    Uses feedparser library
    """
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.sources = config['sources']
        self.timeout = 8 # Enforce max 8 seconds
    
    async def search(self, query: str, **kwargs) -> List[Dict]:
        all_articles = []
        query_lower = query.lower()
        
        logger.info(f"[RSS Feeds] Searching {len(self.sources)} feeds for: {query}")
        
        loop = asyncio.get_event_loop()
        
        async def fetch_feed(source_config):
            if not source_config.get('enabled', True):
                return []
            try:
                def do_fetch():
                    # Use requests to properly enforce timeout before feedparser
                    resp = requests.get(source_config['url'], headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'ar,en-US;q=0.9,en;q=0.8',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Connection': 'keep-alive',
                        'Cache-Control': 'no-cache',
                        'Referer': 'https://www.google.com/'
                    }, timeout=self.timeout)
                    resp.raise_for_status()
                    return feedparser.parse(resp.content)
                
                feed = await loop.run_in_executor(None, do_fetch)
                
                feed_articles = []
                for entry in feed.entries:
                    title = entry.get('title', '').lower()
                    description = entry.get('description', '').lower()
                    
                    # Check if query appears in title or description
                    if query_lower in title or query_lower in description:
                        article = self.standardize_article(entry, source_config)
                        feed_articles.append(article)
                
                logger.info(f"[RSS] {source_config['name']}: Found {len(feed_articles)} matches")
                return feed_articles
            except Exception as e:
                logger.warning(f"[RSS] Failed to parse {source_config['name']}: {str(e)}")
                return []
                
        tasks = [fetch_feed(cfg) for cfg in self.sources.values()]
        results = await asyncio.gather(*tasks)
        for res in results:
            all_articles.extend(res)
            
        logger.info(f"[RSS Feeds] Total articles found: {len(all_articles)}")
        return all_articles
    
    def _strip_html(self, text: str) -> str:
        if not text:
            return ''
        import re
        clean = re.sub(r'<[^>]+>', '', text)
        clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        return clean.strip()
        
    def standardize_article(self, entry: dict, source_config: dict) -> Dict:
        # Parse publication date
        pub_date = None
        if 'published_parsed' in entry and entry.published_parsed:
            pub_date = datetime(*entry.published_parsed[:6])
        elif 'updated_parsed' in entry and entry.updated_parsed:
            pub_date = datetime(*entry.updated_parsed[:6])
            
        summary = entry.get('description', entry.get('summary', ''))
        clean_desc = self._strip_html(summary)
        
        return {
            'title': entry.get('title', ''),
            'description': clean_desc,
            'url': entry.get('link', ''),
            'published_at': pub_date,
            'source': source_config['name'],
            'language': source_config.get('language', 'en'),
            'relevance_score': 0.5,
            'snippet': clean_desc[:200] if clean_desc else ''
        }


# ============================================================================
# WATERFALL ORCHESTRATOR
# ============================================================================

class WaterfallAdverseMediaScraper:
    """
    Main orchestrator that implements waterfall pattern
    """
    
    def __init__(self, config: dict, cache=None):
        self.config = config
        self.cache = cache
        
        # Keywords for ADVERSE risk assessment mapping
        self.risk_keywords = config.get('search', {}).get('keywords', [])
        
        # Initialize all sources
        self.sources = []
        
        if config.get('newsapi', {}).get('enabled'):
            self.sources.append(NewsAPISource(config['newsapi']))
        
        if config.get('google_news', {}).get('enabled'):
            self.sources.append(GoogleNewsRSSSource(config['google_news']))
            
        if config.get('yahoo_finance', {}).get('enabled'):
            self.sources.append(YahooFinanceRSSSource(config['yahoo_finance']))
        
        if config.get('rss_feeds', {}).get('enabled'):
            self.sources.append(RSSFeedSource(config['rss_feeds']))
        
        # Sort by priority
        self.sources.sort(key=lambda x: x.priority)
        
        logger.info(f"Initialized {len(self.sources)} news sources")
    
    async def search(self, query: str, use_cache: bool = True) -> Dict:
        """
        Execute waterfall search
        
        Returns:
        {
            'query': str,
            'total_articles': int,
            'sources_used': List[str],
            'sources_failed': List[str],
            'articles': List[Dict],
            'search_time_ms': int,
            'cached': bool
        }
        """
        start_time = datetime.now()
        
        # Check cache first
        if use_cache and self.cache:
            try:
                cached_result = self.cache.get(query)
                if cached_result:
                    logger.info(f"[CACHE HIT] Returning cached results for: {query}")
                    cached_result = json.loads(cached_result) if isinstance(cached_result, str) else cached_result
                    cached_result['cached'] = True
                    return cached_result
            except Exception as e:
                logger.error(f"Cache retrieval error: {e}")
        
        all_articles = []
        sources_used = []
        sources_failed = []
        
        # Try each source in parallel
        search_params = {
            'language': ','.join(self.config['search'].get('languages', ['en','ar'])),
            'countries': ','.join(self.config['search'].get('countries', ['eg'])),
            'limit': self.config['search']['max_results_per_source'],
            'date_from': datetime.now() - timedelta(
                days=self.config['search']['lookback_days']
            )
        }

        # Per-source deadline. Without this a single slow source (Google News
        # RSS regularly needs ~32s) consumes the entire screening budget and
        # every other source's results are lost with it.
        per_source_timeout = self.config.get('search', {}).get(
            'per_source_timeout', 25)

        failed = {}

        async def _safe_source_search(source):
            if not source.is_available():
                return []
            try:
                articles = await asyncio.wait_for(
                    source.search(query, **search_params),
                    timeout=per_source_timeout,
                )
                if articles:
                    logger.info(f"✅ {source.name}: {len(articles)} articles")
                    return articles
                else:
                    logger.info(f"⚠️ {source.name}: No results")
                    return []
            except asyncio.TimeoutError:
                # Degrade this one source, keep everything the others found.
                logger.warning(
                    f"⏱️ {source.name} exceeded {per_source_timeout}s and was "
                    f"dropped; other sources are unaffected")
                failed[source.name] = 'timeout'
                return []
            except Exception as e:
                logger.error(f"❌ {source.name} failed: {str(e)}")
                failed[source.name] = str(e)[:120]
                return []

        # Run all searches in parallel
        tasks = [_safe_source_search(s) for s in self.sources]
        source_articles_list = await asyncio.gather(*tasks)
        
        for articles in source_articles_list:
            all_articles.extend(articles)
            
        # Logging sources used/failed for metadata
        for source, articles in zip(self.sources, source_articles_list):
            if source.name in failed:
                sources_failed.append(source.name)
            elif source.is_available():
                # answered (with or without results) — the source was searched
                sources_used.append(source.name)
        
        # Remove duplicates (by URL)
        unique_articles = self._deduplicate_articles(all_articles)
        
        # Extract purely adverse subset based on keyword matches inline
        for a in unique_articles:
            text_corpus = (a.get('title', '') + ' ' + a.get('description', '')).lower()
            a['matched_keywords'] = [kw for kw in self.risk_keywords if kw.lower() in text_corpus]
            # Simple risk mapping
            a['risk_score'] = len(a['matched_keywords']) * 20.0
            # Clean up datetime for JSON serialization
            if isinstance(a.get('published_at'), datetime):
                a['published_at'] = a['published_at'].isoformat()
        
        # Sort by risk score and date
        unique_articles.sort(
            key=lambda x: (x.get('risk_score', 0), x['published_at'] or ''),
            reverse=True
        )
        
        # Calculate search time
        search_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        result = {
            'query': query,
            'total_articles': len(unique_articles),
            'sources_used': sources_used,
            'sources_failed': sources_failed,
            'articles': unique_articles,
            'search_time_ms': search_time_ms,
            'cached': False
        }
        
        # Cache result
        if self.cache and use_cache:
            try:
                self.cache.setex(f"adverse_media:{query.lower().strip()}", self.config['cache']['ttl'], json.dumps(result))
                logger.info(f"[CACHE] Saved results for: {query}")
            except Exception as e:
                logger.error(f"Cache save error: {e}")
        
        logger.info(
            f"Search complete: {len(unique_articles)} articles from "
            f"{len(sources_used)} sources in {search_time_ms}ms"
        )
        
        return result
    
    def _deduplicate_articles(self, articles: List[Dict]) -> List[Dict]:
        """Remove duplicate articles based on URL"""
        seen_urls = set()
        unique = []
        
        for article in articles:
            url = article.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique.append(article)
        
        return unique
    
    async def batch_search(self, queries: List[str]) -> Dict[str, Dict]:
        """Search multiple names/entities in parallel"""
        tasks = [self.search(query) for query in queries]
        results = await asyncio.gather(*tasks)
        
        return {
            queries[i]: results[i] 
            for i in range(len(queries))
        }

    # ============================================================================
    # SYNCHRONOUS ENGINE BRIDGE
    # ============================================================================
    
    def screen_person(self, name: str, context: dict = None, save_to_db: bool = True) -> dict:
        """
        Adapter method for synchronous ComplyNex Screening Engine.
        Executes the async Waterfall search and maps the result to the CMS media schema.
        """
        logger.info(f"Waterfall Adverse Media Screening initiated for: {name}")
        
        from concurrent.futures import ThreadPoolExecutor

        try:
            # Execute async search in a new event loop in a separate thread
            # to avoid conflicts with gevent's patched event loop
            import nest_asyncio
            # A Latin name is also searched in Arabic: most Egyptian news about
            # an Egyptian customer is written in Arabic.
            queries = [name]
            try:
                from screening import match_intel as _mi
                if not _mi.is_arabic(name):
                    ar = _mi.to_arabic_display(name)
                    if ar and all(_mi.is_arabic(t) for t in ar.split()):
                        queries.append(ar)
            except Exception:
                pass

            def run_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    res = loop.run_until_complete(asyncio.gather(*[self.search(q) for q in queries]))
                finally:
                    loop.close()
                merged = {'articles': [], 'sources_used': [], 'sources_failed': []}
                for r in res:
                    merged['articles'] += r.get('articles', [])
                    merged['sources_used'] += [x for x in r.get('sources_used', []) if x not in merged['sources_used']]
                    merged['sources_failed'] += [x for x in r.get('sources_failed', []) if x not in merged['sources_failed']]
                merged['sources_failed'] = [x for x in merged['sources_failed'] if x not in merged['sources_used']]
                merged['articles'] = self._deduplicate_articles(merged['articles'])
                return merged

            # NOTE: deliberately NOT a `with` block. Exiting a ThreadPoolExecutor
            # context manager calls shutdown(wait=True), which blocks until the
            # worker finishes — so the timeout below would expire and *still*
            # wait for the slow source. shutdown(wait=False) lets a stuck source
            # be abandoned instead of pinning the request.
            total_timeout = self.config.get('search', {}).get(
                'total_timeout', 40)
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(run_async)
                result = future.result(timeout=total_timeout)
            finally:
                executor.shutdown(wait=False)
            
            # Keep only articles that name this person, and call an article
            # adverse only when it carries a risk term (adverse_relevance).
            from screening.adverse_relevance import assess
            verdict = assess(name, result.get('articles', []))

            def _map(article):
                pub = article.get('published_at', '')
                if isinstance(pub, datetime):
                    pub = pub.isoformat()
                return {
                    'title': article.get('title', ''),
                    'description': article.get('description', ''),
                    'url': article.get('url', ''),
                    'published_at': pub,
                    'published': pub,  # legacy template compatibility
                    'source': article.get('source', 'Unknown'),
                    'language': article.get('language'),
                    'risk_score': article.get('risk_score', 0.0),
                    'severity': article.get('severity', 0),
                    'categories': article.get('categories', []),
                    'matched_keywords': article.get('matched_keywords', []),
                    'name_match': article.get('name_match'),
                }

            mapped_hits = [_map(a) for a in verdict['hits']]
            mentions = [_map(a) for a in verdict['mentions']][:10]
            risk_level = verdict['risk_level']
            recommendation = {
                'HIGH': '🚨 HIGH RISK: the person is named in news about terrorism, sanctions or financial crime. Escalate.',
                'MEDIUM': '⚠️ MEDIUM RISK: the person is named in news about criminal proceedings or serious allegations. Enhanced due diligence.',
                'LOW': '⚠️ LOW RISK: weak or partial-name adverse news. Review and record the conclusion.',
                'CLEAR': '✅ CLEAR: no adverse news naming this person was found.',
            }[risk_level]
            if risk_level == 'CLEAR' and not result.get('sources_used'):
                risk_level = 'ERROR'
                recommendation = '⚠️ No news source answered — no conclusion can be drawn. Please retry.'

            return {
                'all_hits': mapped_hits,
                'total_hits': len(mapped_hits),
                'risk_score': verdict['risk_score'],
                'risk_level': risk_level,
                'recommendation': recommendation,
                'mentions': mentions,
                'mentions_count': len(verdict['mentions']),
                'unrelated_filtered': verdict['unrelated'],
                'articles_reviewed': len(result.get('articles', [])),
                'queries': queries,
                'sources_used': result.get('sources_used', []),
                'sources_failed': result.get('sources_failed', [])
            }
            
        except FuturesTimeoutError:
            # A bare TimeoutError has no message, which is why this used to
            # surface to the user as the meaningless "Screening failed ()".
            import traceback
            logger.error(
                "Adverse media screening exceeded its total budget for "
                f"{name!r}; returning TIMEOUT so the caller can retry")
            logger.error(traceback.format_exc())
            return {
                'all_hits': [],
                'total_hits': 0,
                'risk_score': 0.0,
                'risk_level': 'TIMEOUT',
                'recommendation': (
                    '⏱️ News sources did not respond in time. '
                    'No adverse media conclusion can be drawn — please retry.'
                ),
                'sources_used': [],
                'sources_failed': ['timeout'],
            }
        except Exception as e:
            import traceback
            msg = str(e) or type(e).__name__
            logger.error(f"Error in synchronous screen_person bridge: {msg}")
            logger.error(traceback.format_exc())
            return {
                'all_hits': [],
                'total_hits': 0,
                'risk_score': 0.0,
                'risk_level': 'ERROR',
                'recommendation': f'⚠️ ERROR: Screening failed ({msg})',
                'sources_used': [],
                'sources_failed': ['error'],
            }
