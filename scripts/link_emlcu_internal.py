#!/usr/bin/env python3
"""
Tie EMLCU website records to the same person in the Public Prosecution / terrorist lists
(Phase 2, P2-2 for EMLCU).

The EMLCU file publishes national IDs masked (only the last 4 digits) and no date of birth,
so an EMLCU hit could never be confirmed or excluded by date of birth. The same people are
usually also in internal_blacklist with the full national ID. When the name is the same
(normalised) and the full ID ends with the published last 4 digits, the EMLCU record gets:
  - date_of_birth decoded from the full Egyptian national ID (century, year, month, day)
  - properties.linked_internal = [internal_blacklist ids], properties.dob_source = 'national ID
    of the linked Public Prosecution record'
The full ID itself is not copied into the EMLCU record (the internal record keeps it).

Safe to run repeatedly (only changed rows are written). Dry run unless --apply.
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    import psycopg2
    from config import Config
    from screening.match_intel import normalize, decode_egyptian_nid
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()
    cur.execute("""SELECT id, original_name, full_name, national_id FROM internal_blacklist
                   WHERE COALESCE(is_active,1)!=0 AND national_id ~ '^[23][0-9]{13}$'""")
    by_name = {}
    for i, on, fn, nid in cur.fetchall():
        for n in {on, fn}:
            k = normalize(n or '')
            if k:
                by_name.setdefault(k, []).append((i, nid))
    cur.execute("""SELECT id, full_name, national_id_numbers, date_of_birth, COALESCE(properties,'')
                   FROM screening_watchlist WHERE source='emlcu' AND is_active=1""")
    rows = cur.fetchall()
    linked = ambiguous = written = 0
    for wid, name, nids, dob, props in rows:
        last4 = set(re.findall(r'(\d{4})"', nids or ''))
        cands = by_name.get(normalize(name or ''), [])
        if not last4:
            continue                       # no published digits: a name alone is not enough to link
        hits = [(i, nid) for i, nid in cands if nid[-4:] in last4]
        if not hits:
            continue
        dobs = set()
        for _, nid in hits:
            d = decode_egyptian_nid(nid) or {}
            if d.get('dob'):
                dobs.add(str(d['dob']))
        if len(dobs) != 1:
            ambiguous += 1
            continue
        linked += 1
        new_dob = dobs.pop()
        try:
            p = json.loads(props) if props.strip().startswith('{') else {}
        except ValueError:
            p = {}
        old_link = p.get('linked_internal')
        p['linked_internal'] = sorted(i for i, _ in hits)
        p['dob_source'] = 'decoded from the national ID of the linked Public Prosecution record'
        if dob == new_dob and old_link == p['linked_internal']:
            continue
        written += 1
        if a.apply:
            cur.execute("""UPDATE screening_watchlist SET date_of_birth=%s, year_of_birth=%s, properties=%s,
                           updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                        (new_dob, int(new_dob[:4]), json.dumps(p, ensure_ascii=False), wid))
    print(f'EMLCU records: {len(rows)}; linked with one date of birth: {linked}; ambiguous (several DOBs): '
          f'{ambiguous}; to write: {written}')
    if a.apply:
        conn.commit()
        print('APPLIED')
    else:
        conn.rollback()
        print('DRY RUN')


if __name__ == '__main__':
    main()
