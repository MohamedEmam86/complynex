#!/usr/bin/env python3
"""
Search-index health check (Phase 2): are Elasticsearch and the semantic index in step
with the lists in PostgreSQL?

Checks
  1. Elasticsearch reachable and the aml_watchlist index present.
  2. Active records per source in PostgreSQL == documents per source in Elasticsearch.
  3. A random sample of active ids is in the index and a sample of deactivated ids is not.
  4. The incremental sync ran recently (last_incremental_sync age).
  5. Semantic index: active records added after the last checkpoint (waiting to be embedded).

Writes the result to logs/index_health.json; exit code 1 when any check fails, so the
timer / monitoring can alert.

    python scripts/index_health.py
"""
import json
import os
import random
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

SYNC_MAX_AGE_MIN = 45            # the incremental sync runs every 15 minutes
SAMPLE = 300
SEMANTIC_LAG_WARN = 5000         # new records not yet embedded (embedded nightly)


def main():
    import psycopg2
    from config import Config
    from screening.es_client import get_es_client
    out = {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': {}, 'ok': True}

    def fail(name, detail):
        out['checks'][name] = {'ok': False, 'detail': detail}
        out['ok'] = False

    def ok(name, detail):
        out['checks'][name] = {'ok': True, 'detail': detail}

    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()
    try:
        es = get_es_client(timeout=30)
        if not es.indices.exists(index='aml_watchlist'):
            fail('elasticsearch', 'index aml_watchlist missing')
            es = None
        else:
            ok('elasticsearch', 'reachable, index present')
    except Exception as ex:
        fail('elasticsearch', f'not reachable: {ex}')
        es = None

    cur.execute("SELECT source, count(*) FROM screening_watchlist WHERE is_active=1 GROUP BY 1")
    db = dict(cur.fetchall())
    if es is not None:
        es_counts = {}
        for src in db:
            es_counts[src] = es.count(index='aml_watchlist',
                                      body={'query': {'term': {'source.keyword': src}}})['count']
        if sum(es_counts.values()) == 0:      # field not keyword-mapped: fall back to match
            for src in db:
                es_counts[src] = es.count(index='aml_watchlist', body={'query': {'match': {'source': src}}})['count']
        diffs = {s: {'db': db[s], 'es': es_counts.get(s, 0)} for s in db if db[s] != es_counts.get(s, 0)}
        total_es = es.count(index='aml_watchlist')['count']
        if diffs or total_es != sum(db.values()):
            fail('counts', {'per_source_mismatch': diffs, 'db_total': sum(db.values()), 'es_total': total_es})
        else:
            ok('counts', {'db_total': sum(db.values()), 'es_total': total_es, 'sources': len(db)})

        cur.execute("SELECT id FROM screening_watchlist WHERE is_active=1 ORDER BY random() LIMIT %s", (SAMPLE,))
        act = [str(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT id FROM screening_watchlist WHERE is_active=0 ORDER BY random() LIMIT %s", (SAMPLE,))
        ina = [str(r[0]) for r in cur.fetchall()]
        missing = [d['_id'] for d in es.mget(index='aml_watchlist', body={'ids': act})['docs'] if not d.get('found')]
        stale = [d['_id'] for d in es.mget(index='aml_watchlist', body={'ids': ina})['docs'] if d.get('found')] if ina else []
        if missing or stale:
            fail('sample', {'active_not_indexed': len(missing), 'inactive_still_indexed': len(stale),
                            'examples': (missing + stale)[:5]})
        else:
            ok('sample', f'{len(act)} active found, {len(ina)} inactive absent')
        try:
            ts = es.get(index='aml_sync_meta', id='last_incremental_sync')['_source']['timestamp']
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace('Z', '+00:00'))).total_seconds() / 60
            (ok if age <= SYNC_MAX_AGE_MIN else fail)('sync_age', f'last incremental sync {age:.0f} min ago')
        except Exception as ex:
            fail('sync_age', f'unknown ({ex})')

    state_path = os.path.join(BASE, 'screening', 'semantic_index_state.json')
    try:
        st = json.load(open(state_path))
        cur.execute("SELECT count(*) FROM screening_watchlist WHERE is_active=1 AND id > %s", (st['watchlist_max_id'],))
        w = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM internal_pep WHERE COALESCE(is_active,1)!=0 AND id > %s", (st['pep_max_id'],))
        p = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM internal_blacklist WHERE COALESCE(is_active,1)!=0 AND id > %s",
                    (st['blacklist_max_id'],))
        b = cur.fetchone()[0]
        detail = {'waiting_watchlist': w, 'waiting_internal_pep': p, 'waiting_internal_blacklist': b,
                  'last_incremental': st.get('last_run'), 'last_full_rebuild': st.get('last_full_rebuild')}
        (ok if w + p + b <= SEMANTIC_LAG_WARN else fail)('semantic', detail)
    except Exception as ex:
        fail('semantic', f'state unreadable: {ex}')

    os.makedirs(os.path.join(BASE, 'logs'), exist_ok=True)
    tmp = os.path.join(BASE, 'logs', 'index_health.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(out, f, indent=1, default=str)
    os.replace(tmp, os.path.join(BASE, 'logs', 'index_health.json'))
    print(json.dumps(out, indent=1, default=str, ensure_ascii=False))
    sys.exit(0 if out['ok'] else 1)


if __name__ == '__main__':
    main()
