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
"""Parsers for the published control lists (pure functions: bytes / text in, records out).

Used by scripts/dualuse/import_lists.py. Each parser returns plain dicts; the importer
versions them, diffs them against the previous load and writes the tables.
"""
import csv
import html as _html
import io
import os
import re

# ------------------------------------------------------------------ technical thresholds
UNITS = (r"(?:Weighted TeraFLOPS|Weighted TeraOPS|TeraFLOPS|TeraOPS|W/kg|W/cm2|W/m2|MeV|keV|eV|mm/s|µm/s|m/s2|"
         r"rad/s|°/h|degrees? per hour|arc seconds?|arc minutes?|lines per mm|dB/km|Ns/kg|N·m|kN·m|J/kg|%|GHz|MHz|"
         r"kHz|THz|Hz|GW|MW|kW|mW|µW|W|kV|mV|V|kA|mA|µA|A|K|°C|°|Gbit/s|Mbit/s|kbit/s|bit/s|bits?|Gbyte|Mbyte|"
         r"kbyte|TB|GB|MB|kB|byte|nm|µm|mm|cm|km|m|kg|mg|µg|g|tonnes|t|GPa|MPa|kPa|Pa|bar|psi|ps|ns|µs|ms|fs|s|"
         r"min|h|rpm|MJ|kJ|J|dBm|dB|m/s|km/h|kN|N|Nm|ml|l|m3|m2|mrad|µrad|rad|degrees?|g/cm3|Gy|Sv|Bq|Ci|TOPS|"
         r"TFLOPS|GFLOPS|FLOPS|channels|axes|Mach|g0)")
_PRE = [(r'equal to or (?:more|greater) than|not less than|at least|≥|>=', '>='),
        (r'equal to or less than|not (?:more|greater) than|not exceeding|less than or equal to|up to and including|≤|<=',
         '<='),
        (r'exceeding|more than|greater than|in excess of|higher than|above|over|>', '>'),
        (r'less than|lower than|below|under|<', '<')]
_POST = [(r'or (?:more|higher|greater|above)', '>='), (r'or (?:less|lower|below)', '<=')]
_NUM = r"(\d[\d ,]*(?:[.,]\d+)?(?:\s*[x×]\s*10\s*\^?\s*[-−]?\s*\d+)?)"
_pre = '|'.join('(?:%s)' % o for o, _ in _PRE)
_post = '|'.join('(?:%s)' % o for o, _ in _POST)
_P1 = re.compile(r"(?P<op>" + _pre + r")\s*" + _NUM + r"\s*(?P<unit>" + UNITS + r")(?![A-Za-z])", re.I)
_P2 = re.compile(_NUM + r"\s*(?P<unit>" + UNITS + r")(?![A-Za-z])(?:\s*\([^)]{1,20}\))?\s*,?\s+(?P<op>" + _post + r")\b",
                 re.I)
_CASW = r'(?:CAS|C\.A\.S\.)\s*(?:No\.?|Registry Number)?\s*#?\s*'
_CAS = re.compile(r'(?<![A-Za-z])' + _CASW + r'(\d{2,7}-\d{2}-\d)\b')


def _sym(t, table):
    for o, s in table:
        if re.fullmatch(o, t.strip(), re.I):
            return s
    return t


def _num(v, dec='.'):
    v = v.strip().rstrip(',')
    v = v.replace(' ', '').replace(',', '.') if dec == ',' else v.replace(',', '')
    m = re.match(r'([\d .]+?)\s*[x×]\s*10\s*\^?\s*([-−]?)\s*(\d+)$', v)
    if m:
        return float(m.group(1).replace(' ', '')) * 10 ** (int(m.group(3)) * (-1 if m.group(2) else 1))
    return float(v.replace(' ', ''))


_PN_CUT = re.compile(r'.*\b(?:having|with|where|whose|in which|of which|of|at|for|than)\s+(?:an?\s+|the\s+|its\s+|their\s+)?', re.I)
_PN_LEAD = re.compile(r'^(?:an?|the|its|their|any|all|each|total|both)\s+', re.I)


