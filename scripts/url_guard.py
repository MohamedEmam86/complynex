#!/usr/bin/env python3
"""Guard: url_for(...) placeholders replaced with an END-anchored regex.

Broken whenever the id is not the last path segment — which is invisible until
someone presses the button and it silently acts on the wrong record.
"""
import os, re, sys
ROOT = '/var/www/complynex'
SKIP = ('/venv', '/node_modules', '/.git', '__pycache__', '/backups', '/tools/')
PAT = re.compile(r'url_for\([^)]*=\s*0\s*\)[^\n]*replace\(\s*/\s*0\s*\$\s*/')
bad = []
for dp, dirs, files in os.walk(ROOT):
    if any(x in dp for x in SKIP):
        continue
    for fn in files:
        if not fn.endswith(('.html', '.py')) or '.bak' in fn:
            continue
        p = os.path.join(dp, fn)
        src = open(p, encoding='utf-8', errors='replace').read()
        for m in PAT.finditer(src):
            bad.append((p.replace(ROOT + '/', ''), src[:m.start()].count('\n') + 1))
if bad:
    print(f'URL GUARD: {len(bad)} end-anchored id placeholder(s)\n')
    for f, ln in bad:
        print(f'  {f}:{ln}')
    sys.exit(1)
print('URL GUARD: clean — no end-anchored url_for id placeholders')
