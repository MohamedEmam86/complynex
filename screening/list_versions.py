"""
List versions, update guard, rollback and freshness (Phase 2: P2-1, P2-7).

Every list update (scheduled run, manual sync, file import) becomes a numbered
version per source in screening_list_versions: when, the hash of what was
downloaded, how many records came in, and what it changed (added / updated /
deactivated / reactivated).

Guard. Before anything is written, the downloaded list is compared with the last
good version (or, before the first version, with the records active today):
  * the record count drops by more than max_drop_pct, or
  * more than max_delist_pct of the active records would be deactivated,
and the change is at least min_abs records  ->  the update is NOT applied, the
version is recorded as BLOCKED and the MLRO is alerted. The MLRO can approve a
blocked version (written reason, audited); the next run with the same download
is then applied.

Rollback. After each applied version the set of active record keys (source_id)
is kept as a compressed snapshot (the last KEEP_SNAPSHOTS per source). A rollback
re-activates / de-activates records so that the active set equals the previous
good version's set. Nothing is deleted. Record content changed by the update is
not reverted (only the active set is), which is what decides whether a name is
screened. Every rollback is a new version (RESTORED) with its reason, audited.

Freshness. freshness() gives, per list: current version, last good update, age,
the allowed age (screening_config.list_max_age_hours) and a state:
green / amber (over 75% of the allowed age) / red (overdue, or the last update
failed or was blocked). check_and_alert() raises one MLRO notification per
problem and per day (index-health timer and the end of every scheduled run).

Settings in screening_config (JSON, MLRO-editable on the list versions page):
  list_update_guard     {"default": {"max_drop_pct": 10, "max_delist_pct": 10, "min_abs": 25}, "<source>": {...}}
  list_max_age_hours    {"default": 48, "<source>": hours}
"""
import gzip
import hashlib
import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GUARD_KEY = 'list_update_guard'
MAX_AGE_KEY = 'list_max_age_hours'
GUARD_DEFAULT = {'max_drop_pct': 10.0, 'max_delist_pct': 10.0, 'min_abs': 25}
MAX_AGE_DEFAULT = 48
# lists downloaded by hand (no feed): a longer allowed age unless the MLRO sets one
MAX_AGE_SOURCE_DEFAULTS = {'pma_ps': 24 * 45}
KEEP_SNAPSHOTS = 10
INTERNAL = {'internal_blacklist', 'internal_pep'}
GOOD = ('APPLIED', 'RESTORED')
ALERT_EVERY_HOURS = 20
LINK = '/screening/lists/versions'


# --------------------------------------------------------------------------- helpers
def connect():
    """A plain connection (scripts, timers and app threads use the same code)."""
    import psycopg2
    from config import Config
    return psycopg2.connect(**Config.POSTGRES_CONFIG, connect_timeout=10)


def _cur(conn):
    from psycopg2.extras import RealDictCursor
    return conn.cursor(cursor_factory=RealDictCursor)


def _iso_now():
    # ISO with 'T': the search index rejects 'YYYY-MM-DD HH:MM:SS' (see import_pma_national.py)
    return datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def _cfg_json(conn, key):
    try:
        c = _cur(conn)
        c.execute("SELECT config_value FROM screening_config WHERE config_key = %s", (key,))
        r = c.fetchone()
        v = json.loads(r['config_value']) if r and r['config_value'] else {}
        return v if isinstance(v, dict) else {}
    except Exception as e:
        logger.warning('screening_config %s unreadable (%s); using defaults', key, e)
        try:
            conn.rollback()
        except Exception:
            pass
        return {}


def guard_settings(conn, source, cfg=None):
    cfg = _cfg_json(conn, GUARD_KEY) if cfg is None else cfg
    out = dict(GUARD_DEFAULT)
    for part in (cfg.get('default'), cfg.get(source)):
        if isinstance(part, dict):
            for k in GUARD_DEFAULT:
                try:
                    if part.get(k) is not None:
                        out[k] = float(part[k])
                except (TypeError, ValueError):
                    pass
    return out


