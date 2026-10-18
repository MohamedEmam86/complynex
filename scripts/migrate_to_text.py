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

import psycopg
import os
import logging

# Database config
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'dbname': os.getenv('DB_NAME', 'complynex_dev'),
    'user': os.getenv('DB_USER', 'complynex_dev'),
    'password': os.getenv('DB_PASSWORD', 'dev_password_123'),
    'port': int(os.getenv('DB_PORT', 5432))
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def migrate():
    try:
        conn = psycopg.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        logger.info("Migrating screening_watchlist columns to TEXT...")
        
        cursor.execute("""
            ALTER TABLE screening_watchlist 
              ALTER COLUMN full_name TYPE TEXT,
              ALTER COLUMN original_name TYPE TEXT,
              ALTER COLUMN entity_type TYPE TEXT,
              ALTER COLUMN list_type TYPE TEXT,
              ALTER COLUMN dataset TYPE TEXT,
              ALTER COLUMN place_of_birth TYPE TEXT,
              ALTER COLUMN gender TYPE TEXT,
              ALTER COLUMN nationality TYPE TEXT,
              ALTER COLUMN source TYPE TEXT,
              ALTER COLUMN source_id TYPE TEXT,
              ALTER COLUMN name_normalized TYPE TEXT,
              ALTER COLUMN name_soundex TYPE TEXT,
              ALTER COLUMN name_metaphone TYPE TEXT,
              ALTER COLUMN risk_level TYPE TEXT;
        """)
        
        conn.commit()
        logger.info("Migration successful!")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        conn.rollback()
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    migrate()
