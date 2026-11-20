# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Minimal PDF text extraction for simple-font PDFs (literal WinAnsi strings), used when pdftotext is not
installed on the server. One output line per text baseline, words placed by their x position, so the
layout parsers (List of Common High Priority Items) work on its output as on pdftotext -layout."""
import re, zlib

_STR = re.compile(rb'\((?:\\.|[^\\()])*\)')


def _unescape(b):
    b = b[1:-1]
    out, i = bytearray(), 0
    while i < len(b):
        c = b[i]
        if c == 0x5c and i + 1 < len(b):
            n = b[i + 1]
            m = {ord('n'): 10, ord('r'): 13, ord('t'): 9, ord('b'): 8, ord('f'): 12}.get(n)
            if m is not None:
                out.append(m); i += 2; continue
            if 48 <= n <= 55:
                j = i + 1; oc = b''
                while j < len(b) and len(oc) < 3 and 48 <= b[j] <= 55:
                    oc += bytes([b[j]]); j += 1
                out.append(int(oc, 8) & 255); i = j; continue
            out.append(n); i += 2; continue
        out.append(c); i += 1
    return out.decode('cp1252', 'replace')


MAX_STREAM = 50_000_000        # one decompressed stream (a 'zip bomb' stops here)
MAX_TOTAL = 200_000_000        # all streams of the file


def _inflate(s, budget):
    d = zlib.decompressobj()
    out = d.decompress(s, min(MAX_STREAM, budget))
    if d.unconsumed_tail:
        raise ValueError('PDF stream too large')
    return out


def text_layout(data):
    """Very small PDF text extractor for simple-font PDFs (WinAnsi literal strings): one text line per
    baseline, words placed by their x position. Returns '' when the PDF uses other encodings. Decompression is
    capped (MAX_STREAM per stream, MAX_TOTAL per file)."""
    pages = []
    budget = MAX_TOTAL
    for s in re.findall(rb'stream\r?\n(.*?)\r?\nendstream', data, re.S):
        if budget <= 0:
            break
        try:
            u = _inflate(s, budget)
        except Exception:
            continue
        budget -= len(u)
        if b'BT' not in u:
            continue
        runs = []
        for bt in re.findall(rb'BT(.*?)ET', u, re.S):
            fs = re.search(rb'/\w+\s+([\d.]+)\s+Tf', bt)
            size = float(fs.group(1)) if fs else 11.0
            m = re.search(rb'(-?[\d.]+)\s+(-?[\d.]+)\s+Td', bt) or re.search(
                rb'[\d.\-]+\s+[\d.\-]+\s+[\d.\-]+\s+[\d.\-]+\s+(-?[\d.]+)\s+(-?[\d.]+)\s+Tm', bt)
            if not m:
                continue
            x, y = float(m.group(1)), float(m.group(2))
            parts = []
            for arr in re.findall(rb'\[(.*?)\]\s*TJ', bt, re.S):
                for tok in re.finditer(rb'\((?:\\.|[^\\()])*\)|(-?[\d.]+)', arr):
                    if tok.group(0).startswith(b'('):
                        parts.append(_unescape(tok.group(0)))
                    elif float(tok.group(0)) < -200:
                        parts.append(' ')
            for tj in re.findall(rb'(\((?:\\.|[^\\()])*\))\s*Tj', bt):
                parts.append(_unescape(tj))
            t = ''.join(parts)
            if t.strip():
                runs.append((round(-y, 0), x, t, size))
        if runs:
            pages.append(runs)
    out = []
    for runs in pages:
        lines = {}
        for y, x, t, size in runs:
            key = next((k for k in lines if abs(k - y) <= 2), y)
            lines.setdefault(key, []).append((x, t, size))
        for y in sorted(lines):
            row, end = '', None
            for x, t, size in sorted(lines[y]):
                if end is not None and x - end < size * 0.3:
                    row += t                       # the same word continued in another run
                else:
                    col = int(x / 5.2)
                    row = row + (' ' * max(1 if row else 0, col - len(row))) + t
                end = x + len(t) * size * 0.5
            out.append(row.rstrip())
        out.append('')
    return '\n'.join(out)
