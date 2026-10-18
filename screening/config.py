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
Screening Tool Configuration
Moov Watchman-inspired tunable parameters
Updated for Advanced AML Module.
"""
import os

class ScreeningConfig:
    """Configuration for hybrid screening engine.

    NOTE: only the legacy HybridScreeningEngine (screening/hybrid_engine.py,
    now used solely by scripts/test_*/verify_*/debug_* tools) reads the
    weights and thresholds below. The PRODUCTION scoring path is
    ComplyNexScreeningEngine, which defines its own class-level weights in
    complynex_engine.py — tuning values here does NOT change live screening.
    (NEWSAPI_*/ADVERSE_MEDIA_*/AUDIT_LOG_* at the bottom ARE read by
    production code.)
    """

    # Advanced Ensemble Weights (from response.md recommendation)
    FUZZY_RATIO_WEIGHT = 0.40      # Levenshtein Ratio
    JARO_WINKLER_WEIGHT = 0.30     # Jaro-Winkler
    PHONETIC_WEIGHT = 0.20         # Metaphone/Soundex check match
    PARTIAL_RATIO_WEIGHT = 0.10    # Partial Ratio (for aliases)
    
    # Legacy Weights (for backward compatibility if needed)
    # JARO_WINKLER_WEIGHT_OLD = 0.70
    # LEVENSHTEIN_WEIGHT_OLD = 0.30
    
    # Moov Watchman parameters
    EXACT_MATCH_FAVORITISM = 0.25  
    PREFIX_SCALE = 0.1  # Winkler prefix weight
    
    # Thresholds (OFAC standard)
    EXACT_MATCH = 1.0
    HIGH_MATCH_MIN = 0.90
    MEDIUM_MATCH_MIN = 0.80
    LOW_MATCH_MIN = 0.70
    
    # Matching Logic parameters
    AUTO_MATCH_THRESHOLD = 0.95
    POTENTIAL_MATCH_THRESHOLD = 0.80
    NO_MATCH_THRESHOLD = 0.70 # Anything below this is ignored
    
    # Attribute adjustment weights
    DOB_EXACT_MATCH_BONUS = 0.10
    DOB_MISMATCH_PENALTY = -0.20
    YEAR_MATCH_BONUS = 0.05
    YEAR_MISMATCH_PENALTY = -0.10
    COUNTRY_MATCH_BONUS = 0.05
    GENDER_MATCH_BONUS = 0.02
    GENDER_MISMATCH_PENALTY = -0.10
    
    # Stop words (expanded from Moov Watchman)
    STOP_WORDS = {
        # English titles
        'MR', 'MRS', 'MS', 'MISS', 'DR', 'PROF', 'SIR', 'LADY', 'LORD',
        'COLONEL', 'COL', 'GENERAL', 'GEN', 'CAPTAIN', 'CAPT', 'MAJOR', 'MAJ',
        'BRIGADIER', 'BRIG', 'ADMIRAL', 'ADM', 'JUDGE',
        # Arabic titles/particles
        'AL', 'EL', 'ABU', 'IBN', 'BIN', 'BINT', 'UMM', 'UM',
        'SHEIKH', 'SHAYKH', 'SHAIKH', 'HAJJ', 'HAJI', 'HAJJA',
        'PASHA', 'BEY',  # Ottoman-Egyptian honorific titles — not given names, unlike MOHAMED/MOHAMMAD/MOUHAMAD
        # Articles
        'THE', 'AND', 'OF',
        # Company suffixes
        'LLC', 'INC', 'LTD', 'CORP', 'CO', 'GROUP', 'HOLDINGS', 'PLC', 'ENTERPRISES'
    }
    
    # Performance settings
    MAX_CANDIDATES = 1000  # Phonetic pre-filter limit
    LEVENSHTEIN_THRESHOLD = 0.60  # Lowered for advanced module to be more inclusive
    
    # NewsAPI / Adverse Media Screening (loaded from database)
    try:
        from .config_manager import ConfigManager
        NEWSAPI_KEY = ConfigManager.get_newsapi_key() or os.environ.get('NEWSAPI_KEY', '')
        ADVERSE_MEDIA_ENABLED = ConfigManager.is_adverse_media_enabled()
    except ImportError:
        NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY', '')
        ADVERSE_MEDIA_ENABLED = os.environ.get('NEWSAPI_ENABLED', 'true').lower() == 'true'
    ADVERSE_MEDIA_CACHE_TTL = 86400  # 24 hours cache for NewsAPI results
    
    # Audit Log
    AUDIT_LOG_RETENTION_DAYS = 365  # How long to keep audit records
