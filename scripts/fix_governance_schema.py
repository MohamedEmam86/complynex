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

import sys
import os
import sqlite3

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import get_db
from app import create_app

def fix_schema():
    app = create_app()
    with app.app_context():
        db = get_db()
        print("Checking and fixing Governance schema...")
        
        # Check board_members columns
        try:
            columns = db.execute("PRAGMA table_info(board_members)").fetchall()
            col_names = [col['name'] for col in columns]
            
            if 'member_name_arabic' not in col_names:
                print("Adding member_name_arabic to board_members...")
                db.execute("ALTER TABLE board_members ADD COLUMN member_name_arabic VARCHAR(255)")
            else:
                print("member_name_arabic already exists.")
                
            if 'term_end_date' not in col_names: # Check another one just in case
                print("Adding term_end_date to board_members...")
                db.execute("ALTER TABLE board_members ADD COLUMN term_end_date DATE")
                
        except sqlite3.OperationalError as e:
            print(f"Error checking board_members: {e}")
            # If table doesn't exist, schema.sql should have created it?
            # Creating it if not exists would be better but verify_governance implies it exists.

        db.commit()
        print("Schema fix complete.")

if __name__ == '__main__':
    fix_schema()
