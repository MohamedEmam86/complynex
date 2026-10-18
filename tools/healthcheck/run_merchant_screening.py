#!/usr/bin/env python3
"""
Full merchant screening run — background job.

Screens every unique merchant name (name only, per instruction) through the
live ComplyNex engine and records every match scoring >=85%.

Design notes:
  * RESUMABLE. Results are appended as JSON lines and already-screened names
    are skipped on restart, so a disconnect or reboot does not lose 20 hours.
  * NOT PERSISTED to screening_results / the review queue. This is an offline
    assessment producing a report; writing 102k screening records and their
    queue items would flood production data. Say the word and I can switch it
    to persist instead.
  * include_media=False — adverse media is a per-name web scrape taking 25-40s
    and is not part of a name-match assessment.
  * Junk names (pure digits, phone numbers, single characters) are skipped and
    listed separately, as agreed.
  * Each match also carries an INDEPENDENT ordered-similarity score, computed
    outside the engine, so every flag can be sanity-checked without re-running
    anything.
"""
import difflib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/var/www/complynex')
os.chdir('/var/www/complynex')
from dotenv import load_dotenv
load_dotenv('/var/www/complynex/.env')

from app import create_app

OUT = '/var/www/complynex/backups/merchant_screening_results.jsonl'
PROGRESS = '/var/www/complynex/backups/merchant_screening_progress.json'
THRESHOLD = 85.0
WORKERS = int(os.environ.get('SCREEN_WORKERS', '8'))

# Names per process before a clean exit. Each worker thread holds its own
# engine, with its own FAISS index and models, so a long-lived process drifts
# towards the memory ceiling — at 12 workers it reached 9.6 GB on an 11 GB
# machine and the kernel killed it at 1,625 names.
#
# Exiting on a chunk boundary and letting systemd restart costs about 40
# seconds of model loading, and makes the ceiling unreachable. The run is
# resumable, so a restart picks up exactly where it stopped.
CHUNK = int(os.environ.get('SCREEN_CHUNK', '1000'))

app = create_app()

JUNK = re.compile(r'^[\d\W_]+$')          # digits/punctuation only

# System placeholders, not names. These return zero ES candidates, which fires
# the PostgreSQL fallback (a full seq scan) — so they cost far more than they
# are worth and can never produce a match.
PLACEHOLDER = re.compile(r'^(agent|merchant|test|customer|dummy)[\s_]*name',
                         re.I)

UNSCREENABLE = '/var/www/complynex/backups/merchant_unscreenable.json'


def is_placeholder(name):
    return bool(PLACEHOLDER.match(str(name).strip()))


def is_mojibake(name):
    # Arabic lost to '?' at export time — unrecoverable from this file.
    return str(name).count('?') >= 3


def is_junk(name):
    n = str(name).strip()
    if len(n) < 3:
        return True
    if JUNK.match(n):
        return True
    # a "name" that is mostly digits (phone numbers pasted into the field)
    digits = sum(c.isdigit() for c in n)
    return digits >= max(4, len(n.replace(' ', '')) * 0.5)


def ordered_sim(a, b):
    return round(difflib.SequenceMatcher(None, str(a), str(b)).ratio() * 100, 1)


