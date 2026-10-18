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
import time
import threading
import logging
import sqlite3
import os
try:
    import psycopg
except ImportError:
    psycopg = None
    try:
        import psycopg2
    except ImportError:
        psycopg2 = None

logger = logging.getLogger(__name__)

class ScreeningMetrics:
    """
    Collects and records screening metrics.
    """
    
    def __init__(self, db_config):
        self.db_config = db_config
        # Determine DB type
        if 'database' in db_config and len(db_config) == 1:
            self.db_type = 'sqlite'
        else:
            self.db_type = 'postgresql'
            
    def log(self, result, name, entity_type):
        """
        Log screening result to metrics table.
        Runs in a separate thread to avoid blocking.
        """
        try:
            threading.Thread(target=self._save_metric, args=(result, name, entity_type)).start()
        except Exception as e:
            logger.error(f"Failed to start metrics thread: {e}")
            
    def _save_metric(self, result, name, entity_type):
        try:
            # Extract metrics
            processing_time = result.get('processing_time_ms', 0)
            total_matches = result.get('total_matches', 0)
            highest_score = result.get('highest_score', 0.0)
            status = result.get('screening_result', 'UNKNOWN')
            cache_hit = 1 if result.get('from_cache', False) else 0
            total_candidates = result.get('total_candidates', 0)
            
            # Connect and insert
            if self.db_type == 'sqlite':
                self._insert_sqlite(processing_time, total_candidates, total_matches, highest_score, cache_hit, name, entity_type, status)
            else:
                self._insert_pg(processing_time, total_candidates, total_matches, highest_score, cache_hit, name, entity_type, status)
                
        except Exception as e:
            logger.error(f"Error saving metric: {e}")

    def _insert_sqlite(self, processing_time, total_candidates, total_matches, highest_score, cache_hit, name, entity_type, status):
        # Despite the name/placeholder style, this always serves the shared
        # Postgres pool in production (db_pool always backs onto
        # Config.POSTGRES_CONFIG) — conn.close() on the pool's wrapper is a
        # deliberate no-op, so calling it here instead of return_connection()
        # leaked one pool slot on every single screening call (this runs on
        # every engine.screen_person()), exhausting the 20-connection pool
        # under sustained load.
        conn = None
        try:
            conn = db_pool.checkout_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO screening_metrics
                (processing_time_ms, total_candidates, total_matches, highest_score, cache_hit, screened_name, entity_type, match_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (processing_time, total_candidates, total_matches, highest_score, cache_hit, name, entity_type, status))
            conn.commit()
        except Exception as e:
             logger.error(f"Error saving sqlite metric: {e}")
        finally:
            if conn: db_pool.return_connection(conn)
            
    def _insert_pg(self, processing_time, total_candidates, total_matches, highest_score, cache_hit, name, entity_type, status):
        conn = None
        try:
            # We need to reconstruct connection params broadly
            # Assuming db_config has standard PG keys
            if psycopg:
                conn = psycopg.connect(
                    dbname=self.db_config.get('dbname') or self.db_config.get('database'),
                    user=self.db_config.get('user'),
                    password=self.db_config.get('password'),
                    host=self.db_config.get('host'),
                    port=self.db_config.get('port', 5432)
                )
            elif psycopg2:
                conn = psycopg2.connect(**self.db_config)
            
            if conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO screening_metrics 
                    (processing_time_ms, total_candidates, total_matches, highest_score, cache_hit, screened_name, entity_type, match_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (processing_time, total_candidates, total_matches, highest_score, cache_hit, name, entity_type, status))
                conn.commit()
        except Exception as e:
             logger.error(f"Error saving pg metric: {e}")
        finally:
            if conn: conn.close()
