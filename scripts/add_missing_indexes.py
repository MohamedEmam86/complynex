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
Add Missing Indexes
===================
Adds performance indexes for Users, AML, and Training tables.
"""

import sqlite3
import os
import sys

def add_indexes():
    db_path = 'complynex_cms.db'
    if not os.path.exists(db_path):
        db_path = 'complynex.db'
        
    print(f"Adding indexes to {db_path}...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    indexes = [
        # Users
        ("idx_users_email", "users", "email"),
        ("idx_users_role", "users", "role"),
        
        # AML Transactions
        ("idx_transactions_date", "aml_transactions", "transaction_date"),
        ("idx_transactions_amount", "aml_transactions", "amount"),
        
        # Training
        ("idx_training_user", "training_enrollments", "user_id"),
        ("idx_training_status", "training_enrollments", "status"),
        
        # Screening Watchlist
        ("idx_watchlist_soundex", "screening_watchlist", "name_soundex"),
        ("idx_watchlist_metaphone", "screening_watchlist", "name_metaphone"),
        ("idx_watchlist_normalized", "screening_watchlist", "name_normalized"),
        ("idx_watchlist_source", "screening_watchlist", "source"),
        ("idx_watchlist_active", "screening_watchlist", "is_active")
    ]
    
    success_count = 0
    for idx_name, table, column in indexes:
        try:
            # Check if table exists first
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if not cursor.fetchone():
                print(f"  SKIP: Table '{table}' does not exist.")
                continue
                
            print(f"  Creating {idx_name} on {table}({column})...", end=" ")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})")
            print("OK")
            success_count += 1
        except Exception as e:
            print(f"FAILED: {e}")
            
    conn.commit()
    conn.close()
    print(f"\nDone. Added {success_count} indexes.")

if __name__ == "__main__":
    add_indexes()
