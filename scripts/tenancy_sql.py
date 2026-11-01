#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Generate the SQL for tenant isolation (P6-1). It only READS the schema of the target
database and PRINTS SQL; it never changes anything. Apply the output by hand, phase by
phase, as described in docs/TENANCY.md.

    scripts/tenancy_sql.py --db complynex_db --phase report
    scripts/tenancy_sql.py --db <db> --phase prepare  > prepare.sql   # columns, indexes, policies (RLS still off)
    scripts/tenancy_sql.py --db <db> --phase enforce  > enforce.sql   # strict default + ENABLE/FORCE RLS
    scripts/tenancy_sql.py --db <db> --phase relax    > relax.sql     # back to RLS off (emergency)

prepare is safe on a live system: ADD COLUMN ... DEFAULT 1 is a metadata change in
PostgreSQL 11+, the default then becomes "the tenant of the session, else 1", and the
policies exist but do nothing until enforce enables RLS.
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from database.tenancy import classify, SETTING, DEFAULT_TENANT   # noqa: E402

CUR = f"NULLIF(current_setting('{SETTING}', true), '')::int"
POLICY = 'cx_tenant_isolation'


def q(ident):
    return '"' + ident.replace('"', '""') + '"'


def idx_name(table):
    return ('cxt_' + table)[:60]


def tables_of(conn):
    cur = conn.cursor()
    cur.execute("""SELECT c.relname,
                          EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                                  AND a.attname = 'tenant_id' AND NOT a.attisdropped) AS has_tid,
                          c.relrowsecurity, c.relforcerowsecurity, c.reltuples::bigint
                   FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 1""")
    return [dict(zip(('table', 'has_tid', 'rls', 'force', 'rows'), r)) for r in cur.fetchall()]


def unique_constraints(conn, table):
    cur = conn.cursor()
    cur.execute("""SELECT con.conname, pg_get_constraintdef(con.oid)
                   FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
                   WHERE c.relname = %s AND con.contype = 'u'""", (table,))
    return cur.fetchall()


def sql_prepare(tables):
    out = ["-- ComplyNex tenancy: PREPARE (columns, indexes, policies; RLS stays OFF)",
           "BEGIN;",
           "CREATE TABLE IF NOT EXISTS tenants (",
           "    id          SERIAL PRIMARY KEY,",
           "    code        TEXT UNIQUE NOT NULL,",
           "    name        TEXT NOT NULL,",
           "    regulator   TEXT,",
           "    db_mode     TEXT NOT NULL DEFAULT 'shared',   -- shared | dedicated (own database)",
           "    is_active   INTEGER NOT NULL DEFAULT 1,",
           "    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()",
           ");",
           f"INSERT INTO tenants (id, code, name) VALUES ({DEFAULT_TENANT}, 'default', 'Default tenant') "
           "ON CONFLICT (id) DO NOTHING;",
           "SELECT setval('tenants_id_seq', GREATEST((SELECT max(id) FROM tenants), 1));",
           "GRANT SELECT ON tenants TO complynex;"]
    for t in tables:
        kind = classify(t['table'])
        tq = q(t['table'])
        if kind in ('shared', 'system'):
            continue
        if kind == 'mixed':
            out += [f"ALTER TABLE {tq} ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id);",
                    f"CREATE INDEX IF NOT EXISTS {idx_name(t['table'])} ON {tq} (tenant_id) WHERE tenant_id IS NOT NULL;",
                    f"DROP POLICY IF EXISTS {POLICY} ON {tq};",
                    f"CREATE POLICY {POLICY} ON {tq} USING (tenant_id IS NULL OR tenant_id = {CUR}) "
                    f"WITH CHECK (tenant_id = {CUR});"]
            continue
        out += [f"ALTER TABLE {tq} ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT {DEFAULT_TENANT};",
                f"ALTER TABLE {tq} ALTER COLUMN tenant_id SET DEFAULT COALESCE({CUR}, {DEFAULT_TENANT});",
                f"DO $$ BEGIN ALTER TABLE {tq} ADD CONSTRAINT {q(('cxt_fk_' + t['table'])[:60])} "
                f"FOREIGN KEY (tenant_id) REFERENCES tenants(id) NOT VALID; "
                f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
                f"CREATE INDEX IF NOT EXISTS {idx_name(t['table'])} ON {tq} (tenant_id);"]
        if kind == 'tenant':
            out += [f"DROP POLICY IF EXISTS {POLICY} ON {tq};",
                    f"CREATE POLICY {POLICY} ON {tq} USING (tenant_id = {CUR}) WITH CHECK (tenant_id = {CUR});"]
    out.append("COMMIT;")
    return out