def _param_name(text, start):
    """The quantity a threshold applies to, from the words just before it ('a "peak power" exceeding 1 kW'
    -> 'peak power'; 'systems having transmit pulse widths 100 ns or less' -> 'transmit pulse widths')."""
    seg = re.split(r'[;:]|, (?=[a-z])|\band\b|\bor\b', text[max(0, start - 120):start])[-1]
    q = re.findall(r'["\'“‘]([^"\'”’]{3,60})["\'”’]', seg)
    if q:
        return q[-1].lower()
    w = re.sub(r'\([^)]*\)', ' ', seg)
    w = re.sub(r'\s+', ' ', w).strip(" ,(-")
    w = re.sub(r'\b(having|with|of|a|an|the|which|that|is|are|any|and|or|by|in|for|at|to|be|equal)\s*$', '', w).strip()
    cut = _PN_CUT.sub('', w)
    if cut and len(cut.split()) >= 1 and cut != w and not cut[:1].isdigit():
        w = cut
    w = _PN_LEAD.sub('', w).strip(" ,(-")
    words = w.split()[-5:]
    if not words or (len(words) == 1 and words[0].lower() in ('able', 'capable', 'designed', 'rated', 'modified')):
        return None
    return ' '.join(words).lower()


def extract_parameters(text, dec='.'):
    """Thresholds written in a control entry -> [{parameter, operator, value, unit, raw}]."""
    out = []
    text = (text or '').replace('μ', 'µ')
    text = re.sub(r'\s*\((?:better|worse|lower|higher)\)\s*', ' ', text)
    for pat, table in ((_P1, _PRE), (_P2, _POST)):
        for m in pat.finditer(text):
            try:
                val = _num(m.group(2) if pat is _P1 else m.group(1), dec)
            except ValueError:
                continue
            out.append({'parameter': _param_name(text, m.start()), 'operator': _sym(m.group('op'), table),
                        'value': val, 'unit': m.group('unit'), 'raw': re.sub(r'\s+', ' ', m.group(0)).strip()[:200]})
    return out


def cas_numbers(text):
    return sorted(set(_CAS.findall(text or '')))


def _clean(t):
    return re.sub(r'\s+', ' ', t or '').strip()


GROUPS = {'A': 'Systems, Equipment and Components', 'B': 'Test, Inspection and Production Equipment',
          'C': 'Materials', 'D': 'Software', 'E': 'Technology'}


# ------------------------------------------------------------------ EU Annex I (EUR-Lex HTML)
def parse_eu_annex1(html_text):
    """Annex I from EUR-Lex HTML. Two layouts exist: the consolidated text of the Regulation (CELEX 02021R0821-…,
    'grid-list' blocks, preferred: it includes every corrigendum) and the Official Journal act that replaces the
    Annex (nested tables)."""
    if 'grid-list-column-2' in (html_text or ''):
        return parse_eu_consolidated(html_text)
    return _parse_eu_oj_tables(html_text)


_EU_ENTRY = re.compile(r'^(\d[A-E]\d{3})\s+(\S.*)$', re.S)
_EU_LABEL = re.compile(r'^([a-z]{1,2}|\d{1,2})\.$')
_EU_NOTE_HEAD = re.compile(r'^(Notes?|N\.\s?B\.|Technical Notes?|Nota|Note \d+)\b', re.I)
_EU_STOP = re.compile(r'^(?:\d[A-E]\d?\s|PART\b|Category\s+\d|CATEGORY\s+\d)', re.I)


def _eu_annex1_slice(html_text):
    """The HTML of Annex I only (the consolidated document also carries Annexes II-VI, whose
    Annex IV repeats some codes with a different scope)."""
    s = html_text
    m = re.search(r'<p[^>]*class="title-annex-1"[^>]*>\s*ANNEX I\s*</p>', s)
    if not m:
        return s
    e = re.search(r'<p[^>]*class="title-annex-1"[^>]*>\s*ANNEX II\s*</p>', s[m.end():])
    return s[m.start(): m.end() + e.start() if e else len(s)]


