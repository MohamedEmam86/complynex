#!/usr/bin/env python3
"""
Gap analysis: which names on the Egyptian local negative list are NOT in the
ComplyNex database?

Matching deliberately uses the SAME Arabic normalisation the live screening
engine uses (normalize_arabic_text). Anything else would give an answer that
does not reflect what screening would actually catch — the whole point is to
know which names would slip through a real screen.

Checked against:
  * internal_blacklist  (the local/internal list)
  * screening_watchlist (the international lists: OFAC / UN / EU / PEP feeds)

Also reports national-ID matches separately: a name spelled differently but
carrying the same national ID is a match a human would accept, and is worth
distinguishing from a genuine absence.

Writes /tmp/gap_results.json
"""
import json
import sys
from collections import defaultdict

sys.path.insert(0, '/var/www/complynex')
from app import create_app  # noqa: E402
from database.db import get_db  # noqa: E402
from screening.complynex_engine import normalize_arabic_text  # noqa: E402

app = create_app()


def norm(s):
    if not s:
        return ''
    try:
        n = normalize_arabic_text(s)
    except Exception:
        n = s
    return ' '.join(str(n).upper().split())


def clean_nid(s):
    if not s:
        return ''
    d = ''.join(ch for ch in str(s) if ch.isdigit())
    return d if len(d) >= 10 else ''


def main():
    with open('/tmp/local_list_names.json', encoding='utf-8') as f:
        rows = json.load(f)
    print('list rows loaded: %d' % len(rows))

    with app.app_context():
        db = get_db()

        print('loading internal_blacklist ...')
        db_names = set()
        db_ids = set()
        cur = db.execute(
            "SELECT full_name, original_name, national_id FROM internal_blacklist")
        n_bl = 0
        for r in cur.fetchall():
            d = dict(r)
            for key in ('full_name', 'original_name'):
                if d.get(key):
                    db_names.add(norm(d[key]))
            nid = clean_nid(d.get('national_id'))
            if nid:
                db_ids.add(nid)
            n_bl += 1
        print('  internal_blacklist rows: %d  (%d distinct normalised names)'
              % (n_bl, len(db_names)))

        print('loading screening_watchlist ...')
        wl_names = set()
        # 2.7M rows: pull them in id-ranged pages so nothing is held twice
        # and the wrapper's fetchall() is never asked for the whole table.
        n_wl = 0
        last_id = 0
        while True:
            cur = db.execute(
                "SELECT id, full_name FROM screening_watchlist "
                "WHERE id > %s ORDER BY id LIMIT 100000", (last_id,))
            batch = cur.fetchall()
            if not batch:
                break
            for r in batch:
                d = dict(r)
                if d.get('full_name'):
                    wl_names.add(norm(d['full_name']))
                last_id = d['id']
                n_wl += 1
            if n_wl % 500000 == 0:
                print('   ...%d rows' % n_wl, flush=True)
        print('  screening_watchlist rows: %d  (%d distinct normalised names)'
              % (n_wl, len(wl_names)))

    all_db_names = db_names | wl_names

    # de-duplicate the incoming list by normalised name, keeping the richest row
    by_norm = {}
    for r in rows:
        k = norm(r['name'])
        if not k:
            continue
        if k not in by_norm or len(r) > len(by_norm[k]):
            by_norm[k] = r

    missing, present_bl, present_wl, present_by_id = [], 0, 0, []
    for k, r in by_norm.items():
        if k in db_names:
            present_bl += 1
            continue
        if k in wl_names:
            present_wl += 1
            continue
        nid = clean_nid(r.get('national_id'))
        if nid and nid in db_ids:
            present_by_id.append(r)
            continue
        missing.append(r)

    by_sheet = defaultdict(int)
    for m in missing:
        by_sheet[m['sheet']] += 1

    print('\n' + '=' * 66)
    print('RESULT')
    print('=' * 66)
    print('unique names on the local list      : %d' % len(by_norm))
    print('already in internal_blacklist       : %d' % present_bl)
    print('already in screening_watchlist      : %d' % present_wl)
    print('matched by national ID only         : %d' % len(present_by_id))
    print('NOT IN THE DATABASE AT ALL          : %d' % len(missing))
    print('\nmissing, by source sheet:')
    for s, c in sorted(by_sheet.items(), key=lambda x: -x[1]):
        print('   %-42s %6d' % (s, c))

    with open('/tmp/gap_results.json', 'w', encoding='utf-8') as f:
        json.dump({'missing': missing,
                   'matched_by_id': present_by_id,
                   'summary': {'unique_list_names': len(by_norm),
                               'in_blacklist': present_bl,
                               'in_watchlist': present_wl,
                               'matched_by_id': len(present_by_id),
                               'missing': len(missing),
                               'by_sheet': dict(by_sheet)}}, f,
                  ensure_ascii=False)
    print('\nwritten /tmp/gap_results.json')


if __name__ == '__main__':
    main()
