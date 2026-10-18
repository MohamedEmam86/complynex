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
Create all database tables for screening module
This is the complete production-ready schema
"""

import psycopg
import os
from datetime import datetime

# Database connection from .env
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'dbname': os.getenv('DB_NAME', 'complynex_dev'),
    'user': os.getenv('DB_USER', 'complynex_dev'),
    'password': os.getenv('DB_PASSWORD', 'dev_password_123'),
    'port': int(os.getenv('DB_PORT', 5432))
}


def create_schema():
    """Create all screening tables"""
    
    print("Connecting to database...")
    conn = psycopg.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    print("Creating tables...")
    
    # Table 1: Screening Watchlist (Master Data)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_watchlist (
            id SERIAL PRIMARY KEY,
            
            -- Identity
            full_name VARCHAR(500) NOT NULL,
            original_name VARCHAR(500),  -- Arabic or non-Latin script
            aliases TEXT[],  -- Array of alternative names
            
            -- Entity Type
            entity_type VARCHAR(20),  -- 'PERSON', 'ORGANIZATION', 'VESSEL', 'AIRCRAFT'
            
            -- Classification
            list_type VARCHAR(50) NOT NULL,  -- 'SANCTIONS', 'PEP', 'WANTED', 'CRIME'
            dataset VARCHAR(100) NOT NULL,   -- Source dataset
            topics TEXT[],  -- Classification tags
            
            -- Personal Information
            date_of_birth DATE,
            year_of_birth INTEGER,
            place_of_birth VARCHAR(200),
            gender VARCHAR(10),  -- 'MALE', 'FEMALE'
            
            -- Geographic
            countries TEXT[],
            nationality VARCHAR(100),
            
            -- Identifiers
            passport_numbers TEXT[],
            national_id_numbers TEXT[],
            
            -- Addresses
            addresses JSONB,
            
            -- Source Information
            source VARCHAR(100) NOT NULL,  -- 'opensanctions', 'un', 'ofac', 'eu', 'hmt', 'emlcu'
            source_id VARCHAR(200) UNIQUE,
            source_url TEXT,
            first_seen DATE,
            last_seen DATE,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            -- Search Optimization
            name_normalized VARCHAR(500),  -- Uppercase, no special chars
            name_soundex VARCHAR(20),
            name_metaphone VARCHAR(20),
            name_tokens TEXT[],
            
            -- Full-text search
            search_vector TSVECTOR,
            
            -- Risk
            risk_level VARCHAR(20),  -- 'EXTREME', 'HIGH', 'MEDIUM', 'LOW'
            
            -- Metadata
            properties JSONB,
            
            -- System
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE
        );
    """)
    
    # Indexes for screening_watchlist
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_name_norm ON screening_watchlist(name_normalized);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_soundex ON screening_watchlist(name_soundex);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_metaphone ON screening_watchlist(name_metaphone);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_source ON screening_watchlist(source);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_dataset ON screening_watchlist(dataset);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_list_type ON screening_watchlist(list_type);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_dob ON screening_watchlist(date_of_birth);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_active ON screening_watchlist(is_active) WHERE is_active = 1;")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_fts ON screening_watchlist USING GIN(search_vector);")
    
    # pg_trgm extension + GIN trigram indexes for fuzzy candidate recall
    try:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trgm_full_name ON screening_watchlist USING GIN (full_name gin_trgm_ops);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trgm_name_normalized ON screening_watchlist USING GIN (name_normalized gin_trgm_ops);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trgm_original_name ON screening_watchlist USING GIN (original_name gin_trgm_ops);")
        print("[OK] Created pg_trgm GIN trigram indexes")
    except Exception as e:
        print(f"[WARN] pg_trgm indexes skipped (may need superuser): {e}")
    print("[OK] Created screening_watchlist table")
    
    # Table 2: Screening Results (Audit Log)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_results (
            id SERIAL PRIMARY KEY,
            
            -- What was screened
            screening_type VARCHAR(20),  -- 'CUSTOMER', 'TRANSACTION', 'BENEFICIAL_OWNER'
            customer_id INTEGER,
            transaction_id INTEGER,
            
            -- Input data
            screened_name VARCHAR(500) NOT NULL,
            screened_dob DATE,
            screened_country VARCHAR(100),
            screened_nationality VARCHAR(100),
            screened_gender VARCHAR(10),
            
            -- Screening metadata
            screening_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            screening_method VARCHAR(50) DEFAULT 'AUTOMATIC',  -- 'AUTOMATIC', 'MANUAL', 'BULK'
            is_arabic BOOLEAN DEFAULT FALSE,
            
            -- Results
            total_matches_found INTEGER DEFAULT 0,
            highest_match_score DECIMAL(5,2),  -- 0.00 to 100.00
            
            -- Match classification
            has_exact_match BOOLEAN DEFAULT FALSE,
            has_high_match BOOLEAN DEFAULT FALSE,
            has_medium_match BOOLEAN DEFAULT FALSE,
            
            -- Overall decision
            screening_result VARCHAR(20),  -- 'CLEAR', 'LOW_MATCH', 'POTENTIAL_MATCH', 'CONFIRMED_HIT'
            
            -- Detailed matches (JSONB with score breakdown)
            matches JSONB,
            
            -- Review & Decision
            requires_review BOOLEAN DEFAULT FALSE,
            reviewed BOOLEAN DEFAULT FALSE,
            reviewed_by INTEGER,
            reviewed_at TIMESTAMP,
            review_decision VARCHAR(20),  -- 'TRUE_POSITIVE', 'FALSE_POSITIVE', 'WHITELIST'
            review_notes TEXT,
            
            -- Actions taken
            customer_blocked BOOLEAN DEFAULT FALSE,
            transaction_blocked BOOLEAN DEFAULT FALSE,
            edd_triggered BOOLEAN DEFAULT FALSE,
            sar_filed BOOLEAN DEFAULT FALSE,
            emlcu_notified BOOLEAN DEFAULT FALSE,
            
            -- Performance
            processing_time_ms INTEGER,
            
            -- Audit trail
            ip_address VARCHAR(50),
            user_agent TEXT,
            
            -- System
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER
        );
    """)
    
    # Indexes for screening_results
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_screening_date ON screening_results(screening_date DESC);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_screening_result ON screening_results(screening_result);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_screening_review ON screening_results(requires_review) WHERE requires_review = TRUE;")
    
    print("[OK] Created screening_results table")
    
    # Table 3: Screening Whitelist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_whitelist (
            id SERIAL PRIMARY KEY,
            
            -- Customer/Entity
            customer_id INTEGER,
            whitelisted_name VARCHAR(500) NOT NULL,
            
            -- Watchlist match
            watchlist_id INTEGER REFERENCES screening_watchlist(id),
            watchlist_name VARCHAR(500),
            dataset VARCHAR(100),
            match_score DECIMAL(5,2),
            
            -- Justification
            false_positive_reason TEXT NOT NULL,
            supporting_documents TEXT[],
            
            -- Approval
            approved_by INTEGER NOT NULL,
            approval_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            -- Validity
            valid_until DATE,
            
            -- System
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE
        );
    """)
    
    print("[OK] Created screening_whitelist table")
    
    # Table 4: Data Sources Configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_data_sources (
            id SERIAL PRIMARY KEY,
            
            -- Source identification
            source_name VARCHAR(100) UNIQUE NOT NULL,  -- 'opensanctions', 'un', 'ofac', etc.
            source_display_name VARCHAR(200) NOT NULL,
            source_url TEXT NOT NULL,
            source_type VARCHAR(50),  -- 'JSON', 'XML', 'CSV', 'HTML_SCRAPE'
            
            -- Status
            is_active BOOLEAN DEFAULT TRUE,
            is_official BOOLEAN DEFAULT FALSE,  -- True for UN, OFAC, EU, HMT, EMLCU
            
            -- Update configuration
            update_frequency_hours INTEGER DEFAULT 24,
            last_update_attempt TIMESTAMP,
            last_successful_update TIMESTAMP,
            next_scheduled_update TIMESTAMP,
            
            -- Statistics
            total_records INTEGER DEFAULT 0,
            records_added_last_update INTEGER DEFAULT 0,
            records_updated_last_update INTEGER DEFAULT 0,
            
            -- Error tracking
            consecutive_failures INTEGER DEFAULT 0,
            last_error_message TEXT,
            
            -- System
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by INTEGER
        );
    """)
    
    print("[OK] Created screening_data_sources table")
    
    # Table 5: Update Log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_update_logs (
            id SERIAL PRIMARY KEY,
            
            -- Source
            source_name VARCHAR(100) NOT NULL,
            
            -- Timing
            update_started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            update_completed_at TIMESTAMP,
            duration_seconds INTEGER,
            
            -- Statistics
            records_before INTEGER,
            records_after INTEGER,
            records_added INTEGER DEFAULT 0,
            records_updated INTEGER DEFAULT 0,
            records_removed INTEGER DEFAULT 0,
            
            -- Status
            update_status VARCHAR(20),  -- 'SUCCESS', 'FAILED', 'PARTIAL'
            error_message TEXT,
            
            -- File information
            source_file_url TEXT,
            source_file_size_bytes BIGINT,
            source_file_hash VARCHAR(64),  -- SHA256
            
            -- Trigger
            triggered_by VARCHAR(50) DEFAULT 'MANUAL',  -- 'MANUAL', 'CRON', 'AUTO'
            triggered_by_user INTEGER,
            
            -- Details
            update_details JSONB
        );
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_update_log_source ON screening_update_logs(source_name);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_update_log_date ON screening_update_logs(update_started_at DESC);")
    
    print("[OK] Created screening_update_logs table")
    
    # Table 6: Screening Configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS screening_config (
            id SERIAL PRIMARY KEY,
            
            -- Configuration key-value
            config_key VARCHAR(100) UNIQUE NOT NULL,
            config_value TEXT NOT NULL,
            config_type VARCHAR(20) DEFAULT 'STRING',  -- 'STRING', 'FLOAT', 'INTEGER', 'BOOLEAN'
            
            -- Description
            description TEXT,
            category VARCHAR(50),  -- 'ALGORITHMS', 'THRESHOLDS', 'ADJUSTMENTS'
            
            -- Validation
            min_value DECIMAL(10,4),
            max_value DECIMAL(10,4),
            
            -- System
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by INTEGER
        );
    """)
    
    print("[OK] Created screening_config table")
    
    # Insert default configuration (per specifications)
    cursor.execute("""
        INSERT INTO screening_config (config_key, config_value, config_type, description, category, min_value, max_value) VALUES
        ('fuzzy_ratio_weight', '0.40', 'FLOAT', 'Weight for Levenshtein fuzzy ratio', 'ALGORITHMS', 0.0, 1.0),
        ('jaro_winkler_weight', '0.30', 'FLOAT', 'Weight for Jaro-Winkler algorithm', 'ALGORITHMS', 0.0, 1.0),
        ('phonetic_weight', '0.20', 'FLOAT', 'Weight for phonetic matching (Soundex + Metaphone)', 'ALGORITHMS', 0.0, 1.0),
        ('partial_ratio_weight', '0.10', 'FLOAT', 'Weight for partial substring matching', 'ALGORITHMS', 0.0, 1.0),
        ('exact_match_favoritism', '25.0', 'FLOAT', 'Bonus for exact token matches (%)', 'ADJUSTMENTS', 0.0, 50.0),
        ('dob_exact_match_bonus', '10.0', 'FLOAT', 'Bonus for exact DOB match (%)', 'ADJUSTMENTS', 0.0, 20.0),
        ('dob_mismatch_penalty', '-10.0', 'FLOAT', 'Penalty for DOB mismatch (%)', 'ADJUSTMENTS', -20.0, 0.0),
        ('nationality_bonus', '5.0', 'FLOAT', 'Bonus for nationality match (%)', 'ADJUSTMENTS', 0.0, 10.0),
        ('confirmed_hit_threshold', '95.0', 'FLOAT', 'Threshold for confirmed hit (%)', 'THRESHOLDS', 0.0, 100.0),
        ('potential_match_threshold', '80.0', 'FLOAT', 'Threshold for potential match (%)', 'THRESHOLDS', 0.0, 100.0),
        ('low_match_threshold', '70.0', 'FLOAT', 'Threshold for low match (%)', 'THRESHOLDS', 0.0, 100.0)
        ON CONFLICT (config_key) DO NOTHING;
    """)
    
    print("[OK] Inserted default configuration")
    
    # Insert data sources
    cursor.execute("""
        INSERT INTO screening_data_sources (source_name, source_display_name, source_url, source_type, is_official, update_frequency_hours) VALUES
        ('opensanctions', 'OpenSanctions (Aggregated)', 'https://data.opensanctions.org/datasets/latest/default/entities.ftm.json', 'JSON', FALSE, 24),
        ('un_consolidated', 'UN Security Council Consolidated List', 'https://scsanctions.un.org/resources/xml/en/consolidated.xml', 'XML', TRUE, 24),
        ('ofac_sdn', 'OFAC SDN List (US Treasury)', 'https://www.treasury.gov/ofac/downloads/sdn.xml', 'XML', TRUE, 24),
        ('eu_sanctions', 'EU Financial Sanctions', 'https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw', 'XML', TRUE, 24),
        ('uk_hmt', 'UK HMT Consolidated List', 'https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/1069750/ConList.csv', 'CSV', TRUE, 24),
        ('emlcu_egypt', 'EMLCU Egyptian Terrorist List', 'https://www.mlcu.org.eg/ar/3125/', 'HTML_SCRAPE', TRUE, 168)
        ON CONFLICT (source_name) DO NOTHING;
    """)
    
    print("[OK] Inserted data sources")
    
    # Commit all changes
    conn.commit()
    
    print("")
    print("=" * 50)
    print("[SUCCESS] Database schema created successfully!")
    print("=" * 50)
    print(f"Database: {DB_CONFIG['dbname']}")
    print(f"Tables created: 6")
    print("")
    
    # Show table counts
    cursor.execute("SELECT COUNT(*) FROM screening_watchlist;")
    watchlist_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM screening_data_sources;")
    sources_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM screening_config;")
    config_count = cursor.fetchone()[0]
    
    print(f"Watchlist records: {watchlist_count}")
    print(f"Data sources: {sources_count}")
    print(f"Config entries: {config_count}")
    print("")
    
    cursor.close()
    conn.close()


if __name__ == "__main__":
    create_schema()
