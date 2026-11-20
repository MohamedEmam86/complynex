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
"""
Read the local negative-lists workbook into records with a stable identity (no database here).

Sheets are recognised by their HEADER CONTENT, never by their name (names carry dates and change with every
edition). Kinds of sheet:

  PP_ORDER         asset-disposal ban orders of the Public Prosecutor - a historical register: one row per
                   order event, «منع» (imposed) or «إنهاء أثر» (lifted); old rows are never deleted
  TERROR_REGISTER  terrorists and terrorist entities from the unit's letters - the same historical register
                   idea, the last column says when a listing was lifted («رفع الحظر / رفع التحفظ / إنهاء الأثر»)
  FIU_PERSONS      the terrorist list as published on the unit's site (masked national IDs)
  FIU_ENTITIES     terrorist entities (groups) as published on the unit's site
  FIU_LEGAL        legal persons (companies, associations) listed as terrorist entities
  UN               UN Security Council sanctions sheets (1718 / ISIL-AQ / 1988 / Iran ...) with Arabic names

Header handling: the header row is found by content (first rows), a second header row under merged cells
(«رقم أمر المنع / سنة المنع», «الأول / الثاني ...») is merged into the column labels, and a merged header is
carried to the columns it spans. Placeholders ('ــــ', '—', '-', 'N/A', 'غير مذكور' ...) become empty.

Identity (what makes a record the same record in the next edition):
  PP_ORDER / TERROR_REGISTER   full national ID > (when absent) attach to a person already known by unified code,
                               by name + order number or by name + case number > other ID (passport, commercial
                               register) > unified code > name (+ date of birth)
  FIU_PERSONS                  name + visible digits of the masked national ID > passport > name + date of birth >
                               name + case
  FIU_ENTITIES / FIU_LEGAL     name
  UN                           the UN reference number (e.g. XXi.123)

Status of a register record: the events are grouped per order (order number / year, else case); each order is
in force or lifted according to its LAST event (by date, then by row order); the record is LISTED while any
order is in force, else LIFTED. A lift that names no known order lifts the only order in force; when several
are in force it lifts none (counted as 'lift_unmatched' - conservative: the person stays listed).
"""
import datetime as _dt
import hashlib
import json
import re
import unicodedata

from screening.local_lists.categories import CATEGORIES, UN_PREFIX, UN_TITLE_HINTS  # noqa: F401 (re-exported)

KINDS = ('PP_ORDER', 'TERROR_REGISTER', 'FIU_PERSONS', 'FIU_ENTITIES', 'FIU_LEGAL', 'UN')
KIND_LABEL = {
    'PP_ORDER': 'Public Prosecutor asset-disposal ban orders (register)',
    'TERROR_REGISTER': 'Terrorists and terrorist entities (register of letters)',
    'FIU_PERSONS': 'Terrorist list (unit site)',
    'FIU_ENTITIES': 'Terrorist entities (unit site)',
    'FIU_LEGAL': 'Legal persons listed as terrorist entities (unit site)',
    'UN': 'UN Security Council sanctions list',
}
KEY_PREFIX = {'PP_ORDER': 'PP', 'TERROR_REGISTER': 'TR', 'FIU_PERSONS': 'FP', 'FIU_ENTITIES': 'FE',
              'FIU_LEGAL': 'FL', 'UN': 'UN'}
MAX_COLS = 40
EMPTY_RUN_STOP = 2000          # consecutive empty rows that end a sheet (the sheets claim a million rows)

# ----------------------------------------------------------------------------- text helpers
_DIAC = re.compile('[ً-ٰٟـ]')
_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_PLACEHOLDER = re.compile(r'^[\s\-ـ_–—.·•*/\\|~=+]*$')
_PLACEHOLDER_WORDS = {'na', 'n/a', 'n.a', 'n.a.', 'nan', 'none', 'null', 'nil', 'غير مذكور', 'غير معروف', 'لا يوجد',
                      'لايوجد', 'بدون', 'غير متوفر'}
AR = re.compile('[؀-ۿ]')
LAT = re.compile('[A-Za-z]')


def norm(s):
    """Normalised Arabic / English text for header matching and identity keys."""
    s = unicodedata.normalize('NFKC', str(s or '')).translate(_AR_DIGITS)
    s = _DIAC.sub('', s)
    s = re.sub('[أإآٱ]', 'ا', s).replace('ة', 'ه').replace('ى', 'ي').replace('ؤ', 'و').replace('ئ', 'ي')
    s = re.sub(r'[^\w\s]', ' ', s.lower()).replace('_', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def name_key(s):
    """Identity form of a name: letters only, Arabic variants folded, 'عبد ال' joined."""
    s = norm(s)
    s = re.sub(r'\d+', ' ', s)
    s = re.sub(r'\bعبد\s+(?=ال)', 'عبد', s)
    s = re.sub(r'\bابو\s+', 'ابو', s)
    return re.sub(r'\s+', ' ', s).strip()


def clean(v):
    """Cell -> trimmed text ('' for empty / placeholder). Integral floats lose '.0', dates become ISO."""
    if v is None:
        return ''
    if isinstance(v, _dt.datetime):
        return v.date().isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, float):
        if v != v:
            return ''
        if v == int(v):
            v = int(v)
    s = unicodedata.normalize('NFKC', str(v)).replace('\xa0', ' ')
    s = re.sub(r'[ \t]+', ' ', s).strip()
    s = re.sub(r'\s*\n\s*', '\n', s)
    if _PLACEHOLDER.match(s) or s.lower().strip(' .') in _PLACEHOLDER_WORDS:
        return ''
    return s


