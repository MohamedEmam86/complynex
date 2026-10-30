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
import time
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GUARD_KEY = 'list_update_guard'
MAX_AGE_KEY = 'list_max_age_hours'
GUARD_DEFAULT = {'max_drop_pct': 10.0, 'max_delist_pct': 10.0, 'min_abs': 25}
MAX_AGE_DEFAULT = 48
# lists downloaded by hand (no feed): a longer allowed age unless the MLRO sets one
MAX_AGE_SOURCE_DEFAULTS = {'pma_ps': 24 * 45}
MAX_AGE_REG_DEFAULT = 24 * 45          # *_reg regulatory lists are imported by hand
HARD_PCT = 50.0                        # a drop / deactivation above this is always blocked, whatever min_abs says
STALE_RUNNING_HOURS = 6                # a RUNNING version older than this is marked FAILED (process died)
FOUR_EYES_KEY = 'list_four_eyes'       # 'false' turns off "the approver must differ from who started the update"
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


def _plain(conn, name=None):
    """Tuple cursor whatever the connection's default factory (the updater's is RealDictCursor)."""
    import psycopg2.extensions
    if name:
        return conn.cursor(name=name, cursor_factory=psycopg2.extensions.cursor)
    return conn.cursor(cursor_factory=psycopg2.extensions.cursor)


class SourceBusy(RuntimeError):
    """Another update, import or rollback of the same list is running."""


@contextmanager
def source_lock(conn, source):
    """One writer per list at a time (scheduled / approved update, import, rollback).
    A session-level advisory lock: it survives the commits inside the update and is
    released at the end (or when the connection closes)."""
    key = 'cx_list_source:' + source
    c = _plain(conn)
    c.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (key,))
    if not c.fetchone()[0]:
        raise SourceBusy(f'another update or rollback of {source} is running')
    try:
        yield
    finally:
        try:
            try:
                _plain(conn).execute("SELECT pg_advisory_unlock(hashtext(%s))", (key,))
            except Exception:
                conn.rollback()
                _plain(conn).execute("SELECT pg_advisory_unlock(hashtext(%s))", (key,))
            conn.commit()
        except Exception as e:
            logger.warning('could not release the list lock of %s: %s', source, e)


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


def _cfg_raw(conn, key):
    try:
        c = _cur(conn)
        c.execute("SELECT config_value FROM screening_config WHERE config_key = %s", (key,))
        r = c.fetchone()
        return (r or {}).get('config_value')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def four_eyes_on(conn):
    v = _cfg_raw(conn, FOUR_EYES_KEY)
    return str(v).strip().lower() not in ('false', '0', 'no', 'off') if v is not None else True


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


def _pos(v):
    try:
        v = float(v)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def max_age_hours(source, cfg, freq_hours=None):
    """Allowed age: the MLRO's value for the list, else a list default (hand-imported
    PMA / *_reg lists), else twice the list's update frequency (weekly lists are not
    overdue after two days), never below the general default."""
    cfg = cfg or {}
    for v in (cfg.get(source), MAX_AGE_SOURCE_DEFAULTS.get(source),
              MAX_AGE_REG_DEFAULT if str(source).endswith('_reg') else None):
        if _pos(v):
            return _pos(v)
    base = _pos(cfg.get('default')) or float(MAX_AGE_DEFAULT)
    f = _pos(freq_hours)
    return max(base, 2 * f) if f else base


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


def _active_ids(conn, source):
    """Active record keys, streamed through a server-side tuple cursor (OpenSanctions: ~800k)."""
    c = _plain(conn, name='lv_active_ids')
    c.itersize = 20000
    c.execute("SELECT source_id FROM screening_watchlist WHERE source = %s AND is_active = 1 AND source_id IS NOT NULL",
              (source,))
    ids = [r[0] for r in c]
    c.close()
    return ids


_VCOLS = ('id, source, version_no, status, trigger, triggered_by, started_at, finished_at, file_sha256, '
          'content_sha256, hash_kind, fetched_count, active_before, active_after, snapshot_count, restored_from, '
          'snapshot IS NOT NULL AS has_snapshot')


def last_good(conn, source):
    c = _cur(conn)
    c.execute(f"""SELECT {_VCOLS} FROM screening_list_versions WHERE source = %s AND status = ANY(%s)
                  ORDER BY version_no DESC LIMIT 1""", (source, list(GOOD)))
    return c.fetchone()


