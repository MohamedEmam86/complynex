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
    db_path = 'complynex_cms.db'
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if is_mandatory exists in policies
    cursor.execute("PRAGMA table_info(policies)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'is_mandatory' not in columns:
        print("Adding is_mandatory column to policies table...")
        cursor.execute("ALTER TABLE policies ADD COLUMN is_mandatory BOOLEAN DEFAULT 0")
        conn.commit()
    else:
        print("is_mandatory column already exists.")

    print("Migration completed successfully.")
    conn.close()

if __name__ == "__main__":
    migrate()
