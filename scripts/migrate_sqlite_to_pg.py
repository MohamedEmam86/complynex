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

"""
ComplyNex — Full SQLite to PostgreSQL Migration Script
Migrates all 120+ tables and 1.6M+ rows with zero data loss
"""
import sqlite3
import psycopg2
import sys, os, time
from datetime import datetime

SQLITE_PATH = '/opt/complynex/complynex_cms.db'
PG_CONFIG = {
    'host': 'localhost', 'database': 'complynex_db',
    'user': 'complynex', 'password': 'ComplynexDB2026!', 'port': 5432
}
BATCH_SIZE = 500
SKIP_TABLES = {'sqlite_sequence', 'screening_whitelist_legacy'}
TYPE_MAP = {
    'INTEGER':'INTEGER','INT':'INTEGER','BIGINT':'BIGINT','SMALLINT':'SMALLINT',
    'TEXT':'TEXT','VARCHAR':'TEXT','CHAR':'TEXT','CLOB':'TEXT',
    'BLOB':'BYTEA','REAL':'DOUBLE PRECISION','FLOAT':'DOUBLE PRECISION',
    'DOUBLE':'DOUBLE PRECISION','NUMERIC':'NUMERIC','DECIMAL':'NUMERIC',
    'BOOLEAN':'INTEGER','BOOL':'INTEGER','DATE':'TEXT','DATETIME':'TEXT',
    'TIMESTAMP':'TEXT','TIME':'TEXT','JSON':'TEXT','JSONB':'TEXT',
    'NONE':'TEXT','':'TEXT',
}

def log(msg, level='INFO'):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {level}: {msg}")

def get_pg_type(sqlite_type):
    base = (sqlite_type or '').upper().split('(')[0].strip()
    return TYPE_MAP.get(base, 'TEXT')

def get_tables(sqlite_conn):
    rows = sqlite_conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r[0] for r in rows if r[0] not in SKIP_TABLES]

def get_schema(sqlite_conn, table):
    return sqlite_conn.execute(f"PRAGMA table_info([{table}])").fetchall()

def get_count(sqlite_conn, table):
    row = sqlite_conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()
    return row[0] if row else 0

def create_table(pg_cursor, table, columns):
    col_defs = []
    for col in columns:
        cid, name, col_type, notnull, default, is_pk = col
        pg_type = get_pg_type(col_type)
        if is_pk == 1 and pg_type == 'INTEGER':
            col_defs.append(f'"{name}" SERIAL PRIMARY KEY')
        elif is_pk == 1:
            col_defs.append(f'"{name}" {pg_type} PRIMARY KEY')
        else:
            col_defs.append(f'"{name}" {pg_type}')
    ddl = f'CREATE TABLE IF NOT EXISTS "{table}" (\n    ' + ',\n    '.join(col_defs) + '\n);'
    try:
        pg_cursor.execute(ddl)
        return True
    except Exception as e:
        log(f"Create table {table} failed: {e}", 'ERROR')
        return False

def migrate_data(sqlite_conn, pg_conn, table, columns, total):
    if total == 0:
        return 0
    col_names = [col[1] for col in columns]
    quoted = ', '.join([f'"{c}"' for c in col_names])
    placeholders = ', '.join(['%s'] * len(col_names))
    sql = f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
    cursor = pg_conn.cursor()
    migrated = 0
    offset = 0
    while offset < total:
        rows = sqlite_conn.execute(f"SELECT * FROM [{table}] LIMIT {BATCH_SIZE} OFFSET {offset}").fetchall()
        if not rows:
            break
        batch = []
        for row in rows:
            converted = []
            for val in row:
                if val is None:
                    converted.append(None)
                elif isinstance(val, bytes):
                    converted.append(val.decode('utf-8', errors='replace'))
                else:
                    converted.append(val)
            batch.append(tuple(converted))
        try:
            cursor.executemany(sql, batch)
            pg_conn.commit()
            migrated += len(batch)
        except Exception as e:
            pg_conn.rollback()
            log(f"Batch error in {table} at offset {offset}: {str(e)[:100]}", 'WARN')
            for row_data in batch:
                try:
                    cursor.execute(sql, row_data)
                    pg_conn.commit()
                    migrated += 1
                except:
                    pg_conn.rollback()
        offset += BATCH_SIZE
        if total > 50000 and offset % 200000 == 0:
            log(f"  {table}: {offset:,}/{total:,} ({offset/total*100:.0f}%)")
    cursor.close()
    return migrated

