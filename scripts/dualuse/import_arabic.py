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
"""Load Arabic texts of control entries, chemicals and priority items from a JSON file.

    python scripts/dualuse/import_arabic.py arabic.json            # dry run
    python scripts/dualuse/import_arabic.py arabic.json --apply

File format (a list; keys by list + code; status = draft | verified | reviewed):
    [{"list": "eu_annex1", "code": "5A002.a", "title_ar": "...", "text_ar": "...", "status": "reviewed",
      "parameters_ar": {"key length": "طول المفتاح"}},
     {"list": "chemicals", "code": "100-37-8", "names_ar": ["..."], "status": "verified"},
     {"list": "chpl", "code": "854231", "text_ar": "...", "status": "reviewed"},
     {"terms": [["lathe", "مخرطة"], ...]}]

Only the CURRENT version of each list is updated, and only when the English text the
translation was made from still matches (optional "source_en" key); otherwise the row is
reported and skipped. A text never moves to a lower status (reviewed > verified > draft).
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from import_lists import connect      # noqa: E402

RANK = {'none': 0, 'stale': 0, 'draft': 1, 'verified': 2, 'reviewed': 3}
AR = re.compile('[؀-ۿ]')


def norm_ws(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--dbname', default=None)
    a = ap.parse_args()
    data = json.load(open(a.file, encoding='utf-8'))
    conn = connect(a.dbname)
    cur = conn.cursor()
    stats = {'items': 0, 'chemicals': 0, 'priority': 0, 'params': 0, 'terms': 0, 'skipped_status': 0,
             'skipped_source_changed': 0, 'not_found': 0, 'not_arabic': 0}
    problems = []
    # a code given twice in the file (two translations for one item) is reported, not silently overwritten
    seen = {}
    for rec in data:
        if 'terms' not in rec and rec.get('code'):
            k = (rec.get('list'), rec.get('code'))
            seen[k] = seen.get(k, 0) + 1
    dups = sorted(k for k, n in seen.items() if n > 1)
    stats['duplicate_codes'] = len(dups)
    for k in dups[:30]:
        problems.append((k[0], k[1], 'given %d times in the file: the last one wins' % seen[k]))
    for rec in data:
        if 'terms' in rec:
            for en, ar in rec['terms']:
                if AR.search(ar or '') and en:
                    cur.execute("""INSERT INTO dualuse_terms (term_en, term_ar, source) VALUES (%s,%s,'translation')
                                   ON CONFLICT (term_en, term_ar) DO NOTHING""", (en.strip()[:200], ar.strip()[:200]))
                    stats['terms'] += cur.rowcount
            continue
        lst, code, status = rec.get('list'), rec.get('code'), rec.get('status') or 'draft'
        if status not in ('draft', 'verified', 'reviewed'):
            problems.append((lst, code, 'bad status'))
            continue
        texts = [rec.get('title_ar'), rec.get('text_ar')] + list(rec.get('names_ar') or [])
        if not any(AR.search(t or '') for t in texts):
            stats['not_arabic'] += 1
            continue
        if lst == 'chemicals':
            cur.execute("""SELECT c.id, c.ar_status FROM dualuse_chemicals c JOIN dualuse_list_versions v
                           ON v.id = c.version_id AND v.is_current WHERE c.cas = %s""", (code,))
            row = cur.fetchone()
            if not row:
                stats['not_found'] += 1
                continue
            if RANK[status] < RANK.get(row['ar_status'], 0):
                stats['skipped_status'] += 1
                continue
            cur.execute("UPDATE dualuse_chemicals SET names_ar = %s, ar_status = %s WHERE id = %s",
                        ([n.strip() for n in rec.get('names_ar') or [] if n.strip()][:12], status, row['id']))
            stats['chemicals'] += 1
            continue
        if lst == 'chpl':
            cur.execute("""UPDATE dualuse_hs_map m SET description_ar = %s FROM dualuse_list_versions v, dualuse_lists l
                           WHERE v.id = m.version_id AND v.is_current AND l.id = v.list_id AND l.code = 'chpl'
                           AND m.hs6 = %s""", (rec.get('text_ar'), re.sub(r'\D', '', code or '')))
            stats['priority' if cur.rowcount else 'not_found'] += 1
            continue
        cur.execute("""SELECT i.id, i.text_en, i.ar_status FROM dualuse_items i
                       JOIN dualuse_list_versions v ON v.id = i.version_id AND v.is_current
                       JOIN dualuse_lists l ON l.id = v.list_id AND l.code = %s WHERE i.code = %s""", (lst, code))
        row = cur.fetchone()
        if not row:
            stats['not_found'] += 1
            problems.append((lst, code, 'not found'))
            continue
        if rec.get('source_en') and norm_ws(rec['source_en']) != norm_ws(row['text_en']):
            stats['skipped_source_changed'] += 1
            problems.append((lst, code, 'English text changed since translation'))
            continue
        if row['ar_status'] != 'stale' and RANK[status] < RANK.get(row['ar_status'], 0):
            stats['skipped_status'] += 1
            continue
        cur.execute("""UPDATE dualuse_items SET title_ar = COALESCE(%s, title_ar), text_ar = COALESCE(%s, text_ar),
                       ar_status = %s, ar_updated_at = now() WHERE id = %s""",
                    (norm_ws(rec.get('title_ar')) or None, norm_ws(rec.get('text_ar')) or None, status, row['id']))
        stats['items'] += 1
        for pname, par in (rec.get('parameters_ar') or {}).items():
            cur.execute("UPDATE dualuse_parameters SET parameter_ar = %s WHERE item_id = %s AND parameter = %s",
                        (par.strip()[:200], row['id'], pname))
            stats['params'] += cur.rowcount
    print(stats)
    for p in problems[:30]:
        print('  ', *p)
    if a.apply:
        conn.commit()
        print('applied')
    else:
        conn.rollback()
        print('DRY RUN - nothing written (use --apply)')
    conn.close()


if __name__ == '__main__':
    main()
