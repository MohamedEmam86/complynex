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
Enhanced Adverse Media Screener for Egypt
==========================================

Free sources for Egyptian adverse media screening:
1. Google News RSS (Egypt Edition)
2. NewsAPI.org (Free tier: 100 requests/day)
3. Egypt Independent (web scraping)
4. Al-Ahram English (web scraping)
5. Mada Masr (web scraping)
6. Daily News Egypt (web scraping)
7. Egyptian Streets (web scraping)

Features:
- Multi-source aggregation
- Source credibility scoring
- Date relevance weighting
- Name verification (prevent false positives)
- Sentiment analysis
- Risk categorization
- Caching to avoid duplicate requests
"""

import requests
import feedparser
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin
import logging
from datetime import datetime, timedelta
import hashlib
import json
import re
try:
    from textblob import TextBlob
except ImportError:
    TextBlob = None
try:
    import redis
except ImportError:
    redis = None

from .api_config import APIConfig, NEWSAPI_RATE_LIMITER

logger = logging.getLogger(__name__)

class AdverseMediaScreener:
    """
    Enhanced adverse media screening with multiple Egyptian sources.
    All sources are FREE but have rate limits.
    """
    
    # Source Credibility Weights (0.0 - 1.0)
    SOURCE_CREDIBILITY = {
        'al-ahram': 1.0,      # Official state newspaper
        'egypt-independent': 0.9,
        'mada-masr': 0.85,    # Independent investigative
        'daily-news-egypt': 0.8,
        'egyptian-streets': 0.75,
        'youm7': 0.75,
        'masrawy': 0.75,
        'google-news': 0.7,
        'yahoo-news': 0.7,
        'newsapi': 0.8,
        'unknown': 0.5
    }
    
    # Risk Keywords (Weighted)
    RISK_KEYWORDS_AR = {
        # High Risk (Weight: 40 - CRITICAL)
        'فساد': 40, 'رشوة': 40, 'غسيل أموال': 40, 'غسل أموال': 40,
        'احتيال': 40, 'تزوير': 40, 'اختلاس': 40, 'تهريب': 40,
        'إرهاب': 40, 'تمويل إرهاب': 40, 'منظمة إجرامية': 40,
        'اتجار': 40, 'مخدرات': 35, 'سلاح': 35,
        
        # Medium Risk (Weight: 15 - Boosted)
        'اعتقال': 15, 'سجن': 15, 'محاكمة': 15, 'اتهام': 15,
        'تحقيق جنائي': 15, 'النيابة': 15, 'قبض على': 15,
        'حبس احتياطي': 15, 'تحفظ على': 15,
        
        # Low Risk (Weight: 5)
        'جريمة': 5, 'جناية': 5, 'مخالفة': 5, 'غرامة': 5,
        'استغلال نفوذ': 6, 'تهرب ضريبي': 6,
        
        # Sanctions/Watchlists (Weight: 40 - Boosted)
        'عقوبات': 40, 'حظر': 40, 'قائمة سوداء': 40,
        'قائمة الإرهاب': 40, 'الانتربول': 40
    }
    
    RISK_KEYWORDS_EN = {
        # High Risk
        'corruption': 40, 'bribery': 40, 'money laundering': 40,
        'fraud': 40, 'forgery': 40, 'embezzlement': 40, 'smuggling': 40,
        'terrorism': 40, 'terrorist financing': 40, 'organized crime': 40,
        'trafficking': 40, 'narcotics': 35, 'weapons': 35,
        
        # Medium Risk
        'arrested': 15, 'imprisoned': 15, 'trial': 15, 'accused': 15,
        'criminal investigation': 15, 'prosecution': 15, 'detained': 15,
        'custody': 15, 'indicted': 15,
        
        # Low Risk
        'crime': 5, 'felony': 5, 'violation': 5, 'fine': 5,
        'abuse of power': 6, 'tax evasion': 6,
        
        # Sanctions
        'sanctions': 40, 'blacklisted': 40, 'watchlist': 40,
        'terror list': 40, 'interpol': 40, 'wanted': 35
    }
    
    def __init__(self, newsapi_key=None, redis_client=None, cache_ttl=86400):
        """
        Initialize screener.
        
        Args:
            newsapi_key: Optional NewsAPI.org API key (free tier: 100/day)
            redis_client: Optional Redis client for caching
            cache_ttl: Cache time-to-live in seconds (default: 24 hours)
        """
        self.newsapi_key = newsapi_key or APIConfig.get_newsapi_key()
        self.redis = redis_client
        self.cache_ttl = cache_ttl
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.rate_limiter = NEWSAPI_RATE_LIMITER
        
    def screen_person(self, name, additional_context=None):
        """
        Screen a person against multiple adverse media sources.
        
        Args:
            name: Person's name (Arabic or English)
            additional_context: Dict with optional context (dob, nationality, occupation)
            
        Returns:
            Dict with aggregated results and risk score
        """
        # Check cache first
        cache_key = self._generate_cache_key(name, additional_context)
        cached = self._get_from_cache(cache_key)
        if cached:
            logger.info(f"Cache hit for: {name}")
            return cached
            
        all_hits = []
        
        # 1. Google News RSS
        try:
            google_hits = self._screen_google_news(name, additional_context)
            all_hits.extend(google_hits)
        except Exception as e:
            logger.error(f"Google News failed for {name}: {e}")
            
        # 1b. Yahoo News RSS
        try:
            yahoo_hits = self._screen_yahoo_news(name, additional_context)
            all_hits.extend(yahoo_hits)
        except Exception as e:
            logger.error(f"Yahoo News failed for {name}: {e}")
            
        # 2. NewsAPI (if key provided)
        if self.newsapi_key:
            try:
                newsapi_hits = self._screen_newsapi(name, additional_context)
                all_hits.extend(newsapi_hits)
            except Exception as e:
                logger.error(f"NewsAPI failed for {name}: {e}")
                
        # 3. Web Scraping (Egyptian sources)
        try:
            scraped_hits = self._screen_egyptian_sites(name, additional_context)
            all_hits.extend(scraped_hits)
        except Exception as e:
            logger.error(f"Web scraping failed for {name}: {e}")

        # 3b. Masrawy (no discoverable direct RSS feed — covered via a
        # site-restricted Google News search instead)
        try:
            masrawy_hits = self._screen_masrawy(name, additional_context)
            all_hits.extend(masrawy_hits)
        except Exception as e:
            logger.error(f"Masrawy failed for {name}: {e}")

        # Analyze and score all hits
        analyzed_results = self._analyze_hits(all_hits, name, additional_context)
        
        # Calculate aggregate risk score
        result = self._calculate_aggregate_risk(analyzed_results, name)
        
        # Cache result
        self._save_to_cache(cache_key, result)
        
        return result
    
    def _screen_google_news(self, name, context=None):
        """
        Screen using Google News RSS (Free, unlimited but may be rate-limited)
        """
        hits = []
        
        # Build query with risk keywords
        risk_keywords_ar = ' OR '.join([
            f'"{kw}"' for kw in list(self.RISK_KEYWORDS_AR.keys())[:10]  # Top 10 keywords
        ])
        risk_keywords_en = ' OR '.join([
            f'"{kw}"' for kw in ['corruption', 'bribery', 'fraud', 'arrested', 'trial', 'sanctions']
        ])
        
        # Try Arabic query
        query_ar = f'"{name}"'
        hits.extend(self._fetch_google_rss(f'{query_ar} ({risk_keywords_ar})', 'ar-EG', 'EG'))
        
        # Try English query
        query_en = f'"{name}"'
        hits.extend(self._fetch_google_rss(f'{query_en} ({risk_keywords_en})', 'en-EG', 'EG'))
        
        # fallback: name only if no hits with keywords
        if not hits:
             hits.extend(self._fetch_google_rss(query_en, 'en-EG', 'EG'))
        
        return hits

    def _screen_yahoo_news(self, name, context=None):
        """
        Screen using Yahoo News RSS (Free)
        """
        hits = []
        # Yahoo News RSS search
        query = quote_plus(f'"{name}" (corruption OR fraud OR arrest OR trial OR sanctions)')
        url = f"https://news.search.yahoo.com/rss/search?p={query}"
        
        try:
            feed = feedparser.parse(url)
            # feedparser doesn't raise on a non-XML/error response (e.g. a
            # provider discontinuing an endpoint and returning an HTML page
            # instead) — it just yields zero entries, indistinguishable from
            # "no hits found" unless status/bozo are checked explicitly.
            if not feed.entries and (feed.get('status', 200) >= 400 or feed.bozo):
                logger.warning(f"Yahoo News RSS fetch returned no usable feed (status={feed.get('status')}): {feed.get('bozo_exception')}")
            for entry in feed.entries[:15]:
                hits.append({
                    'source': 'yahoo-news',
                    'title': entry.title,
                    'link': entry.link,
                    'published': entry.get('published', ''),
                    'summary': entry.get('description', ''),
                    'language': 'en'
                })
        except Exception as e:
            logger.error(f"Yahoo News RSS fetch failed: {e}")

        return hits

    def _screen_masrawy(self, name, context=None):
        """
        Masrawy doesn't publish a discoverable raw RSS feed, so it's covered
        via a site-restricted Google News search instead (same mechanism as
        _screen_google_news, tagged with its own source/credibility).
        """
        hits = []
        query_ar = f'"{name}" site:masrawy.com'
        hits.extend(self._fetch_google_rss(query_ar, 'ar-EG', 'EG', source_tag='masrawy'))
        return hits

    def _fetch_google_rss(self, query, lang, region, source_tag='google-news'):
        """Fetch from Google News RSS"""
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={lang}&gl={region}&ceid={region}:{lang.split('-')[0]}"

        try:
            feed = feedparser.parse(url)
            hits = []

            if not feed.entries and (feed.get('status', 200) >= 400 or feed.bozo):
                logger.warning(f"Google News RSS fetch returned no usable feed for '{query}' "
                                f"(status={feed.get('status')}): {feed.get('bozo_exception')}")

            for entry in feed.entries[:20]:  # Top 20 results
                hits.append({
                    'source': source_tag,
                    'title': entry.title,
                    'link': entry.link,
                    'published': entry.get('published', ''),
                    'summary': entry.get('summary', ''),
                    'language': lang.split('-')[0]
                })

            return hits
        except Exception as e:
            logger.error(f"Google RSS fetch failed: {e}")
            return []
    
    def _screen_newsapi(self, name, context=None):
        """
        Screen using NewsAPI.org
        Documentation: https://newsapi.org/docs/endpoints/everything
        """
        if not self.newsapi_key:
            return []

        if not self.rate_limiter.can_make_request():
            logger.warning(f"NewsAPI.org rate limit reached. {self.rate_limiter.get_remaining_requests()} requests remaining.")
            return []

        hits = []
        base_url = "https://newsapi.org/v2/everything"

        # Search for name, then filter keywords in _analyze_hits
        search_query = f'"{name}"'

        params = {
            'q': search_query,
            'language': 'en',
            'pageSize': 50,  # Max for the free Developer plan
            'sortBy': 'relevancy',
            'apiKey': self.newsapi_key
        }

        try:
            self.rate_limiter.record_request()
            response = requests.get(base_url, params=params, timeout=12) # Slightly longer timeout

            if response.status_code == 401:
                logger.error("NewsAPI.org Unauthorized: Invalid Key or Plan. Disabling NewsAPI.")
                self.newsapi_key = None  # Disable for future requests
                return []

            response.raise_for_status()
            data = response.json()

            if data.get('status') != 'ok':
                logger.error(f"NewsAPI.org error response: {data.get('message')}")
                return []

            # NewsAPI.org results are in the 'articles' key
            for article in data.get('articles', []):
                hits.append({
                    'source': 'newsapi',
                    'title': article.get('title', ''),
                    'link': article.get('url', ''),
                    'published': article.get('publishedAt', ''),
                    'summary': article.get('description', ''),
                    'content': article.get('content', ''),
                    'source_name': (article.get('source') or {}).get('name', ''),
                    'language': 'en'
                })

            return hits
        except Exception as e:
            logger.error(f"NewsAPI.org error: {e}")
            return []
    
    def _screen_egyptian_sites(self, name, context=None):
        """
        Screen major Egyptian news sites via RSS feeds (more reliable than scraping).
        """
        hits = []
        
        # Site configurations with RSS feeds
        sites = [
            {
                'name': 'egypt-independent',
                'rss_url': 'https://www.egyptindependent.com/feed/',
                'enabled': True
            },
            {
                'name': 'al-ahram',
                'rss_url': 'https://english.ahram.org.eg/rss/All.aspx',
                'enabled': True
            },
            {
                # Was 'dailynewssegypt.com' (double 's') — a typo that resolved
                # to a domain serving an empty feed body. Correct domain below.
                'name': 'daily-news-egypt',
                'rss_url': 'https://www.dailynewsegypt.com/feed/',
                'enabled': True
            },
            {
                'name': 'egyptian-streets',
                'rss_url': 'https://egyptianstreets.com/feed/',
                'enabled': True
            },
            {
                'name': 'youm7',
                'rss_url': 'https://www.youm7.com/rss/SectionRss?SectionID=65',
                'language': 'ar',
                'enabled': True
            }
        ]
        
        for site in sites:
            if not site['enabled']:
                continue
                
            try:
                site_hits = self._fetch_rss_hits(site, name)
                hits.extend(site_hits)
            except Exception as e:
                logger.warning(f"Failed to fetch RSS for {site['name']}: {e}")
                
        return hits
    
    def _fetch_rss_hits(self, site_config, name):
        """Fetch and filter hits from a specific site RSS feed"""
        try:
            feed = feedparser.parse(site_config['rss_url'])
            hits = []
            name_lower = name.lower()

            if not feed.entries and (feed.get('status', 200) >= 400 or feed.bozo):
                logger.warning(f"RSS fetch returned no usable feed for {site_config['name']} "
                                f"(status={feed.get('status')}): {feed.get('bozo_exception')}")

            for entry in feed.entries:
                text = f"{entry.title} {entry.get('summary', '')}".lower()
                # Check if name is mentioned in this feed entry
                if name_lower in text:
                    hits.append({
                        'source': site_config['name'],
                        'title': entry.title,
                        'link': entry.link,
                        'published': entry.get('published', ''),
                        'summary': entry.get('summary', ''),
                        'language': site_config.get('language', 'en')
                    })
            return hits
        except Exception as e:
            logger.error(f"RSS error for {site_config['name']}: {e}")
            return []
    
    
    def _analyze_hits(self, hits, name, context=None):
        """
        Analyze and score each hit with advanced filtering.
        """
        analyzed = []
        name_lower = name.lower()
        name_parts = [p for p in name_lower.split() if len(p) > 2]
        
        for hit in hits:
            # Combine text for analysis
            text = f"{hit['title']} {hit.get('summary', '')} {hit.get('content', '')}"
            text_lower = text.lower()
            
            # 1. SMART NAME VERIFICATION
            # Check for exact Match, Variants, or Fuzzy Match
            name_found = False
            
            # Use fuzzy matching for higher recall in adverse media
            from rapidfuzz import fuzz
            
            # 1a. Raw check
            if name_lower in text_lower:
                name_found = True
            
            # 1b. Split and check parts (at least 2 if exists)
            if not name_found:
                matching_parts = sum(1 for part in name_parts if part in text_lower)
                if len(name_parts) >= 2 and matching_parts >= 2:
                    name_found = True
                elif len(name_parts) == 1 and matching_parts == 1:
                    name_found = True
            
            # 1c. Fuzzy check on title or summary snippets
            if not name_found:
                # Check if any part of the text has a high fuzzy similarity to the name
                # We split text into small chunks to avoid diluting the ratio
                chunks = re.split(r'[,.\s]+', text_lower)
                # Check sliding window of name parts length
                n_len = len(name_parts)
                for i in range(len(chunks) - n_len + 1):
                    window = ' '.join(chunks[i:i+n_len])
                    if fuzz.ratio(name_lower, window) > 85:
                        name_found = True
                        break
            
            if not name_found:
                continue  # Skip this hit
                
            # 2. KEYWORD SCORING
            risk_score = 0
            found_keywords = []
            
            # Arabic keywords
            for keyword, weight in self.RISK_KEYWORDS_AR.items():
                if keyword in text:
                    risk_score += weight
                    found_keywords.append(keyword)
                    
            # English keywords
            for keyword, weight in self.RISK_KEYWORDS_EN.items():
                if keyword in text_lower:
                    risk_score += weight
                    found_keywords.append(keyword)
                    
            # Skip if no risk keywords found
            if risk_score == 0:
                continue
                
            # 3. SOURCE CREDIBILITY WEIGHT
            source = hit.get('source', 'unknown')
            credibility = self.SOURCE_CREDIBILITY.get(source, 0.5)
            
            # 4. DATE RELEVANCE (recent articles weighted higher)
            date_weight = self._calculate_date_weight(hit.get('published'))
            
            # 5. SENTIMENT ANALYSIS (if TextBlob available)
            sentiment_score = 0
            if TextBlob:
                try:
                    blob = TextBlob(text)
                    sentiment = blob.sentiment.polarity  # -1 to 1
                    # Negative sentiment increases risk
                    if sentiment < -0.2:
                        sentiment_score = 5
                except Exception as e:
                    logger.debug(f"[SWALLOWED] sentiment score adjustment failed: {e}")
                    
            # 6. CONTEXT MATCHING (if provided)
            context_bonus = 0
            if context:
                if context.get('occupation') and context['occupation'].lower() in text_lower:
                    context_bonus += 5
                if context.get('nationality') and context['nationality'].lower() in text_lower:
                    context_bonus += 3
                    
            # Calculate final hit score
            # Formula: (risk_score * credibility * date_weight) + sentiment + context
            final_score = (risk_score * credibility * date_weight) + sentiment_score + context_bonus
            
            analyzed.append({
                **hit,
                'risk_score': round(final_score, 2),
                'risk_keywords': found_keywords,
                'raw_keyword_score': risk_score,
                'credibility': credibility,
                'date_weight': date_weight,
                'sentiment': sentiment_score,
                'context_bonus': context_bonus
            })
            
        # Sort by risk score
        analyzed.sort(key=lambda x: x['risk_score'], reverse=True)
        
        return analyzed
    
    def _calculate_date_weight(self, published_date):
        """
        Calculate recency weight: recent articles weighted higher.
        - Last 7 days: 1.0
        - Last 30 days: 0.8
        - Last 90 days: 0.6
        - Last 365 days: 0.4
        - Older: 0.2
        """
        if not published_date:
            return 0.5  # Unknown date: medium weight
            
        try:
            # Parse date (handle multiple formats)
            if isinstance(published_date, str):
                # Try ISO format first
                try:
                    pub_date = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
                except:
                    # Try other common formats
                    for fmt in ['%a, %d %b %Y %H:%M:%S %Z', '%Y-%m-%d', '%d %b %Y']:
                        try:
                            pub_date = datetime.strptime(published_date, fmt)
                            break
                        except:
                            continue
                    else:
                        return 0.5  # Parsing failed
            else:
                pub_date = published_date
                
            days_ago = (datetime.now() - pub_date).days
            
            if days_ago <= 7:
                return 1.0
            elif days_ago <= 30:
                return 0.95
            elif days_ago <= 90:
                return 0.90
            elif days_ago <= 365:
                return 0.80
            else:
                return 0.90  # Historical AM retains high relevance for AML
                
        except Exception as e:
            logger.debug(f"Date parsing error: {e}")
            return 0.5
    
    def _calculate_aggregate_risk(self, analyzed_hits, name):
        """
        Calculate overall risk assessment from all hits.
        """
        if not analyzed_hits:
            return {
                'person_name': name,
                'risk_level': 'CLEAR',
                'risk_score': 0,
                'total_hits': 0,
                'high_risk_hits': 0,
                'medium_risk_hits': 0,
                'low_risk_hits': 0,
                'top_hits': [],
                'recommendation': 'No adverse media found. Proceed with standard due diligence.',
                'screened_at': datetime.now().isoformat()
            }
            
        # Categorize hits by risk level
        high_risk = [h for h in analyzed_hits if h['risk_score'] >= 50]
        medium_risk = [h for h in analyzed_hits if 20 <= h['risk_score'] < 50]
        low_risk = [h for h in analyzed_hits if h['risk_score'] < 20]
        
        # Calculate aggregate score
        # Use top 3 highest scores with diminishing weight
        top_scores = sorted([h['risk_score'] for h in analyzed_hits], reverse=True)[:3]
        weights = [1.0, 0.6, 0.3]
        aggregate_score = sum(score * weight for score, weight in zip(top_scores, weights))
        
        # Normalize to 0-100 scale
        aggregate_score = min(100, aggregate_score)
        
        # Determine risk level
        if aggregate_score >= 70 or len(high_risk) >= 2:
            risk_level = 'HIGH'
            recommendation = 'Enhanced Due Diligence (EDD) required. Multiple credible adverse media hits detected.'
        elif aggregate_score >= 40 or len(high_risk) >= 1:
            risk_level = 'MEDIUM'
            recommendation = 'Additional investigation recommended. Review adverse media details and consider EDD.'
        elif aggregate_score >= 20:
            risk_level = 'LOW'
            recommendation = 'Standard Due Diligence sufficient. Monitor for new adverse media.'
        else:
            risk_level = 'CLEAR'
            recommendation = 'No significant adverse media. Proceed with onboarding.'
            
        return {
            'person_name': name,
            'risk_level': risk_level,
            'risk_score': round(aggregate_score, 2),
            'total_hits': len(analyzed_hits),
            'high_risk_hits': len(high_risk),
            'medium_risk_hits': len(medium_risk),
            'low_risk_hits': len(low_risk),
            'top_hits': analyzed_hits[:5],  # Top 5 for review
            'all_hits': analyzed_hits,  # Full list
            'recommendation': recommendation,
            'screened_at': datetime.now().isoformat(),
            'sources_checked': list(set(h['source'] for h in analyzed_hits))
        }
    
    def _generate_cache_key(self, name, context):
        """Generate unique cache key for search"""
        key_data = f"{name}_{json.dumps(context or {}, sort_keys=True)}"
        return f"adverse_media:{hashlib.md5(key_data.encode()).hexdigest()}"
    
    def _get_from_cache(self, key):
        """Get from Redis cache if available"""
        if not self.redis:
            return None
            
        try:
            cached = self.redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.debug(f"Cache read error: {e}")
            
        return None
    
    def _save_to_cache(self, key, data):
        """Save to Redis cache"""
        if not self.redis:
            return
            
        try:
            self.redis.setex(key, self.cache_ttl, json.dumps(data))
        except Exception as e:
            logger.debug(f"Cache write error: {e}")


# ============================================
# USAGE EXAMPLES
# ============================================

if __name__ == "__main__":
    # Example 1: Basic usage (Google News only)
    screener = AdverseMediaScreener()
    result = screener.screen_person("محمد أحمد")
    print(json.dumps(result, indent=2, ensure_ascii=False))
