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
Additive migration: compliance-review, final-decision, and onboarding columns
for the eKYC module.

Deliberately does NOT create a parallel ekyc_screening_match/disposition
table — eKYC screening hits are written into the existing screening_history/
screening_queue tables (source_module='eKYC'), the same mechanism Customer
KYC and Merchant KYC already use (see aml/routes.py), so officers disposition
eKYC hits in the screening module's existing /screening/queue UI instead of a
second, duplicate disposition workflow.

What this migration adds, all additive (no existing column/table touched
beyond ekyc_session.status's CHECK constraint, which is widened, not
narrowed — every value it already allowed remains allowed):

- ekyc_session: review-queue assignment (assigned_to/reviewed_by/reviewed_at),
  the officer's final Approve/Reject (final_decision/decision_by/decided_at/
  decision_notes -- named final_decision, not decision, because
  EkycSession.list_all() already LEFT JOINs ekyc_result and selects its
  decision column (the pipeline's own PASS/REVIEW/FAIL) unaliased; a same-
  named column on ekyc_session would silently shadow it in that query's
  result rows), and onboarded_customer_id linking to the customers table
  once approved.
- ekyc_result: field_sources (JSONB) -- which fields an officer manually
  corrected during review, e.g. {"national_id": "manual"}. Fields not listed
  are assumed AI-sourced; this avoids a source column per extracted field.
- ekyc_session.status CHECK constraint widened to add NEEDS_REVIEW,
  DECISION_PENDING, APPROVED, ONBOARDED, REJECTED.

Run with: python scripts/mig_ekyc_review_onboarding.py
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

    print("Adding review/decision/onboarding columns to ekyc_session (no-op if already present)...")
    cur.execute("""
        ALTER TABLE ekyc_session
            ADD COLUMN IF NOT EXISTS assigned_to INTEGER REFERENCES users(id),
            ADD COLUMN IF NOT EXISTS reviewed_by INTEGER REFERENCES users(id),
            ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS final_decision VARCHAR(10) CHECK (final_decision IN ('APPROVED', 'REJECTED')),
            ADD COLUMN IF NOT EXISTS decision_by INTEGER REFERENCES users(id),
            ADD COLUMN IF NOT EXISTS decided_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS decision_notes TEXT,
            ADD COLUMN IF NOT EXISTS onboarded_customer_id INTEGER REFERENCES customers(id)
    """)

    print("Widening ekyc_session.status CHECK constraint (adding values, removing none)...")
    cur.execute("""
        ALTER TABLE ekyc_session DROP CONSTRAINT IF EXISTS ekyc_session_status_check
    """)
    cur.execute("""
        ALTER TABLE ekyc_session ADD CONSTRAINT ekyc_session_status_check
            CHECK (status IN (
                'CREATED', 'CONSENT_GIVEN', 'CAPTURED', 'QUEUED', 'PROCESSING',
                'NEEDS_REVIEW', 'DECISION_PENDING', 'APPROVED', 'ONBOARDED', 'REJECTED',
                'COMPLETED', 'FAILED', 'EXPIRED'
            ))
    """)

    print("Adding field_sources column to ekyc_result (no-op if already present)...")
    cur.execute("""
        ALTER TABLE ekyc_result
            ADD COLUMN IF NOT EXISTS field_sources JSONB
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_ekyc_session_assigned_to ON ekyc_session(assigned_to)")

    conn.commit()
    cur.close()
    conn.close()
    print("eKYC review/onboarding migration complete.")


if __name__ == "__main__":
    migrate()
