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

DB_PATH = 'C:/Users/HP 835/Downloads/Kimi_Agent_Complynexpay Compliance Gem Design/complynex_cms/complynex_cms.db'

def fix_governance_schema():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Define the required columns for governance tables based on schema.sql
    schema_definitions = {
        'board_members': [
            ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
            ('member_name', 'VARCHAR(255) NOT NULL'),
            ('member_name_arabic', 'VARCHAR(255)'),
            ('role', 'VARCHAR(100) NOT NULL'),
            ('is_independent', 'BOOLEAN DEFAULT 0'),
            ('is_executive', 'BOOLEAN DEFAULT 0'),
            ('expertise_areas', 'TEXT'),
            ('appointment_date', 'DATE NOT NULL'),
            ('term_end_date', 'DATE'),
            ('email', 'VARCHAR(255)'),
            ('phone', 'VARCHAR(50)'),
            ('bio', 'TEXT'),
            ('status', 'VARCHAR(20) DEFAULT "ACTIVE"')
        ],
        'board_committees': [
            ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
            ('committee_name', 'VARCHAR(255) NOT NULL'),
            ('committee_type', 'VARCHAR(50)'),
            ('chairman_id', 'INTEGER'),
            ('charter_file', 'VARCHAR(500)'),
            ('meeting_frequency', 'VARCHAR(50)'),
            ('is_active', 'BOOLEAN DEFAULT 1')
        ],
        'committee_memberships': [
            ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
            ('committee_id', 'INTEGER NOT NULL'),
            ('member_id', 'INTEGER NOT NULL'),
            ('role', 'VARCHAR(50) DEFAULT "MEMBER"'),
            ('joined_date', 'DATE')
        ],
        'board_meetings': [
            ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
            ('meeting_type', 'VARCHAR(50)'),
            ('committee_id', 'INTEGER'),
            ('meeting_date', 'DATE NOT NULL'),
            ('meeting_time', 'TIME'),
            ('location', 'VARCHAR(255)'),
            ('agenda', 'TEXT'),
            ('minutes_file', 'VARCHAR(500)'),
            ('quorum_met', 'BOOLEAN DEFAULT 0'),
            ('status', 'VARCHAR(20) DEFAULT "SCHEDULED"')
        ],
        'meeting_attendance': [
            ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
            ('meeting_id', 'INTEGER NOT NULL'),
            ('member_id', 'INTEGER NOT NULL'),
            ('attended', 'BOOLEAN DEFAULT 0'),
            ('apology_received', 'BOOLEAN DEFAULT 0'),
            ('proxy_name', 'VARCHAR(255)')
        ],
        'board_decisions': [
            ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
            ('meeting_id', 'INTEGER NOT NULL'),
            ('decision_number', 'VARCHAR(50)'),
            ('decision_text', 'TEXT NOT NULL'),
            ('responsible_person', 'VARCHAR(255)'),
            ('deadline', 'DATE'),
            ('status', 'VARCHAR(20) DEFAULT "PENDING"'),
            ('completion_date', 'DATE')
        ]
    }

    for table_name, columns in schema_definitions.items():
        print(f"\nChecking table: {table_name}")
        
        # Check if table exists
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if not cursor.fetchone():
            print(f"Table {table_name} does not exist. Creating it.")
            col_defs = ", ".join([f"{col[0]} {col[1]}" for col in columns])
            cursor.execute(f"CREATE TABLE {table_name} ({col_defs})")
            continue

        # Table exists, check columns
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_cols = {row['name']: row for row in cursor.fetchall()}
        
        for col_name, col_type in columns:
            if col_name not in existing_cols:
                print(f"Adding column {col_name} to {table_name}")
                # Note: This is an oversimplification as it doesn't handle NOT NULL without defaults well,
                # but for this specific database and schema it should be fine.
                try:
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError as e:
                    print(f"Error adding column {col_name}: {e}")
            else:
                pass # Column exists

    conn.commit()
    conn.close()
    print("\nGovernance schema fix completed successfully.")

if __name__ == '__main__':
    fix_governance_schema()