def main():
    with open('/tmp/merchant_unique.json', encoding='utf-8') as f:
        names = json.load(f)

    placeholder, mojibake, junk, todo_all = [], [], [], []
    for n in names:
        if is_placeholder(n):
            placeholder.append(n)
        elif is_mojibake(n):
            mojibake.append(n)
        elif is_junk(n):
            junk.append(n)
        else:
            todo_all.append(n)

    with open('/var/www/complynex/backups/merchant_junk_names.json', 'w',
              encoding='utf-8') as f:
        json.dump(junk, f, ensure_ascii=False)

    # Reported, not silently dropped: each of these is a merchant record whose
    # name field cannot be screened, which is itself a compliance finding.
    with open(UNSCREENABLE, 'w', encoding='utf-8') as f:
        json.dump({
            'placeholder_names': placeholder,
            'mojibake_names': mojibake,
            'numeric_or_junk': junk,
            'note': ('placeholder = system-generated stub in the name field; '
                     'mojibake = Arabic lost to "?" during export, needs a '
                     'UTF-8 re-extract from the source system'),
        }, f, ensure_ascii=False, indent=1)

    print('placeholder excluded: %d' % len(placeholder), flush=True)
    print('mojibake excluded   : %d' % len(mojibake), flush=True)

    done = set()
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            for line in f:
                try:
                    done.add(json.loads(line)['name'])
                except Exception:
                    pass

    todo = [n for n in todo_all if n not in done]
    total_remaining = len(todo)
    if CHUNK > 0:
        todo = todo[:CHUNK]
    print('unique names        : %d' % len(names), flush=True)
    print('junk excluded       : %d' % len(junk), flush=True)
    print('to screen           : %d' % len(todo_all), flush=True)
    print('already done        : %d' % len(done), flush=True)
    print('remaining overall   : %d' % total_remaining, flush=True)
    print('this chunk          : %d' % len(todo), flush=True)
    print('workers             : %d' % WORKERS, flush=True)

    lock = threading.Lock()
    counter = {'n': len(done), 'hits': 0, 'err': 0}
    t0 = time.time()
    fh = open(OUT, 'a', encoding='utf-8')

    # ONE APP CONTEXT PER THREAD — not one for the whole run, and not one per
    # name.
    #
    # get_db() caches the connection on Flask's `g`, which is scoped to the app
    # context. Sharing a single context across worker threads therefore shares a
    # single database connection and serialises every query: that took this job
    # from 0.99 names/sec to 0.05. Creating a context per NAME works correctly
    # but pays the setup cost 102,000 times.
    #
    # A thread-local context is pushed once per worker and reused, so each
    # thread holds its own pooled connection (12 threads against a pool max of
    # 20) with no per-name overhead.
    from screening.routes import get_engine as _ge
    _local = threading.local()

    def _thread_engine():
        eng = getattr(_local, 'engine', None)
        if eng is None:
            ctx = app.app_context()
            ctx.push()
            _local.ctx = ctx
            eng = _ge()
            _local.engine = eng
        return eng

    def work(name):
        if True:
            eng = _thread_engine()
            try:
                res = eng.screen_person(name=name, entity_type='INDIVIDUAL',
                                        include_media=False)
                ms = res.get('matches') or []
                hi = []
                seen = set()
                for m in ms:
                    sc = m.get('match_score', 0) or 0
                    if sc < THRESHOLD:
                        continue
                    cand = (m.get('original_name') or m.get('full_name') or '')
                    key = (cand, m.get('source'), m.get('list_type'))
                    if key in seen:          # collapse duplicate candidate rows
                        continue
                    seen.add(key)
                    hi.append({
                        'matched_name': cand,
                        'score': round(float(sc), 1),
                        'independent_similarity': ordered_sim(name, cand),
                        'source': m.get('source'),
                        'list_type': m.get('list_type'),
                        'category': m.get('category'),
                        'entity_type': m.get('entity_type'),
                        'nationality': m.get('nationality'),
                        'dob': m.get('date_of_birth'),
                        'source_url': m.get('source_url'),
                        'ml_score': m.get('ml_score'),
                    })
                rec = {'name': name, 'total_matches': len(ms),
                       'hits': sorted(hi, key=lambda x: -x['score'])}
            except Exception as e:
                rec = {'name': name, 'error': str(e)[:200], 'hits': []}
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
            counter['n'] += 1
            if rec.get('hits'):
                counter['hits'] += 1
            if rec.get('error'):
                counter['err'] += 1
            if counter['n'] % 25 == 0:
                fh.flush()
                el = time.time() - t0
                rate = (counter['n'] - len(done)) / max(el, 1)
                left = (len(todo_all) - counter['n']) / max(rate, 0.001) / 3600
                json.dump({'done': counter['n'], 'total': len(todo_all),
                           'with_hits': counter['hits'],
                           'errors': counter['err'],
                           'rate_per_sec': round(rate, 2),
                           'hours_remaining': round(left, 1),
                           'updated': time.strftime('%Y-%m-%d %H:%M:%S')},
                          open(PROGRESS, 'w'))
                print('  %d/%d  %.2f/s  ~%.1fh left  hits=%d err=%d'
                      % (counter['n'], len(todo_all), rate, left,
                         counter['hits'], counter['err']), flush=True)

    print('starting (one app context per worker thread)', flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, todo))

    fh.flush()
    fh.close()
    json.dump({'done': counter['n'], 'total': len(todo_all),
               'with_hits': counter['hits'], 'errors': counter['err'],
               'status': 'COMPLETE',
               'updated': time.strftime('%Y-%m-%d %H:%M:%S')},
              open(PROGRESS, 'w'))
    remaining_after = total_remaining - len(todo)
    print('CHUNK DONE  screened=%d  with_hits=%d  errors=%d  in %.1f min  '
          'remaining=%d'
          % (counter['n'], counter['hits'], counter['err'],
             (time.time() - t0) / 60, remaining_after), flush=True)

    # Tell systemd whether to come back. Exit 0 with names left means "restart
    # me"; the unit uses Restart=always, and exit 64 marks a genuine finish so
    # it stops cleanly instead of looping.
    if remaining_after <= 0:
        print('ALL NAMES SCREENED', flush=True)
        raise SystemExit(64)


if __name__ == '__main__':
    main()
