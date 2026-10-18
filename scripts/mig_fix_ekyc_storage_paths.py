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
ekyc_document.stored_path holds an absolute path (ekyc/secure_storage.py's
save_frame() bakes STORAGE_ROOT into it at write time). Rows written before
the ComplyNex -> ComplyNex rebrand still hold the old absolute prefix
'/var/www/complynex/ekyc_storage/...'; the app now runs from
'/var/www/complynex' (STORAGE_ROOT is derived from __file__, so new writes
are already correct). The old directory no longer exists, so any read of
one of these rows 500s with FileNotFoundError even though the physical
file was moved and is sitting at the equivalent /var/www/complynex path.

Only rewrites a row when the target file is confirmed to exist at the new
path first — never blind string-replaces. Idempotent — safe to re-run.

Run with: python scripts/mig_fix_ekyc_storage_paths.py
"""
import os
import psycopg2

PG = dict(
    host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
    port=int(os.environ.get("POSTGRES_PORT", 5432)),
    dbname=os.environ.get("POSTGRES_DB", "complynex_db"),
    user=os.environ.get("POSTGRES_USER", "complynex"),
    password=os.environ.get("POSTGRES_PASSWORD"),
)

OLD_PREFIX = "/var/www/complynex/ekyc_storage/"
NEW_PREFIX = "/var/www/complynex/ekyc_storage/"


def main():
    conn = psycopg2.connect(**PG)
    conn.autocommit = False
    cur = conn.cursor()

    # ILIKE '%complynex%' (not just a strict OLD_PREFIX match) in case any
    # row has the old segment somewhere other than a clean leading prefix.
    cur.execute(
        "SELECT id, stored_path FROM ekyc_document WHERE stored_path ILIKE %s",
        ('%complynex%',)
    )
    rows = cur.fetchall()
    print(f"Found {len(rows)} row(s) referencing the old 'complynex' path.")

    fixed, missing = 0, []
    for doc_id, old_path in rows:
        new_path = old_path.replace('/var/www/complynex/', '/var/www/complynex/')
        if new_path == old_path:
            missing.append((doc_id, old_path, '(pattern did not match — unexpected format)'))
            continue
        if os.path.exists(new_path):
            cur.execute("UPDATE ekyc_document SET stored_path = %s WHERE id = %s", (new_path, doc_id))
            fixed += 1
        else:
            missing.append((doc_id, old_path, new_path))

    conn.commit()
    print(f"Fixed {fixed} row(s).")
    if missing:
        print(f"WARNING: {len(missing)} row(s) skipped — file not found at expected new path:")
        for doc_id, old_path, new_path in missing:
            print(f"  id={doc_id} old={old_path} expected_new={new_path}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
