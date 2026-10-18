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

DB_PATH = 'complynex_cms.db'

def reinit_watchlist():
    print(f"Connecting to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("Dropping old screening_watchlist table...")
    c.execute("DROP TABLE IF EXISTS screening_watchlist")

    print("Creating screening_watchlist table...")
    c.execute("""
    CREATE TABLE screening_watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        
        -- Identity
        full_name VARCHAR(500) NOT NULL,
        original_name VARCHAR(500),  -- Arabic or non-Latin script
        aliases TEXT,  -- JSON Array of alternative names
        
        -- Entity Type
        entity_type VARCHAR(20),  -- 'PERSON', 'ORGANIZATION', 'VESSEL', 'AIRCRAFT'
        
        -- Classification
        list_type VARCHAR(50) NOT NULL,  -- 'SANCTIONS', 'PEP', 'WANTED', 'CRIME'
        dataset VARCHAR(100) NOT NULL,   -- Source dataset
        topics TEXT,  -- JSON Array
        
        -- Personal Information
        date_of_birth DATE,
        year_of_birth INTEGER,
        place_of_birth VARCHAR(200),
        gender VARCHAR(10),  -- 'MALE', 'FEMALE'
        
        -- Geographic
        countries TEXT, -- JSON Array
        nationality VARCHAR(100),
        
        -- Identifiers
        passport_numbers TEXT, -- JSON Array
        national_id_numbers TEXT, -- JSON Array
        
        -- Addresses
        addresses TEXT, -- JSON
        
        -- Source Information
        source VARCHAR(100) NOT NULL,  -- 'opensanctions', 'un', 'ofac', 'eu', 'hmt', 'emlcu'
        source_id VARCHAR(200) UNIQUE, -- Added UNIQUE constraint for upsert
        source_url TEXT,
        first_seen DATE,
        last_seen DATE,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        -- Search Optimization
        name_normalized VARCHAR(500),  -- Uppercase, no special chars
        name_soundex VARCHAR(20),
        name_metaphone VARCHAR(20),
        name_tokens TEXT, -- JSON Array
        
        -- Risk
        risk_level VARCHAR(20),  -- 'EXTREME', 'HIGH', 'MEDIUM', 'LOW'
        
        -- Metadata
        properties TEXT, -- JSON
        
        -- System
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_active BOOLEAN DEFAULT 1
    )
    """)
    
    # Create Indexes
    print("Creating indexes...")
    c.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_source ON screening_watchlist(source)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_name_norm ON screening_watchlist(name_normalized)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_source_id ON screening_watchlist(source_id)")

    conn.commit()
    print("Watchlist table re-initialized successfully.")
    conn.close()

if __name__ == '__main__':
    reinit_watchlist()
