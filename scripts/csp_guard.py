#!/usr/bin/env python3
"""
Regression guard for the defect class that made API Keys inert.

Two things the CSP refuses and which fail SILENTLY in the browser — no server
error, no log line, just a dead page:

  1. <script> with no nonce         (script-src has no 'unsafe-inline')
  2. on* handler attributes         (a nonce does not re-enable these)

Run this after any template change. Exit code 1 means a page is about to ship
broken.
"""
import os, re, sys

ROOT = 'templates'
SCRIPT_NO_NONCE = re.compile(r'<script(?![^>]*\bnonce=)(?![^>]*\bsrc=)[^>]*>')
INLINE_HANDLER  = re.compile(r'\son(click|submit|change|input|load|error|'
                             r'focus|blur|keyup|keydown|mouseover)\s*=\s*["\']')

fails = []
for dirpath, _, files in os.walk(ROOT):
    for fn in files:
        if not fn.endswith('.html') or '.bak' in fn:
            continue
        p = os.path.join(dirpath, fn)
        src = open(p, encoding='utf-8', errors='replace').read()
        for m in SCRIPT_NO_NONCE.finditer(src):
            fails.append((p, src[:m.start()].count('\n') + 1,
                          'inline <script> without nonce'))
        for m in INLINE_HANDLER.finditer(src):
            fails.append((p, src[:m.start()].count('\n') + 1,
                          'inline handler ' + m.group(0).strip()))

if fails:
    print(f'CSP GUARD: {len(fails)} violation(s)\n')
    for p, ln, why in fails:
        print(f'  {p}:{ln}  {why}')
    sys.exit(1)
print('CSP GUARD: clean — no nonce-less inline scripts, no inline handlers')
