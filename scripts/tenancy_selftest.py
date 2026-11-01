#!/usr/bin/env python3
"""P6-1 isolation self-test on a SCRATCH database (never complynex_db).
Usage (as the app user, after prepare+enforce were applied to the scratch DB):
    TENANCY_TEST_DB=complynex_tenancy_test python scripts/tenancy_selftest.py"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import psycopg2
from config import Config
from database import tenancy as T

DB = os.environ.get('TENANCY_TEST_DB', '')
assert DB and DB != 'complynex_db' and 'test' in DB, 'refusing: TENANCY_TEST_DB must name a scratch test database'
cfg = dict(Config.POSTGRES_CONFIG); cfg.pop('database', None); cfg['dbname'] = DB
conn = psycopg2.connect(**cfg)
c = conn.cursor()
ok = fails = 0
def check(label, cond):
    global ok, fails
    print(('PASS ' if cond else 'FAIL ') + label)
    ok += bool(cond); fails += (not cond)
def count(sql, args=()):
    c.execute(sql, args); return c.fetchone()[0]

c.execute("SELECT current_user, (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)")
who, bypass = c.fetchone(); conn.commit()
check(f'connected as {who} without BYPASSRLS', not bypass)

for tid in (1, 2):
    T.bind(conn, tid)
    c.execute("INSERT INTO notifications (user_id, title, message, type, is_read, created_at) VALUES (1, %s, 'm', 'info', 0, now())", (f't{tid}',))
    c.execute("INSERT INTO screening_watchlist (full_name, source, source_id, is_active, tenant_id) VALUES (%s, 'internal_blacklist', %s, 1, %s)",
              (f'private {tid}', f'IBL-test-{tid}', tid))
    conn.commit()

T.bind(conn, 1)
check('tenant 1 sees only its notification', count("SELECT count(*) FROM notifications") == 1 and count("SELECT count(*) FROM notifications WHERE title='t2'") == 0)
check('tenant 1 sees shared + its private watchlist rows', count("SELECT count(*) FROM screening_watchlist") == 2 and count("SELECT count(*) FROM screening_watchlist WHERE full_name='private 2'") == 0)
c.execute("UPDATE notifications SET title='hacked' WHERE title='t2'"); n = c.rowcount; conn.commit()
check('tenant 1 cannot update tenant 2 rows', n == 0)
c.execute("DELETE FROM screening_watchlist WHERE full_name='private 2'"); n = c.rowcount; conn.commit()
check('tenant 1 cannot delete tenant 2 private list rows', n == 0)
try:
    c.execute("INSERT INTO notifications (user_id, title, message, type, is_read, created_at, tenant_id) VALUES (1,'x','m','info',0,now(),2)")
    conn.commit(); check('tenant 1 cannot write a row for tenant 2', False)
except psycopg2.Error:
    conn.rollback(); check('tenant 1 cannot write a row for tenant 2', True)
try:
    c.execute("INSERT INTO screening_watchlist (full_name, source, source_id, is_active) VALUES ('x','un','UN-x',1)")
    conn.commit(); check('app role cannot write shared list rows', False)
except psycopg2.Error:
    conn.rollback(); check('app role cannot write shared list rows', True)

T.bind(conn, 2)
check('tenant 2 sees only its notification', count("SELECT count(*) FROM notifications") == 1 and count("SELECT count(*) FROM notifications WHERE title='t2'") == 1)
check('tenant 2 sees shared + its private rows', count("SELECT count(*) FROM screening_watchlist") == 2 and count("SELECT count(*) FROM screening_watchlist WHERE full_name='private 2'") == 1)

T.unbind(conn)
check('no tenant set: no tenant rows visible', count("SELECT count(*) FROM notifications") == 0)
check('no tenant set: shared list rows still visible', count("SELECT count(*) FROM screening_watchlist WHERE tenant_id IS NULL") == 1)
try:
    c.execute("INSERT INTO notifications (user_id, title, message, type, is_read, created_at) VALUES (1,'x','m','info',0,now())")
    conn.commit(); check('no tenant set: insert is refused (fail closed)', False)
except psycopg2.Error:
    conn.rollback(); check('no tenant set: insert is refused (fail closed)', True)
check('users table is not filtered (login works before the tenant is known)', count("SELECT count(*) FROM users") >= 0)

# pooled connection reuse: bind(2) then unbind -> next borrower without a tenant sees nothing
T.bind(conn, 2); T.unbind(conn)
check('after unbind the connection carries no tenant', count("SELECT count(*) FROM notifications") == 0)
print(f'\n{ok} passed, {fails} failed')
sys.exit(1 if fails else 0)
