"""P6-1 / P6-3 / P6-4 / P6-7 unit tests (no database)."""
import importlib.util
import os

from database import tenancy as T

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BASE, rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_classify():
    assert T.classify('screening_watchlist') == 'mixed'
    assert T.classify('screening_data_sources') == 'shared'
    assert T.classify('bk_users_expired_20261021') == 'system'
    assert T.classify('users') == 'tagged'
    for t in ('customers', 'cases', 'internal_blacklist', 'internal_pep', 'screening_whitelist', 'audit_logs'):
        assert T.classify(t) == 'tenant', t


def test_es_filter_and_flag(monkeypatch):
    monkeypatch.delenv('TENANCY_ENFORCED', raising=False)
    assert T.es_filter_current() is None            # flag off: query unchanged
    f = T.es_filter(2)
    assert f['bool']['minimum_should_match'] == 1
    assert {'term': {'tenant_id': 2}} in f['bool']['should']
    assert T.es_filter(None) == {'bool': {'must_not': {'exists': {'field': 'tenant_id'}}}}


def test_private_source_id():
    assert T.private_source_id('IBL-abc', None) == 'IBL-abc'
    assert T.private_source_id('IBL-abc', 1) == 'IBL-abc'
    assert T.private_source_id('IBL-abc', 7) == 'IBL-abc-t7'


class _Cur:
    def __init__(self, log): self.log = log
    def execute(self, sql, args=None): self.log.append((sql, args))
    def close(self): pass


class _Conn:
    def __init__(self): self.log, self.commits = [], 0
    def cursor(self): return _Cur(self.log)
    def commit(self): self.commits += 1
    def rollback(self): pass
    def get_transaction_status(self): return 0     # idle


def test_bind_sets_session_setting_and_commits():
    c = _Conn()
    assert T.bind(c, 3)
    assert c.log[-1] == ("SELECT set_config(%s, %s, false)", ('app.tenant_id', '3'))
    assert c.commits == 1
    T.unbind(c)
    assert c.log[-1][1] == ('app.tenant_id', '')


def test_generator_phases():
    g = _load('tenancy_sql', 'scripts/tenancy_sql.py')
    tables = [{'table': t, 'has_tid': False, 'rls': False, 'force': False, 'rows': 1}
              for t in ('customers', 'screening_watchlist', 'screening_data_sources', 'users', 'bk_x')]
    prep = '\n'.join(g.sql_prepare(tables))
    assert 'ALTER TABLE "customers" ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1;' in prep
    assert 'ON "screening_watchlist" USING (tenant_id IS NULL OR' in prep
    assert '"screening_data_sources"' not in prep and '"bk_x"' not in prep
    assert 'ENABLE ROW LEVEL SECURITY' not in prep                 # prepare never switches RLS on
    assert 'POLICY cx_tenant_isolation ON "users"' not in prep      # tagged: column, no policy
    enf = '\n'.join(g.sql_enforce(tables))
    assert 'ALTER TABLE "customers" FORCE ROW LEVEL SECURITY;' in enf
    assert '"users" ENABLE' not in enf
    rel = '\n'.join(g.sql_relax(tables))
    assert 'DISABLE ROW LEVEL SECURITY' in rel


def test_monitor_alert_rules():
    m = _load('ops_monitor', 'scripts/ops_monitor.py')
    st = {'checks': [{'key': 'disk:/', 'label': 'Disk /', 'value': '91%', 'level': 'crit'},
                     {'key': 'es', 'label': 'ES', 'value': 'green', 'level': 'ok'},
                     {'key': 'x', 'label': 'X', 'value': '?', 'level': 'unknown'}]}
    msgs, state = m.decide_alerts(st, {}, now=1000)
    assert msgs == ['[CRIT] Disk /: 91%'] and 'disk:/' in state
    msgs2, state2 = m.decide_alerts(st, state, now=1000 + 60)      # same level, too soon: silent
    assert msgs2 == []
    msgs3, _ = m.decide_alerts(st, state, now=1000 + 7 * 3600)     # repeat after OPS_REALERT_HOURS
    assert len(msgs3) == 1
    st['checks'][0]['level'] = 'ok'
    msgs4, state4 = m.decide_alerts(st, state, now=2000)
    assert msgs4 == ['[RECOVERED] Disk /: 91%'] and 'disk:/' not in state4


def test_env_example_lists_settings_without_values():
    e = _load('env_example', 'scripts/env_example.py')
    out = e.render({'POSTGRES_PASSWORD': {'config.py'}, 'TENANCY_ENFORCED': {'database/tenancy.py'}})
    assert 'POSTGRES_PASSWORD=\n' in out + '\n' and '[secret]' in out
    assert 'TENANCY_ENFORCED=' in out
