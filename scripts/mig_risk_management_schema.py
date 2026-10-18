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
Schema migration for the Enterprise Risk Management module.

The tables `risks`, `risk_categories`, `risk_treatments` already exist in
production but are empty (0 rows) and unreferenced by any application code —
they were mechanically transliterated from an old SQLite draft schema and are
structurally unusable on Postgres (dates/booleans stored as TEXT, no enforced
FK/CHECK constraints). This migration drops and recreates those three
cleanly, and adds the rest of the ERM data model: scoring bands, appetite
statements, the control library (controls/risk_controls/control_test_results),
KRIs, score history, the risk-treatment lifecycle, and the generic
cross-module risk_source_links table. Also adds the perm_risk_management
permission column to users. Idempotent — safe to re-run.

Run with: python scripts/mig_risk_management_schema.py
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

    print("Adding perm_risk_management column to users (no-op if already present)...")
    cur.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_risk_management VARCHAR(10) DEFAULT 'none'
    """)

    print("Dropping legacy empty/unused risk tables (risks, risk_treatments, risk_categories)...")
    cur.execute("DROP TABLE IF EXISTS risk_treatments CASCADE")
    cur.execute("DROP TABLE IF EXISTS risks CASCADE")
    cur.execute("DROP TABLE IF EXISTS risk_categories CASCADE")

    print("Creating risk_categories...")
    cur.execute("""
        CREATE TABLE risk_categories (
            id SERIAL PRIMARY KEY,
            category_code VARCHAR(10) UNIQUE NOT NULL,
            parent_category_id INTEGER REFERENCES risk_categories(id),
            category_name VARCHAR(100) NOT NULL,
            category_description TEXT
        )
    """)

    print("Creating risk_scoring_bands...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS risk_scoring_bands (
            id SERIAL PRIMARY KEY,
            band_name VARCHAR(30) NOT NULL,
            min_score INTEGER NOT NULL,
            max_score INTEGER NOT NULL,
            color_hex VARCHAR(7) NOT NULL DEFAULT '#6c757d',
            display_order INTEGER NOT NULL,
            requires_board_notification BOOLEAN NOT NULL DEFAULT FALSE,
            UNIQUE(min_score, max_score)
        )
    """)

    print("Creating risks...")
    cur.execute("""
        CREATE TABLE risks (
            id SERIAL PRIMARY KEY,
            risk_id VARCHAR(50) UNIQUE NOT NULL,
            risk_title VARCHAR(255) NOT NULL,
            risk_description TEXT,
            category_id INTEGER NOT NULL REFERENCES risk_categories(id),
            secondary_tags TEXT[],
            department_id INTEGER REFERENCES departments(id),
            parent_risk_id INTEGER REFERENCES risks(id),
            likelihood INTEGER NOT NULL CHECK (likelihood BETWEEN 1 AND 5),
            impact INTEGER NOT NULL CHECK (impact BETWEEN 1 AND 5),
            inherent_risk_score INTEGER NOT NULL,
            existing_controls TEXT,
            control_effectiveness VARCHAR(20)
                CHECK (control_effectiveness IN ('EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'INEFFECTIVE', 'NOT_ASSESSED')),
            residual_likelihood INTEGER CHECK (residual_likelihood BETWEEN 1 AND 5),
            residual_impact INTEGER CHECK (residual_impact BETWEEN 1 AND 5),
            residual_risk_score INTEGER,
            risk_response VARCHAR(20) CHECK (risk_response IN ('ACCEPT', 'MITIGATE', 'TRANSFER', 'AVOID')),
            risk_owner_id INTEGER REFERENCES users(id),
            review_frequency VARCHAR(20) NOT NULL DEFAULT 'QUARTERLY'
                CHECK (review_frequency IN ('MONTHLY', 'QUARTERLY', 'SEMI_ANNUAL', 'ANNUAL')),
            last_review_date DATE,
            next_review_date DATE,
            risk_appetite_aligned BOOLEAN,
            status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('DRAFT', 'ACTIVE', 'CLOSED', 'ACCEPTED')),
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_risks_category ON risks(category_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_risks_owner ON risks(risk_owner_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_risks_status ON risks(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_risks_next_review ON risks(next_review_date)")

    print("Creating risk_appetite_statements...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS risk_appetite_statements (
            id SERIAL PRIMARY KEY,
            category_id INTEGER REFERENCES risk_categories(id),
            statement_text TEXT NOT NULL,
            appetite_level VARCHAR(20) NOT NULL
                CHECK (appetite_level IN ('AVERSE', 'MINIMAL', 'CAUTIOUS', 'OPEN', 'HUNGRY')),
            max_acceptable_inherent_score INTEGER,
            max_acceptable_residual_score INTEGER NOT NULL,
            effective_from DATE NOT NULL,
            effective_to DATE,
            approved_by_meeting_id INTEGER REFERENCES board_meetings(id),
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_appetite_category_active ON risk_appetite_statements(category_id, effective_to)")

    print("Creating controls...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS controls (
            id SERIAL PRIMARY KEY,
            control_code VARCHAR(30) UNIQUE NOT NULL,
            control_name VARCHAR(255) NOT NULL,
            control_description TEXT,
            control_type VARCHAR(20) NOT NULL
                CHECK (control_type IN ('PREVENTIVE', 'DETECTIVE', 'CORRECTIVE')),
            control_nature VARCHAR(20) NOT NULL DEFAULT 'MANUAL'
                CHECK (control_nature IN ('MANUAL', 'AUTOMATED', 'IT_DEPENDENT')),
            control_owner_id INTEGER REFERENCES users(id),
            department_id INTEGER REFERENCES departments(id),
            testing_frequency VARCHAR(20) NOT NULL DEFAULT 'ANNUAL'
                CHECK (testing_frequency IN ('MONTHLY', 'QUARTERLY', 'SEMI_ANNUAL', 'ANNUAL', 'AD_HOC')),
            last_tested_date DATE,
            last_test_result VARCHAR(20)
                CHECK (last_test_result IN ('EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'INEFFECTIVE', 'NOT_TESTED')),
            next_test_due_date DATE,
            status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'RETIRED')),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    print("Creating risk_controls...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS risk_controls (
            id SERIAL PRIMARY KEY,
            risk_id INTEGER NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
            control_id INTEGER NOT NULL REFERENCES controls(id) ON DELETE CASCADE,
            reliance_level VARCHAR(20) NOT NULL DEFAULT 'PRIMARY'
                CHECK (reliance_level IN ('PRIMARY', 'SECONDARY')),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(risk_id, control_id)
        )
    """)

    print("Creating control_test_results (audit_project_id FK added later by the Internal Audit migration)...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS control_test_results (
            id SERIAL PRIMARY KEY,
            control_id INTEGER NOT NULL REFERENCES controls(id) ON DELETE CASCADE,
            tested_by INTEGER REFERENCES users(id),
            test_date DATE NOT NULL,
            test_procedure TEXT,
            result VARCHAR(20) NOT NULL
                CHECK (result IN ('EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'INEFFECTIVE')),
            exceptions_noted TEXT,
            evidence_file VARCHAR(500),
            audit_project_id INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_control_test_results_control ON control_test_results(control_id)")

    print("Creating kris / kri_measurements...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kris (
            id SERIAL PRIMARY KEY,
            risk_id INTEGER REFERENCES risks(id) ON DELETE CASCADE,
            kri_name VARCHAR(255) NOT NULL,
            kri_description TEXT,
            unit_of_measure VARCHAR(50),
            measurement_frequency VARCHAR(20) NOT NULL DEFAULT 'MONTHLY'
                CHECK (measurement_frequency IN ('DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY')),
            target_value NUMERIC(15,2),
            warning_threshold NUMERIC(15,2),
            breach_threshold NUMERIC(15,2),
            direction VARCHAR(10) NOT NULL DEFAULT 'UPPER' CHECK (direction IN ('UPPER', 'LOWER')),
            owner_id INTEGER REFERENCES users(id),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kri_measurements (
            id SERIAL PRIMARY KEY,
            kri_id INTEGER NOT NULL REFERENCES kris(id) ON DELETE CASCADE,
            measurement_date DATE NOT NULL,
            actual_value NUMERIC(15,2) NOT NULL,
            status VARCHAR(10) NOT NULL CHECK (status IN ('GREEN', 'AMBER', 'RED')),
            notes TEXT,
            recorded_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(kri_id, measurement_date)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_kri_measurements_kri_date ON kri_measurements(kri_id, measurement_date DESC)")

    print("Creating risk_score_history...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS risk_score_history (
            id SERIAL PRIMARY KEY,
            risk_id INTEGER NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
            likelihood INTEGER NOT NULL,
            impact INTEGER NOT NULL,
            inherent_risk_score INTEGER NOT NULL,
            residual_likelihood INTEGER,
            residual_impact INTEGER,
            residual_risk_score INTEGER,
            control_effectiveness VARCHAR(20),
            changed_by INTEGER REFERENCES users(id),
            change_reason TEXT,
            recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_risk_score_history_risk ON risk_score_history(risk_id, recorded_at)")

    print("Creating risk_treatments...")
    cur.execute("""
        CREATE TABLE risk_treatments (
            id SERIAL PRIMARY KEY,
            risk_id INTEGER NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
            treatment_description TEXT NOT NULL,
            treatment_type VARCHAR(20) CHECK (treatment_type IN ('ACCEPT', 'MITIGATE', 'TRANSFER', 'AVOID')),
            treatment_owner_id INTEGER NOT NULL REFERENCES users(id),
            estimated_cost NUMERIC(15,2),
            budget_approved BOOLEAN NOT NULL DEFAULT FALSE,
            target_date DATE NOT NULL,
            completion_date DATE,
            status VARCHAR(20) NOT NULL DEFAULT 'PROPOSED'
                CHECK (status IN ('PROPOSED', 'APPROVED', 'IN_PROGRESS', 'COMPLETED', 'VERIFIED', 'CLOSED', 'REJECTED')),
            verified_by INTEGER REFERENCES users(id),
            verified_at TIMESTAMP,
            verification_notes TEXT,
            evidence_file VARCHAR(500),
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_risk_treatments_risk ON risk_treatments(risk_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_risk_treatments_owner_status ON risk_treatments(treatment_owner_id, status)")

    print("Creating risk_source_links (generic cross-module integration table)...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS risk_source_links (
            id SERIAL PRIMARY KEY,
            risk_id INTEGER NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
            source_module VARCHAR(40) NOT NULL,
            source_table VARCHAR(60) NOT NULL,
            source_record_id INTEGER NOT NULL,
            link_type VARCHAR(20) NOT NULL DEFAULT 'EVIDENCE'
                CHECK (link_type IN ('TRIGGER', 'EVIDENCE', 'RELATED')),
            linked_by INTEGER REFERENCES users(id),
            linked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            UNIQUE(risk_id, source_module, source_table, source_record_id, link_type)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_risk_source_links_risk ON risk_source_links(risk_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_risk_source_links_source ON risk_source_links(source_module, source_table, source_record_id)")

    conn.commit()
    cur.close()
    conn.close()
    print("Risk Management schema migration complete.")


if __name__ == "__main__":
    migrate()
