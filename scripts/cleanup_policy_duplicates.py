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

db_path = 'complynex_cms.db'

def cleanup_duplicates():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Duplicate IDs identified earlier: 9, 10, 11, 12, 13, 14, 15, 16
    duplicate_ids = [9, 10, 11, 12, 13, 14, 15, 16]
    
    print(f"Cleaning up duplicate categories: {duplicate_ids}")
    
    for cat_id in duplicate_ids:
        # Verify no policies
        count = cursor.execute('SELECT COUNT(*) FROM policies WHERE category_id = ?', (cat_id,)).fetchone()[0]
        if count == 0:
            cursor.execute('DELETE FROM policy_categories WHERE id = ?', (cat_id,))
            print(f"  Deleted category ID: {cat_id}")
        else:
            print(f"  Skipped category ID: {cat_id} (has {count} policies)")
            
    conn.commit()
    conn.close()
    print("Cleanup complete.")

if __name__ == '__main__':
    cleanup_duplicates()
