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
Database Migration: Add Internal Blacklist Tables
Creates tables for managing internal blacklist entries
"""

import sqlite3
import os
from datetime import datetime

def run_migration(db_path='complynex_cms.db'):
    """Run the internal blacklist migration"""
    
    print("=" * 60)
    print("INTERNAL BLACKLIST MIGRATION")
    print("=" * 60)
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create internal_blacklist table
        print("\n[1/4] Creating internal_blacklist table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS internal_blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                
                -- Entity Information
                full_name VARCHAR(500) NOT NULL,
                original_name VARCHAR(500),  -- Arabic or original script
                entity_type VARCHAR(20) NOT NULL DEFAULT 'INDIVIDUAL',  -- INDIVIDUAL or ORGANIZATION
                
                -- Identifiers
                national_id VARCHAR(50),
                passport_number VARCHAR(50),
                date_of_birth DATE,
                place_of_birth VARCHAR(200),
                nationality VARCHAR(100),
                
                -- Organization Info (if entity_type = ORGANIZATION)
                registration_number VARCHAR(100),
                
                -- Location
                address TEXT,
                city VARCHAR(100),
                country VARCHAR(100),
                
                -- Blacklist Details
                reason TEXT NOT NULL,  -- Why blacklisted
                risk_level VARCHAR(20) DEFAULT 'HIGH',  -- HIGH, MEDIUM, LOW
                category VARCHAR(50),  -- e.g., "Fraud", "Money Laundering", "Terrorism"
                
                -- Additional Info
                aliases TEXT,  -- JSON array of alternative names
                notes TEXT,
                phone_number VARCHAR(50),
                email VARCHAR(200),
                
                -- Source Tracking
                source VARCHAR(100) DEFAULT 'INTERNAL',
                source_id VARCHAR(100) UNIQUE,
                added_by INTEGER,  -- User ID who added this entry
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                modified_by INTEGER,
                modified_date TIMESTAMP,
                
                -- Status
                is_active BOOLEAN DEFAULT 1,
                expiry_date DATE,  -- Optional: when this entry expires
                
                -- Metadata
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                FOREIGN KEY (added_by) REFERENCES users(id),
                FOREIGN KEY (modified_by) REFERENCES users(id)
            )
        """)
        print("   ✅ internal_blacklist table created")
        
        # Create indexes
        print("\n[2/4] Creating indexes...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_internal_blacklist_name 
            ON internal_blacklist(full_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_internal_blacklist_entity_type 
            ON internal_blacklist(entity_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_internal_blacklist_active 
            ON internal_blacklist(is_active)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_internal_blacklist_risk 
            ON internal_blacklist(risk_level)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_internal_blacklist_national_id 
            ON internal_blacklist(national_id)
        """)
        print("   ✅ Indexes created")
        
        # Create audit log table for blacklist changes
        print("\n[3/4] Creating internal_blacklist_audit table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS internal_blacklist_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blacklist_id INTEGER NOT NULL,
                action VARCHAR(20) NOT NULL,  -- ADDED, MODIFIED, DELETED, ACTIVATED, DEACTIVATED
                field_changed VARCHAR(100),
                old_value TEXT,
                new_value TEXT,
                changed_by INTEGER,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reason TEXT,
                
                FOREIGN KEY (blacklist_id) REFERENCES internal_blacklist(id),
                FOREIGN KEY (changed_by) REFERENCES users(id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_blacklist_audit_entry 
            ON internal_blacklist_audit(blacklist_id)
        """)
        print("   ✅ internal_blacklist_audit table created")
        
        # Create bulk import tracking table
        print("\n[4/4] Creating blacklist_bulk_imports table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blacklist_bulk_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename VARCHAR(255),
                total_records INTEGER,
                successful_imports INTEGER,
                failed_imports INTEGER,
                imported_by INTEGER,
                import_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                error_log TEXT,  -- JSON of errors
                
                FOREIGN KEY (imported_by) REFERENCES users(id)
            )
        """)
        print("   ✅ blacklist_bulk_imports table created")
        
        # Update screening_data_sources to include internal blacklist
        print("\n[BONUS] Adding internal blacklist to screening sources...")
        cursor.execute("""
            SELECT COUNT(*) FROM screening_data_sources 
            WHERE source_name = 'internal_blacklist'
        """)
        
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO screening_data_sources 
                (name, type, source_name, is_active, priority, description)
                VALUES 
                ('Internal Blacklist', 'INTERNAL', 'internal_blacklist', 1, 1, 
                 'Manually managed internal blacklist entries')
            """)
            print("   ✅ Internal blacklist added to screening sources")
        else:
            print("   ℹ️  Internal blacklist already exists in screening sources")
        
        # Commit changes
        conn.commit()
        
        print("\n" + "=" * 60)
        print("✅ MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print("\nTables created:")
        print("  1. internal_blacklist")
        print("  2. internal_blacklist_audit")
        print("  3. blacklist_bulk_imports")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import sys
    
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'complynex_cms.db'
    
    print(f"Database: {db_path}")
    print()
    
    success = run_migration(db_path)
    
    sys.exit(0 if success else 1)
