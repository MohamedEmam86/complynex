#!/usr/bin/env python3
"""
Apply Arabic translations to the catalog, with the safety checks that the
earlier failures taught us:

  * %(name)s placeholders must match exactly between msgid and msgstr, or the
    page raises at render time (this produced 500s before).
  * A literal '%' must stay doubled ('%%'). Jinja's gettext wrapper always
    applies `result % variables`, so a single '%' either corrupts the output
    or raises ValueError.
  * The fuzzy flag must be cleared, otherwise pybabel excludes the entry from
    the compiled catalog and the string silently renders in English.

Anything failing a check is reported and left untouched rather than written.
"""
import importlib.util
import re
import sys

import polib

PO = '/var/www/complynex/translations/ar/LC_MESSAGES/messages.po'
PLACEHOLDER = re.compile(r'%\([a-zA-Z_][a-zA-Z0-9_]*\)[sdifr]')
# a single % that is not part of %% and not part of %(name)s
LONE_PCT = re.compile(r'(?<!%)%(?!%)(?!\([a-zA-Z_])')


def load(path):
    spec = importlib.util.spec_from_file_location('batch', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for attr in dir(m):
        if attr.startswith('T') and isinstance(getattr(m, attr), dict):
            return getattr(m, attr)
    raise SystemExit('no translation dict found in %s' % path)


def main():
    paths = [a for a in sys.argv[1:] if not a.startswith('-')]
    trans = {}
    for p in paths:
        d = load(p)
        trans.update(d)
        print('loaded %-28s %d entries' % (p.split('/')[-1], len(d)))
    print('total translations to apply: %d' % len(trans))

    po = polib.pofile(PO)
    by_id = {e.msgid: e for e in po}

    applied, missing, rejected = 0, [], []
    for msgid, msgstr in trans.items():
        e = by_id.get(msgid)
        if e is None:
            missing.append(msgid)
            continue
        # --- safety checks ------------------------------------------------
        a = sorted(PLACEHOLDER.findall(msgid))
        b = sorted(PLACEHOLDER.findall(msgstr))
        if a != b:
            rejected.append((msgid, 'placeholder mismatch %s vs %s' % (a, b)))
            continue
        src_lone = LONE_PCT.search(msgid.replace('%%', ''))
        dst_lone = LONE_PCT.search(msgstr.replace('%%', ''))
        if dst_lone and not src_lone:
            rejected.append((msgid, 'msgstr introduces a bare % '))
            continue
        if msgid.count('%%') != msgstr.count('%%'):
            rejected.append((msgid, 'literal %% count differs (%d vs %d)'
                             % (msgid.count('%%'), msgstr.count('%%'))))
            continue
        e.msgstr = msgstr
        if 'fuzzy' in e.flags:
            e.flags.remove('fuzzy')
        applied += 1

    po.save(PO)

    print('\napplied  : %d' % applied)
    print('not in catalog : %d' % len(missing))
    for m in missing[:10]:
        print('    %r' % m[:70])
    print('rejected by safety checks : %d' % len(rejected))
    for m, why in rejected[:15]:
        print('    %-60r %s' % (m[:60], why))

    total = len(po)
    done = len([e for e in po if e.msgstr and 'fuzzy' not in e.flags])
    fz = len([e for e in po if 'fuzzy' in e.flags])
    print('\ncatalog now: %d total / %d translated / %d fuzzy / %d untranslated'
          % (total, done, fz, total - done - fz))


if __name__ == '__main__':
    main()
