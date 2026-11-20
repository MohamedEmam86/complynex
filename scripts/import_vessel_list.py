#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Import a ship list that has no machine-readable feed (V1) into screening_watchlist as VESSEL records,
then refresh the vessel tables. Examples: the EU list of ships banned from ports and services
(Reg. 833/2014 Annex XLII, published only as a table in the Official Journal) and the UN 1718
Committee's designated vessels.

Input, either:
  * a UTF-8 CSV / .xlsx with a header row:
        name, imo, flag, type, measure, listed_on, reference, aliases, owner
    (name or imo required; aliases separated by ';'), or
  * --html: the list's page saved as HTML; every table row holding a 7-digit IMO number becomes one
    ship, the name taken from the cell before the IMO cell.

Every import replaces the previous version of the source (records not in the file are deactivated,
never deleted). A file with fewer than half the active records stops unless --allow-shrink.

    python scripts/import_vessel_list.py file.csv --source eu_xlii_vessels --label "..." [--apply]
    python scripts/import_vessel_list.py page.html --html --source un_1718_vessels --measure port_ban
"""
import argparse
import csv
import datetime
import hashlib
import html as _html
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

IMO_RE = re.compile(r'(?<!\d)(?:IMO[\s:.-]*)?(\d{7})(?!\d)', re.I)


def clean(v):
    return re.sub(r'\s+', ' ', str(v or '')).strip()


def parse_table(path):
    rows = []
    if path.lower().endswith('.xlsx'):
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        head = [clean(h).lower() for h in next(it)]
        for r in it:
            rows.append({head[i]: clean(v) for i, v in enumerate(r) if i < len(head)})
    else:
        with open(path, encoding='utf-8-sig', newline='') as fh:
            for r in csv.DictReader(fh):
                rows.append({clean(k).lower(): clean(v) for k, v in r.items() if k})
    return rows


def parse_html(path):
    """Generic: each <tr> with a 7-digit IMO -> {name, imo, listed_on?}."""
    text = open(path, encoding='utf-8', errors='replace').read()
    out = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', text, flags=re.S | re.I):
        cells = [clean(_html.unescape(re.sub(r'<[^>]+>', ' ', c)))
                 for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, flags=re.S | re.I)]
        for i, c in enumerate(cells):
            m = IMO_RE.fullmatch(c.replace(' ', '')) or (IMO_RE.search(c) if 'imo' in c.lower() else None)
            if m:
                name = next((x for x in reversed(cells[:i]) if x and not x.rstrip('.').isdigit()), '')
                date = next((x for x in cells[i + 1:] if re.search(r'\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2}', x)), '')
                out.append({'name': name, 'imo': m.group(1), 'listed_on': date})
                break
    return out


class ImportStop(Exception):
    """The import refused the file (nothing was written)."""


def run(path, source, label=None, url=None, measure='port_ban', html=False, allow_shrink=False, apply=False,
        out=print, user_id=None, conn=None):
    """Import one vessel list file (also used by the vessel update page's upload). Raises ImportStop when the
    file is refused. Returns a summary dict."""
    a = argparse.Namespace(path=path, source=source, label=label, url=url, measure=measure, html=html,
                           allow_shrink=allow_shrink, apply=apply)
    return _run(a, out, user_id, conn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--source', required=True)
    ap.add_argument('--label')
    ap.add_argument('--url')
    ap.add_argument('--measure', default='port_ban', help='default measure when the file has none')
    ap.add_argument('--html', action='store_true')
    ap.add_argument('--allow-shrink', action='store_true')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    try:
        _run(a, print, None, None)
    except ImportStop as e:
        print(f'STOP: {e}')
        sys.exit(2)


def _run(a, print, user_id, conn):
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,40}', a.source) or not a.source.endswith('_vessels'):
        raise ImportStop('the source must be lower-case and end with _vessels (e.g. eu_xlii_vessels)')
    label = a.label or a.source
    from screening.format_handlers import vessel_block, vessel_measures
    from screening.vessel_utils import norm_imo, imo_valid

    recs = parse_html(a.path) if a.html else parse_table(a.path)
    problems, ships = [], {}
    for n, r in enumerate(recs, 2):
        name, imo = clean(r.get('name')), norm_imo(r.get('imo'))
        if not name and not imo:
            problems.append(f'row {n}: no name and no IMO')
            continue
        key = imo or name.upper()
        s = ships.setdefault(key, {'name': name, 'imo': imo, 'rows': []})
        s['rows'].append(r)
        if not s['name'] and name:
            s['name'] = name
    if problems and not ships:
        raise ImportStop('; '.join(problems[:30]))
    bad_imo = [k for k, s in ships.items() if s['imo'] and not imo_valid(s['imo'])]

    if conn is None:
        import psycopg2
        from config import Config
        conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()
    cur.execute('SELECT count(*) FROM screening_watchlist WHERE source=%s AND is_active=1', (a.source,))
    active_now = cur.fetchone()[0]
    if active_now and len(ships) < 0.5 * active_now and not a.allow_shrink:
        raise ImportStop(f'the file has {len(ships)} ships but {active_now} are active today (allow shrink to accept)')
    LV = vid = None
    if a.apply:
        from screening import list_versions as LV
        try:
            LV.hold_source_lock(conn, a.source)
        except LV.SourceBusy as e:
            raise ImportStop(str(e))
        with open(a.path, 'rb') as fh:
            vid = LV.begin(conn, a.source, LV.file_sha256(fh.read()), 'file', len(ships), trigger='import')
        cur = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    ids = []
    for key, s in ships.items():
        rows = s['rows']
        first = rows[0]
        sid = a.source.upper().replace('_', '-') + '-' + (s['imo'] or hashlib.sha1(key.encode()).hexdigest()[:12].upper())
        ids.append(sid)
        aliases = [x for r in rows for x in clean(r.get('aliases')).split(';') if x.strip()]
        aliases = [x.strip() for x in dict.fromkeys(aliases + [clean(r.get('name')) for r in rows])
                   if x.strip() and x.strip() != s['name']]
        measures = vessel_measures(*[r.get('measure') for r in rows]) or [a.measure]
        owners = [{'name': clean(r.get('owner')), 'role': 'owner', 'ref': None} for r in rows if clean(r.get('owner'))]
        block = vessel_block(imos=[s['imo']] if s['imo'] else [], vtype=clean(first.get('type')) or None,
                             flag=clean(first.get('flag')) or None, names_past=aliases, owners=owners,
                             measures=measures)
        props = {'vessel': block, 'regime': label, 'listed_on': clean(first.get('listed_on')) or None,
                 'reference': clean(first.get('reference')) or None,
                 'identifiers': [{'type': 'IMO', 'number': s['imo']}] if s['imo'] else []}
        full = s['name'] or f"IMO {s['imo']}"
        cur.execute("""
            INSERT INTO screening_watchlist (full_name, original_name, aliases, entity_type, list_type, dataset,
                topics, source, source_id, source_url, first_seen, last_seen, last_updated, risk_level,
                details, properties, created_at, updated_at, is_active)
            VALUES (%s,%s,%s,'VESSEL','SANCTIONS',%s,%s,%s,%s,%s,%s,%s,%s,'HIGH',%s,%s,%s,%s,1)
            ON CONFLICT (source, source_id) DO UPDATE SET
                full_name=EXCLUDED.full_name, original_name=EXCLUDED.original_name, aliases=EXCLUDED.aliases,
                entity_type='VESSEL', list_type=EXCLUDED.list_type, dataset=EXCLUDED.dataset,
                topics=EXCLUDED.topics, source_url=EXCLUDED.source_url, details=EXCLUDED.details,
                properties=EXCLUDED.properties, last_seen=EXCLUDED.last_seen, last_updated=EXCLUDED.last_updated,
                is_active=1, updated_at=EXCLUDED.updated_at
        """, (full, full, json.dumps(aliases, ensure_ascii=False), a.source, json.dumps(['sanction', 'vessel']),
              a.source, sid, a.url, now, now, now, json.dumps({'regime': label, 'measures': measures}),
              json.dumps(props, ensure_ascii=False), now, now))
    cur.execute("""UPDATE screening_watchlist SET is_active=0, updated_at=%s
                   WHERE source=%s AND is_active=1 AND NOT (source_id = ANY(%s))""", (now, a.source, ids))
    removed = cur.rowcount
    cur.execute("""INSERT INTO sanctions_lists (list_code, list_name, source_url, last_download_date, record_count, is_active)
                   SELECT %s, %s, %s, %s, %s, 1 WHERE NOT EXISTS (SELECT 1 FROM sanctions_lists WHERE list_code=%s)""",
                (a.source, label, a.url, now, len(ids), a.source))
    cur.execute('UPDATE sanctions_lists SET last_download_date=%s, record_count=%s WHERE list_code=%s',
                (now, len(ids), a.source))
    print(f'{label}: {len(ships)} ships ({sum(1 for s in ships.values() if s["imo"])} with IMO, '
          f'{len(bad_imo)} IMO failing the check digit - kept and flagged); deactivated {removed}; '
          f'{len(problems)} rows skipped')
    summary = {'source': a.source, 'ships': len(ships), 'with_imo': sum(1 for s in ships.values() if s['imo']),
               'imo_check_fails': len(bad_imo), 'deactivated': removed, 'rows_skipped': len(problems),
               'applied': bool(a.apply)}
    if a.apply:
        conn.commit()
        LV.applied(conn, vid, {'updated': len(ids), 'delisted': removed})
        from screening import vessel_store as VS
        summary['sync'] = VS.sync(conn, a.source, log=print, trigger='import', user_id=user_id)
        print(summary['sync'])
        print('APPLIED')
    else:
        conn.rollback()
        print('DRY RUN (nothing saved)')
    return summary


if __name__ == '__main__':
    main()
