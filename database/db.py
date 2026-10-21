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
Database connection helper - Production grade with connection pooling.
"""
import sqlite3
import logging
import os
import threading
from flask import current_app, g
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from psycopg2 import pool as pg_pool
except ImportError:
    psycopg2 = None
    RealDictCursor = None
    pg_pool = None

# Global connection pool — shared across all workers via app context
_connection_pool = None

# Guards pool creation against a concurrency bug that was causing severe,
# fast-onset memory blowups (one gunicorn worker observed at 11GB RSS within
# minutes of starting, triggering an OOM kill). Root cause: gunicorn.conf.py's
# post_fork hook resets _connection_pool to None so each worker builds its own
# pool lazily on first use (see get_db() below). Under the gevent worker
# class, many requests run as cooperative greenlets in the SAME OS process,
# and pg_pool.ThreadedConnectionPool(...) performs blocking socket I/O
# (opening minconn=2 real connections to Postgres) that gevent's monkey-patch
# turns into a yield point. If several requests hit a freshly-forked worker
# at the same moment (health checks, multiple users, a burst right after a
# deploy), each one's greenlet observes `_connection_pool is None`, starts
# creating its OWN pool, yields mid-connect, and by the time it resumes the
# global has already been overwritten by another greenlet's pool — the
# earlier pool(s) become orphaned: their live Postgres connections are never
# closed and are no longer reachable to be reused or torn down, so they just
# leak until the process dies. Under a bursty cold start this can spin up
# many such orphaned pools in seconds, which is consistent with the observed
# meteoric (minutes-scale, not days-scale) RSS growth. A plain lock serializes
# pool creation so only the first greenlet ever builds it; everyone else
# waits and then reuses the same pool instance. Because gunicorn.conf.py runs
# gevent.monkey.patch_all() before this module is imported, threading.Lock()
# here is transparently the gevent-cooperative lock, not a real OS lock — no
# extra dependency needed.
_pool_lock = threading.Lock()


def init_pool(app):
    """Initialize PostgreSQL connection pool.

    Safe to call more than once and safe to call concurrently from multiple
    greenlets/threads — only the first caller actually creates the pool;
    everyone else is a no-op. See the note above _pool_lock for why this
    matters (it's the fix for a real production OOM incident, not
    defensive-for-its-own-sake).
    """
    global _connection_pool
    if app.config.get('DB_TYPE') != 'postgresql':
        return
    if _connection_pool is not None:
        return
    with _pool_lock:
        # Re-check inside the lock: another greenlet may have already built
        # the pool while we were waiting our turn.
        if _connection_pool is not None:
            return
        try:
            _connection_pool = pg_pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=20,  # Max 20 pooled connections — well within PG's 100 limit
                cursor_factory=RealDictCursor,
                # TCP keepalives so a dead peer (idle connection silently dropped by
                # Postgres or a network device) is detected at the socket level
                # instead of only surfacing on the next query.
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3,
                **app.config['POSTGRES_CONFIG']
            )
            logger.info("✅ PostgreSQL connection pool initialized (min=2, max=20)")
        except Exception as e:
            logger.error(f"❌ Failed to initialize connection pool: {e}")
            raise


class DictRow(dict):
    """Dict that also supports index access like sqlite3.Row"""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class DictCursor:
    """Cursor wrapper that returns DictRow objects"""
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, args=()):
        self._cursor.execute(query, args)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return DictRow(row)
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [DictRow(r) if isinstance(r, dict) else r for r in rows]

    def close(self):
        self._cursor.close()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cursor, 'lastrowid', None)

    def __iter__(self):
        return iter(self.fetchall())


class PgConnectionWrapper:
    """
    Wraps a pooled psycopg2 connection with SQLite-compatible interface.
    Returns the connection to the pool on close() instead of destroying it.
    """
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._closed = False

    def execute(self, query, args=()):
        try:
            cursor = self._conn.cursor()
            cursor.execute(query, args)
            return DictCursor(cursor)
        except (BrokenPipeError, OSError) as pipe_err:
            # OS-level pipe to PostgreSQL is broken — swap in a fresh connection
            # and retry once.  This happens when an idle pooled connection is
            # dropped by the server or a network device.
            logger.warning(f"Broken pipe on DB execute, reconnecting: {pipe_err}")
            self._replace_connection()
            cursor = self._conn.cursor()
            cursor.execute(query, args)
            return DictCursor(cursor)
        except Exception:
            if psycopg2 and self._is_connection_dead():
                logger.warning("Dead pooled connection detected, reconnecting")
                self._replace_connection()
                cursor = self._conn.cursor()
                cursor.execute(query, args)
                return DictCursor(cursor)
            raise

    def _is_connection_dead(self):
        try:
            if getattr(self._conn, 'closed', 0):
                return True
            # rollback() is a cheap round-trip that also recovers a connection
            # sitting in an aborted-transaction state (a normal SQL error, not a
            # dead connection) — checking only `.closed` misses connections the
            # server or network silently dropped while idle, since psycopg2
            # doesn't flip `.closed` until an operation is actually attempted.
            self._conn.rollback()
            return False
        except Exception:
            return True

    def _replace_connection(self):
        """Return the dead connection to the pool and check out a fresh one."""
        try:
            if self._pool and self._conn:
                self._pool.putconn(self._conn, close=True)
        except Exception:
            pass
        if self._pool:
            self._conn = self._pool.getconn()
            self._closed = False

    def executemany(self, query, args_list):
        cursor = self._conn.cursor()
        cursor.executemany(query, args_list)
        return cursor

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        """Return connection to pool instead of closing it."""
        if not self._closed and self._pool and self._conn:
            try:
                self._conn.rollback()  # Clean state before returning to pool
                self._pool.putconn(self._conn)
            except Exception as e:
                logger.warning(f"Error returning connection to pool: {e}")
            self._closed = True

    def cursor(self):
        return DictCursor(self._conn.cursor())

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_db():
    """
    Get database connection for current request.
    PostgreSQL: pulls from connection pool (fast, reuses existing connections).
    SQLite: creates file connection as before.
    """
    if 'db' not in g:
        db_type = current_app.config.get('DB_TYPE', 'sqlite')

        if db_type == 'postgresql':
            global _connection_pool
            if _connection_pool is None:
                # Fallback: initialize pool if not done at startup
                init_pool(current_app._get_current_object())

            raw_conn = None
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    raw_conn = _connection_pool.getconn()
                    # Pre-ping: a connection can sit idle in the pool long enough
                    # for Postgres or a network device to silently close it. If we
                    # hand it out as-is, the first query on it fails with a
                    # user-facing 500 (e.g. "SSL connection has been closed
                    # unexpectedly"). rollback() is a cheap round-trip that raises
                    # immediately if the connection is actually dead, so we can
                    # discard it and get a fresh one before any request code sees it.
                    raw_conn.rollback()
                    break
                except Exception as e:
                    logger.warning(f"Discarding dead pooled connection (attempt {attempt}/{max_attempts}): {e}")
                    if raw_conn is not None:
                        try:
                            _connection_pool.putconn(raw_conn, close=True)
                        except Exception:
                            pass
                        raw_conn = None
                    if attempt == max_attempts:
                        logger.error("Failed to obtain a live DB connection after pre-ping retries")
                        raise

            g.db = PgConnectionWrapper(raw_conn, _connection_pool)
        else:
            g.db = sqlite3.connect(
                current_app.config['DATABASE'],
                detect_types=0,
                timeout=30.0
            )
            g.db.execute('PRAGMA journal_mode=WAL;')
            g.db.execute('PRAGMA synchronous=NORMAL;')
            g.db.row_factory = sqlite3.Row

    return g.db


def close_db(e=None):
    """Return connection to pool at end of request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Initialize database with schema."""
    db = get_db()
    db_type = current_app.config.get('DB_TYPE', 'sqlite')
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    if db_type == 'postgresql':
        cursor = db.cursor()
        cursor.execute(schema_sql)
        cursor.close()
    else:
        db.executescript(schema_sql)
    import secrets as _secrets
    _initial_pw = _secrets.token_urlsafe(14) + 'A1!'
    admin_password_hash = generate_password_hash(_initial_pw)
    print(f"Initial admin password (shown once, change it at first login): {_initial_pw}")
    param = "%s" if db_type == 'postgresql' else "%s"
    db.execute(
        f"UPDATE users SET password_hash = {param} WHERE email = 'admin@complynex.online'",
        (admin_password_hash,)
    )
    db.commit()
    print(f"Database ({db_type}) initialized successfully!")


def init_app(app):
    """Register database functions with Flask app."""
    app.teardown_appcontext(close_db)
    # Initialize pool at app startup
    with app.app_context():
        if app.config.get('DB_TYPE') == 'postgresql':
            init_pool(app)


def query_db(query, args=(), one=False):
    """Execute a query and return results."""
    db = get_db()
    db_type = current_app.config.get('DB_TYPE', 'sqlite')
    if db_type == 'postgresql':
        cursor = db.cursor()
        cursor.execute(query, args)
        rv = cursor.fetchall()
        cursor.close()
        return (rv[0] if rv else None) if one else rv
    else:
        cur = db.execute(query, args)
        rv = cur.fetchall()
        cur.close()
        return (rv[0] if rv else None) if one else rv


def execute_db(query, args=()):
    """Execute a query that modifies data."""
    db = get_db()
    db_type = current_app.config.get('DB_TYPE', 'sqlite')
    if db_type == 'postgresql':
        cursor = db.cursor()
        cursor.execute(query, args)
        rowcount = cursor.rowcount
        db.commit()
        cursor.close()
        return rowcount
    else:
        cur = db.execute(query, args)
        db.commit()
        last_id = cur.lastrowid
        count = cur.rowcount
        cur.close()
        return last_id if last_id else count
