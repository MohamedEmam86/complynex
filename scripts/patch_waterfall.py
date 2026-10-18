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

import sys
import re

with open('c:/Users/Dina/Downloads/ComplyNex_CMS/screening/waterfall_scraper.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern_classes = r'# ============================================================================\n# SOURCE 1: TheNewsAPI\n# ============================================================================\n.*?class TheNewsAPISource.*?# ============================================================================\n# SOURCE 4: Direct RSS Feeds'

replacement_classes = '''# ============================================================================
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
                    q=query,
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
        try:
            encoded_name = quote_plus(query)
            url = f"https://news.google.com/rss/search?q={encoded_name}&hl=ar&gl=EG&ceid=EG:ar"
            logger.info(f"[GoogleNewsRSS] URL: {url}")
            
            loop = asyncio.get_event_loop()
            def do_fetch():
                resp = requests.get(url, headers={'User-Agent': 'ComplyNex-CMS/1.0'}, timeout=self.timeout)
                resp.raise_for_status()
                return feedparser.parse(resp.content)
                
            feed = await loop.run_in_executor(None, do_fetch)
            articles = []
            for entry in feed.entries:
                articles.append(self.standardize_article(entry))
            logger.info(f"[GoogleNewsRSS] Found {len(articles)} articles")
            return articles
        except Exception as e:
            logger.error(f"[GoogleNewsRSS] Failed: {str(e)}")
            return []
            
    def standardize_article(self, entry: dict) -> Dict:
        pub_date = None
        if 'published_parsed' in entry and entry.published_parsed:
            pub_date = datetime(*entry.published_parsed[:6])
        return {
            'title': entry.get('title', ''),
            'description': entry.get('description', entry.get('summary', '')),
            'url': entry.get('link', ''),
            'published_at': pub_date,
            'source': entry.get('source', {}).get('title', 'Google News'),
            'language': 'ar',
            'relevance_score': 0.6,
            'snippet': entry.get('summary', '')[:200] if entry.get('summary') else ''
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
                resp = requests.get(url, headers={'User-Agent': 'ComplyNex-CMS/1.0'}, timeout=self.timeout)
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
            
    def standardize_article(self, entry: dict) -> Dict:
        pub_date = None
        if 'published_parsed' in entry and entry.published_parsed:
            pub_date = datetime(*entry.published_parsed[:6])
        return {
            'title': entry.get('title', ''),
            'description': entry.get('description', entry.get('summary', '')),
            'url': entry.get('link', ''),
            'published_at': pub_date,
            'source': 'Yahoo Finance',
            'language': 'en',
            'relevance_score': 0.6,
            'snippet': entry.get('summary', '')[:200] if entry.get('summary') else ''
        }


# ============================================================================
# SOURCE 4: Direct RSS Feeds'''

new_content = re.sub(pattern_classes, replacement_classes, content, flags=re.DOTALL)

pattern_init = r'self\.sources = \[\].*?if config\[\'rss_feeds\'\]\[\'enabled\'\]:\s*self\.sources\.append\(RSSFeedSource\(config\[\'rss_feeds\'\]\)\)'

replacement_init = '''self.sources = []
        
        if config.get('newsapi', {}).get('enabled'):
            self.sources.append(NewsAPISource(config['newsapi']))
        
        if config.get('google_news', {}).get('enabled'):
            self.sources.append(GoogleNewsRSSSource(config['google_news']))
            
        if config.get('yahoo_finance', {}).get('enabled'):
            self.sources.append(YahooFinanceRSSSource(config['yahoo_finance']))
        
        if config.get('rss_feeds', {}).get('enabled'):
            self.sources.append(RSSFeedSource(config['rss_feeds']))'''

new_content = re.sub(pattern_init, replacement_init, new_content, flags=re.DOTALL)

if new_content == content:
    print('Error: Substituted nothing!')
    sys.exit(1)

with open('c:/Users/Dina/Downloads/ComplyNex_CMS/screening/waterfall_scraper.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('Successfully patched waterfall_scraper.py')
