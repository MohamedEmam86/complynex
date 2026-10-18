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

import os

def _get_newsapi_key():
    # screening_config (Postgres) is the source of truth — same precedence as
    # ConfigManager.get_config() (DB > env > default). Previously this read
    # os.environ first and only fell back to a separate raw-psycopg2 DB query
    # if the env var was unset, the opposite precedence of ConfigManager —
    # an admin updating the key via screening_config would have been silently
    # ignored as long as the (possibly stale) .env value was still set.
    from screening.config_manager import ConfigManager
    return ConfigManager.get_newsapi_key() or os.environ.get('NEWSAPI_KEY', '')

def _is_newsapi_enabled():
    from screening.config_manager import ConfigManager
    return ConfigManager.is_adverse_media_enabled()

ADVERSE_MEDIA_CONFIG = {
    'newsapi': {
        'newsapi_key': _get_newsapi_key(),
        'newsapi_language': 'ar,en',
        'newsapi_page_size': 20,
        'newsapi_timeout': 8,
        'enabled': _is_newsapi_enabled(),
        'priority': 1
    },
    'google_news': {
        'enabled': True,
        'priority': 2,
        'timeout': 8
    },
    'yahoo_finance': {
        'enabled': True,
        'priority': 3,
        'timeout': 8
    },
    'mediastack': {
        'api_key': '7cc8bc68954fe347726d3d41377962a4',
        'base_url': 'http://api.mediastack.com/v1/news',
        'rate_limit': 500,
        'timeout': 10,
        'priority': 3,
        'enabled': False
    },
    'rss_feeds': {
        'enabled': True,
        'priority': 4,
        'timeout': 15,
        'sources': {
            'almasry_alyoum': {
                'name': 'Al-Masry Al-Youm',
                'url': 'https://www.almasryalyoum.com/rss/rss.xml',
                'enabled': False,  # Cloudflare protected
                'language': 'ar',
                'category': 'general'
            },
            'youm7': {
                'name': 'Youm7',
                'url': 'https://www.youm7.com/rss/SectionRss?SectionID=1',
                'language': 'ar',
                'category': 'general'
            },
            'ahram': {
                'name': 'Al-Ahram',
                'url': 'https://gate.ahram.org.eg/rss/RssFeed.aspx',
                'enabled': False,  # Cloudflare protected
                'language': 'ar',
                'category': 'general'
            },
            'dostor': {
                'name': 'Al-Dostor',
                'url': 'https://www.dostor.org/rss',
                'enabled': False,  # Cloudflare protected
                'language': 'ar',
                'category': 'general'
            },
            'shorouk': {
                'name': 'Al-Shorouk',
                'url': 'https://www.shorouknews.com/rss',
                'language': 'ar',
                'category': 'general'
            },
            'mada_masr': {
                'name': 'Mada Masr',
                'url': 'https://www.madamasr.com/en/feed/',
                'language': 'en',
                'category': 'investigative'
            },
            'egypt_independent': {
                'name': 'Egypt Independent',
                'url': 'https://www.egyptindependent.com/feed/',
                'language': 'en',
                'category': 'general'
            },
            'daily_news_egypt': {
                'name': 'Daily News Egypt',
                'url': 'https://dailynewssegypt.com/feed/',
                'enabled': False,  # Timeout
                'language': 'en',
                'category': 'business'
            },
            'enterprise': {
                'name': 'Enterprise',
                'url': 'https://enterprise.press/feed/',
                'enabled': False,  # Timeout
                'language': 'en',
                'category': 'business'
            },
            'egypt_today_business': {
                'name': 'Egypt Today Business',
                'url': 'https://www.egypttoday.com/RSS/24',
                'enabled': False,  # Cloudflare protected
                'language': 'en',
                'category': 'business'
            }
        }
    },
    'cache': {
        'enabled': True,
        'ttl': 3600,
        'redis_key_prefix': 'adverse_media:'
    },
    'search': {
        # Per-source deadline: a slow source is dropped, the rest still count.
        # Total budget must exceed it. See waterfall_scraper.screen_person().
        'per_source_timeout': 25,
        'total_timeout': 40,
        'lookback_days': 730,
        'max_results_per_source': 100,
        'languages': ['ar', 'en'],
        'countries': ['eg'],
        'keywords': [
            # Financial Crime
            'fraud', 'embezzlement', 'bribery', 'corruption', 'money laundering',
            'financial crime', 'tax evasion', 'ponzi scheme', 'insider trading',
            'market manipulation', 'asset misappropriation', 'kickback',
            'fictitious invoices', 'shell company', 'offshore accounts',
            'illicit enrichment', 'unexplained wealth', 'suspicious transaction',
            # Legal/Criminal
            'arrested', 'indicted', 'convicted', 'sentenced', 'imprisoned',
            'criminal charges', 'prosecution', 'fugitive', 'warrant',
            'confiscation', 'asset seizure', 'forfeiture', 'extradition',
            'detained', 'wanted', 'guilty', 'verdict',
            # Sanctions/Compliance
            'sanctions', 'blacklisted', 'OFAC', 'SDN list', 'designated',
            'banned', 'debarred', 'watchlist', 'terrorism financing',
            'proliferation financing', 'UN sanctions',
            # Governance/Ethics
            'scandal', 'misconduct', 'abuse of power', 'conflict of interest',
            'nepotism', 'cronyism', 'whistleblower', 'leaked documents',
            'investigation', 'probe', 'inquiry', 'allegation',
            # Terrorism/Security
            'terrorism', 'extremism', 'militant', 'jihadist', 'radicalization',
            'arms trafficking', 'drug trafficking', 'human trafficking',
            'organized crime', 'mafia', 'cartel',
            # Arabic - Financial Crime
            'احتيال', 'اختلاس', 'رشوة', 'فساد', 'غسل أموال',
            'تهرب ضريبي', 'تزوير', 'نصب', 'إثراء غير مشروع',
            'أموال مشبوهة', 'شركات وهمية', 'فواتير وهمية',
            # Arabic - Legal/Criminal
            'اعتقال', 'محاكمة', 'إدانة', 'سجن', 'مذكرة توقيف',
            'تحقيق', 'ملاحقة قضائية', 'مطلوب', 'مصادرة', 'حكم',
            'قضية جنائية', 'اتهام', 'حبس', 'توقيف',
            # Arabic - Sanctions/Compliance
            'عقوبات', 'قائمة سوداء', 'تمويل الإرهاب', 'تمويل إرهاب',
            'قيود مالية', 'تجميد أصول',
            # Arabic - Governance
            'فضيحة', 'إساءة سلطة', 'تضارب مصالح', 'محسوبية',
            'وثائق مسربة', 'مخالفات', 'انتهاكات',
            # Arabic - Terrorism/Security
            'إرهاب', 'تطرف', 'مسلح', 'جهادي', 'تجنيد',
            'اتجار بالسلاح', 'اتجار بالمخدرات', 'اتجار بالبشر',
            'جريمة منظمة'
        ]
    }
}