def parse_eu_consolidated(html_text):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(_eu_annex1_slice(html_text), 'lxml')
    for t in soup.select('p.modref, .arrow, span.superscript a, a.footnote'):
        t.decompose()
    for t in soup.select('span.superscript'):         # 10<sup>-4</sup> -> 10^-4 ; m<sup>3</sup> -> m3
        prev = t.previous_sibling
        lead = '^' if isinstance(prev, str) and re.search(r'10\s*$', prev) else ''
        t.replace_with(lead + t.get_text('').strip())
    for t in soup.select('span.subscript'):
        t.replace_with(t.get_text('').strip())
    soup.smooth()
    items = {}

    def is_grid(el):
        return el.name == 'div' and 'grid-list' in (el.get('class') or [])

    def col(grid, n):
        return grid.find('div', class_='grid-list-column-%d' % n, recursive=False)

    def italic(el):
        """True when every visible character of `el` (outside nested lists) is set in italics: the Annex
        prints notes in italics and the controlling text in roman."""
        seen = False
        for s in el.find_all(string=True):
            if not s.strip():
                continue
            if any(is_grid(p) for p in s.parents if p is not el and el in p.parents):
                continue
            seen = True
            node, ok = s.parent, False
            while node is not None and node is not el.parent:
                if 'italics' in (node.get('class') or []):
                    ok = True
                    break
                node = node.parent
            if not ok:
                return False
        return seen

    def text(el):
        return _clean(el.get_text(' '))

    def add_note(code, t):
        if code in items and t:
            items[code]['notes_en'].append(t[:4000])

    def walk(children, code, entry):
        """children of an item (or of the entry block) in document order."""
        own, in_note = [], False
        for ch in children:
            if getattr(ch, 'name', None) is None:
                continue
            cls = ch.get('class') or []
            if is_grid(ch):
                c1, c2 = col(ch, 1), col(ch, 2)
                if c2 is None:
                    continue
                lab = text(c1) if c1 else ''
                m = _EU_LABEL.match(lab)
                first = next((x for x in c2.children if getattr(x, 'name', None) and not is_grid(x)), None)
                if m and not (c1 and italic(c1)) and not (first is not None and italic(first)):
                    in_note = False                  # a roman lettered / numbered paragraph ends a note
                    c = code + '.' + m.group(1)
                    items[c] = {'code': c, 'entry': entry, 'parent': code, 'level': c.count('.'),
                                'text_en': '', 'notes_en': []}
                    items[c]['text_en'] = walk(list(c2.children), c, entry)
                else:
                    add_note(code, (lab + ' ' + text(c2)).strip())
                continue
            if any(k.startswith('title-gr-seq') for k in cls):
                in_note = True                       # "Technical Notes:" heading inside an item
                add_note(code, text(ch))
                continue
            t = text(ch)
            if not t:
                continue
            if italic(ch) or _EU_NOTE_HEAD.match(t):
                in_note = in_note or bool(_EU_NOTE_HEAD.match(t))
                add_note(code, t)
            elif in_note and ch.name == 'div':
                add_note(code, t)
            else:
                own.append(t)
                in_note = False
        return _clean(' '.join(own))

    def entry_head(el):
        """(code, first text, children of the entry body) when `el` opens an entry, else None. An entry is
        either a paragraph starting with the code or a list block whose label is the code."""
        if getattr(el, 'name', None) is None:
            return None
        if is_grid(el):
            c1, c2 = col(el, 1), col(el, 2)
            lab = text(c1) if c1 else ''
            if c2 is not None and re.fullmatch(r'\d[A-E]\d{3}', lab):
                return lab, '', list(c2.children)
            return None
        cls = el.get('class') or []
        fp = el if (el.name == 'p' and 'norm' in cls) else (
            el.find('p', class_='norm', recursive=False) if el.name == 'div' else None)
        if fp is None or italic(fp):
            return None
        m = _EU_ENTRY.match(text(fp))
        if not m:
            return None
        return m.group(1), m.group(2).strip(), []

    heads = []
    for el in soup.find_all(['p', 'div']):
        if el.find_parent('div', class_='grid-list-column-2'):
            continue
        if el.name == 'p' and el.parent is not None and el.parent.name == 'div' and not is_grid(el.parent) \
                and len(el.parent.find_all('p', recursive=False)) == 1:
            continue                                 # the wrapping div is examined instead
        h = entry_head(el)
        if h and h[0] not in items:
            heads.append((el, h))
            items[h[0]] = None
    for el, (code, first, body) in heads:
        items[code] = {'code': code, 'entry': code, 'parent': None, 'level': 0, 'text_en': first, 'notes_en': []}
        block = list(body)
        for sib in el.find_next_siblings():
            cls = sib.get('class') or []
            if any(k.startswith('title-gr-seq') for k in cls) and _EU_STOP.match(text(sib)):
                break
            if entry_head(sib):
                break
            block.append(sib)
        rest = walk(block, code, code)
        if rest:
            items[code]['text_en'] = _clean((items[code]['text_en'] + ' ' + rest).strip())
    return _finish_eu({k: v for k, v in items.items() if v})


