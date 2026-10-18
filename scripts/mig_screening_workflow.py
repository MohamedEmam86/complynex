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
Migration Script: Screening Workflow System
Creates new tables and adds columns required for the comprehensive screening workflow.
Run once to set up the database schema.
"""

import sqlite3
import os
import sys

# Navigate to the project root to find the DB
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, 'complynex_cms.db')

def run_migration():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database not found at: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    print(f"[INFO] Connected to: {DB_PATH}")

    # Helper to check if a column exists
    def column_exists(table, column):
        cur.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cur.fetchall())

    # Helper to check if a table exists
    def table_exists(table):
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return cur.fetchone() is not None

    # =========================================================================
    # 1. CREATE screening_history TABLE
    # =========================================================================
    if not table_exists('screening_history'):
        print("[CREATING] screening_history table...")
        cur.execute("""
            CREATE TABLE screening_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_name TEXT NOT NULL,
                entity_type TEXT DEFAULT 'Individual',
                screening_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                screening_type TEXT DEFAULT 'Manual',
                initiated_by INTEGER,
                source_module TEXT,
                source_record_id INTEGER,
                total_matches_found INTEGER DEFAULT 0,
                high_risk_matches INTEGER DEFAULT 0,
                auto_cleared_matches INTEGER DEFAULT 0,
                highest_score REAL DEFAULT 0.0,
                screening_result TEXT,
                matches_json TEXT,
                status TEXT DEFAULT 'Completed',
                resolution_date TIMESTAMP,
                resolved_by INTEGER,
                notes TEXT,
                processing_time_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("CREATE INDEX idx_sh_entity ON screening_history(entity_name)")
        cur.execute("CREATE INDEX idx_sh_source ON screening_history(source_module, source_record_id)")
        cur.execute("CREATE INDEX idx_sh_status ON screening_history(status)")
        cur.execute("CREATE INDEX idx_sh_date ON screening_history(screening_date)")
        print("[OK] screening_history created.")
    else:
        print("[SKIP] screening_history already exists.")

    # =========================================================================
    # 2. CREATE screening_queue TABLE
    # =========================================================================
    if not table_exists('screening_queue'):
        print("[CREATING] screening_queue table...")
        cur.execute("""
            CREATE TABLE screening_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                screening_history_id INTEGER,
                entity_name TEXT NOT NULL,
                entity_type TEXT DEFAULT 'Individual',
                match_name TEXT,
                match_score REAL DEFAULT 0.0,
                list_source TEXT,
                match_details TEXT,
                assigned_to INTEGER,
                priority TEXT DEFAULT 'Medium',
                status TEXT DEFAULT 'Pending',
                resolution TEXT,
                resolution_notes TEXT,
                resolved_by INTEGER,
                resolved_date TIMESTAMP,
                escalated INTEGER DEFAULT 0,
                escalation_reason TEXT,
                source_module TEXT,
                source_record_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (screening_history_id) REFERENCES screening_history(id)
            )
        """)
        cur.execute("CREATE INDEX idx_sq_status ON screening_queue(status)")
        cur.execute("CREATE INDEX idx_sq_assigned ON screening_queue(assigned_to)")
        cur.execute("CREATE INDEX idx_sq_priority ON screening_queue(priority)")
        cur.execute("CREATE INDEX idx_sq_source ON screening_queue(source_module, source_record_id)")
        print("[OK] screening_queue created.")
    else:
        print("[SKIP] screening_queue already exists.")

    # =========================================================================
    # 3. ENHANCE screening_whitelist TABLE (add new columns)
    # =========================================================================
    print("[ENHANCING] screening_whitelist table...")
    wl_columns = {
        'entity_type': "TEXT DEFAULT 'Individual'",
        'national_id': "TEXT",
        'commercial_registry': "TEXT",
        'date_of_birth': "DATE",
        'nationality': "TEXT",
        'original_match_name': "TEXT",
        'original_match_score': "REAL",
        'original_list_source': "TEXT",
        'approved_by': "INTEGER",
        'approval_date': "TIMESTAMP",
        'review_date': "DATE",
        'status': "TEXT DEFAULT 'Active'",
        'notes': "TEXT",
    }
    for col_name, col_type in wl_columns.items():
        if not column_exists('screening_whitelist', col_name):
            cur.execute(f"ALTER TABLE screening_whitelist ADD COLUMN {col_name} {col_type}")
            print(f"  [+] screening_whitelist.{col_name}")
        else:
            print(f"  [=] screening_whitelist.{col_name} exists")
    print("[OK] screening_whitelist enhanced.")

    # =========================================================================
    # 4. ALTER merchants TABLE (add screening-related columns)
    # =========================================================================
    print("[ENHANCING] merchants table...")
    merchant_columns = {
        'internal_reference_number': "VARCHAR(50)",
        'internal_account_number': "VARCHAR(50)",
        'screening_status': "VARCHAR(20) DEFAULT 'Not Screened'",
        'last_screening_date': "DATETIME",
        'last_screened_by': "INTEGER",
        'risk_rating': "VARCHAR(20)",
        'pep_status': "BOOLEAN DEFAULT 0",
        'screening_notes': "TEXT",
        'onboarding_status': "VARCHAR(30) DEFAULT 'Pending Screening'",
    }
    for col_name, col_type in merchant_columns.items():
        if not column_exists('merchants', col_name):
            cur.execute(f"ALTER TABLE merchants ADD COLUMN {col_name} {col_type}")
            print(f"  [+] merchants.{col_name}")
        else:
            print(f"  [=] merchants.{col_name} exists")
    print("[OK] merchants enhanced.")

    # =========================================================================
    # 5. ALTER customers TABLE (add screening-related columns)
    # =========================================================================
    print("[ENHANCING] customers table...")
    customer_columns = {
        'screening_status': "VARCHAR(20) DEFAULT 'Not Screened'",
        'last_screening_date': "DATETIME",
        'last_screened_by': "INTEGER",
        'screening_notes': "TEXT",
    }
    for col_name, col_type in customer_columns.items():
        if not column_exists('customers', col_name):
            cur.execute(f"ALTER TABLE customers ADD COLUMN {col_name} {col_type}")
            print(f"  [+] customers.{col_name}")
        else:
            print(f"  [=] customers.{col_name} exists")
    print("[OK] customers enhanced.")

    # =========================================================================
    # COMMIT
    # =========================================================================
    conn.commit()
    conn.close()
    print("\n[SUCCESS] Migration complete! All tables and columns are ready.")


if __name__ == '__main__':
    run_migration()
