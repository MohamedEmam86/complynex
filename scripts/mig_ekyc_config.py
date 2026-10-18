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
Additive migration: ekyc_config table for editable risk-fusion thresholds
and weights, mirroring the screening_config key-value pattern but scoped
to the eKYC module.

Run with: python scripts/mig_ekyc_config.py
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

DEFAULTS = [
    # Decision boundaries on the fused 0-100 risk score.
    ('risk_threshold_pass', '80', 'Fused score at/above this -> PASS'),
    ('risk_threshold_review', '55', 'Fused score at/above this (but below pass) -> REVIEW; below this -> FAIL'),
    # Fusion weights — should sum to ~1.0.
    ('weight_ocr', '0.20', 'Weight of OCR/national-ID-validity sub-score in the fused risk score'),
    ('weight_face_match', '0.30', 'Weight of selfie-vs-ID-photo face match sub-score'),
    ('weight_passive_liveness', '0.15', 'Weight of passive (Silent-Face) liveness sub-score'),
    ('weight_active_liveness', '0.15', 'Weight of active (MediaPipe challenge) liveness sub-score'),
    ('weight_document_pad', '0.20', 'Weight of document presentation-attack-detection sub-score'),
]


def migrate():
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()

    print("Creating ekyc_config...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ekyc_config (
            config_key VARCHAR(100) PRIMARY KEY,
            config_value TEXT NOT NULL,
            description TEXT,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for key, value, description in DEFAULTS:
        cur.execute("""
            INSERT INTO ekyc_config (config_key, config_value, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (config_key) DO NOTHING
        """, (key, value, description))

    conn.commit()
    cur.close()
    conn.close()
    print("eKYC config migration complete.")


if __name__ == "__main__":
    migrate()
