#!/usr/bin/env python3
"""
Import a regulatory-measures list (Phase 2, P2-4) into screening_watchlist with
list_type 'REGULATORY' (see screening/regulatory.py for when these lists are searched).

First list: the Palestine Monetary Authority list of AML/CFT measures and sanctions taken
against supervised financial institutions and their staff (Article 58, Decree-Law 39/2022),
published on https://www.pma.ps/anti-money-laundering/statements-and-lists under
"قائمة العقوبات المتخذة" in four groups: banks, money changers, specialised lending
institutions, e-payment companies. Any other regulator's list can use the same file format
with its own --source.

Input: a UTF-8 CSV (Excel: "CSV UTF-8") with a header row:
    name_ar, name_en, kind, sector, institution, measure, decision_date, reference, notes
  kind         institution | individual
  sector       bank | money_changer | lending | e_payment | other
  institution  for an individual: the institution he / she works for
  measure      the measure or sanction (warning, fine, suspension, licence revoked ...)
At least one of name_ar / name_en is required on every row.

Every import replaces the previous version of the source: records not in the file are
deactivated (never deleted). If the file has fewer than half the active records, the import
stops unless --allow-shrink is given (a broken file must not empty the list).

    python scripts/import_regulatory_list.py file.csv                         # dry run
    python scripts/import_regulatory_list.py file.csv --apply
    python scripts/import_regulatory_list.py file.csv --source cbe_reg --label "..." --url "..." --apply
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

PMA = {'source': 'pma_ps_reg', 'dataset': 'pma_ps_regulatory_art58',
       'label': 'Palestine Monetary Authority - AML/CFT regulatory measures (Art. 58, Decree-Law 39/2022)',
       'url': 'https://www.pma.ps/anti-money-laundering/statements-and-lists'}
SECTORS = {'bank': 'Bank', 'money_changer': 'Money changer', 'lending': 'Specialised lending institution',
           'e_payment': 'E-payment company', 'other': 'Other'}
ARABIC = re.compile('[؀-ۿ]')


AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def iso_date(v):
    """'15/03/2024', '2024-03-15', '2024/3/15', Arabic digits, Excel serial -> '2024-03-15T00:00:00'.
    '' when empty; None when it cannot be read (the row is then rejected)."""
    v = clean(v).translate(AR_DIGITS)
    if not v:
        return ''
    if re.fullmatch(r'\d{5}(\.0+)?', v):
        d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(v)))
        return d.isoformat() + 'T00:00:00'
    v = v.split('T')[0].split(' ')[0]
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y'):
        try:
            return datetime.datetime.strptime(v, fmt).date().isoformat() + 'T00:00:00'
        except ValueError:
            pass
    return None


def clean(v):
    return re.sub(r'\s+', ' ', str(v or '').replace('\xa0', ' ')).strip()


def parse(path):
    recs, problems = [], []
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.DictReader(f)
        need = {'name_ar', 'name_en', 'kind', 'sector', 'measure'}
        miss = need - set(h.strip() for h in (rd.fieldnames or []))
        if miss:
            raise SystemExit(f'STOP: missing columns {sorted(miss)}')
        for n, row in enumerate(rd, start=2):
            row = {k.strip(): clean(v) for k, v in row.items() if k}
            ar, en = row.get('name_ar', ''), row.get('name_en', '')
            if not ar and not en:
                if any(row.values()):
                    problems.append(f'row {n}: no name')
                continue
            if ar and not ARABIC.search(ar):
                problems.append(f'row {n}: name_ar has no Arabic letters')
            kind = row.get('kind', '').lower()
            if kind not in ('institution', 'individual'):
                problems.append(f'row {n}: kind must be institution or individual')
            sector = row.get('sector', '').lower() or 'other'
            if sector not in SECTORS:
                problems.append(f'row {n}: sector must be one of {", ".join(SECTORS)}')
            dd = iso_date(row.get('decision_date'))
            if dd is None:
                problems.append(f"row {n}: decision_date {row.get('decision_date')!r} not understood (use YYYY-MM-DD)")
            recs.append(dict(row, name_ar=ar, name_en=en, kind=kind, sector=sector, line=n, decision_date=dd or ''))
    return recs, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--source', default=PMA['source'])
    ap.add_argument('--dataset')
    ap.add_argument('--label')
    ap.add_argument('--url')
    ap.add_argument('--allow-shrink', action='store_true')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    is_pma = a.source == PMA['source']
    dataset = a.dataset or (PMA['dataset'] if is_pma else a.source)
    label = a.label or (PMA['label'] if is_pma else a.source)
    url = a.url or (PMA['url'] if is_pma else None)
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,40}', a.source) or not a.source.endswith('_reg'):
        raise SystemExit('STOP: --source must be lower-case and end with _reg (e.g. pma_ps_reg)')

    recs, problems = parse(a.path)
    if problems:
        print('STOP: fix the file first:\n  ' + '\n  '.join(problems[:50]))
        sys.exit(2)
    from screening.arabic_transliteration_enhanced import transliterate_to_english
    import psycopg2
    from config import Config
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM screening_watchlist WHERE source=%s AND is_active=1", (a.source,))
    active_now = cur.fetchone()[0]
    n_unique = len({'|'.join([r['kind'], r['name_ar'] or r['name_en'], r.get('institution', '')]) for r in recs})
    if active_now and n_unique < 0.5 * active_now and not a.allow_shrink:
        print(f'STOP: the file has {n_unique} records but {active_now} are active today '
              f'(use --allow-shrink if the list really shrank)')
        sys.exit(2)
    # List version (P2-1): opened before anything is written, closed after the commit
    # (this importer keeps its own shrink check: --allow-shrink).
    LV = vid = None
    if a.apply:
        from screening import list_versions as LV
        try:   # one writer per list; released when this script's connection closes
            LV.hold_source_lock(conn, a.source)
        except LV.SourceBusy as e:
            print(f'STOP: {e}')
            sys.exit(2)
        with open(a.path, 'rb') as fh:
            vid = LV.begin(conn, a.source, LV.file_sha256(fh.read()), 'file', len(recs), trigger='import')
        cur = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    groups = {}                       # one record per institution / person, all its measures kept
    for r in recs:
        key = '|'.join([r['kind'], r['name_ar'] or r['name_en'], r.get('institution', '')])
        groups.setdefault(key, []).append(r)
    ids = []
    for key, rows in groups.items():
        rows.sort(key=lambda x: x['decision_date'] or '9999')
        r = rows[-1]
        r['name_en'] = next((x['name_en'] for x in rows if x['name_en']), '')
        sid = a.source.upper().replace('_', '-') + '-' + hashlib.sha1(key.encode('utf-8')).hexdigest()[:12].upper()
        ids.append(sid)
        latin = r['name_en'] or (transliterate_to_english(r['name_ar']) if r['name_ar'] else '')
        if r['kind'] == 'institution' and not r['name_en'] and r['name_ar']:
            full = r['name_ar']       # institution names do not transliterate well: the Arabic name leads
        else:
            full = latin or r['name_ar']
        aliases = [x for x in dict.fromkeys([r['name_ar'], latin, r['name_en']]) if x and x != full]
        measures = [{k: x.get(k) for k in ('measure', 'decision_date', 'reference', 'notes') if x.get(k)} for x in rows]
        props = {k: v for k, v in {
            'sector': SECTORS[r['sector']], 'institution': r.get('institution'), 'measure': r.get('measure'),
            'decision_date': r['decision_date'][:10] if r['decision_date'] else None, 'reference': r.get('reference'),
            'measures': measures, 'other_information': r.get('notes'), 'regime': label}.items() if v}
        reason = ' ; '.join(' - '.join(y for y in [x.get('measure'), (x.get('decision_date') or '')[:10], x.get('reference')] if y)
                            for x in rows)
        reason = ' - '.join(y for y in [SECTORS[r['sector']],
                                        (f"employee of {r['institution']}" if r['kind'] == 'individual' and r.get('institution') else ''),
                                        reason] if y)
        props['statement_of_reasons'] = reason
        first = rows[0]['decision_date'] or now
        cur.execute("""
            INSERT INTO screening_watchlist (full_name, original_name, full_name_arabic, aliases, aliases_arabic,
                entity_type, list_type, dataset, topics, source, source_id, source_url, first_seen, last_seen,
                last_updated, risk_level, risk_category, details, properties, created_at, updated_at, is_active,
                original_script)
            VALUES (%s,%s,%s,%s,%s,%s,'REGULATORY',%s,%s,%s,%s,%s,%s,%s,%s,'MEDIUM','Regulatory measure',%s,%s,%s,%s,1,%s)
            ON CONFLICT (source, source_id) DO UPDATE SET
                full_name=EXCLUDED.full_name, original_name=EXCLUDED.original_name,
                full_name_arabic=EXCLUDED.full_name_arabic, aliases=EXCLUDED.aliases,
                aliases_arabic=EXCLUDED.aliases_arabic, entity_type=EXCLUDED.entity_type,
                list_type=EXCLUDED.list_type, dataset=EXCLUDED.dataset, topics=EXCLUDED.topics,
                source_url=EXCLUDED.source_url, risk_level=EXCLUDED.risk_level, risk_category=EXCLUDED.risk_category,
                original_script=EXCLUDED.original_script, first_seen=EXCLUDED.first_seen,
                details=EXCLUDED.details, properties=EXCLUDED.properties, last_seen=EXCLUDED.last_seen,
                last_updated=EXCLUDED.last_updated, is_active=1, updated_at=EXCLUDED.updated_at
        """, (full, r['name_ar'] or r['name_en'], r['name_ar'] or None, json.dumps(aliases, ensure_ascii=False),
              json.dumps([x for x in aliases if ARABIC.search(x)], ensure_ascii=False),
              'INDIVIDUAL' if r['kind'] == 'individual' else 'ENTITY', dataset, json.dumps(['reg.action']),
              a.source, sid, url, first, now, now, json.dumps([reason], ensure_ascii=False),
              json.dumps(props, ensure_ascii=False), now, now, 'ar' if r['name_ar'] else 'latin'))
    cur.execute("""UPDATE screening_watchlist SET is_active=0, updated_at=%s
                   WHERE source=%s AND is_active=1 AND NOT (source_id = ANY(%s))""", (now, a.source, ids))
    removed = cur.rowcount
    cur.execute("""INSERT INTO sanctions_lists (list_code, list_name, source_url, last_download_date, record_count, is_active)
                   SELECT %s, %s, %s, %s, %s, 1 WHERE NOT EXISTS (SELECT 1 FROM sanctions_lists WHERE list_code=%s)""",
                (a.source, label, url, now, len(ids), a.source))
    cur.execute("UPDATE sanctions_lists SET last_download_date=%s, record_count=%s WHERE list_code=%s",
                (now, len(ids), a.source))
    inst = sum(k.startswith('institution|') for k in groups)
    print(f'{label}: {len(recs)} measures on {inst} institutions and {len(groups) - inst} individuals; '
          f'deactivated (no longer listed) {removed}')
    if a.apply:
        conn.commit()
        LV.applied(conn, vid, {'updated': len(ids), 'delisted': removed})
        print('APPLIED - the search index picks the change up within 15 minutes')
    else:
        conn.rollback()
        print('DRY RUN (nothing saved)')


if __name__ == '__main__':
    main()