def max_age_hours(source, cfg):
    for v in (cfg.get(source), MAX_AGE_SOURCE_DEFAULTS.get(source), cfg.get('default'), MAX_AGE_DEFAULT):
        try:
            if v is not None and float(v) > 0:
                return float(v)
        except (TypeError, ValueError):
            continue
    return float(MAX_AGE_DEFAULT)


def validate_settings(guard, max_age):
    """Problems (empty = valid) for the two settings dicts as the MLRO submits them."""
    p = []
    for src, g in (guard or {}).items():
        if not isinstance(g, dict):
            p.append(f'{src}: guard must be an object')
            continue
        for k, v in g.items():
            if k not in GUARD_DEFAULT:
                p.append(f'{src}: unknown guard setting {k}')
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                p.append(f'{src}: {k} must be a number')
                continue
            if k.endswith('_pct') and not (1 <= v <= 90):
                p.append(f'{src}: {k} must be between 1 and 90')
            if k == 'min_abs' and not (0 <= v <= 100000):
                p.append(f'{src}: min_abs must be between 0 and 100000')
    for src, v in (max_age or {}).items():
        try:
            v = float(v)
        except (TypeError, ValueError):
            p.append(f'{src}: allowed age must be a number of hours')
            continue
        if not (6 <= v <= 24 * 120):
            p.append(f'{src}: allowed age must be between 6 and 2880 hours')
    return p


def file_sha256(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.encode('utf-8', 'surrogatepass')
    return hashlib.sha256(raw).hexdigest()


def content_sha256(entities):
    """Fingerprint of a parsed list (used when the download is streamed, e.g. OpenSanctions)."""
    h = hashlib.sha256()
    for line in sorted(f"{e.get('source_id') or ''}\t{e.get('full_name') or ''}" for e in entities):
        h.update(line.encode('utf-8', 'surrogatepass'))
        h.update(b'\n')
    return h.hexdigest()


def _prefixes(ids):
    return sorted({re.match(r'^\D*', i).group(0) for i in ids})


def _pack(ids):
    return gzip.compress('\n'.join(sorted(ids)).encode('utf-8'), 6)


def _unpack(blob):
    if blob is None:
        return None
    raw = gzip.decompress(bytes(blob)).decode('utf-8')
    return set(raw.split('\n')) if raw else set()


def _lock(cur, source):
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ('cx_list_version:' + source,))


def _next_no(cur, source):
    cur.execute("SELECT COALESCE(MAX(version_no), 0) + 1 AS n FROM screening_list_versions WHERE source = %s",
                (source,))
    return cur.fetchone()['n']


def _active_ids(cur, source):
    cur.execute("SELECT source_id FROM screening_watchlist WHERE source = %s AND is_active = 1 AND source_id IS NOT NULL",
                (source,))
    return [r['source_id'] for r in cur.fetchall()]


def last_good(conn, source):
    c = _cur(conn)
    c.execute("""SELECT * FROM screening_list_versions WHERE source = %s AND status = ANY(%s)
                 ORDER BY version_no DESC LIMIT 1""", (source, list(GOOD)))
    return c.fetchone()


# --------------------------------------------------------------------------- update path
def begin(conn, source, sha, hash_kind, fetched_count, user_id=None, trigger='scheduled'):
    """Record a RUNNING version (committed at once, so a crash still leaves a trace).
    Before the very first version of a source, the state in force is recorded as a
    BASELINE version with its snapshot, so the first update can already be rolled back."""
    c = _cur(conn)
    _lock(c, source)
    c.execute("SELECT 1 FROM screening_list_versions WHERE source = %s LIMIT 1", (source,))
    if not c.fetchone():
        ids = _active_ids(c, source)
        if ids:
            c.execute("""INSERT INTO screening_list_versions
                           (source, version_no, status, trigger, started_at, finished_at, fetched_count,
                            active_before, active_after, snapshot, snapshot_count, reason)
                         VALUES (%s, 1, 'APPLIED', 'baseline', now(), now(), %s, %s, %s, %s, %s,
                                 'state in force before versioning started')""",
                        (source, len(ids), len(ids), len(ids), _pack(ids), len(ids)))
    no = _next_no(c, source)
    c.execute("""INSERT INTO screening_list_versions
                   (source, version_no, status, trigger, triggered_by, file_sha256, hash_kind, fetched_count)
                 VALUES (%s, %s, 'RUNNING', %s, %s, %s, %s, %s) RETURNING id""",
              (source, no, trigger, user_id, sha, hash_kind, fetched_count))
    vid = c.fetchone()['id']
    conn.commit()
    return vid


