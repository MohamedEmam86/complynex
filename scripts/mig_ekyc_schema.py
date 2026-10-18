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
Additive migration for the eKYC module.
Creates ekyc_session, ekyc_document, ekyc_result, ekyc_audit_log tables
and adds the perm_ekyc permission column to users. Never touches existing
tables/data beyond that single additive column.

Run with: python scripts/mig_ekyc_schema.py
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

    print("Adding perm_ekyc column to users (no-op if already present)...")
    cur.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_ekyc VARCHAR(10) DEFAULT 'none'
    """)

    print("Creating ekyc_session...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ekyc_session (
            id SERIAL PRIMARY KEY,
            session_token VARCHAR(64) UNIQUE NOT NULL,
            customer_reference VARCHAR(200),
            document_type VARCHAR(30) NOT NULL DEFAULT 'NATIONAL_ID'
                CHECK (document_type IN ('NATIONAL_ID', 'PASSPORT', 'DRIVING_LICENSE', 'COMMERCIAL_REGISTER', 'TAX_ID')),
            status VARCHAR(20) NOT NULL DEFAULT 'CREATED'
                CHECK (status IN ('CREATED', 'CONSENT_GIVEN', 'CAPTURED', 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED', 'EXPIRED')),
            consent_given BOOLEAN NOT NULL DEFAULT FALSE,
            consent_text TEXT,
            consent_given_at TIMESTAMP,
            consent_ip VARCHAR(50),
            locale VARCHAR(5) NOT NULL DEFAULT 'ar',
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            retention_expires_at TIMESTAMP,
            error_message TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ekyc_session_token ON ekyc_session(session_token)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ekyc_session_status ON ekyc_session(status)")

    print("Creating ekyc_document...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ekyc_document (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES ekyc_session(id) ON DELETE CASCADE,
            doc_role VARCHAR(20) NOT NULL
                CHECK (doc_role IN ('ID_FRONT_VIDEO', 'ID_BACK_VIDEO', 'SELFIE_VIDEO')),
            stored_path VARCHAR(500) NOT NULL,
            encryption_key_id VARCHAR(100) NOT NULL,
            checksum_sha256 VARCHAR(64),
            file_size BIGINT,
            mime_type VARCHAR(50),
            captured_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            purged_at TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ekyc_document_session ON ekyc_document(session_id)")

    print("Creating ekyc_result...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ekyc_result (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL UNIQUE REFERENCES ekyc_session(id) ON DELETE CASCADE,

            extracted_full_name_ar VARCHAR(300),
            extracted_full_name_en VARCHAR(300),
            national_id VARCHAR(14),
            national_id_valid BOOLEAN,
            dob DATE,
            gender VARCHAR(10),
            governorate_code VARCHAR(5),
            governorate_name VARCHAR(100),
            ocr_confidence NUMERIC(5,2),
            ocr_engine_used VARCHAR(20),

            face_match_score NUMERIC(5,2),
            face_match_engine VARCHAR(20),

            passive_liveness_score NUMERIC(5,2),
            passive_liveness_pass BOOLEAN,

            active_liveness_pass BOOLEAN,
            active_liveness_challenge VARCHAR(50),

            document_pad_score NUMERIC(5,2),
            document_pad_pass BOOLEAN,

            duplicate_of_session_id INTEGER REFERENCES ekyc_session(id),

            risk_score NUMERIC(5,2),
            decision VARCHAR(10) CHECK (decision IN ('PASS', 'REVIEW', 'FAIL')),
            decision_reasons JSONB,

            screening_history_id INTEGER,
            screening_result VARCHAR(30),

            raw_signals JSONB,

            processed_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ekyc_result_national_id ON ekyc_result(national_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ekyc_result_decision ON ekyc_result(decision)")

    print("Creating ekyc_audit_log...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ekyc_audit_log (
            id SERIAL PRIMARY KEY,
            session_id INTEGER REFERENCES ekyc_session(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id),
            action VARCHAR(100) NOT NULL,
            details TEXT,
            ip_address VARCHAR(50),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ekyc_audit_session ON ekyc_audit_log(session_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ekyc_audit_created ON ekyc_audit_log(created_at)")

    conn.commit()
    cur.close()
    conn.close()
    print("eKYC schema migration complete.")


if __name__ == "__main__":
    migrate()
