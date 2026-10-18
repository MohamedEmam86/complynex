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

    try:
        # 1. Update board_members table
        print("Updating board_members table...")
        try:
            cursor.execute("ALTER TABLE board_members ADD COLUMN document_path VARCHAR(500)")
        except sqlite3.OperationalError as e:
            print(f"  Note: {e}")

        # 2. Update users table with modular permissions
        print("Updating users table...")
        columns = [
            'perm_governance', 'perm_aml', 'perm_policies', 
            'perm_reports', 'perm_pdpl', 'perm_training'
        ]
        for col in columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} VARCHAR(20) DEFAULT 'none'")
            except sqlite3.OperationalError as e:
                print(f"  Note for {col}: {e}")

        # 3. Update board_meetings (Recreate to change CHECK constraint)
        print("Updating board_meetings table (recreating to update constraints)...")
        cursor.execute("PRAGMA foreign_keys=OFF")
        
        cursor.execute("ALTER TABLE board_meetings RENAME TO board_meetings_old")
        
        cursor.execute('''
            CREATE TABLE board_meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_type VARCHAR(50) CHECK (meeting_type IN ('BOARD', 'AUDIT_COMMITTEE', 'RISK_COMMITTEE', 'COMPLIANCE_COMMITTEE', 'NOMREM_COMMITTEE', 'REGULAR', 'EXTRAORDINARY', 'EMERGENCY')),
                committee_id INTEGER,
                meeting_date DATE NOT NULL,
                meeting_time TIME,
                location VARCHAR(255),
                agenda TEXT,
                minutes_file VARCHAR(500),
                quorum_met BOOLEAN DEFAULT 0,
                status VARCHAR(20) DEFAULT 'SCHEDULED',
                meeting_reference VARCHAR(255),
                FOREIGN KEY (committee_id) REFERENCES board_committees(id)
            )
        ''')
        
        cursor.execute('''
            INSERT INTO board_meetings (id, meeting_type, committee_id, meeting_date, meeting_time, location, agenda, minutes_file, quorum_met, status, meeting_reference)
            SELECT id, meeting_type, committee_id, meeting_date, meeting_time, location, agenda, minutes_file, quorum_met, status, meeting_reference FROM board_meetings_old
        ''')
        
        cursor.execute("DROP TABLE board_meetings_old")

        # 4. Update board_committees
        print("Updating board_committees table (recreating to remove constraints)...")
        cursor.execute("ALTER TABLE board_committees RENAME TO board_committees_old")
        
        cursor.execute('''
            CREATE TABLE board_committees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                committee_name VARCHAR(255) NOT NULL,
                committee_type VARCHAR(100), 
                chairman_id INTEGER,
                charter_file VARCHAR(500),
                meeting_frequency VARCHAR(50),
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (chairman_id) REFERENCES board_members(id)
            )
        ''')
        
        cursor.execute('''
            INSERT INTO board_committees (id, committee_name, committee_type, chairman_id, charter_file, meeting_frequency, is_active)
            SELECT id, committee_name, committee_type, chairman_id, charter_file, meeting_frequency, is_active FROM board_committees_old
        ''')
        
        cursor.execute("DROP TABLE board_committees_old")
        
        cursor.execute("PRAGMA foreign_keys=ON")

        conn.commit()
        print("Migration completed successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
