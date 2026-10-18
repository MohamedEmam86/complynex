#!/usr/bin/env python3
"""
Static check that every url_for() endpoint referenced in Python or templates
actually exists.

This class of bug has now bitten twice: admin.permissions / admin.security were
invented in the sidebar work, and risk_management.risk_register was invented in
today's 500 fix. It only shows up when someone happens to load the page, which
is exactly the kind of thing that reaches a user first.
"""
import os, re, sys
sys.path.insert(0, '/var/www/complynex')
from app import app

ROOT = '/var/www/complynex'
SKIP = ('/venv', '/node_modules', '/.git', '__pycache__', '/backups', '/tools/healthcheck')
PAT = re.compile(r"""url_for\(\s*['"]([a-zA-Z0-9_.]+)['"]""")

with app.app_context():
    known = {r.endpoint for r in app.url_map.iter_rules()}

bad = []
for dirpath, dirs, files in os.walk(ROOT):
    if any(x in dirpath for x in SKIP):
        continue
    for fn in files:
        if not (fn.endswith('.py') or fn.endswith('.html')) or '.bak' in fn:
            continue
        p = os.path.join(dirpath, fn)
        try:
            src = open(p, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        for m in PAT.finditer(src):
            ep = m.group(1)
            if ep not in known:
                bad.append((p.replace(ROOT + '/', ''),
                            src[:m.start()].count('\n') + 1, ep))

if bad:
    print(f'ENDPOINT GUARD: {len(bad)} reference(s) to endpoints that do not exist\n')
    for f, ln, ep in bad:
        print(f'  {f}:{ln}  ->  {ep}')
    sys.exit(1)
print(f'ENDPOINT GUARD: clean — all url_for() targets resolve ({len(known)} endpoints)')
