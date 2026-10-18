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

import logging
import os
import sqlite3
import sys
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from psycopg2 import pool as pg_pool
except ImportError:
    psycopg2 = None
    pg_pool = None

# Single source of truth — same dict the live app connects with
# (config.Config.POSTGRES_CONFIG), not a separate hardcoded copy that can
# drift from it.
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
from config import Config

_PG_CONFIG = dict(Config.POSTGRES_CONFIG)


class PostgresConnectionWrapper:
    """Full connection wrapper: translates SQLite ? to %s, mocks row_factory."""
    def __init__(self, conn):
        self._conn = conn
        self.row_factory = None  # Mock SQLite attribute

    def cursor(self, *args, **kwargs):
        kwargs.setdefault('cursor_factory', RealDictCursor)
        return PostgresCursorWrapper(self._conn.cursor(*args, **kwargs), self._conn)

    def execute(self, query, vars=None):
        cur = self.cursor()
        cur.execute(query, vars)
        return cur

    def commit(self): self._conn.commit()
    def rollback(self): self._conn.rollback()
    def close(self): pass  # Pool handles this

    def __getattr__(self, name):
        if name in self.__dict__:
            return self.__dict__[name]
        return getattr(self._conn, name)


class PostgresCursorWrapper:
    """Cursor wrapper: translates ? to %s."""
    def __init__(self, cursor, conn):
        self._cursor = cursor
        self._conn = conn

    def execute(self, query, vars=None):
        if isinstance(query, str):
            query = query.replace('?', '%s')
        try:
            self._cursor.execute(query, vars) if vars is not None else self._cursor.execute(query)
        except Exception as e:
            try: self._conn.rollback()
            except: pass
            raise e
        return self

    def executemany(self, query, vars_list):
        if isinstance(query, str):
            query = query.replace('?', '%s')
        try:
            self._cursor.executemany(query, vars_list)
        except Exception as e:
            try: self._conn.rollback()
            except: pass
            raise e
        return self

    @property
    def lastrowid(self):
        try:
            self._cursor.execute("SELECT lastval()")
            res = self._cursor.fetchone()
            if isinstance(res, dict):
                return res.get('lastval') or res.get('last_value')
            return res[0] if res else None
        except Exception:
            try: self._conn.rollback()
            except: pass
            return None

    def fetchone(self): return self._cursor.fetchone() if self._cursor else None
    def fetchall(self): return self._cursor.fetchall() if self._cursor else []

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)


class DatabasePool:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabasePool, cls).__new__(cls)
            cls._instance.pool = None
            cls._instance.db_type = 'postgres'
            cls._instance.db_config = _PG_CONFIG.copy()
        return cls._instance

    def initialize(self, db_config=None):
        """Called by engine — always uses PostgreSQL config from env."""
        self.db_type = 'postgres'
        self.db_config = _PG_CONFIG.copy()
        if not self.pool:
            self._init_pool()

    def _init_pool(self):
        try:
            self.pool = pg_pool.ThreadedConnectionPool(1, 20, **self.db_config)
            logger.info("✅ Screening Engine Postgres Pool Active")
        except Exception as e:
            logger.error(f"❌ Screening Pool Init Failed: {e}")
            self.pool = None

    def checkout_connection(self):
        if not self.pool:
            self._init_pool()
        if not self.pool:
            raise Exception("Screening DB pool unavailable")
        return PostgresConnectionWrapper(self.pool.getconn())

    def return_connection(self, conn):
        if not conn or not self.pool:
            return
        raw = conn._conn if hasattr(conn, '_conn') else conn
        try:
            self.pool.putconn(raw)
        except Exception as e:
            logger.warning(f"Error returning screening connection: {e}")

    @contextmanager
    def get_connection(self):
        conn = self.checkout_connection()
        try:
            yield conn
        finally:
            self.return_connection(conn)

    def _sqlite_dict_factory(self, cursor, row):
        return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


# Global singleton — auto-initializes on import
db_pool = DatabasePool()
db_pool.initialize()
