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
Bulk screening (P4-9): a file of names screened in the background, with no
row lost.

Flow: upload (CSV / Excel) -> column mapping -> input-quality check per row
(P3-11) with a summary before anything runs -> background run -> report of
hits, INCOMPLETE screenings and failed rows only, plus totals and an Excel
export of every row.

Why it is built this way (the previous version kept jobs in a per-process
dict and ran a nested function in a process pool):
- jobs and rows live in PostgreSQL, so any web worker can show progress and
  a restart loses nothing;
- the run is a separate process (scripts/bulk_screening_worker.py), so a web
  restart or a long file never ties up a web worker;
- every row ends in exactly one state (DONE / FAILED / SKIPPED) with its
  reason; rows in == rows out is checked at the end and shown on the report;
- a run is resumable: a worker that died leaves RUNNING rows behind, the
  next run puts them back to PENDING (heartbeat older than STALE_SECONDS);
- every screened row is saved as its own screening result, so clearances,
  the queue and the evidence pack work per row exactly as for a single
  screening.

The logic is written against a small store interface (SqlStore for
production, MemoryStore for tests and dry runs) so it can be proved on a
large file without writing anything.
"""
import json
import os
import logging
import re
import threading
import time
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_ROWS = 20000
STALE_SECONDS = 180
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CONCURRENT = int(os.getenv('BULK_MAX_CONCURRENT', '2'))
FIELDS = ('name', 'entity_type', 'dob', 'nationality', 'national_id', 'customer_ref')

# header synonyms (normalised: lower case, no spaces / punctuation)
_SYNONYMS = {
    'name': ('name', 'fullname', 'customername', 'entityname', 'clientname', 'merchantname', 'companyname',
             'الاسم', 'اسم', 'الاسمبالكامل', 'اسمالعميل', 'اسمالشركه', 'اسمالشركة'),
    'entity_type': ('type', 'entitytype', 'kind', 'customertype', 'النوع', 'نوعالعميل', 'الصفة', 'الصفه'),
    'dob': ('dob', 'dateofbirth', 'birthdate', 'birth', 'تاريخالميلاد', 'الميلاد'),
    'nationality': ('nationality', 'country', 'citizenship', 'countryofbirth', 'الجنسية', 'الجنسيه', 'الدولة', 'الدوله'),
    'national_id': ('id', 'nationalid', 'idnumber', 'nid', 'passport', 'registrationnumber', 'crnumber',
                    'الرقمالقومي', 'رقمالهوية', 'رقمالهويه', 'الرقم', 'السجلالتجاري'),
    'customer_ref': ('ref', 'reference', 'customerref', 'customerid', 'clientid', 'accountnumber', 'code',
                     'رقمالعميل', 'الكود', 'المرجع'),
}

_ENTITY_WORDS = {
    'ENTITY': ('entity', 'company', 'corporate', 'organisation', 'organization', 'business', 'merchant',
               'legal', 'شركة', 'شركه', 'كيان', 'منشأة', 'منشاه', 'تاجر'),
    'INDIVIDUAL': ('individual', 'person', 'natural', 'فرد', 'شخص', 'طبيعي'),
}


def _hnorm(h):
    return re.sub(r'[\s_\-\./()]+', '', str(h or '').strip().lower())


def guess_mapping(headers):
    """{field: header} for the headers we recognise; a header is used once."""
    out, used = {}, set()
    norm = {h: _hnorm(h) for h in headers}
    for field in FIELDS:
        for h in headers:
            if h in used:
                continue
            if norm[h] in _SYNONYMS[field]:
                out[field] = h
                used.add(h)
                break
    return out


def _cell(v):
    """Excel / CSV cell -> clean string ('' for blanks, dates as YYYY-MM-DD)."""
    if v is None:
        return ''
    try:
        import math
        if isinstance(v, float) and math.isnan(v):
            return ''
    except Exception:
        pass
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%d')
    if hasattr(v, 'strftime') and hasattr(v, 'year'):
        try:
            return v.strftime('%Y-%m-%d')
        except Exception:
            pass
    s = str(v).strip()
    if s.lower() in ('nan', 'nat', 'none', 'null'):
        return ''
    if re.fullmatch(r'\d+\.0', s):          # 29001011234567.0 from Excel numbers
        s = s[:-2]
    if re.fullmatch(r'\d{4}-\d{2}-\d{2} 00:00:00', s):
        s = s[:10]
    return s


def read_file(stream, filename):
    """(headers, rows as list of dicts header->str). Raises ValueError with a user message."""
    import pandas as pd
    fn = (filename or '').lower()
    try:
        if fn.endswith('.csv'):
            raw = stream.read()
            text = None
            for enc in ('utf-8-sig', 'cp1256', 'latin-1'):
                try:
                    text = raw.decode(enc)
                    break
                except Exception:
                    continue
            import io
            df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
        elif fn.endswith('.xlsx') or fn.endswith('.xls'):
            if fn.endswith('.xlsx'):
                # count rows cheaply (read-only) before pandas loads the whole sheet
                import openpyxl
                wb = openpyxl.load_workbook(stream, read_only=True, data_only=True)
                try:
                    ws = wb.worksheets[0]
                    nrows = 0
                    for _r in ws.iter_rows(values_only=True):
                        nrows += 1
                        if nrows > MAX_ROWS + 1:
                            break
                finally:
                    wb.close()
                if nrows > MAX_ROWS + 1:
                    raise ValueError(f'The file has more than {MAX_ROWS:,} rows; the limit is {MAX_ROWS:,} per file.')
                stream.seek(0)
            df = pd.read_excel(stream, dtype=object)
        else:
            raise ValueError('Allowed file types are CSV and Excel (.xlsx)')
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f'The file could not be read: {str(e)[:200]}')
    headers = [str(c).strip() for c in df.columns]
    if not headers:
        raise ValueError('The file has no columns.')
    if len(df) > MAX_ROWS:
        raise ValueError(f'The file has {len(df):,} rows; the limit is {MAX_ROWS:,} per file.')
    rows = []
    for rec in df.itertuples(index=False, name=None):
        rows.append({h: _cell(v) for h, v in zip(headers, rec)})
    return headers, rows


def entity_type_of(value, default='INDIVIDUAL'):
    v = str(value or '').strip().lower()
    if not v:
        return default
    for et, words in _ENTITY_WORDS.items():
        if any(w in v for w in words):
            return et
    return default


def normalise_row(raw, mapping, default_type='INDIVIDUAL'):
    """Mapped, cleaned fields of one raw row + its input-quality warnings."""
    def get(field):
        h = mapping.get(field)
        return _cell(raw.get(h)) if h else ''
    row = {f: get(f) for f in FIELDS}
    row['entity_type'] = entity_type_of(row['entity_type'], default_type)
    warnings = []
    if row['name']:
        try:
            from screening import input_quality as iq
            warnings = iq.assess(row['name'], row['entity_type'], row['nationality'] or None,
                                 row['dob'] or None, row['national_id'] or None) or []
        except Exception as e:
            logger.warning(f'[BULK] input check failed: {e}')
    return row, warnings


def summarise(rows):
    """Pre-run summary from normalised rows: [{'row':..., 'warnings':[...], 'skip': reason|None}]."""
    total = len(rows)
    skipped = [r for r in rows if r.get('skip')]
    warned = [r for r in rows if not r.get('skip') and r.get('warnings')]
    by_code = {}
    for r in warned:
        for w in r['warnings']:
            code = w.get('code') if isinstance(w, dict) else str(w)
            e = by_code.setdefault(code, {'n': 0, 'en': (w.get('en') if isinstance(w, dict) else code) or code,
                                          'ar': (w.get('ar') if isinstance(w, dict) else code) or code})
            e['n'] += 1
    return {'total': total, 'to_screen': total - len(skipped), 'skipped': len(skipped),
            'with_warnings': len(warned),
            'warnings_by_code': dict(sorted(by_code.items(), key=lambda x: -x[1]['n']))}


# --------------------------------------------------------------------------- stores
class MemoryStore:
    """Same interface as SqlStore, in memory (tests, dry runs)."""

    def __init__(self):
        self.jobs, self.rows = {}, {}
        self.lock = threading.Lock()

    def create_job(self, user_id, filename, headers, raw_rows):
        jid = str(uuid.uuid4())
        self.jobs[jid] = {'id': jid, 'created_by': user_id, 'filename': filename, 'headers': headers,
                          'status': 'MAPPING', 'total_rows': len(raw_rows), 'heartbeat': None,
                          'created_at': datetime.now(), 'column_map': {}}
        self.rows[jid] = [{'row_no': i + 1, 'raw': r, 'status': 'NEW'} for i, r in enumerate(raw_rows)]
        return jid

    def job(self, jid):
        return self.jobs.get(jid)

    def raw_rows(self, jid):
        return [(r['row_no'], r['raw']) for r in self.rows[jid]]

    def save_mapping(self, jid, mapping, prepared, default_type):
        with self.lock:
            for r in self.rows[jid]:
                fields, warnings, skip = prepared[r['row_no']]
                r.update(fields)
                r['input_warnings'] = warnings
                r['status'] = 'SKIPPED' if skip else 'PENDING'
                r['error'] = skip
            self.jobs[jid].update({'column_map': mapping, 'default_type': default_type, 'status': 'READY'})

    def set_status(self, jid, status, **extra):
        with self.lock:
            self.jobs[jid]['status'] = status
            self.jobs[jid].update(extra)

    def retry_failed(self, jid):
        with self.lock:
            n = 0
            for r in self.rows[jid]:
                if r['status'] == 'FAILED':
                    r['status'], r['error'] = 'PENDING', None
                    n += 1
            return n

    def running_jobs(self, exclude=None):
        with self.lock:
            return [dict(j) for k, j in self.jobs.items() if j.get('status') == 'RUNNING' and k != exclude]

    def reset_stale(self, jid):
        with self.lock:
            n = 0
            for r in self.rows[jid]:
                if r['status'] == 'RUNNING':
                    r['status'] = 'PENDING'
                    n += 1
            return n

    def claim(self, jid, n):
        with self.lock:
            out = []
            for r in self.rows[jid]:
                if r['status'] == 'PENDING':
                    r['status'] = 'RUNNING'
                    r['attempts'] = r.get('attempts', 0) + 1
                    out.append(dict(r))
                    if len(out) >= n:
                        break
            return out

    def finish_row(self, jid, row_no, status, **f):
        with self.lock:
            r = self.rows[jid][row_no - 1]
            r['status'] = status
            r.update(f)

    def heartbeat(self, jid):
        with self.lock:
            self.jobs[jid]['heartbeat'] = datetime.now()

    def counts(self, jid):
        c = {}
        for r in self.rows[jid]:
            c[r['status']] = c.get(r['status'], 0) + 1
        res = {}
        for r in self.rows[jid]:
            if r['status'] == 'DONE':
                res[r.get('result_status')] = res.get(r.get('result_status'), 0) + 1
        return c, res

    def rows_for_report(self, jid, flagged_only=True):
        out = []
        for r in self.rows[jid]:
            if not flagged_only or r['status'] == 'FAILED' or r.get('result_status') in FLAGGED:
                out.append(dict(r))
        return out


FLAGGED = ('CONFIRMED_HIT', 'POTENTIAL_MATCH', 'LOW_MATCH', 'INCOMPLETE')


class SqlStore:
    """PostgreSQL store (tables from migration 20261117_p4_bulk_jobs.sql).

    commit=False keeps everything in the caller's transaction (tests inside
    BEGIN ... ROLLBACK)."""

    def __init__(self, conn, commit=True):
        self.conn, self._commit = conn, commit
        self.lock = threading.Lock()   # one connection, serialised (the worker's threads share it)

    def _c(self):
        from psycopg2.extras import RealDictCursor
        return self.conn.cursor(cursor_factory=RealDictCursor)

    def _done(self):
        if self._commit:
            self.conn.commit()

    def create_job(self, user_id, filename, headers, raw_rows):
        from psycopg2.extras import execute_values
        jid = str(uuid.uuid4())
        with self.lock:
            c = self._c()
            c.execute("""INSERT INTO screening_bulk_jobs (id, created_by, filename, headers, status, total_rows)
                         VALUES (%s, %s, %s, %s, 'MAPPING', %s)""",
                      (jid, user_id, (filename or '')[:250], json.dumps(headers, ensure_ascii=False), len(raw_rows)))
            execute_values(c, "INSERT INTO screening_bulk_rows (job_id, row_no, raw, status) VALUES %s",
                           [(jid, i + 1, json.dumps(r, ensure_ascii=False), 'NEW') for i, r in enumerate(raw_rows)],
                           page_size=1000)
            self._done()
        return jid

    def job(self, jid):
        with self.lock:
            c = self._c()
            c.execute("SELECT * FROM screening_bulk_jobs WHERE id = %s", (jid,))
            j = c.fetchone()
            self._done()
        if j:
            j = dict(j)
            for k in ('headers', 'column_map', 'summary'):
                if isinstance(j.get(k), str):
                    try:
                        j[k] = json.loads(j[k])
                    except Exception:
                        pass
        return j

    def raw_rows(self, jid):
        with self.lock:
            c = self._c()
            c.execute("SELECT row_no, raw FROM screening_bulk_rows WHERE job_id = %s ORDER BY row_no", (jid,))
            out = [(r['row_no'], r['raw'] if isinstance(r['raw'], dict) else json.loads(r['raw'] or '{}'))
                   for r in c.fetchall()]
            self._done()
        return out

    def save_mapping(self, jid, mapping, prepared, default_type):
        vals = []
        for row_no, (f, warnings, skip) in prepared.items():
            vals.append((row_no, f['name'][:500], f['entity_type'], f['dob'][:40], f['nationality'][:120],
                         f['national_id'][:120], f['customer_ref'][:120],
                         json.dumps(warnings, ensure_ascii=False, default=str),
                         'SKIPPED' if skip else 'PENDING', skip))
        with self.lock:
            c = self._c()
            # one UPDATE ... FROM (VALUES ...) per page of 1,000 rows
            for i in range(0, len(vals), 1000):
                page = vals[i:i + 1000]
                args = []
                ph = []
                for v in page:
                    ph.append('(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)')
                    args.extend(v)
                c.execute(f"""
                    UPDATE screening_bulk_rows r SET name = v.name, entity_type = v.et, dob = v.dob,
                           nationality = v.nat, national_id = v.nid, customer_ref = v.ref,
                           input_warnings = v.w::jsonb, status = v.st, error = v.err,
                           result_status = NULL, screening_result_id = NULL, attempts = 0
                    FROM (VALUES {','.join(ph)}) AS v(row_no, name, et, dob, nat, nid, ref, w, st, err)
                    WHERE r.job_id = %s AND r.row_no = v.row_no::int""", args + [jid])
            c.execute("""UPDATE screening_bulk_jobs SET column_map = %s, default_type = %s, status = 'READY'
                         WHERE id = %s""", (json.dumps(mapping, ensure_ascii=False), default_type, jid))
            self._done()

    def set_status(self, jid, status, **extra):
        cols = ['status = %s']
        args = [status]
        for k, v in extra.items():
            if k not in ('started_at', 'finished_at', 'error', 'summary', 'started_by', 'worker_pid'):
                continue
            cols.append(f'{k} = %s')
            args.append(json.dumps(v, ensure_ascii=False, default=str) if k == 'summary' else v)
        with self.lock:
            c = self._c()
            c.execute(f"UPDATE screening_bulk_jobs SET {', '.join(cols)} WHERE id = %s", args + [jid])
            self._done()

    def retry_failed(self, jid):
        """Resume of a finished-with-gap job: failed rows are screened again."""
        with self.lock:
            c = self._c()
            c.execute("UPDATE screening_bulk_rows SET status = 'PENDING', error = NULL "
                      "WHERE job_id = %s AND status = 'FAILED'", (jid,))
            n = c.rowcount
            self._done()
        return n

    def running_jobs(self, exclude=None):
        with self.lock:
            c = self._c()
            c.execute("SELECT id, status, heartbeat, started_at FROM screening_bulk_jobs "
                      "WHERE status = 'RUNNING' AND id <> %s", (exclude or '',))
            out = [dict(r) for r in c.fetchall()]
            self._done()
        return out

    def reset_stale(self, jid):
        with self.lock:
            c = self._c()
            c.execute("UPDATE screening_bulk_rows SET status = 'PENDING' WHERE job_id = %s AND status = 'RUNNING'",
                      (jid,))
            n = c.rowcount
            self._done()
        return n

    def claim(self, jid, n):
        with self.lock:
            c = self._c()
            c.execute("""
                UPDATE screening_bulk_rows SET status = 'RUNNING', attempts = attempts + 1
                WHERE job_id = %s AND row_no IN (
                    SELECT row_no FROM screening_bulk_rows WHERE job_id = %s AND status = 'PENDING'
                    ORDER BY row_no LIMIT %s FOR UPDATE SKIP LOCKED)
                RETURNING row_no, name, entity_type, dob, nationality, national_id, customer_ref, attempts""",
                      (jid, jid, n))
            out = [dict(r) for r in c.fetchall()]
            self._done()
        return out

    def finish_row(self, jid, row_no, status, **f):
        with self.lock:
            c = self._c()
            c.execute("""UPDATE screening_bulk_rows SET status = %s, result_status = %s, highest_score = %s,
                                match_count = %s, screening_result_id = %s, error = %s, finished_at = now()
                         WHERE job_id = %s AND row_no = %s""",
                      (status, f.get('result_status'), f.get('highest_score'), f.get('match_count'),
                       f.get('screening_result_id'), (f.get('error') or None) and str(f.get('error'))[:500],
                       jid, row_no))
            self._done()

    def heartbeat(self, jid):
        with self.lock:
            c = self._c()
            c.execute("UPDATE screening_bulk_jobs SET heartbeat = now() WHERE id = %s", (jid,))
            self._done()

    def counts(self, jid):
        with self.lock:
            c = self._c()
            c.execute("SELECT status, count(*) AS n FROM screening_bulk_rows WHERE job_id = %s GROUP BY 1", (jid,))
            st = {r['status']: r['n'] for r in c.fetchall()}
            c.execute("""SELECT result_status, count(*) AS n FROM screening_bulk_rows
                         WHERE job_id = %s AND status = 'DONE' GROUP BY 1""", (jid,))
            res = {r['result_status']: r['n'] for r in c.fetchall()}
            self._done()
        return st, res

    def rows_for_report(self, jid, flagged_only=True):
        where = ("AND (status = 'FAILED' OR result_status IN ('CONFIRMED_HIT','POTENTIAL_MATCH','LOW_MATCH','INCOMPLETE'))"
                 if flagged_only else '')
        with self.lock:
            c = self._c()
            c.execute(f"""SELECT row_no, name, entity_type, dob, nationality, national_id, customer_ref,
                                 input_warnings, status, result_status, highest_score, match_count,
                                 screening_result_id, error
                          FROM screening_bulk_rows WHERE job_id = %s {where} ORDER BY row_no""", (jid,))
            out = [dict(r) for r in c.fetchall()]
            self._done()
        return out


# --------------------------------------------------------------------------- steps
def prepare(store, jid, mapping, default_type='INDIVIDUAL'):
    """Apply the column mapping and the input check; returns the pre-run summary."""
    if not mapping.get('name'):
        raise ValueError('Choose the column that holds the name.')
    prepared, view = {}, []
    for row_no, raw in store.raw_rows(jid):
        f, warnings = normalise_row(raw, mapping, default_type)
        skip = None if f['name'] else 'empty name'
        prepared[row_no] = (f, warnings, skip)
        view.append({'row_no': row_no, 'warnings': warnings, 'skip': skip})
    store.save_mapping(jid, mapping, prepared, default_type)
    summary = summarise(view)
    store.set_status(jid, 'READY', summary=summary)
    return summary


def run(store, jid, screen_fn, save_fn, threads=4, batch=20, stop=None, progress=None):
    """Screen every PENDING row of the job. screen_fn(row) -> engine result;
    save_fn(row, result) -> screening_results id. Every row ends DONE or FAILED.
    Returns the final totals (and whether rows in == rows out)."""
    n_reset = store.reset_stale(jid)
    if n_reset:
        logger.info(f'[BULK] job {jid}: {n_reset} interrupted rows put back to PENDING')
    store.set_status(jid, 'RUNNING', started_at=datetime.now(), finished_at=None, error=None)
    t0 = time.time()
    done = [0]
    dlock = threading.Lock()

    def one(row):
        try:
            res = screen_fn(row)
            if not isinstance(res, dict):
                raise RuntimeError('no result returned by the screening engine')
            status = res.get('screening_result') or ('INCOMPLETE' if res.get('incomplete') else None)
            if res.get('incomplete') and status in ('CLEAR', 'LOW_MATCH', 'WHITE_LISTED', None):
                status = 'INCOMPLETE'
            if not status:
                raise RuntimeError('the screening engine returned no screening result for this row')
            rid = save_fn(row, res)
            store.finish_row(jid, row['row_no'], 'DONE', result_status=status,
                             highest_score=float(res.get('highest_score') or 0),
                             match_count=len(res.get('matches') or []), screening_result_id=rid)
        except Exception as e:
            logger.warning(f'[BULK] job {jid} row {row["row_no"]} failed: {e}')
            try:
                store.finish_row(jid, row['row_no'], 'FAILED', error=f'{type(e).__name__}: {e}')
            except Exception as e2:   # the row stays RUNNING -> PENDING on the next resume
                logger.error(f'[BULK] job {jid} row {row["row_no"]} could not be recorded: {e2}')
        with dlock:
            done[0] += 1

    from concurrent.futures import ThreadPoolExecutor
    cancelled = False
    with ThreadPoolExecutor(max_workers=max(1, int(threads))) as ex:
        while True:
            if stop is not None and stop():
                cancelled = True
                break
            rows = store.claim(jid, batch)
            if not rows:
                break
            list(ex.map(one, rows))
            store.heartbeat(jid)
            if progress:
                progress(done[0])
    st, res = store.counts(jid)
    j = store.job(jid) or {}
    total = int(j.get('total_rows') or sum(st.values()))
    accounted = st.get('DONE', 0) + st.get('FAILED', 0) + st.get('SKIPPED', 0)
    left = st.get('PENDING', 0) + st.get('RUNNING', 0) + st.get('NEW', 0)
    summary = dict(j.get('summary') or {})
    summary.update({'rows_in': total, 'rows_out': accounted, 'left': left, 'counts': st, 'results': res,
                    'seconds': round(time.time() - t0, 1)})
    # re-read: a cancel pressed during the last batch must not be overwritten by DONE / PAUSED
    if not cancelled and (store.job(jid) or {}).get('status') == 'CANCELLED':
        cancelled = True
    if cancelled:
        store.set_status(jid, 'CANCELLED', finished_at=datetime.now(), summary=summary)
    elif left:
        store.set_status(jid, 'PAUSED', summary=summary)
    else:
        summary['complete'] = (accounted == total)
        store.set_status(jid, 'DONE' if accounted == total else 'DONE_WITH_GAP', finished_at=datetime.now(),
                         summary=summary)
    return summary


def is_stale(job):
    hb = job.get('heartbeat') or job.get('started_at')
    if not hb:
        return True
    try:
        if isinstance(hb, str):
            hb = datetime.fromisoformat(hb)
        now = datetime.now(hb.tzinfo) if getattr(hb, 'tzinfo', None) else datetime.now()
        return (now - hb).total_seconds() > STALE_SECONDS
    except Exception:
        return True


def progress_of(store, jid):
    j = store.job(jid) or {}
    st, res = store.counts(jid)
    total = int(j.get('total_rows') or 0)
    finished = st.get('DONE', 0) + st.get('FAILED', 0) + st.get('SKIPPED', 0)
    return {'status': j.get('status'), 'total': total, 'finished': finished,
            'done': st.get('DONE', 0), 'failed': st.get('FAILED', 0), 'skipped': st.get('SKIPPED', 0),
            'pending': st.get('PENDING', 0) + st.get('RUNNING', 0),
            'results': res, 'percent': int(100 * finished / total) if total else 0,
            'stale': j.get('status') == 'RUNNING' and is_stale(j)}


def _xl(v):
    """Spreadsheet cell guard: a text cell must never be read as a formula (= + - @, tab, CR)."""
    if v is None or isinstance(v, (int, float)):
        return v
    s = str(v)
    return "'" + s if s[:1] in ('=', '+', '-', '@', '\t', '\r') else s


def export_xlsx(store, jid):
    """BytesIO with three sheets: summary, flagged rows, every row."""
    import io
    import pandas as pd
    j = store.job(jid) or {}
    p = progress_of(store, jid)
    allrows = store.rows_for_report(jid, flagged_only=False)

    def frame(rows):
        return pd.DataFrame([{k: _xl(v) for k, v in {
            'Row': r.get('row_no'), 'Name': r.get('name'), 'Type': r.get('entity_type'), 'DOB': r.get('dob'),
            'Nationality': r.get('nationality'), 'ID': r.get('national_id'), 'Customer ref': r.get('customer_ref'),
            'Row status': r.get('status'), 'Result': r.get('result_status'), 'Highest score': r.get('highest_score'),
            'Matches': r.get('match_count'), 'Screening result id': r.get('screening_result_id'),
            'Input warnings': '; '.join((w.get('en') or w.get('code') or '') if isinstance(w, dict) else str(w)
                                        for w in (r.get('input_warnings') or [])),
            'Error / reason': r.get('error')}.items()} for r in rows])
    summ = pd.DataFrame([
        ('File', j.get('filename')), ('Rows in file', p['total']), ('Screened', p['done']),
        ('Failed', p['failed']), ('Skipped (empty name)', p['skipped']), ('Not finished', p['pending']),
        ('Rows in = rows out', 'YES' if p['finished'] == p['total'] else 'NO')]
        + [(f'Result: {k}', v) for k, v in sorted((p['results'] or {}).items(), key=lambda x: str(x[0]))],
        columns=['Item', 'Value']).map(_xl)
    flagged = [r for r in allrows if r.get('status') == 'FAILED' or r.get('result_status') in FLAGGED]
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        summ.to_excel(w, index=False, sheet_name='Summary')
        frame(flagged).to_excel(w, index=False, sheet_name='Hits, incomplete, failed')
        frame(allrows).to_excel(w, index=False, sheet_name='All rows')
    out.seek(0)
    return out