def _finish_eu(items):
    recs = []
    for c, r in items.items():
        if 'text_en' not in r:
            continue
        r['category'], r['group'] = c[0], c[1]
        r['not_used'] = bool(re.fullmatch(r'not used\W*', r['text_en'] or '', re.I))
        r['parameters'] = extract_parameters(r['text_en'], ',')
        r['cas_numbers'] = cas_numbers(r['text_en'])
        recs.append(r)
    return recs


def _parse_eu_oj_tables(html_text):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, 'lxml')
    code_re = re.compile(r'^(\d[A-E]\d{3})$')
    lab_re = re.compile(r'^([a-z]{1,2}|\d{1,2})\.$')
    note_re = re.compile(r'^(Note|Notes|N\.B\.|Technical Notes?|Nota|Note \d+)\s*\d*\s*:?$', re.I)
    items = {}

    def own_text(td):
        c = BeautifulSoup(str(td), 'lxml').find('td')
        for t in c.find_all('table'):
            t.decompose()
        return _clean(c.get_text(' '))

    def direct_tables(td):
        return [t for t in td.find_all('table') if t.find_parent('td') is td]

    def rows(table):
        tb = table.find('tbody') or table
        return tb.find_all('tr', recursive=False)

    def walk(td, code, entry):
        for t in direct_tables(td):
            for r in rows(t):
                tds = r.find_all('td', recursive=False)
                if len(tds) < 2:
                    continue
                lab = _clean(tds[-2].get_text(' '))
                content = tds[-1]
                m = lab_re.match(lab)
                if m:
                    c = code + '.' + m.group(1)
                    items[c] = {'code': c, 'entry': entry, 'parent': code, 'level': c.count('.'),
                                'text_en': own_text(content), 'notes_en': []}
                    walk(content, c, entry)
                elif note_re.match(lab) or lab.endswith(':'):
                    items.setdefault(code, {}).setdefault('notes_en', []).append(
                        (lab + ' ' + _clean(content.get_text(' ')))[:4000])
                else:
                    walk(content, code, entry)

    for tr in soup.find_all('tr'):
        tds = tr.find_all('td', recursive=False)
        if len(tds) < 2:
            continue
        for i in range(len(tds) - 1):
            lab = _clean(tds[i].get_text(' '))
            if code_re.match(lab) and not tds[i].find('table'):
                code, content = lab, tds[i + 1]
                if code in items and items[code].get('text_en'):
                    break
                items[code] = {'code': code, 'entry': code, 'parent': None, 'level': 0,
                               'text_en': own_text(content), 'notes_en': items.get(code, {}).get('notes_en', [])}
                walk(content, code, code)
                break
    return _finish_eu(items)


# ------------------------------------------------------------------ EU dual-use / CN correlation (xlsx)
def _norm_eu_code(c):
    c = str(c).strip().replace(' ', '')
    m = re.match(r'^(\d[A-E]\d{3})(.*)$', c)
    if not m:
        return None
    head, rest = m.groups()
    return head + ''.join('.' + p for p in re.findall(r'[a-z]+|\d+', rest.strip('.')))


