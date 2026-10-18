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
import sys

def fix_schema():
    """
    Fix SQLite schema by adding missing columns to screening_watchlist
    and ensuring the table exists.
    """
    # Path to database
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, 'complynex_cms.db')
    
    print(f"Checking database at: {db_path}")
    
    if not os.path.exists(db_path):
        print("Database file does not exist. Please run the application first.")
        return
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='screening_watchlist'")
        if not cursor.fetchone():
            print("Table screening_watchlist does not exist. Creating it...")
            # Create table if it doesn't exist (simplified version for SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS screening_watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name VARCHAR(500) NOT NULL,
                    original_name VARCHAR(500),
                    aliases TEXT,
                    entity_type VARCHAR(20),
                    list_type VARCHAR(50) NOT NULL,
                    dataset VARCHAR(100) NOT NULL,
                    topics TEXT,
                    date_of_birth DATE,
                    year_of_birth INTEGER,
                    place_of_birth VARCHAR(200),
                    gender VARCHAR(10),
                    countries TEXT,
                    nationality VARCHAR(100),
                    passport_numbers TEXT,
                    national_id_numbers TEXT,
                    addresses TEXT,
                    source VARCHAR(100) NOT NULL,
                    source_id VARCHAR(200),
                    source_url TEXT,
                    first_seen DATE,
                    last_seen DATE,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    name_normalized VARCHAR(500),
                    name_soundex VARCHAR(20),
                    name_metaphone VARCHAR(20),
                    name_tokens TEXT,
                    risk_level VARCHAR(20),
                    properties TEXT,  -- Added to fix error
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                );
            """)
            print("Table created.")
        else:
            print("Table screening_watchlist exists. Checking columns...")
            # Check for properties column
            cursor.execute("PRAGMA table_info(screening_watchlist)")
            columns = [info[1] for info in cursor.fetchall()]
            
            if 'properties' not in columns:
                print("Column 'properties' missing. Adding it...")
                cursor.execute("ALTER TABLE screening_watchlist ADD COLUMN properties TEXT")
                print("Column added.")
            else:
                print("Column 'properties' already exists.")
                
            # Check for other potentially missing columns used in SELECT
            required_columns = ['source', 'risk_level', 'entity_type']
            for col in required_columns:
                if col not in columns:
                    print(f"Column '{col}' missing. Adding it...")
                    cursor.execute(f"ALTER TABLE screening_watchlist ADD COLUMN {col} TEXT")
                    print(f"Column '{col}' added.")
                    
        conn.commit()
        print("Schema fix completed successfully.")
        
    except Exception as e:
        print(f"Error fixing schema: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    fix_schema()
