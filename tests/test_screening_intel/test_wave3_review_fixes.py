"""Review fixes for merge/wave3: per-request INCOMPLETE flags, clearance of what was screened,
same-customer rule for name entries, fingerprint fields."""
import os
import subprocess
import sys
import textwrap

from screening import clearance_scope as CS

ENTRY = {'id': 7, 'approved_by_name': 'Mlro One', 'approval_date': '2026-10-01 10:00:00',
         'customer_id': 'C-1', 'national_id': '29001011234567', 'date_of_birth': '1990-01-01'}
ROW = {'id': 11, 'full_name': 'Person A', 'aliases': '["P. A"]', 'date_of_birth': '1970-01-02',
       'nationality': 'EG', 'list_type': 'SANCTIONS', 'source': 'un', 'is_active': 1}


def _hit(rid=11):
    return {'id': rid, 'source': 'un', 'full_name': 'Person A', 'match_score': 88.0}


def _links(fp):
    return {('watchlist', 11): {'fingerprint': fp, 'is_active': True, 'cleared_at': '2026-10-01 10:00',
                                'cleared_by_name': 'Analyst'}}


def test_flags_do_not_leak_between_greenlets():
    """Two screenings in two greenlets of one gevent worker: one sees ES down, the other not."""
    code = textwrap.dedent("""
        from gevent import monkey; monkey.patch_all()
        import gevent
        from screening.complynex_engine import ComplyNexScreeningEngine as E
        eng = E.__new__(E)          # shared engine object, as in a gevent worker
        seen = {}
        def run(tag, degraded):
            eng.es_degraded = False
            eng.semantic_degraded = False
            gevent.sleep(0.01)
            if degraded:
                eng.es_degraded = True
                eng.semantic_degraded = True
            gevent.sleep(0.02)      # the other greenlet runs and resets its own flags here
            seen[tag] = (eng.es_degraded, eng.semantic_degraded)
        gevent.joinall([gevent.spawn(run, 'down', True), gevent.spawn(run, 'ok', False)])
        assert seen == {'down': (True, True), 'ok': (False, False)}, seen
        print('NO-LEAK')
    """)
    env = dict(os.environ)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env['PYTHONPATH'] = root + os.pathsep + env.get('PYTHONPATH', '')
    out = subprocess.run([sys.executable, '-c', code], cwd=root, env=env, capture_output=True,
                         text=True, timeout=120)
    assert 'NO-LEAK' in out.stdout, (out.stdout[-2000:], out.stderr[-2000:])


def test_same_customer_rule():
    assert CS.same_customer(ENTRY, customer_id='C-1')
    assert CS.same_customer(ENTRY, national_id='2900-1011-234567')
    assert CS.same_customer(ENTRY, dob='1990-01-01')
    assert not CS.same_customer(ENTRY)                       # name only
    assert not CS.same_customer(ENTRY, customer_id='C-2', dob='1991-01-01')
    assert not CS.same_customer(dict(ENTRY, national_id=None, date_of_birth=None, customer_id=None),
                                customer_id='C-1')


def test_cleared_record_of_another_customer_is_shown_with_note():
    fp = CS.fingerprint(CS.KIND_WATCHLIST, ROW)
    kept, cleared = CS.classify([_hit()], ENTRY, _links(fp), {('watchlist', 11): (fp, True)},
                                who={'customer_id': None, 'national_id': None, 'dob': None})
    assert cleared == [] and kept[0]['clearance']['state'] == CS.ST_OTHER
    kept, cleared = CS.classify([_hit()], ENTRY, _links(fp), {('watchlist', 11): (fp, True)},
                                who={'customer_id': 'C-1', 'national_id': None, 'dob': None})
    assert kept == [] and cleared[0]['clearance']['state'] == CS.ST_CLEARED


class _Cur:
    def __init__(self, log):
        self.log = log
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def close(self):
        pass


class _Conn:
    def __init__(self):
        self.log = []

    def cursor(self, *a, **k):
        return _Cur(self.log)


def _inserted(conn):
    return [p[2] for s, p in conn.log if 'INSERT INTO screening_whitelist_matches' in s]


def test_record_links_only_covers_what_was_screened(monkeypatch):
    monkeypatch.setattr(CS, 'current_state', lambda conn, keys: {('watchlist', 11): ('fp-now', True),
                                                                  ('watchlist', 12): ('fp-same', True)})
    conn = _Conn()
    skipped = []
    a = dict(_hit(11), record_fp='fp-then')       # changed between screening and approval
    b = dict(_hit(12), record_fp='fp-same')       # unchanged
    n = CS.record_links(conn, 5, [a, b], cleared_by=1, skipped=skipped)
    assert n == 1 and _inserted(conn) == [12]
    assert [s['id'] for s in skipped] == [11] and skipped[0]['reason'] == 'changed_since_screening'


def test_record_links_old_result_skips_records_updated_after_screening(monkeypatch):
    monkeypatch.setattr(CS, 'current_state', lambda conn, keys: {('watchlist', 11): ('x', True),
                                                                  ('watchlist', 12): ('y', True)})
    monkeypatch.setattr(CS, 'updated_at', lambda conn, keys: {('watchlist', 11): '2026-10-31 04:21:17',
                                                              ('watchlist', 12): '2026-10-29 04:00:00'})
    conn = _Conn()
    skipped = []
    n = CS.record_links(conn, 5, [_hit(11), _hit(12)], screened_at='2026-10-30 12:00:00', skipped=skipped)
    assert n == 1 and _inserted(conn) == [12] and skipped[0]['id'] == 11


def test_stamp_records_screening_time_fingerprint(monkeypatch):
    monkeypatch.setattr(CS, 'current_state', lambda conn, keys: {('watchlist', 11): ('fp-a', True)})
    ms = [_hit(11), _hit(99)]
    CS.stamp(object(), ms)
    assert ms[0]['record_fp'] == 'fp-a' and 'record_fp' not in ms[1]


def test_fingerprint_new_fields():
    a = CS.fingerprint(CS.KIND_WATCHLIST, ROW)
    assert a != CS.fingerprint(CS.KIND_WATCHLIST, dict(ROW, place_of_birth='Cairo'))
    assert a != CS.fingerprint(CS.KIND_WATCHLIST, dict(ROW, gender='male'))
    assert a != CS.fingerprint(CS.KIND_WATCHLIST, dict(ROW, topics='sanction'))
    p1 = dict(ROW, properties='{"datasets": ["un_sc", "us_ofac"], "notes": "x"}')
    p2 = dict(ROW, properties='{"datasets": ["us_ofac", "un_sc"], "notes": "other enrichment"}')
    p3 = dict(ROW, properties='{"datasets": ["us_ofac"]}')
    assert CS.fingerprint(CS.KIND_WATCHLIST, p1) == CS.fingerprint(CS.KIND_WATCHLIST, p2)
    assert CS.fingerprint(CS.KIND_WATCHLIST, p1) != CS.fingerprint(CS.KIND_WATCHLIST, p3)
    pep = {'id': 1, 'full_name': 'X'}
    assert CS.fingerprint(CS.KIND_PEP, pep) != CS.fingerprint(CS.KIND_PEP, dict(pep, passport_number='A1'))
