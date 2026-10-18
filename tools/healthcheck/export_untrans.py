#!/usr/bin/env python3
"""Export every string still needing Arabic, grouped so translation can be
done in coherent batches. Fuzzy entries are included: pybabel excludes them
from the compiled catalog, so a fuzzy string renders in English."""
import json
import re
from collections import Counter

import polib

PO = '/var/www/complynex/translations/ar/LC_MESSAGES/messages.po'
po = polib.pofile(PO)

total = len(po)
translated = [e for e in po if e.msgstr and 'fuzzy' not in e.flags]
fuzzy = [e for e in po if 'fuzzy' in e.flags]
untrans = [e for e in po if not e.msgstr and 'fuzzy' not in e.flags]

print('catalog     : %d' % total)
print('translated  : %d' % len(translated))
print('fuzzy       : %d  (render in English until reviewed)' % len(fuzzy))
print('untranslated: %d' % len(untrans))
print('TO DO       : %d' % (len(fuzzy) + len(untrans)))

need = fuzzy + untrans

# where do they come from?
mod = Counter()
for e in need:
    src = e.occurrences[0][0] if e.occurrences else '?'
    parts = src.replace('\\', '/').split('/')
    if parts[0] == 'templates' and len(parts) > 1:
        mod[parts[1]] += 1
    else:
        mod[parts[0]] += 1
print('\nby module:')
for m, c in mod.most_common(30):
    print('   %-28s %d' % (m, c))

# length profile - short strings dominate and are quick to do
buckets = Counter()
for e in need:
    n = len(e.msgid)
    buckets['1-20' if n <= 20 else '21-60' if n <= 60 else
            '61-150' if n <= 150 else '150+'] += 1
print('\nby length:', dict(buckets))

out = []
for e in need:
    out.append({
        'msgid': e.msgid,
        'fuzzy': 'fuzzy' in e.flags,
        'current': e.msgstr,
        'src': e.occurrences[0][0] if e.occurrences else '',
        'placeholders': re.findall(r'%\([a-zA-Z_]+\)[sdfr]|%[sd]', e.msgid),
    })
with open('/tmp/need_translation.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False)
print('\nwritten /tmp/need_translation.json (%d entries)' % len(out))
