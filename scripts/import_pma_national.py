#!/usr/bin/env python3
"""
Import the Palestinian national designation list (UNSCR 1373), published by the
committee for implementing UN Security Council resolutions (sanction.pgp.ps,
linked from the Palestine Monetary Authority AML page), into screening_watchlist
as source 'pma_ps' (Phase 2, P2-3).

The file is an Excel 97 workbook with two sheets: individuals and entities. Names are
in Arabic with the Hebrew form after "بالعبرية". Latin forms are added from the
OpenSanctions copy of the same list when a record can be tied to it (same date of
birth for individuals, same Arabic / Hebrew name for entities); the provenance is
recorded in `details`.

Every import replaces the previous version of this source: records not in the new
file are deactivated (never deleted). A guard stops if the new file has far fewer
records than are active today (a broken download must not empty the list).

    python scripts/import_pma_national.py /path/to/file.xls            # dry run
    python scripts/import_pma_national.py /path/to/file.xls --apply
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

SOURCE = 'pma_ps'
DATASET = 'pma_ps_national_1373'
SOURCE_URL = 'https://sanction.pgp.ps/ar/SanctionFiles_arb'
HEBREW = re.compile('[֐-׿]')


def xdate(v):
    try:
        f = float(v)
        if f > 1000:
            return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(f))).isoformat()
    except (TypeError, ValueError):
        pass
    v = str(v or '').strip()
    return '' if v in ('', '-') else v


def xdate_flag(v):
    """Date of birth -> (ISO date or '', note). 'yyyy/mm/dd- غير مؤكد' -> ('yyyy-mm-dd', 'uncertain')."""
    d = xdate(v)
    note = ''
    if 'غير مؤكد' in d:
        note, d = 'uncertain', d.replace('غير مؤكد', '')
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', d)
    if m:
        d = f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    elif d and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d):
        note, d = (note + ' ' if note else '') + f'as written: {d}', ''
    return d, note


def clean(v):
    v = str(v or '').replace('\xa0', ' ').strip()
    return '' if v in ('-', '—') else re.sub(r'\s+', ' ', v)


def split_name(cell):
    """'ايتي زار، بالعبرية: איתי זר' -> ('ايتي زار', 'איתי זר', nickname)"""
    t = clean(cell)
    nick = ''
    m = re.search(r'ملقب\s*"([^"]+)"', t)
    if m:
        nick = m.group(1)
        t = t.replace(m.group(0), '')
    en = ''
    m_en = re.search(r'،?\s*بالإنجليزية\s*:?\s*([A-Za-z0-9 .\'\-]+)', t)
    if m_en:
        en = m_en.group(1).strip()
        t = t.replace(m_en.group(0), '')
    parts = re.split(r'،?\s*بالعبرية\s*:?', t, maxsplit=1)
    ar = parts[0].strip(' ،,')
    he = parts[1].strip() if len(parts) > 1 else ''
    if not he and HEBREW.search(ar):            # Hebrew written inline
        he = ' '.join(w for w in ar.split() if HEBREW.search(w))
        ar = ' '.join(w for w in ar.split() if not HEBREW.search(w))
    ar = re.sub(r'\s*\(.*?\)\s*', ' ', ar).strip(' ،,')
    return ar, he, nick, en


def sid(kind, key):
    return f'PMA-PS-{kind}-' + hashlib.sha1(key.encode('utf-8')).hexdigest()[:12].upper()


def parse(path):
    import xlrd
    wb = xlrd.open_workbook(path)
    ind, ent = wb.sheet_by_index(0), wb.sheet_by_index(1)
    recs = []
    for r in range(3, ind.nrows):
        row = [ind.cell_value(r, c) for c in range(ind.ncols)]
        if not clean(row[1]):
            continue
        ar, he, nick, en = split_name(row[1])
        doc = clean(row[9])
        doc = doc[:-2] if doc.endswith('.0') else doc
        if doc.isdigit() and 'اسرائيلية' in clean(row[8]).replace('إ', 'ا'):
            doc = doc.zfill(9)                         # Israeli IDs are 9 digits; Excel drops leading zeros
        dob, dob_note = xdate_flag(row[7])
        recs.append({
            'kind': 'I', 'entity_type': 'INDIVIDUAL', 'name_ar': ar, 'name_he': he,
            'aliases': [x for x in (he, nick, clean(row[4])) if x],
            'gender': {'ذكر': 'male', 'أنثى': 'female', 'انثى': 'female'}.get(clean(row[2]), ''),
            'father': clean(row[3]), 'linked_entity': clean(row[5]), 'address': clean(row[6]),
            'dob': dob, 'dob_note': dob_note, 'english': en, 'doc_type': clean(row[8]), 'doc_no': doc, 'mother': clean(row[10]),
            'nationality': clean(row[11]), 'listed': xdate(row[12]), 'last_change': clean(row[13]),
            'last_change_date': xdate(row[14]),
            'source_id': sid('I', doc or (ar + '|' + (dob or ''))),
        })
    for r in range(3, ent.nrows):
        row = [ent.cell_value(r, c) for c in range(ent.ncols)]
        if not clean(row[0]):
            continue
        ar, he, nick, en = split_name(row[0])
        m = re.search(r'\(([^)]+)\)', clean(row[0]))
        recs.append({
            'kind': 'E', 'entity_type': 'ENTITY', 'name_ar': ar, 'name_he': he,
            'aliases': [x for x in (he, nick, m.group(1) if m else '') if x],
            'english': en, 'description': clean(row[1]), 'listed': xdate(row[2]), 'last_change': clean(row[3]) if ent.ncols > 3 else '',
            'last_change_date': xdate(row[4]) if ent.ncols > 4 else '',
            'source_id': sid('E', ar),
        })
    return recs


def enrich(cur, recs):
    """Latin forms from the OpenSanctions copy of the same list (if the record can be tied to it)."""
    cur.execute("""SELECT full_name, aliases, date_of_birth, entity_type FROM screening_watchlist
                   WHERE is_active=1 AND source='opensanctions'
                     AND (dataset LIKE '%%ps_national_terrorism_list%%' OR dataset LIKE '%%ps_local_freezing%%')""")
    os_rows = cur.fetchall()
    by_dob, by_name = {}, {}
    for full, al, dob, et in os_rows:
        try:
            als = json.loads(al or '[]')
        except ValueError:
            als = []
        names = [full] + [a for a in als if a]
        if dob:
            by_dob.setdefault(str(dob)[:10], []).append(names)
        for n in names:
            by_name[re.sub(r'\s+', ' ', n).strip()] = names
    tied = 0
    for r in recs:
        cand = None
        if r['kind'] == 'I' and r.get('dob') and len(by_dob.get(r['dob'], [])) == 1:
            cand = by_dob[r['dob']][0]
        elif r['name_he'] and r['name_he'] in by_name:
            cand = by_name[r['name_he']]
        elif r['name_ar'] in by_name:
            cand = by_name[r['name_ar']]
        lat = [n for n in (cand or []) if re.fullmatch(r"[A-Za-z .'\-]+", n or '')]
        if r.get('english') and r['english'] not in lat:
            lat = [r['english']] + lat
        r['latin'] = lat
        r['enriched_from'] = 'opensanctions ps_national_terrorism_list' if lat else ''
        tied += bool(lat)
    return tied


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    import psycopg2
    from config import Config
    recs = parse(a.path)
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()
    tied = enrich(cur, recs)
    ind = sum(r['kind'] == 'I' for r in recs)
    print(f'parsed: {ind} individuals, {len(recs) - ind} entities; Latin forms tied from OpenSanctions: {tied}')
    cur.execute("SELECT count(*) FROM screening_watchlist WHERE source=%s AND is_active=1", (SOURCE,))
    active_now = cur.fetchone()[0]
    if active_now and len(recs) < 0.5 * active_now:
        print(f'STOP: the file has {len(recs)} records but {active_now} are active today - not importing')
        sys.exit(2)
    # List version + update guard (P2-1): only for a real import, before anything is written.
    LV = vid = ev = None
    if a.apply:
        from screening import list_versions as LV
        try:   # one writer per list; released when this script's connection closes
            LV.source_lock(conn, SOURCE).__enter__()
        except LV.SourceBusy as e:
            print(f'STOP: {e}')
            sys.exit(2)
        with open(a.path, 'rb') as fh:
            sha = LV.file_sha256(fh.read())
        ids_in = [r['source_id'] for r in recs]
        vid = LV.begin(conn, SOURCE, sha, 'file', len(set(ids_in)), trigger='import')
        ev = LV.evaluate(conn, SOURCE, ids_in, sha=sha)
        if ev['blocked']:
            LV.block(conn, vid, ev)
            print('BLOCKED by the update guard: ' + '; '.join(ev['reasons']) +
                  ' - nothing imported. If the change is genuine, approve the version on the list versions page and run again.')
            sys.exit(2)
        cur = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')   # ISO: the search index rejects 'YYYY-MM-DD HH:MM:SS'
    for r in recs:
        full = r['latin'][0] if r['latin'] else r['name_ar']
        aliases = list(dict.fromkeys(r['latin'][1:] + r['aliases']))
        details = {k: r.get(k) for k in ('father', 'mother', 'linked_entity', 'address', 'doc_type', 'doc_no', 'dob_note',
                                          'description', 'listed', 'last_change', 'last_change_date', 'enriched_from')
                   if r.get(k)}
        details['list'] = 'Palestinian national designation list (UNSCR 1373)'
        cur.execute("""
            INSERT INTO screening_watchlist (full_name, original_name, full_name_arabic, aliases, aliases_arabic,
                entity_type, list_type, dataset, topics, date_of_birth, gender, nationality, national_id_numbers,
                addresses, source, source_id, source_url, first_seen, last_seen, last_updated, risk_level,
                risk_category, details, created_at, updated_at, is_active, original_script)
            VALUES (%s,%s,%s,%s,%s,%s,'SANCTIONS',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'HIGH','Terrorism',%s,%s,%s,1,'ar')
            ON CONFLICT (source, source_id) DO UPDATE SET
                full_name=EXCLUDED.full_name, original_name=EXCLUDED.original_name,
                full_name_arabic=EXCLUDED.full_name_arabic, aliases=EXCLUDED.aliases,
                aliases_arabic=EXCLUDED.aliases_arabic, entity_type=EXCLUDED.entity_type,
                date_of_birth=EXCLUDED.date_of_birth, gender=EXCLUDED.gender, nationality=EXCLUDED.nationality,
                national_id_numbers=EXCLUDED.national_id_numbers, addresses=EXCLUDED.addresses,
                details=EXCLUDED.details, last_seen=EXCLUDED.last_seen, last_updated=EXCLUDED.last_updated,
                is_active=1, updated_at=EXCLUDED.updated_at
        """, (full, r['name_ar'], r['name_ar'], json.dumps(aliases, ensure_ascii=False),
              json.dumps([x for x in aliases if not re.search('[A-Za-z]', x)], ensure_ascii=False),
              r['entity_type'], DATASET, json.dumps(['sanction', 'crime.terror']), r.get('dob') or None,
              r.get('gender') or None, r.get('nationality') or None,
              json.dumps([r['doc_no']]) if r.get('doc_no') else None,
              json.dumps([r['address']], ensure_ascii=False) if r.get('address') else None,
              SOURCE, r['source_id'], SOURCE_URL, r.get('listed') or now, now, now,
              json.dumps(details, ensure_ascii=False), now, now))
    cur.execute("""UPDATE screening_watchlist SET is_active=0, updated_at=%s
                   WHERE source=%s AND is_active=1 AND NOT (source_id = ANY(%s))""",
                (now, SOURCE, [r['source_id'] for r in recs]))
    removed = cur.rowcount
    cur.execute("""INSERT INTO sanctions_lists (list_code, list_name, source_url, last_download_date, record_count, is_active)
                   SELECT %s, %s, %s, %s, %s, 1 WHERE NOT EXISTS (SELECT 1 FROM sanctions_lists WHERE list_code=%s)""",
                (SOURCE, 'Palestine National Designation List (UNSCR 1373)', SOURCE_URL, now, len(recs), SOURCE))
    cur.execute("UPDATE sanctions_lists SET last_download_date=%s, record_count=%s WHERE list_code=%s",
                (now, len(recs), SOURCE))
    print(f'upserted {len(recs)}, deactivated (no longer in the file) {removed}')
    if a.apply:
        conn.commit()
        LV.applied(conn, vid, {'updated': len(recs), 'delisted': removed}, ev)
        print('APPLIED')
    else:
        conn.rollback()
        print('DRY RUN (nothing saved)')


if __name__ == '__main__':
    main()
