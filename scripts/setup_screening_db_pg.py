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

import psycopg2
from psycopg2.extras import RealDictCursor
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# DB connection configuration from environment or defaults
DB_CONFIG = {
    'host': os.environ.get('POSTGRES_HOST', 'localhost'),
    'database': os.environ.get('POSTGRES_DB', 'complynex_cms'),
    'user': os.environ.get('POSTGRES_USER', 'postgres'),
    'password': os.environ.get('POSTGRES_PASSWORD', ''),
    'port': os.environ.get('POSTGRES_PORT', '5432')
}

def setup_database():
    """Create tables and indexes for the screening module in PostgreSQL"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        logger.info("Connected to PostgreSQL. Initializing schema...")
        
        # 1. screening_watchlist table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_watchlist (
            id SERIAL PRIMARY KEY,
            source_id VARCHAR(100) UNIQUE,
            full_name TEXT NOT NULL,
            original_name TEXT,
            name_normalized TEXT,
            name_soundex VARCHAR(10),
            name_metaphone VARCHAR(10),
            list_type VARCHAR(50),
            dataset VARCHAR(100),
            source VARCHAR(100),
            source_url TEXT,
            risk_level VARCHAR(50),
            topics TEXT, -- Stored as comma-separated or JSON string
            countries TEXT,
            date_of_birth DATE,
            year_of_birth INTEGER,
            nationality VARCHAR(100),
            gender VARCHAR(10),
            aliases TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # Indexes for fast recall (Phase 1)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_normalized ON screening_watchlist(name_normalized);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_soundex ON screening_watchlist(name_soundex);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_metaphone ON screening_watchlist(name_metaphone);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_gender ON screening_watchlist(gender);")
        
        # 2. screening_sources table (Integration Management)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_sources (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            type VARCHAR(50) DEFAULT 'FTJSON', -- FTJSON, EMLCU_SCRAPER, CUSTOM
            url TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            last_updated_at TIMESTAMP,
            last_updated_by INTEGER
        );
        """)

        # 3. screening_config table (Administrative Tuning)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_config (
            id SERIAL PRIMARY KEY,
            config_key VARCHAR(100) UNIQUE NOT NULL,
            config_value TEXT,
            category VARCHAR(50),
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        # 3. screening_results table (Log)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_results (
            id SERIAL PRIMARY KEY,
            screening_type VARCHAR(50),
            screened_name TEXT,
            screened_dob DATE,
            screening_method VARCHAR(50),
            total_matches_found INTEGER,
            highest_match_score DECIMAL(5,2),
            screening_result VARCHAR(50),
            matches JSONB,
            processing_time_ms INTEGER,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Insert default configuration
        logger.info("Seeding default screening configuration...")
        default_settings = [
            ('fuzzy_ratio_weight', '0.40', 'weights', 'Weight for Levenshtein fuzzy ratio'),
            ('jaro_winkler_weight', '0.30', 'weights', 'Weight for Jaro-Winkler algorithm'),
            ('phonetic_weight', '0.20', 'weights', 'Weight for Soundex/Metaphone phonetic'),
            ('partial_ratio_weight', '0.10', 'weights', 'Weight for partial substring matching'),
            ('exact_match_favoritism', '25.0', 'bonus', 'Bonus for exact token matches'),
            ('dob_exact_match_bonus', '10.0', 'bonus', 'Bonus for exact DOB match'),
            ('dob_mismatch_penalty', '-10.0', 'penalty', 'Penalty for DOB mismatch'),
            ('nationality_bonus', '5.0', 'bonus', 'Bonus for nationality match'),
            ('confirmed_hit_threshold', '95.0', 'thresholds', 'Threshold for confirmed hit'),
            ('potential_match_threshold', '80.0', 'thresholds', 'Threshold for potential match'),
            ('low_match_threshold', '70.0', 'thresholds', 'Threshold for low match')
        ]
        
        for key, val, cat, desc in default_settings:
            cursor.execute("""
                INSERT INTO screening_config (config_key, config_value, category, description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (config_key) DO NOTHING;
            """, (key, val, cat, desc))
            
        # Insert default sources
        logger.info("Seeding regulatory data sources...")
        sources = [
            ('OpenSanctions (Baseline Aggregated)', 'FTJSON', 'https://data.opensanctions.org/datasets/latest/default/entities.ftm.json'),
            ('UN Consolidated List (Direct)', 'FTJSON', 'https://data.opensanctions.org/datasets/latest/un_sc_sanctions/entities.ftm.json'),
            ('US OFAC SDN (Direct)', 'FTJSON', 'https://data.opensanctions.org/datasets/latest/us_ofac_sdn/entities.ftm.json'),
            ('EU Financial Sanctions (Direct)', 'FTJSON', 'https://data.opensanctions.org/datasets/latest/eu_fsf/entities.ftm.json'),
            ('UK HMT Sanctions (Direct)', 'FTJSON', 'https://data.opensanctions.org/datasets/latest/gb_hmt/entities.ftm.json'),
            ('EMLCU Egypt Terrorist List', 'EMLCU_SCRAPER', None)
        ]
        
        for name, stype, url in sources:
            cursor.execute("""
                INSERT INTO screening_sources (name, type, url)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING; -- No unique constraint on name yet, but can be added
            """, (name, stype, url))

        conn.commit()
        cursor.close()
        conn.close()
        logger.info("PostgreSQL schema successfully initialized.")
        
    except Exception as e:
        logger.error(f"Error setting up database: {e}")

if __name__ == "__main__":
    setup_database()