def one_line(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def digits(s):
    return re.sub(r'\D', '', str(s or '').translate(_AR_DIGITS))


# ----------------------------------------------------------------------------- dates
_MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10,
    'nov': 11, 'dec': 12, 'يناير': 1, 'فبراير': 2, 'مارس': 3, 'ابريل': 4, 'مايو': 5, 'يونيو': 6, 'يونيه': 6,
    'يوليو': 7, 'يوليه': 7, 'اغسطس': 8, 'سبتمبر': 9, 'اكتوبر': 10, 'نوفمبر': 11, 'ديسمبر': 12,
}
_MONTH_RE = '|'.join(sorted(_MONTHS, key=len, reverse=True))


def _mk(y, m, d):
    try:
        y, m, d = int(y), int(m), int(d)
        if y < 100:
            y += 2000 if y < 50 else 1900
        if 1880 <= y <= 2100:
            return _dt.date(y, m, d).isoformat()
    except (TypeError, ValueError):
        pass
    return None


_DATE_PATTERNS = (
    (r'(?<!\d)((?:18|19|20)\d\d) (\d{1,2}) (\d{1,2})(?!\d)', lambda g: _mk(g[0], g[1], g[2])),
    (r'(?<!\d)(\d{1,2}) (\d{1,2}) ((?:18|19|20)\d\d|\d\d)(?!\d)', lambda g: _mk(g[2], g[1], g[0])),
    (rf'(?<!\d)(\d{{1,2}}) ?({_MONTH_RE})\w* ?((?:18|19|20)\d\d)(?!\d)', lambda g: _mk(g[2], _MONTHS[g[1]], g[0])),
    (rf'\b({_MONTH_RE})\w* (\d{{1,2}}) ((?:18|19|20)\d\d)(?!\d)', lambda g: _mk(g[2], _MONTHS[g[0]], g[1])),
)


def find_dates(v):
    """All dates in a cell, in order (ISO 'YYYY-MM-DD'; a bare year 'YYYY' only when nothing finer exists)."""
    if isinstance(v, (_dt.date, _dt.datetime)):
        return [clean(v)]
    s = norm(clean(v))
    if not s:
        return []
    found, taken = [], []
    for pat, conv in _DATE_PATTERNS:
        for m in re.finditer(pat, s):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            d = conv(m.groups())
            if d:
                found.append((m.start(), d))
                taken.append((m.start(), m.end()))
    if not found:
        for m in re.finditer(r'(?<!\d)(1[89]\d\d|20\d\d)(?!\d)', s):
            found.append((m.start(), m.group(1)))
    return [d for _p, d in sorted(found)]


def first_date(v):
    d = find_dates(v)
    return d[0] if d else ''


# ----------------------------------------------------------------------------- national ID
def valid_nid(s):
    """A full 14-digit Egyptian national ID with a real date of birth (century 2/3)."""
    d = digits(s)
    if len(d) != 14 or d[0] not in '23':
        return ''
    return d if _mk((1900 if d[0] == '2' else 2000) + int(d[1:3]), d[3:5], d[5:7]) else ''


def nid_dob(nid):
    try:
        from screening.match_intel import decode_egyptian_nid
        out = decode_egyptian_nid(nid) or {}
        if out.get('dob'):
            return out['dob']
    except Exception:
        pass
    d = valid_nid(nid)
    return _mk((1900 if d[0] == '2' else 2000) + int(d[1:3]), d[3:5], d[5:7]) if d else ''


# ----------------------------------------------------------------------------- names and aliases
_AKA = re.compile(r'\s*(?:،|,)?\s*(?:و\s*)?(?:الشهير(?:ه)?|الشهيره|المكني|المكنى|الملقب(?:ه)?|وشهرته|وشهرتها|شهرته|'
                  r'شهرتها|المعروف(?:ه)?|الشهيرة)\s*(?:ب|بـ|باسم)?\s*')


def split_name(raw):
    """Published name -> (main name, [aliases]). Quoted nicknames, text in brackets, 'الشهير بـ ...' and
    alternatives separated by ' / ' or ' - ' become aliases; the full published form is kept as an alias
    when it differs from the main name."""
    full = one_line(raw)
    if not full:
        return '', []
    aliases = []
    t = full
    for q in re.findall(r'["“”«»]([^"“”«»]{2,})["“”«»]', t):
        aliases.append(q.strip())
    t = re.sub(r'["“”«»][^"“”«»]{2,}["“”«»]', ' ', t)
    for b in re.findall(r'\(([^)]{2,})\)', t):
        b = _AKA.sub(' ', b).strip()
        aliases.extend(p.strip() for p in re.split(r'\s*/\s*|\s*؛\s*|\s*;\s*', b) if p.strip())
    t = re.sub(r'\([^)]*\)', ' ', t)
    parts = _AKA.split(t)
    t = parts[0]
    aliases.extend(p.strip(' ،,-') for p in parts[1:] if p.strip(' ،,-'))
    alts = [p.strip(' ،,') for p in re.split(r'\s+/\s+|\s+-\s+|\s*/\s*(?=\S)', t) if p.strip(' ،,')]
    main = alts[0] if alts else t
    aliases.extend(alts[1:])
    main = one_line(main.strip(' ،,-/'))
    if not main and aliases:
        main = aliases.pop(0)
    if full != main:
        aliases.append(full)
    seen, out = {name_key(main)}, []
    for a in aliases:
        a = one_line(a.strip(' ،,-/'))
        k = name_key(a)
        if a and k and k not in seen and len(k) > 1:
            seen.add(k)
            out.append(a)
    return main, out


