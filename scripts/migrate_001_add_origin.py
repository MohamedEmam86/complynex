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
import sys

# Database config
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'dbname': os.getenv('DB_NAME', 'complynex_dev'),
    'user': os.getenv('DB_USER', 'complynex_dev'),
    'password': os.getenv('DB_PASSWORD', 'dev_password_123'),
    'port': int(os.getenv('DB_PORT', 5432))
}

def migrate():
    """Add data_source_origin column to screening_watchlist"""
    print("Connecting to database...")
    try:
        conn = psycopg.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("Checking if column exists...")
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='screening_watchlist' AND column_name='data_source_origin';
        """)
        
        if cursor.fetchone():
            print("Column 'data_source_origin' already exists.")
        else:
            print("Adding 'data_source_origin' column...")
            cursor.execute("""
                ALTER TABLE screening_watchlist 
                ADD COLUMN data_source_origin TEXT[];
            """)
            print("Column added successfully.")
            
        conn.commit()
        conn.close()
        print("Migration complete.")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate()
