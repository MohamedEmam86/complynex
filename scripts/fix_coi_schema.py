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

def fix_schema():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Get existing columns
        cursor.execute("PRAGMA table_info(coi_declarations)")
        existing_columns = [col[1] for col in cursor.fetchall()]
        print(f"Existing columns: {existing_columns}")

        # List of columns to add
        new_columns = [
            ('has_financial_interests', 'BOOLEAN DEFAULT 0'),
            ('financial_interests_details', 'TEXT'),
            ('has_family_in_competitor', 'BOOLEAN DEFAULT 0'),
            ('family_competitor_details', 'TEXT'),
            ('has_family_in_supplier', 'BOOLEAN DEFAULT 0'),
            ('family_supplier_details', 'TEXT'),
            ('has_outside_employment', 'BOOLEAN DEFAULT 0'),
            ('outside_employment_details', 'TEXT'),
            ('has_received_gifts', 'BOOLEAN DEFAULT 0'),
            ('gifts_details', 'TEXT'),
            ('has_other_conflicts', 'BOOLEAN DEFAULT 0'),
            ('other_conflicts_details', 'TEXT'),
            ('declaration_statement', 'TEXT'),
            ('digital_signature', 'TEXT'),
            ('pin_code', 'VARCHAR(10)')
        ]

        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                print(f"Adding column {col_name}...")
                cursor.execute(f"ALTER TABLE coi_declarations ADD COLUMN {col_name} {col_type}")
            else:
                print(f"Column {col_name} already exists.")

        conn.commit()
        print("Schema fix completed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"Schema fix failed: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    fix_schema()
