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
Section 8 (general platform review) — performance finding: `notifications`
and `audit_logs` had no indexes beyond their primary key, despite both being
hit on almost every request:
  - notifications: models/notification.py's get_unread_for_user() filters on
    (user_id, is_read) and sorts by created_at DESC — this runs in the
    context_processor on every single authenticated page load.
  - audit_logs: models/audit.py's get_all() (the Settings > Audit Trail page)
    does an unbounded ORDER BY created_at DESC with optional filters on
    user_id/module/action, and every write anywhere in the app inserts here,
    so this table only grows.

Idempotent — safe to re-run.

Run with: python scripts/mig_perf_indexes.py
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

    print("Adding notifications(user_id, is_read) + created_at index...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
        ON notifications (user_id, is_read)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_created
        ON notifications (created_at DESC)
    """)

    print("Adding audit_logs(user_id), (module), (created_at) indexes...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_logs_user
        ON audit_logs (user_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_logs_module
        ON audit_logs (module)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_logs_created
        ON audit_logs (created_at DESC)
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    migrate()
