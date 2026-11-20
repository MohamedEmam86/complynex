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
Read-only crawl of every GET route as several kinds of user — the final general check before / after a deploy.

For each user it requests every GET route of app.url_map (URL ids filled with real sample ids read from the
database) and reports: HTTP 500s and exceptions, Jinja / Python tracebacks in the page, double-escaped text
('&amp;amp;'), broken labels ('& &', '&&' in visible text), and 'None' / 'Undefined' printed where a value
was missing.

SAFE ON PRODUCTION
  * Pages that call outside services on every view (news / adverse-media search) are skipped unless
    --external is given.
  * GET requests only, through the application in-process (no network, no server load beyond one worker),
    with a delay between requests (--delay, default 0.25 s).
  * Every request of the crawl runs on ONE database connection inside ONE transaction that is rolled back
    at the end: commit() is turned into a savepoint, so nothing a page might write (audit rows, "last seen"
    stamps) is kept, and temporary users never become visible to anybody else.

USERS
  --temp-users            create a superadmin, an administrator, a compliance officer, a portal employee and a
                          restricted customer (vessels + dual-use) inside that transaction (rolled back)
  --as ROLE=ID[,ROLE=ID]  use existing accounts instead (e.g. --as admin=1,portal=57)

    PYTHONPATH=. python scripts/route_crawl.py --temp-users [--only vessels.,dualuse.] [--json out.json]