def expire_stale(conn, hours=STALE_RUNNING_HOURS):
    """A version still RUNNING after `hours` (the process died) becomes FAILED, so the
    list shows red instead of looking fine for ever. Returns the expired rows."""
    try:
        c = _cur(conn)
        c.execute("""UPDATE screening_list_versions SET status = 'FAILED', finished_at = now(),
                        reason = COALESCE(reason || '; ', '') || %s
                     WHERE status = 'RUNNING' AND started_at < now() - make_interval(hours => %s)
                     RETURNING source, version_no""", (f'no result after {int(hours)} hours (the process stopped)',
                                                      int(hours)))
        rows = c.fetchall()
        conn.commit()
        return rows
    except Exception as e:
        logger.warning('could not expire stale list versions: %s', e)
        try:
            conn.rollback()
        except Exception:
            pass
        return []


# --------------------------------------------------------------------------- update path
def begin(conn, source, sha, hash_kind, fetched_count, user_id=None, trigger='scheduled', content_sha=None):
    """Record a RUNNING version (committed at once, so a crash still leaves a trace).
    Before the very first version of a source, the state in force is recorded as a
    BASELINE version with its snapshot, so the first update can already be rolled back."""
    c = _cur(conn)
    _lock(c, source)
    c.execute("SELECT 1 FROM screening_list_versions WHERE source = %s LIMIT 1", (source,))
    if not c.fetchone():
        ids = _active_ids(conn, source)
        if ids:
            c.execute("""INSERT INTO screening_list_versions
                           (source, version_no, status, trigger, started_at, finished_at, fetched_count,
                            active_before, active_after, snapshot, snapshot_count, reason)
                         VALUES (%s, 1, 'APPLIED', 'baseline', now(), now(), %s, %s, %s, %s, %s,
                                 'state in force before versioning started')""",
                        (source, len(ids), len(ids), len(ids), _pack(ids), len(ids)))
    no = _next_no(c, source)
    c.execute("""INSERT INTO screening_list_versions
                   (source, version_no, status, trigger, triggered_by, file_sha256, content_sha256, hash_kind,
                    fetched_count)
                 VALUES (%s, %s, 'RUNNING', %s, %s, %s, %s, %s, %s) RETURNING id""",
              (source, no, trigger, user_id, sha, content_sha, hash_kind, fetched_count))
    vid = c.fetchone()['id']
    conn.commit()
    return vid


def judge(baseline, fetched, active, projected, s, held_by=None):
    """The guard's decision on plain numbers (no database): the list of reasons to block.
    baseline = records of the version in force (or active today before the first version),
    active = records active now, projected = active records the update would deactivate."""
    reasons = []
    drop = max(0, baseline - fetched)
    drop_pct = round(100.0 * drop / baseline, 2) if baseline else 0.0
    delist_pct = round(100.0 * projected / active, 2) if active else 0.0
    if fetched == 0:
        reasons.append('the download has no records')
    elif baseline and drop_pct > s['max_drop_pct'] and (drop >= s['min_abs'] or drop_pct > HARD_PCT):
        reasons.append(f"record count fell {drop_pct:g}% ({baseline:,} -> {fetched:,}; limit {s['max_drop_pct']:g}%)")
    if active and projected and delist_pct > s['max_delist_pct'] and (projected >= s['min_abs'] or delist_pct > HARD_PCT):
        reasons.append(f"{projected:,} of {active:,} active records would be deactivated "
                       f"({delist_pct:g}%; limit {s['max_delist_pct']:g}%)")
    if held_by:
        reasons.append(f"the list was rolled back (version {held_by}); updates are held until the MLRO approves one")
    return reasons, drop_pct, delist_pct


