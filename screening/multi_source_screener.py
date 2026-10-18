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
Multi-Source Screener
======================
Orchestrates screening across multiple engines and data sources.
Acts as the unified entry point for all screening operations.

Sources:
1. Local Watchlist (ComplyNexScreeningEngine) - Sanctions, PEPs, Internal Lists
2. Adverse Media (AdverseMediaScreener) - Google News, etc.
3. External APIs (Future) - Setup for real-time checks against UN, OFAC, etc. directly if needed.

Usage:
    screener = MultiSourceScreener(db_config, cache_config)
    result = screener.screen("John Doe", country="US")
"""
import logging
from .complynex_engine import ComplyNexScreeningEngine
from .adverse_media import AdverseMediaScreener

logger = logging.getLogger(__name__)

class MultiSourceScreener:
    def __init__(self, db_config, cache_config=None, ml_threshold=0.60):
        """
        Initialize the multi-source screener.
        
        Args:
            db_config: Database configuration
            cache_config: Redis cache configuration
            ml_threshold: Threshold for ML scoring (default 0.60)
        """
        self.db_config = db_config
        self.cache_config = cache_config
        
        # Initialize engines
        self.local_engine = ComplyNexScreeningEngine(
            db_config, 
            cache_config,
            ml_threshold=ml_threshold
        )
        
        # Adverse media is currently integrated in local_engine, but we expose it here
        # for potential direct usage or configuration.
        self.media_screener = self.local_engine.media_screener
        
    def screen_person(self, name, date_of_birth=None, nationality=None, entity_type='INDIVIDUAL', **kwargs):
        """
        Perform screening against all configured sources.
        
        Args:
            name (str): Name to screen
            date_of_birth (date/str): DOB
            nationality (str): Country ISO code or name
            entity_type (str): INDIVIDUAL or ENTITY
            
        Returns:
            dict: Unified screening result
        """
        # 1. Screen Local Watchlist (includes cached Adverse Media if configured)
        # ComplyNexScreeningEngine is the primary aggregator currently
        result = self.local_engine.screen_person(
            name=name, 
            date_of_birth=date_of_birth, 
            nationality=nationality, 
            entity_type=entity_type,
            **kwargs
        )
        
        # 2. Future: Add Real-time External API checks here
        # if self.enable_external_apis:
        #     ext_results = self.external_screener.check(name)
        #     result = self._merge_results(result, ext_results)
        
        return result

    def close(self):
        """Close resources"""
        if self.local_engine:
            self.local_engine.close()
