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
Configuration Manager for Screening System
Reads configuration from database screening_config table
"""

import sqlite3
import os
import logging

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Manages configuration from database and environment variables.
    Priority: Database > Environment > Default
    """
    
    _config_cache = {}
    _db_path = None
    
    @classmethod
    def set_db_path(cls, db_path):
        """Set database path for configuration"""
        cls._db_path = db_path
        cls._config_cache = {}  # Clear cache when DB changes
    
    @classmethod
    def _get_db_path(cls):
        """Get database path"""
        if cls._db_path:
            return cls._db_path
        
        # Try common locations
        possible_paths = [
            'complynex.db',
            '../complynex.db',
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex.db')
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                cls._db_path = path
                return path
        
        logger.warning("Database not found in common locations")
        return 'complynex.db'  # Default
    
    @classmethod
    def get_config(cls, key, default=None, use_cache=True):
        """
        Get configuration value.
        
        Priority:
        1. Database (screening_config table)
        2. Environment variable
        3. Default value
        
        Args:
            key: Configuration key
            default: Default value if not found
            use_cache: Whether to use cached value
        
        Returns:
            Configuration value or default
        """
        # Check cache first
        if use_cache and key in cls._config_cache:
            return cls._config_cache[key]
        
        value = None

        # Try database first
        conn = None
        try:
            db_path = cls._get_db_path()
            conn = db_pool.checkout_connection()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT config_value FROM screening_config WHERE config_key = %s",
                (key,)
            )
            result = cursor.fetchone()

            if result:
                # db_pool's Postgres connections return RealDictCursor rows
                # (dict-like, e.g. {'config_value': ...}), not plain tuples —
                # result[0] raised KeyError(0) here on every call, silently
                # masking every DB-stored config value (logged as
                # "Database error reading config '<key>': 0").
                value = result['config_value'] if isinstance(result, dict) else result[0]
                logger.debug(f"Config '{key}' loaded from database")

        except Exception as e:
            if conn:
                conn.rollback()
            if 'no such table' in str(e).lower():
                logger.debug(f"screening_config table does not exist yet")
            else:
                logger.warning(f"Database error reading config '{key}': {e}")
        finally:
            # conn.close() on the pool's connection wrapper is a deliberate
            # no-op ("Pool handles this") — calling it here instead of
            # returning the connection left every config lookup's connection
            # permanently checked out as "idle in transaction" in Postgres,
            # eventually starving the pool (size 20) under concurrent syncs.
            if conn:
                db_pool.return_connection(conn)

        # Fallback to environment variable
        if not value:
            env_key = key.upper()
            value = os.environ.get(env_key)
            if value:
                logger.debug(f"Config '{key}' loaded from environment variable {env_key}")
        
        # Use default if still not found
        if value is None:
            value = default
            if default is not None:
                logger.debug(f"Config '{key}' using default value")
        
        # Cache the value
        if value is not None:
            cls._config_cache[key] = value
        
        return value
    
    @classmethod
    def get_newsapi_key(cls):
        """
        Get NewsAPI key from configuration.
        
        Returns:
            NewsAPI key or None if not configured
        """
        return cls.get_config('newsapi_key')
    
    @classmethod
    def is_adverse_media_enabled(cls):
        """Check if adverse media screening is enabled"""
        enabled = cls.get_config('adverse_media_enabled', 'false')
        return str(enabled).lower() in ['true', '1', 'yes']
    
    @classmethod
    def clear_cache(cls):
        """Clear configuration cache"""
        cls._config_cache = {}
    
    @classmethod
    def reload_config(cls):
        """Reload all configuration from database"""
        cls.clear_cache()


# Convenience function
def get_newsapi_key():
    """Get NewsAPI key (convenience function)"""
    return ConfigManager.get_newsapi_key()
