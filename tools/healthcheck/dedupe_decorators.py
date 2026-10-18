#!/usr/bin/env python3
"""
Find (and optionally remove) EXACT duplicate @permission_required decorators.

Applying the same permission check twice to one view is harmless for security
but makes every request to that route run the permission lookup twice. On the
hot routes (screening queue, AML customer list) that is pure waste.

IMPORTANT: only decorators that are semantically IDENTICAL are removed.
`@permission_required('screening', 'view')` and
`@permission_required('screening', level='view')` are the same call written two
ways, so they count as identical. Two checks against DIFFERENT modules or
levels are intentional (the user must satisfy both) and are left alone.

Usage: dedupe_decorators.py [--apply]
"""
import ast
import os
import sys

APP = '/var/www/complynex'
SKIP = {'venv', '__pycache__', '.git', 'node_modules', 'backups'}
POSITIONAL_NAMES = ['module', 'level']   # permission_required(module, level)


def norm(dec):
    """Normalise a decorator call to (name, module, level) ignoring whether
    the args were passed positionally or by keyword."""
    if not isinstance(dec, ast.Call):
        return None
    fn = dec.func
    name = getattr(fn, 'id', getattr(fn, 'attr', None))
    if name != 'permission_required':
        return None
    vals = {'module': None, 'level': 'view'}
    for i, a in enumerate(dec.args):
        if i < len(POSITIONAL_NAMES) and isinstance(a, ast.Constant):
            vals[POSITIONAL_NAMES[i]] = a.value
    for kw in dec.keywords:
        if isinstance(kw.value, ast.Constant):
            vals[kw.arg] = kw.value.value
    return (name, vals['module'], vals['level'])


def main():
    apply_changes = '--apply' in sys.argv
    total_removed = 0
    report = []

    for root, dirs, files in os.walk(APP):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for fn in files:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, encoding='utf-8') as f:
                    src = f.read()
                tree = ast.parse(src)
            except Exception:
                continue

            drop_lines = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                seen = {}
                for dec in node.decorator_list:
                    key = norm(dec)
                    if key is None:
                        continue
                    if key in seen:
                        drop_lines.add(dec.lineno)
                        report.append((os.path.relpath(path, APP),
                                       dec.lineno, node.name, key))
                    else:
                        seen[key] = dec.lineno

            if drop_lines and apply_changes:
                lines = src.split('\n')
                kept = [l for i, l in enumerate(lines, start=1)
                        if i not in drop_lines]
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(kept))
                total_removed += len(drop_lines)

    print('EXACT duplicate @permission_required decorators')
    print('=' * 78)
    cur = None
    for rel, line, func, key in sorted(report):
        if rel != cur:
            print('\n%s' % rel)
            cur = rel
        print('   :%-5s %-32s %s' % (line, func, key))
    print('\nTOTAL exact duplicates: %d' % len(report))
    if apply_changes:
        print('REMOVED: %d lines' % total_removed)
    else:
        print('(dry run - pass --apply to remove)')


if __name__ == '__main__':
    main()
