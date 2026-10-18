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

def migrate():
    db_path = os.path.join('complynex_cms', 'complynex_cms.db')
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get current columns
    cursor.execute("PRAGMA table_info(customers)")
    columns = [row[1] for row in cursor.fetchall()]

    # Missing columns to add
    to_add = [
        ('is_pep', 'INTEGER DEFAULT 0'),
        ('is_sanctioned', 'INTEGER DEFAULT 0'),
        ('is_high_risk_country', 'INTEGER DEFAULT 0'),
        ('nationality', 'TEXT'),
        ('requires_edd', 'INTEGER DEFAULT 0'),
        ('edd_completed', 'INTEGER DEFAULT 0'),
        ('risk_classification', "TEXT DEFAULT 'MEDIUM'"),
        ('risk_classification_date', 'DATE'),
        ('risk_classification_reason', 'TEXT'),
        ('risk_classified_by', 'INTEGER'),
        ('risk_override_reason', 'TEXT'),
        ('edd_approved_by', 'INTEGER'),
        ('edd_approval_date', 'DATE'),
        ('annual_income_range', 'TEXT'),
        ('business_activity', 'TEXT')
    ]

    for col_name, col_type in to_add:
        if col_name not in columns:
            print(f"Adding column {col_name}...")
            try:
                cursor.execute(f"ALTER TABLE customers ADD COLUMN {col_name} {col_type}")
                print(f"Column {col_name} added successfully.")
            except sqlite3.OperationalError as e:
                print(f"Error adding {col_name}: {e}")
        else:
            print(f"Column {col_name} already exists.")

    conn.commit()
    conn.close()
    print("Migration completed.")

if __name__ == "__main__":
    migrate()
