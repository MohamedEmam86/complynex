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
Additive migration: back-side ID OCR columns on ekyc_result.

ekyc_document already allowed doc_role='ID_BACK_VIDEO' and ekyc/id_layout.py
already had BACK_FIELDS crop boxes (occupation, marital_status, gender,
expiry_date) and ekyc/ocr_pipeline.py already supported side='back' — none
of that was ever wired up end-to-end (capture UI only ever captured one ID
image, ekyc/routes.py never accepted a second one, ekyc/pipeline.py never
decoded it). This migration adds columns to store what side='back' OCR
extracts once that wiring exists.

Run with: python scripts/mig_ekyc_back_fields.py
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

    print("Adding back-side OCR columns to ekyc_result (no-op if already present)...")
    cur.execute("""
        ALTER TABLE ekyc_result
            ADD COLUMN IF NOT EXISTS back_card_detected BOOLEAN,
            ADD COLUMN IF NOT EXISTS back_ocr_confidence NUMERIC(5,2),
            ADD COLUMN IF NOT EXISTS extracted_occupation VARCHAR(200),
            ADD COLUMN IF NOT EXISTS extracted_marital_status VARCHAR(50),
            ADD COLUMN IF NOT EXISTS id_expiry_raw VARCHAR(50)
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("eKYC back-fields migration complete.")


if __name__ == "__main__":
    migrate()
