#!/usr/bin/env python3
"""
Deep template validator. Parses EVERY template with the real Jinja AST (not
regex) and reports four classes of latent crash:

 1. %-FORMAT BUGS  - Jinja's gettext wrapper ALWAYS does `result % variables`,
    even with no variables. Any literal '%' not part of a %(name)s placeholder
    raises ValueError or silently corrupts text at render time. We prove this
    by actually running `msgid % {}`.

 2. GETTEXT SHADOWING - `{% set _ = ... %}` / `{% for _ in ... %}` rebinds the
    translation function to a non-callable, so every later {{ _('...') }} in
    that template raises "'NoneType' object is not callable".

 3. BAD url_for ENDPOINTS - url_for('does.not.exist') raises BuildError => 500.

 4. SYNTAX ERRORS - template won't parse at all.
"""
import os
import sys

sys.path.insert(0, '/var/www/complynex')
from app import create_app  # noqa: E402
from jinja2 import nodes  # noqa: E402

app = create_app()
TPL_ROOT = '/var/www/complynex/templates'

GETTEXT_FUNCS = {'_', 'gettext', 'ngettext'}


def walk_templates():
    for dirpath, _dirs, files in os.walk(TPL_ROOT):
        for fn in sorted(files):
            if fn.endswith('.html'):
                yield os.path.join(dirpath, fn)


def check(path, env, endpoints):
    rel = os.path.relpath(path, TPL_ROOT)
    problems = []
    try:
        with open(path, encoding='utf-8') as f:
            src = f.read()
    except Exception as e:
        return [(rel, 0, 'READ', str(e))]

    try:
        ast = env.parse(src)
    except Exception as e:
        return [(rel, getattr(e, 'lineno', 0), 'SYNTAX', str(e))]

    # --- 2. gettext shadowing -------------------------------------------
    for node in ast.find_all(nodes.Assign):
        tgt = node.target
        if isinstance(tgt, nodes.Name) and tgt.name in GETTEXT_FUNCS:
            problems.append((rel, node.lineno, 'SHADOW',
                             "{%% set %s = ... %%} rebinds the translation "
                             "function; all later _() calls crash" % tgt.name))
    for node in ast.find_all(nodes.For):
        tgt = node.target
        names = []
        if isinstance(tgt, nodes.Name):
            names = [tgt.name]
        elif isinstance(tgt, nodes.Tuple):
            names = [n.name for n in tgt.items if isinstance(n, nodes.Name)]
        for n in names:
            if n in GETTEXT_FUNCS:
                problems.append((rel, node.lineno, 'SHADOW',
                                 "{%% for %s ... %%} rebinds the translation "
                                 "function" % n))

    # --- 1 & 3. inspect every call --------------------------------------
    for node in ast.find_all(nodes.Call):
        fn = node.node
        fname = getattr(fn, 'name', None)

        if fname in GETTEXT_FUNCS and node.args:
            arg = node.args[0]
            if isinstance(arg, nodes.Const) and isinstance(arg.value, str):
                msgid = arg.value
                kwargs = {k.key: 'x' for k in (node.kwargs or [])}
                try:
                    # Reproduce exactly what jinja2.ext._make_new_gettext does
                    msgid % kwargs
                except Exception as e:
                    problems.append((rel, node.lineno, 'PERCENT',
                                     '%r -> %s: %s' % (msgid[:70],
                                                       type(e).__name__, e)))
                else:
                    # silent corruption: % consumed but output changed
                    if not kwargs and (msgid % {}) != msgid:
                        problems.append((rel, node.lineno, 'PERCENT-SILENT',
                                         '%r renders as %r' %
                                         (msgid[:60], (msgid % {})[:60])))

        if fname == 'url_for' and node.args:
            a0 = node.args[0]
            if isinstance(a0, nodes.Const) and isinstance(a0.value, str):
                if a0.value not in endpoints:
                    problems.append((rel, node.lineno, 'BAD-ENDPOINT',
                                     "url_for('%s') - endpoint does not exist"
                                     % a0.value))
    return problems


def main():
    env = app.jinja_env
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}

    all_problems = []
    count = 0
    for path in walk_templates():
        count += 1
        all_problems.extend(check(path, env, endpoints))

    print('Scanned %d templates' % count)
    by_kind = {}
    for p in all_problems:
        by_kind.setdefault(p[2], []).append(p)

    for kind in ('SYNTAX', 'SHADOW', 'PERCENT', 'PERCENT-SILENT',
                 'BAD-ENDPOINT', 'READ'):
        items = by_kind.get(kind, [])
        print('\n' + '=' * 72)
        print('%s  (%d)' % (kind, len(items)))
        print('=' * 72)
        for rel, line, _k, msg in items:
            print('%-50s :%-5s %s' % (rel, line, msg))

    print('\nTOTAL PROBLEMS: %d' % len(all_problems))


if __name__ == '__main__':
    main()