def evaluate(conn, source, fetched_ids, sha=None, settings=None):
    """Compare the download with the last good version. Writes nothing (temp table only)."""
    c = _cur(conn)
    s = settings or guard_settings(conn, source)
    ids = list({i for i in fetched_ids if i})
    pref = _prefixes(ids) if ids else []
    c.execute("""SELECT count(*) AS n FROM screening_watchlist
                 WHERE source = %s AND is_active = 1 AND substring(source_id from '^\\D*') = ANY(%s)""",
              (source, pref))
    active_same = c.fetchone()['n']
    c.execute("SELECT count(*) AS n FROM screening_watchlist WHERE source = %s AND is_active = 1", (source,))
    active_all = c.fetchone()['n']
    projected = 0
    if ids and active_same:
        c.execute("CREATE TEMP TABLE IF NOT EXISTS _lv_ids (source_id text PRIMARY KEY)")
        c.execute("TRUNCATE _lv_ids")
        from psycopg2.extras import execute_values
        execute_values(c, "INSERT INTO _lv_ids (source_id) VALUES %s ON CONFLICT DO NOTHING",
                       [(i,) for i in ids], page_size=5000)
        c.execute("""SELECT count(*) AS n FROM screening_watchlist w
                     WHERE w.source = %s AND w.is_active = 1 AND substring(w.source_id from '^\\D*') = ANY(%s)
                       AND NOT EXISTS (SELECT 1 FROM _lv_ids f WHERE f.source_id = w.source_id)""", (source, pref))
        projected = c.fetchone()['n']
        c.execute("DROP TABLE IF EXISTS _lv_ids")
    prev = last_good(conn, source)
    if prev and prev.get('trigger') != 'baseline' and (prev.get('fetched_count') or 0) > 0:
        baseline, kind = int(prev['fetched_count']), f"version {prev['version_no']}"
    else:
        baseline, kind = int(active_same or 0), 'records active today'
    fetched = len(ids)
    drop = max(0, baseline - fetched)
    drop_pct = round(100.0 * drop / baseline, 2) if baseline else 0.0
    delist_pct = round(100.0 * projected / active_same, 2) if active_same else 0.0
    reasons = []
    if fetched == 0:
        reasons.append('the download has no records')
    if baseline and drop >= s['min_abs'] and drop_pct > s['max_drop_pct']:
        reasons.append(f"record count fell {drop_pct:g}% ({baseline:,} -> {fetched:,}; limit {s['max_drop_pct']:g}%)")
    if active_same and projected >= s['min_abs'] and delist_pct > s['max_delist_pct']:
        reasons.append(f"{projected:,} of {active_same:,} active records would be deactivated "
                       f"({delist_pct:g}%; limit {s['max_delist_pct']:g}%)")
    approved = None
    if reasons and sha:
        c.execute("""SELECT id, version_no FROM screening_list_versions
                     WHERE source = %s AND status = 'BLOCKED' AND approved_at IS NOT NULL
                       AND approval_used_by IS NULL AND file_sha256 = %s
                     ORDER BY version_no DESC LIMIT 1""", (source, sha))
        approved = c.fetchone()
    conn.commit()        # end the read transaction (the caller may hold committed-anyway progress rows)
    return {'source': source, 'fetched': fetched, 'baseline': baseline, 'baseline_kind': kind,
            'active_before': int(active_all or 0), 'active_same_format': int(active_same or 0),
            'projected_delist': int(projected), 'drop_pct': drop_pct, 'delist_pct': delist_pct,
            'settings': s, 'reasons': reasons, 'approved_version': (approved or {}).get('id'),
            'blocked': bool(reasons) and not approved}


