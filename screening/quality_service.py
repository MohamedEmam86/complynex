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
"""Data for the Screening Quality page: list freshness, index coverage and
the measured accuracy of the engine (scripts/screening_quality_eval.py)."""
import json
import logging
import os
from datetime import datetime, timezone

from database.db import get_db, query_db as _query_db


def query_db(sql, args=(), one=False):
    try:
        return _query_db(sql, args, one)
    except Exception:
        try:
            get_db().rollback()
        except Exception:
            pass
        raise

logger = logging.getLogger(__name__)
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'semantic_index_state.json')

TARGETS = {'recall': 95.0, 'false_alert_rate': 5.0, 'false_confirmed_rate': 0.0, 'freshness_days': 2}


def _age_days(ts):
    if not ts:
        return None
    try:
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - ts).total_seconds() / 86400.0, 1)
    except Exception:
        return None


def _cached(key, ttl, fn):
    """Small Redis cache for slow, slowly-changing aggregates (lists change once a day).
    Falls back to computing directly when Redis is unavailable."""
    import pickle
    try:
        import redis
        r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'), socket_timeout=1)
        hit = r.get(key)
        if hit:
            return pickle.loads(hit)
    except Exception:
        r = None
    val = fn()
    if r is not None:
        try:
            r.setex(key, ttl, pickle.dumps(val))
        except Exception:
            pass
    return val


def list_freshness():
    """Per-source list counts (a scan of the whole watchlist): cached for 10 minutes."""
    return _cached('cx:screening:list_freshness:v1', 600, _list_freshness)


def _list_freshness():
    rows = query_db("""
        SELECT source, SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active,
               COUNT(*) AS total, MAX(updated_at::timestamptz) AS last_change
        FROM screening_watchlist
        WHERE source NOT IN ('internal_blacklist', 'internal_pep')
        GROUP BY source ORDER BY 2 DESC""") or []
    logs = {}
    try:
        for r in query_db("""SELECT DISTINCT ON (source) source, run_at, status, error, added, updated,
                                    delisted, relisted
                             FROM screening_list_update_log ORDER BY source, run_at DESC""") or []:
            logs[r['source']] = dict(r)
    except Exception:
        pass
    out = []
    for r in rows:
        lg = logs.get(r['source'], {})
        last_ok = lg.get('run_at') if lg.get('status') == 'ok' else None
        age = _age_days(lg.get('run_at') or r['last_change'])
        if lg.get('status') == 'failed':
            state = 'red'
        elif age is None or age > 7:
            state = 'red'
        elif age > TARGETS['freshness_days']:
            state = 'amber'
        else:
            state = 'green'
        out.append({'source': r['source'], 'active': int(r['active'] or 0), 'total': int(r['total'] or 0),
                    'last_change': r['last_change'], 'last_run': lg.get('run_at'), 'last_status': lg.get('status'),
                    'error': lg.get('error'), 'last_ok': last_ok, 'age_days': age, 'state': state,
                    'delisted': lg.get('delisted'), 'added': lg.get('added')})
    # P2-7: the version in force and the state against each list's allowed age
    # (failed / blocked updates red) come from the list versions module.
    try:
        from screening import list_versions as LV
        c = LV.connect()
        try:
            lv = {f['source']: f for f in LV.freshness(c)}
        finally:
            c.close()
    except Exception as e:
        logger.warning('list versions unavailable for the freshness view: %s', e)
        lv = {}
    for o in out:
        f = lv.get(o['source'])
        o.update(version_no=(f or {}).get('version_no'), latest_status=(f or {}).get('latest_status'),
                 max_age_hours=(f or {}).get('max_age_hours'), problem=(f or {}).get('problem'))
        if f:
            o['state'] = f['state']
    return out


def internal_lists():
    out = []
    for table, label in (('internal_blacklist', 'Internal blacklist (asset-freeze, local terrorist & UN lists)'),
                         ('internal_pep', 'Internal PEP list')):
        try:
            r = query_db(f"""SELECT SUM(CASE WHEN COALESCE(is_active,1) != 0 THEN 1 ELSE 0 END) AS active,
                                    COUNT(*) AS total, MAX(created_at::timestamptz) AS last_added
                             FROM {table}""", one=True)
            cats = query_db(f"""SELECT COALESCE(category, '—') AS category, COUNT(*) AS n FROM {table}
                                WHERE COALESCE(is_active,1) != 0 GROUP BY 1 ORDER BY 2 DESC LIMIT 8""") or []
            out.append({'table': table, 'label': label, 'active': int(r['active'] or 0), 'total': int(r['total'] or 0),
                        'last_added': r['last_added'], 'categories': [dict(c) for c in cats]})
        except Exception as e:
            logger.warning('internal list stats failed for %s: %s', table, e)
    return out