def split_aliases(raw):
    """'a) X b) Y', 'X; Y', lines -> [X, Y]."""
    s = clean(raw)
    if not s:
        return []
    s = re.sub(r'(?:(?<=\s)|^)[a-z]\)\s*', '\n', s)
    out = []
    for p in re.split(r'[;\n؛]', s):
        p = one_line(p).strip(' ,.،')
        if p and not _PLACEHOLDER.match(p) and p.lower() not in _PLACEHOLDER_WORDS:
            out.append(p)
    return out


# ----------------------------------------------------------------------------- sheet layout
# field -> list of header phrases (matched on the normalised label); '=' prefix = the label must be exactly it
FIELDS = {
    'PP_ORDER': [('name', ['=الاسم', '=اسم الممنوع']), ('file_ref', ['ترتيب الملفات']),
                 ('id', ['رقم البطاقه', 'رقم اثبات', 'الرقم القومي']), ('id_type', ['نوع اثبات']),
                 ('code', ['الكود الموحد']), ('person_type', ['نوع الشخص']),
                 ('order_no', ['رقم امر', 'امر المنع']), ('order_year', ['سنه المنع', 'سنه الامر']),
                 ('case_no', ['رقم القضيه', 'القضيه']), ('case_year', ['سنه القضيه']),
                 ('status', ['انهاء اثر', 'انهاء الاثر']), ('letter_no', ['رقم الكتاب', 'كتاب']),
                 ('letter_date', ['كتاب السيد المستشار التاريخ', 'تاريخ الكتاب']),
                 ('received', ['تاريخ ورود']), ('notes', ['ملحوظات', 'ملاحظات'])],
    'TERROR_REGISTER': [('name', ['=الاسم']), ('file_ref', ['ترتيب الملفات']),
                        ('id', ['رقم اثبات', 'رقم البطاقه', 'الرقم القومي']), ('id_type', ['نوع اثبات']),
                        ('code', ['الكود الموحد']), ('owner', ['مالك الكيان']), ('address', ['العنوان']),
                        ('occupation', ['نوع النشاط', 'الوظيفه']), ('order_no', ['قرار ادراج']),
                        ('order_year', ['سنه القرار']), ('case_no', ['رقم القضيه']), ('case_year', ['سنه القضيه']),
                        ('letter_no', ['كتاب المستشار']), ('letter_date', ['تاريخ الكتاب']),
                        ('received', ['تاريخ ورود']), ('status', ['رفع التحفظ', 'رفع الحظر', 'الموقف'])],
    'FIU_PERSONS': [('name', ['=الاسم']), ('alias', ['اسم اخر', 'اسم الشهره']), ('id', ['الرقم القومي']),
                    ('passport', ['جواز السفر']), ('nationality', ['الجنسيه']), ('case', ['رقم القضيه']),
                    ('decision', ['قرار ادراج']), ('pub_date', ['تاريخ النشر']), ('pub_issue', ['عدد النشر'])],
    'FIU_ENTITIES': [('serial', ['=مسلسل']), ('name', ['اسم الكيان']), ('country', ['الدوله']),
                     ('name_en', ['بالانجليزيه']), ('name_foreign', ['بلغه البلد', 'الاجنبي']),
                     ('case', ['رقم القضيه']), ('gazette', ['العدد بالجريده', 'الجريده الرسميه']),
                     ('updates', ['التحديثات'])],
    'FIU_LEGAL': [('serial', ['=مسلسل']), ('name', ['اسم الشخص الاعتباري']),
                  ('registration', ['السجل التجاري', 'مشهره']), ('address', ['المقر', 'العنوان']),
                  ('case', ['رقم القضيه']), ('gazette', ['العدد بالجريده', 'الجريده الرسميه']),
                  ('updates', ['التحديثات'])],
    'UN': [('party_type', ['اشخاص']), ('ref', ['مسلسل الادراج']), ('official', ['الاسم الرسمي']),
           ('dob', ['تاريخ الميلاد']), ('pob', ['محل الميلاد']), ('alias_good', ['تم تاكيدها']),
           ('alias_low', ['غير اكيده', 'غير مؤكده']), ('nationality', ['الجنسيه']), ('passport', ['جواز السفر']),
           ('nid', ['رقم قومي']), ('address', ['العنوان']), ('listed', ['تاريخ الادراج']),
           ('info', ['معلومات اضافيه'])],
}
SUB_HEADER_WORDS = ('رقم', 'سنه', 'التاريخ', 'الاول', 'الثاني', 'الثالث', 'الرابع', 'ملحوظات', 'تاريخ')
_ALL_PHRASES = sorted({norm(p.lstrip('=')) for fs in FIELDS.values() for _f, ps in fs for p in ps}
                      | {norm('الاسم'), norm('الإسم الرباعي'), norm('منع / إنهاء اثر')}, key=len, reverse=True)


def _norm_fields():
    return {k: [(f, [('=' if p.startswith('=') else '') + norm(p.lstrip('=')) for p in ps]) for f, ps in v]
            for k, v in FIELDS.items()}


_FIELDS_N = _norm_fields()