def evaluate(conn, source, fetched_ids, sha=None, settings=None, content_sha=None):
    """Compare the download with the last good version. Writes nothing (temp table only).
    The deactivations are counted exactly as _sync_delistings will apply them: every active
    record of the source that is not in the download, whatever its id format."""
    c = _cur(conn)
    s = settings or guard_settings(conn, source)
    ids = list({i for i in fetched_ids if i})
    c.execute("SELECT count(*) AS n FROM screening_watchlist WHERE source = %s AND is_active = 1", (source,))
    active_all = int(c.fetchone()['n'] or 0)
    projected = 0
    if ids and active_all:
        c.execute("CREATE TEMP TABLE IF NOT EXISTS _lv_ids (source_id text PRIMARY KEY)")
        c.execute("TRUNCATE _lv_ids")
        from psycopg2.extras import execute_values
        execute_values(c, "INSERT INTO _lv_ids (source_id) VALUES %s ON CONFLICT DO NOTHING",
                       [(i,) for i in ids], page_size=5000)
        c.execute("""SELECT count(*) AS n FROM screening_watchlist w
                     WHERE w.source = %s AND w.is_active = 1
                       AND NOT EXISTS (SELECT 1 FROM _lv_ids f WHERE f.source_id = w.source_id)""", (source,))
        projected = int(c.fetchone()['n'] or 0)
        c.execute("DROP TABLE IF EXISTS _lv_ids")
    prev = last_good(conn, source)
    if prev and prev.get('trigger') != 'baseline' and (prev.get('fetched_count') or 0) > 0:
        baseline, kind = int(prev['fetched_count']), f"version {prev['version_no']}"
    else:
        baseline, kind = active_all, 'records active today'
    held_by = prev['version_no'] if prev and prev.get('status') == 'RESTORED' else None
    fetched = len(ids)
    reasons, drop_pct, delist_pct = judge(baseline, fetched, active_all, projected, s, held_by)
    approved = None
    key = content_sha or sha
    if reasons and key:
        c.execute("""SELECT id, version_no FROM screening_list_versions
                     WHERE source = %s AND status = 'BLOCKED' AND approved_at IS NOT NULL
                       AND approval_used_by IS NULL AND COALESCE(content_sha256, file_sha256) = %s
                     ORDER BY version_no DESC LIMIT 1""", (source, key))
        approved = c.fetchone()
    conn.commit()        # end the read transaction (the caller may hold committed-anyway progress rows)
    return {'source': source, 'fetched': fetched, 'baseline': baseline, 'baseline_kind': kind,
            'active_before': active_all, 'active_same_format': active_all,
            'projected_delist': int(projected), 'drop_pct': drop_pct, 'delist_pct': delist_pct,
            'settings': s, 'reasons': reasons, 'approved_version': (approved or {}).get('id'),
            'held_after_rollback': held_by, 'blocked': bool(reasons) and not approved}


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
    ids = _active_ids(conn, source)
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
    c.execute("""SELECT triggered_by FROM screening_list_versions
                 WHERE id = %s AND status = 'BLOCKED' AND approved_at IS NULL""", (vid,))
    pre = c.fetchone()
    if pre and pre.get('triggered_by') and user_id and int(pre['triggered_by']) == int(user_id) and four_eyes_on(conn):
        # four eyes: whoever started the update does not approve it, unless no other MLRO exists
        c.execute("""SELECT count(*) AS n FROM users WHERE is_active = 1 AND role = 'compliance_manager'
                     AND id <> %s""", (user_id,))
        if c.fetchone()['n']:
            conn.rollback()
            raise ValueError('You started this update; another MLRO must approve it (four eyes).')
    c.execute("""UPDATE screening_list_versions SET approved_by = %s, approved_at = now(), approval_reason = %s
                 WHERE id = %s AND status = 'BLOCKED' AND approved_at IS NULL RETURNING source, version_no""",
              (user_id, reason, vid))
    row = c.fetchone()
    if not row:
        conn.rollback()
        raise ValueError('Only a blocked version that is not yet approved can be approved.')
    conn.commit()
    return dict(row)


def _pick_target(rows):
    """(current, target) from good versions, newest first. After a rollback the version in
    force is RESTORED from X: going back again means the good version before X, not X."""
    if not rows:
        return None, None
    cur = rows[0]
    floor = None
    if cur.get('status') == 'RESTORED' and cur.get('restored_from'):
        src = next((r for r in rows if r['id'] == cur['restored_from']), None)
        floor = src['version_no'] if src else None
    for r in rows[1:]:
        if floor is not None and r['version_no'] >= floor:
            continue
        return cur, r
    return cur, None


def _good_rows(c, source, limit=KEEP_SNAPSHOTS + 5):
    c.execute(f"""SELECT {_VCOLS} FROM screening_list_versions
                  WHERE source = %s AND status = ANY(%s) ORDER BY version_no DESC LIMIT %s""",
              (source, list(GOOD), limit))
    return c.fetchall()


def rollback_target(conn, source):
    """(current good version, version to restore) or (current, None)."""
    c = _cur(conn)
    rows = _good_rows(c, source)
    conn.rollback()
    return _pick_target(rows)


def rollback_problem(conn, source):
    """Why a rollback cannot start now (None = it can)."""
    from screening.update_lock import held
    if held():
        return 'A list update is running now; try the rollback again when it has finished.'
    expire_stale(conn)
    c = _cur(conn)
    c.execute("SELECT version_no FROM screening_list_versions WHERE source = %s AND status = 'RUNNING' LIMIT 1",
              (source,))
    r = c.fetchone()
    conn.rollback()
    if r:
        return f"An update of this list is running (version {r['version_no']}); try again when it has finished."
    return None


