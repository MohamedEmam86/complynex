"""G10 (related parties screened with the company) and G13 (relatives / close associates of PEPs)."""
import importlib.util
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from kyb import logic as L                          # noqa: E402
from screening import pep_relations as PR            # noqa: E402


def _importer():
    spec = importlib.util.spec_from_file_location('ipr', os.path.join(ROOT, 'scripts', 'import_pep_relations.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ===================================================================== G10: KYB states
def test_incomplete_state_blocks_and_ranks():
    p = {'screening_history_id': 7, 'screened_key': None, 'full_name': 'Party A'}
    assert L.screening_state(p, {'screening_result': 'INCOMPLETE'}, []) == L.INCOMPLETE
    # an open queue item still reads OPEN first; a confirmed hit wins over everything
    assert L.screening_state(p, {'screening_result': 'INCOMPLETE'}, [{'status': 'Pending'}]) == L.OPEN
    assert L.screening_state(p, {'screening_result': 'CLEAR'}, []) == L.CLEAR
    assert L.INCOMPLETE in L.BLOCKING_STATES
    assert L.worst_state([L.CLEAR, L.INCOMPLETE, L.PEP]) == L.INCOMPLETE
    assert L.worst_state([L.CLEAR, L.OPEN, L.INCOMPLETE]) == L.OPEN
    assert L.worst_state([L.CLEARED, L.CONFIRMED]) == L.CONFIRMED
    assert L.worst_state([]) is None


def test_incomplete_party_is_an_approval_blocker():
    ent = {'cr_number': '1', 'tax_card_number': '2', 'legal_form': 'LLC', 'incorporation_date': '2020-01-01',
           'incorporation_country': 'EG'}
    ubos = [{'id': 1, 'full_name': 'Owner One', 'ownership_pct': 60, 'control_type': 'ownership'}]
    sigs = [{'id': 2, 'full_name': 'Signer Two'}]
    out = L.approval_blockers(ent, ubos, sigs, {('ubo', 1): L.INCOMPLETE, ('signatory', 2): L.CLEAR})
    assert any('incomplete' in m[0] for m in out)
    s = L.sanctions_summary(True, [{'screening_state': L.INCOMPLETE}, {'screening_state': L.CLEAR}])
    assert s['people_screened'] == 1 and not s['complete']


# ===================================================================== G10: parent status
def test_combined_status():
    from kyb import parties_screening as PS
    assert PS.combined_status('Clear', L.OPEN) == 'Pending Review'
    assert PS.combined_status('Clear', L.CONFIRMED) == 'Pending Review'
    assert PS.combined_status('Clear', L.INCOMPLETE) == 'Incomplete'
    assert PS.combined_status('Whitelisted', L.ERROR) == 'Incomplete'
    assert PS.combined_status('Pending Review', L.INCOMPLETE) == 'Pending Review'   # never lowered
    assert PS.combined_status('Clear', L.CLEAR) == 'Clear'
    assert PS.combined_status('Clear', L.PEP) == 'Clear'
    assert PS.combined_status('Clear', None) == 'Clear'


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeDb:
    def __init__(self):
        self.sql = []
        self.commits = 0

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        return _Rows([])

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _fake_service(monkeypatch, record, people, states, fail=False):
    from kyb import service as S
    calls = {}
    monkeypatch.setattr(S, 'record', lambda subject, sid, db=None: dict(record) if record else None)
    monkeypatch.setattr(S, 'people', lambda kind, subject, sid, db=None: [p for p in people if p['kind'] == kind])

    def _screen_all(subject, sid, user_id, only_needed=True, db=None):
        if fail:
            raise RuntimeError('engine down')
        calls['screen_all'] = only_needed
        return len(people)
    monkeypatch.setattr(S, 'screen_all', _screen_all)

    def _with_states(subject, sid, db=None):
        ubos = [dict(p, screening_state=states[p['id']]) for p in people if p['kind'] == 'ubo']
        sigs = [dict(p, screening_state=states[p['id']]) for p in people if p['kind'] == 'signatory']
        return ubos, sigs, {}
    monkeypatch.setattr(S, 'with_states', _with_states)
    return calls


def test_parent_screening_folds_party_hit(monkeypatch):
    from kyb import parties_screening as PS
    people = [{'kind': 'ubo', 'id': 1, 'full_name': 'Owner One'}, {'kind': 'signatory', 'id': 2, 'full_name': 'Signer'}]
    calls = _fake_service(monkeypatch, {'id': 5, 'screening_status': 'Clear'}, people, {1: L.OPEN, 2: L.CLEAR})
    db = FakeDb()
    out = PS.after_parent_screening('Merchant KYC', 5, 1, db)
    assert calls['screen_all'] is False                     # every party re-screened with the company
    assert out['status'] == 'Pending Review' and out['overview']['worst'] == L.OPEN
    assert any('UPDATE merchants SET screening_status' in s for s, _ in db.sql)


def test_parent_screening_incomplete_party(monkeypatch):
    from kyb import parties_screening as PS
    people = [{'kind': 'ubo', 'id': 1, 'full_name': 'Owner One'}]
    _fake_service(monkeypatch, {'id': 9, 'customer_type': 'CORPORATE', 'screening_status': 'Clear'}, people,
                  {1: L.INCOMPLETE})
    db = FakeDb()
    out = PS.after_parent_screening('Customer KYC', 9, 1, db)
    assert out['status'] == 'Incomplete'
    assert any('UPDATE customers SET screening_status' in s for s, _ in db.sql)


def test_individual_customer_and_other_modules_untouched(monkeypatch):
    from kyb import parties_screening as PS
    _fake_service(monkeypatch, {'id': 3, 'customer_type': 'INDIVIDUAL', 'screening_status': 'Clear'},
                  [{'kind': 'ubo', 'id': 1, 'full_name': 'X'}], {1: L.OPEN})
    assert PS.after_parent_screening('Customer KYC', 3, 1, FakeDb()) is None
    assert PS.after_parent_screening('KYB Beneficial Owner', 3, 1, FakeDb()) is None    # no recursion
    assert PS.after_parent_screening('Manual Screening', 3, 1, FakeDb()) is None


def test_party_failure_never_leaves_parent_clear(monkeypatch):
    from kyb import parties_screening as PS
    _fake_service(monkeypatch, {'id': 5, 'screening_status': 'Clear'},
                  [{'kind': 'ubo', 'id': 1, 'full_name': 'X'}], {1: L.CLEAR}, fail=True)
    db = FakeDb()
    assert PS.after_parent_screening('Merchant KYC', 5, 1, db) is None
    assert any("screening_status = 'Incomplete'" in s for s, _ in db.sql)


# ===================================================================== G13: import parser
def test_import_parser():
    imp = _importer()
    lines = [
        json.dumps({'id': 'fam1', 'schema': 'Family', 'properties': {'person': ['Q1'], 'relative': ['Q2'],
                                                                     'relationship': ['spouse']}}).encode(),
        json.dumps({'id': 'as1', 'schema': 'Associate', 'properties': {'person': ['Q1'], 'associate': ['Q3']}}).encode(),
        json.dumps({'id': 'p1', 'schema': 'Person', 'properties': {'name': ['A']}}).encode(),
        json.dumps({'id': 'bad', 'schema': 'Family', 'properties': {'person': ['Q1']}}).encode(),       # one side
        json.dumps({'id': 'self', 'schema': 'Family', 'properties': {'person': ['Q1'], 'relative': ['Q1']}}).encode(),
        b'', b'not json "Family"',
    ]
    out = list(imp.parse(lines))
    assert [(r['key'], r['pep_sid'], r['rel_sid'], r['type'], r['relationship']) for r in out] == [
        ('os:fam1', 'OS-Q1', 'OS-Q2', 'family', 'spouse'), ('os:as1', 'OS-Q1', 'OS-Q3', 'associate', '')]


# ===================================================================== G13: runtime
class FakeCur:
    """relations: (id, pep_src, pep_sid, rel_src, rel_sid, type, relationship, origin);
    records: {source_id: row dict}."""
    def __init__(self, relations, records, table=True):
        self.relations, self.records, self.table = relations, records, table
        self.rows = []
        self.queries = 0

    def execute(self, sql, params=None):
        self.queries += 1
        if 'to_regclass' in sql:
            self.rows = [(self.table,)]
        elif 'FROM screening_pep_relations' in sql:
            keys = set(zip(params[0], params[1]))
            self.rows = [r for r in self.relations if (r[1], r[2]) in keys or (r[3], r[4]) in keys]
        elif 'FROM screening_watchlist' in sql:
            ids = set(params[0])
            self.rows = [self.records[s] for s in ids if s in self.records]
        else:
            self.rows = []

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


def _reset():
    PR._TABLE.update({'ok': None, 'at': 0.0})


def _rec(sid, name, lt, src='opensanctions', topics=''):
    return {'id': hash(sid) % 100000, 'source': src, 'source_id': sid, 'full_name': name, 'full_name_arabic': None,
            'list_type': lt, 'topics': topics, 'date_of_birth': None, 'nationality': None}


def test_annotate_tags_relative_of_pep_and_keeps_every_hit():
    _reset()
    rel = [(1, 'opensanctions', 'OS-Q1', 'opensanctions', 'OS-Q2', 'family', 'spouse', 'opensanctions')]
    recs = {'OS-Q1': _rec('OS-Q1', 'Pep Person', 'PEP', 'opensanctions_pep', '["role.pep"]'),
            'OS-Q2': _rec('OS-Q2', 'Spouse Person', 'CONTEXT', topics='["role.rca"]')}
    hits = [{'source': 'opensanctions', 'source_id': 'OS-Q2', 'match_score': 88, 'id': 2},
            {'source': 'ofac', 'source_id': 'OFAC-9', 'match_score': 80, 'id': 3},
            {'source': 'internal_blacklist', 'entity_id': 4, 'match_score': 90}]
    before = [dict(h) for h in hits]
    out = PR.annotate(hits, cur=FakeCur(rel, recs))
    assert out is hits and len(out) == 3
    assert hits[0]['pep_related'] is True
    r = hits[0]['pep_relations'][0]
    assert r['role'] == 'relative_of' and r['other_is_pep'] and r['relationship'] == 'spouse'
    for a, b in zip(hits, before):                        # only the two keys are added
        assert {k: v for k, v in a.items() if k not in ('pep_relations', 'pep_related')} == b
    en, ar = PR.explain_lines(hits[0])
    assert en and 'Related to PEP' in en[0] and ar


def test_annotate_pep_side_and_feed_alias():
    _reset()
    rel = [(1, 'opensanctions', 'OS-Q1', 'opensanctions', 'OS-Q2', 'associate', '', 'opensanctions')]
    recs = {'OS-Q1': _rec('OS-Q1', 'Pep Person', 'PEP', 'opensanctions_pep'), 'OS-Q2': _rec('OS-Q2', 'Assoc', 'CONTEXT')}
    hits = [{'source': 'opensanctions_pep', 'source_id': 'OS-Q1', 'match_score': 90}]   # PEP-feed row of the PEP
    PR.annotate(hits, cur=FakeCur(rel, recs))
    assert hits[0]['pep_relations'][0]['role'] == 'has_relative'
    assert 'pep_related' not in hits[0]              # the other side is not a PEP


def test_annotate_fails_open():
    _reset()
    hits = [{'source': 'opensanctions', 'source_id': 'OS-Q2', 'match_score': 88}]
    PR.annotate(hits, cur=FakeCur([], {}, table=False))
    assert hits == [{'source': 'opensanctions', 'source_id': 'OS-Q2', 'match_score': 88}]

    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError('db down')
    _reset()
    hits2 = [{'source': 'opensanctions', 'source_id': 'OS-Q2', 'match_score': 88}]
    assert PR.annotate(hits2, cur=Boom()) == [{'source': 'opensanctions', 'source_id': 'OS-Q2', 'match_score': 88}]
    assert PR.annotate([], cur=Boom()) == []


def test_relation_lookup_ignores_delisted_other_side():
    _reset()
    rel = [(1, 'opensanctions', 'OS-Q1', 'opensanctions', 'OS-Q2', 'family', 'child', 'opensanctions')]
    hits = [{'source': 'opensanctions', 'source_id': 'OS-Q2', 'match_score': 88}]
    PR.annotate(hits, cur=FakeCur(rel, {'OS-Q2': _rec('OS-Q2', 'Child', 'CONTEXT')}))   # PEP side not listed
    assert 'pep_relations' not in hits[0]


def test_workflow_rca_gets_pep_action(monkeypatch):
    from screening import workflow as W
    from screening import list_category as lc
    monkeypatch.setattr(lc, 'for_match', lambda m: 'CONTEXT')
    m = {'source': 'opensanctions', 'list_type': 'CONTEXT', 'match_score': 85}
    assert W.list_type_of(m) == 'CONTEXT'
    m['pep_related'] = True
    assert W.list_type_of(m) == 'PEP'
    monkeypatch.setattr(lc, 'for_match', lambda m: 'SANCTIONS')
    assert W.list_type_of(m) == 'SANCTIONS'           # a sanctions listing keeps its own action


def test_manual_link_validation():
    with pytest.raises(ValueError):
        PR.add_manual(None, {'source': 'ofac', 'source_id': 'A'}, {'source': 'ofac', 'source_id': 'B'},
                      'cousin', '', 1, 'a long enough reason here')
    with pytest.raises(ValueError):
        PR.add_manual(None, {'source': 'ofac', 'source_id': 'A'}, {'source': 'ofac', 'source_id': 'B'},
                      'family', '', 1, 'short')
    with pytest.raises(ValueError):
        PR.add_manual(None, {'source': 'ofac', 'source_id': 'A'}, {'source': 'ofac', 'source_id': 'A'},
                      'family', '', 1, 'a long enough reason here')
    assert PR.side_source('opensanctions_pep') == 'opensanctions' and PR.side_source('OFAC') == 'ofac'
