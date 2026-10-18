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

def fix_timestamps():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        print("Checking coi_declarations for bad timestamps...")
        cursor.execute("SELECT id, declaration_date FROM coi_declarations")
        rows = cursor.fetchall()
        
        fixed_count = 0
        for row in rows:
            date_val = row['declaration_date']
            if date_val and len(date_val) == 10: # YYYY-MM-DD
                new_val = f"{date_val} 00:00:00"
                print(f"Fixing ID {row['id']}: {date_val} -> {new_val}")
                cursor.execute(
                    "UPDATE coi_declarations SET declaration_date = ? WHERE id = ?",
                    (new_val, row['id'])
                )
                fixed_count += 1
        
        if fixed_count > 0:
            conn.commit()
            print(f"Fixed {fixed_count} records.")
        else:
            print("No records needed fixing.")
            
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    fix_timestamps()
