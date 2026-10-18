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
Additive migration: custom_html column on phishing_campaigns.

Lets a campaign override the built-in structured template (sender_display/
offer_title/offer_body/etc., see phishing/routes.py's _build_email_html)
with a fully custom raw HTML email body, so campaigns can mimic a real
marketing email's actual design instead of always looking like the same
templated layout. phishing/routes.py substitutes the literal tokens
{{TRACKING_URL}} and {{RECIPIENT_NAME}} into this HTML at send time.

Run with: python scripts/mig_phishing_custom_html.py
"""
import os
import psycopg2

PG = dict(
    host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
    port=int(os.environ.get("POSTGRES_PORT", 5432)),
    dbname=os.environ.get("POSTGRES_DB", "complynex_db"),
    user=os.environ.get("POSTGRES_USER", "complynex"),
    password=os.environ.get("POSTGRES_PASSWORD", ""),
)


def migrate():
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()

    print("Adding custom_html column to phishing_campaigns (no-op if already present)...")
    cur.execute("""
        ALTER TABLE phishing_campaigns
            ADD COLUMN IF NOT EXISTS custom_html TEXT
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Phishing custom_html migration complete.")


if __name__ == "__main__":
    migrate()
