# =============================================================================
# ComplyNex — cached screening statistics
#
# The dashboard recomputed aggregates over a 2.77M-row watchlist on every page
# load. Indexes brought that from ~7.8s to ~310ms, but the underlying point
# stands: the watchlist changes once a month, so recomputing per request is
# work nobody asked for.
#
# Redis is already running and already used for rate limiting, so this adds no
# new dependency. Every read degrades to a direct query if Redis is unavailable
# — a cache that takes the page down when it fails is worse than no cache.
# =============================================================================
import json
import time

TTL_WATCHLIST = 3600      # list syncs monthly; an hour is generous
TTL_STATS     = 120       # screening counts move during the day
_KEY = 'cnx:screening:'


def _redis():
    try:
        import redis
        from flask import current_app
        url = current_app.config.get('REDIS_URL', 'redis://localhost:6379/3')
        r = redis.Redis.from_url(url, socket_timeout=0.4,
                                 socket_connect_timeout=0.4, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def cached(key, ttl, producer):
    """Return a cached value, computing it only when absent or stale."""
    r = _redis()
    full = _KEY + key
    if r is not None:
        try:
            hit = r.get(full)
            if hit is not None:
                return json.loads(hit)
        except Exception:
            pass
    value = producer()
    if r is not None:
        try:
            r.setex(full, ttl, json.dumps(value, default=str))
        except Exception:
            pass
    return value


def invalidate(*keys):
    """Drop cached values — call after a watchlist sync or a screening run."""
    r = _redis()
    if r is None:
        return 0
    try:
        if keys:
            return r.delete(*[_KEY + k for k in keys])
        found = list(r.scan_iter(_KEY + '*'))
        return r.delete(*found) if found else 0
    except Exception:
        return 0


def watchlist_stats():
    """Active watchlist size and last refresh — the two queries that were
    costing 7.8 seconds a page before indexing, and are now cached besides."""
    from database.db import query_db

    def produce():
        row = query_db("SELECT COUNT(*) AS c FROM screening_watchlist WHERE is_active = 1",
                       one=True)
        upd = query_db("SELECT MAX(last_updated) AS m FROM screening_watchlist", one=True)
        return {'count': dict(row)['c'] if row else 0,
                'last_updated': str(dict(upd)['m']) if upd and dict(upd)['m'] else None,
                'cached_at': time.time()}

    return cached('watchlist', TTL_WATCHLIST, produce)


def screening_stats():
    from database.db import query_db

    def produce():
        r = query_db("""SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE screening_result = 'MATCH')  AS matches,
                               COUNT(*) FILTER (WHERE status = 'PENDING')          AS pending,
                               COUNT(*) FILTER (WHERE created_at::date = CURRENT_DATE) AS today
                        FROM screening_results""", one=True)
        return dict(r) if r else {}

    return cached('stats', TTL_STATS, produce)


def source_breakdown():
    """Where screenings came from — for the history page filters."""
    from database.db import query_db

    def produce():
        rows = query_db("""SELECT source_module, COUNT(*) AS c
                           FROM screening_history
                           WHERE source_module IS NOT NULL
                           GROUP BY 1 ORDER BY 2 DESC""")
        return [dict(x) for x in rows]

    return cached('sources', TTL_STATS, produce)


def list_sources():
    """Distinct watchlist sources, for the 'which list matched' filter.

    Cached hard: a DISTINCT over 2.77M rows is expensive and the answer changes
    only when a new list is onboarded.
    """
    from database.db import query_db

    def produce():
        rows = query_db("""SELECT source, COUNT(*) AS c
                           FROM screening_watchlist
                           WHERE is_active = 1 AND source IS NOT NULL
                           GROUP BY 1 ORDER BY 2 DESC""")
        return [dict(x) for x in rows]

    return cached('list_sources', TTL_WATCHLIST, produce)
