#!/usr/bin/env python3
"""Backfill the OpenSanctions profile fields (P2-2 for OpenSanctions).

The daily update only rewrites rows whose name changed, so the ~2.2M existing
OpenSanctions rows never receive the fields the loader now parses: every date
of birth, place of birth, nationality / citizenship, gender, passport and ID
numbers, other identifiers, addresses and all datasets (properties.datasets).

This script reads the current OpenSanctions files and writes, for every
existing row, exactly what the loader writes for a changed record
(EnhancedDataUpdater._update_entity + _store_rich), including the content
hash, so the next daily run sees those rows as unchanged. When every source
completed with --apply (no --limit), it switches screening_config
'opensanctions_rich' to 'on': from then on the daily update compares and
stores the rich fields itself.

    --dry-run (default)  read only: coverage report and timing, no writes
    --apply              write in batches (one short transaction each)
    --source             opensanctions | opensanctions_pep | all (default)
    --limit N            stop after N parsed entities per source
    --batch / --pause    rows per transaction / seconds between batches
    --file SRC=PATH      use a local copy of a source file instead of downloading
    --keep-download      keep the downloaded file(s) in --workdir
    --restart            forget which sources were completed (state file)

With --apply each file is downloaded completely first (about 2.6 GB + 0.9 GB in
--workdir) and removed at the end unless --keep-download.

Rows are matched on (source, source_id); rows that do not exist yet are left
to the daily update. is_active is never changed. The search-index sync is held
off (update marker) while writing; run scripts/es_incremental_sync.py after.
Run at night, not on the same night as another mass update of these rows.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

SOURCES = ('opensanctions', 'opensanctions_pep')
STATE = '/var/backups/complynex/os_rich_backfill_state.json'
COVER_KEYS = ('date_of_birth', 'multi_dob', 'place_of_birth', 'nationality', 'gender', 'passport_numbers',
              'national_id_numbers', 'identifiers', 'addresses', 'multi_datasets', 'weak_aliases', 'first_seen')


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


def _source_url(conn, source):
    c = conn.cursor()
    c.execute("SELECT source_url FROM screening_data_sources WHERE source_name = %s", (source,))
    r = c.fetchone()
    conn.commit()
    return r[0] if r else None


def _lines(source, url, local_path, workdir, keep):
    """Yield raw JSON lines of one OpenSanctions file (a local copy, or streamed from the source)."""
    if local_path:
        with open(local_path, 'rb') as f:
            for line in f:
                yield line
        return
    import requests
    path = None
    if keep:
        os.makedirs(workdir, exist_ok=True)
        path = os.path.join(workdir, f'{source}.ftm.json')
    r = requests.get(url, timeout=(15, 300), stream=True)
    r.raise_for_status()
    out = open(path, 'wb') if path else None
    try:
        for line in r.iter_lines():
            if out is not None:
                out.write(line + b'\n')
            yield line
    finally:
        if out is not None:
            out.close()
        r.close()


def _row_values(U, entity):
    """The columns the loader writes for a changed record, in UPDATE order."""
    import jellyfish
    from screening.data_updater_enhanced import normalize_arabic_text, stored_json_value as j
    from screening.format_handlers import expand_rich
    entity = expand_rich(entity)
    name_norm = normalize_arabic_text(entity['full_name'])
    yob = None
    if entity.get('date_of_birth'):
        try:
            yob = int(str(entity['date_of_birth'])[:4])
        except Exception:
            yob = None
    return (
        entity['full_name'], entity.get('original_name'), name_norm,
        jellyfish.soundex(name_norm) if name_norm else None,
        jellyfish.metaphone(name_norm) if name_norm else None,
        entity.get('dataset', entity.get('source', 'unknown')),
        entity.get('list_type', 'SANCTIONS'), entity.get('entity_type', 'INDIVIDUAL'),
        json.dumps(entity.get('topics', [])), json.dumps(entity.get('countries', [])),
        entity.get('date_of_birth'), yob, entity.get('nationality'), entity.get('gender'),
        entity.get('source_url'), entity.get('risk_level', 'MEDIUM'),
        json.dumps(entity.get('aliases', [])), json.dumps(entity.get('details', {})),
        entity.get('place_of_birth'), j(entity.get('passport_numbers')), j(entity.get('national_id_numbers')),
        j(entity.get('addresses')), j(entity.get('properties')), entity.get('full_name_arabic'),
        j(entity.get('aliases_arabic')), entity.get('first_seen'), U._content_hash(entity),
    )


UPDATE_SQL = """
UPDATE screening_watchlist w SET
    full_name = v.full_name, original_name = v.original_name, name_normalized = v.name_normalized,
    name_soundex = v.name_soundex, name_metaphone = v.name_metaphone, dataset = v.dataset,
    list_type = v.list_type, entity_type = v.entity_type, topics = v.topics, countries = v.countries,
    date_of_birth = v.date_of_birth, year_of_birth = v.year_of_birth::integer, nationality = v.nationality,
    gender = v.gender, source_url = v.source_url, risk_level = v.risk_level, aliases = v.aliases,
    details = v.details, place_of_birth = v.place_of_birth, passport_numbers = v.passport_numbers,
    national_id_numbers = v.national_id_numbers, addresses = v.addresses, properties = v.properties,
    full_name_arabic = v.full_name_arabic, aliases_arabic = v.aliases_arabic,
    first_seen = COALESCE(v.first_seen, w.first_seen), content_hash = v.content_hash,
    last_updated = CURRENT_TIMESTAMP