def rollback(conn, source, user_id, reason):
    """Restore the active set of the previous good version. Returns a summary dict."""
    reason = (reason or '').strip()
    if len(reason) < 15:
        raise ValueError('Please give the reason (at least 15 characters).')
    problem = rollback_problem(conn, source)
    if problem:
        raise ValueError(problem)
    from screening.update_lock import hold
    try:
        lock = source_lock(conn, source)
        lock.__enter__()
    except SourceBusy as e:
        raise ValueError(str(e))
    try:
        with hold(f'rollback {source}'):
            return _rollback_locked(conn, source, user_id, reason)
    finally:
        lock.__exit__(None, None, None)


def _rollback_locked(conn, source, user_id, reason):
    if True:   # body kept at its original indentation (was inside `with hold(...)`)
        c = _cur(conn)
        _lock(c, source)
        cur_v, target = _pick_target(_good_rows(c, source))
        if not target:
            conn.rollback()
            raise ValueError('There is no earlier version of this list to go back to.')
        c.execute("SELECT snapshot FROM screening_list_versions WHERE id = %s", (target['id'],))
        target = dict(target, snapshot=c.fetchone()['snapshot'])
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
                     WHERE w.source = %s AND w.is_active = 1 AND w.source_id IS NOT NULL
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
                        content_sha256, hash_kind, fetched_count, active_before, active_after, delisted, relisted,
                        snapshot, snapshot_count, restored_from, reason)
                     VALUES (%s, %s, 'RESTORED', 'rollback', %s, now(), now(), %s, %s, %s, %s, %s, %s, %s, %s,
                             %s, %s, %s, %s) RETURNING id""",
                  (source, no, user_id, target['file_sha256'], target.get('content_sha256'), target['hash_kind'],
                   target['fetched_count'],
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
    c.execute("""SELECT source_name, source_display_name, last_successful_update, source_url,
                        update_frequency_hours, consecutive_failures
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
    c.execute("""SELECT DISTINCT ON (source) source, version_no, status, trigger, finished_at, fetched_count, active_after
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
        if g and g.get('trigger') == 'baseline':
            # the baseline is "when versioning started", not a download: use the real last update
            last_ok = None
        if last_ok is None:
            last_ok = log_ok.get(s) or (ds.get(s) or {}).get('last_successful_update') or \
                (reg.get(s) or {}).get('last_download_date') or (g or {}).get('finished_at')
        age = _age_hours(last_ok)
        freq = (ds.get(s) or {}).get('update_frequency_hours')
        mx = max_age_hours(s, cfg, freq)
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
                    'records': (g or {}).get('active_after'), 'freq': freq,
                    'failures': int((ds.get(s) or {}).get('consecutive_failures') or 0)})
    return out


# ---------------------------------------------------------------------------- cached reads for pages
_CACHE = {}


def _cached(key, ttl, fn):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    c = connect()
    try:
        val = fn(c)
    finally:
        c.close()
    _CACHE[key] = (time.time(), val)
    return val


def cached_freshness(ttl=60):
    """freshness() for page views (dashboard, quality page): one query set per minute."""
    return _cached('freshness', ttl, freshness)


def _timeline(conn):
    c = _cur(conn)
    try:
        c.execute("""SELECT source, version_no, finished_at FROM screening_list_versions
                     WHERE status IN ('APPLIED', 'RESTORED', 'ROLLED_BACK') AND finished_at IS NOT NULL
                     ORDER BY finished_at""")
        return [dict(r) for r in c.fetchall()]
    finally:
        conn.rollback()


def versions_at_cached(ts, ttl=120):
    """versions_at() for result pages, from a cached timeline (no connection per page view)."""
    if not ts:
        return {}
    try:
        t = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).strip().replace('Z', '+00:00'))
        if t.tzinfo is None:
            t = t.astimezone()
        out = {}
        for r in _cached('timeline', ttl, _timeline):
            if r['finished_at'] <= t:
                out[r['source']] = r['version_no']
        return out
    except Exception as e:
        logger.warning('versions_at_cached failed: %s', e)
        return {}


def audit(conn, user_id, action, details):
    """Audit row written from a background thread (no request context). Never raises."""
    try:
        try:
            from models.audit import _fp
            details = f'{details} [deploy:{_fp()}]'
        except Exception:
            pass
        c = _plain(conn)
        c.execute("""INSERT INTO audit_logs (user_id, action, module, item_id, details, ip_address, created_at)
                     VALUES (%s, %s, 'Screening', NULL, %s, NULL, %s)""", (user_id, action, details, datetime.now()))
        conn.commit()
    except Exception as e:
        logger.error('list audit failed (%s): %s', action, e)
        try:
            conn.rollback()
        except Exception:
            pass


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
    for r in expire_stale(conn):
        alert(conn, r['source'], 'failed', f"List update failed: {r['source']}",
              f"The update of {r['source']} (version {r['version_no']}) never finished; it is marked failed. "
              f"The previous version stays in force.")
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
