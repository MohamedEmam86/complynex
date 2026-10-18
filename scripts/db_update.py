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

try:
    c.execute("ALTER TABLE screening_watchlist ADD COLUMN country TEXT")
    c.execute("ALTER TABLE screening_watchlist ADD COLUMN country_code TEXT")
except sqlite3.OperationalError:
    pass

c.execute("""
UPDATE screening_watchlist
SET
    countries = 'Egypt',
    nationality = 'Egyptian',
    country = 'Egypt',
    country_code = 'EG'
WHERE dataset = 'emlcu_egypt'
AND (countries IS NULL OR countries = '' OR countries = 'UNKNOWN')
""")
c.commit()

count = c.execute("SELECT COUNT(*) FROM screening_watchlist WHERE country_code = 'EG' OR LOWER(countries) LIKE '%egypt%'").fetchone()[0]
print(f"Update complete. Verified count: {count}")

