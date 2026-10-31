#!/usr/bin/env python3
"""Backfill the OpenSanctions profile fields (P2-2 for OpenSanctions).

The daily update only rewrites rows whose name changed, so the ~2.2M existing
OpenSanctions rows never receive the fields the rich loader parses: every date
of birth, place of birth, nationality / citizenship, gender, passport numbers,
other identifiers (properties.identifiers), addresses and all datasets
(properties.datasets).

This script writes ONLY those profile columns (date_of_birth, year_of_birth,
nationality, gender, place_of_birth, passport_numbers, national_id_numbers,
addresses, properties, first_seen) and the content hash. The hash is written
only when every other stored column already equals what the loader would
write; otherwise it stays empty and the next daily update rewrites that row in
full. list_type is never touched (the OpenSanctions classification job owns it);
rows whose list_type would differ are only counted.

When every source has completed with --apply (no --limit, not stopped), it
switches screening_config 'opensanctions_rich' to 'on': from then on the daily
update parses, compares and stores the profile fields itself.

    --dry-run (default)  read only: coverage report, DOB clears, other differences
    --apply              write in batches; each batch takes the list's lock and the
                         update marker for its own few seconds only
    --source             opensanctions | opensanctions_pep | all (default)
    --limit N            stop after N parsed entities per source
    --batch / --pause    rows per transaction / seconds between batches
    --stop-at HH:MM      stop cleanly at this local time (default 03:45, before the
                         daily list update); run again the next night to resume
    --file SRC=PATH      use a local copy of a source file instead of downloading
    --keep-download      keep the downloaded file(s) in --workdir
    --restart            forget which sources were completed (state file)

With --apply each file is downloaded completely first (about 2.6 GB + 0.9 GB in
--workdir) and removed at the end unless --keep-download. --apply must run from
/var/www/complynex (the update marker lives there). Running again resumes:
rows already written carry the loader's hash and are skipped after one read.
After a run: scripts/es_incremental_sync.py (search index) and index_health.py.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

PROD_BASE = '/var/www/complynex'
SOURCES = ('opensanctions', 'opensanctions_pep')
STATE = '/var/backups/complynex/os_rich_backfill_state.json'
PROFILE_COLS = ('date_of_birth', 'year_of_birth', 'nationality', 'gender', 'place_of_birth', 'passport_numbers',
                'national_id_numbers', 'addresses', 'properties', 'first_seen')
OTHER_COLS = ('full_name', 'original_name', 'entity_type', 'dataset', 'topics', 'aliases', 'details',
              'full_name_arabic', 'aliases_arabic')


class StopRun(Exception):
    pass


def _log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st):
    try:
        tmp = STATE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(st, f)
        os.replace(tmp, STATE)
    except Exception as e:
        _log(f'could not save state: {e}')


def _deadline(hhmm):
    h, m = (int(x) for x in hhmm.split(':'))
    now = datetime.now()
    d = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return d if d > now else d + timedelta(days=1)


def _source_url(conn, source):
    c = conn.cursor()
    c.execute("SELECT source_url FROM screening_data_sources WHERE source_name = %s", (source,))
    r = c.fetchone()
    conn.commit()
    return r[0] if r else None


def _stream(url):
    import requests
    with requests.get(url, timeout=(15, 300), stream=True) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            yield line


def _file_lines(path):
    with open(path, 'rb') as f:
        for line in f:
            yield line


def _download(url, path):
    import requests
    with requests.get(url, timeout=(15, 300), stream=True) as r:
        r.raise_for_status()
        with open(path + '.part', 'wb') as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    os.replace(path + '.part', path)


def _profile(entity):
    """Profile columns as the loader writes them (EnhancedDataUpdater._update_entity / _store_rich)."""
    from screening.data_updater_enhanced import stored_json_value as j
    yob = None
    if entity.get('date_of_birth'):
        try:
            yob = int(str(entity['date_of_birth'])[:4])
        except Exception:
            yob = None
    return {
        'date_of_birth': entity.get('date_of_birth'), 'year_of_birth': yob,
        'nationality': entity.get('nationality'), 'gender': entity.get('gender'),
        'place_of_birth': entity.get('place_of_birth'), 'passport_numbers': j(entity.get('passport_numbers')),
        'national_id_numbers': j(entity.get('national_id_numbers')), 'addresses': j(entity.get('addresses')),
        'properties': j(entity.get('properties')), 'first_seen': entity.get('first_seen'),
    }


def _others(entity):
    """The other columns as the loader would write them (to know if the stored row is current)."""
    from screening.data_updater_enhanced import stored_json_value as j
    return {
        'full_name': entity['full_name'], 'original_name': entity.get('original_name'),
        'entity_type': entity.get('entity_type', 'INDIVIDUAL'),
        'dataset': entity.get('dataset', entity.get('source', 'unknown')),
        'topics': json.dumps(entity.get('topics', [])), 'aliases': json.dumps(entity.get('aliases', [])),
        'details': json.dumps(entity.get('details', {})),
        'full_name_arabic': entity.get('full_name_arabic'), 'aliases_arabic': j(entity.get('aliases_arabic')),
    }


def _row_values(U, entity, with_hash=True):
    """(profile values in PROFILE_COLS order) + content hash (or None)."""
    from screening.format_handlers import expand_rich
    e = expand_rich(entity)
    p = _profile(e)
    return tuple(p[k] for k in PROFILE_COLS) + ((U._content_hash(e) if with_hash else None),)


UPDATE_SQL = """
UPDATE screening_watchlist w SET
    date_of_birth = v.date_of_birth, year_of_birth = v.year_of_birth::integer, nationality = v.nationality,
    gender = v.gender, place_of_birth = v.place_of_birth, passport_numbers = v.passport_numbers,
    national_id_numbers = v.national_id_numbers, addresses = v.addresses, properties = v.properties,
    first_seen = COALESCE(v.first_seen, w.first_seen), content_hash = v.content_hash
