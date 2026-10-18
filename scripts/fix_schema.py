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
Complete Screening Schema Migration
Adds all missing columns and indexes for production use.
Based on ULTIMATE_COMPLYNEX_FIXING_GUIDE.md
"""

import sqlite3
import sys
import os
import shutil
from datetime import datetime
from flask import Flask

# Add parent directory to path to import config if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_db_path():
    """Determine database path using the same logic as config.py"""
    # Try complynex_cms/complynex_cms.db (Production DB - Subdir)
    prod_db_subdir = os.path.join(os.getcwd(), 'complynex_cms', 'complynex_cms.db')
    # Try complynex_cms.db (Production DB - Root)
    prod_db_root = os.path.join(os.getcwd(), 'complynex_cms.db')
    # Try complynex.db in root (Dev DB)
    root_db = os.path.join(os.getcwd(), 'complynex.db')
    
    if os.path.exists(prod_db_subdir):
        return prod_db_subdir
    elif os.path.exists(prod_db_root):
        return prod_db_root
    elif os.path.exists(root_db):
        return root_db
    else:
        # Default to dev
        return os.path.join(os.getcwd(), 'complynex.db')

def migrate_screening_schema():
    """Apply complete screening schema migration"""
    
    db_path = get_db_path()
    
    print("=" * 60)
    print("SCREENING SCHEMA MIGRATION")
    print("=" * 60)
    print(f"Database: {db_path}")
    print(f"Time: {datetime.now()}")
    print()
    
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        return False

    # Backup database
    backup_path = f"{db_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        shutil.copy2(db_path, backup_path)
        print(f"✓ Backup created: {backup_path}")
    except Exception as e:
        print(f"✗ Failed to create backup: {e}")
        return False
    print()
    
    conn = sqlite3.connect(db_path)
    # Enable accessing columns by name
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # 1. Add missing columns to screening_watchlist
        print("1. Updating screening_watchlist table...")
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='screening_watchlist'")
        if not cursor.fetchone():
            print("   - Table screening_watchlist does not exist! Creating it...")
            cursor.execute("""
                CREATE TABLE screening_watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    dataset TEXT,
                    source TEXT,
                    type TEXT,
                    list_type TEXT,
                    reference_number TEXT,
                    aliases TEXT,
                    details TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("   ✓ Created screening_watchlist table")

        columns_to_add = [
            ("name_normalized", "TEXT"),
            ("name_soundex", "TEXT"),
            ("original_script", "TEXT DEFAULT 'latin'"),
            ("aliases", "TEXT"),  # JSON array
            ("risk_score", "INTEGER DEFAULT 100"),
            ("risk_category", "TEXT"),
            ("entity_type", "TEXT"),
            ("nationality", "TEXT"),
            ("date_of_birth", "DATE"),
            ("last_updated", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("active", "BOOLEAN DEFAULT 1")
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE screening_watchlist ADD COLUMN {col_name} {col_type}")
                print(f"   ✓ Added column: {col_name}")
            except sqlite3.OperationalError as e:
                # SQLite throws error if column exists
                if "duplicate column name" in str(e):
                    print(f"   - Column {col_name} already exists")
                else:
                    print(f"   ✗ Error adding {col_name}: {e}")
        
        # 2. Add missing columns to screening_results
        print("\n2. Updating screening_results table...")
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='screening_results'")
        if not cursor.fetchone():
             print("   - Table screening_results does not exist! Creating it...")
             cursor.execute("""
                CREATE TABLE screening_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reference_id TEXT,
                    screened_name TEXT,
                    screened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    match_status TEXT,
                    risk_score REAL DEFAULT 0,
                    match_details TEXT,
                    reviewed_by INTEGER,
                    reviewed_at TIMESTAMP,
                    false_positive BOOLEAN DEFAULT 0
                )
             """)
             print("   ✓ Created screening_results table")

        columns_to_add = [
            ("match_details", "TEXT"),  # JSON
            ("risk_score", "REAL DEFAULT 0"),
            ("reviewed_by", "INTEGER"),
            ("reviewed_at", "TIMESTAMP"),
            ("false_positive", "BOOLEAN DEFAULT 0"),
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE screening_results ADD COLUMN {col_name} {col_type}")
                print(f"   ✓ Added column: {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    print(f"   - Column {col_name} already exists")
                else:
                    print(f"   ✗ Error adding {col_name}: {e}")
        
        # 3. Create/Update screening_update_log
        print("\n3. Updating screening_update_log table...")
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='screening_update_log'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE screening_update_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    update_type TEXT DEFAULT 'AUTO',
                    records_added INTEGER DEFAULT 0,
                    records_updated INTEGER DEFAULT 0,
                    records_skipped INTEGER DEFAULT 0,
                    records_failed INTEGER DEFAULT 0,
                    update_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT,
                    error_message TEXT,
                    execution_time_seconds REAL,
                    file_hash TEXT
                )
            """)
            print("   ✓ Created screening_update_log table")
        else:
             # Add columns if missing
            columns_to_add = [
                ("update_type", "TEXT DEFAULT 'AUTO'"),
                ("execution_time_seconds", "REAL"),
                ("file_hash", "TEXT")
            ]
            for col_name, col_type in columns_to_add:
                try:
                    cursor.execute(f"ALTER TABLE screening_update_log ADD COLUMN {col_name} {col_type}")
                    print(f"   ✓ Added column: {col_name}")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" in str(e):
                         print(f"   - Column {col_name} already exists")
        
        # 4. Create screening_config table
        print("\n4. Creating screening_config table...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='screening_config'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE screening_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_key TEXT UNIQUE NOT NULL,
                    config_value TEXT,
                    config_type TEXT DEFAULT 'string',
                    is_encrypted INTEGER DEFAULT 0,
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by INTEGER
                )
            """)
            
            # Insert defaults
            cursor.execute("""
            INSERT OR IGNORE INTO screening_config (config_key, config_value, config_type, description) VALUES
                ('newsapi_key', '', 'string', 'NewsAPI.org API key'),
                ('newsapi_enabled', 'true', 'bool', 'Enable NewsAPI'),
                ('emlcu_cache_days', '3', 'int', 'EMLCU cache days')
            """)
            print("   ✓ Created screening_config table with defaults")
        else:
            print("   - Table screening_config already exists")

        # 5. Create indexes
        print("\n5. Creating indexes...")
        
        indexes = [
            ("idx_watchlist_normalized", "CREATE INDEX IF NOT EXISTS idx_watchlist_normalized ON screening_watchlist(name_normalized)"),
            ("idx_watchlist_soundex", "CREATE INDEX IF NOT EXISTS idx_watchlist_soundex ON screening_watchlist(name_soundex)"),
            ("idx_results_status", "CREATE INDEX IF NOT EXISTS idx_results_status ON screening_results(match_status)"),
            ("idx_results_date", "CREATE INDEX IF NOT EXISTS idx_results_date ON screening_results(screened_at)"),
            ("idx_watchlist_source", "CREATE INDEX IF NOT EXISTS idx_watchlist_source ON screening_watchlist(source)")
        ]
        
        for idx_name, idx_sql in indexes:
            try:
                cursor.execute(idx_sql)
                print(f"   ✓ Created index: {idx_name}")
            except Exception as e:
                print(f"   ✗ Error creating {idx_name}: {e}")
        
        # 6. Populate normalized fields for existing records
        print("\n6. Populating normalized fields...")
        
        # Only populate if name_normalized is NULL
        cursor.execute("SELECT COUNT(*) FROM screening_watchlist WHERE name_normalized IS NULL")
        count_to_update = cursor.fetchone()[0]
        
        if count_to_update > 0:
            print(f"   - Found {count_to_update} records needing normalization")
            import jellyfish
            
            cursor.execute("SELECT id, name FROM screening_watchlist WHERE name_normalized IS NULL")
            records = cursor.fetchall()
            
            updated_count = 0
            for row in records:
                record_id = row['id']
                name = row['name']
                
                if name:
                    # Simple normalization: uppercase, alphanumeric only
                    normalized = "".join(c for c in name if c.isalnum() or c.isspace()).strip().upper()
                    soundex = jellyfish.soundex(normalized) if normalized else None
                    
                    cursor.execute(
                        "UPDATE screening_watchlist SET name_normalized = ?, name_soundex = ? WHERE id = ?",
                        (normalized, soundex, record_id)
                    )
                    updated_count += 1
                    
                    if updated_count % 1000 == 0:
                        print(f"     ... updated {updated_count} records")
            
            print(f"   ✓ Normalized {updated_count} existing records")
        else:
            print(f"   - All records already normalized")
        
        # Commit all changes
        conn.commit()
        
        print("\n" + "=" * 60)
        print("✓ MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n✗ MIGRATION FAILED: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
        print(f"Database restored from backup: {backup_path}")
        return False
        
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    migrate_screening_schema()
