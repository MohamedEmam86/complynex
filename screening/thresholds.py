"""
Screening tier thresholds — one source of truth (Phase 2).

The values live in screening_config (low_match_threshold, potential_match_threshold,
confirmed_hit_threshold), are editable by the MLRO on the screening configuration page
(with a written reason, audited, and a Gold Set impact preview), and are applied to the
engine and to match_intel on every screening (cached for CACHE_SECONDS, so a change
reaches every worker within a minute).

If the stored values are missing or invalid, the engine keeps the defaults below.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

DEFAULTS = {'low': 75.0, 'potential': 80.0, 'confirmed': 95.0}
KEYS = {'low': 'low_match_threshold', 'potential': 'potential_match_threshold',
        'confirmed': 'confirmed_hit_threshold'}
# sane bounds: below 60 the alert volume is unusable, a confirmed tier below 90 is not a confirmation
BOUNDS = {'low': (60.0, 90.0), 'potential': (65.0, 94.0), 'confirmed': (90.0, 100.0)}
CACHE_SECONDS = 60

_lock = threading.Lock()
_cache = {'at': 0.0, 'values': dict(DEFAULTS)}


def validate(values):
    """Return a list of problems (empty = valid) for a dict with low / potential / confirmed."""
    problems = []
    for k, (lo, hi) in BOUNDS.items():
        v = values.get(k)
        if v is None:
            problems.append(f'{k} is missing')
        elif not (lo <= v <= hi):
            problems.append(f'{k} must be between {lo:g} and {hi:g} (got {v:g})')
    if not problems and not (values['low'] < values['potential'] < values['confirmed']):
        problems.append('the values must satisfy low < potential < confirmed')
    return problems


def _read_db():
    # plain connection (not the Flask pool) so scripts and timers read the same values as the app
    import psycopg2
    from config import Config
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG, connect_timeout=5)
    try:
        cur = conn.cursor()
        cur.execute("SELECT config_key, config_value FROM screening_config WHERE config_key IN (%s, %s, %s)",
                    tuple(KEYS.values()))
        raw = dict(cur.fetchall())
    finally:
        conn.close()
    vals = {}
    for k, key in KEYS.items():
        try:
            vals[k] = float(raw.get(key))
        except (TypeError, ValueError):
            vals[k] = None
    return vals


def current(force=False):
    """The thresholds in force (cached)."""
    now = time.time()
    if not force and now - _cache['at'] < CACHE_SECONDS:
        return dict(_cache['values'])
    with _lock:
        try:
            vals = _read_db()
            if validate(vals):
                logger.warning('screening thresholds in screening_config are invalid %s; using defaults', vals)
                vals = dict(DEFAULTS)
        except Exception as ex:          # no app context / DB down: keep the last good values
            logger.debug('thresholds not readable (%s); keeping %s', ex, _cache['values'])
            vals = dict(_cache['values'])
        _cache['values'], _cache['at'] = vals, now
        return dict(vals)


def apply(engine=None, force=False):
    """Push the thresholds in force into match_intel (and an engine instance / its class)."""
    v = current(force=force)
    from screening import match_intel as mi
    mi.LOW, mi.POTENTIAL, mi.CONFIRMED = v['low'], v['potential'], v['confirmed']
    if engine is not None:
        cls = type(engine)
        cls.LOW_MATCH_THRESHOLD = v['low']
        cls.POTENTIAL_MATCH_THRESHOLD = v['potential']
        cls.CONFIRMED_HIT_THRESHOLD = v['confirmed']
    return v


# ---- Gold Set impact preview (screening config page) -------------------------------------
_prev = {'path': None, 'mtime': None, 'data': None}


def _preview_data():
    """Sorted core Gold Set scores written by scripts/gold_set_eval.py --write-baseline (no scoring here)."""
    import glob
    import json
    import os
    import re
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'screening', 'data', 'gold')
    files = sorted((f for f in glob.glob(os.path.join(base, 'preview_scores_v*.json'))
                    if re.search(r'preview_scores_v\d+\.json$', f)), key=lambda f: int(re.search(r'v(\d+)', f).group(1)))
    if not files:
        return None
    path = files[-1]
    mtime = os.path.getmtime(path)
    if _prev['path'] != path or _prev['mtime'] != mtime:
        with open(path) as f:
            _prev.update(path=path, mtime=mtime, data=json.load(f))
    return _prev['data']


def preview(low):
    """Core-tier Miss / FP rates on the Gold Set if the alert threshold were `low`."""
    import bisect
    d = _preview_data()
    if not d or not d.get('positive') or not d.get('negative'):
        return None
    pos, neg = d['positive'], d['negative']
    miss = bisect.bisect_left(pos, low)                 # positives scored below the threshold
    fp = len(neg) - bisect.bisect_left(neg, low)        # negatives at or above it
    return {'low': low, 'miss_rate': round(100.0 * miss / len(pos), 2), 'fp_rate': round(100.0 * fp / len(neg), 2),
            'pairs': len(pos) + len(neg)}
