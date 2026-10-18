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
API Configuration for Screening Module
Manages external API keys and rate limiting.
"""

import os
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class APIConfig:
    """Central configuration for external APIs"""
    
    # Import config manager
    try:
        from .config_manager import ConfigManager
        # Secrets belong in the environment, not in a DB table readable by
        # any admin screen (2026-07-21, screening Rec #8): env wins, DB is
        # only a legacy fallback.
        NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY') or ConfigManager.get_newsapi_key() or ''
        NEWSAPI_ENABLED = ConfigManager.is_adverse_media_enabled()
        NEWSAPI_RATE_LIMIT = int(ConfigManager.get_config('newsapi_rate_limit', 100))
    except (ImportError, Exception):
        # Fallback to environment variables
        NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY', '')
        NEWSAPI_ENABLED = os.environ.get('NEWSAPI_ENABLED', 'false').lower() == 'true'
        NEWSAPI_RATE_LIMIT = int(os.environ.get('NEWSAPI_RATE_LIMIT', 100))
    
    @classmethod
    def is_newsapi_enabled(cls):
        """Check if NewsAPI is properly configured"""
        return cls.NEWSAPI_ENABLED and bool(cls.NEWSAPI_KEY)
    
    @classmethod
    def get_newsapi_key(cls):
        """Get NewsAPI key (returns None if not configured)"""
        if cls.is_newsapi_enabled():
            return cls.NEWSAPI_KEY
        return None


class RateLimiter:
    """Simple rate limiter for API calls"""
    
    def __init__(self, max_calls, time_window_seconds):
        self.max_calls = max_calls
        self.time_window = time_window_seconds
        self.calls = []
        
    def can_make_request(self):
        """Check if we can make another API call"""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.time_window)
        
        # Remove old calls
        self.calls = [call_time for call_time in self.calls if call_time > cutoff]
        
        return len(self.calls) < self.max_calls
    
    def record_request(self):
        """Record that an API call was made"""
        self.calls.append(datetime.now())
    
    def get_remaining_requests(self):
        """Get number of requests remaining in current window"""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.time_window)
        self.calls = [call_time for call_time in self.calls if call_time > cutoff]
        return self.max_calls - len(self.calls)


# Global rate limiter instance
NEWSAPI_RATE_LIMITER = RateLimiter(
    max_calls=APIConfig.NEWSAPI_RATE_LIMIT,
    time_window_seconds=86400  # 24 hours
)
