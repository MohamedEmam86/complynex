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
Settings module enterprise expansion — schema changes:

- departments: adds unit_type (department/business_unit/branch, defaults to
  'department' so all 6 existing FK-referencing tables keep working
  unchanged), parent_id (nullable self-reference for org hierarchy), and
  is_active (soft-disable, historical FK references stay valid).
- email_templates: new table, admin-editable subject/body per template_key.
  Code falls back to its current hardcoded template when no active row
  exists for a key, so this is purely additive.
- numbering_sequences: new table holding the configurable prefix/padding
  for document numbering (risk IDs, audit engagement numbers, ...). The
  actual "next number" is still derived from MAX(existing id)+1 in code
  (unchanged, avoids introducing a second source of truth that could drift
  from real rows) — only the prefix/padding become admin-configurable.
- system_settings: seeds new keys (org info, security policy, default
  locale) with the values that are already hardcoded elsewhere today, so
  behavior is unchanged until an admin edits them via the new Settings UI.

Idempotent — safe to re-run.

Run with: python scripts/mig_settings_enterprise.py
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

NEW_SETTINGS = {
    "registration_number": ("", "Company registration / license number"),
    "regulator_name": ("Central Bank of Egypt", "Primary regulator name"),
    "contact_email": ("", "Organization primary contact email"),
    "contact_phone": ("", "Organization primary contact phone"),
    "address": ("", "Organization registered address"),
    "default_locale": ("ar", "Platform default language (ar/en) when a visitor has no session preference yet"),
    "session_timeout_minutes": ("30", "Inactivity timeout before a session is logged out"),
    "password_min_length": ("8", "Minimum password length enforced on create/change"),
    "password_require_complexity": ("true", "Require upper+lower+digit in new passwords"),
    "audit_log_retention_days": ("365", "Days audit log entries are retained (informational until a purge job reads it)"),
}


def migrate():
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()

    print("Extending departments with unit_type/parent_id/is_active...")
    cur.execute("""
        ALTER TABLE departments ADD COLUMN IF NOT EXISTS unit_type TEXT NOT NULL DEFAULT 'department'
            CHECK (unit_type IN ('department', 'business_unit', 'branch'))
    """)
    cur.execute("""
        ALTER TABLE departments ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES departments(id) ON DELETE SET NULL
    """)
    cur.execute("""
        ALTER TABLE departments ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE
    """)

    print("Creating email_templates table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_templates (
            id SERIAL PRIMARY KEY,
            template_key TEXT NOT NULL UNIQUE,
            subject TEXT NOT NULL,
            body_html TEXT,
            body_text TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    print("Creating numbering_sequences table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS numbering_sequences (
            id SERIAL PRIMARY KEY,
            sequence_key TEXT NOT NULL UNIQUE,
            prefix TEXT NOT NULL,
            padding INTEGER NOT NULL DEFAULT 4,
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        INSERT INTO numbering_sequences (sequence_key, prefix, padding, description)
        VALUES
            ('risk_id', 'RSK', 4, 'Risk Register entries (Risk Management module)'),
            ('audit_engagement', 'AUD', 4, 'Internal Audit engagement numbers')
        ON CONFLICT (sequence_key) DO NOTHING
    """)

    print("Seeding new system_settings keys (no-op if already present)...")
    for key, (value, description) in NEW_SETTINGS.items():
        cur.execute("""
            INSERT INTO system_settings (setting_key, setting_value, description, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP::TEXT)
            ON CONFLICT (setting_key) DO NOTHING
        """, (key, value, description))

    conn.commit()
    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    migrate()
