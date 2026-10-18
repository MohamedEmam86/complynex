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
Migration script to add dynamic ML threshold configuration to ComplyNex CMS.
"""
import sqlite3
import os
import time

def run_migration():
    print("── Migrating Complynex Database Schema ──")
    db_path = os.getenv('DATABASE_PATH', 'complynex_cms.db')
    
    if not os.path.isabs(db_path):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(base_dir, db_path)

    print(f"Targeting logic database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Create config table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS screening_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_key text NOT NULL UNIQUE,
                config_value text NOT NULL,
                updated_by INTEGER DEFAULT 1,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert default threshold
        cursor.execute("""
            INSERT OR IGNORE INTO screening_config (config_key, config_value) 
            VALUES ('screening_threshold', '55')
        """)

        # Create audit table to track threshold changes (Compliance requirement)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS screening_config_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_key text NOT NULL,
                old_value text,
                new_value text NOT NULL,
                changed_by INTEGER,
                changed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        print("✅ Migration applied successfully.")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    run_migration()
