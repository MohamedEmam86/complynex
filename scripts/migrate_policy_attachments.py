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

"""
Migration: Add policy_attachments table for multi-document support
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'complynex_cms.db')

def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Create policy_attachments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS policy_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            uploaded_by INTEGER,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (policy_id) REFERENCES policies (id) ON DELETE CASCADE,
            FOREIGN KEY (uploaded_by) REFERENCES users (id)
        )
    ''')
    
    # Migrate existing attachment_path data to the new table
    existing = cursor.execute('''
        SELECT id, attachment_path, created_by FROM policies 
        WHERE attachment_path IS NOT NULL AND attachment_path != ''
    ''').fetchall()
    
    for row in existing:
        # Check if already migrated
        check = cursor.execute(
            'SELECT 1 FROM policy_attachments WHERE policy_id = ? AND file_path = ?',
            (row['id'], row['attachment_path'])
        ).fetchone()
        
        if not check:
            filename = os.path.basename(row['attachment_path'])
            cursor.execute('''
                INSERT INTO policy_attachments (policy_id, filename, file_path, uploaded_by)
                VALUES (?, ?, ?, ?)
            ''', (row['id'], filename, row['attachment_path'], row['created_by']))
    
    conn.commit()
    print(f"Migration complete. Migrated {len(existing)} existing attachments.")
    conn.close()

if __name__ == '__main__':
    migrate()
