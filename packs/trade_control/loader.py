# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Download, parse, version and load the control lists (shared by the command line importer
scripts/dualuse/import_lists.py, the scheduled check and the superadmin upload page).

Every load goes through the same steps whatever the source (download or uploaded file):
parse -> safety checks (minimum records, no shrink of more than 40 %) -> content digest (an unchanged list is
skipped) -> diff against the current version (entries added / removed / changed, thresholds changed) ->
a new version made current. Past versions stay, so a past screening can be replayed.

EUR-Lex answers automated clients with an empty "bot check" page (HTTP 202): the EU texts are read from the
Publications Office CELLAR service instead (https://publications.europa.eu/resource/celex/<CELEX>, XHTML),
and the newest consolidated version is found with the CELLAR SPARQL endpoint. A blocked or empty answer is
reported as such ("source blocked automated download - upload the file manually").
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import tempfile

from . import parsers as P
from . import text as T

UA = {'User-Agent': os.getenv('DUALUSE_USER_AGENT', 'Mozilla/5.0 (compatible; ControlListsImporter/1.0)')}

LISTS = {   # code: (legal name - internal only, kind, order)
    'eu_annex1': ('EU Dual-Use Regulation (EU) 2021/821, Annex I', 'control', 10),
    'us_ccl': ('US Commerce Control List (EAR Part 774, Supplement No. 1)', 'control', 20),
    'cwc': ('Chemical Weapons Convention, Annex on Chemicals (Schedules 1-3)', 'control', 30),
    'chemicals': ('Chemicals register by CAS (CWC, Australia Group via EU 1C350, EU and US lists)', 'chemicals', 40),
    'eu_cn_correlation': ('EU dual-use / Combined Nomenclature correlation table', 'hs_map', 50),
    'chpl': ('List of Common High Priority Items', 'priority', 60),
    'eu_expl_precursors': ('EU Regulation (EU) 2019/1148 on explosives precursors, Annexes I and II', 'control', 70),
}
ORDER = ['eu_annex1', 'us_ccl', 'cwc', 'eu_cn_correlation', 'chpl', 'eu_expl_precursors']
# lists a superadmin may load from an uploaded file: (accepted extensions, what to upload)
UPLOADABLE = {
    'eu_annex1': (('.html', '.htm', '.xhtml', '.xml'),
                  'Consolidated text of Regulation (EU) 2021/821 (XHTML / HTML from EUR-Lex or CELLAR)'),
    'eu_cn_correlation': (('.xlsx',), 'Dual-use / CN correlation table (XLSX)'),
    'chpl': (('.pdf',), 'List of Common High Priority Items (PDF)'),
    'eu_expl_precursors': (('.html', '.htm', '.xhtml', '.xml'),
                           'Regulation (EU) 2019/1148 (XHTML / HTML from EUR-Lex or CELLAR)'),
}
MAX_UPLOAD = 20 * 1024 * 1024
MAX_DOWNLOAD = 60 * 1024 * 1024        # the largest list (US CCL XML) is about 10 MB

CELLAR = 'https://publications.europa.eu/resource/celex/%s'
SPARQL = 'https://publications.europa.eu/webapi/rdf/sparql'
DEFAULT_URLS = {
    'eu_annex1': os.getenv('DUALUSE_EU_URL', ''),
    'eu_cn_correlation': os.getenv('DUALUSE_CORR_URL',
                                   'https://circabc.europa.eu/rest/download/8dd0feca-0b12-494e-9ad3-a1a5565e56ad'),
    'chpl': os.getenv('DUALUSE_CHPL_URL', 'https://finance.ec.europa.eu/document/download/'
                      '5a2494db-d874-4e2b-bf2a-ec5a191d2dc0_en?filename=list-common-high-priority-items_en.pdf'),
    'cwc': 'https://www.opcw.org/chemical-weapons-convention/annexes/annex-chemicals/schedule-%d',
    'us_ccl': 'https://www.ecfr.gov/api/versioner/v1/full/%s/title-15.xml?part=774',
    'eu_expl_precursors': os.getenv('DUALUSE_PRECURSORS_URL', ''),
}
# CELEX prefix of the consolidated versions, and the act used when no consolidation is found
CELEX = {'eu_annex1': ('02021R0821', '32025R2003'), 'eu_expl_precursors': ('02019R1148', '32019R1148')}
FILES = {'eu_annex1': 'eu_annex1.html', 'eu_cn_correlation': 'eu_cn_correlation.xlsx', 'chpl': 'chpl.pdf',
         'cwc': 'cwc_s%d.html', 'us_ccl': 'us_ccl.xml', 'eu_expl_precursors': 'eu_expl_precursors.html'}
MIN_RECORDS = {'eu_annex1': 300, 'us_ccl': 300, 'cwc': 20, 'eu_expl_precursors': 10}


class SourceBlocked(RuntimeError):
    """The publisher answered an automated download with a challenge / empty page."""


# ------------------------------------------------------------------ risk
def risk_eu(code):
    """Category 0 (nuclear) and the non-proliferation regimes (third digit 1 = missiles, 2 = nuclear dual-use,
    3 = chemical / biological, 4 = chemical-weapons chemicals) are high; the rest is medium."""
    if code[0] == '0' or (len(code) >= 3 and code[2] in '1234'):
        return 'high'
    return 'medium'


def risk_us(code, reasons, series_600, series_500):
    r = set(reasons or [])
    if series_600 or series_500 or r & {'NP', 'CB', 'CW', 'MT'}:
        return 'high'
    if r and r <= {'AT', 'UN', 'RS'} and code[2] == '9':
        return 'low'
    return 'medium'


# ------------------------------------------------------------------ download
def check_answer(url, status, data, content_type=''):
    """Raise SourceBlocked on a bot check / challenge / empty answer (EUR-Lex: HTTP 202 with an empty body)."""
    host = re.sub(r'^https?://([^/]+).*$', r'\1', url or '')
    head = (data or b'')[:4000].lower()
    if status == 202 or not data or len(data) < 256 or b'awswaf' in head or b'challenge-platform' in head \
            or b'captcha' in head or b'<title>just a moment' in head:
        raise SourceBlocked('%s blocked the automated download (HTTP %s, %d bytes, %s) - upload the file manually '
                            'on the list update page' % (host, status, len(data or b''), content_type or 'no type'))


def fetch(url, timeout=120, accept=None):
    import requests
    h = dict(UA)
    if accept:
        h['Accept'] = accept
    if 'publications.europa.eu' in url:
        h['Accept-Language'] = 'eng'       # CELLAR answers 400 without a language
    with requests.get(url, headers=h, timeout=timeout, stream=True) as r:
        ctype = r.headers.get('Content-Type', '')
        n = r.headers.get('Content-Length')
        if n and n.isdigit() and int(n) > MAX_DOWNLOAD:
            raise RuntimeError('%s: answer of %s bytes is larger than the %d MB limit' % (url, n, MAX_DOWNLOAD >> 20))
        buf = bytearray()
        for chunk in r.iter_content(1 << 16):
            buf += chunk
            if len(buf) > MAX_DOWNLOAD:
                raise RuntimeError('%s: answer larger than the %d MB limit - stopped' % (url, MAX_DOWNLOAD >> 20))
        data = bytes(buf)
        if r.status_code == 202 or (r.ok and not data):
            check_answer(url, r.status_code, data, ctype)
        r.raise_for_status()
    check_answer(url, r.status_code, data, ctype)
    return data


def latest_celex(prefix):
    """Newest CELEX number starting with `prefix` (a consolidated version '02021R0821-YYYYMMDD'), from the
    CELLAR SPARQL endpoint; None when nothing matches."""
    import requests
    q = ('PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> SELECT DISTINCT ?celex WHERE { '
         '?w cdm:resource_legal_id_celex ?celex . FILTER(STRSTARTS(STR(?celex), "%s")) } '
         'ORDER BY DESC(?celex) LIMIT 1' % prefix)
    r = requests.get(SPARQL, params={'query': q}, headers=dict(UA, Accept='application/sparql-results+json'),
                     timeout=60, stream=True)
    r.raise_for_status()
    raw = r.raw.read(1 << 20, decode_content=True)          # a one-row answer: 1 MB is plenty
    r.close()
    b = json.loads(raw or b'{}').get('results', {}).get('bindings') or []
    return b[0]['celex']['value'] if b else None


def latest_ecfr_date():
    data = json.loads(fetch('https://www.ecfr.gov/api/versioner/v1/versions/title-15.json?part=774', 60))
    return max(v['date'] for v in data['content_versions'])


def pdf_text(raw):
    """(text, how): pdftotext when installed, else the built-in reader."""
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(raw)
        f.flush()
        try:
            return subprocess.run(['pdftotext', '-layout', f.name, '-'], capture_output=True, timeout=120,
                                  check=True).stdout.decode('utf-8', 'replace'), 'pdftotext'
        except Exception:
            pass
    try:
        from .pdftext import text_layout
        return text_layout(raw), 'built-in PDF reader'
    except Exception:
        return None, None


def get_raw(code, from_dir=None, raw_dir=None, log=print):
    """-> (bytes or {n: bytes}, version_label, url)."""
    def local(name):
        p = os.path.join(from_dir, name)
        return open(p, 'rb').read() if os.path.exists(p) else None

    def keep(name, data):
        if raw_dir:
            os.makedirs(raw_dir, exist_ok=True)
            with open(os.path.join(raw_dir, name), 'wb') as f:
                f.write(data)

    if code == 'cwc':
        pages = {}
        for n in (1, 2, 3):
            data = local(FILES['cwc'] % n) if from_dir else fetch(DEFAULT_URLS['cwc'] % n)
            if data is None:
                raise RuntimeError('missing ' + FILES['cwc'] % n)
            keep(FILES['cwc'] % n, data)
            pages[n] = data
        return pages, 'OPCW schedules as published', DEFAULT_URLS['cwc'] % 1
    if code == 'us_ccl':
        if from_dir:
            lab = local(FILES['us_ccl'] + '.label')      # optional: the eCFR date the file was taken on
            data, label, url = local(FILES['us_ccl']), (lab.decode().strip() if lab else 'from file'), 'file'
            if data is None:
                raise RuntimeError('missing ' + FILES['us_ccl'])
        else:
            d = latest_ecfr_date()
            url = DEFAULT_URLS['us_ccl'] % d
            data, label = fetch(url, 300), 'eCFR as of %s' % d
        keep(FILES['us_ccl'], data)
        return data, label, url
    if code in CELEX and not from_dir:
        url = DEFAULT_URLS.get(code)
        if not url:
            prefix, act = CELEX[code]
            try:
                celex = latest_celex(prefix) or act
            except Exception as e:
                log('%s: consolidated versions not found on CELLAR (%s) - using %s' % (code, e, act))
                celex = act
            url = CELLAR % celex
        data = fetch(url, 300, accept='application/xhtml+xml, text/html;q=0.9')
        keep(FILES[code], data)
        return data, None, url
    url = DEFAULT_URLS[code]
    data = local(FILES[code]) if from_dir else fetch(url, 180)
    if data is None:
        raise RuntimeError('missing ' + FILES[code])
    keep(FILES[code], data)
    return data, None, url


def content_digest(records):
    """SHA-256 of the parsed records (stable across downloads of an unchanged list)."""
    return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


# ------------------------------------------------------------------ parse -> normalised records
def _param(name, op, value, unit, raw):
    return {'parameter': name, 'operator': op, 'value': value, 'unit': unit, 'raw': raw,
            'upper_op': None, 'upper_value': None, 'upper_unit': None, 'role': 'control'}


def precursor_items(recs):
    items = []
    for r in recs:
        restricted = r['annex'] == 'I'
        code = 'XP-%s.%s' % (r['annex'], r['cas'])
        hs = sorted({c[:6] for c in r['cn'] if not c.startswith('382499')})   # 3824 99 = broad residual codes
        if restricted:
            an = 'nitrogen' in (r['limit_text'] or '').lower()
            pname = 'nitrogen content (w/w)' if an else 'concentration (w/w)'
            text = ('Restricted explosives precursor: %s (CAS %s). Not to be made available to, introduced, '
                    'possessed or used by members of the general public above the limit value (%s). Upper limit '
                    'value for a licence: %s.' % (r['name'], r['cas'], r['limit_text'] or '-', r['upper_text'] or '-'))
            params = [_param(pname, '>', r['limit'], '%', r['limit_text'])] if r['limit'] is not None else []
        else:
            text = ('Reportable explosives precursor: %s (CAS %s). Suspicious transactions, significant '
                    'disappearances and thefts are reported within 24 hours.' % (r['name'], r['cas']))
            params = []
            if 'powder' in r['name'].lower():
                params = [_param('particle size', '<', 200.0, 'µm', 'particle size less than 200 µm'),
                          _param('metal content (w/w)', '>=', 70.0, '%', '70 % w/w or more')]
        if r['notes']:
            text += ' ' + ' '.join(r['notes'])
        items.append({'code': code, 'parent_code': None, 'entry_code': code, 'level': 0, 'category': '1', 'grp': 'C',
                      'title_en': r['name'], 'text_en': text, 'notes_en': r['notes'], 'reasons': [],
                      'not_used': False, 'risk_level': 'high' if restricted else 'medium',
                      'extra': {'cas': [r['cas']], 'annex': r['annex'], 'cn': r['cn'], 'hs': hs,
                                'regime': 'explosives_precursors', 'complete': bool(params) and restricted,
                                'limit_text': r['limit_text'], 'upper_text': r['upper_text']},
                      'params': params})
    return items


def build_items(code, data):
    """-> (items, hs_rows, version_label). Items: dicts for dualuse_items + 'params'."""
    if code == 'eu_annex1':
        txt = data.decode('utf-8', 'replace')
        recs = P.parse_eu_annex1(txt)
        items = [{'code': r['code'], 'parent_code': r['parent'], 'entry_code': r['entry'],
                  'level': r['level'], 'category': r['category'], 'grp': r['group'],
                  'title_en': r['text_en'][:300] if r['level'] == 0 else None, 'text_en': r['text_en'],
                  'notes_en': r.get('notes_en') or [], 'reasons': [], 'not_used': r['not_used'],
                  'risk_level': risk_eu(r['code']), 'extra': {'cas': r['cas_numbers']},
                  'params': r['parameters']} for r in recs]
        c = re.search(r'02021R0821\s*\W+\s*EN\s*\W+\s*(\d{2})\.(\d{2})\.(\d{4})', txt)
        if c:
            return items, [], 'Annex I, consolidated text of %s-%s-%s' % (c.group(3), c.group(2), c.group(1))
        m = re.search(r'Delegated Regulation \(EU\) (\d{4}/\d+)', txt)
        return items, [], ('Annex I as replaced by Delegated Regulation (EU) %s' % m.group(1) if m else 'Annex I')
    if code == 'eu_expl_precursors':
        txt = data.decode('utf-8', 'replace')
        items = precursor_items(P.parse_expl_precursors(txt))
        c = re.search(r'02019R1148\s*\W+\s*EN\s*\W+\s*(\d{2})\.(\d{2})\.(\d{4})', txt)
        return items, [], ('Regulation (EU) 2019/1148, consolidated text of %s-%s-%s' % (
            c.group(3), c.group(2), c.group(1)) if c else 'Regulation (EU) 2019/1148, Annexes I and II')
    if code == 'us_ccl':
        recs = P.parse_ccl(data.decode('utf-8', 'replace'))
        items = []
        for r in recs:
            rl = risk_us(r['code'], r['reasons'], r['series_600'], r['series_500'])
            items.append({'code': r['code'], 'parent_code': None, 'entry_code': r['code'], 'level': 0,
                          'category': r['category'], 'grp': r['group'], 'title_en': r['title_en'][:500],
                          'text_en': r['items_text_en'] or r['title_en'], 'notes_en': r.get('notes_en') or [],
                          'reasons': r['reasons'], 'not_used': bool(r.get('empty')), 'risk_level': rl,
                          'extra': {'cas': r['cas_numbers'], 'category_title': r['category_title'],
                                    'series_600': r['series_600'], 'series_500': r['series_500'],
                                    'itar': bool(r.get('itar'))},
                          'params': r['parameters']})
            for s in r['sub_items']:
                items.append({'code': s['code'], 'parent_code': s['parent'], 'entry_code': r['code'],
                              'level': s['code'].count('.'), 'category': r['category'], 'grp': r['group'],
                              'title_en': None, 'text_en': s['text_en'], 'notes_en': [], 'reasons': r['reasons'],
                              'not_used': bool(s.get('not_used') or re.match(r'\[?reserved\]?', s['text_en'], re.I)),
                              'risk_level': rl, 'extra': {'cas': s['cas_numbers']}, 'params': s['parameters']})
        seen, uniq = set(), []          # sub-item codes can repeat inside notes: keep the first
        for it in items:
            if it['code'] not in seen:
                seen.add(it['code'])
                uniq.append(it)
        return uniq, [], None
    if code == 'cwc':
        recs = P.parse_cwc({n: v.decode('utf-8', 'replace') for n, v in data.items()})
        items, seen = [], set()
        for r in recs:
            c = 'S%d%s.%d' % (r['schedule'], r['part'], r['item'])
            if r['cas']:
                c += '.' + r['cas']
            if c in seen:
                continue
            seen.add(c)
            title = r['common_name_en'] or r['name_en']
            items.append({'code': c, 'parent_code': None, 'entry_code': 'S%d' % r['schedule'], 'level': 0,
                          'category': '1', 'grp': 'C', 'title_en': (title or '')[:300],
                          'text_en': ' — '.join(x for x in (r['name_en'], r['family_en']) if x),
                          'notes_en': [], 'reasons': [], 'not_used': False, 'risk_level': 'high', 'params': [],
                          'extra': {'cas': [r['cas']] if r['cas'] else [], 'schedule': r['schedule'],
                                    'part': r['part'], 'common_name': r['common_name_en']}})
        return items, [], None
    if code == 'chpl':
        txt, how = pdf_text(data)
        recs = P.parse_chpl_text(txt) if txt else []
        if len(recs) < 40:                 # unreadable PDF or a new layout: the bundled copy
            recs = P.chpl_seed()
            label = 'February 2024 (bundled copy: the PDF could not be read - %s)' % (how or 'no PDF reader')
        else:
            v = re.search(r'\(\s*Version\s+of\s+([A-Za-z]+)\s*(\d{4})\s*\)', txt)
            label = 'version of %s %s' % (v.group(1), v.group(2)) if v else 'as published'
            if how != 'pdftotext':
                # the built-in reader spaces some words badly: keep the bundled wording where code and tier agree
                seed = {(r['hs6'], r['tier']): r['description_en'] for r in P.chpl_seed()}
                for r in recs:
                    r['description_en'] = seed.get((r['hs6'], r['tier']), r['description_en'])
                label += ' (read with the %s)' % how
        hs = [{'cn10': None, 'hs6': r['hs6'], 'hs4': r['hs6'][:4], 'chapter': r['hs6'][:2], 'control_code': None,
               'resolved_code': None, 'taric_footnote': None, 'priority_tier': r['tier'],
               'description_en': r['description_en']} for r in recs]
        return [], hs, label
    raise ValueError(code)


def _pkey(p):
    def num(v):
        return None if v is None else round(float(v), 9)
    return ((p.get('parameter') or '').strip(), p.get('operator'), num(p.get('value')), p.get('unit') or None,
            p.get('upper_op') or None, num(p.get('upper_value')), p.get('role') or 'control')


def diff_items(old, new, old_params=None):
    """Entries added / removed / changed (English text), and entries whose thresholds changed."""
    o = {r['code']: r for r in old}
    n = {r['code']: r for r in new}
    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    changed = sorted(c for c in set(o) & set(n) if (o[c].get('text_en') or '') != (n[c].get('text_en') or ''))
    thr = []
    if old_params is not None:
        for c in sorted(set(o) & set(n)):
            a = sorted(str(_pkey(p)) for p in old_params.get(c, []))
            b = sorted(str(_pkey(p)) for p in n[c].get('params') or [])
            if a != b:
                thr.append(c)
    return {'added': len(added), 'removed': len(removed), 'changed': len(changed), 'thresholds_changed': len(thr),
            'added_codes': added[:500], 'removed_codes': removed[:500], 'changed_codes': changed[:500],
            'threshold_codes': thr[:500],
            'added_sample': added[:15], 'removed_sample': removed[:15], 'changed_sample': changed[:15]}


# ------------------------------------------------------------------ database
def connect(dbname=None):
    import psycopg2
    import psycopg2.extras
    from config import Config
    cfg = dict(Config.POSTGRES_CONFIG)
    if dbname:
        cfg['dbname'] = dbname
        cfg.pop('database', None)
    conn = psycopg2.connect(**cfg)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def ensure_lists(cur):
    for code, (name, kind, order) in LISTS.items():
        cur.execute("""INSERT INTO dualuse_lists (code, legal_name, kind, display_order) VALUES (%s,%s,%s,%s)
                       ON CONFLICT (code) DO UPDATE SET legal_name = EXCLUDED.legal_name, kind = EXCLUDED.kind""",
                    (code, name, kind, order))
    cur.execute("SELECT id, code FROM dualuse_lists")
    return {r['code']: r['id'] for r in cur.fetchall()}


def current_version(cur, list_id):
    cur.execute("SELECT * FROM dualuse_list_versions WHERE list_id = %s AND is_current ORDER BY id DESC LIMIT 1",
                (list_id,))
    return cur.fetchone()


def current_items(cur, list_code):
    cur.execute("""SELECT i.* FROM dualuse_items i JOIN dualuse_list_versions v ON v.id = i.version_id
                   JOIN dualuse_lists l ON l.id = v.list_id WHERE l.code = %s AND v.is_current""", (list_code,))
    return cur.fetchall()


def current_params(cur, list_code):
    cur.execute("""SELECT i.code, p.parameter, p.operator, p.value, p.unit, p.upper_op, p.upper_value, p.role
                   FROM dualuse_parameters p JOIN dualuse_items i ON i.id = p.item_id
                   JOIN dualuse_list_versions v ON v.id = i.version_id AND v.is_current
                   JOIN dualuse_lists l ON l.id = v.list_id WHERE l.code = %s""", (list_code,))
    out = {}
    for r in cur.fetchall():
        out.setdefault(r['code'], []).append(r)
    return out


def new_version(cur, list_id, label, url, digest, count, stats, diff, who):
    cur.execute("""INSERT INTO dualuse_list_versions (list_id, version_label, in_force_date, source_url, raw_sha256,
                   record_count, stats, diff, is_current, loaded_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,FALSE,%s)
                   RETURNING id""",
                (list_id, label, None, url, digest, count, json.dumps(stats), json.dumps(diff), who))
    return cur.fetchone()['id']


def make_current(cur, list_id, vid):
    cur.execute("UPDATE dualuse_list_versions SET is_current = (id = %s) WHERE list_id = %s", (vid, list_id))


def write_items(cur, vid, items, previous):
    from psycopg2.extras import execute_values
    prev = {r['code']: r for r in previous}
    rows = []
    for it in items:
        p = prev.get(it['code'])
        title_ar = text_ar = None
        ar_status, ar_at = 'none', None
        if p and (p.get('text_ar') or p.get('title_ar')):
            title_ar, text_ar, ar_at = p.get('title_ar'), p.get('text_ar'), p.get('ar_updated_at')
            ar_status = p['ar_status'] if (p.get('text_en') or '') == (it.get('text_en') or '') else 'stale'
        rows.append((vid, it['code'], it.get('parent_code'), it.get('entry_code'), it.get('level') or 0,
                     it.get('category'), it.get('grp'), it.get('title_en'), it.get('text_en'),
                     json.dumps(it.get('notes_en') or []), it.get('reasons') or [], bool(it.get('not_used')),
                     it.get('risk_level') or 'medium', title_ar, text_ar, ar_status, ar_at,
                     json.dumps(it.get('extra') or {})))
    ids = execute_values(cur, """INSERT INTO dualuse_items (version_id, code, parent_code, entry_code, level, category,
                         grp, title_en, text_en, notes_en, reasons, not_used, risk_level, title_ar, text_ar, ar_status,
                         ar_updated_at, extra) VALUES %s RETURNING id, code""", rows, page_size=500, fetch=True)
    by_code = {r['code']: r['id'] for r in ids}
    prow = []
    for it in items:
        for p in it.get('params') or []:
            if p.get('unit'):
                bv, bu = T.to_base(p.get('value'), p.get('unit'))
                ub, _ = T.to_base(p.get('upper_value'), p.get('upper_unit') or p.get('unit'))
            else:                       # a named unitless quantity ("total processing performance")
                bv, bu, ub = p.get('value'), T.UNITLESS, p.get('upper_value')
            prow.append((by_code[it['code']], p.get('parameter'), p['operator'], p.get('value'), p.get('unit'),
                         bv, bu, p.get('raw'), p.get('upper_op'), p.get('upper_value'),
                         p.get('upper_unit') or (p.get('unit') if p.get('upper_op') else None), ub,
                         p.get('role') or 'control'))
    if prow:
        execute_values(cur, """INSERT INTO dualuse_parameters (item_id, parameter, operator, value, unit, base_value,
                       base_unit, raw, upper_op, upper_value, upper_unit, upper_base, role) VALUES %s""", prow,
                       page_size=1000)
    return len(rows), len(prow)


def write_hs(cur, vid, rows):
    from psycopg2.extras import execute_values
    execute_values(cur, """INSERT INTO dualuse_hs_map (version_id, cn10, hs6, hs4, chapter, control_code, resolved_code,
                   taric_footnote, priority_tier, description_en) VALUES %s""",
                   [(vid, r.get('cn10'), r['hs6'], r.get('hs4'), r.get('chapter'), r.get('control_code'),
                     r.get('resolved_code'), r.get('taric_footnote'), r.get('priority_tier'), r.get('description_en'))
                    for r in rows], page_size=1000)


def rebuild_chemicals(cur, ids, who, apply, log=print):
    """Chemicals register from the CURRENT versions of the EU, US and CWC lists."""
    eu = [{'code': r['code'], 'text_en': r['text_en']} for r in current_items(cur, 'eu_annex1')]
    us = [{'code': r['code'], 'items_text_en': r['text_en']} for r in current_items(cur, 'us_ccl') if r['level'] == 0]
    cwc = []
    for r in current_items(cur, 'cwc'):
        x = r['extra'] or {}
        for c in x.get('cas') or [None]:
            cwc.append({'cas': c, 'schedule': x.get('schedule'), 'part': x.get('part'),
                        'item': r['code'].split('.')[1] if '.' in r['code'] else '',
                        'name_en': (r['text_en'] or '').split(' — ')[0], 'common_name_en': x.get('common_name')})
    chem = P.build_chemicals(eu, cwc, us)
    digest = hashlib.sha256(json.dumps(chem, sort_keys=True).encode()).hexdigest()
    cv = current_version(cur, ids['chemicals'])
    if cv and cv['raw_sha256'] == digest:
        log('chemicals: unchanged (%d CAS)' % len(chem))
        return {'code': 'chemicals', 'status': 'unchanged', 'records': len(chem)}
    old = {}
    if cv:
        cur.execute("SELECT cas, names_ar, ar_status FROM dualuse_chemicals WHERE version_id = %s", (cv['id'],))
        old = {r['cas']: r for r in cur.fetchall()}
    stats = {'cas': len(chem), 'ag_precursors': sum(r['ag_precursor'] for r in chem),
             'cwc_scheduled': sum(1 for r in chem if r['cwc_schedule'])}
    new = {r['cas'] for r in chem}
    added, removed = sorted(new - set(old)), sorted(set(old) - new)
    d = {'added': len(added), 'removed': len(removed), 'changed': 0, 'added_codes': added[:500],
         'removed_codes': removed[:500], 'previous': cv['record_count'] if cv else 0}
    log('chemicals: %s' % stats)
    if not apply:
        return {'code': 'chemicals', 'status': 'dry-run', 'stats': stats, 'diff': d}
    from psycopg2.extras import execute_values
    vid = new_version(cur, ids['chemicals'], 'built %s' % datetime.date.today(), None, digest, len(chem), stats, d,
                      who)
    execute_values(cur, """INSERT INTO dualuse_chemicals (version_id, cas, names_en, names_ar, cwc_schedule, ag_precursor,
                   listings, ar_status) VALUES %s""",
                   [(vid, r['cas'], r['names_en'][:12], (old.get(r['cas']) or {}).get('names_ar') or [],
                     r['cwc_schedule'], r['ag_precursor'], json.dumps(r['listings']),
                     (old.get(r['cas']) or {}).get('ar_status') or 'none') for r in chem], page_size=500)
    make_current(cur, ids['chemicals'], vid)
    return {'code': 'chemicals', 'status': 'loaded', 'version_id': vid, 'stats': stats, 'diff': d}


def _hs_diff(cur, cv, rows, key, fmt):
    old = set()
    if cv:
        cur.execute("SELECT cn10, hs6, control_code, priority_tier FROM dualuse_hs_map WHERE version_id = %s",
                    (cv['id'],))
        old = {key(r) for r in cur.fetchall()}
    new = {key(r) for r in rows}
    return {'added': len(new - old), 'removed': len(old - new), 'changed': 0,
            'added_codes': sorted(fmt % x for x in new - old)[:500],
            'removed_codes': sorted(fmt % x for x in old - new)[:500]}


def load_one(conn, ids, code, data, label=None, url=None, apply=True, who='import_lists', force=False,
             eu_codes=None, log=print):
    """Parse one list's data and load it as a new version when it changed. -> result dict
    {code, status: unchanged | loaded | dry-run | refused, message, version_id, stats, diff}."""
    cur = conn.cursor()
    cv = current_version(cur, ids[code])
    if code == 'eu_cn_correlation':
        known = eu_codes or {r['code'] for r in current_items(cur, 'eu_annex1')}
        if not known:
            return {'code': code, 'status': 'refused', 'message': 'load the EU control list first'}
        try:
            rows = P.parse_correlation(data, known)
        except Exception as e:
            return {'code': code, 'status': 'refused',
                    'message': 'the file could not be read as the correlation table (%s)' % str(e)[:120]}
        if len(rows) < 1000:
            return {'code': code, 'status': 'refused', 'message': 'only %d correlation rows read - refusing to load '
                                                                   '(wrong file or new layout)' % len(rows)}
        digest = content_digest(rows)
        if cv and cv['raw_sha256'] == digest and not force:
            return {'code': code, 'status': 'unchanged', 'version_id': cv['id'], 'records': cv['record_count']}
        stats = {'pairs': len(rows), 'cn10': len({r['cn10'] for r in rows}),
                 'resolved': sum(1 for r in rows if r['resolved_code'])}
        d = _hs_diff(cur, cv, rows, lambda r: (r['cn10'], r['control_code']), '%s -> %s')
        if not apply:
            return {'code': code, 'status': 'dry-run', 'stats': stats, 'diff': d}
        vid = new_version(cur, ids[code], label or 'as published', url, digest, len(rows), stats, d, who)
        write_hs(cur, vid, rows)
        make_current(cur, ids[code], vid)
        conn.commit()
        return {'code': code, 'status': 'loaded', 'version_id': vid, 'stats': stats, 'diff': d}
    try:
        items, hs_rows, vlabel = build_items(code, data)
    except Exception as e:
        return {'code': code, 'status': 'refused', 'message': 'the file could not be parsed (%s)' % str(e)[:160]}
    label = vlabel or label or 'as published'
    if code == 'chpl':
        digest = content_digest(hs_rows)
        if cv and cv['raw_sha256'] == digest and not force:
            return {'code': code, 'status': 'unchanged', 'version_id': cv['id'], 'records': cv['record_count'],
                    'label': cv['version_label']}
        stats = {'hs6': len(hs_rows), 'source': 'bundled copy' if 'bundled' in label else 'PDF'}
        d = _hs_diff(cur, cv, hs_rows, lambda r: (r['hs6'], r['priority_tier']), '%s (tier %s)')
        if not apply:
            return {'code': code, 'status': 'dry-run', 'stats': stats, 'diff': d, 'label': label}
        vid = new_version(cur, ids[code], label, url, digest, len(hs_rows), stats, d, who)
        write_hs(cur, vid, hs_rows)
        make_current(cur, ids[code], vid)
        conn.commit()
        return {'code': code, 'status': 'loaded', 'version_id': vid, 'stats': stats, 'diff': d, 'label': label}
    digest = content_digest(items)
    if cv and cv['raw_sha256'] == digest and not force:
        return {'code': code, 'status': 'unchanged', 'version_id': cv['id'], 'label': cv['version_label'],
                'records': cv['record_count'], 'items': items}
    minimum = MIN_RECORDS.get(code, 20)
    if len(items) < minimum:
        return {'code': code, 'status': 'refused',
                'message': 'only %d records parsed (at least %d expected) - refusing to load: the file is not the '
                           'expected text or the layout changed' % (len(items), minimum)}
    old = current_items(cur, code)
    if old and len(items) < 0.6 * len(old):
        return {'code': code, 'status': 'refused',
                'message': '%d records vs %d now - refusing a shrink of more than 40 percent' % (len(items), len(old))}
    d = diff_items(old, items, current_params(cur, code) if old else None)
    live = [i for i in items if not i['not_used']]
    stats = {'records': len(items), 'live': len(live), 'with_parameters': sum(1 for i in live if i['params']),
             'parameters': sum(len(i['params']) for i in items)}
    if not apply:
        return {'code': code, 'status': 'dry-run', 'stats': stats, 'diff': d, 'label': label, 'items': items}
    vid = new_version(cur, ids[code], label, url, digest, len(items), stats, d, who)
    write_items(cur, vid, items, old)
    make_current(cur, ids[code], vid)
    conn.commit()
    return {'code': code, 'status': 'loaded', 'version_id': vid, 'stats': stats, 'diff': d, 'label': label,
            'items': items}


# ------------------------------------------------------------------ runs (scheduled / button / command line)
def _run_log(conn, run_id, **fields):
    if not run_id:
        return
    cur = conn.cursor()
    sets = ', '.join('%s = %%s' % k for k in fields)
    vals = [json.dumps(v, default=str) if isinstance(v, (dict, list)) else v for v in fields.values()]
    try:
        cur.execute('UPDATE dualuse_update_runs SET %s WHERE id = %%s' % sets, vals + [run_id])
        conn.commit()
    except Exception:
        conn.rollback()


def start_run(conn, mode, who):
    cur = conn.cursor()
    cur.execute("""INSERT INTO dualuse_update_runs (mode, triggered_by, status) VALUES (%s, %s, 'running')
                   RETURNING id""", (mode, who))
    rid = cur.fetchone()['id']
    conn.commit()
    return rid


def run_status(results):
    if any(r['status'] == 'blocked' for r in results):
        return 'blocked'
    if any(r['status'] in ('failed', 'refused') for r in results):
        return 'failed'
    return 'ok'


def run(lists=None, apply=True, force=False, from_dir=None, raw_dir=None, who='import_lists', dbname=None,
        run_id=None, mode=None, log=print):
    """Download (or read from a folder) and load the lists. -> list of result dicts."""
    todo = lists or ORDER
    conn = connect(dbname)
    cur = conn.cursor()
    cur.execute("SELECT pg_try_advisory_lock(hashtext('dualuse_import')) AS ok")
    if not cur.fetchone()['ok']:
        conn.close()
        raise RuntimeError('another dual-use import is running')
    if mode and not run_id and apply:
        try:
            run_id = start_run(conn, mode, who)
        except Exception:
            conn.rollback()
    lines, results = [], []

    def say(msg):
        lines.append(msg)
        log(msg)
        _run_log(conn, run_id, log='\n'.join(lines)[-20000:])

    try:
        ids = ensure_lists(cur)
        conn.commit()
        eu_codes = None
        for code in todo:
            try:
                data, label, url = get_raw(code, from_dir, raw_dir, log=say)
            except SourceBlocked as e:
                results.append({'code': code, 'status': 'blocked', 'message': str(e)})
                say('%s: %s' % (code, e))
                continue
            except Exception as e:
                results.append({'code': code, 'status': 'failed', 'message': 'download failed: %s' % str(e)[:200]})
                say('%s: download failed: %s' % (code, e))
                continue
            r = load_one(conn, ids, code, data, label, url, apply, who, force, eu_codes, log=say)
            if code == 'eu_annex1' and r.get('items'):
                eu_codes = {i['code'] for i in r['items']}
            r.pop('items', None)
            r['source'] = url
            results.append(r)
            say('%s: %s %s' % (code, r['status'], r.get('message') or r.get('stats') or r.get('records') or ''))
        if any(c in todo for c in ('eu_annex1', 'us_ccl', 'cwc')):
            results.append(rebuild_chemicals(cur, ids, who, apply, log=say))
            conn.commit()
        _run_log(conn, run_id, status=run_status(results), finished_at=datetime.datetime.now(), summary=results)
    except Exception as e:
        conn.rollback()
        _run_log(conn, run_id, status='failed', finished_at=datetime.datetime.now(), summary=results,
                 log='\n'.join(lines + ['error: %s' % e])[-20000:])
        raise
    finally:
        conn.close()
    return results


def load_uploaded(code, data, filename, who, dbname=None, log=print):
    """A superadmin's uploaded source file -> the same parse, safety checks, diff and versioned load."""
    if code not in UPLOADABLE:
        return {'code': code, 'status': 'refused', 'message': 'this list cannot be uploaded'}
    exts, _ = UPLOADABLE[code]
    if not (filename or '').lower().endswith(exts):
        return {'code': code, 'status': 'refused', 'message': 'expected a %s file' % ' / '.join(exts)}
    if len(data or b'') > MAX_UPLOAD:
        return {'code': code, 'status': 'refused', 'message': 'the file is larger than 20 MB'}
    try:
        check_answer('upload', 200, data)
    except SourceBlocked:
        return {'code': code, 'status': 'refused', 'message': 'the file is empty or is a challenge page, not the text'}
    conn = connect(dbname)
    cur = conn.cursor()
    try:
        cur.execute("SELECT pg_try_advisory_lock(hashtext('dualuse_import')) AS ok")
        if not cur.fetchone()['ok']:
            return {'code': code, 'status': 'refused', 'message': 'another update is running: try again in a minute'}
        ids = ensure_lists(cur)
        conn.commit()
        name = os.path.basename(filename)[:120]
        r = load_one(conn, ids, code, data, 'uploaded file %s' % name[:80], 'upload:%s' % name, True, who, False,
                     log=log)
        r.pop('items', None)
        if code == 'eu_annex1' and r['status'] == 'loaded':
            r['chemicals'] = rebuild_chemicals(cur, ids, who, True, log=log)
            conn.commit()
        try:
            rid = start_run(conn, 'upload', who)
            _run_log(conn, rid, status=run_status([r]), finished_at=datetime.datetime.now(), summary=[r],
                     log='%s: %s (%s)' % (code, r['status'], name))
        except Exception:
            conn.rollback()
        return r
    finally:
        conn.close()