def sql_enforce(tables):
    out = ["-- ComplyNex tenancy: ENFORCE (run only after docs/TENANCY.md 'before enforcing' is done)",
           "BEGIN;"]
    for t in tables:
        kind = classify(t['table'])
        tq = q(t['table'])
        if kind == 'tenant':
            out += [f"ALTER TABLE {tq} ALTER COLUMN tenant_id SET DEFAULT {CUR};",   # no tenant -> NOT NULL error
                    f"ALTER TABLE {tq} ENABLE ROW LEVEL SECURITY;",
                    f"ALTER TABLE {tq} FORCE ROW LEVEL SECURITY;"]
        elif kind == 'mixed':
            out += [f"ALTER TABLE {tq} ENABLE ROW LEVEL SECURITY;", f"ALTER TABLE {tq} FORCE ROW LEVEL SECURITY;"]
        elif kind == 'tagged':
            out += [f"ALTER TABLE {tq} ALTER COLUMN tenant_id SET DEFAULT {CUR};"]
    out += ["-- maintenance role for list loaders, backups and migrations (sees every tenant)",
            "DO $$ BEGIN CREATE ROLE complynex_maint NOLOGIN BYPASSRLS; "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
            "-- give it a LOGIN password and the table grants of complynex by hand, and point the",
            "-- list loaders / sync jobs at it (MAINT_DB_USER in .env); never grant it to complynex.",
            "COMMIT;"]
    return out


def sql_relax(tables):
    out = ["-- ComplyNex tenancy: RELAX (RLS off again; columns and policies are kept)", "BEGIN;"]
    for t in tables:
        kind = classify(t['table'])
        tq = q(t['table'])
        if kind in ('tenant', 'mixed'):
            out += [f"ALTER TABLE {tq} NO FORCE ROW LEVEL SECURITY;",
                    f"ALTER TABLE {tq} DISABLE ROW LEVEL SECURITY;"]
        if kind in ('tenant', 'tagged'):
            out += [f"ALTER TABLE {tq} ALTER COLUMN tenant_id SET DEFAULT COALESCE({CUR}, {DEFAULT_TENANT});"]
    out.append("COMMIT;")
    return out


def report(conn, tables):
    by = {}
    for t in tables:
        by.setdefault(classify(t['table']), []).append(t)
    print(f"{'class':8} {'tables':>6} {'rows (est.)':>14}")
    for k in ('tenant', 'tagged', 'mixed', 'shared', 'system'):
        v = by.get(k, [])
        print(f"{k:8} {len(v):>6} {sum(max(0, t['rows']) for t in v):>14,}")
    uniq = [(t['table'], n, d) for t in by.get('tenant', []) + by.get('tagged', [])
            for n, d in unique_constraints(conn, t['table']) if 'tenant_id' not in d]
    print(f"\nunique constraints without tenant_id on tenant tables: {len(uniq)} "
          "(each must become UNIQUE (tenant_id, ...) before a 2nd tenant is added)")
    for tb, n, d in uniq:
        print(f"  {tb}: {n} {d}")
    done = [t['table'] for t in tables if t['has_tid']]
    print(f"\ntables that already have tenant_id: {len(done)}; with RLS enabled: "
          f"{sum(1 for t in tables if t['rls'])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True, help='database to read the schema from')
    ap.add_argument('--phase', required=True, choices=('report', 'prepare', 'enforce', 'relax'))
    a = ap.parse_args()
    import psycopg2
    from config import Config
    cfg = dict(Config.POSTGRES_CONFIG)
    cfg.pop('database', None)
    cfg['dbname'] = a.db
    conn = psycopg2.connect(**cfg)
    conn.set_session(readonly=True)
    tables = tables_of(conn)
    if a.phase == 'report':
        report(conn, tables)
    else:
        fn = {'prepare': sql_prepare, 'enforce': sql_enforce, 'relax': sql_relax}[a.phase]
        print('\n'.join(fn(tables)))
    conn.close()


if __name__ == '__main__':
    main()