def block(conn, vid, ev):
    c = _cur(conn)
    c.execute("""UPDATE screening_list_versions SET status = 'BLOCKED', finished_at = now(), reason = %s,
                    active_before = %s, guard = %s WHERE id = %s RETURNING source, version_no""",
              ('; '.join(ev['reasons']), ev['active_before'], json.dumps(ev, default=str), vid))
    row = c.fetchone()
    conn.commit()
    alert(conn, row['source'], 'blocked',
          f"List update blocked: {row['source']} (version {row['version_no']})",
          f"The update of {row['source']} was not applied: {'; '.join(ev['reasons'])}. "
          f"The previous version stays in force. Review it on the list versions page; "
          f"if the change is genuine, approve it there.", force=True)


def fail(conn, vid, error):
    try:
        conn.rollback()
        c = _cur(conn)
        c.execute("""UPDATE screening_list_versions SET status = 'FAILED', finished_at = now(), reason = %s
                     WHERE id = %s AND status = 'RUNNING' RETURNING source, version_no""", (str(error)[:1000], vid))
        row = c.fetchone()
        conn.commit()
        if row:
            alert(conn, row['source'], 'failed', f"List update failed: {row['source']}",
                  f"The update of {row['source']} (version {row['version_no']}) failed: {str(error)[:300]}. "
                  f"The previous version stays in force.")
    except Exception as e:
        logger.error('could not record failed list version %s: %s', vid, e)


def applied(conn, vid, stats, ev=None):
    """Mark the version APPLIED, keep the snapshot of the active set, prune old snapshots."""
    c = _cur(conn)
    c.execute("SELECT source FROM screening_list_versions WHERE id = %s", (vid,))
    source = c.fetchone()['source']
    ids = _active_ids(c, source)
    c.execute("""UPDATE screening_list_versions SET status = 'APPLIED', finished_at = now(),
                    added = %s, updated = %s, unchanged = %s, delisted = %s, relisted = %s,
                    active_before = COALESCE(%s, active_before), active_after = %s,
                    snapshot = %s, snapshot_count = %s, guard = COALESCE(%s, guard)
                 WHERE id = %s""",
              (int(stats.get('added') or 0), int(stats.get('updated') or 0), int(stats.get('unchanged') or 0),
               int(stats.get('delisted') or 0), int(stats.get('relisted') or 0),
               (ev or {}).get('active_before'), len(ids), _pack(ids), len(ids),
               json.dumps(ev, default=str) if ev else None, vid))
    if ev and ev.get('approved_version'):
        c.execute("UPDATE screening_list_versions SET approval_used_by = %s WHERE id = %s",
                  (vid, ev['approved_version']))
    _prune(c, source)
    conn.commit()


def _prune(c, source):
    c.execute("""UPDATE screening_list_versions SET snapshot = NULL
                 WHERE source = %s AND snapshot IS NOT NULL AND id NOT IN (
                   SELECT id FROM screening_list_versions WHERE source = %s AND snapshot IS NOT NULL
                   ORDER BY version_no DESC LIMIT %s)""", (source, source, KEEP_SNAPSHOTS))


# --------------------------------------------------------------------------- MLRO actions
def approve(conn, vid, user_id, reason):
    reason = (reason or '').strip()
    if len(reason) < 15:
        raise ValueError('Please give the reason (at least 15 characters).')
    c = _cur(conn)
    c.execute("""UPDATE screening_list_versions SET approved_by = %s, approved_at = now(), approval_reason = %s
                 WHERE id = %s AND status = 'BLOCKED' AND approved_at IS NULL RETURNING source, version_no""",
              (user_id, reason, vid))
    row = c.fetchone()
    if not row:
        conn.rollback()
        raise ValueError('Only a blocked version that is not yet approved can be approved.')
    conn.commit()
    return dict(row)


def rollback_target(conn, source):
    """(current good version, version to restore) or (current, None)."""
    c = _cur(conn)
    c.execute("""SELECT id, version_no, status, trigger, snapshot IS NOT NULL AS has_snapshot, snapshot_count,
                        finished_at FROM screening_list_versions
                 WHERE source = %s AND status = ANY(%s) ORDER BY version_no DESC LIMIT 2""",
              (source, list(GOOD)))
    rows = c.fetchall()
    conn.rollback()
    if len(rows) < 2:
        return (rows[0] if rows else None), None
    return rows[0], rows[1]


