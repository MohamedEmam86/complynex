"""Shared helpers for the demo data scripts."""
import json
import random
from datetime import date, datetime, timedelta

import psycopg2
import psycopg2.extras
from config import Config

COMPANY_EN = 'Nile Microfinance S.A.E.'
COMPANY_AR = 'شركة النيل للتمويل متناهي الصغر ش.م.م'
DOMAIN = 'nilemicro.example'


class Ctx:
    """Connection + the ids each area hands to the next."""

    def __init__(self):
        self.conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
        self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        self.rnd = random.Random(2026)
        self.today = date.today()
        self.now = datetime.now()
        self.users = {}      # key -> id
        self.depts = {}      # code -> departments.id
        self.units = {}      # code -> org_units.id
        self.data = {}       # free-form hand-over between areas
        self._cols = {}
        self.reload()

    def reload(self):
        """Pick up users / units created by earlier areas (lets one area run alone)."""
        for r in self.q("SELECT id, email FROM users WHERE email LIKE %s", (f'%@{DOMAIN}',)):
            key = r['email'].split('@')[0]
            self.users['admin' if key == 'demo.admin' else key] = r['id']
        for r in self.q("SELECT id, code, legacy_department_id FROM org_units"):
            self.units[r['code']] = r['id']
            if r['legacy_department_id']:
                self.depts[r['code']] = r['legacy_department_id']

    # -- sql
    def q(self, sql, args=None):
        self.cur.execute(sql, args)
        try:
            return self.cur.fetchall()
        except psycopg2.ProgrammingError:
            return []

    def one(self, sql, args=None):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def cols(self, table):
        if table not in self._cols:
            self.cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                             "WHERE table_schema='public' AND table_name=%s", (table,))
            self._cols[table] = {r['column_name']: r['data_type'] for r in self.cur.fetchall()}
            if not self._cols[table]:
                raise KeyError(f'no table {table}')
        return self._cols[table]

    def ins(self, table, **vals):
        """INSERT one row; unknown columns raise; returns id (or None)."""
        cols = self.cols(table)
        bad = set(vals) - set(cols)
        if bad:
            raise KeyError(f'{table}: unknown columns {sorted(bad)}')
        vals = {k: (json.dumps(v) if isinstance(v, dict) or (isinstance(v, list) and cols[k] != 'ARRAY') else v)
                for k, v in vals.items()}
        ks = list(vals)
        sql = (f'INSERT INTO "{table}" ({", ".join(chr(34) + k + chr(34) for k in ks)}) '
               f'VALUES ({", ".join(["%s"] * len(ks))})')
        if 'id' in cols:
            sql += ' RETURNING id'
        self.cur.execute(sql, [vals[k] for k in ks])
        return self.cur.fetchone()['id'] if 'id' in cols else None

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.commit()
        self.conn.close()

    # -- data helpers
    def ago(self, days, hour=None):
        d = self.now - timedelta(days=days)
        if hour is not None:
            d = d.replace(hour=hour, minute=self.rnd.randrange(60))
        return d

    def dago(self, days):
        return self.today - timedelta(days=days)

    def pick(self, seq):
        return self.rnd.choice(seq)

    def uid(self, key):
        return self.users[key]

    def user(self, key):
        """Full user row (names for 'created by' text columns)."""
        return self.one("SELECT id, first_name, last_name, email, job_title FROM users WHERE id = %s", (self.users[key],))

    def name(self, key):
        u = self.user(key)
        return f"{u['first_name']} {u['last_name']}"

    def spread(self, n, days=365, recent_bias=False):
        """n dates spread over the last `days` days (oldest first)."""
        out = []
        for _ in range(n):
            d = self.rnd.random()
            if recent_bias:
                d = d ** 1.6
            out.append(int(d * days))
        return sorted(out, reverse=True)
