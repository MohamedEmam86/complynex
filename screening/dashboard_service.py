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

import logging
import time
try:
    import redis
except ImportError:
    redis = None

logger = logging.getLogger(__name__)

class DashboardService:
    """
    Provides real-time analytics and system health for the dashboard.
    Uses Redis for atomic counters and caching.
    """
    
    def __init__(self, redis_config=None):
        self.redis = None
        if redis and redis_config:
            try:
                self.redis = redis.Redis(
                    host=redis_config.get('host', 'localhost'),
                    port=redis_config.get('port', 6379),
                    db=redis_config.get('db', 0),
                    password=redis_config.get('password'),
                    decode_responses=True,
                    socket_timeout=1.0  # Prevent blocking on connection
                )
                self.redis.ping()
                logger.info("DashboardService connected to Redis.")
            except Exception as e:
                # Use DEBUG level to avoid alarming users in development
                logger.debug(f"DashboardService: Redis not available ({e}). Real-time stats disabled.")
                self.redis = None
        
    def increment_metric(self, metric_name, amount=1):
        """Increment a counter metric (e.g., 'screenings_today')"""
        if self.redis:
            try:
                # Use a daily key to allow historical tracking if needed (or just expire)
                today = time.strftime("%Y%m%d")
                key = f"dashboard:{metric_name}:{today}"
                self.redis.incrby(key, amount)
                self.redis.expire(key, 86400 * 7) # Keep for 7 days
                
                # Also global total
                self.redis.incrby(f"dashboard:total:{metric_name}", amount)
            except Exception as e:
                logger.error(f"Failed to increment metric {metric_name}: {e}")

    def get_stats(self):
        """Retrieve current statistics"""
        stats = {
            "screenings_today": 0,
            "matches_found_today": 0,
            "false_positives_today": 0,
            "system_health": "UNKNOWN"
        }
        
        if self.redis:
            try:
                today = time.strftime("%Y%m%d")
                stats["screenings_today"] = int(self.redis.get(f"dashboard:screenings_today:{today}") or 0)
                stats["matches_found_today"] = int(self.redis.get(f"dashboard:matches_found:{today}") or 0)
                # Calculate simple health check
                stats["system_health"] = "HEALTHY" # Could check DB/Neo4j connectivity here
                stats["redis_status"] = "CONNECTED"
            except Exception as e:
                logger.error(f"Failed to retrieve stats: {e}")
                stats["system_health"] = "DEGRADED"
                stats["redis_status"] = "ERROR"
        else:
             stats["redis_status"] = "DISABLED"
             
        return stats
