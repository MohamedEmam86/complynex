#!/usr/bin/env python3
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
"""Find screening_watchlist records that are missing from the Elasticsearch
index and index them, reporting why any of them is rejected.

The incremental sync only looks at rows changed since its last run and
swallowed bulk errors, so records that failed once never got another chance
(about 9% of the OpenSanctions records were not searchable in ES).

    python scripts/es_backfill_missing.py [--source opensanctions] [--dry-run]
"""
import argparse
import os
import re
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import psycopg2  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402
from elasticsearch import Elasticsearch  # noqa: E402
from elasticsearch.helpers import bulk  # noqa: E402
from config import Config  # noqa: E402

INDEX = os.getenv('ES_INDEX_WATCHLIST', 'aml_watchlist')


def doc_for(row):
    doc = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in dict(row).items() if v is not None}
    raw = row.get('original_name') or row.get('full_name')
    if raw:
        doc['name_normalized'] = re.sub(r' {2,}', ' ', re.sub(r'عبدال([؀-ۿ])',
                                                             lambda m: 'عبد ال' + m.group(1), raw)).strip().lower()
    doc['watchlist_id'] = row['id']
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    es = Elasticsearch(os.getenv('ES_URL', 'http://localhost:9200'), request_timeout=120)
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    where = "is_active = 1 AND source NOT IN ('internal_blacklist','internal_pep')"
    params = []
    if a.source:
        where += ' AND source = %s'
        params.append(a.source)
    ids_cur = conn.cursor('ids')
    ids_cur.itersize = 5000
    ids_cur.execute(f'SELECT id FROM screening_watchlist WHERE {where} ORDER BY id', params)
    missing, checked, indexed, errors, first_err = [], 0, 0, 0, None

    def flush(batch_ids):
        nonlocal indexed, errors, first_err
        if not batch_ids or a.dry_run:
            return
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM screening_watchlist WHERE id = ANY(%s)', (batch_ids,))
        actions = [{'_op_type': 'index', '_index': INDEX, '_id': str(r['id']), '_source': doc_for(r)}
                   for r in cur.fetchall()]
        ok, errs = bulk(es, actions, raise_on_error=False, chunk_size=500)
        indexed += ok
        errors += len(errs)
        if errs and first_err is None:
            first_err = str(errs[0])[:600]

    chunk = []
    for (rid,) in ids_cur:
        chunk.append(str(rid))
        if len(chunk) == 5000:
            res = es.mget(index=INDEX, ids=chunk, source=False)
            miss = [int(d['_id']) for d in res['docs'] if not d.get('found')]
            missing += miss
            checked += len(chunk)
            flush(miss)
            chunk = []
    if chunk:
        res = es.mget(index=INDEX, ids=chunk, source=False)
        miss = [int(d['_id']) for d in res['docs'] if not d.get('found')]
        missing += miss
        checked += len(chunk)
        flush(miss)
    # deactivated records must not stay searchable
    cur = conn.cursor()
    cur.execute("SELECT id FROM screening_watchlist WHERE is_active = 0")
    inactive = [str(r[0]) for r in cur.fetchall()]
    removed = 0
    if inactive and not a.dry_run:
        for i in range(0, len(inactive), 5000):
            ok, _ = bulk(es, [{'_op_type': 'delete', '_index': INDEX, '_id': x} for x in inactive[i:i + 5000]],
                         raise_on_error=False)
            removed += ok
    es.indices.refresh(index=INDEX)
    print(f'checked={checked} missing={len(missing)} indexed={indexed} errors={errors} '
          f'inactive_removed={removed}')
    if first_err:
        print('first error:', first_err)


if __name__ == '__main__':
    main()