def parse_correlation(xlsx_bytes, known_codes):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True)
    ws = wb.worksheets[0]
    rows, seen = [], set()
    for r in list(ws.iter_rows(values_only=True))[1:]:
        if len(r) < 3:
            continue
        cn, fn, du = r[:3]
        if not cn or not du:
            continue
        cn = re.sub(r'\D', '', str(cn)).ljust(10, '0')
        for d in re.split(r'[;,/]\s*', str(du)):
            c = _norm_eu_code(d)
            if not c or (cn, c) in seen:
                continue
            seen.add((cn, c))
            best = c
            while best not in known_codes and '.' in best:
                best = best.rsplit('.', 1)[0]
            rows.append({'cn10': cn, 'hs6': cn[:6], 'hs4': cn[:4], 'chapter': cn[:2], 'taric_footnote': fn,
                         'control_code': c, 'resolved_code': best if best in known_codes else None})
    return rows


# ------------------------------------------------------------------ Common High Priority Items
def parse_chpl_text(text):
    """Text of the CHPL PDF (pdftotext -layout) -> [{tier, hs6, hs_display, description_en}]."""
    recs, tier, pending, cur = [], None, [], None
    for ln in (text or '').splitlines():
        t = re.match(r'^\s*TIER\s+([0-9](?:\.[AB])?)\s*$', ln)
        if t:
            tier, pending, cur = t.group(1), [], None
            continue
        if tier is None or re.match(r'^\s*HS code', ln) or not ln.strip() or re.match(r'^\s*\d+\s*$', ln):
            continue
        m = re.match(r'^\s{2,}(\d{4}\.\d{2})(?:\s+(.*))?$', ln)
        if m:
            cur = {'tier': tier, 'hs6': m.group(1).replace('.', ''), 'hs_display': m.group(1),
                   'description_en': ' '.join(pending + [(m.group(2) or '').strip()]).strip()}
            recs.append(cur)
            pending = []
            continue
        txt = ln.strip()
        if cur and (txt[:1].islower() or txt[:1].isdigit() or txt[:1] in '(,;'):
            cur['description_en'] += ' ' + txt
        else:
            pending.append(txt)
    for r in recs:
        r['description_en'] = _clean(r['description_en'])
    return recs


def chpl_seed():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seed', 'chpl_2024-02.csv')
    with open(path, encoding='utf-8') as f:
        return [dict(r) for r in csv.DictReader(f)]


# ------------------------------------------------------------------ Chemical Weapons Convention schedules
def parse_cwc(pages):
    """pages: {1: html, 2: html, 3: html} of the schedule pages."""
    recs = []
    cas_line = re.compile(r'^\((\d{2,7}-\d{2}-\d)\)$')
    for n in (1, 2, 3):
        s = pages.get(n) or ''
        s = re.sub(r'<script.*?</script>|<style.*?</style>', '', s, flags=re.S)
        i = s.find('A. Toxic')
        s = s[i:] if i >= 0 else s
        s = re.sub(r'</?(sub|sup|em|i|b|strong|span|a)\b[^>]*>', '', s)
        t = _html.unescape(re.sub(r'<[^>]+>', '\n', s))
        lines = [x for x in (re.sub(r'\s+', ' ', y).strip() for y in t.split('\n')) if x]
        sec, groups, cur = 'A', [], None
        for ln in lines:
            if re.match(r'^[A-Z]\. (Toxic|Precursors)', ln):
                sec = ln[0]
                continue
            if re.match(r'^(Download|Media Centre|Featured Topics|Guidelines for Schedules)', ln) and groups:
                break
            m = re.match(r'^\((\d+)\)$', ln)
            if m:
                cur = {'item': int(m.group(1)), 'part': sec, 'lines': []}
                groups.append(cur)
                continue
            if cur is not None and ln.lower() != '(cas registry number)':
                cur['lines'].append(ln)
        for g in groups:
            L = g['lines']
            eg = next((k for k, x in enumerate(L) if x.lower().rstrip('.:') == 'e.g'), None)
            family = ' '.join(x for x in L[:eg] if not cas_line.match(x)) if eg is not None else None
            for k, x in enumerate(L):
                c = cas_line.match(x)
                if not c or k == 0:
                    continue
                name = L[k - 1]
                if cas_line.match(name) or name.lower().startswith('e.g'):
                    continue
                nm = re.match(r'^([A-Z][A-Za-z0-9\- ]{1,24}):\s+(.+)$', name)
                common, iupac = (nm.group(1).strip(), nm.group(2).strip()) if nm else (None, name)
                recs.append({'schedule': n, 'part': g['part'], 'item': g['item'], 'cas': c.group(1),
                             'name_en': iupac, 'common_name_en': common, 'family_en': family})
            if not any(cas_line.match(x) for x in L):
                recs.append({'schedule': n, 'part': g['part'], 'item': g['item'], 'cas': None,
                             'name_en': ' '.join(L)[:500], 'common_name_en': None, 'family_en': ' '.join(L)[:500]})
    return recs


