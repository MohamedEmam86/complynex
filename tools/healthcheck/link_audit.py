#!/usr/bin/env python3
"""
Template link auditor.

Two classes of bug this finds:

 1. HARDCODED hrefs (href="/governance/committee") that do not match ANY
    registered Flask rule -> guaranteed 404 for the user.
 2. url_for('endpoint') references to endpoints that DO NOT EXIST -> these
    raise BuildError at render time = guaranteed 500 on the whole page.

(2) is the more dangerous class: one bad url_for in a template 500s the entire
page even though every other link on it is fine.
"""
import os
import re
import sys

sys.path.insert(0, '/var/www/complynex')
from app import create_app  # noqa: E402
from werkzeug.routing import Map  # noqa: E402

app = create_app()
TPL_ROOT = '/var/www/complynex/templates'

HREF_RE = re.compile(r'(?:href|action)="(/[^"{}\s]*)"')
URLFOR_RE = re.compile(r"url_for\(\s*['\"]([a-zA-Z0-9_.]+)['\"]")


def registered_endpoints():
    return {r.endpoint for r in app.url_map.iter_rules()}


def match_path(path):
    """True if `path` matches some registered rule (any method)."""
    adapter = app.url_map.bind('localhost')
    clean = path.split('?')[0].split('#')[0]
    if not clean:
        return True
    try:
        adapter.match(clean, method='GET')
        return True
    except Exception as e:
        # 405 = path exists but wrong method -> still a real path
        if e.__class__.__name__ == 'MethodNotAllowed':
            return True
        # try with trailing slash variant
        try:
            adapter.match(clean.rstrip('/') + '/', method='GET')
            return True
        except Exception:
            return False


def main():
    eps = registered_endpoints()
    bad_urlfor = []
    bad_href = []

    for dirpath, _dirs, files in os.walk(TPL_ROOT):
        for fn in files:
            if not fn.endswith('.html'):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, TPL_ROOT)
            try:
                with open(full, encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                continue

            for m in URLFOR_RE.finditer(content):
                ep = m.group(1)
                if ep not in eps:
                    line = content[:m.start()].count('\n') + 1
                    bad_urlfor.append((rel, line, ep))

            for m in HREF_RE.finditer(content):
                path = m.group(1)
                if path.startswith(('/static/', '//', '/uploads/')):
                    continue
                if not match_path(path):
                    line = content[:m.start()].count('\n') + 1
                    bad_href.append((rel, line, path))

    print('=' * 70)
    print('BROKEN url_for() -> ENDPOINT DOES NOT EXIST  (causes HTTP 500)')
    print('=' * 70)
    for rel, line, ep in sorted(bad_urlfor):
        print('%-55s :%-5s %s' % (rel, line, ep))
    print('TOTAL: %d' % len(bad_urlfor))

    print()
    print('=' * 70)
    print('HARDCODED href/action -> NO MATCHING ROUTE  (causes HTTP 404)')
    print('=' * 70)
    for rel, line, path in sorted(bad_href):
        print('%-55s :%-5s %s' % (rel, line, path))
    print('TOTAL: %d' % len(bad_href))


if __name__ == '__main__':
    main()
