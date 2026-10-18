#!/usr/bin/env python3
"""Audit whether false-positive resolutions actually reached the whitelist."""
import sys
sys.path.insert(0, '/var/www/complynex')
from app import create_app
from database.db import get_db

app = create_app()

Q = [
 ("distinct FP entity names in queue",
  "SELECT count(DISTINCT upper(trim(entity_name))) AS c FROM screening_queue "
  "WHERE resolution LIKE '%%False Positive%%'"),
 ("active whitelist rows",
  "SELECT count(*) AS c FROM screening_whitelist WHERE status = 'Active'"),
 ("total whitelist rows",
  "SELECT count(*) AS c FROM screening_whitelist"),
 ("FP names NOT in whitelist",
  """SELECT count(*) AS c FROM (
       SELECT DISTINCT upper(trim(q.entity_name)) AS n
         FROM screening_queue q
        WHERE q.resolution LIKE '%%False Positive%%'
     ) x
     WHERE NOT EXISTS (
       SELECT 1 FROM screening_whitelist w
        WHERE upper(trim(w.normalized_name)) = x.n
           OR upper(trim(w.name)) = x.n)"""),
 ("sample FP names missing from whitelist",
  """SELECT DISTINCT upper(trim(q.entity_name)) AS n, q.resolution
       FROM screening_queue q
      WHERE q.resolution LIKE '%%False Positive%%'
        AND NOT EXISTS (
          SELECT 1 FROM screening_whitelist w
           WHERE upper(trim(w.normalized_name)) = upper(trim(q.entity_name))
              OR upper(trim(w.name)) = upper(trim(q.entity_name)))
      LIMIT 10"""),
 ("true-match resolutions",
  "SELECT count(*) AS c FROM screening_queue "
  "WHERE resolution LIKE '%%True Match%%'"),
 ("internal_blacklist rows",
  "SELECT count(*) AS c FROM internal_blacklist"),
 ("true-match names NOT in internal_blacklist",
  """SELECT count(*) AS c FROM (
       SELECT DISTINCT upper(trim(entity_name)) AS n FROM screening_queue
        WHERE resolution LIKE '%%True Match%%') x
      WHERE NOT EXISTS (
        SELECT 1 FROM internal_blacklist b
         WHERE upper(trim(b.full_name)) = x.n)"""),
]

with app.app_context():
    db = get_db()
    for label, q in Q:
        try:
            cur = db.execute(q)
            rows = cur.fetchall()
            if len(rows) == 1 and 'c' in dict(rows[0]):
                print('%-45s %s' % (label, dict(rows[0])['c']))
            else:
                print('%s:' % label)
                for r in rows:
                    print('    ', dict(r))
        except Exception as e:
            print('%-45s ERR %s' % (label, str(e).split(chr(10))[0][:70]))
            db.rollback()
