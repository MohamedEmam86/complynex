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

conn = sqlite3.connect('C:/Users/Dina/Downloads/ComplyNex_CMS/complynex_cms.db')
cur = conn.cursor()

# Missing DOB
cur.execute("SELECT COUNT(*) FROM screening_watchlist WHERE date_of_birth IS NULL OR date_of_birth = ''")
missing = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM screening_watchlist WHERE country_code = 'EG'")
total_eg = cur.fetchone()[0]

print(f"Missing DOB (global): {missing}")
print(f"Total Egyptian records: {total_eg}")