# ------------------------------------------------------------------ US Commerce Control List (eCFR XML)
def parse_ccl(xml_text):
    s = xml_text or ''
    a = s.find('<DIV9 N="Supplement No. 1 to Part 774"')
    b = s.find('<DIV9 N="Supplement No. 2 to Part 774"')
    sup = s[a:b if b > a else len(s)] if a >= 0 else s

    def txt(x):
        x = re.sub(r'\s*\n\s*', ' ', x)                                  # source line breaks are not paragraphs
        x = re.sub(r'<(SU|E T="51")>\s*([^<]{1,12}?)\s*</(SU|E)>', r'^\2', x)  # superscript: 10^4
        x = re.sub(r'<br\s*/?>', ' ', x)
        x = re.sub(r'</(P|FP-\d|FP|TD|TR|HD\d|LI)>', '\n', x)
        x = _html.unescape(re.sub(r'<[^>]+>', '', x))
        x = re.sub(r'[ \t]+', ' ', x)
        return re.sub(r' *\n[\s]*', '\n', x).strip()

    cat = {}
    for m in re.finditer(r'<HD1>Category (\d)\W+([^<]+)', sup):
        cat[m.group(1)] = re.sub(r'^(?:x[0-9a-fA-F]+;|[^A-Za-z])+', '', _html.unescape(m.group(2))).strip()
    hdr = re.compile(r'<FP-2><B>\s*(\d[A-E]\d{3}(?:\.[a-z])?)\s+(.*?)</B>', re.S)
    ms = list(hdr.finditer(sup))
    recs = []
    note_blk = re.compile(r'<NOTE>.*?</NOTE>|<P>\s*<I>(?:(?!</?P>).)*?</I>\s*</P>', re.S)
    sub_re = re.compile(r'(?m)^([a-z]\.(?:(?:\d{1,2}|[a-z])\.)*)\s+(.{3,})$')
    for i, m in enumerate(ms):
        body = sup[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(sup)]
        t, title = txt(body), txt(m.group(2))
        rc = re.search(r'Reason for Control:\s*([^\n]+)', t)
        reasons = sorted(set(re.findall(r'\b(NS|MT|NP|CB|CW|AT|RS|CC|EI|SI|SL|FC|UN)\b', rc.group(1)))) if rc else []
        ib = re.search(r'<I>\s*Items:\s*</I>', body)
        items_raw = body[ib.end():] if ib else ''
        notes = [txt(x) for x in note_blk.findall(items_raw)]
        items = txt(note_blk.sub('\n', items_raw)) if ib else ''
        if not ib:
            im = re.search(r'Items:\s*(.*)', t, re.S)
            items = im.group(1).strip() if im else ''
        subs, seen = [], set()
        for sm in sub_re.finditer(items):
            code = m.group(1) + '.' + sm.group(1).rstrip('.')
            if code in seen:
                continue
            seen.add(code)
            tx = sm.group(2).strip()[:2000]
            subs.append({'code': code, 'parent': code.rsplit('.', 1)[0], 'text_en': tx,
                         'parameters': extract_parameters(tx, '.'), 'cas_numbers': cas_numbers(tx)})
        e = m.group(1)
        empty = bool(re.search(r'No items currently are in this ECCN', t)) or bool(
            re.match(r'\[?reserved\]?', title, re.I))
        recs.append({'code': e, 'category': e[0], 'category_title': cat.get(e[0]), 'group': e[1],
                     'title_en': title, 'reasons': reasons, 'items_text_en': items[:20000],
                     'notes_en': [n[:4000] for n in notes if n][:40], 'empty': empty,
                     'itar': 'subject to the ITAR' in title,
                     'series_600': e[2] == '6', 'series_500': e[2] == '5',
                     'sub_items': subs, 'parameters': extract_parameters(title, '.'), 'cas_numbers': cas_numbers(items)})
    return recs