FROM (VALUES %s) AS v(id, date_of_birth, year_of_birth, nationality, gender, place_of_birth, passport_numbers,
      national_id_numbers, addresses, properties, first_seen, content_hash)
WHERE w.id = v.id
"""


def _same(stored, new):
    return (stored or None) == (new or None)


def _cover(e, cov):
    p = e.get('properties') or {}
    for k, v in (('date_of_birth', e.get('date_of_birth')), ('multi_dob', len(p.get('dates_of_birth') or []) > 1),
                 ('place_of_birth', e.get('place_of_birth')), ('nationality', e.get('nationality')),
                 ('gender', e.get('gender')), ('passport_numbers', e.get('passport_numbers')),
                 ('identifiers', p.get('identifiers')), ('addresses', e.get('addresses')),
                 ('multi_datasets', len(p.get('datasets') or []) > 1), ('weak_aliases', p.get('weak_aliases')),
                 ('first_seen', e.get('first_seen'))):
        if v:
            cov[k] = cov.get(k, 0) + 1


def run_source(conn, U, H, source, a, deadline):
    from psycopg2.extras import RealDictCursor, execute_values
    from screening.format_handlers import expand_rich
    url = _source_url(conn, source)
    local = dict(x.split('=', 1) for x in a.file).get(source) if a.file else None
    if not url and not local:
        _log(f'{source}: no source URL - skipped')
        return False
    downloaded = None
    if a.apply and not local:
        os.makedirs(a.workdir, exist_ok=True)
        downloaded = os.path.join(a.workdir, f'{source}.ftm.json')
        _log(f'{source}: downloading to {downloaded}')
        _download(url, downloaded)
        local = downloaded
        _log(f'{source}: downloaded {os.path.getsize(downloaded) / 1e9:.2f} GB')
    lines = _file_lines(local) if local else _stream(url)
    _log(f'{source}: start ({"apply" if a.apply else "dry-run"}), stop at {deadline:%Y-%m-%d %H:%M}')
    st = {'parsed': 0, 'matched': 0, 'missing_in_db': 0, 'already_current': 0, 'to_write': 0,
          'with_hash': 0, 'without_hash_other_columns_differ': 0, 'written': 0, 'dob_cleared': 0,
          'dob_changed': 0, 'dob_added': 0, 'nationality_changed': 0, 'list_type_would_differ': 0,
          'seconds_read_db': 0.0, 'seconds_write': 0.0}
    other_diff, cov = {}, {}
    t0 = time.time()
    batch, stopped = [], False

    def flush():
        if not batch:
            return
        c = conn.cursor(cursor_factory=RealDictCursor)
        t = time.time()
        c.execute(f"""SELECT id, source_id, content_hash, list_type, {', '.join(PROFILE_COLS + OTHER_COLS)}
                      FROM screening_watchlist WHERE source = %s AND source_id = ANY(%s)""",
                  (source, [e['source_id'] for e in batch]))
        rows = {r['source_id']: r for r in c.fetchall()}
        conn.commit()
        st['seconds_read_db'] += time.time() - t
        values = []
        for raw_e in batch:
            r = rows.get(raw_e['source_id'])
            if not r:
                st['missing_in_db'] += 1
                continue
            st['matched'] += 1
            e = expand_rich(raw_e)
            h = U._content_hash(e)
            if r.get('content_hash') and r['content_hash'] == h:
                st['already_current'] += 1
                continue
            p, o = _profile(e), _others(e)
            if r.get('date_of_birth') and not p['date_of_birth']:
                st['dob_cleared'] += 1
            elif r.get('date_of_birth') and p['date_of_birth'] != r['date_of_birth']:
                st['dob_changed'] += 1
            elif p['date_of_birth'] and not r.get('date_of_birth'):
                st['dob_added'] += 1
            if not _same(r.get('nationality'), p['nationality']):
                st['nationality_changed'] += 1
            if not _same(r.get('list_type'), e.get('list_type')):
                st['list_type_would_differ'] += 1
            diff = [k for k in OTHER_COLS if not _same(r.get(k), o[k])]
            for k in diff:
                other_diff[k] = other_diff.get(k, 0) + 1
            if diff:
                st['without_hash_other_columns_differ'] += 1
            else:
                st['with_hash'] += 1
            st['to_write'] += 1
            values.append((r['id'],) + tuple(p[k] for k in PROFILE_COLS) + ((None if diff else h),))
        if a.apply and values:
            from screening import list_versions as LV
            from screening.update_lock import hold
            t = time.time()
            try:
                # the list's lock and the update marker for this batch only (a few seconds):
                # a list update or a rollback is never kept waiting by the backfill
                with LV.source_lock(conn, source):
                    with hold(f'opensanctions rich backfill {source}'):
                        execute_values(conn.cursor(), UPDATE_SQL, values, page_size=len(values))
                        conn.commit()
            except LV.SourceBusy:
                raise StopRun(f'{source}: a list update or rollback is running - stopped, run again later')
            st['written'] += len(values)
            st['seconds_write'] += time.time() - t
            if a.pause:
                time.sleep(a.pause)
        batch.clear()

    try:
        for raw in lines:
            try:
                line = raw.decode('utf-8') if isinstance(raw, bytes) else raw
                if not line.strip():
                    continue
                e = H._parse_line(line)
            except Exception:
                continue
            if not e:
                continue
            st['parsed'] += 1
            _cover(expand_rich(e), cov)
            batch.append(e)
            if len(batch) >= a.batch:
                if a.apply and datetime.now() >= deadline:
                    raise StopRun(f'{source}: reached {deadline:%H:%M} - stopped cleanly, run again to resume')
                flush()
                if st['parsed'] % (a.batch * 100) == 0:
                    _log(f"{source}: {st['parsed']:,} parsed, {st['written']:,} written, {time.time() - t0:,.0f}s")
            if a.limit and st['parsed'] >= a.limit:
                break
        flush()
    except StopRun as ex:
        _log(str(ex))
        stopped = True
    finally:
        if downloaded and not a.keep_download:
            try:
                os.remove(downloaded)
            except OSError:
                pass
    complete = not a.limit and not stopped
    st['seconds_total'] = round(time.time() - t0, 1)
    st['seconds_read_db'] = round(st['seconds_read_db'], 1)
    st['seconds_write'] = round(st['seconds_write'], 1)
    print(json.dumps({'source': source, 'mode': 'apply' if a.apply else 'dry-run', 'complete': complete,
                      'stats': st, 'other_columns_differ': other_diff, 'coverage_in_source_file': cov},
                     indent=1), flush=True)
    return complete


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--source', default='all', choices=('all',) + SOURCES)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--batch', type=int, default=1000)
    ap.add_argument('--pause', type=float, default=0.2)
    ap.add_argument('--stop-at', default='03:45')
    ap.add_argument('--file', action='append', default=[], help='SOURCE=/path/to/entities.ftm.json')
    ap.add_argument('--workdir', default='/var/tmp/complynex_os')
    ap.add_argument('--keep-download', action='store_true')
    ap.add_argument('--restart', action='store_true')
    a = ap.parse_args()
    if a.dry_run:
        a.apply = False
    a.batch = max(100, min(a.batch, 5000))
    if a.apply:
        from screening import update_lock
        if os.path.realpath(BASE) != PROD_BASE or not os.path.realpath(update_lock.LOCK_DIR).startswith(PROD_BASE + '/'):
            sys.exit(f'--apply must run from {PROD_BASE} (update marker there); this copy is {BASE}')

    import psycopg2
    from config import Config
    from screening.format_handlers import OpenSanctionsHandler
    from screening.data_updater_enhanced import EnhancedDataUpdater as U
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    sources = SOURCES if a.source == 'all' else (a.source,)
    deadline = _deadline(a.stop_at)
    st = _load_state() if a.apply else {}
    if a.apply and a.restart:
        st = {}
        _save_state(st)
    for s in sources:
        if a.apply and st.get(s, {}).get('complete') and not a.restart:
            _log(f'{s}: already complete (state file) - skipped; --restart to run it again')
            continue
        done = run_source(conn, U, OpenSanctionsHandler(rich=True), s, a, deadline)
        if a.apply:
            st.setdefault(s, {}).update({'complete': done, 'finished_at': datetime.now().isoformat(timespec='seconds')})
            _save_state(st)
        if a.apply and datetime.now() >= deadline:
            break
    if a.apply:
        st = _load_state()
        if all(st.get(s, {}).get('complete') for s in SOURCES):
            c = conn.cursor()
            c.execute("""INSERT INTO screening_config (config_key, config_value)
                         VALUES ('opensanctions_rich', 'on')
                         ON CONFLICT (config_key) DO UPDATE SET config_value = 'on'""")
            conn.commit()
            _log('both sources complete: screening_config opensanctions_rich = on')
        else:
            _log('not every source is complete yet: the daily update keeps the profile fields off')
        _log('next: scripts/es_incremental_sync.py (search index) and scripts/index_health.py')
    conn.close()


if __name__ == '__main__':
    main()
