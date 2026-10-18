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
Additive migration: client-side OCR hint column on ekyc_document.

static/ekyc/js/capture.js's readIdHint() now runs a throwaway, self-hosted
Tesseract.js read on the front ID frame before submitting it to
ekyc.worker.check_id_side. This is a draft-only signal — the server always
re-reads the same frame from scratch via ekyc/ocr_pipeline.py and never
trusts the browser's text — but it's worth keeping alongside the frame it
came from so ekyc/pipeline.py can surface a disagreement to the reviewing
officer (see ekyc/pipeline.py's raw_signals['ocr_hint'] and
templates/ekyc/review_detail.html).

Run with: python scripts/mig_ekyc_ocr_hint.py
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

    print("Adding client_ocr_hint column to ekyc_document (no-op if already present)...")
    cur.execute("""
        ALTER TABLE ekyc_document
            ADD COLUMN IF NOT EXISTS client_ocr_hint JSONB
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("eKYC OCR-hint migration complete.")


if __name__ == "__main__":
    migrate()
