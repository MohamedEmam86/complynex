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
Creates generic_attachments: a single, reusable evidence/document store any
module can attach to, instead of hand-rolling its own <module>_documents
table. Keyed polymorphically by (module, record_type, record_id), so it can
attach to any existing row in any table without a new foreign key per module.

Added 2026-07-24 to satisfy: "optional (never mandatory) document/evidence
attachment capability" for the ESG Governance ('G') pillar, the separate
Corporate Governance module, and other modules going forward — one shared
table + blueprint instead of duplicating upload/download/delete logic
per module.

Soft-delete only (is_deleted flag) — compliance evidence should never be
silently hard-deleted; a removed attachment still needs to be traceable for
an audit trail, consistent with how screening_whitelist entries are
'Revoked' rather than deleted outright.

Idempotent — safe to re-run.

Run with: python scripts/migrate_generic_attachments.py
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


def run():
    conn = psycopg2.connect(**PG)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS generic_attachments (
                id SERIAL PRIMARY KEY,
                module TEXT NOT NULL,
                record_type TEXT NOT NULL,
                record_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                description TEXT,
                uploaded_by INTEGER,
                uploaded_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
                is_deleted INTEGER NOT NULL DEFAULT 0,
                deleted_by INTEGER,
                deleted_at TEXT
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_generic_attachments_parent
            ON generic_attachments (module, record_type, record_id)
            WHERE is_deleted = 0
        """)
        conn.commit()
        print("OK: generic_attachments table + index created (or already existed).")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    run()
