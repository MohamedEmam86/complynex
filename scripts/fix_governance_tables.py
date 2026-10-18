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

def fix_governance_tables():
    # Robust path handling
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, 'complynex_cms.db')
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Fixing governance tables...")
    
    # Create board_roles table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS board_roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_name VARCHAR(100) NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    print(" - board_roles table created/verified")
    
    # Check if roles exist, if not seed them
    cursor.execute("SELECT COUNT(*) FROM board_roles")
    if cursor.fetchone()[0] == 0:
        roles = [
            ('Chairman', 'Chairman of the Board'),
            ('Vice Chairman', 'Vice Chairman of the Board'),
            ('Board Member', 'Regular member of the board'),
            ('Independent Director', 'Independent non-executive director'),
            ('CEO', 'Chief Executive Officer'),
            ('Company Secretary', 'Secretary to the board')
        ]
        cursor.executemany("INSERT INTO board_roles (role_name, description) VALUES (?, ?)", roles)
        print(f" - Seeded {len(roles)} default board roles")

    # Create committee_memberships table (plural)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS committee_memberships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        committee_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        role VARCHAR(50) DEFAULT 'MEMBER',
        joined_date DATE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (committee_id) REFERENCES board_committees(id),
        FOREIGN KEY (member_id) REFERENCES board_members(id)
    )
    ''')
    print(" - committee_memberships table created/verified")

    conn.commit()
    conn.close()
    print("Governance tables fixed successfully!")

if __name__ == "__main__":
    fix_governance_tables()
