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
Rebuilds the semantic search index (screening/watchlist_semantic_v2.index +
watchlist_semantic_ids_v2.npy) from the CURRENT PostgreSQL data — all three
name lists the engine screens against: screening_watchlist (external
sanctions/PEP), internal_pep, and internal_blacklist. Internal lists get
the same semantic cross-lingual matching as external ones; they are not a
separate, weaker pathway.

Replaces scripts/build_semantic_index.py, which read from a SQLite file
(complynex_cms.db) that hasn't existed since the app moved to Postgres —
that's the direct cause of the id mismatch this script fixes: the deployed
index was built from a since-replaced data source, so its ids no longer
line up with the current table (confirmed: index-id 171616 was embedded as
"Bashar al-Assad", current table id 171616 is "Juan Carlos Girauta").

Usage:
    python scripts/rebuild_semantic_index.py           # full run
    python scripts/rebuild_semantic_index.py --limit 2000   # sample run
"""
import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('rebuild_semantic_index')

# Encode with all available CPU threads — unlike the serving process
# (semantic_service.py, thread-pinned to 1 to avoid contention with
# concurrent requests), this is a one-off batch job with nothing else to
# share the box with in the moment it runs, so let torch/faiss use both
# cores for throughput.
os.environ.setdefault('SEMANTIC_MATCHER_ENABLED', 'true')
os.environ.setdefault('HF_HOME', '/var/www/complynex/.cache/huggingface')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

from screening.semantic_matcher import (
    WATCHLIST_ID_OFFSET, INTERNAL_PEP_ID_OFFSET, INTERNAL_BLACKLIST_ID_OFFSET,
)


def _make_cursor(conn, cursor_name):
    import psycopg2.extras
    cur = conn.cursor(cursor_name, cursor_factory=psycopg2.extras.DictCursor)
    cur.itersize = 5000
    return cur


def _combine_name(arabic_name, latin_name):
    arabic_name = (arabic_name or '').strip()
    latin_name = (latin_name or '').strip()
    name_parts = []
    if arabic_name:
        name_parts.append(arabic_name)
    if latin_name and latin_name != arabic_name:
        name_parts.append(latin_name)
    return ' '.join(name_parts)


def fetch_watchlist_records(conn, limit=None):
    """External sanctions/PEP data — screening_watchlist.id, offset 0."""
    cur = _make_cursor(conn, 'semantic_rebuild_watchlist')
    query = """
        SELECT id, name_normalized, full_name, original_name
        FROM screening_watchlist
        WHERE is_active = 1
    """
    if limit:
        query += f" LIMIT {int(limit)}"
    cur.execute(query)

    count = 0
    for row in cur:
        combined = _combine_name(row['original_name'], row['name_normalized'] or row['full_name'])
        if not combined:
            continue
        count += 1
        yield {'id': row['id'] + WATCHLIST_ID_OFFSET, 'name': combined}
        if count % 100000 == 0:
            logger.info(f"  ...fetched {count} watchlist records so far")
    cur.close()


def fetch_internal_pep_records(conn, limit=None):
    """Internal PEP list — internal_pep.id, offset INTERNAL_PEP_ID_OFFSET.
    Not a separate, semantic-search-blind pathway from the external list."""
    cur = _make_cursor(conn, 'semantic_rebuild_pep')
    query = """
        SELECT id, full_name, original_name
        FROM internal_pep
        WHERE COALESCE(is_active, 1) != 0
    """
    if limit:
        query += f" LIMIT {int(limit)}"
    cur.execute(query)

    count = 0
    for row in cur:
        combined = _combine_name(row['original_name'], row['full_name'])
        if not combined:
            continue
        count += 1
        yield {'id': row['id'] + INTERNAL_PEP_ID_OFFSET, 'name': combined}
    logger.info(f"  ...fetched {count} internal PEP records")
    cur.close()


def fetch_internal_blacklist_records(conn, limit=None):
    """Internal blacklist — internal_blacklist.id, offset INTERNAL_BLACKLIST_ID_OFFSET."""
    cur = _make_cursor(conn, 'semantic_rebuild_blacklist')
    query = """
        SELECT id, full_name, original_name
        FROM internal_blacklist
        WHERE COALESCE(is_active, 1) != 0
    """
    if limit:
        query += f" LIMIT {int(limit)}"
    cur.execute(query)

    count = 0
    for row in cur:
        combined = _combine_name(row['original_name'], row['full_name'])
        if not combined:
            continue
        count += 1
        yield {'id': row['id'] + INTERNAL_BLACKLIST_ID_OFFSET, 'name': combined}
    logger.info(f"  ...fetched {count} internal blacklist records")
    cur.close()


def fetch_records(limit=None):
    """Pull (namespaced id, combined Arabic+Latin name) pairs from all three
    live tables, streamed via server-side cursors rather than one large
    fetchall() — at ~2.5M rows the row objects alone would otherwise sit
    fully in Python memory for the whole run."""
    from config import Config
    import psycopg2

    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    conn.set_session(readonly=True)

    yield from fetch_watchlist_records(conn, limit=limit)
    yield from fetch_internal_pep_records(conn, limit=limit)
    yield from fetch_internal_blacklist_records(conn, limit=limit)

    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None,
                         help='Only process this many rows (for a fast sample/validation run)')
    args = parser.parse_args()

    from screening.semantic_matcher import SemanticSequenceMatcher
    matcher = SemanticSequenceMatcher()
    if matcher.model is None:
        # enabled may be False here only because the OLD index files don't
        # exist yet on a from-scratch box — the model itself still loads
        # independently of that; build_index() only actually needs
        # self.model, not a pre-existing index.
        logger.error("Embedding model failed to load — check SEMANTIC_MATCHER_ENABLED, "
                      "HF cache path, and faiss-cpu/sentence-transformers installation.")
        sys.exit(1)
    matcher.enabled = True  # build_index() gates on this; model is what actually matters

    logger.info("Fetching active entries from screening_watchlist + internal_pep + internal_blacklist...")
    t0 = time.time()
    records = list(fetch_records(limit=args.limit))
    logger.info(f"Fetched {len(records)} total records in {time.time()-t0:.1f}s")

    # Track the highest real (offset-decoded) id seen per table, so
    # scripts/incremental_reindex.py has a checkpoint to start from —
    # without this, a fresh full rebuild leaves the incremental script with
    # no baseline, and it would either refuse to run or (worse) silently
    # re-embed everything from id 0.
    wl_max = pep_max = bl_max = 0
    for r in records:
        rid = r['id']
        if rid >= INTERNAL_BLACKLIST_ID_OFFSET:
            bl_max = max(bl_max, rid - INTERNAL_BLACKLIST_ID_OFFSET)
        elif rid >= INTERNAL_PEP_ID_OFFSET:
            pep_max = max(pep_max, rid - INTERNAL_PEP_ID_OFFSET)
        else:
            wl_max = max(wl_max, rid - WATCHLIST_ID_OFFSET)

    logger.info("Embedding + building FAISS index (this is the slow part)...")
    t1 = time.time()
    ok = matcher.build_index(records)
    elapsed = time.time() - t1
    if ok:
        logger.info(f"Done in {elapsed:.1f}s ({elapsed/max(len(records),1)*1000:.1f}ms/record). "
                     f"Index: {matcher.INDEX_FILE}  Ids: {matcher.IDS_FILE}")

        if not args.limit:
            # Only write a fresh checkpoint for a real full run — a --limit
            # sample run must not overwrite the real checkpoint with a
            # tiny sample's (much lower) max ids.
            state = {
                'watchlist_max_id': wl_max, 'pep_max_id': pep_max, 'blacklist_max_id': bl_max,
                'last_run': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'last_full_rebuild': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            }
            state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                       'screening', 'semantic_index_state.json')
            tmp = state_file + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, state_file)
            logger.info(f"Checkpoint written: {state}")

            # This full rebuild just re-fetched every active row straight
            # from Postgres, so anything sitting in the delta index (see
            # SemanticSequenceMatcher.add_to_delta, populated by
            # scripts/incremental_reindex.py between full rebuilds) is
            # already folded into the new main index above — the delta
            # files would otherwise cause duplicate/stale hits once the
            # live service is restarted onto this new main index.
            from screening.semantic_matcher import SemanticSequenceMatcher as _SSM
            for delta_file in (_SSM.DELTA_INDEX_FILE, _SSM.DELTA_IDS_FILE):
                if os.path.exists(delta_file):
                    os.remove(delta_file)
            logger.info("Cleared delta index (folded into this full rebuild).")
    else:
        logger.error("build_index() returned False")
        sys.exit(1)


if __name__ == '__main__':
    main()