def index_coverage(freshness):
    """How much of each active list is searchable in Elasticsearch, and how far
    the semantic (similar-name) index lags behind the database."""
    es_counts, es_ok = {}, False
    try:
        from elasticsearch import Elasticsearch
        from screening.es_client import get_es_client
        es = get_es_client(timeout=10)
        res = es.search(index=os.getenv('ES_INDEX_WATCHLIST', 'aml_watchlist'), size=0,
                        query={'term': {'is_active': 1}},
                        aggs={'s': {'terms': {'field': 'source', 'size': 50}}})
        es_counts = {b['key']: b['doc_count'] for b in res['aggregations']['s']['buckets']}
        es_ok = True
    except Exception as e:
        logger.warning('ES coverage check failed: %s', e)
    rows = []
    for f in freshness:
        n_es = es_counts.get(f['source'])
        pct = round(100.0 * n_es / f['active'], 1) if (n_es is not None and f['active']) else None
        rows.append({'source': f['source'], 'db_active': f['active'], 'es': n_es, 'pct': pct})
    sem = {}
    try:
        with open(STATE_FILE) as fh:
            st = json.load(fh)
        mx = query_db("SELECT (SELECT max(id) FROM screening_watchlist) AS wl, "
                      "(SELECT max(id) FROM internal_blacklist) AS bl, (SELECT max(id) FROM internal_pep) AS pep",
                      one=True)
        pend = query_db("""SELECT
              (SELECT count(*) FROM screening_watchlist WHERE id > %s AND is_active = 1) AS wl,
              (SELECT count(*) FROM internal_blacklist WHERE id > %s AND COALESCE(is_active,1) != 0) AS bl""",
                        (st.get('watchlist_max_id', 0), st.get('blacklist_max_id', 0)), one=True)
        sem = {'last_run': st.get('last_run'), 'last_full_rebuild': st.get('last_full_rebuild'),
               'age_days': _age_days(st.get('last_run')), 'pending_watchlist': int(pend['wl'] or 0),
               'pending_blacklist': int(pend['bl'] or 0), 'max_ids': dict(mx or {})}
    except Exception as e:
        logger.warning('semantic state read failed: %s', e)
    return {'es_ok': es_ok, 'rows': rows, 'semantic': sem}


def quality_runs(limit=12):
    try:
        rows = query_db("SELECT id, run_at, kind, summary, duration_s FROM screening_quality_runs "
                        "ORDER BY run_at DESC LIMIT %s", (limit,)) or []
    except Exception:
        return []
    out = []
    for r in rows:
        s = r['summary'] if isinstance(r['summary'], dict) else json.loads(r['summary'] or '{}')
        out.append({'id': r['id'], 'run_at': r['run_at'], 'kind': r['kind'], 'summary': s,
                    'duration_s': r['duration_s']})
    return out


def run_cases(run_id):
    r = query_db("SELECT cases FROM screening_quality_runs WHERE id = %s", (run_id,), one=True)
    if not r:
        return []
    c = r['cases']
    return c if isinstance(c, list) else json.loads(c or '[]')


def delta_overview(limit=50):
    """New list names vs existing relationships (scripts/screening_delta_rescreen.py)."""
    try:
        runs = query_db("SELECT id, run_at, new_names, subjects, hits, duration_s, note "
                        "FROM screening_delta_runs ORDER BY id DESC LIMIT 5") or []
        hits = query_db("""SELECT id, found_at, subject_table, subject_id, subject_name, listed_name, list_source,
                                  category, score, tier, decision, status
                           FROM screening_delta_hits WHERE status = 'open'
                           ORDER BY (tier = 'CONFIRMED') DESC, score DESC, found_at DESC LIMIT %s""", (limit,)) or []
        counts = query_db("""SELECT count(*) FILTER (WHERE status = 'open') AS open,
                                    count(*) FILTER (WHERE status = 'true_match') AS true_match,
                                    count(*) FILTER (WHERE status = 'false_positive') AS false_positive
                             FROM screening_delta_hits""", one=True) or {}
    except Exception:
        return {'runs': [], 'hits': [], 'counts': {}}
    out = []
    for h in hits:
        h = dict(h)
        d = h.get('decision')
        h['decision'] = d if isinstance(d, dict) else json.loads(d or '{}')
        out.append(h)
    return {'runs': [dict(r) for r in runs], 'hits': out, 'counts': dict(counts)}