def rollback(conn, source, user_id, reason):
    """Restore the active set of the previous good version. Returns a summary dict."""
    reason = (reason or '').strip()
    if len(reason) < 15:
        raise ValueError('Please give the reason (at least 15 characters).')
    from screening.update_lock import hold
    with hold(f'rollback {source}'):
        c = _cur(conn)
        _lock(c, source)
        c.execute("""SELECT * FROM screening_list_versions WHERE source = %s AND status = ANY(%s)
                     ORDER BY version_no DESC LIMIT 2""", (source, list(GOOD)))
        rows = c.fetchall()
        if len(rows) < 2:
            conn.rollback()
            raise ValueError('There is no earlier version of this list to go back to.')
        cur_v, target = rows[0], rows[1]
        keep = _unpack(target['snapshot'])
        if keep is None:
            conn.rollback()
            raise ValueError('The earlier version has no stored snapshot (only the last %d are kept).' % KEEP_SNAPSHOTS)
        c.execute("SELECT count(*) AS n FROM screening_watchlist WHERE source = %s AND is_active = 1", (source,))
        before = c.fetchone()['n']
        c.execute("CREATE TEMP TABLE IF NOT EXISTS _lv_keep (source_id text PRIMARY KEY) ON COMMIT DROP")
        c.execute("TRUNCATE _lv_keep")
        from psycopg2.extras import execute_values
        execute_values(c, "INSERT INTO _lv_keep (source_id) VALUES %s ON CONFLICT DO NOTHING",
                       [(i,) for i in keep], page_size=5000)
        now = _iso_now()
        c.execute("""UPDATE screening_watchlist w SET is_active = 0, updated_at = %s
                     WHERE w.source = %s AND w.is_active = 1
                       AND NOT EXISTS (SELECT 1 FROM _lv_keep k WHERE k.source_id = w.source_id)""", (now, source))
        deact = c.rowcount
        c.execute("""UPDATE screening_watchlist w SET is_active = 1, updated_at = %s
                     WHERE w.source = %s AND w.is_active = 0
                       AND EXISTS (SELECT 1 FROM _lv_keep k WHERE k.source_id = w.source_id)""", (now, source))
        react = c.rowcount
        missing = len(keep) - (before - deact + react)
        no = _next_no(c, source)
        c.execute("""UPDATE screening_list_versions SET status = 'ROLLED_BACK', rolled_back_by = %s,
                        rolled_back_at = now(), rollback_reason = %s WHERE id = %s""", (user_id, reason, cur_v['id']))
        c.execute("""INSERT INTO screening_list_versions
                       (source, version_no, status, trigger, triggered_by, started_at, finished_at, file_sha256,
                        hash_kind, fetched_count, active_before, active_after, delisted, relisted,
                        snapshot, snapshot_count, restored_from, reason)
                     VALUES (%s, %s, 'RESTORED', 'rollback', %s, now(), now(), %s, %s, %s, %s, %s, %s, %s,
                             %s, %s, %s, %s) RETURNING id""",
                  (source, no, user_id, target['file_sha256'], target['hash_kind'], target['fetched_count'],
                   before, before - deact + react, deact, react, target['snapshot'], target['snapshot_count'],
                   target['id'], reason))
        new_id = c.fetchone()['id']
        _prune(c, source)
        conn.commit()
    out = {'source': source, 'version_id': new_id, 'version_no': no, 'restored_version': target['version_no'],
           'rolled_back_version': cur_v['version_no'], 'deactivated': deact, 'reactivated': react,
           'active_before': before, 'active_after': before - deact + react, 'missing': max(0, missing)}
    logger.info('list rollback %s', out)
    return out


# --------------------------------------------------------------------------- freshness + alerts
def _age_hours(ts):
    if not ts:
        return None
    try:
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.strip().replace('Z', '+00:00'))
        if ts.tzinfo is None:
            ts = ts.astimezone()
        return round((datetime.now(timezone.utc) - ts).total_seconds() / 3600.0, 1)
    except Exception:
        return None


