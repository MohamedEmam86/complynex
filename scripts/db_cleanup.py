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

c = sqlite3.connect('complynex_cms.db')

q2 = """
SELECT DISTINCT dataset, COUNT(*) as count 
FROM screening_watchlist 
WHERE (countries IS NULL OR countries = '' OR countries = 'UNKNOWN') 
AND (nationality IS NULL OR nationality = '' OR nationality = 'UNKNOWN')
GROUP BY dataset 
ORDER BY count DESC
"""
print("Datasets with NULL country/nationality:")
for row in c.execute(q2).fetchall():
    print(f"  {row[0]}: {row[1]}")
