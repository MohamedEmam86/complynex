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
Enhanced Adverse Media Screening with NewsAPI Integration
==========================================================

Full integration with NewsAPI.org for Egyptian adverse media screening.
Includes intelligent name extraction from articles.

API Key: Loaded from database configuration (screening_config table)
Correct Key: 7ex9ooE1pDM2BwUoRfg0NmOPwe4J0RdbHP64XyZE
Rate Limit: 100 requests/day (free tier)

Features:
- Smart name extraction from articles
- Context-aware matching
- Risk scoring with entity verification
- Caching to optimize API usage
- Integration with screening results database

"""

import requests
import logging
from datetime import datetime, timedelta
import hashlib
import json
import re

logger = logging.getLogger(__name__)

try:
    import redis
except ImportError:
    redis = None

try:
    from textblob import TextBlob
except ImportError:
    TextBlob = None


class EnhancedAdverseMediaScreener:
    """
    Production-ready adverse media screener with NewsAPI integration.
    """
    
    # Risk keywords with weights
    RISK_KEYWORDS_AR = {
        # High Risk (Weight: 10)
        'فساد': 10, 'رشوة': 10, 'غسيل أموال': 10, 'غسل أموال': 10,
        'احتيال': 10, 'تزوير': 10, 'اختلاس': 10, 'تهريب': 10,
        'إرهاب': 10, 'تمويل إرهاب': 10, 'منظمة إجرامية': 10,
        'اتجار': 10, 'مخدرات': 9,
        # Medium Risk (Weight: 7)
        'اعتقال': 7, 'سجن': 7, 'محاكمة': 7, 'اتهام': 7,
        'تحقيق جنائي': 7, 'قبض': 7,
        # Sanctions (Weight: 10)
        'عقوبات': 10, 'حظر': 10, 'قائمة سوداء': 10,
    }
    
    RISK_KEYWORDS_EN = {
        # High Risk
        'corruption': 10, 'bribery': 10, 'money laundering': 10,
        'fraud': 10, 'forgery': 10, 'embezzlement': 10, 'smuggling': 10,
        'terrorism': 10, 'terrorist financing': 10, 'organized crime': 10,
        'trafficking': 10, 'narcotics': 9,
        # Medium Risk
        'arrested': 7, 'imprisoned': 7, 'trial': 7, 'accused': 7,
        'criminal investigation': 7, 'detained': 7,
        # Sanctions
        'sanctions': 10, 'blacklisted': 10, 'watchlist': 10,
        'wanted': 9
    }
    
    def __init__(self, newsapi_key, db_config=None, redis_client=None):
        """
        Initialize adverse media screener.
        
        Args:
            newsapi_key: NewsAPI.org API key
            db_config: Database configuration for storing results
            redis_client: Optional Redis client for caching
        """
        self.newsapi_key = newsapi_key
        self.db_config = db_config
        self.redis = redis_client
        self.session = requests.Session()
        
    def screen_person(self, name, context=None, save_to_db=True):
        """
        Screen a person against adverse media using NewsAPI.
        
        Args:
            name: Person's name (Arabic or English)
            context: Optional dict with additional context (dob, nationality, occupation)
            save_to_db: Whether to save results to database
            
        Returns:
            Dict with screening results
        """
        # Check cache first
        cache_key = self._generate_cache_key(name, context)
        cached = self._get_from_cache(cache_key)
        if cached:
            logger.info(f"Cache hit for adverse media: {name}")
            return cached
            
        logger.info(f"Screening adverse media for: {name}")
        
        # Build search query with risk keywords
        query = self._build_search_query(name)
        
        # Search NewsAPI
        articles = self._search_newsapi(query)
        
        if not articles:
            result = self._create_clear_result(name)
        else:
            # Extract and verify names from articles
            verified_hits = self._extract_and_verify_names(articles, name, context)
            
            # Calculate risk
            result = self._calculate_risk(verified_hits, name, context)
            
        # Cache result
        self._save_to_cache(cache_key, result)
        
        # Save to database if requested
        if save_to_db and self.db_config:
            self._save_to_database(result)
            
        return result
        
    def _build_search_query(self, name):
        """
        Build optimized search query for NewsAPI.
        
        Combines person name with risk keywords.
        """
        # Top risk keywords for query
        risk_keywords = [
            'corruption', 'bribery', 'fraud', 'arrested',
            'sanctions', 'money laundering'
        ]
        
        # Build query: "Name" AND (keyword1 OR keyword2 OR ...)
        keywords_part = ' OR '.join(risk_keywords)
        query = f'"{name}" AND ({keywords_part})'
        
        # Limit to Egypt for Egyptian names
        if self._is_arabic(name):
            query += ' AND Egypt'
            
        return query
        
    def _search_newsapi(self, query):
        """
        Search NewsAPI.org with the given query.
        
        Returns:
            List of articles
        """
        url = 'https://newsapi.org/v2/everything'
        
        # Date range: last 2 years
        from_date = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
        
        params = {
            'q': query,
            'apiKey': self.newsapi_key,
            'language': 'en',
            'sortBy': 'relevancy',
            'from': from_date,
            'pageSize': 20  # Max results per request
        }
        
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('status') == 'ok':
                articles = data.get('articles', [])
                logger.info(f"Found {len(articles)} articles from NewsAPI")
                return articles
            else:
                logger.error(f"NewsAPI error: {data.get('message', 'Unknown error')}")
                return []
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to query NewsAPI: {e}")
            return []
            
    def _extract_and_verify_names(self, articles, target_name, context):
        """
        Extract names from articles and verify they match target person.
        
        This is critical to avoid false positives.
        """
        verified_hits = []
        
        for article in articles:
            # Combine title and description for analysis
            title = article.get('title', '')
            description = article.get('description', '')
            content = f"{title}. {description}"
            
            # Check if target name appears in article
            if not self._name_appears_in_text(target_name, content):
                continue
                
            # Extract all names from article
            extracted_names = self._extract_names_from_text(content)
            
            # Check if target name is in extracted names
            name_match = False
            for extracted_name in extracted_names:
                if self._names_match(target_name, extracted_name):
                    name_match = True
                    break
                    
            if not name_match:
                # Name appears in text but not prominently - low confidence
                continue
                
            # Additional context verification if provided
            context_score = 0
            if context:
                if context.get('occupation') and context['occupation'].lower() in content.lower():
                    context_score += 5
                if context.get('nationality') and context['nationality'].lower() in content.lower():
                    context_score += 3
                    
            # Calculate risk score for this article
            risk_score = self._calculate_article_risk_score(content, article)
            risk_score += context_score
            
            if risk_score > 0:  # Only include articles with risk indicators
                verified_hits.append({
                    'source': article.get('source', {}).get('name', 'Unknown'),
                    'title': title,
                    'description': description,
                    'url': article.get('url'),
                    'published_at': article.get('publishedAt'),
                    'risk_score': risk_score,
                    'context_score': context_score,
                    'matched_keywords': self._get_matched_keywords(content)
                })
                
        # Sort by risk score
        verified_hits.sort(key=lambda x: x['risk_score'], reverse=True)
        
        return verified_hits
        
    def _extract_names_from_text(self, text):
        """
        Extract person names from text.
        
        Uses simple heuristics (capitalized words).
        For production, consider using NER models.
        """
        # Simple extraction: find capitalized word sequences
        # Example: "John Smith was arrested" -> ["John Smith"]
        
        names = []
        
        # Pattern: 2-3 consecutive capitalized words
        pattern = r'\b([A-Z][a-z]+(%s: [A-Z][a-z]+){1,2})\b'
        matches = re.findall(pattern, text)
        
        for match in matches:
            # Filter out common non-names
            if match not in ['The', 'This', 'That', 'These', 'Those', 'And', 'But']:
                names.append(match)
                
        return list(set(names))  # Deduplicate
        
    def _name_appears_in_text(self, name, text):
        """Check if name appears in text (case-insensitive)"""
        return name.lower() in text.lower()
        
    def _names_match(self, name1, name2, threshold=0.8):
        """
        Check if two names match using fuzzy matching.
        """
        from rapidfuzz import fuzz
        
        # Exact match
        if name1.lower() == name2.lower():
            return True
            
        # Fuzzy match
        ratio = fuzz.ratio(name1.lower(), name2.lower()) / 100.0
        return ratio >= threshold
        
    def _calculate_article_risk_score(self, content, article):
        """
        Calculate risk score for a single article.
        """
        score = 0
        content_lower = content.lower()
        
        # Check for risk keywords
        for keyword, weight in self.RISK_KEYWORDS_EN.items():
            if keyword in content_lower:
                score += weight
                
        # Date recency bonus
        published_at = article.get('publishedAt')
        if published_at:
            try:
                pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                days_ago = (datetime.now(pub_date.tzinfo) - pub_date).days
                
                if days_ago <= 30:
                    score *= 1.5
                elif days_ago <= 90:
                    score *= 1.2
                elif days_ago <= 365:
                    score *= 1.0
                else:
                    score *= 0.7
            except Exception as e:
                logger.debug(f"[SWALLOWED] recency score adjustment failed: {e}")
                
        return round(score, 2)
        
    def _get_matched_keywords(self, content):
        """Get list of risk keywords that appear in content"""
        matched = []
        content_lower = content.lower()
        
        for keyword in self.RISK_KEYWORDS_EN.keys():
            if keyword in content_lower:
                matched.append(keyword)
                
        return matched
        
    def _calculate_risk(self, hits, name, context):
        """
        Calculate overall risk assessment from hits.
        """
        if not hits:
            return self._create_clear_result(name)
            
        # Categorize hits
        high_risk = [h for h in hits if h['risk_score'] >= 50]
        medium_risk = [h for h in hits if 20 <= h['risk_score'] < 50]
        low_risk = [h for h in hits if h['risk_score'] < 20]
        
        # Calculate aggregate score (top 3 hits with diminishing weight)
        top_scores = sorted([h['risk_score'] for h in hits], reverse=True)[:3]
        weights = [1.0, 0.6, 0.3]
        aggregate_score = sum(score * weight for score, weight in zip(top_scores, weights))
        aggregate_score = min(100, aggregate_score)
        
        # Determine risk level
        if aggregate_score >= 70 or len(high_risk) >= 2:
            risk_level = 'HIGH'
            recommendation = '🚨 Enhanced Due Diligence (EDD) required. Multiple credible adverse media hits.'
        elif aggregate_score >= 40 or len(high_risk) >= 1:
            risk_level = 'MEDIUM'
            recommendation = '⚠️ Additional investigation recommended. Review adverse media details.'
        elif aggregate_score >= 20:
            risk_level = 'LOW'
            recommendation = '📋 Standard Due Diligence sufficient. Monitor for new adverse media.'
        else:
            risk_level = 'CLEAR'
            recommendation = '✅ No significant adverse media. Proceed with onboarding.'
            
        return {
            'person_name': name,
            'risk_level': risk_level,
            'risk_score': round(aggregate_score, 2),
            'total_hits': len(hits),
            'high_risk_hits': len(high_risk),
            'medium_risk_hits': len(medium_risk),
            'low_risk_hits': len(low_risk),
            'top_hits': hits[:5],  # Top 5 for display
            'all_hits': hits,
            'recommendation': recommendation,
            'screened_at': datetime.now().isoformat(),
            'sources_checked': ['NewsAPI']
        }
        
    def _create_clear_result(self, name):
        """Create result for clear/no hits case"""
        return {
            'person_name': name,
            'risk_level': 'CLEAR',
            'risk_score': 0,
            'total_hits': 0,
            'high_risk_hits': 0,
            'medium_risk_hits': 0,
            'low_risk_hits': 0,
            'top_hits': [],
            'all_hits': [],
            'recommendation': '✅ No adverse media found. Proceed with standard due diligence.',
            'screened_at': datetime.now().isoformat(),
            'sources_checked': ['NewsAPI']
        }
        
    def _is_arabic(self, text):
        """Check if text contains Arabic characters"""
        return bool(re.search(r'[\u0600-\u06FF]', text))
        
    def _generate_cache_key(self, name, context):
        """Generate cache key"""
        key_data = f"{name}_{json.dumps(context or {}, sort_keys=True)}"
        return f"adverse_media:{hashlib.md5(key_data.encode()).hexdigest()}"
        
    def _get_from_cache(self, key):
        """Get from Redis cache"""
        if not self.redis:
            return None
            
        try:
            cached = self.redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.debug(f"Cache read error: {e}")
            
        return None
        
    def _save_to_cache(self, key, data, ttl=86400):
        """Save to Redis cache (24 hours default)"""
        if not self.redis:
            return
            
        try:
            self.redis.setex(key, ttl, json.dumps(data, default=str))
        except Exception as e:
            logger.debug(f"Cache write error: {e}")
            
    def _save_to_database(self, result):
        """Save screening result to database"""
        if not self.db_config:
            return
            
        import sqlite3
        try:
            import psycopg2
        except ImportError:
            psycopg2 = None
            
        try:
            # Connect to database
            if isinstance(self.db_config, dict) and 'database' in self.db_config:
                conn = db_pool.checkout_connection()
                placeholder = '%s'
            elif psycopg2:
                conn = psycopg2.connect(**self.db_config)
                placeholder = '%s'
            else:
                return
                
            cursor = conn.cursor()
            
            # Insert into adverse_media_results table
            cursor.execute(f"""
                INSERT INTO adverse_media_results (
                    person_name, risk_level, risk_score,
                    total_hits, high_risk_hits, medium_risk_hits, low_risk_hits,
                    sources_checked, top_hits, all_hits,
                    recommendation, screened_at
                ) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, (
                result['person_name'],
                result['risk_level'],
                result['risk_score'],
                result['total_hits'],
                result['high_risk_hits'],
                result['medium_risk_hits'],
                result['low_risk_hits'],
                json.dumps(result['sources_checked']),
                json.dumps(result['top_hits'], default=str),
                json.dumps(result['all_hits'], default=str),
                result['recommendation'],
                result['screened_at']
            ))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Saved adverse media result to database for {result['person_name']}")
            
        except Exception as e:
            logger.error(f"Failed to save adverse media result to database: {e}")


