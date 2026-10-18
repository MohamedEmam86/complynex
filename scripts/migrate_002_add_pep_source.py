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
    """Add opensanctions_pep source and update opensanctions display name"""
    print("Connecting to database...")
    try:
        conn = psycopg.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("Updating 'opensanctions' display name...")
        cursor.execute("""
            UPDATE screening_data_sources 
            SET source_display_name = 'OpenSanctions (Global Sanctions)',
                source_url = 'https://data.opensanctions.org/datasets/latest/sanctions/entities.ftm.json'
            WHERE source_name = 'opensanctions';
        """)
        
        print("Inserting 'opensanctions_pep' source...")
        cursor.execute("""
            INSERT INTO screening_data_sources (source_name, source_display_name, source_url, source_type, is_official, update_frequency_hours)
            VALUES ('opensanctions_pep', 'OpenSanctions (Global PEPs)', 'https://data.opensanctions.org/datasets/latest/peps/entities.ftm.json', 'JSON', FALSE, 24)
            ON CONFLICT (source_name) DO UPDATE SET
                source_display_name = EXCLUDED.source_display_name,
                source_url = EXCLUDED.source_url;
        """)
        
        print("Sources updated successfully.")
        
        conn.commit()
        conn.close()
        print("Migration complete.")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate()