def freshness(conn):
    """One row per list (internal lists excluded: they are maintained in the app)."""
    c = _cur(conn)
    cfg = _cfg_json(conn, MAX_AGE_KEY)
    c.execute("""SELECT source_name, source_display_name, last_successful_update, source_url
                 FROM screening_data_sources WHERE is_active = 1""")
    ds = {r['source_name']: r for r in c.fetchall()
          if r['source_name'] not in INTERNAL and (r['source_url'] or '') != 'internal'}
    srcs = set(ds)
    c.execute("SELECT DISTINCT source FROM screening_list_versions")
    srcs |= {r['source'] for r in c.fetchall()}
    reg = {}
    try:
        c.execute("SELECT list_code, list_name, last_download_date FROM sanctions_lists WHERE is_active = 1")
        reg = {r['list_code']: r for r in c.fetchall()}
        srcs |= {k for k in reg if k not in ds and (k == 'pma_ps' or k.endswith('_reg'))}
    except Exception:
        conn.rollback()
    srcs -= INTERNAL
    c.execute("""SELECT DISTINCT ON (source) source, version_no, status, finished_at, started_at
                 FROM screening_list_versions WHERE source = ANY(%s) ORDER BY source, version_no DESC""",
              (list(srcs),))
    latest = {r['source']: r for r in c.fetchall()}
    c.execute("""SELECT DISTINCT ON (source) source, version_no, status, finished_at, fetched_count, active_after
                 FROM screening_list_versions WHERE source = ANY(%s) AND status = ANY(%s)
                 ORDER BY source, version_no DESC""", (list(srcs), list(GOOD)))
    good = {r['source']: r for r in c.fetchall()}
    logs = {}
    try:
        c.execute("""SELECT DISTINCT ON (source) source, run_at, status, error FROM screening_list_update_log
                     WHERE source = ANY(%s) ORDER BY source, run_at DESC""", (list(srcs),))
        logs = {r['source']: r for r in c.fetchall()}
        c.execute("""SELECT DISTINCT ON (source) source, run_at FROM screening_list_update_log
                     WHERE source = ANY(%s) AND status = 'ok' ORDER BY source, run_at DESC""", (list(srcs),))
        log_ok = {r['source']: r['run_at'] for r in c.fetchall()}
    except Exception:
        conn.rollback()
        log_ok = {}
    conn.rollback()
    out = []
    for s in sorted(srcs):
        g, lt, lg = good.get(s), latest.get(s), logs.get(s) or {}
        last_ok = (g or {}).get('finished_at') if g and g.get('status') else None
        if last_ok is None:
            last_ok = log_ok.get(s) or (ds.get(s) or {}).get('last_successful_update') or \
                (reg.get(s) or {}).get('last_download_date')
        age = _age_hours(last_ok)
        mx = max_age_hours(s, cfg)
        problem = None
        lt_status = (lt or {}).get('status')
        if lt_status in ('BLOCKED', 'FAILED'):
            problem = 'blocked' if lt_status == 'BLOCKED' else 'failed'
        elif not lt and lg.get('status') in ('failed', 'blocked'):
            problem = lg['status']
        if problem:
            state = 'red'
        elif age is None or age > mx:
            state, problem = 'red', 'overdue'
        elif age > 0.75 * mx:
            state = 'amber'
        else:
            state = 'green'
        out.append({'source': s, 'name': (ds.get(s) or {}).get('source_display_name') or
                    (reg.get(s) or {}).get('list_name') or s,
                    'version_no': (g or {}).get('version_no'), 'latest_no': (lt or {}).get('version_no'),
                    'latest_status': lt_status or (lg.get('status') or '').upper() or None,
                    'last_ok': last_ok, 'age_hours': age, 'max_age_hours': mx, 'state': state, 'problem': problem,
                    'records': (g or {}).get('active_after')})
    return out


def versions_at(conn, ts):
    """{source: version_no} in force at a moment (e.g. when a screening ran)."""
    if not ts:
        return {}
    c = _cur(conn)
    try:
        c.execute("""SELECT DISTINCT ON (source) source, version_no FROM screening_list_versions
                     WHERE status IN ('APPLIED', 'RESTORED', 'ROLLED_BACK') AND finished_at <= %s::timestamptz
                     ORDER BY source, finished_at DESC""", (str(ts),))
        return {r['source']: r['version_no'] for r in c.fetchall()}
    except Exception as e:
        logger.warning('versions_at failed: %s', e)
        return {}
    finally:
        conn.rollback()