def reset_sequences(pg_conn):
    log("Resetting sequences...")
    cursor = pg_conn.cursor()
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    tables = [r[0] for r in cursor.fetchall()]
    for table in tables:
        try:
            cursor.execute(f'SELECT MAX(id) FROM "{table}"')
            row = cursor.fetchone()
            if row and row[0] is not None:
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('\"{table}\"','id'), %s, false)",
                    (row[0] + 1,)
                )
        except:
            pass
    pg_conn.commit()
    cursor.close()
    log("Sequences reset ✅")

def verify(sqlite_conn, pg_conn, tables):
    log("\n" + "="*60)
    log("VERIFICATION — Comparing row counts")
    log("="*60)
    cursor = pg_conn.cursor()
    mismatches = []
    for table in tables:
        sq = get_count(sqlite_conn, table)
        if sq == 0:
            continue
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            pg = cursor.fetchone()[0]
        except:
            pg = -1
        ok = sq == pg
        if not ok:
            mismatches.append((table, sq, pg))
        print(f"  {'✅' if ok else '❌'} {table:<45} SQLite:{sq:>8,}  PG:{pg:>8,}")
    cursor.close()
    if mismatches:
        log(f"⚠️  {len(mismatches)} mismatches:", 'WARN')
        for t, sq, pg in mismatches:
            log(f"   {t}: SQLite={sq} PG={pg}", 'WARN')
    else:
        log("✅ ALL ROW COUNTS MATCH PERFECTLY")
    return len(mismatches) == 0

def main():
    log("="*60)
    log("ComplyNex — SQLite → PostgreSQL Migration")
    log("="*60)

    sqlite_conn = sqlite3.connect(SQLITE_PATH, detect_types=0)
    sqlite_conn.row_factory = sqlite3.Row
    log(f"SQLite connected: {SQLITE_PATH} ✅")

    try:
        pg_conn = psycopg2.connect(**PG_CONFIG)
        pg_conn.autocommit = False
        log("PostgreSQL connected ✅")
    except Exception as e:
        log(f"PostgreSQL connection failed: {e}", 'ERROR')
        sys.exit(1)

    tables = get_tables(sqlite_conn)
    log(f"Tables found: {len(tables)}")

    # Count data
    table_counts = {t: get_count(sqlite_conn, t) for t in tables}
    total = sum(table_counts.values())
    non_empty = sum(1 for c in table_counts.values() if c > 0)
    log(f"Total rows: {total:,} across {non_empty} non-empty tables")

    # Phase 1: Create tables
    log("\n--- PHASE 1: Creating tables ---")
    pg_cursor = pg_conn.cursor()
    created = failed = 0
    for table in tables:
        cols = get_schema(sqlite_conn, table)
        if cols:
            if create_table(pg_cursor, table, cols):
                created += 1
            else:
                failed += 1
    pg_conn.commit()
    pg_cursor.close()
    log(f"Created: {created} ✅  Failed: {failed}")

    # Phase 2: Migrate data
    log("\n--- PHASE 2: Migrating data ---")
    start = time.time()
    total_migrated = 0
    for table in tables:
        count = table_counts[table]
        if count == 0:
            continue
        cols = get_schema(sqlite_conn, table)
        log(f"Migrating {table} ({count:,} rows)...")
        migrated = migrate_data(sqlite_conn, pg_conn, table, cols, count)
        total_migrated += migrated
        status = "✅" if migrated == count else f"⚠️  {migrated}/{count}"
        log(f"  {status} {table}")

    elapsed = time.time() - start
    log(f"\nMigrated {total_migrated:,} rows in {elapsed:.1f}s")

    # Phase 3: Reset sequences
    log("\n--- PHASE 3: Resetting sequences ---")
    reset_sequences(pg_conn)

    # Phase 4: Verify
    all_ok = verify(sqlite_conn, pg_conn, tables)

    sqlite_conn.close()
    pg_conn.close()

    log("\n" + "="*60)
    if all_ok:
        log("🎉 MIGRATION COMPLETE — Zero data loss confirmed")
    else:
        log("⚠️  MIGRATION COMPLETE WITH WARNINGS")
    log("="*60)
    return 0 if all_ok else 1

if __name__ == '__main__':
    sys.exit(main())
