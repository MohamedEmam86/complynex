# appended test: the guard does not block an additive update that delistings will skip
import types
from screening import list_versions as LV

class _Cur:
    def __init__(self, active_all, active_same):
        self.q = []; self.a = active_all; self.s = active_same; self._r = None
    def execute(self, sql, args=None):
        self.q.append(sql)
        if 'substring(source_id' in sql: self._r = {'n': self.s}
        elif 'NOT EXISTS' in sql: self._r = {'n': self.a - 3}
        elif 'count(*)' in sql: self._r = {'n': self.a}
        else: self._r = None
    def fetchone(self): return self._r

def _run(monkeypatch, active_all, active_same, nfetched, partial=True):
    cur = _Cur(active_all, active_same)
    conn = types.SimpleNamespace(commit=lambda: None)
    monkeypatch.setattr(LV, '_cur', lambda c: cur)
    monkeypatch.setattr(LV, 'guard_settings', lambda c, s: {'max_drop_pct': 10, 'max_delist_pct': 10, 'min_abs': 25})
    monkeypatch.setattr(LV, 'last_good', lambda c, s: {'trigger': 'baseline', 'version_no': 1, 'fetched_count': active_all, 'status': 'APPLIED'})
    import psycopg2.extras as px
    monkeypatch.setattr(px, 'execute_values', lambda *a, **k: None)
    return LV.evaluate(conn, 'emlcu', [f'emlcu_person_{i:x}' for i in range(nfetched)], delist_skips_partial=partial)

def test_additive_update_not_blocked(monkeypatch):
    ev = _run(monkeypatch, 7349, 7349, 3665)
    assert ev['delist_skipped'] and not ev['blocked'] and ev['projected_delist'] == 0

def test_real_mass_delisting_still_blocked(monkeypatch):
    ev = _run(monkeypatch, 1000, 1000, 850)   # covers >= 80%: delistings apply -> guard counts them
    assert not ev['delist_skipped']
    assert ev['blocked']

def test_other_callers_still_blocked(monkeypatch):
    # import_pma_national deactivates without the 80% skip: a 60% file must still be blocked
    ev = _run(monkeypatch, 1000, 1000, 600, partial=False)
    assert not ev['delist_skipped'] and ev['blocked']

def test_note_states_what_approval_would_do(monkeypatch):
    ev = _run(monkeypatch, 7349, 7349, 3665)
    assert ev['delist_if_approved'] > 0 and 'unless this download is approved' in ev['note']