def _recipients(c):
    c.execute("SELECT id FROM users WHERE is_active = 1 AND role = 'compliance_manager' ORDER BY id")
    ids = [r['id'] for r in c.fetchall()]
    if not ids:
        c.execute("SELECT id FROM users WHERE is_active = 1 AND role = 'admin' ORDER BY id")
        ids = [r['id'] for r in c.fetchall()]
    return ids


def alert(conn, source, kind, title, message, force=False):
    """In-app notification to every MLRO (admins if none), at most once per source+kind
    every ALERT_EVERY_HOURS (force=True for a new blocked version). Never raises."""
    try:
        c = _cur(conn)
        if not force:
            c.execute("""SELECT 1 FROM screening_list_alerts WHERE source = %s AND kind = %s
                         AND created_at > now() - make_interval(hours => %s)""", (source, kind, ALERT_EVERY_HOURS))
            if c.fetchone():
                conn.rollback()
                return 0
        ids = _recipients(c)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for uid in ids:
            c.execute("""INSERT INTO notifications (user_id, title, message, type, is_read, link, created_at)
                         VALUES (%s, %s, %s, 'warning', 0, %s, %s)""", (uid, title[:200], message, LINK, now))
        c.execute("INSERT INTO screening_list_alerts (source, kind, title, recipients) VALUES (%s, %s, %s, %s)",
                  (source, kind, title[:200], len(ids)))
        conn.commit()
        logger.warning('LIST ALERT %s/%s -> %d user(s): %s', source, kind, len(ids), title)
        return len(ids)
    except Exception as e:
        logger.error('list alert failed (%s/%s): %s', source, kind, e)
        try:
            conn.rollback()
        except Exception:
            pass
        return 0


def check_and_alert(conn):
    """Alert on every list that is red (failed / blocked / overdue). Returns the red rows."""
    red = [f for f in freshness(conn) if f['state'] == 'red']
    for f in red:
        if f['problem'] == 'overdue':
            age = f'{f["age_hours"]:g} hours' if f['age_hours'] is not None else 'never updated'
            alert(conn, f['source'], 'overdue', f"List out of date: {f['name']}",
                  f"{f['name']} was last updated successfully {age} ago; the allowed age is "
                  f"{f['max_age_hours']:g} hours. Screenings still run on the version in force.")
        else:
            alert(conn, f['source'], f['problem'], f"List update {f['problem']}: {f['name']}",
                  f"The last update of {f['name']} {f['problem']}. The previous version stays in force.")
    return red


def history(conn, source=None, limit=60):
    c = _cur(conn)
    c.execute(f"""SELECT v.id, v.source, v.version_no, v.status, v.trigger, v.started_at, v.finished_at,
                         v.file_sha256, v.hash_kind, v.fetched_count, v.active_before, v.active_after, v.added,
                         v.updated, v.delisted, v.relisted, v.reason, v.snapshot IS NOT NULL AS has_snapshot,
                         v.approved_at, v.approval_reason, v.rolled_back_at, v.rollback_reason, v.restored_from,
                         v.approval_used_by,
                         NULLIF(TRIM(COALESCE(t.first_name,'') || ' ' || COALESCE(t.last_name,'')), '') AS triggered_by_name,
                         NULLIF(TRIM(COALESCE(a.first_name,'') || ' ' || COALESCE(a.last_name,'')), '') AS approved_by_name,
                         NULLIF(TRIM(COALESCE(r.first_name,'') || ' ' || COALESCE(r.last_name,'')), '') AS rolled_back_by_name
                  FROM screening_list_versions v
                  LEFT JOIN users t ON t.id = v.triggered_by
                  LEFT JOIN users a ON a.id = v.approved_by
                  LEFT JOIN users r ON r.id = v.rolled_back_by
                  {"WHERE v.source = %s" if source else ""}
                  ORDER BY v.started_at DESC, v.id DESC LIMIT %s""", ((source, limit) if source else (limit,)))
    rows = [dict(r) for r in c.fetchall()]
    conn.rollback()
    return rows
