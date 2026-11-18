#!/usr/bin/env python3
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
"""Download, parse, version and load the dual-use control lists.

    python scripts/dualuse/import_lists.py                       # dry run: download, parse, show the diff
    python scripts/dualuse/import_lists.py --apply               # load every list that changed
    python scripts/dualuse/import_lists.py --list us_ccl --apply # one list
    python scripts/dualuse/import_lists.py --from-dir DIR        # use files already downloaded (same names)

Idempotent: a list whose downloaded file has the same SHA-256 as the current version is skipped
(--force reloads it). Each load is a new version; the previous one stays for replaying past
screenings. Arabic texts are carried over to the new version (marked 'stale' when the English
text changed). Run with the application's .env loaded (set -a; . .env; set +a).
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from packs.trade_control import parsers as P     # noqa: E402
from packs.trade_control import text as T        # noqa: E402

UA = {'User-Agent': os.getenv('DUALUSE_USER_AGENT', 'Mozilla/5.0 (compatible; ControlListsImporter/1.0)')}

LISTS = {   # code: (legal name - internal only, kind, order)
    'eu_annex1': ('EU Dual-Use Regulation (EU) 2021/821, Annex I', 'control', 10),
    'us_ccl': ('US Commerce Control List (EAR Part 774, Supplement No. 1)', 'control', 20),
    'cwc': ('Chemical Weapons Convention, Annex on Chemicals (Schedules 1-3)', 'control', 30),
    'chemicals': ('Chemicals register by CAS (CWC, Australia Group via EU 1C350, EU and US lists)', 'chemicals', 40),
    'eu_cn_correlation': ('EU dual-use / Combined Nomenclature correlation table', 'hs_map', 50),
    'chpl': ('List of Common High Priority Items', 'priority', 60),
}
EURLEX = 'https://eur-lex.europa.eu/legal-content/EN/'
DEFAULT_URLS = {
    # Annex I: the newest CONSOLIDATED text of Regulation (EU) 2021/821, which carries every amending act and
    # corrigendum (an amending act alone misses later corrigenda). The date is discovered on EUR-Lex;
    # DUALUSE_EU_URL forces a given document (consolidated or Official Journal layout, both are parsed).
    'eu_annex1': os.getenv('DUALUSE_EU_URL', ''),
    'eu_annex1_index': EURLEX + 'ALL/?uri=CELEX:32021R0821',
    'eu_annex1_consolidated': EURLEX + 'TXT/HTML/?uri=CELEX:02021R0821-%s',
    'eu_annex1_fallback': 'https://eur-lex.europa.eu/eli/reg_del/2025/2003/oj/eng',
    'eu_cn_correlation': os.getenv('DUALUSE_CORR_URL',
                                   'https://circabc.europa.eu/rest/download/8dd0feca-0b12-494e-9ad3-a1a5565e56ad'),
    'chpl': os.getenv('DUALUSE_CHPL_URL', 'https://finance.ec.europa.eu/document/download/'
                      '5a2494db-d874-4e2b-bf2a-ec5a191d2dc0_en?filename=list-common-high-priority-items_en.pdf'),
    'cwc': 'https://www.opcw.org/chemical-weapons-convention/annexes/annex-chemicals/schedule-%d',
    'us_ccl': 'https://www.ecfr.gov/api/versioner/v1/full/%s/title-15.xml?part=774',
}
FILES = {'eu_annex1': 'eu_annex1.html', 'eu_cn_correlation': 'eu_cn_correlation.xlsx', 'chpl': 'chpl.pdf',
         'cwc': 'cwc_s%d.html', 'us_ccl': 'us_ccl.xml'}


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
def fetch(url, timeout=120):
    import requests
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.content


def latest_ecfr_date():
    data = json.loads(fetch('https://www.ecfr.gov/api/versioner/v1/versions/title-15.json?part=774', 60))
    return max(v['date'] for v in data['content_versions'])


def latest_eu_consolidated():
    """Date (YYYYMMDD) of the newest consolidated version of Regulation (EU) 2021/821 listed on EUR-Lex."""
    page = fetch(DEFAULT_URLS['eu_annex1_index'], 180).decode('utf-8', 'replace')
    dates = sorted(set(re.findall(r'02021R0821-(\d{8})', page)))
    return dates[-1] if dates else None


def pdf_text(raw):
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(raw)
        f.flush()
        try:
            return subprocess.run(['pdftotext', '-layout', f.name, '-'], capture_output=True, timeout=120,
                                  check=True).stdout.decode('utf-8', 'replace')
        except Exception:
            return None


def get_raw(code, a):
    """-> (bytes or {n: bytes}, version_label, url)."""
    def local(name):
        p = os.path.join(a.from_dir, name)
        return open(p, 'rb').read() if os.path.exists(p) else None

    def keep(name, data):
        if a.raw_dir:
            os.makedirs(a.raw_dir, exist_ok=True)
            with open(os.path.join(a.raw_dir, name), 'wb') as f:
                f.write(data)

    if code == 'cwc':
        pages = {}
        for n in (1, 2, 3):
            data = local(FILES['cwc'] % n) if a.from_dir else fetch(DEFAULT_URLS['cwc'] % n)
            if data is None:
                raise RuntimeError('missing ' + FILES['cwc'] % n)
            keep(FILES['cwc'] % n, data)
            pages[n] = data
        return pages, 'OPCW schedules as published', DEFAULT_URLS['cwc'] % 1
    if code == 'us_ccl':
        if a.from_dir:
            # optional us_ccl.xml.label next to the file names the eCFR date it was taken on
            lab = local(FILES['us_ccl'] + '.label')
            data, label = local(FILES['us_ccl']), (lab.decode().strip() if lab else 'from file')
            url = 'file'
        else:
            d = latest_ecfr_date()
            url = DEFAULT_URLS['us_ccl'] % d
            data, label = fetch(url, 300), 'eCFR as of %s' % d
        keep(FILES['us_ccl'], data)
        return data, label, url
    if code == 'eu_annex1' and not a.from_dir:
        url, label = DEFAULT_URLS['eu_annex1'], None
        if not url:
            try:
                d = latest_eu_consolidated()
            except Exception as e:
                print('eu_annex1: consolidated versions not listed (%s) - using the last amending act' % e)
                d = None
            url = DEFAULT_URLS['eu_annex1_consolidated'] % d if d else DEFAULT_URLS['eu_annex1_fallback']
        data = fetch(url, 300)
        keep(FILES[code], data)
        return data, None, url
    url = DEFAULT_URLS[code]
    data = local(FILES[code]) if a.from_dir else fetch(url, 180)
    if data is None:
        raise RuntimeError('missing ' + FILES[code])
    keep(FILES[code], data)
    return data, None, url


def content_digest(records):
    """SHA-256 of the parsed records (stable across downloads of an unchanged list)."""
    return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def sha(data):
    h = hashlib.sha256()
    if isinstance(data, dict):
        for k in sorted(data):
            h.update(data[k])
    else:
        h.update(data)
    return h.hexdigest()


# ------------------------------------------------------------------ parse -> normalised records
def build_items(code, data):
    """-> (items, hs_rows, chem_rows, version_label). Items: dicts for dualuse_items + 'params'."""
    if code == 'eu_annex1':
        recs = P.parse_eu_annex1(data.decode('utf-8', 'replace'))
        items = []
        for r in recs:
            items.append({'code': r['code'], 'parent_code': r['parent'], 'entry_code': r['entry'],
                          'level': r['level'], 'category': r['category'], 'grp': r['group'],
                          'title_en': r['text_en'][:300] if r['level'] == 0 else None, 'text_en': r['text_en'],
                          'notes_en': r.get('notes_en') or [], 'reasons': [], 'not_used': r['not_used'],
                          'risk_level': risk_eu(r['code']), 'extra': {'cas': r['cas_numbers']},
                          'params': r['parameters']})
        c = re.search(r'02021R0821\s*\W+\s*EN\s*\W+\s*(\d{2})\.(\d{2})\.(\d{4})', data.decode('utf-8', 'replace'))
        if c:
            return items, [], [], 'Annex I, consolidated text of %s-%s-%s' % (c.group(3), c.group(2), c.group(1))
        m = re.search(rb'Delegated Regulation \(EU\) (\d{4}/\d+)', data)
        return items, [], [], ('Annex I as replaced by Delegated Regulation (EU) %s' % m.group(1).decode()
                               if m else 'Annex I')
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
                              'not_used': bool(re.match(r'\[?reserved\]?', s['text_en'], re.I)), 'risk_level': rl,
                              'extra': {'cas': s['cas_numbers']}, 'params': s['parameters']})
        # sub-item codes can repeat inside notes: keep the first
        seen, uniq = set(), []
        for it in items:
            if it['code'] not in seen:
                seen.add(it['code'])
                uniq.append(it)
        return uniq, [], [], None
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
                          'notes_en': [], 'reasons': [], 'not_used': False,
                          'risk_level': 'high', 'params': [],
                          'extra': {'cas': [r['cas']] if r['cas'] else [], 'schedule': r['schedule'],
                                    'part': r['part'], 'common_name': r['common_name_en']}})
        return items, [], [], None
    if code == 'eu_cn_correlation':
        return [], None, [], None          # needs the EU codes: handled in main()
    if code == 'chpl':
        txt = pdf_text(data)
        recs = P.parse_chpl_text(txt) if txt else []
        if len(recs) < 40:                 # no pdftotext on this host, or the layout changed
            recs = P.chpl_seed()
            label = 'February 2024 (bundled copy; pdftotext not available or parse incomplete)'
        else:
            v = re.search(r'\(Version of ([A-Za-z]+ \d{4})\)', txt)
            label = 'version of %s' % v.group(1) if v else 'as published'
        hs = [{'cn10': None, 'hs6': r['hs6'], 'hs4': r['hs6'][:4], 'chapter': r['hs6'][:2], 'control_code': None,
               'resolved_code': None, 'taric_footnote': None, 'priority_tier': r['tier'],
               'description_en': r['description_en']} for r in recs]
        return [], hs, [], label
    raise ValueError(code)


def diff_items(old, new):
    o = {r['code']: r for r in old}
    n = {r['code']: r for r in new}
    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    changed = sorted(c for c in set(o) & set(n) if (o[c].get('text_en') or '') != (n[c].get('text_en') or ''))
    return {'added': len(added), 'removed': len(removed), 'changed': len(changed),
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
            bv, bu = T.to_base(p.get('value'), p.get('unit'))
            prow.append((by_code[it['code']], p.get('parameter'), p['operator'], p.get('value'), p.get('unit'),
                         bv, bu, p.get('raw')))
    if prow:
        execute_values(cur, """INSERT INTO dualuse_parameters (item_id, parameter, operator, value, unit, base_value,
                       base_unit, raw) VALUES %s""", prow, page_size=1000)
    return len(rows), len(prow)


def write_hs(cur, vid, rows):
    from psycopg2.extras import execute_values
    execute_values(cur, """INSERT INTO dualuse_hs_map (version_id, cn10, hs6, hs4, chapter, control_code, resolved_code,
                   taric_footnote, priority_tier, description_en) VALUES %s""",
                   [(vid, r.get('cn10'), r['hs6'], r.get('hs4'), r.get('chapter'), r.get('control_code'),
                     r.get('resolved_code'), r.get('taric_footnote'), r.get('priority_tier'), r.get('description_en'))
                    for r in rows], page_size=1000)


def rebuild_chemicals(cur, ids, who, apply):
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
        print('chemicals: unchanged (%d CAS)' % len(chem))
        return
    old = {}
    if cv:
        cur.execute("SELECT cas, names_ar, ar_status FROM dualuse_chemicals WHERE version_id = %s", (cv['id'],))
        old = {r['cas']: r for r in cur.fetchall()}
    stats = {'cas': len(chem), 'ag_precursors': sum(r['ag_precursor'] for r in chem),
             'cwc_scheduled': sum(1 for r in chem if r['cwc_schedule'])}
    print('chemicals:', stats)
    if not apply:
        return
    from psycopg2.extras import execute_values
    vid = new_version(cur, ids['chemicals'], 'built %s' % datetime.date.today(), None, digest, len(chem), stats,
                      {'previous': cv['record_count'] if cv else 0}, who)
    execute_values(cur, """INSERT INTO dualuse_chemicals (version_id, cas, names_en, names_ar, cwc_schedule, ag_precursor,
                   listings, ar_status) VALUES %s""",
                   [(vid, r['cas'], r['names_en'][:12], (old.get(r['cas']) or {}).get('names_ar') or [],
                     r['cwc_schedule'], r['ag_precursor'], json.dumps(r['listings']),
                     (old.get(r['cas']) or {}).get('ar_status') or 'none') for r in chem], page_size=500)
    make_current(cur, ids['chemicals'], vid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', default='all', help='all or one of: ' + ', '.join(c for c in LISTS if c != 'chemicals'))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--force', action='store_true', help='reload even when the file is unchanged')
    ap.add_argument('--from-dir', default=None, help='read files from this folder instead of downloading')
    ap.add_argument('--raw-dir', default=None, help='keep a copy of every downloaded file here')
    ap.add_argument('--dbname', default=None, help='override the database name (scratch / test databases)')
    ap.add_argument('--who', default='import_lists')
    a = ap.parse_args()
    order = ['eu_annex1', 'us_ccl', 'cwc', 'eu_cn_correlation', 'chpl']
    todo = order if a.list == 'all' else [a.list]
    conn = connect(a.dbname)
    cur = conn.cursor()
    cur.execute("SELECT pg_try_advisory_lock(hashtext('dualuse_import'))")
    if not list(cur.fetchone().values())[0]:
        sys.exit('another dual-use import is running')
    ids = ensure_lists(cur)
    conn.commit()
    changed_any = False
    eu_codes_new = None
    for code in todo:
        try:
            data, label, url = get_raw(code, a)
        except Exception as e:
            print('%s: download failed: %s' % (code, e))
            continue
        cv = current_version(cur, ids[code])
        if code == 'eu_cn_correlation':
            known = eu_codes_new or {r['code'] for r in current_items(cur, 'eu_annex1')}
            if not known:
                print('eu_cn_correlation: load eu_annex1 first')
                continue
            rows = P.parse_correlation(data, known)
            digest = content_digest(rows)
            if cv and cv['raw_sha256'] == digest and not a.force:
                print('%s: unchanged (version %s, %d pairs)' % (code, cv['id'], cv['record_count']))
                continue
            stats = {'pairs': len(rows), 'cn10': len({r['cn10'] for r in rows}),
                     'resolved': sum(1 for r in rows if r['resolved_code'])}
            print(code, stats)
            if a.apply:
                vid = new_version(cur, ids[code], label or 'as published', url, digest, len(rows), stats,
                                  {'previous': cv['record_count'] if cv else 0}, a.who)
                write_hs(cur, vid, rows)
                make_current(cur, ids[code], vid)
                conn.commit()
                changed_any = True
            continue
        items, hs_rows, _, vlabel = build_items(code, data)
        label = vlabel or label or 'as published'
        if code == 'eu_annex1':
            eu_codes_new = {i['code'] for i in items}
        # The digest is taken on the PARSED content, not on the downloaded bytes: the publishers' pages
        # carry session tokens and timestamps, so the raw file differs on every download.
        digest = content_digest(items if code != 'chpl' else hs_rows)
        if cv and cv['raw_sha256'] == digest and not a.force:
            print('%s: unchanged (version %s: %s, %d records)' % (code, cv['id'], cv['version_label'],
                                                               cv['record_count']))
            continue
        if code == 'chpl':
            stats = {'hs6': len(hs_rows)}
            print(code, stats, label)
            if a.apply:
                vid = new_version(cur, ids[code], label, url, digest, len(hs_rows), stats,
                                  {'previous': cv['record_count'] if cv else 0}, a.who)
                write_hs(cur, vid, hs_rows)
                make_current(cur, ids[code], vid)
                conn.commit()
                changed_any = True
            continue
        if len(items) < 20:
            print('%s: only %d records parsed - refusing to load (the source layout may have changed)'
                  % (code, len(items)))
            continue
        old = current_items(cur, code)
        if old and len(items) < 0.6 * len(old):
            print('%s: %d records vs %d now - refusing a shrink of more than 40%%' % (code, len(items), len(old)))
            continue
        d = diff_items(old, items)
        live = [i for i in items if not i['not_used']]
        stats = {'records': len(items), 'live': len(live), 'with_parameters': sum(1 for i in live if i['params']),
                 'parameters': sum(len(i['params']) for i in items)}
        print(code, label, stats, 'diff', {k: d[k] for k in ('added', 'removed', 'changed')})
        if a.apply:
            vid = new_version(cur, ids[code], label, url, digest, len(items), stats, d, a.who)
            n, np_ = write_items(cur, vid, items, old)
            make_current(cur, ids[code], vid)
            conn.commit()
            changed_any = True
            print('  loaded version %s: %d items, %d parameters' % (vid, n, np_))
    if any(c in todo for c in ('eu_annex1', 'us_ccl', 'cwc')):
        rebuild_chemicals(cur, ids, a.who, a.apply)
        conn.commit()
    if not a.apply:
        print('DRY RUN - nothing written (use --apply)')
    elif changed_any:
        print('done - the search index reloads on its own within a minute')
    conn.close()


if __name__ == '__main__':
    main()
