#!/usr/bin/env python3
"""
Finds the 'missing null guard' bug class:

    obj = Model.get_by_id(some_id)      # returns None when the row is gone
    ...
    return render_template(..., obj=obj)  # template does obj.id -> 500

A record that was deleted (or an id typed by hand in the URL bar) should give
a friendly "not found" page, never a 500. This walks the real Python AST of
every route module, finds `X = <something>.get_by_id(...)` (and similar
lookup helpers), and reports the ones where X is never tested for falsiness
before the function returns a render_template/redirect.
"""
import ast
import os

APP = '/var/www/complynex'
LOOKUPS = ('get_by_id', 'get_by_token', 'find_by_id', 'get_one')
SKIP_DIRS = {'venv', 'node_modules', '__pycache__', 'scripts', 'tools',
             'tests', 'migrations', 'backups', 'data', 'uploads', 'static',
             'templates', 'logs', 'ekyc_storage', 'translations'}


def route_files():
    for dirpath, dirs, files in os.walk(APP):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                   and not d.startswith('.')]
        for fn in files:
            if fn.endswith('.py') and not fn.endswith('.bak'):
                yield os.path.join(dirpath, fn)


def is_lookup_call(node):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOOKUPS)


def names_tested(fn_node):
    """Every name that appears in a boolean/None test anywhere in the fn."""
    tested = set()
    for n in ast.walk(fn_node):
        if isinstance(n, (ast.If, ast.IfExp, ast.Assert, ast.While)):
            for sub in ast.walk(n.test):
                if isinstance(sub, ast.Name):
                    tested.add(sub.id)
        # `x or default`, `x and y`
        if isinstance(n, ast.BoolOp):
            for v in n.values:
                if isinstance(v, ast.Name):
                    tested.add(v.id)
        # abort_if_none(x) style helpers
        if isinstance(n, ast.Call):
            for a in n.args:
                if isinstance(a, ast.Name):
                    fname = getattr(n.func, 'attr', getattr(n.func, 'id', ''))
                    if 'abort' in fname or 'require' in fname or '404' in fname:
                        tested.add(a.id)
    return tested


def has_decorator_route(fn_node):
    for d in fn_node.decorator_list:
        s = ast.dump(d)
        if 'route' in s:
            return True
    return False


def main():
    findings = []
    for path in route_files():
        try:
            with open(path, encoding='utf-8') as f:
                tree = ast.parse(f.read())
        except Exception:
            continue

        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)]:
            if not has_decorator_route(fn):
                continue
            tested = names_tested(fn)

            # collect `x = Model.get_by_id(...)`
            assigned = {}
            for n in ast.walk(fn):
                if (isinstance(n, ast.Assign) and is_lookup_call(n.value)
                        and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Name)):
                    assigned[n.targets[0].id] = (n.lineno,
                                                 n.value.func.attr)

            # does the fn render a template / use the var in url_for?
            renders = any(
                isinstance(n, ast.Call)
                and getattr(n.func, 'id', '') in ('render_template',)
                for n in ast.walk(fn))

            for var, (lineno, kind) in assigned.items():
                if var not in tested and renders:
                    findings.append((os.path.relpath(path, APP), lineno,
                                     fn.name, var, kind))

    print('=' * 78)
    print('ROUTES THAT LOOK UP A RECORD BUT NEVER CHECK FOR None')
    print('(deleted record or hand-typed id => HTTP 500 instead of "not found")')
    print('=' * 78)
    for rel, lineno, fname, var, kind in sorted(findings):
        print('%-42s :%-5s %-32s %s = ...%s()' %
              (rel, lineno, fname, var, kind))
    print('\nTOTAL: %d' % len(findings))


if __name__ == '__main__':
    main()
