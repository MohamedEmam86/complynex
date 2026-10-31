"""OpenSanctions profile fields (P2-2 for OpenSanctions) and their backfill.
No database, no network: invented records and fake connections only."""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'scripts'))
os.environ.setdefault('SECRET_KEY', 'test-only-not-a-secret')

from screening.format_handlers import OpenSanctionsHandler  # noqa: E402
from screening.data_updater_enhanced import EnhancedDataUpdater as U  # noqa: E402

PERSON = {
    'id': 'test-person-1', 'schema': 'Person', 'datasets': ['test_sanctions_a', 'test_peps_b'],
    'referents': ['ref-1'], 'first_seen': '2023-05-01T10:11:12', 'last_seen': '2026-10-30T00:00:00',
    'last_change': '2026-10-29T08:00:00',
    'properties': {
        'name': ['Zorvan Test Keldar'], 'alias': ['Zorvan Keldar'], 'weakAlias': ['Zork'],
        'birthDate': ['1971-02-03', '1972'], 'birthPlace': ['Testville'], 'citizenship': ['xa'],
        'gender': ['Male'], 'passportNumber': ['P1234567'], 'idNumber': ['ID-998877'],
        'taxNumber': ['TX-1'], 'address': ['1 Invented Street, Testville'], 'position': ['Minister of Tests'],
        'topics': ['sanction'], 'country': ['xa'], 'notes': ['invented record for tests'],
    },
}


def _raw(d=PERSON):
    return OpenSanctionsHandler()._parse_line(json.dumps(d))


def _parse(d=PERSON):
    from screening.format_handlers import expand_rich
    return expand_rich(_raw(d))


def test_rich_fields_parsed():
    e = _parse()
    assert e['date_of_birth'] == '1971-02-03;1972'
    assert e['place_of_birth'] == 'Testville'
    assert e['nationality'] == 'xa'                       # citizenship when no nationality
    assert e['gender'] == 'male'
    assert e['passport_numbers'] == ['P1234567']
    assert e['national_id_numbers'] == ['ID-998877']
    assert e['addresses'] == ['1 Invented Street, Testville']
    assert e['first_seen'] == '2023-05-01T10:11:12'        # ISO with T (the index maps it as a date)
    p = e['properties']
    assert p['datasets'] == ['test_sanctions_a', 'test_peps_b']
    assert e['dataset'] == 'test_sanctions_a'              # the first dataset stays in `dataset`
    assert p['weak_aliases'] == ['Zork']
    assert {'type': 'Tax number', 'number': 'TX-1'} in p['identifiers']
    assert {'type': 'Passport', 'number': 'P1234567'} in p['identifiers']
    assert 'Zork' not in e['aliases']                      # weak aliases are not searched as aliases
    assert e['_rich'] is True


def test_hash_ignores_volatile_fields():
    a = _parse()
    d = json.loads(json.dumps(PERSON))
    d['last_seen'] = '2026-11-02T00:00:00'
    d['last_change'] = '2026-11-02T00:00:00'
    b = _parse(d)
    assert U._content_hash(a) == U._content_hash(b)        # no mass "updated" every day
    d['properties']['passportNumber'] = ['P7654321']
    assert U._content_hash(_parse(d)) != U._content_hash(a)


def test_values_are_capped():
    d = json.loads(json.dumps(PERSON))
    d['properties']['address'] = [f'addr {i}' for i in range(50)]
    d['properties']['birthPlace'] = ['x' * 5000]
    e = _parse(d)
    assert len(e['addresses']) == 10
    assert len(e['place_of_birth']) == 300


def test_minimal_entity_still_parses():
    e = _parse({'id': 'x2', 'schema': 'Company', 'datasets': [], 'properties': {'name': ['Invented Co']}})
    assert e['full_name'] == 'Invented Co' and e['date_of_birth'] is None and e['properties'] == {}
    assert e['first_seen'] is None and e['dataset'] == 'OpenSanctions'


class _Cur:
    def __init__(self, value):
        self.value = value

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return {'config_value': self.value} if self.value is not None else None

    def fetchall(self):
        return []


class _Conn:
    def __init__(self, value):
        self.value = value

    def cursor(self, *a, **k):
        return _Cur(self.value)

    def rollback(self):
        pass

    def commit(self):
        pass


def _updater(flag):
    u = U.__new__(U)
    u.db_conn = _Conn(flag)
    u.task_id = None
    return u


def test_flag_defaults_off():
    assert _updater(None)._os_rich_enabled() is False
    assert _updater('off')._os_rich_enabled() is False
    assert _updater('on')._os_rich_enabled() is True


def test_rich_stripped_until_backfill(monkeypatch):
    seen = {}
    u = _updater(None)

    def fake_batch(self, entities, source_name):
        seen['rich'] = [e.get('_rich') for e in entities]
        return 0, 0, 0
    # call only the guard part: replace the rest of the method after the flag check
    entities = [_raw()]
    if str('opensanctions').startswith('opensanctions') and not u._os_rich_enabled():
        for e in entities:
            e.pop('_rich', None)
    assert entities[0].get('_rich') is None
    # and the real method strips it too (no DB rows: the fake cursor returns nothing)
    entities = [_raw()]
    monkeypatch.setattr(U, '_batch_insert_entities', lambda self, ents, cur, src=None: seen.setdefault('ins', ents))
    u._import_entities_batch(entities, 'opensanctions_pep')
    assert seen['ins'][0].get('_rich') is None
    u2 = _updater('on')
    seen.clear()
    u2._import_entities_batch([_raw()], 'opensanctions')
    assert seen['ins'][0].get('_rich') is True


def test_backfill_row_values_match_loader_columns():
    import backfill_opensanctions_rich as B
    e = _raw()
    vals = B._row_values(U, e)
    assert len(vals) == 27                         # id is prepended by the caller: 28 VALUES columns
    assert vals[-1] == U._content_hash(e)          # the stored hash is the loader's hash
    assert vals[10] == '1971-02-03;1972' and vals[11] == 1971
    assert json.loads(vals[22])['datasets'] == ['test_sanctions_a', 'test_peps_b']
    assert B.UPDATE_SQL.count('%s') == 1           # execute_values needs exactly one placeholder
    # the stored text is plain JSON, written exactly like the OFAC / UK profile fields
    assert vals[19] == '["P1234567"]' and json.loads(vals[22])['weak_aliases'] == ['Zork']


def test_stored_json_value_keeps_other_lists_unchanged():
    from screening.data_updater_enhanced import stored_json_value
    assert stored_json_value(['A1', 'Ä']) == '["A1", "Ä"]'         # OFAC / UK lists: as before
    assert stored_json_value({'k': 1}) == '{"k": 1}'
    assert stored_json_value([]) is None and stored_json_value(None) is None


def test_compact_record_stays_small():
    e = _raw()
    assert len(e) <= 21          # one dict size class: the 2.2M records held in memory do not grow
    assert U._content_hash(e) == U._content_hash(_parse())   # hash reads the expanded fields
