#!/usr/bin/env python3
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
Incrementally adds newly-inserted rows (screening_watchlist, internal_pep,
internal_blacklist) to the existing semantic index, instead of re-running
the ~10-hour full rebuild (scripts/rebuild_semantic_index.py) every time a
scraper imports new names. Meant to run frequently (see
complynex-semantic-reindex.timer) so new names become semantically
searchable within minutes, not whenever someone remembers to do a full
rebuild — that gap (index built once, never kept in sync with new imports)
is exactly what caused the stale-index bug this whole semantic-search
rebuild effort started from.

Tracks progress in semantic_index_state.json (last-seen id per table).
Only ever *appends* — a genuinely stale/wrong existing entry (a record
whose name text changed after it was first indexed) is NOT caught by this
script, since it only looks at ids past the last checkpoint. That's an
accepted gap: catching edits would mean tracking modified_date across three
differently-shaped tables and risking a partial/inconsistent index if an
in-place FAISS vector "update" (remove+re-add) is interrupted partway.
scripts/rebuild_semantic_index.py should still be run periodically (weekly/
monthly) as a full resync to catch any such drift — this script exists to
keep the common case (brand new names) fresh in near-real-time.

Usage:
    python scripts/incremental_reindex.py
    python scripts/incremental_reindex.py --dry-run   # report counts, don't write