Exit code 1 when anything was found.
"""

import argparse
import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# known legitimate text: the rating scales have a level literally called "None"
ALLOW = {('None printed', 'guides.ratings')}
SKIP = {'static', 'auth.logout', 'academy.logout', 'prometheus_metrics', 'health'}
# pages that call outside services (news search, adverse media) on every view: skipped unless --external
EXTERNAL = {'vessels.result_news', 'screening.api_adverse_media', 'screening.get_url_history'}
CHECKS = [
    ('traceback', re.compile(r'Traceback \(most recent call last\)|jinja2\.exceptions|UndefinedError|'
                             r'psycopg2\.errors')),
    ('double-escaped', re.compile(r'&amp;(amp|lt|gt|quot|#\d+);')),
    ('broken label', re.compile(r'(?<![&\w])& &|&&(?!\w)')),
    ('None printed', re.compile(r'>\s*(None|Undefined)\s*<|\bNone None\b')),
]
# English 'None' is also a real word (a rating level, "no manager"): only an artefact on an Arabic page
EN_OK = {'None printed'}


class _OneConnection:
    """Pool stand-in: every request gets the same connection; commit/rollback map to savepoints and the real
    transaction is rolled back by close_all()."""

    def __init__(self, raw):
        self.raw = raw
        self.raw.autocommit = False
        self.closed = False

    def getconn(self, *a, **kw):
        cur = self.raw.cursor()
        cur.execute('SAVEPOINT cx_crawl')
        cur.close()
        return _Proxy(self.raw)

    def putconn(self, *a, **kw):
        pass

    def closeall(self):
        self.raw.rollback()
        self.raw.close()


class _Proxy:
    def __init__(self, raw):
        self._raw = raw

    def commit(self):
        cur = self._raw.cursor()
        cur.execute('RELEASE SAVEPOINT cx_crawl; SAVEPOINT cx_crawl')
        cur.close()

    def rollback(self):
        cur = self._raw.cursor()
        try:
            cur.execute('ROLLBACK TO SAVEPOINT cx_crawl')
        except Exception:
            pass
        cur.close()

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _visible(html):
    html = re.sub(r'(?is)<(script|style)\b.*?</\1>', ' ', html)
    return html


_TABLES = {}


def _tables(db):
    if not _TABLES:
        for r in db.execute("""SELECT table_name FROM information_schema.columns
                               WHERE table_schema = 'public' AND column_name = 'id'
                                 AND data_type IN ('integer', 'bigint')""").fetchall():
            _TABLES[r['table_name']] = None
    return _TABLES


def _sample_id(db, endpoint, arg, path):
    """A real id for a URL argument: the table whose name best matches the argument / endpoint words."""
    words = [w for w in re.split(r'[^a-z]+', (arg[:-3] if arg.endswith('_id') else arg).lower()) if len(w) > 2]
    if not words or words == ['sid']:
        words = []
    fn = endpoint.split('.')[-1]
    words += [w for w in re.split(r'[_/\-]+', fn + '/' + path.lower()) if len(w) > 3 and not w.startswith('<')]
    bp = endpoint.split('.')[0] if '.' in endpoint else ''
    best, score = None, 0
    for t in _tables(db):
        s = 0
        for i, w in enumerate(words):
            stem = w.rstrip('s')
            if stem and stem in t:
                s += 3 if i == 0 else 1
        if bp and t.startswith(bp.rstrip('s')):
            s += 1
        if s > score:
            best, score = t, s
    if best:
        if _TABLES.get(best) is None:
            try:
                r = db.execute(f'SELECT max(id) AS i FROM "{best}"').fetchone()
                _TABLES[best] = r['i'] or 1
            except Exception:
                db.rollback()
                _TABLES[best] = 1
        return _TABLES[best]
    return 1


def _urls(app, db, only):
    adapter = app.url_map.bind('localhost')
    out, seen = [], set()
    for r in sorted(app.url_map.iter_rules(), key=lambda r: r.endpoint):
        if 'GET' not in r.methods or r.endpoint in seen or r.endpoint in SKIP:
            continue
        if r.endpoint in EXTERNAL and not _urls.external:
            continue
        if only and not r.endpoint.startswith(tuple(only)):
            continue
        vals = {}
        for a in r.arguments:
            conv = type(r._converters.get(a)).__name__
            vals[a] = _sample_id(db, r.endpoint, a, r.rule) if 'Integer' in conv else 'x'
        try:
            out.append((r.endpoint, adapter.build(r.endpoint, vals)))
            seen.add(r.endpoint)
        except Exception:
            continue
    return out


_urls.external = False


def _temp_users(db):
    """Five users inside the crawl transaction (rolled back at the end)."""
    from models.user import User
    from access import registry as R, service as S
    stamp = str(int(time.time()))
    spec = [('superadmin', 'superadmin', {}), ('admin', 'admin', {}),
            ('compliance_officer', 'compliance_officer', {p: 'edit' for p in (
                'perm_screening', 'perm_aml', 'perm_governance', 'perm_policies', 'perm_reports', 'perm_vessels')}),
            ('portal', 'employee', {}), ('restricted', 'employee', {})]
    ids = {}
    for key, role, perms in spec:
        u = User.create_user(f'crawl-{key}-{stamp}@example.invalid', 'Crawl!Passw0rd#' + stamp, 'Crawl', key,
                             role=role, **perms)
        db.execute('UPDATE users SET must_change_password = FALSE WHERE id = %s', (u.id,))
        ids[key] = u.id
    ext = User.get_by_id(ids['restricted'])
    keys = {k for k, f in R.FEATURES.items() if k.startswith(('vessels.', 'dualuse.'))}
    S.save(ext, 'restricted', keys, actor_id=ids['superadmin'], note='route crawl (rolled back)')
    return ids


def main():
    ap = argparse.ArgumentParser(description='read-only crawl of every GET route')
    ap.add_argument('--temp-users', action='store_true')
    ap.add_argument('--as', dest='as_', default='', help='ROLE=ID[,ROLE=ID] existing accounts')
    ap.add_argument('--only', default='', help='comma-separated endpoint prefixes')
    ap.add_argument('--delay', type=float, default=0.25)
    ap.add_argument('--lang', default='en,ar', help='interface languages to crawl (default both)')
    ap.add_argument('--json')
    ap.add_argument('--max-report', type=int, default=200)
    ap.add_argument('--external', action='store_true', help='also pages that call outside news / media services')
    a = ap.parse_args()
    _urls.external = a.external
    if not a.temp_users and not a.as_:
        ap.error('give --temp-users or --as ROLE=ID,...')
    logging.disable(logging.WARNING)

    from app import create_app
    import database.db as D
    from flask import got_request_exception
    app = create_app()
    app.testing = False
    app.config['PROPAGATE_EXCEPTIONS'] = False
    app.config['WTF_CSRF_ENABLED'] = False
    try:
        from extensions import limiter
        limiter.enabled = False
    except Exception:
        pass

    # one connection, one transaction, rolled back at the end
    import psycopg2
    from psycopg2.extras import RealDictCursor
    with app.app_context():
        D.init_pool(app)
    raw = psycopg2.connect(cursor_factory=RealDictCursor, **app.config['POSTGRES_CONFIG'])
    real_pool = D._connection_pool
    D._connection_pool = _OneConnection(raw)

    errors = {}

    def _on_exc(sender, exception, **extra):
        from flask import request
        errors[request.path] = f'{type(exception).__name__}: {str(exception)[:200]}'
    got_request_exception.connect(_on_exc, app)

    findings = []
    try:
        from models.user import User
        with app.app_context():
            db = D.get_db()
            ids = _temp_users(db) if a.temp_users else \
                {k: int(v) for k, v in (p.split('=') for p in a.as_.split(',') if '=' in p)}
            urls = _urls(app, db, [p for p in a.only.split(',') if p])
            sids = {k: User.get_by_id(v).get_id() for k, v in ids.items()}
        print(f'{len(urls)} GET routes x {len(sids)} users: {", ".join(sids)}')
        for (who, sid), lang in [(x, lg) for x in sids.items() for lg in a.lang.split(',')]:
            n = 0
            for ep, url in urls:
                c = app.test_client()
                with c.session_transaction() as s:
                    s['_user_id'] = sid
                    s['_fresh'] = True
                    s['lang'] = lang
                    s['dir'] = 'rtl' if lang == 'ar' else 'ltr'
                errors.pop(url.split('?')[0], None)
                try:
                    r = c.get(url, headers={'Accept': 'text/html'})
                    status, body = r.status_code, r.get_data(as_text=True) if r.mimetype == 'text/html' else ''
                except Exception as e:                       # never stop the crawl
                    status, body = 'EXC', f'{type(e).__name__}: {e}'
                problems = []
                if status == 500 or status == 'EXC':
                    problems.append(('server error', errors.get(url.split('?')[0]) or str(body)[:200]))
                if body:
                    vis = _visible(body)
                    for name, rx in CHECKS:
                        if lang == 'en' and name in EN_OK:
                            rx = re.compile(r'>\s*Undefined\s*<|\bNone None\b')
                        m = rx.search(vis if name != 'traceback' else body)
                        if m:
                            ctx = vis[max(0, m.start() - 60):m.end() + 60] if name != 'traceback' else m.group(0)
                            problems.append((name, re.sub(r'\s+', ' ', ctx)))
                for kind, detail in problems:
                    if (kind, ep) in ALLOW:
                        continue
                    findings.append({'user': f'{who}/{lang}', 'endpoint': ep, 'url': url, 'status': status, 'problem': kind,
                                     'detail': detail})
                n += 1
                time.sleep(a.delay)
            print(f'  {who} ({lang}): {n} pages')
    finally:
        D._connection_pool.closeall()          # roll back everything the crawl did
        D._connection_pool = real_pool
    by = {}
    for f in findings:
        by.setdefault(f['problem'], []).append(f)
    for kind, fs in sorted(by.items()):
        print(f'\n== {kind}: {len(fs)}')
        for f in fs[:a.max_report]:
            print(f"  [{f['user']}] {f['status']} {f['endpoint']} {f['url']}  {f['detail'][:220]}")
    print(f'\n{len(findings)} finding(s)')
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(findings, fh, indent=1, ensure_ascii=False)
    sys.exit(1 if findings else 0)


if __name__ == '__main__':
    main()
