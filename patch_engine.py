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

import os
import re

target_dir = '/opt/complynex/screening/'
for filename in os.listdir(target_dir):
    if not filename.endswith('.py') or filename == 'db_pool.py':
        continue
        
    filepath = os.path.join(target_dir, filename)
    with open(filepath, 'r') as f:
        content = f.read()
        
    if 'sqlite3.connect' in content:
        # Inject the pool import if missing
        if 'from screening.db_pool import db_pool' not in content:
            content = 'from screening.db_pool import db_pool\n' + content
            
        # Replace sqlite3.connect(...) with the Postgres pool checkout
        content = re.sub(r'sqlite3\.connect\([^)]*\)', 'db_pool.checkout_connection()', content)
        
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"✅ Patched {filename} to use PostgreSQL")