def create_adverse_media_screener(newsapi_key=None, db_config=None, redis_client=None):
    """
    Create adverse media screener with automatic config loading.
    
    Args:
        newsapi_key: NewsAPI key (if None, loads from config)
        db_config: Database configuration
        redis_client: Redis client for caching
    
    Returns:
        EnhancedAdverseMediaScreener instance
    """
    if not newsapi_key:
        # Load from configuration (database > environment > error)
        try:
            from .config_manager import ConfigManager
            newsapi_key = ConfigManager.get_newsapi_key()
        except ImportError:
            logger.warning("ConfigManager not available, trying environment variable")
            import os
            newsapi_key = os.getenv('NEWSAPI_KEY')
        
        if not newsapi_key:
            raise ValueError(
                "NewsAPI key not configured. Please:\n"
                "1. Run: python scripts/set_newsapi_key.py, OR\n"
                "2. Set environment variable: NEWSAPI_KEY=your_key_here"
            )
    
    logger.info(f"Initializing adverse media screener with API key: {newsapi_key[:8]}...{newsapi_key[-4:]}")
    return EnhancedAdverseMediaScreener(newsapi_key, db_config, redis_client)


if __name__ == "__main__":
    # Test the screener
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Enhanced Adverse Media Screener...")
    
    screener = create_adverse_media_screener()
    
    # Test with a name
    test_name = "Mohamed Ali"
    print(f"\nScreening: {test_name}")
    
    result = screener.screen_person(test_name, save_to_db=False)
    
    print(f"\nRisk Level: {result['risk_level']}")
    print(f"Risk Score: {result['risk_score']}")
    print(f"Total Hits: {result['total_hits']}")
    print(f"Recommendation: {result['recommendation']}")
    
    if result['top_hits']:
        print("\nTop Hits:")
        for hit in result['top_hits'][:3]:
            print(f"  - {hit['title']} (Score: {hit['risk_score']})")