"""
import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('incremental_reindex')

# No SEMANTIC_MATCHER_ENABLED/HF_HOME/offline-mode env vars needed here
# anymore — this script no longer loads the embedding model or FAISS index
# itself, it just imports the id-offset constants below (cheap) and calls
# complynex-semantic.service's /add_embeddings over HTTP to do the actual
# embedding (see main()).
from screening.semantic_matcher import (
    WATCHLIST_ID_OFFSET, INTERNAL_PEP_ID_OFFSET, INTERNAL_BLACKLIST_ID_OFFSET,
)
from scripts.rebuild_semantic_index import _combine_name

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                           'screening', 'semantic_index_state.json')


def _load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    # First incremental run before any state exists: assume the last full
    # rebuild already covered everything up to the ids it saw. That's
    # recorded by rebuild_semantic_index.py itself (see main()) — if this
    # file is genuinely missing (e.g. someone deleted it), falling back to
    # 0 would silently re-embed the entire table's worth of "new" rows,
    # which is safe (just slow, and de-duplicated by FAISS.add() adding
    # them a second time under the same id — see the dedup note below) but
    # defeats the purpose, so this is a real error condition, not silently
    # handled.
    raise FileNotFoundError(
        f"{STATE_FILE} not found — run scripts/rebuild_semantic_index.py first; "
        "it writes this file's initial checkpoint."
    )


def _save_state(state):
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def _fetch_new(conn, table, id_offset, last_id, extra_cols, active_clause, limit=None):
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cols = ', '.join(['id', 'full_name', 'original_name'] + extra_cols)
    query = f"""
        SELECT {cols} FROM {table}
        WHERE id > %s AND {active_clause}
        ORDER BY id
    """
    params = [last_id]
    if limit:
        query += " LIMIT %s"
        params.append(limit)
    cur.execute(query, params)

    records, max_id = [], last_id
    for row in cur:
        combined = _combine_name(row['original_name'], row.get('name_normalized') or row['full_name'])
        max_id = max(max_id, row['id'])
        if not combined:
            continue
        records.append({'id': row['id'] + id_offset, 'name': combined})
    cur.close()
    return records, max_id


def _full_rebuild_in_progress():
    """True if complynex-semantic-rebuild.service is currently running.
    That job reads the index/ids files at startup and only writes them back
    at the very end of its ~10h run — if this script ran concurrently and
    wrote in between, the full rebuild's final write would silently discard
    whatever this script just added. Never run both at once.

    `systemctl is-active` reports 'activating' (not 'active') for a
    Type=oneshot unit that's still mid-ExecStart — 'active' is only ever
    reported briefly right at completion (this unit has no
    RemainAfterExit=yes). Checking for the exact string 'active' would
    have let this guard pass straight through for the entire ~10h the job
    is actually running — caught by testing this against the real job
    while it was live, not just by inspection."""
    import subprocess
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'complynex-semantic-rebuild.service'],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() in ('active', 'activating', 'reloading')
    except Exception:
        return False  # systemctl unavailable — fail open rather than never running


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help="Report counts only, don't touch the index")
    args = parser.parse_args()

    if _full_rebuild_in_progress():
        logger.info("complynex-semantic-rebuild.service is currently running a full rebuild — "
                     "skipping this incremental run to avoid a race on the index files.")
        return

    from screening.update_lock import wait_until_free
    if not wait_until_free(logger=logger):  # rows of a running list update are not all committed yet
        return

    state = _load_state()
    logger.info(f"Checkpoint: watchlist>{state['watchlist_max_id']}, "
                f"pep>{state['pep_max_id']}, blacklist>{state['blacklist_max_id']}")

    from config import Config
    import psycopg2
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    conn.set_session(readonly=True)

    wl_records, wl_max = _fetch_new(
        conn, 'screening_watchlist', WATCHLIST_ID_OFFSET, state['watchlist_max_id'],
        ['name_normalized'], 'is_active = 1',
    )
    pep_records, pep_max = _fetch_new(
        conn, 'internal_pep', INTERNAL_PEP_ID_OFFSET, state['pep_max_id'],
        [], 'COALESCE(is_active, 1) != 0',
    )
    bl_records, bl_max = _fetch_new(
        conn, 'internal_blacklist', INTERNAL_BLACKLIST_ID_OFFSET, state['blacklist_max_id'],
        [], 'COALESCE(is_active, 1) != 0',
    )
    conn.close()

    new_records = wl_records + pep_records + bl_records
    logger.info(f"New since last checkpoint: {len(wl_records)} watchlist, "
                f"{len(pep_records)} internal PEP, {len(bl_records)} internal blacklist "
                f"({len(new_records)} total)")

    if not new_records:
        logger.info("Nothing new to index.")
        return

    if args.dry_run:
        logger.info("--dry-run: not writing anything.")
        return

    # Embedding happens inside complynex-semantic.service itself (via its
    # /add_delta endpoint, into the small delta index) rather than this
    # script loading its own second copy of the model+index, and rather
    # than growing the service's ~2.5M-vector main index in-process —
    # both of those OOM-killed the box (taking the live service down with
    # it) the first two times this was tried. The delta index is folded
    # into the next full rebuild and reset (see
    # scripts/rebuild_semantic_index.py).
    #
    # This checkpoint is only saved once, after every chunk below has
    # succeeded — if a later chunk times out or errors, this whole batch
    # gets re-fetched and re-sent next run. That used to mean unbounded
    # duplicate growth of the delta index on every retry (production
    # incident 2026-07-24: the same ~191k-record batch got re-added on
    # each failed 15-min retry, growing the delta index to 5.17M vectors /
    # 7.4GB and OOM-killing the service). /add_delta is now idempotent by
    # id (see SemanticSequenceMatcher.add_to_delta) — a retry of the same
    # batch is a safe no-op for whatever already landed, it just re-embeds
    # nothing. The timeout below is widened from 180s to 600s on top of
    # that as a second line of defense, since 191k records batched at 2000
    # per request is comfortably within 600s per chunk on this box even
    # under concurrent screening traffic, whereas 180s measurably was not.
    import requests
    base_url = os.environ.get('SEMANTIC_SERVICE_URL', 'http://127.0.0.1:8100')
    chunk_size = 2000  # keeps each request's encode time/payload bounded
    t0 = time.time()
    added_total = 0
    try:
        for start in range(0, len(new_records), chunk_size):
            chunk = new_records[start:start + chunk_size]
            resp = requests.post(
                f"{base_url}/add_delta",
                json={'records': [{'id': r['id'], 'name': r['name']} for r in chunk]},
                timeout=600,
            )
            if not resp.ok:
                logger.error(f"/add_delta returned {resp.status_code}: {resp.text[:300]}")
                sys.exit(1)
            added_total += resp.json().get('added', 0)
    except requests.exceptions.RequestException as e:
        logger.error(f"Could not reach semantic service at {base_url} to add embeddings: {e}. "
                     "Leaving checkpoint unchanged — safe to retry next run (add_delta is "
                     "idempotent by id, so already-added records won't be duplicated).")
        sys.exit(1)

    state['watchlist_max_id'] = wl_max
    state['pep_max_id'] = pep_max
    state['blacklist_max_id'] = bl_max
    state['last_run'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    _save_state(state)

    logger.info(f"Added {added_total} records in {time.time()-t0:.1f}s via semantic service. Checkpoint saved.")


if __name__ == '__main__':
    main()