# ------------------------------------------------------------------ unified chemicals register
_CHEM = re.compile(r"([A-Za-z0-9,()\[\]'’\-\s]+?)\s*\(\s*" + _CASW + r"(\d{2,7}-\d{2}-\d)\s*\)")
_CHEM_AFTER = re.compile(r"\(\s*" + _CASW + r"(\d{2,7}-\d{2}-\d)\s*\)\s*([^;\n()]{3,150}(?:\([^)\n]{0,40}\)[^;\n()]{0,80})?)")


def build_chemicals(eu, cwc, us):
    chem = {}

    def add(cas, name, ref):
        c = chem.setdefault(cas, {'cas': cas, 'names_en': [], 'listings': []})
        name = _clean(name)
        if name and len(name) <= 160 and name.lower() not in {n.lower() for n in c['names_en']} \
                and not name.lower().startswith(('and ', 'or ', 'as follows')):
            c['names_en'].append(name)
        if ref not in c['listings']:
            c['listings'].append(ref)

    for r in cwc:
        if r.get('cas'):
            if r.get('common_name_en'):
                add(r['cas'], r['common_name_en'], {'source': 'cwc', 'ref': 'Schedule %s%s item %s' % (
                    r['schedule'], r['part'], r['item']), 'schedule': r['schedule']})
            add(r['cas'], r['name_en'], {'source': 'cwc', 'ref': 'Schedule %s%s item %s' % (
                r['schedule'], r['part'], r['item']), 'schedule': r['schedule']})
    for r in eu:
        for m in _CHEM.finditer(r.get('text_en') or ''):
            add(m.group(2), re.sub(r'^\W+', '', m.group(1)).strip(' ;,')[-150:], {'source': 'eu_annex1', 'ref': r['code']})
    for r in us:
        txt = r.get('items_text_en') or ''
        for line in txt.split('\n'):
            lm = re.match(r'^([a-z]\.(?:(?:\d{1,2}|[a-z])\.)*)\s', line)
            ref = r['code'] + ('.' + lm.group(1).rstrip('.') if lm else '')
            hit = False
            for m in _CHEM_AFTER.finditer(line):        # "(C.A.S. #7784-34-1) Arsenic trichloride;"
                if m.group(2)[:1].islower():
                    continue                             # "(CAS 12045-63-5) having ...": the name came before
                add(m.group(1), m.group(2).strip(' ;,.'), {'source': 'us_ccl', 'ref': ref})
                hit = True
            if not hit:
                for m in _CHEM.finditer(line):
                    add(m.group(2), re.sub(r'^[a-z]\.(?:(?:\d{1,2}|[a-z])\.)*\s*', '', m.group(1).strip(' ;,.'))[-150:],
                        {'source': 'us_ccl', 'ref': ref})
    out = []
    for r in sorted(chem.values(), key=lambda x: x['cas']):
        r['ag_precursor'] = any(l['source'] == 'eu_annex1' and l['ref'].startswith('1C350') for l in r['listings'])
        r['cwc_schedule'] = min([l['schedule'] for l in r['listings'] if l['source'] == 'cwc'], default=None)
        out.append(r)
    return out
