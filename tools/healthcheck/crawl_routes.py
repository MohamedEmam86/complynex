#!/usr/bin/env python3
"""
Full-app route crawler.

Enumerates EVERY registered Flask rule, resolves <int:id> style params using
REAL ids pulled from the database (falling back to 1), and issues a GET for
each in both English and Arabic, recording status + any traceback.

Output: JSON report to /tmp/route_report_user.json plus a human summary on stdout.
"""
import json
import re
import sys
import traceback

sys.path.insert(0, '/var/www/complynex')

from app import create_app  # noqa: E402
from database.db import get_db  # noqa: E402

app = create_app()

SKIP_ENDPOINT_PREFIXES = ('static', 'debugtoolbar')
# Destructive / side-effectful paths we must not GET-crawl
SKIP_PATTERNS = [
    r'/logout', r'/delete', r'/remove', r'/purge', r'/reset',
    r'/sync', r'/run-', r'/execute', r'/send', r'/approve', r'/reject',
    r'/export', r'/download', r'/backup', r'/restore', r'/seed',
]
SKIP_RE = re.compile('|'.join(SKIP_PATTERNS), re.I)

PARAM_RE = re.compile(r'<(?:(?P<conv>[a-zA-Z_]+)(?:\([^)]*\))?:)?(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>')


def sample_ids():
    """Pull one real primary-key id from every table so <int:x_id> params resolve."""
    ids = {}
    with app.app_context():
        db = get_db()
        try:
            cur = db.execute("""SELECT table_name FROM information_schema.tables
                                WHERE table_schema='public'""")
            tables = [r[0] for r in cur.fetchall()]
        except Exception:
            cur = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]

        for tname in tables:
            try:
                cur = db.execute('SELECT id FROM "%s" ORDER BY id LIMIT 1' % tname)
                row = cur.fetchone()
                if row:
                    ids[tname] = row[0]
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
    return ids


def guess_value(param_name, conv, ids):
    """Best-effort real id for a URL param."""
    pname = param_name.lower()
    if conv in (None, 'int', 'float'):
        # try to match <thing_id> -> table 'things' / 'thing'
        base = pname[:-3] if pname.endswith('_id') else pname
        for cand in (base + 's', base, base + 'es'):
            if cand in ids:
                return ids[cand]
        # try fuzzy: any table containing the base word
        for tname, tid in ids.items():
            if base and base in tname:
                return tid
        return 1
    if conv == 'path':
        return 'x'
    return 'test'


def build_urls(ids):
    urls = []
    for rule in app.url_map.iter_rules():
        if any(rule.endpoint.startswith(p) for p in SKIP_ENDPOINT_PREFIXES):
            continue
        if 'GET' not in (rule.methods or set()):
            continue
        path = str(rule)
        if SKIP_RE.search(path):
            continue

        def sub(m):
            return str(guess_value(m.group('name'), m.group('conv'), ids))

        concrete = PARAM_RE.sub(sub, path)
        urls.append((rule.endpoint, path, concrete))
    return sorted(set(urls), key=lambda x: x[2])


def main():
    ids = sample_ids()
    urls = build_urls(ids)
    print('Discovered %d crawlable GET routes' % len(urls), flush=True)

    results = []
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['_user_id'] = __import__('models.user', fromlist=['User']).User.session_id_for_app(app, 1)
            s['_fresh'] = True

        for endpoint, pattern, url in urls:
            for lang in ('en', 'ar'):
                target = url + ('?lang=ar' if lang == 'ar' else '')
                rec = {'endpoint': endpoint, 'pattern': pattern,
                       'url': url, 'lang': lang}
                try:
                    r = c.get(target, follow_redirects=False)
                    rec['status'] = r.status_code
                    if r.status_code >= 500:
                        body = r.get_data(as_text=True)
                        rec['body_tail'] = body[-3000:]
                except Exception:
                    rec['status'] = 'EXC'
                    rec['body_tail'] = traceback.format_exc()[-3000:]
                results.append(rec)

    with open('/tmp/route_report_user.json', 'w') as f:
        json.dump(results, f, indent=1)

    bad = [r for r in results if r['status'] == 'EXC' or (
        isinstance(r['status'], int) and r['status'] >= 400 and r['status'] != 401)]
    print('\n=== NON-OK (%d of %d checks) ===' % (len(bad), len(results)))
    for r in bad:
        print('%s  %s  [%s]  %s' % (r['status'], r['url'], r['lang'], r['endpoint']))


if __name__ == '__main__':
    main()
