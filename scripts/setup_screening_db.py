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
Setup Screening Database (SQLite)
Creates tables for the Hybrid Screening Tool.
Updated for Advanced AML Module.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex_cms.db')

def setup_db():
    print(f"Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. screening_watchlist
    print("Creating table: screening_watchlist...")
    cursor.execute("DROP TABLE IF EXISTS screening_watchlist;")
    cursor.execute("""
    CREATE TABLE screening_watchlist (
        id TEXT PRIMARY KEY,
        full_name TEXT NOT NULL,
        full_name_arabic TEXT,
        name_normalized TEXT,
        name_soundex TEXT,
        name_metaphone TEXT,
        dataset TEXT,
        list_type TEXT,
        topics TEXT, -- JSON array
        countries TEXT, -- JSON array
        date_of_birth TEXT, -- ISO date string
        year_of_birth INTEGER,
        nationality TEXT,
        gender TEXT,
        source_url TEXT,
        risk_level TEXT,
        aliases TEXT, -- JSON array (English)
        aliases_arabic TEXT, -- JSON array
        pep_position TEXT,
        pep_country TEXT,
        details TEXT, -- Generic JSON details (program, reason, etc)
        is_active BOOLEAN DEFAULT 1,
        last_updated TEXT
    );
    """)
    
    # Indexes for performance
    print("Creating indexes for screening_watchlist...")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sw_name_norm ON screening_watchlist(name_normalized);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sw_soundex ON screening_watchlist(name_soundex);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sw_metaphone ON screening_watchlist(name_metaphone);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sw_dob ON screening_watchlist(date_of_birth);")
    
    # 2. screening_results (Audit Log)
    print("Creating table: screening_results...")
    # Keep IF NOT EXISTS for results to preserve history, or DROP if it's a fresh start.
    # We'll keep it for now but ensure it has the right columns if we ever change them.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS screening_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        screening_type TEXT, -- 'CUSTOMER', 'ADHOC', etc.
        screened_name TEXT,
        screened_dob TEXT,
        screening_method TEXT, -- 'AUTOMATIC', 'MANUAL'
        total_matches_found INTEGER,
        highest_match_score REAL,
        screening_result TEXT, -- 'CLEAR', 'POTENTIAL_MATCH', 'CONFIRMED_HIT'
        matches TEXT, -- JSON detailed results
        processing_time_ms INTEGER,
        created_by INTEGER, -- User ID
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    # 3. screening_whitelist (False Positive Management)
    print("Creating table: screening_whitelist...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS screening_whitelist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER,
        watchlist_id TEXT,
        reason TEXT,
        approved_by INTEGER,
        approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_active BOOLEAN DEFAULT 1
    );
    """)

    # 4. screening_settings
    print("Creating table: screening_settings...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS screening_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        value TEXT NOT NULL,
        category TEXT,
        description TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Seed default settings if empty
    cursor.execute("SELECT COUNT(*) FROM screening_settings")
    if cursor.fetchone()[0] == 0:
        print("Seeding default screening settings...")
        default_settings = [
            ('FUZZY_RATIO_WEIGHT', '0.40', 'weights', 'Weight for Levenshtein Ratio matching'),
            ('JARO_WINKLER_WEIGHT', '0.30', 'weights', 'Weight for Jaro-Winkler similarity matching'),
            ('PHONETIC_WEIGHT', '0.20', 'weights', 'Weight for Phonetic (Soundex/Metaphone) match'),
            ('PARTIAL_RATIO_WEIGHT', '0.10', 'weights', 'Weight for Partial Ratio matching'),
            ('AUTO_MATCH_THRESHOLD', '0.95', 'thresholds', 'Threshold for automatic hit confirmation'),
            ('POTENTIAL_MATCH_THRESHOLD', '0.80', 'thresholds', 'Threshold for potential match flagging'),
            ('LOW_MATCH_MIN', '0.70', 'thresholds', 'Minimum score to be considered a match')
        ]
        cursor.executemany(
            "INSERT INTO screening_settings (key, value, category, description) VALUES (?, ?, ?, ?)",
            default_settings
        )

    # 5. screening_sources
    print("Creating table: screening_sources...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS screening_sources (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL, -- e.g. 'OpenSanctions', 'Custom'
        url TEXT,
        is_active BOOLEAN DEFAULT 1,
        last_updated_at TIMESTAMP,
        last_updated_by INTEGER
    );
    """)

    # Seed default source if empty
    cursor.execute("SELECT COUNT(*) FROM screening_sources")
    if cursor.fetchone()[0] == 0:
        print("Seeding default screening source...")
        cursor.execute("""
            INSERT INTO screening_sources (id, name, type, url, is_active)
            VALUES (?, ?, ?, ?, ?)
        """, ('os_default', 'OpenSanctions (Full)', 'OpenSanctions', 'https://data.opensanctions.org/datasets/latest/default/entities.ftm.json', 1))
    
    conn.commit()
    conn.close()
    print("Database setup complete.")

if __name__ == "__main__":
    setup_db()
