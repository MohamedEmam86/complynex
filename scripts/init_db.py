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
from werkzeug.security import generate_password_hash

DB_PATH = 'complynex_cms.db'
SCHEMA_PATH = 'database/schema.sql'

def init_db():
    if not os.path.exists(SCHEMA_PATH):
        print(f"Schema file not found at {SCHEMA_PATH}")
        return

    print(f"Initializing database at {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
        conn.executescript(schema_sql)
        print("Schema executed.")
        
    # Update Admin Password
    admin_password = 'Admin@123'
    password_hash = generate_password_hash(admin_password)
    
    # Check if admin exists first (it should from schema INSERT OR IGNORE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = 'admin@complynex.online'")
    if cursor.fetchone():
        print("Updating admin password...")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = 'admin@complynex.online'",
            (password_hash,)
        )
    else:
        print("Admin user not found. Creating...")
        conn.execute(
            "INSERT INTO users (email, password_hash, first_name, last_name, role, is_active) VALUES (?, ?, ?, ?, ?, ?)",
            ('admin@complynex.com', password_hash, 'System', 'Administrator', 'admin', 1)
        )
        
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

if __name__ == "__main__":
    init_db()
