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

import sqlite3
import os

def migrate_db():
    print("Starting database migration to Phase 2...")
    
    db_path = 'complynex_cms.db'
    schema_path = 'schema_phase2.sql'
    
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}. Creating new database...")
    
    if not os.path.exists(schema_path):
        print(f"Schema file not found at {schema_path}!")
        return
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_script = f.read()
            
        # SQLite doesn't support executing multiple statements in execute(), use executescript()
        cursor.executescript(schema_script)
        
        conn.commit()
        print("Migration completed successfully!")
        
        # Verify tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Total tables in database: {len(tables)}")
        for table in tables:
            print(f"- {table[0]}")
            
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    migrate_db()
