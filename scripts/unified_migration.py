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

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex_cms.db')

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print(f"Starting migration for {DB_PATH}...")

    # 1. Migrate screening_data_sources
    cur.execute("PRAGMA table_info(screening_data_sources)")
    columns = [row['name'] for row in cur.fetchall()]
    
    # Renames
    renames = {
        'name': 'source_name',
        'display_name': 'source_display_name',
        'type': 'source_type'
    }
    
    for old_name, new_name in renames.items():
        if old_name in columns and new_name not in columns:
            print(f"Renaming column {old_name} to {new_name}...")
            cur.execute(f"ALTER TABLE screening_data_sources RENAME COLUMN {old_name} TO {new_name}")
        elif old_name in columns and new_name in columns:
            # Handle conflict if both exist for some reason
            print(f"Warning: Both {old_name} and {new_name} exist. Dropping old {old_name}.")
            cur.execute(f"ALTER TABLE screening_data_sources DROP COLUMN {old_name}")

    # Add missing columns
    cur.execute("PRAGMA table_info(screening_data_sources)")
    updated_columns = [row['name'] for row in cur.fetchall()]
    
    new_cols = [
        ("last_update_attempt", "TIMESTAMP"),
        ("next_scheduled_update", "TIMESTAMP"),
        ("records_added_last_update", "INTEGER DEFAULT 0"),
        ("records_updated_last_update", "INTEGER DEFAULT 0"),
        ("consecutive_failures", "INTEGER DEFAULT 0"),
        ("last_error_message", "TEXT"),
        ("updated_at", "TIMESTAMP"),
        ("updated_by", "INTEGER")
    ]
    
    for col_name, col_def in new_cols:
        if col_name not in updated_columns:
            print(f"Adding column {col_name}...")
            cur.execute(f"ALTER TABLE screening_data_sources ADD COLUMN {col_name} {col_def}")

    # 2. Create screening_update_logs (plural) if missing
    cur.execute("""
        CREATE TABLE IF NOT EXISTS screening_update_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name VARCHAR(100) NOT NULL,
            update_started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            update_completed_at TIMESTAMP,
            duration_seconds INTEGER,
            records_added INTEGER DEFAULT 0,
            records_updated INTEGER DEFAULT 0,
            update_status VARCHAR(20) DEFAULT 'IN_PROGRESS', -- 'IN_PROGRESS', 'SUCCESS', 'FAILED', 'PARTIAL'
            triggered_by VARCHAR(50) DEFAULT 'SYSTEM', -- 'SYSTEM', 'MANUAL'
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("Table screening_update_logs (plural) is ready.")

    # 3. Create customer_transactions table for Transaction Analysis (Phase 4)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customer_transactions (
            id VARCHAR(50) PRIMARY KEY,
            customer_id VARCHAR(50) NOT NULL,
            amount DECIMAL(18, 2) NOT NULL,
            currency VARCHAR(3) DEFAULT 'EGP',
            transaction_type VARCHAR(20), -- 'TRANSFER', 'DEPOSIT', 'WITHDRAWAL'
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT,
            status VARCHAR(10) DEFAULT 'COMPLETED'
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_customer ON customer_transactions(customer_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON customer_transactions(timestamp)")
    print("Table customer_transactions is ready.")

    # 4. Add adverse_media column to screening_results
    cur.execute("PRAGMA table_info(screening_results)")
    screening_columns = [row['name'] for row in cur.fetchall()]
    if 'adverse_media' not in screening_columns:
        print("Adding column adverse_media to screening_results...")
        cur.execute("ALTER TABLE screening_results ADD COLUMN adverse_media TEXT")
    
    if 'adverse_media_summary' not in screening_columns:
        print("Adding column adverse_media_summary to screening_results...")
        cur.execute("ALTER TABLE screening_results ADD COLUMN adverse_media_summary TEXT")


    conn.commit()
    conn.close()
    print("Migration successful.")

if __name__ == "__main__":
    migrate()
