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
Schema migration for the Internal Audit module.

Run AFTER scripts/mig_risk_management_schema.py — this migration adds foreign
keys into `risks` and `controls`, which must already exist.

The tables `audit_universe`, `annual_audit_plans`, `audit_projects`,
`audit_findings` already exist in production but are empty (0 rows) and
unreferenced by any application code — same legacy-scaffold situation as the
risk tables. This migration drops and recreates those four cleanly with a
real workflow status and independent-verification fields, and adds:
audit_universe_risks (risk-based audit planning), audit_team_members,
audit_programs (procedures/checklist, each optionally testing a control),
audit_working_papers (evidence repository). Also adds the
perm_internal_audit permission column to users, and backfills the
control_test_results.audit_project_id foreign key that the risk-management
migration left unconstrained (it runs first and audit_projects didn't exist
yet at that point). Idempotent — safe to re-run.

Run with: python scripts/mig_internal_audit_schema.py
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

    print("Adding perm_internal_audit column to users (no-op if already present)...")
    cur.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_internal_audit VARCHAR(10) DEFAULT 'none'
    """)

    print("Dropping legacy empty/unused audit tables...")
    cur.execute("DROP TABLE IF EXISTS audit_findings CASCADE")
    cur.execute("DROP TABLE IF EXISTS audit_projects CASCADE")
    cur.execute("DROP TABLE IF EXISTS annual_audit_plans CASCADE")
    cur.execute("DROP TABLE IF EXISTS audit_universe CASCADE")

    print("Creating audit_universe...")
    cur.execute("""
        CREATE TABLE audit_universe (
            id SERIAL PRIMARY KEY,
            auditable_area VARCHAR(255) NOT NULL,
            area_description TEXT,
            risk_level VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'
                CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
            department_id INTEGER REFERENCES departments(id),
            last_audit_date DATE,
            audit_frequency VARCHAR(20) NOT NULL DEFAULT 'ANNUAL'
                CHECK (audit_frequency IN ('QUARTERLY', 'SEMI_ANNUAL', 'ANNUAL', 'BIENNIAL')),
            next_audit_due DATE,
            responsible_department VARCHAR(100),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    print("Creating audit_universe_risks (risk-based audit planning join table)...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_universe_risks (
            id SERIAL PRIMARY KEY,
            universe_id INTEGER NOT NULL REFERENCES audit_universe(id) ON DELETE CASCADE,
            risk_id INTEGER NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
            UNIQUE(universe_id, risk_id)
        )
    """)

    print("Creating annual_audit_plans...")
    cur.execute("""
        CREATE TABLE annual_audit_plans (
            id SERIAL PRIMARY KEY,
            plan_year INTEGER NOT NULL,
            plan_name VARCHAR(255),
            status VARCHAR(20) NOT NULL DEFAULT 'DRAFT'
                CHECK (status IN ('DRAFT', 'APPROVED', 'IN_PROGRESS', 'CLOSED')),
            approved_date DATE,
            approved_by INTEGER REFERENCES users(id),
            approved_by_meeting_id INTEGER REFERENCES board_meetings(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    print("Creating audit_projects...")
    cur.execute("""
        CREATE TABLE audit_projects (
            id SERIAL PRIMARY KEY,
            plan_id INTEGER REFERENCES annual_audit_plans(id),
            audit_number VARCHAR(50) UNIQUE NOT NULL,
            audit_name VARCHAR(255) NOT NULL,
            auditable_area_id INTEGER REFERENCES audit_universe(id),
            audit_type VARCHAR(50) NOT NULL DEFAULT 'INTERNAL'
                CHECK (audit_type IN ('INTERNAL', 'EXTERNAL', 'REGULATORY', 'SPECIAL')),
            audit_scope TEXT,
            planned_start_date DATE,
            planned_end_date DATE,
            actual_start_date DATE,
            actual_end_date DATE,
            lead_auditor_id INTEGER REFERENCES users(id),
            status VARCHAR(20) NOT NULL DEFAULT 'PLANNED'
                CHECK (status IN ('PLANNED', 'FIELDWORK', 'REPORTING', 'MANAGEMENT_RESPONSE', 'FOLLOW_UP', 'CLOSED')),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_projects_plan ON audit_projects(plan_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_projects_status ON audit_projects(status)")

    print("Backfilling control_test_results.audit_project_id foreign key...")
    cur.execute("""
        ALTER TABLE control_test_results
        DROP CONSTRAINT IF EXISTS control_test_results_audit_project_id_fkey
    """)
    cur.execute("""
        ALTER TABLE control_test_results
        ADD CONSTRAINT control_test_results_audit_project_id_fkey
        FOREIGN KEY (audit_project_id) REFERENCES audit_projects(id)
    """)

    print("Creating audit_team_members...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_team_members (
            id SERIAL PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES audit_projects(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            role_on_engagement VARCHAR(30) NOT NULL DEFAULT 'AUDITOR'
                CHECK (role_on_engagement IN ('LEAD', 'AUDITOR', 'REVIEWER', 'OBSERVER')),
            allocated_hours NUMERIC(6,1),
            UNIQUE(project_id, user_id)
        )
    """)

    print("Creating audit_programs (procedures/checklist, each optionally testing a control)...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_programs (
            id SERIAL PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES audit_projects(id) ON DELETE CASCADE,
            step_number INTEGER NOT NULL,
            procedure_description TEXT NOT NULL,
            control_id INTEGER REFERENCES controls(id),
            test_result VARCHAR(20)
                CHECK (test_result IN ('EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'INEFFECTIVE', 'N/A', 'NOT_TESTED')),
            workpaper_reference VARCHAR(100),
            performed_by INTEGER REFERENCES users(id),
            performed_at TIMESTAMP,
            reviewed_by INTEGER REFERENCES users(id),
            reviewed_at TIMESTAMP,
            UNIQUE(project_id, step_number)
        )
    """)

    print("Creating audit_working_papers (evidence repository)...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_working_papers (
            id SERIAL PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES audit_projects(id) ON DELETE CASCADE,
            program_step_id INTEGER REFERENCES audit_programs(id),
            finding_id INTEGER,
            file_path VARCHAR(500) NOT NULL,
            description VARCHAR(255),
            uploaded_by INTEGER REFERENCES users(id),
            uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_working_papers_project ON audit_working_papers(project_id)")

    print("Creating audit_findings...")
    cur.execute("""
        CREATE TABLE audit_findings (
            id SERIAL PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES audit_projects(id) ON DELETE CASCADE,
            finding_number VARCHAR(50) NOT NULL,
            finding_title VARCHAR(255) NOT NULL,
            finding_description TEXT,
            severity VARCHAR(20) NOT NULL
                CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')),
            root_cause TEXT,
            recommendation TEXT,
            management_response TEXT,
            agreed_action TEXT,
            responsible_person_id INTEGER REFERENCES users(id),
            target_date DATE,
            status VARCHAR(40) NOT NULL DEFAULT 'OPEN'
                CHECK (status IN ('OPEN', 'MANAGEMENT_RESPONSE_RECEIVED', 'REMEDIATION_IN_PROGRESS',
                                   'REMEDIATED_PENDING_VERIFICATION', 'VERIFIED_CLOSED')),
            verified_by INTEGER REFERENCES users(id),
            verified_at TIMESTAMP,
            verification_notes TEXT,
            linked_risk_id INTEGER REFERENCES risks(id),
            linked_control_id INTEGER REFERENCES controls(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, finding_number)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_findings_project ON audit_findings(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_findings_status ON audit_findings(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_findings_severity ON audit_findings(severity)")

    # audit_working_papers.finding_id has no FK constraint above (audit_findings
    # didn't exist yet when that table was created in this same script) — add it now.
    cur.execute("""
        ALTER TABLE audit_working_papers
        DROP CONSTRAINT IF EXISTS audit_working_papers_finding_id_fkey
    """)
    cur.execute("""
        ALTER TABLE audit_working_papers
        ADD CONSTRAINT audit_working_papers_finding_id_fkey
        FOREIGN KEY (finding_id) REFERENCES audit_findings(id)
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Internal Audit schema migration complete.")


if __name__ == "__main__":
    migrate()
