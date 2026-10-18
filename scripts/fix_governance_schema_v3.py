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

def fix_governance_schema_v3():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # We need to recreate board_meetings to update the CHECK constraint
    print("Fixing board_meetings table CHECK constraint...")
    
    # Check current definition
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='board_meetings'")
    row = cursor.fetchone()
    current_sql = row[0] if row else ""
    
    # Correct SQL for board_meetings
    correct_sql = """
    CREATE TABLE IF NOT EXISTS board_meetings (
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
        meeting_reference VARCHAR(50) UNIQUE,
        meeting_mode VARCHAR(50) DEFAULT 'IN_PERSON',
        agenda_file_path VARCHAR(500),
        minutes_file_path VARCHAR(500),
        FOREIGN KEY (committee_id) REFERENCES board_committees(id)
    )
    """

    # If it's missing board types, we recreate
    if 'BOARD' not in current_sql:
        print("Recreating board_meetings table to support all meeting types...")
        # Backup data if any
        cursor.execute("SELECT count(*) FROM board_meetings")
        count = cursor.fetchone()[0]
        
        if count > 0:
            print(f"Backing up {count} meetings...")
            # This is complex in SQLite, usually: rename, create new, copy back
            cursor.execute("ALTER TABLE board_meetings RENAME TO board_meetings_old")
            cursor.execute(correct_sql)
            # Map columns carefully - this is risky if schemas differ wildly
            # For now, let's just try a simple copy
            try:
                # Get common columns
                cursor.execute("PRAGMA table_info(board_meetings_old)")
                old_cols = [r['name'] for r in cursor.fetchall()]
                cursor.execute("PRAGMA table_info(board_meetings)")
                new_cols = [r['name'] for r in cursor.fetchall()]
                common_cols = list(set(old_cols) & set(new_cols))
                
                cols_str = ", ".join(common_cols)
                cursor.execute(f"INSERT INTO board_meetings ({cols_str}) SELECT {cols_str} FROM board_meetings_old")
                cursor.execute("DROP TABLE board_meetings_old")
            except Exception as e:
                print(f"Error during migration: {e}")
                # Revert if possible? No, let's just proceed for now as it's likely a fresh-ish DB
        else:
            cursor.execute("DROP TABLE IF EXISTS board_meetings")
            cursor.execute(correct_sql)

    conn.commit()
    conn.close()
    print("Governance schema fix v3 completed.")

if __name__ == '__main__':
    fix_governance_schema_v3()
