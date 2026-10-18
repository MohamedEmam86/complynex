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

DB_PATH = 'complynex_cms.db'  # Adjust if needed

def migrate():
    print(f"Migrating database: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 1. Create departments table
        print("Creating departments table...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT UNIQUE NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 2. Seed initial departments
        print("Seeding departments...")
        initial_depts = [
            ('Human Resources', 'HR', 'HR Policy Management'),
            ('Information Technology', 'IT', 'IT & Security Policies'),
            ('Legal', 'LEGAL', 'Legal & Compliance'),
            ('Finance', 'FIN', 'Finance & Accounting'),
            ('Operations', 'OPS', 'General Operations'),
            ('Compliance', 'COMP', 'Compliance Department')
        ]
        
        for name, code, desc in initial_depts:
            try:
                cursor.execute('INSERT INTO departments (name, code, description) VALUES (?, ?, ?)', (name, code, desc))
            except sqlite3.IntegrityError:
                pass # Already exists

        # 3. Add department_id to users
        print("Updating users table...")
        columns = [row['name'] for row in cursor.execute("PRAGMA table_info(users)").fetchall()]
        if 'department_id' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN department_id INTEGER REFERENCES departments(id)')
            print("Added department_id to users.")
        
        # 4. Add department_id and is_internal to policies
        print("Updating policies table...")
        columns = [row['name'] for row in cursor.execute("PRAGMA table_info(policies)").fetchall()]
        if 'department_id' not in columns:
            cursor.execute('ALTER TABLE policies ADD COLUMN department_id INTEGER REFERENCES departments(id)')
            print("Added department_id to policies.")
        
        if 'is_internal' not in columns:
            cursor.execute('ALTER TABLE policies ADD COLUMN is_internal BOOLEAN DEFAULT 1') # Default to Internal
            print("Added is_internal to policies.")

        # 5. Add department_id to policy_categories
        print("Updating policy_categories table...")
        columns = [row['name'] for row in cursor.execute("PRAGMA table_info(policy_categories)").fetchall()]
        if 'department_id' not in columns:
            cursor.execute('ALTER TABLE policy_categories ADD COLUMN department_id INTEGER REFERENCES departments(id)')
            print("Added department_id to policy_categories.")
            
        conn.commit()
        print("Migration completed successfully.")

    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
