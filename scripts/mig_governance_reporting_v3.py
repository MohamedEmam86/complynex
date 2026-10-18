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
Corporate Governance + Regulatory Reporting — regulator-agnostic schema
changes:

- governance_compliance_tracker: adds regulator_id (nullable FK to
  regulators; the existing free-text regulatory_source column stays as a
  fallback label for anything not registered as a formal regulator yet)
  and is_active (soft-disable, so a requirement can be retired without
  losing its history).
- fit_proper_assessments: adds generic regulator_id + submission/approval
  columns (submitted_to_regulator, regulator_submission_date,
  regulator_reference_number, regulator_approval_date,
  regulator_approval_status, regulator_feedback). The existing cbe_*
  columns on this table were never wired to any form (confirmed dead —
  no code path ever writes to them), so they're left untouched rather
  than migrated/dropped, per this project's backward-compatibility
  standard.
- regulatory_reports: adds regulatory_reference (generic replacement for
  the CBE-only cbe_circular_reference), backfilled from the old column
  where it was already populated. cbe_circular_reference is kept as-is.

Idempotent — safe to re-run.

Run with: python scripts/mig_governance_reporting_v3.py
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

    print("Extending governance_compliance_tracker with regulator_id/is_active...")
    cur.execute("""
        ALTER TABLE governance_compliance_tracker
            ADD COLUMN IF NOT EXISTS regulator_id INTEGER REFERENCES regulators(id) ON DELETE SET NULL
    """)
    cur.execute("""
        ALTER TABLE governance_compliance_tracker
            ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 1
    """)

    print("Extending fit_proper_assessments with generic regulator_* columns...")
    cur.execute("""
        ALTER TABLE fit_proper_assessments
            ADD COLUMN IF NOT EXISTS regulator_id INTEGER REFERENCES regulators(id) ON DELETE SET NULL
    """)
    cur.execute("""
        ALTER TABLE fit_proper_assessments
            ADD COLUMN IF NOT EXISTS submitted_to_regulator INTEGER
    """)
    cur.execute("""
        ALTER TABLE fit_proper_assessments
            ADD COLUMN IF NOT EXISTS regulator_submission_date TEXT
    """)
    cur.execute("""
        ALTER TABLE fit_proper_assessments
            ADD COLUMN IF NOT EXISTS regulator_reference_number TEXT
    """)
    cur.execute("""
        ALTER TABLE fit_proper_assessments
            ADD COLUMN IF NOT EXISTS regulator_approval_date TEXT
    """)
    cur.execute("""
        ALTER TABLE fit_proper_assessments
            ADD COLUMN IF NOT EXISTS regulator_approval_status TEXT
    """)
    cur.execute("""
        ALTER TABLE fit_proper_assessments
            ADD COLUMN IF NOT EXISTS regulator_feedback TEXT
    """)

    print("Extending regulatory_reports with generic regulatory_reference...")
    cur.execute("""
        ALTER TABLE regulatory_reports
            ADD COLUMN IF NOT EXISTS regulatory_reference TEXT
    """)
    cur.execute("""
        UPDATE regulatory_reports
        SET regulatory_reference = cbe_circular_reference
        WHERE regulatory_reference IS NULL
          AND cbe_circular_reference IS NOT NULL
          AND cbe_circular_reference != ''
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    migrate()
