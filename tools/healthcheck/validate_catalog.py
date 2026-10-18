#!/usr/bin/env python3
"""
Pre-compile catalog safety check — the exact failure modes that caused 500s
earlier in this project:

  1. %(name)s placeholders must match between msgid and msgstr. A mismatch
     raises KeyError at render time and takes the whole page down.
  2. A literal '%' must be doubled. Jinja's gettext wrapper always applies
     `result % variables`, so a lone '%' either corrupts output or raises
     ValueError: unsupported format character.
  3. Every msgstr must actually survive that format operation. This runs it
     for real rather than reasoning about it.

Anything unsafe is quarantined (flagged fuzzy) so pybabel leaves it out of the
compiled catalog and the string falls back to English — degraded, never broken.
"""
import re
import sys

import polib

PO = '/var/www/complynex/translations/ar/LC_MESSAGES/messages.po'
PLACEHOLDER = re.compile(r'%\([a-zA-Z_][a-zA-Z0-9_]*\)[sdifr]')

po = polib.pofile(PO)
bad_ph, bad_fmt = [], []

for e in po:
    # polib iteration includes obsolete (#~) entries. They are never compiled
    # into the .mo, so a stale single-%% msgid left over from before the
    # templates were fixed must not be reported as a live problem.
    if getattr(e, 'obsolete', False):
        continue
    if not e.msgstr:
        continue
    a = sorted(PLACEHOLDER.findall(e.msgid))
    b = sorted(PLACEHOLDER.findall(e.msgstr))
    if a != b:
        bad_ph.append((e.msgid[:60], a, b))
        e.flags.append('fuzzy')
        continue
    # Reproduce jinja2.ext._make_new_gettext: rv % variables, always.
    # NOTE: parse the placeholder NAME with a capture group. Using
    # str.strip('%()sdifr') mangles it -- strip() removes ANY of those
    # characters from both ends, so '%(error)s' became 'erro' (trailing
    # 'r' is in the set) and every entry looked broken. Also supply a value
    # whose type matches the conversion: %d with a str raises TypeError.
    kwargs = {}
    for m in PLACEHOLDER.finditer(e.msgid):
        name = m.group(0)[2:m.group(0).rindex(')') - len(m.group(0))]
        name = re.match(r'%\(([a-zA-Z_][a-zA-Z0-9_]*)\)', m.group(0)).group(1)
        conv = m.group(0)[-1]
        kwargs[name] = 1 if conv in 'di' else (1.0 if conv == 'f' else 'x')
    try:
        e.msgstr % kwargs
    except Exception as exc:
        bad_fmt.append((e.msgid[:60], e.msgstr[:60],
                        '%s: %s' % (type(exc).__name__, exc)))
        e.flags.append('fuzzy')

if bad_ph or bad_fmt:
    po.save(PO)

print('entries checked            : %d' % len(po))
print('placeholder mismatches     : %d' % len(bad_ph))
for m, a, b in bad_ph[:20]:
    print('   %-58r msgid=%s msgstr=%s' % (m, a, b))
print('format-operation failures  : %d' % len(bad_fmt))
for m, s, why in bad_fmt[:20]:
    print('   %-40r -> %-40r %s' % (m, s, why))

if bad_ph or bad_fmt:
    print('\nUnsafe entries were flagged fuzzy and will be EXCLUDED from the')
    print('compiled catalog, so they fall back to English instead of erroring.')
else:
    print('\nAll clear — safe to compile.')
sys.exit(0)
