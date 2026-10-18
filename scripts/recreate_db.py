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

def recreate_db():
    print("Recreating database with Phase 2 schema...")
    
    db_path = 'complynex_cms.db'
    schema_path = 'schema_phase2.sql'
    
    if os.path.exists(db_path):
        print(f"Removing existing database at {db_path}...")
        os.remove(db_path)
    
    if not os.path.exists(schema_path):
        print(f"Schema file not found at {schema_path}!")
        return
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("Applying schema...")
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_script = f.read()
            
        cursor.executescript(schema_script)
        
        conn.commit()
        print("Database recreated successfully!")
        
        # Verify tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Total tables created: {len(tables)}")
        for table in tables:
            print(f"- {table[0]}")

        # Create a default admin user for testing
        print("\nCreating default admin user...")
        
        # Check if users table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
        if not cursor.fetchone():
            print("Users table missing! Creating users table with correct schema...")
            # Schema based on models/user.py expectations
            cursor.execute("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(200) NOT NULL,
                    first_name VARCHAR(100),
                    last_name VARCHAR(100),
                    role VARCHAR(20) DEFAULT 'employee',
                    employee_id VARCHAR(50) UNIQUE,
                    department VARCHAR(100),
                    job_title VARCHAR(100),
                    manager_id INTEGER REFERENCES users(id),
                    cms_access_level VARCHAR(20) DEFAULT 'none',
                    profile_picture VARCHAR(500),
                    is_active BOOLEAN DEFAULT 1,
                    last_login TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            cursor.execute("""
                INSERT INTO users (
                    email, password_hash, first_name, last_name, role, 
                    cms_access_level, employee_id, department, job_title
                )
                VALUES (
                    'admin@complynex.com', 
                    'pbkdf2:sha256:600000$dummyhash', 
                    'System', 
                    'Admin', 
                    'admin', 
                    'edit',
                    'ADM001',
                    'IT',
                    'System Administrator'
                );
            """)
            conn.commit()
            print("Default admin user created.")
            
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    recreate_db()
