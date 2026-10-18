#!/usr/bin/env python3
"""
Detect premature </script> terminators inside inline <script> blocks.

WHY THIS MATTERS
The HTML parser does not understand JavaScript. The instant it sees the
character sequence "</script" inside a <script> element it ENDS the element --
even when that sequence sits inside a JS comment or a quoted string.
Everything after it is re-parsed as ordinary page content and rendered as
visible text on the page, and the real script never runs.

This is what corrupted the screening result page: a comment that mentioned
</script> while explaining how to escape untrusted data silently truncated the
block, leaked source code onto the page, and left the adverse-media spinner
running forever.

HOW IT DETECTS
A small JavaScript lexer walks each inline script tracking whether it is
inside a line comment, block comment, or a single/double/backtick string.
Any "</script" seen while in one of those states is a premature terminator.
(A "</style" inside a <script> is harmless and is NOT reported -- only the
matching end-tag name terminates an element.)

Usage: scan_script_breakout.py [--fix]
  --fix rewrites the offender as "<\\/script", which JavaScript reads as the
        identical string while the HTML parser no longer matches an end tag.
        This is the standard, spec-endorsed escape.
"""
import os
import re
import sys

TPL = '/var/www/complynex/templates'
OPEN_RE = re.compile(r'<script\b[^>]*>', re.I)
END_RE = re.compile(r'</\s*script', re.I)


def find_breakouts(src):
    """Yield (abs_pos, state) for every </script written inside a JS comment
    or string literal."""
    out = []
    for om in OPEN_RE.finditer(src):
        i = om.end()
        n = len(src)
        state = None        # None | 'line' | 'block' | "'" | '"' | '`'
        while i < n:
            ch = src[i]
            nxt = src[i + 1] if i + 1 < n else ''

            if state is None:
                if ch == '/' and nxt == '/':
                    state = 'line'
                    i += 2
                    continue
                if ch == '/' and nxt == '*':
                    state = 'block'
                    i += 2
                    continue
                if ch in ('"', "'", '`'):
                    state = ch
                    i += 1
                    continue
                if ch == '<' and END_RE.match(src, i):
                    break            # legitimate end of the script element
                i += 1
                continue

            # --- inside a comment or string -----------------------------
            if state == 'line':
                if ch == '\n':
                    state = None
            elif state == 'block':
                if ch == '*' and nxt == '/':
                    state = None
                    i += 2
                    continue
            else:                      # a quoted string
                if ch == '\\':
                    i += 2
                    continue
                if ch == state:
                    state = None
                elif ch == '\n' and state in ('"', "'"):
                    state = None       # unterminated string; resync

            if ch == '<' and END_RE.match(src, i):
                out.append((i, state))
                # keep scanning: the HTML parser would have stopped here, but
                # we want to report every offender in the file
            i += 1
    return out


def process(path, fix=False):
    with open(path, encoding='utf-8') as f:
        src = f.read()

    hits = find_breakouts(src)
    if not hits:
        return []

    report = []
    for pos, state in hits:
        line = src[:pos].count('\n') + 1
        ctx = src[max(0, pos - 55):pos + 45].replace('\n', ' ')
        report.append((line, state, ctx.strip()))

    if fix:
        # rewrite from the end so earlier offsets stay valid
        for pos, _state in sorted(hits, reverse=True):
            m = END_RE.match(src, pos)
            src = src[:pos] + '<\\/script' + src[m.end():]
        with open(path, 'w', encoding='utf-8') as f:
            f.write(src)

    return report


def main():
    fix = '--fix' in sys.argv
    total = 0
    for root, _dirs, files in os.walk(TPL):
        for fn in sorted(files):
            if not fn.endswith('.html'):
                continue
            path = os.path.join(root, fn)
            try:
                rep = process(path, fix)
            except Exception as e:
                print('!! %s: %s' % (path, e))
                continue
            if rep:
                print('\n%s' % os.path.relpath(path, TPL))
                for line, state, ctx in rep:
                    where = {'line': 'JS line comment',
                             'block': 'JS block comment'}.get(
                                 state, 'string literal (%s)' % state)
                    print('   line %-5s in %-22s ...%s...' % (line, where, ctx))
                total += len(rep)

    print('\nTOTAL premature </script> terminators: %d' % total)
    if fix and total:
        print('FIXED - rewritten as <\\/script>')
    elif total:
        print('(dry run - pass --fix to repair)')


if __name__ == '__main__':
    main()
