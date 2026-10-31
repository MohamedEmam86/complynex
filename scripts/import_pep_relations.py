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
G13 — import relatives / close associates of PEPs from the OpenSanctions exports.

The exports carry 'Family' (person, relative, relationship) and 'Associate'
(person, associate, relationship) entities next to the Person records the daily
update loads. This script streams the same files (the source_url of the
OpenSanctions sources in screening_data_sources, or --file) and keeps only those
two schemas.

  dry run (default)  counts, relationship kinds and how many sides are listed today
  --apply            upserts screening_pep_relations (origin 'opensanctions'); a relation
                     an MLRO removed is never revived; after a COMPLETE run over every
                     source, OpenSanctions relations no longer in the files are marked
                     inactive (guard: only when this run saw at least half of the
                     relations active before it)

Never touches screening_watchlist. Output: counts only (no names).
"""
import argparse
import collections
import json
import os
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

SCHEMAS = {'Family': ('person', 'relative', 'family'), 'Associate': ('person', 'associate', 'associate')}


def _conn():
    import psycopg2
    from config import Config
    return psycopg2.connect(**dict(Config.POSTGRES_CONFIG))


def _sources(cur):
    cur.execute("""SELECT source_name, source_url FROM screening_data_sources
                    WHERE source_name IN ('opensanctions_pep', 'opensanctions') AND COALESCE(source_url, '') <> ''
                    ORDER BY source_name = 'opensanctions_pep' DESC""")
    return [(r[0], r[1]) for r in cur.fetchall()]


def _lines(path_or_url):
    if os.path.exists(path_or_url):
        with open(path_or_url, 'rb') as f:
            for line in f:
                yield line
        return
    import requests
    with requests.get(path_or_url, stream=True, timeout=(15, 300)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            yield line


def parse(lines):
    """Yield relation dicts from FtM lines (pure; used by the tests)."""
    for line in lines:
        if not line:
            continue
        if isinstance(line, bytes) and b'"Family"' not in line and b'"Associate"' not in line:
            continue                    # fast skip: most lines are Person / Occupancy / Position
        try:
            d = json.loads(line)
        except Exception:
            continue
        spec = SCHEMAS.get(d.get('schema'))
        if not spec or not d.get('id'):
            continue
        p = d.get('properties') or {}
        a, b = (p.get(spec[0]) or [None])[0], (p.get(spec[1]) or [None])[0]
        if not a or not b or a == b:
            continue
        rel = (p.get('relationship') or [''])[0] or ''
        yield {'key': 'os:' + str(d['id']), 'pep_sid': 'OS-' + str(a), 'rel_sid': 'OS-' + str(b),
               'type': spec[2], 'relationship': str(rel).strip()[:120]}


def _listed(cur, sids):
    out = set()
    sids = list(sids)
    for i in range(0, len(sids), 5000):
        cur.execute("""SELECT DISTINCT source_id FROM screening_watchlist
                        WHERE source IN ('opensanctions', 'opensanctions_pep') AND source_id = ANY(%s)
                          AND is_active = 1""", (sids[i:i + 5000],))
        out.update(r[0] for r in cur.fetchall())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--file', action='append', default=[], help='local FtM file instead of the source URLs')
    a = ap.parse_args()
    t0 = time.time()
    run_start = datetime.now()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SET statement_timeout = '10min'")
    srcs = [('file', f) for f in a.file] if a.file else _sources(cur)
    if not srcs:
        print('no OpenSanctions source URL configured')
        return 1
    rels, complete = {}, True
    for name, url in srcs:
        n = 0
        try:
            for r in parse(_lines(url)):
                rels.setdefault(r['key'], r)
                n += 1
        except Exception as e:
            complete = False
            print(f'{name}: read failed ({type(e).__name__}) - stale relations will not be retired')
        print(f'{name}: {n:,} relations read ({time.time() - t0:.0f}s)')
    by_type = collections.Counter(r['type'] for r in rels.values())
    kinds = collections.Counter((r['relationship'] or '-').lower() for r in rels.values())
    listed = _listed(cur, {r['pep_sid'] for r in rels.values()} | {r['rel_sid'] for r in rels.values()})
    both = sum(1 for r in rels.values() if r['pep_sid'] in listed and r['rel_sid'] in listed)
    one = sum(1 for r in rels.values() if (r['pep_sid'] in listed) != (r['rel_sid'] in listed))
    print(f'relations: {len(rels):,} ({dict(by_type)}); both sides listed today: {both:,}; one side: {one:,}; '
          f'none: {len(rels) - both - one:,}')
    print('top relationship words:', kinds.most_common(12))
    if not a.apply:
        print('dry run - nothing written')
        return 0
    cur.execute("SELECT count(*) FROM screening_pep_relations WHERE origin = 'opensanctions' AND is_active")
    before = cur.fetchone()[0]
    rows = list(rels.values())
    for i in range(0, len(rows), 2000):
        chunk = rows[i:i + 2000]
        cur.executemany("""
            INSERT INTO screening_pep_relations
                (relation_key, pep_source, pep_source_id, related_source, related_source_id,
                 relation_type, relationship, origin, last_seen_at)
            VALUES (%s, 'opensanctions', %s, 'opensanctions', %s, %s, %s, 'opensanctions', %s)
            ON CONFLICT (relation_key) DO UPDATE
               SET pep_source_id = EXCLUDED.pep_source_id, related_source_id = EXCLUDED.related_source_id,
                   relation_type = EXCLUDED.relation_type, relationship = EXCLUDED.relationship,
                   last_seen_at = EXCLUDED.last_seen_at,
                   is_active = (screening_pep_relations.removed_by IS NULL),
                   updated_at = now()""",
            [(r['key'], r['pep_sid'], r['rel_sid'], r['type'], r['relationship'], run_start) for r in chunk])
        conn.commit()
    retired = 0
    if complete and len(rels) >= 0.5 * before:
        cur.execute("""UPDATE screening_pep_relations SET is_active = FALSE, updated_at = now()
                        WHERE origin = 'opensanctions' AND is_active AND (last_seen_at IS NULL OR last_seen_at < %s)""",
                    (run_start,))
        retired = cur.rowcount
        conn.commit()
    elif before:
        print(f'stale relations kept: run incomplete or only {len(rels):,} read vs {before:,} active before')
    cur.execute("SELECT count(*) FROM screening_pep_relations WHERE is_active")
    print(f'applied: {len(rels):,} upserted, {retired:,} retired, {cur.fetchone()[0]:,} active '
          f'({time.time() - t0:.0f}s)')
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
