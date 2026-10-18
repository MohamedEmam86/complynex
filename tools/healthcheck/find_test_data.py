#!/usr/bin/env python3
"""
Hunt for leftover verification/test rows in the production database.

A previous automated verification run created records like
'_VERIFY_TEST_COMMITTEE_DO_NOT_KEEP' and left them behind. They pollute real
compliance data (they show up in counts, reports and CBE/FRA extracts) and
in this case one of them pointed at a non-existent file and produced a 404.

Scans every text column of every table for the usual test markers.
"""
import sys

sys.path.insert(0, '/var/www/complynex')
from app import create_app  # noqa: E402
from database.db import get_db  # noqa: E402

MARKERS = ['_VERIFY', 'DO_NOT_KEEP', 'TEST_ONLY', '__TEST__',
           'DELETEME', 'DUMMY_TEST', 'XXTEST']

app = create_app()


def main():
    with app.app_context():
        db = get_db()
        cur = db.execute("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type IN ('character varying', 'text', 'character')
            ORDER BY table_name, column_name
        """)
        cols = cur.fetchall()

        # rows come back as dict-like (RealDictCursor), so index by name --
        # unpacking `for t, c in cols` would iterate the KEYS, not the values.
        by_table = {}
        for row in cols:
            t = row['table_name']
            c = row['column_name']
            by_table.setdefault(t, []).append(c)

        hits = 0
        for table, columns in by_table.items():
            # Use strpos(), NOT LIKE: every marker contains '_', which LIKE
            # treats as a single-character wildcard ('_VERIFY' would match
            # "XVERIFY"), producing hundreds of false positives against a
            # 2.7M-row sanctions watchlist. strpos() is a literal search.
            where = ' OR '.join(
                "strpos(\"%s\", '%s') > 0" % (c, m)
                for c in columns for m in MARKERS)
            sql = 'SELECT * FROM "%s" WHERE %s' % (table, where)
            try:
                cur = db.execute(sql)
                rows = cur.fetchall()
            except Exception as e:
                print('  !! %-30s %s' % (table, str(e).split('\n')[0][:90]))
                try:
                    db.rollback()
                except Exception:
                    pass
                continue
            if rows:
                print('\n### %s  (%d row(s))' % (table, len(rows)))
                for r in rows[:10]:
                    d = dict(r) if hasattr(r, 'keys') else r
                    if isinstance(d, dict):
                        slim = {k: v for k, v in d.items()
                                if v not in (None, '', 0, False)}
                        print('   ', slim)
                    else:
                        print('   ', d)
                hits += len(rows)

        print('\nTOTAL suspect rows: %d' % hits)


if __name__ == '__main__':
    main()