def detect_kind(labels):
    """Kind of sheet from its (normalised) column labels; None when it is not a list sheet."""
    text = ' | '.join(labels)

    def has(*ps):
        return all(norm(p) in text for p in ps)
    if has('الاسم الرسمي') and (has('مسلسل الادراج') or has('تاريخ الادراج')):
        return 'UN'
    if has('انهاء اثر') or (has('امر المنع') and not has('قرار ادراج')):
        return 'PP_ORDER'
    if has('قرار ادراج') and (has('الكود الموحد') or has('رفع التحفظ') or has('مالك الكيان')):
        return 'TERROR_REGISTER'
    if has('اسم الكيان'):
        return 'FIU_ENTITIES'
    if has('اسم الشخص الاعتباري') or (has('السجل التجاري') and has('المقر')):
        return 'FIU_LEGAL'
    if has('الاسم') and (has('اسم اخر') or (has('جواز السفر') and (has('تاريخ النشر') or has('قرار ادراج')))):
        return 'FIU_PERSONS'
    return None


def _score(cells):
    n = 0
    for c in cells:
        t = norm(c)
        if t and len(t) <= 60 and any(p == t or (len(p) > 4 and p in t) for p in _ALL_PHRASES):
            n += 1
    return n


def read_rows(ws):
    """Rows of a worksheet as lists of raw values (trailing empties trimmed), stopping after a long empty run."""
    out, empty = [], 0
    for row in ws.iter_rows(max_col=MAX_COLS, values_only=True):
        vals = list(row)
        while vals and (vals[-1] is None or (isinstance(vals[-1], str) and not vals[-1].strip())):
            vals.pop()
        if not vals:
            empty += 1
            out.append([])
            if empty >= EMPTY_RUN_STOP:
                break
            continue
        empty = 0
        out.append(vals)
    while out and not out[-1]:
        out.pop()
    return out


def layout(rows):
    """(header_index, labels, first_data_index, title) or None. Labels are normalised, merged headers carried
    to the columns they span and the sub-header row (if any) appended."""
    head = None
    for i, r in enumerate(rows[:15]):
        if _score([clean(c) for c in r]) >= 3:
            head = i
            break
    if head is None:
        return None
    hdr = [clean(c) for c in rows[head]]
    sub, start = [], head + 1
    if head + 1 < len(rows):
        cand = [clean(c) for c in rows[head + 1]]
        ne = [c for c in cand if c]
        if len(ne) >= 2 and not any(re.search(r'\d', c) for c in ne) and \
                sum(1 for c in ne if any(w in norm(c) for w in SUB_HEADER_WORDS)) >= 2:
            sub, start = cand, head + 2
    width = max([len(hdr), len(sub)] + [len(r) for r in rows[start:start + 200]] or [0])
    labels, last = [], ''
    for j in range(width):
        h = hdr[j] if j < len(hdr) else ''
        if h:
            last = h
        else:
            h = last
        s = sub[j] if j < len(sub) else ''
        labels.append(norm(f'{h} {s}'.strip()))
    title = ' '.join(clean(c) for r in rows[:head] for c in r if clean(c))
    return head, labels, start, title


def map_columns(kind, labels):
    """field -> column index (and for UN 'name_parts' -> [indexes])."""
    used, cols = set(), {}
    for field, phrases in _FIELDS_N[kind]:
        for p in phrases:
            exact = p.startswith('=')
            p = p.lstrip('=')
            hit = next((j for j, lab in enumerate(labels) if j not in used and lab and
                        ((lab == p or lab.startswith(p + ' ')) if exact else p in lab)), None)
            if hit is not None:
                cols[field] = hit
                used.add(hit)
                break
    if kind == 'UN':
        parts = [j for j, lab in enumerate(labels) if j not in used and lab.startswith(norm('الاسم'))
                 and 'الرسمي' not in lab]
        cols['name_parts'] = parts
    return cols


def _junk(cells):
    """A filler row: the same value repeated in four or more columns (signature / test rows)."""
    vals = [c for c in cells if c]
    if not vals:
        return True
    top = max(vals.count(v) for v in set(vals))
    return top >= 4 and len(set(vals)) <= 2


# ----------------------------------------------------------------------------- workbook
class Sheet:
    def __init__(self, name, kind, rows_read=0):
        self.name, self.kind, self.rows_read = name, kind, rows_read
        self.rows = []          # parsed rows: dict field -> text, plus '_row'
        self.skipped = 0
        self.title = ''
        self.columns = {}
        self.category_hint = None