FROM (VALUES %s) AS v(id, full_name, original_name, name_normalized, name_soundex, name_metaphone, dataset,
      list_type, entity_type, topics, countries, date_of_birth, year_of_birth, nationality, gender, source_url,
      risk_level, aliases, details, place_of_birth, passport_numbers, national_id_numbers, addresses,
      properties, full_name_arabic, aliases_arabic, first_seen, content_hash)
WHERE w.id = v.id
"""


def _cover(entity, cov):
    from screening.format_handlers import expand_rich
    entity = expand_rich(entity)
    p = entity.get('properties') or {}
    checks = {
        'date_of_birth': entity.get('date_of_birth'),
        'multi_dob': len(p.get('dates_of_birth') or []) > 1,
        'place_of_birth': entity.get('place_of_birth'),
        'nationality': entity.get('nationality'),
        'gender': entity.get('gender'),
        'passport_numbers': entity.get('passport_numbers'),
        'national_id_numbers': entity.get('national_id_numbers'),
        'identifiers': p.get('identifiers'),
        'addresses': entity.get('addresses'),
        'multi_datasets': len(p.get('datasets') or []) > 1,
        'weak_aliases': p.get('weak_aliases'),
        'first_seen': entity.get('first_seen'),
    }
    for k, v in checks.items():
        if v:
            cov[k] = cov.get(k, 0) + 1


def run_source(conn, U, H, source, a, st):
    from psycopg2.extras import RealDictCursor, execute_values
    url = _source_url(conn, source)
    local = dict(x.split('=', 1) for x in a.file).get(source) if a.file else None
    if not url and not local:
        _log(f'{source}: no source URL - skipped')
        return False
    # resuming = running again: rows already written carry the loader's content hash and are
    # skipped after one read (a fresh download has other line positions, so lines are not skipped)
    skip = 0
    _log(f'{source}: start ({"apply" if a.apply else "dry-run"})')
    stats = {'lines': 0, 'parsed': 0, 'matched': 0, 'missing_in_db': 0, 'already_current': 0,
             'to_write': 0, 'written': 0, 'inactive_rows': 0, 'seconds_read_db': 0.0, 'seconds_write': 0.0}
    cov_new, cov_db = {}, {}
    t0 = time.time()
    batch = []

    def flush(final=False):
        if not batch:
            return
        ids = [e['source_id'] for e in batch]
        c = conn.cursor(cursor_factory=RealDictCursor)
        t = time.time()
        c.execute("""SELECT id, source_id, is_active, content_hash, date_of_birth, place_of_birth, nationality, gender,
                            passport_numbers, national_id_numbers, addresses, properties, first_seen
                     FROM screening_watchlist WHERE source = %s AND source_id = ANY(%s)""", (source, ids))
        rows = {r['source_id']: r for r in c.fetchall()}
        conn.commit()
        stats['seconds_read_db'] += time.time() - t
        values = []
        for e in batch:
            r = rows.get(e['source_id'])
            if not r:
                stats['missing_in_db'] += 1
                continue
            stats['matched'] += 1
            if not r['is_active']:
                stats['inactive_rows'] += 1
            for k in ('date_of_birth', 'place_of_birth', 'nationality', 'gender', 'passport_numbers',
                      'national_id_numbers', 'addresses', 'properties', 'first_seen'):
                if r.get(k):
                    cov_db[k] = cov_db.get(k, 0) + 1
            if r.get('content_hash') and r['content_hash'] == U._content_hash(e):
                stats['already_current'] += 1
                continue
            stats['to_write'] += 1
            values.append((r['id'],) + _row_values(U, e))
        if a.apply and values:
            t = time.time()
            c = conn.cursor()
            execute_values(c, UPDATE_SQL, values, template=None, page_size=len(values))
            # updated_at is set by trg_watchlist_updated_at (NOW()), as for every list update, so the
            # incremental search-index sync picks these rows up
            conn.commit()
            stats['written'] += len(values)
            stats['seconds_write'] += time.time() - t
            if a.pause:
                time.sleep(a.pause)
        batch.clear()

    downloaded = None
    if a.apply and not local:
        # download the whole file first: a stream held open for an hour of writes can be cut
        import requests
        os.makedirs(a.workdir, exist_ok=True)
        downloaded = os.path.join(a.workdir, f'{source}.ftm.json')
        _log(f'{source}: downloading to {downloaded}')
        with requests.get(url, timeout=(15, 300), stream=True) as r:
            r.raise_for_status()
            with open(downloaded + '.part', 'wb') as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        os.replace(downloaded + '.part', downloaded)
        local = downloaded
        _log(f'{source}: downloaded {os.path.getsize(downloaded) / 1e9:.2f} GB')
    for raw in _lines(source, url, local, a.workdir, a.keep_download and not downloaded):
        stats['lines'] += 1
        if stats['lines'] <= skip:
            continue
        try:
            line = raw.decode('utf-8') if isinstance(raw, bytes) else raw
            if not line.strip():
                continue
            e = H._parse_line(line)
        except Exception:
            continue
        if not e:
            continue
        stats['parsed'] += 1
        _cover(e, cov_new)
        batch.append(e)
        if len(batch) >= a.batch:
            flush()
            if a.apply:
                st.setdefault(source, {})['lines'] = stats['lines']
                _save_state(st)
            if stats['parsed'] % (a.batch * 50) == 0:
                el = time.time() - t0
                _log(f"{source}: {stats['parsed']:,} parsed, {stats['written']:,} written, {el:,.0f}s")
        if a.limit and stats['parsed'] >= a.limit:
            break
    flush(final=True)
    if downloaded and not a.keep_download:
        try:
            os.remove(downloaded)
        except OSError:
            pass
    complete = not a.limit
    if a.apply:
        st.setdefault(source, {}).update({'lines': stats['lines'], 'complete': complete,
                                          'finished_at': datetime.now().isoformat(timespec='seconds')})
        _save_state(st)
    el = time.time() - t0
    stats['seconds_total'] = round(el, 1)
    stats['seconds_read_db'] = round(stats['seconds_read_db'], 1)
    stats['seconds_write'] = round(stats['seconds_write'], 1)
    out = {'source': source, 'mode': 'apply' if a.apply else 'dry-run', 'stats': stats,
           'coverage_in_source_file': cov_new, 'coverage_stored_now': cov_db}
    print(json.dumps(out, indent=1), flush=True)
    return complete


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--source', default='all', choices=('all',) + SOURCES)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--batch', type=int, default=1000)
    ap.add_argument('--pause', type=float, default=0.2)
    ap.add_argument('--file', action='append', default=[], help='SOURCE=/path/to/entities.ftm.json')
    ap.add_argument('--workdir', default='/var/tmp/complynex_os')
    ap.add_argument('--keep-download', action='store_true')
    ap.add_argument('--restart', action='store_true')
    a = ap.parse_args()
    if a.dry_run:
        a.apply = False
    a.batch = max(100, min(a.batch, 5000))

    import psycopg2
    from config import Config
    from screening.format_handlers import OpenSanctionsHandler
    from screening.data_updater_enhanced import EnhancedDataUpdater as U
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    sources = SOURCES if a.source == 'all' else (a.source,)
    st = _load_state() if a.apply else {}
    if a.apply and a.restart:
        st = {}
        _save_state(st)

    lock_ctx = None
    if a.apply:
        from screening import list_versions as LV
        from screening.update_lock import hold
        for s in sources:
            LV.hold_source_lock(conn, s)          # no list update / rollback of these lists meanwhile
        lock_ctx = hold('opensanctions rich backfill')   # the search-index sync waits, checkpoint unchanged
        lock_ctx.__enter__()
    try:
        done = [run_source(conn, U, OpenSanctionsHandler(), s, a, st) for s in sources]
    finally:
        if lock_ctx is not None:
            lock_ctx.__exit__(None, None, None)

    if a.apply:
        st = _load_state()
        if all(st.get(s, {}).get('complete') for s in SOURCES):
            c = conn.cursor()
            c.execute("""INSERT INTO screening_config (config_key, config_value)
                         VALUES ('opensanctions_rich', 'on')
                         ON CONFLICT (config_key) DO UPDATE SET config_value = 'on'""")
            conn.commit()
            _log("both sources complete: screening_config opensanctions_rich = on")
            _log("next: run scripts/es_incremental_sync.py (search index) and scripts/index_health.py")
        else:
            _log('not every source is complete yet: the daily update keeps rich fields off')
    conn.close()


if __name__ == '__main__':
    main()
