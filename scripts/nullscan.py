#!/usr/bin/env python3
"""
Find the defect class behind three of today's four 500s:

    obj = Model.get_by_id(x)
    ... obj.attribute        # obj is None when the record is gone

A stale link, a deleted record or a guessed URL turns into a 500 rather than a
clean "not found". Reports any function that fetches by id and dereferences it
without a None check in between.
"""
import ast, os, sys

ROOT = '/var/www/complynex'
SKIP = ('/venv', '/node_modules', '/.git', '__pycache__', '/backups')

FETCHERS = ('get_by_id', 'get_by_case_id', 'find_by_id', 'get_one')

class Scan(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path; self.hits = []

    def visit_FunctionDef(self, node):
        # names assigned from a *_by_id() call, with the line number
        fetched = {}
        for n in ast.walk(node):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                f = n.value.func
                name = getattr(f, 'attr', None)
                if name in FETCHERS and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                    fetched[n.targets[0].id] = n.lineno

        if fetched:
            # any `if not X` / `if X is None` / `if X:` guard anywhere in the fn
            guarded = set()
            for n in ast.walk(node):
                if isinstance(n, ast.If):
                    for sub in ast.walk(n.test):
                        if isinstance(sub, ast.Name) and sub.id in fetched:
                            guarded.add(sub.id)
                # `X.y if X else None` also counts
                if isinstance(n, ast.IfExp):
                    for sub in ast.walk(n.test):
                        if isinstance(sub, ast.Name) and sub.id in fetched:
                            guarded.add(sub.id)

            for var, ln in fetched.items():
                if var in guarded:
                    continue
                # is it dereferenced after the fetch?
                for n in ast.walk(node):
                    if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                            and n.value.id == var and n.lineno > ln):
                        self.hits.append((node.name, var, ln, n.lineno))
                        break
        self.generic_visit(node)

total = 0
for dirpath, dirs, files in os.walk(ROOT):
    if any(x in dirpath for x in SKIP):
        continue
    for fn in files:
        if not fn.endswith('.py') or '.bak' in fn:
            continue
        p = os.path.join(dirpath, fn)
        try:
            tree = ast.parse(open(p, encoding='utf-8', errors='replace').read())
        except Exception:
            continue
        sc = Scan(p); sc.visit(tree)
        if sc.hits:
            rel = p.replace(ROOT + '/', '')
            for fname, var, ln, dl in sc.hits:
                print(f'  {rel}:{ln}  {fname}()  ->  {var} fetched, used at line {dl}, no None check')
                total += 1
print(f'\nunguarded fetch-then-dereference: {total}')