def read_workbook(path):
    """[Sheet] for every sheet (kind None = not a list sheet: explanation, empty or unrecognised)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = []
    try:
        for ws in wb.worksheets:
            raw = read_rows(ws)
            lay = layout(raw)
            if not lay:
                sh = Sheet(ws.title, None, sum(1 for r in raw if r))
                sh.looks_like_data = sum(1 for r in raw if len([c for c in r if clean(c)]) >= 3) >= 5
                sheets.append(sh)
                continue
            head, labels, start, title = lay
            kind = detect_kind(labels)
            sh = Sheet(ws.title, kind)
            sh.title, sh.labels = title, labels
            sh.looks_like_data = True
            if not kind:
                sh.rows_read = sum(1 for r in raw[start:] if r)
                sheets.append(sh)
                continue
            cols = map_columns(kind, labels)
            sh.columns = cols
            hdr_raw = {norm(clean(c)) for c in raw[head] if clean(c)}
            for i in range(start, len(raw)):
                r = raw[i]
                if not r:
                    continue
                sh.rows_read += 1
                cells = [clean(c) for c in r]
                if _junk(cells) or sum(1 for c in cells if c and norm(c) in hdr_raw) >= 3:
                    sh.skipped += 1
                    continue
                rec = {'_row': i + 1}
                for f, j in cols.items():
                    if f == 'name_parts':
                        rec[f] = [cells[k] for k in j if k < len(cells) and cells[k]]
                    elif j < len(r):
                        rec[f] = cells[j]
                        if f in ('letter_date', 'received', 'dob', 'listed', 'pub_date') and \
                                isinstance(r[j], (_dt.date, _dt.datetime)):
                            rec[f] = clean(r[j])
                        if f == 'id' and isinstance(r[j], (_dt.date, _dt.datetime)):
                            rec['id_is_date'] = True
                if kind == 'UN':
                    ok = bool(rec.get('ref') and re.match(r'[A-Za-z]{3}\s*\.', rec['ref'])) or \
                        (rec.get('name_parts') and sum(1 for c in cells if c) >= 3)
                else:
                    ok = bool(rec.get('name'))
                if not ok:
                    sh.skipped += 1
                    continue
                sh.rows.append(rec)
            sheets.append(sh)
    finally:
        try:
            wb.close()
        except Exception:
            pass
    return sheets


def workbook_date(sheets):
    """The edition date: the latest date in the sheet names / titles (None if none)."""
    best = None
    today = _dt.date.today().isoformat()
    for sh in sheets:
        for d in find_dates(f'{sh.name} {sh.title}'):
            if len(d) == 10 and d <= today and (best is None or d > best):
                best = d
    return best


# ----------------------------------------------------------------------------- record building
def _order_key(no, year):
    n = norm(no).replace(' ', '')
    y = digits(year)[:4]
    return f'{n}/{y}' if n or y else ''


def _ref(no, year):
    no, year = one_line(no), one_line(year)
    return f'{no}/{year}' if no and year else (no or year)


_ENTITY_WORDS = ('شركه', 'شركة', 'جمعيه', 'جمعية', 'مؤسسه', 'مؤسسة', 'مكتب', 'مدرسه', 'مدرسة', 'مستشفي', 'مستشفى',
                 'مصنع', 'مجموعه', 'مجموعة', 'جماعه', 'جماعة', 'حركه', 'حركة', 'منظمه', 'منظمة', 'قناه', 'قناة',
                 'موقع', 'دار', 'مركز', 'بنك', 'صندوق', 'اتحاد')
_CR_TYPES = ('سجل تجار', 'رقم القيد', 'رقم تاسيس', 'ملف ضريب', 'استثمار', 'سجل')
_LIFT_WORDS = ('انهاء اثر', 'انهاء الاثر', 'رفع الحظر', 'رفع التحفظ', 'الغاء الادراج', 'رفع الاسم', 'رفع اسم',
               'شطب')


def is_lift(status):
    t = norm(status)
    return any(w in t for w in _LIFT_WORDS)


def _id_class(id_type):
    t = norm(id_type)
    if 'جواز' in t:
        return 'pp'
    if any(w in t for w in _CR_TYPES):
        return 'cr'
    if 'ميلاد' in t or t == 'سن':
        return 'dob'
    if 'قومي' in t or 'بطاقه' in t:
        return 'nid'
    return 'id'


def _codes(s):
    return sorted(set(re.findall(r'\d{4,}', digits_keep_sep(s))))


def digits_keep_sep(s):
    return str(s or '').translate(_AR_DIGITS)


def _nationality_from_notes(notes):
    for n in notes:
        m = re.search(r'(\S+)\s+(?:ال)?جنسي[هة]', n)
        if m:
            return m.group(1)
    return ''


def _base(kind, category, etype):
    return {'kind': kind, 'category': category, 'entity_type': etype, 'name': '', 'name_latin': '',
            'aliases': [], 'aliases_weak': [], 'national_id': '', 'id_type': '', 'passport': '', 'registration': '',
            'unified_codes': [], 'dob': '', 'pob': '', 'nationality': '', 'country': '', 'address': '',
            'occupation': '', 'owner': '', 'person_type': '', 'listings': [], 'status': 'LISTED',
            'lifted_on': '', 'lift_note': '', 'notes': [], '_rows': [], '_flags': {}}


def _register_events(sheet):
    """PP_ORDER / TERROR_REGISTER rows -> events (one per row) with an effective date."""
    evs, last_date = [], ''
    for seq, r in enumerate(sheet.rows):
        name, aliases = split_name(r.get('name'))
        if not name:
            continue
        idv = r.get('id', '')
        id_type = r.get('id_type', '')
        cls = _id_class(id_type)
        nid = valid_nid(idv) if not r.get('id_is_date') else ''
        dob = ''
        if r.get('id_is_date') or cls == 'dob':
            dob = first_date(idv)
            if len(dob) != 10:
                dob = ''
        d = first_date(r.get('received')) or first_date(r.get('letter_date'))
        if len(d) != 10:
            d = ''
        eff = d or last_date
        last_date = eff or last_date
        ptype = norm(r.get('person_type'))
        is_entity = ('اعتبار' in ptype) or (cls == 'cr' and not nid) or bool(r.get('owner')) or \
            (not nid and name_key(name).split(' ')[0] in {name_key(w) for w in _ENTITY_WORDS})
        notes = [one_line(n) for n in (r.get('notes'),) if one_line(n)]
        st = r.get('status', '')
        lift = is_lift(st)
        if sheet.kind == 'TERROR_REGISTER' and st and not lift:
            notes.append(one_line(st))
        evs.append({
            'seq': seq, 'row': r['_row'], 'date': eff, 'raw_date': d, 'lift': lift, 'status_text': one_line(st),
            'name': name, 'aliases': aliases, 'nk': name_key(name), 'nid': nid,
            'id_raw': '' if (nid or dob) else one_line(idv), 'id_class': cls, 'id_type': one_line(id_type), 'dob': dob,
            'codes': _codes(r.get('code')), 'order': _ref(r.get('order_no'), r.get('order_year')),
            'ok': _order_key(r.get('order_no'), r.get('order_year')),
            'case': _ref(r.get('case_no'), r.get('case_year')), 'ck': _order_key(r.get('case_no'), r.get('case_year')),
            'letter': _ref(r.get('letter_no'), r.get('letter_date') if len(first_date(r.get('letter_date'))) != 10
                           else first_date(r.get('letter_date'))),
            'person_type': one_line(r.get('person_type')), 'entity': is_entity, 'notes': notes,
            'owner': one_line(r.get('owner')), 'address': one_line(r.get('address')),
            'occupation': one_line(r.get('occupation')),
        })
    return evs


def _assign_identities(evs, prefix):
    """Event -> identity key (see the module docstring)."""
    by_code, by_name_order, by_name_case = {}, {}, {}

    def remember(e, key):
        for c in e['codes']:
            by_code.setdefault(c, key)
        if e['ok']:
            by_name_order.setdefault((e['nk'], e['ok']), key)
        if e['ck']:
            by_name_case.setdefault((e['nk'], e['ck']), key)
    for e in evs:
        if e['nid']:
            e['key'] = f'{prefix}|nid:{e["nid"]}'
            remember(e, e['key'])
    for e in evs:
        if e.get('key'):
            continue
        key = None
        for c in e['codes']:
            if c in by_code:
                key = by_code[c]
                break
        key = key or (by_name_order.get((e['nk'], e['ok'])) if e['ok'] else None) \
            or (by_name_case.get((e['nk'], e['ck'])) if e['ck'] else None)
        if not key:
            idd = digits(e['id_raw'])
            if len(idd) >= 5:
                key = f'{prefix}|{e["id_class"]}:{idd}'
            elif e['codes']:
                key = f'{prefix}|uc:{e["codes"][0]}'
            else:
                key = f'{prefix}|nm:{e["nk"]}' + (f'|dob:{e["dob"]}' if e['dob'] else '')
        e['key'] = key
        remember(e, key)
    return evs


def _register_records(sheet):
    prefix = KEY_PREFIX[sheet.kind]
    evs = _assign_identities(_register_events(sheet), prefix)
    groups = {}
    for e in evs:
        groups.setdefault(e['key'], []).append(e)
    out = []
    for key, es in groups.items():
        es.sort(key=lambda x: (x['date'] or '', x['seq']))
        entity = sum(1 for e in es if e['entity']) * 2 > len(es) or all(e['entity'] for e in es)
        if sheet.kind == 'PP_ORDER':
            cat = 'EG_FREEZE_ORDER'
        else:
            cat = 'EG_TERROR_ENTITIES' if entity else 'EG_TERROR_PERSONS'
        rec = _base(sheet.kind, cat, 'ENTITY' if entity else 'INDIVIDUAL')
        rec['key'] = key
        orders = {}         # order key -> state
        unmatched = 0
        for e in es:
            ok = e['ok'] or (('c:' + e['ck']) if e['ck'] else '_')
            if not e['lift']:
                o = orders.setdefault(ok, {'order': e['order'], 'case': e['case'], 'ck': e['ck'], 'state': 'IN_FORCE',
                                           'since': e['date'], 'lifted_on': '', 'letters': set()})
                if o['state'] == 'LIFTED':
                    o['state'], o['lifted_on'], o['relisted_on'] = 'IN_FORCE', '', e['date']
                if e['letter']:
                    o['letters'].add(e['letter'])
                continue
            target = orders.get(ok)
            if target is None and e['ck']:
                same_case = [o for o in orders.values() if o['ck'] == e['ck']]
                target = same_case[0] if len(same_case) == 1 else None
            if target is None:
                live = [o for o in orders.values() if o['state'] == 'IN_FORCE']
                if len(live) == 1:
                    target = live[0]
                elif not live:
                    target = orders.setdefault(ok, {'order': e['order'], 'case': e['case'], 'ck': e['ck'],
                                                    'state': 'IN_FORCE', 'since': '', 'lifted_on': '',
                                                    'letters': set()})
                else:
                    unmatched += 1
                    continue
            target['state'], target['lifted_on'] = 'LIFTED', e['date']
            target['lift_text'] = e['status_text']
            if e['letter']:
                target['letters'].add(e['letter'])
        live_names = [e for e in es if not e['lift']] or es
        latest = live_names[-1]
        rec['name'] = latest['name']
        names = []
        for e in es:
            names.append(e['name'])
            names.extend(e['aliases'])
        rec['aliases'] = sorted({a for a in names if name_key(a) and name_key(a) != name_key(rec['name'])})
        nid = next((e['nid'] for e in reversed(es) if e['nid']), '')
        rec['national_id'] = nid
        rec['id_type'] = next((e['id_type'] for e in reversed(es) if (e['nid'] or e['id_raw']) and e['id_type']), '')
        other = next((e for e in reversed(es) if e['id_raw']), None)
        if other and not nid:
            if other['id_class'] == 'pp':
                rec['passport'] = other['id_raw']
            elif other['id_class'] == 'cr' or rec['entity_type'] == 'ENTITY':
                rec['registration'] = other['id_raw']
            else:
                rec['national_id'] = other['id_raw']
        rec['dob'] = nid_dob(nid) if nid else next((e['dob'] for e in reversed(es) if e['dob']), '')
        rec['unified_codes'] = sorted({c for e in es for c in e['codes']})
        rec['person_type'] = latest['person_type']
        for f in ('owner', 'address', 'occupation'):
            rec[f] = next((e[f] for e in reversed(es) if e[f]), '')
        rec['notes'] = sorted({n for e in es for n in e['notes']})
        rec['nationality'] = _nationality_from_notes(rec['notes'])
        rec['listings'] = sorted(({'order': o['order'], 'case': o['case'], 'state': o['state'],
                                   'since': o['since'], 'lifted_on': o['lifted_on'],
                                   'letters': sorted(o['letters'])} for o in orders.values()),
                                 key=lambda x: (x['since'] or '', x['order'], x['case']))
        live = [o for o in orders.values() if o['state'] == 'IN_FORCE']
        if live:
            rec['status'] = 'LISTED'
        else:
            rec['status'] = 'LIFTED'
            last = max(orders.values(), key=lambda o: o['lifted_on'] or '') if orders else {}
            rec['lifted_on'] = last.get('lifted_on', '')
            rec['lift_note'] = last.get('lift_text', '') or 'إنهاء أثر'
        rec['_rows'] = [e['row'] for e in es]
        if unmatched:
            rec['_flags']['lift_unmatched'] = unmatched
        out.append(rec)
    return out


def _fiu_person_records(sheet):
    groups = {}
    for r in sheet.rows:
        name, aliases = split_name(r.get('name'))
        if not name:
            continue
        nk = name_key(name)
        idv = r.get('id', '')
        dob = ''
        masked = ''
        if r.get('id_is_date') or (re.search(r'[؀-ۿA-Za-z]', idv) and find_dates(idv)):
            dob = first_date(idv)
        elif idv:
            masked = one_line(idv)
        vis = digits(masked)
        full = valid_nid(masked) if '*' not in masked else ''
        pp = one_line(r.get('passport'))
        case = one_line(r.get('case'))
        if full:
            key = f'FP|nid:{full}'
        elif vis:
            key = f'FP|m:{vis}|{nk}'
        elif pp:
            key = f'FP|pp:{digits(pp) or norm(pp)}|{nk}'
        elif dob:
            key = f'FP|nm:{nk}|dob:{dob}'
        else:
            key = f'FP|nm:{nk}|c:{norm(case)}'
        rec = groups.get(key)
        if rec is None:
            rec = _base('FIU_PERSONS', 'EG_TERROR_PERSONS', 'INDIVIDUAL')
            rec['key'], rec['name'] = key, name
            groups[key] = rec
        rec['aliases'] = sorted(set(rec['aliases']) | set(aliases) | set(split_aliases(r.get('alias'))))
        rec['national_id'] = rec['national_id'] or full or masked
        rec['dob'] = rec['dob'] or (nid_dob(full) if full else dob)
        rec['passport'] = rec['passport'] or pp
        rec['nationality'] = rec['nationality'] or one_line(r.get('nationality'))
        dates = find_dates(r.get('pub_date'))
        rec['listings'].append({'case': case, 'decision': one_line(r.get('decision')),
                                'published': [d for d in dates if len(d) == 10],
                                'publication': one_line(r.get('pub_issue')),
                                'note': ' '.join(w for w in re.split(r'\s+', norm(r.get('pub_date')))
                                                 if not re.search(r'\d', w))})
        rec['_rows'].append(r['_row'])
    for rec in groups.values():
        rec['aliases'] = [a for a in rec['aliases'] if name_key(a) != name_key(rec['name'])]
        rec['listings'].sort(key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    return list(groups.values())


def _fiu_entity_records(sheet):
    groups = {}
    for r in sheet.rows:
        name, aliases = split_name(r.get('name'))
        if not name:
            continue
        key = f'{KEY_PREFIX[sheet.kind]}|nm:{name_key(name)}'
        rec = groups.get(key)
        if rec is None:
            rec = _base(sheet.kind, 'EG_TERROR_ENTITIES', 'ENTITY')
            rec['key'], rec['name'] = key, name
            groups[key] = rec
        extra = [one_line(r.get('name_en')), one_line(r.get('name_foreign'))]
        rec['aliases'] = sorted({a for a in rec['aliases'] + aliases + [x for x in extra if x]
                                 if name_key(a) != name_key(name)})
        if r.get('name_en'):
            rec['name_latin'] = rec['name_latin'] or one_line(r.get('name_en'))
        rec['country'] = rec['country'] or one_line(r.get('country'))
        rec['registration'] = rec['registration'] or one_line(r.get('registration'))
        rec['address'] = rec['address'] or one_line(r.get('address'))
        rec['listings'].append({'case': one_line(r.get('case')), 'publication': one_line(r.get('gazette')),
                                'updates': one_line(r.get('updates'))})
        rec['_rows'].append(r['_row'])
    for rec in groups.values():
        rec['listings'].sort(key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    return list(groups.values())


def _un_category(sheet, ref):
    m = re.match(r'([A-Za-z]{2})[A-Za-z]?\s*\.', ref or '')
    if m and m.group(1).upper() in UN_PREFIX:
        return UN_PREFIX[m.group(1).upper()]
    text = norm(f'{sheet.name} {sheet.title}')
    for hint, code in UN_TITLE_HINTS:
        if norm(hint) in text:
            return code
    return 'UN_OTHER'


def _un_records(sheet):
    out = {}
    for r in sheet.rows:
        ref = re.sub(r'\s+', '', one_line(r.get('ref'))).upper()
        latin = one_line(' '.join(r.get('name_parts') or []))
        official = one_line(r.get('official'))
        if not (latin or official):
            continue
        m = re.match(r'[A-Z]{2}([IE])\.', ref)
        if m:
            etype = 'ENTITY' if m.group(1) == 'E' else 'INDIVIDUAL'
        else:
            pt = norm(r.get('party_type'))
            etype = 'ENTITY' if ('كيان' in pt or 'جماع' in pt) else 'INDIVIDUAL'
        cat = _un_category(sheet, ref)
        rec = _base('UN', cat, etype)
        rec['key'] = f'UN|ref:{ref}' if ref else f'UN|nm:{name_key(latin or official)}'
        if official and AR.search(official):
            rec['name'], rec['name_latin'] = official, latin
        else:
            rec['name'], rec['name_latin'] = latin or official, latin or official
            if official and latin and name_key(official) != name_key(latin):
                rec['aliases'].append(official)
        rec['aliases'] = sorted(set(rec['aliases'] + split_aliases(r.get('alias_good'))))
        rec['aliases_weak'] = sorted(set(split_aliases(r.get('alias_low'))) - set(rec['aliases']))
        dates = find_dates(r.get('dob'))
        rec['dob'] = next((d for d in dates if len(d) == 10), dates[0] if dates else '')
        if len(dates) > 1:
            rec['notes'].append('DOB: ' + one_line(r.get('dob')))
        rec['pob'] = one_line(r.get('pob'))
        rec['nationality'] = one_line(r.get('nationality'))
        rec['passport'] = one_line(r.get('passport'))
        rec['national_id'] = one_line(r.get('nid'))
        rec['address'] = one_line(r.get('address'))
        rec['listings'] = [{'ref': ref, 'listed': one_line(r.get('listed'))}]
        info = one_line(r.get('info'))
        if info:
            rec['notes'].append(info)
        rec['_rows'] = [r['_row']]
        if rec['key'] in out:          # the same reference twice: keep both name forms
            prev = out[rec['key']]
            prev['aliases'] = sorted(set(prev['aliases']) | {rec['name']} | set(rec['aliases'])
                                     - {prev['name']})
            prev['_rows'] += rec['_rows']
            continue
        out[rec['key']] = rec
    return list(out.values())


BUILDERS = {'PP_ORDER': _register_records, 'TERROR_REGISTER': _register_records,
            'FIU_PERSONS': _fiu_person_records, 'FIU_ENTITIES': _fiu_entity_records,
            'FIU_LEGAL': _fiu_entity_records, 'UN': _un_records}

HASH_EXCLUDE = ('key', '_rows', '_flags', '_sheet', '_dob_linked')


def content_of(rec):
    """The part of a record that a change is measured on (source fields only, no derived spellings)."""
    return {k: v for k, v in rec.items() if k not in HASH_EXCLUDE}


def content_sha(rec):
    return hashlib.sha256(json.dumps(content_of(rec), sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def record_key(rec):
    """Stored identity: kind prefix + hash of the identity string (no ID number in clear in the key)."""
    raw = rec['key']
    return raw.split('|', 1)[0] + ':' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def parse(path):
    """Read and build: {'sheets': [summary], 'records': [record], 'date': edition date, 'unknown': [...]}.
    Two sheets of the same kind (e.g. the UN Iran persons and entities) are merged; a record key met in two
    sheets keeps the first and counts a duplicate."""
    sheets = read_workbook(path)
    records, seen, summaries, unknown = [], {}, [], []
    for sh in sheets:
        if not sh.kind:
            summaries.append({'sheet': sh.name, 'kind': None, 'rows': sh.rows_read, 'records': 0,
                              'looks_like_data': bool(getattr(sh, 'looks_like_data', False))})
            if getattr(sh, 'looks_like_data', False) and getattr(sh, 'labels', None) is not None:
                unknown.append(sh.name)
            continue
        recs = BUILDERS[sh.kind](sh)
        dup = 0
        cats = {}
        for rec in recs:
            rec['_sheet'] = sh.name
            rec['_flags'] = rec.get('_flags') or {}
            k = record_key(rec)
            rec['record_key'] = k
            if k in seen:
                dup += 1
                continue
            seen[k] = rec
            records.append(rec)
            c = cats.setdefault(rec['category'], {'records': 0, 'listed': 0, 'lifted': 0, 'persons': 0,
                                                  'entities': 0})
            c['records'] += 1
            c['listed' if rec['status'] == 'LISTED' else 'lifted'] += 1
            c['persons' if rec['entity_type'] == 'INDIVIDUAL' else 'entities'] += 1
        summaries.append({'sheet': sh.name, 'kind': sh.kind, 'rows': sh.rows_read, 'data_rows': len(sh.rows),
                          'skipped_rows': sh.skipped, 'records': sum(c['records'] for c in cats.values()),
                          'duplicates': dup, 'categories': cats,
                          'lift_unmatched': sum(r['_flags'].get('lift_unmatched', 0) for r in recs),
                          'missing_columns': sorted(f for f, _p in FIELDS[sh.kind]
                                                    if f not in sh.columns and f not in ('file_ref', 'serial'))})
    for rec in records:
        rec.pop('record_key', None)
    return {'sheets': summaries, 'records': records, 'date': workbook_date(sheets), 'unknown': unknown}


__all__ = ['parse', 'record_key', 'content_sha', 'content_of', 'CATEGORIES', 'KINDS', 'KIND_LABEL', 'norm',
           'name_key', 'split_name', 'find_dates', 'valid_nid', 'detect_kind', 'is_lift']
