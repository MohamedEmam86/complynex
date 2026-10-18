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
    """Cleanup legacy sources and add Internal Blacklist"""
    print("Connecting to database...")
    try:
        conn = psycopg.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # 1. Delete legacy sources
        legacy_sources = [
            'un_consolidated', 'ofac_sdn', 'eu_sanctions', 'uk_hmt', 'emlcu_egypt', 
            'test_custom_source', 'custom' # Clean up any test sources
        ]
        
        print(f"Removing legacy sources: {legacy_sources}")
        cursor.execute("DELETE FROM screening_data_sources WHERE source_name = ANY(%s)", (legacy_sources,))
        
        # 2. Add Internal Blacklist
        print("Ensuring 'internal_blacklist' exists...")
        cursor.execute("""
            INSERT INTO screening_data_sources (source_name, source_display_name, source_url, source_type, is_active, is_official)
            VALUES ('internal_blacklist', 'Internal Blacklist', 'internal', 'CUSTOM', TRUE, FALSE)
            ON CONFLICT (source_name) DO UPDATE SET
                source_display_name = 'Internal Blacklist',
                is_active = 1;
        """)
        
        # 3. Ensure OpenSanctions sources are correct
        # (Already handled by previous migrations but good to be safe)
        
        conn.commit()
        conn.close()
        print("Migration complete. Only PEP, Sanctions (OpenSanctions), and Internal Blacklist should remain.")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate()
