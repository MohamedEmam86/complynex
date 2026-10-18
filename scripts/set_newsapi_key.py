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

conn = sqlite3.connect('complynex_cms.db')
c = conn.cursor()

key = '7ex9ooE1pDM2BwUoRfg0NmOPwe4J0RdbHP64XyZE'

# Update existing row
c.execute("UPDATE screening_config SET config_value = ? WHERE config_key = 'newsapi_key'", (key,))
updated = c.rowcount

if updated == 0:
    # Insert if not exists
    c.execute("INSERT INTO screening_config (config_key, config_value) VALUES ('newsapi_key', ?)", (key,))
    print(f"Inserted newsapi_key")
else:
    print(f"Updated newsapi_key ({updated} row)")

# Also enable adverse media
c.execute("UPDATE screening_config SET config_value = 'true' WHERE config_key = 'adverse_media_enabled'")
print(f"adverse_media_enabled set to true ({c.rowcount} row)")

conn.commit()

# Verify
row = c.execute("SELECT config_key, config_value FROM screening_config WHERE config_key = 'newsapi_key'").fetchone()
print(f"Verified: {row[0]} = {row[1][:8]}...{row[1][-4:]}")

conn.close()
