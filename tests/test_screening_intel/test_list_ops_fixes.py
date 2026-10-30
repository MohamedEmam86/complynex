"""Review fixes for list versions (P2-1 / P2-7) and the search-index write guard.
No database and no Elasticsearch: everything external is replaced by fakes."""
import importlib
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'scripts'))
os.environ.setdefault('SECRET_KEY', 'test-only-not-a-secret')   # config.py refuses to load without one

from screening import es_client  # noqa: E402
from screening import list_versions as LV  # noqa: E402


# ------------------------------------------------------------------ S1: index write guard
def _set_db(monkeypatch, name):
    from config import Config
    monkeypatch.setitem(Config.POSTGRES_CONFIG, 'database', name)
    monkeypatch.delenv('ES_INDEX_DB', raising=False)


def test_write_allowed_only_for_the_index_database(monkeypatch):
    _set_db(monkeypatch, 'complynex_db')
    assert es_client.es_write_allowed()[0] is True
    _set_db(monkeypatch, 'complynex_scratch_ops')
    ok, why = es_client.es_write_allowed()
    assert ok is False and 'complynex_scratch_ops' in why
    with pytest.raises(es_client.ESTargetError):
        es_client.guard_es_write('test')
    # an index explicitly assigned to another database refuses production
    monkeypatch.setenv('ES_INDEX_DB', 'complynex_test')
    assert es_client.es_write_allowed('complynex_db')[0] is False
    assert es_client.es_write_allowed('complynex_test')[0] is True


class _NoES:
    def __getattr__(self, name):
        raise AssertionError('Elasticsearch must not be touched')


def test_incremental_sync_refuses_scratch_db_before_touching_the_index(monkeypatch):
    m = importlib.import_module('es_incremental_sync')
    monkeypatch.setitem(m.PG, 'database', 'complynex_scratch_ops')
    monkeypatch.delenv('ES_INDEX_DB', raising=False)
    monkeypatch.setattr(m, 'get_es_client', lambda *a, **k: _NoES())
    import utils.demo
    import screening.update_lock
    monkeypatch.setattr(utils.demo, 'skip_in_demo', lambda *a, **k: False)
    monkeypatch.setattr(screening.update_lock, 'held', lambda: False)
    monkeypatch.setattr(m.psycopg2, 'connect', lambda *a, **k: (_ for _ in ()).throw(AssertionError('no DB')))
    with pytest.raises(es_client.ESTargetError):
        m.run()


@pytest.mark.parametrize('mod,fn', [('es_reconcile', 'run'), ('es_full_migrate', 'run'),
                                    ('es_backfill_missing', 'main'), ('es_sync_setup', 'setup'),
                                    ('es_create_index', 'create_index')])
def test_other_index_writers_refuse_scratch_db(monkeypatch, mod, fn):
    _set_db(monkeypatch, 'complynex_scratch_ops')
    m = importlib.import_module(mod)
    for name in ('get_es_client', 'get_es'):
        if hasattr(m, name):
            monkeypatch.setattr(m, name, lambda *a, **k: _NoES())
    import utils.demo
    monkeypatch.setattr(utils.demo, 'skip_in_demo', lambda *a, **k: False)
    monkeypatch.setattr(sys, 'argv', ['x'])
    with pytest.raises(es_client.ESTargetError):
        getattr(m, fn)()


# ------------------------------------------------------------------ S5 / S6 / S3: guard decision
S = {'max_drop_pct': 10.0, 'max_delist_pct': 10.0, 'min_abs': 25}


def test_normal_update_passes():
    r, _, _ = LV.judge(1000, 995, 1000, 5, S)
    assert r == []


def test_big_drop_blocked():
    r, d, _ = LV.judge(1000, 400, 1000, 600, S)
    assert len(r) == 2 and d == 60.0


def test_small_list_collapse_is_blocked_despite_min_abs():
    # 24 -> 1: under min_abs (25) but more than half the list is gone
    r, _, _ = LV.judge(24, 1, 24, 23, S)
    assert r, 'a small list losing most of its records must be blocked'
    # a small genuine change (24 -> 22) still passes
    assert LV.judge(24, 22, 24, 2, S)[0] == []


def test_deactivations_counted_over_the_whole_source():
    # same number fetched, but a whole id family would be deactivated: blocked on deactivations
    r, _, dl = LV.judge(1000, 1000, 1300, 300, S)
    assert dl > 10 and any('deactivated' in x for x in r)


def test_empty_download_blocked():
    assert LV.judge(500, 0, 500, 500, S)[0][0] == 'the download has no records'


def test_held_after_rollback():
    r, _, _ = LV.judge(1000, 1000, 1000, 0, S, held_by=7)
    assert len(r) == 1 and 'rolled back' in r[0]


# ------------------------------------------------------------------ S7: allowed age
def test_allowed_age_defaults():
    assert LV.max_age_hours('ofac', {'default': 48}) == 48
    assert LV.max_age_hours('ofac', {'default': 48}, 168) == 336          # weekly list
    assert LV.max_age_hours('ofac', {'default': 48}, 24) == 48
    assert LV.max_age_hours('pma_ps_reg', {'default': 48}) == LV.MAX_AGE_REG_DEFAULT
    assert LV.max_age_hours('pma_ps', {}) == 24 * 45
    assert LV.max_age_hours('ofac', {'default': 48, 'ofac': 12}, 168) == 12   # MLRO value wins


# ------------------------------------------------------------------ rollback target
def _v(i, no, status='APPLIED', restored_from=None):
    return {'id': i, 'version_no': no, 'status': status, 'restored_from': restored_from}


def test_first_rollback_targets_previous():
    cur, t = LV._pick_target([_v(13, 3), _v(12, 2), _v(11, 1)])
    assert cur['id'] == 13 and t['id'] == 12


def test_second_rollback_walks_further_back():
    # v3 rolled back -> v4 RESTORED from v2; rolling back again must go to v1, not v2 again
    rows = [_v(14, 4, 'RESTORED', restored_from=12), _v(12, 2), _v(11, 1)]
    cur, t = LV._pick_target(rows)
    assert cur['id'] == 14 and t['id'] == 11
    assert LV._pick_target([_v(14, 4, 'RESTORED', restored_from=12), _v(12, 2)])[1] is None


# ------------------------------------------------------------------ S2: one writer per list
class _Cur:
    def __init__(self, got, log):
        self.got, self.log = got, log

    def execute(self, sql, args=None):
        self.log.append(sql.split('(')[0].strip())

    def fetchone(self):
        return (self.got,)


class _Conn:
    def __init__(self, got):
        self.got, self.log = got, []

    def cursor(self, *a, **k):
        return _Cur(self.got, self.log)

    def commit(self):
        self.log.append('commit')

    def rollback(self):
        self.log.append('rollback')


def test_source_lock_busy_and_released():
    with pytest.raises(LV.SourceBusy):
        with LV.source_lock(_Conn(False), 'ofac'):
            pass
    c = _Conn(True)
    with LV.source_lock(c, 'ofac'):
        pass
    assert any('pg_advisory_unlock' in x for x in c.log)
