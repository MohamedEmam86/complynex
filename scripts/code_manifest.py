#!/usr/bin/env python3
"""
ComplyNex — source code integrity and provenance manifest.

Answers two different questions people conflate:

  GENUINE   Has anything been altered since the last known-good state?
            -> cryptographic hash of every source file, compared over time.

  UNIQUE    Can you prove you authored it, and when?
            -> version history + independently timestamped manifests.

Usage:
    python3 scripts/code_manifest.py generate     write a new manifest
    python3 scripts/code_manifest.py verify       compare against the last one
    python3 scripts/code_manifest.py report       provenance summary
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = '/var/www/complynex'
OUT_DIR = os.path.join(ROOT, 'provenance')
SKIP_DIRS = {'venv', 'node_modules', '.git', '__pycache__', 'provenance',
             'uploads', 'ekyc_storage', 'logs', 'backups', 'attachments'}
SKIP_EXT = {'.pyc', '.pyo', '.log', '.db', '.index', '.sql', '.gz', '.tar'}


def is_source(path, name):
    if any(p in path.split(os.sep) for p in SKIP_DIRS):
        return False
    if '.bak' in name or name.endswith('~'):
        return False
    ext = os.path.splitext(name)[1].lower()
    if ext in SKIP_EXT:
        return False
    return ext in {'.py', '.html', '.js', '.css', '.json', '.cfg', '.sh', '.md', '.txt', '.po'}


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def collect():
    files, total_lines = {}, 0
    for dp, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, ROOT)
            if not is_source(rel, n):
                continue
            try:
                files[rel] = {
                    'sha256': file_hash(p),
                    'bytes': os.path.getsize(p),
                    'modified': datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec='seconds'),
                }
                if n.endswith(('.py', '.html', '.js')):
                    with open(p, 'rb') as f:
                        total_lines += sum(1 for _ in f)
            except OSError:
                continue
    return files, total_lines


def git(*args):
    try:
        return subprocess.check_output(['git', '-C', ROOT] + list(args),
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return ''


def generate():
    files, lines = collect()
    # One hash over the whole tree. Any change to any file changes this value,
    # so a single string is enough to prove or disprove integrity later.
    combined = hashlib.sha256(
        '\n'.join(f'{k}:{v["sha256"]}' for k, v in sorted(files.items())).encode()
    ).hexdigest()

    manifest = {
        'product': 'ComplyNex',
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'file_count': len(files),
        'total_lines': lines,
        'tree_sha256': combined,
        'git': {
            'commits': git('rev-list', '--count', 'HEAD') or '0',
            'head': git('rev-parse', 'HEAD'),
            'last_commit_date': git('log', '-1', '--format=%ci'),
            'first_commit_date': (git('log', '--reverse', '--format=%ci') or '\n').split('\n')[0],
            'uncommitted_files': len([l for l in git('status', '--short').split('\n') if l.strip()]),
            'authors': sorted(set(a for a in git('log', '--format=%an').split('\n') if a)),
        },
        'files': files,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(OUT_DIR, f'manifest_{stamp}.json')
    with open(path, 'w') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    latest = os.path.join(OUT_DIR, 'manifest_latest.json')
    with open(latest, 'w') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    print(f'Manifest written: {path}')
    print(f'  files      : {len(files)}')
    print(f'  lines      : {lines:,}')
    print(f'  TREE HASH  : {combined}')
    print()
    print('  Keep this hash somewhere independent — an email to yourself, a')
    print('  notarised document, or a blockchain timestamp. It is the fingerprint')
    print('  of the entire codebase at this moment.')
    return manifest


def verify():
    latest = os.path.join(OUT_DIR, 'manifest_latest.json')
    if not os.path.exists(latest):
        print('No previous manifest. Run "generate" first.')
        return 1
    old = json.load(open(latest))
    files, _ = collect()

    added = sorted(set(files) - set(old['files']))
    removed = sorted(set(old['files']) - set(files))
    changed = sorted(k for k in set(files) & set(old['files'])
                     if files[k]['sha256'] != old['files'][k]['sha256'])

    print(f'Baseline : {old["generated_at"]}  ({old["file_count"]} files)')
    print(f'Now      : {len(files)} files')
    print()
    print(f'  changed : {len(changed)}')
    print(f'  added   : {len(added)}')
    print(f'  removed : {len(removed)}')
    for label, items in (('CHANGED', changed), ('ADDED', added), ('REMOVED', removed)):
        for f in items[:15]:
            print(f'    {label:<8} {f}')
        if len(items) > 15:
            print(f'    ... and {len(items)-15} more')
    if not (changed or added or removed):
        print('\n  IDENTICAL — nothing has been altered since the baseline.')
        return 0
    return 2


def report():
    files, lines = collect()
    hdr = 0
    for rel in files:
        if not rel.endswith('.py'):
            continue
        try:
            if 'Copyright (c)' in open(os.path.join(ROOT, rel), encoding='utf-8',
                                      errors='replace').read(2000):
                hdr += 1
        except OSError:
            pass
    py = [f for f in files if f.endswith('.py')]

    print('ComplyNex — provenance report')
    print('=' * 46)
    print(f'  source files          : {len(files)}')
    print(f'  python files          : {len(py)}')
    print(f'  lines of code         : {lines:,}')
    print(f'  copyright headers     : {hdr}/{len(py)} python files')
    print()
    print('  VERSION CONTROL')
    print(f'    commits             : {git("rev-list", "--count", "HEAD") or 0}')
    print(f'    first commit        : {(git("log","--reverse","--format=%ci") or chr(10)).split(chr(10))[0] or "-"}')
    print(f'    last commit         : {git("log","-1","--format=%ci") or "-"}')
    unc = len([l for l in git('status', '--short').split('\n') if l.strip()])
    print(f'    UNCOMMITTED FILES   : {unc}')
    print(f'    authors             : {", ".join(sorted(set(a for a in git("log","--format=%an").split(chr(10)) if a))) or "-"}')
    if unc > 50:
        print()
        print(f'    WARNING: {unc} files are not committed. Work with no commit')
        print('    history has no timestamped record of authorship.')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'report'
    sys.exit({'generate': lambda: (generate(), 0)[1],
              'verify': verify,
              'report': lambda: (report(), 0)[1]}.get(cmd, lambda: (report(), 0)[1])())
