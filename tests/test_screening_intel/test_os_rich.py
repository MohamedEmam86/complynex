"""OpenSanctions profile fields (P2-2 for OpenSanctions), their backfill, and the ID rule
that keeps foreign ID numbers from confirming a hit. Invented records, no DB, no network."""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'scripts'))
os.environ.setdefault('SECRET_KEY', 'test-only-not-a-secret')

from screening.format_handlers import OpenSanctionsHandler, expand_rich  # noqa: E402
from screening.data_updater_enhanced import EnhancedDataUpdater as U  # noqa: E402
from screening import match_intel as mi  # noqa: E402

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


def _raw(d=PERSON, rich=True):
    return OpenSanctionsHandler(rich=rich)._parse_line(json.dumps(d))


def _parse(d=PERSON):
    return expand_rich(_raw(d))


# ------------------------------------------------------------------ parsing
def test_rich_fields_parsed():
    e = _parse()
    assert e['date_of_birth'] == '1971-02-03;1972'
    assert e['place_of_birth'] == 'Testville'
    assert e['nationality'] == 'xa'                       # citizenship when no nationality
    assert e['gender'] == 'male'
    assert e['passport_numbers'] == ['P1234567']
    assert e['national_id_numbers'] == []                 # generic idNumber is NOT a national ID
    assert e['addresses'] == ['1 Invented Street, Testville']
    assert e['first_seen'] == '2023-05-01T10:11:12'        # ISO with T (the index maps it as a date)
    p = e['properties']
    assert p['datasets'] == ['test_sanctions_a', 'test_peps_b']
    assert e['dataset'] == 'test_sanctions_a'
    assert p['weak_aliases'] == ['Zork']
    assert {'type': 'ID number', 'number': 'ID-998877'} in p['identifiers']
    assert {'type': 'Tax number', 'number': 'TX-1'} in p['identifiers']
    assert 'Zork' not in e['aliases']
    assert e['_rich'] is True


def test_rich_off_record_equals_previous_loader():
    e = _raw(rich=False)
    assert e == {
        'source_id': 'OS-test-person-1', 'full_name': 'Zorvan Test Keldar', 'original_name': None,
        'list_type': e['list_type'], 'entity_type': 'INDIVIDUAL', 'dataset': 'test_sanctions_a',
        'source': 'opensanctions', 'source_url': 'ref-1', 'risk_level': 'HIGH', 'topics': ['sanction'],
        'countries': ['xa'], 'date_of_birth': '1971-02-03', 'nationality': None,
        'aliases': ['Zorvan Keldar'], 'details': ['invented record for tests']}
    assert OpenSanctionsHandler()._parse_line(json.dumps(PERSON)) == e      # default is off


def test_hash_ignores_volatile_fields():
    a = _raw()
    d = json.loads(json.dumps(PERSON))
    d['last_seen'] = d['last_change'] = '2026-11-02T00:00:00'
    assert U._content_hash(a) == U._content_hash(_raw(d))
    d['properties']['passportNumber'] = ['P7654321']
    assert U._content_hash(_raw(d)) != U._content_hash(a)


def test_values_are_capped():
    d = json.loads(json.dumps(PERSON))
    d['properties']['address'] = [f'addr {i}' for i in range(50)]
    d['properties']['birthPlace'] = ['x' * 5000]
    e = _parse(d)
    assert len(e['addresses']) == 10 and len(e['place_of_birth']) == 300


def test_minimal_entity_still_parses():
    e = _parse({'id': 'x2', 'schema': 'Company', 'datasets': [], 'properties': {'name': ['Invented Co']}})
    assert e['full_name'] == 'Invented Co' and e['date_of_birth'] is None and e['properties'] == {}
    assert e['first_seen'] is None and e['dataset'] == 'OpenSanctions'


def test_compact_record_stays_small():
    e = _raw()
    assert len(e) <= 21 and isinstance(e['_os_rich'], bytes)
    assert U._content_hash(e) == U._content_hash(_parse())


# ------------------------------------------------------------------ loader flag
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


def test_rich_stripped_while_flag_off(monkeypatch):
    seen = {}
    monkeypatch.setattr(U, '_batch_insert_entities', lambda self, ents, cur, src=None: seen.setdefault('ins', ents))
    _updater(None)._import_entities_batch([_raw()], 'opensanctions_pep')
    assert seen['ins'][0].get('_rich') is None
    seen.clear()
    _updater('on')._import_entities_batch([_raw()], 'opensanctions')
    assert seen['ins'][0].get('_rich') is True


# ------------------------------------------------------------------ backfill
def test_backfill_writes_only_profile_columns():
    import backfill_opensanctions_rich as B
    vals = B._row_values(U, _raw())
    assert len(vals) == len(B.PROFILE_COLS) + 1
    assert vals[-1] == U._content_hash(_raw())
    assert vals[0] == '1971-02-03;1972' and vals[1] == 1971 and vals[2] == 'xa' and vals[3] == 'male'
    assert vals[5] == '["P1234567"]' and vals[6] is None
    assert json.loads(vals[8])['weak_aliases'] == ['Zork']
    sql = B.UPDATE_SQL
    assert sql.count('%s') == 1
    for col in ('list_type', 'full_name', 'aliases', 'name_normalized', 'topics', 'dataset', 'is_active'):
        assert f'{col} =' not in sql.split('FROM')[0]
    assert B._row_values(U, _raw(), with_hash=False)[-1] is None


def test_backfill_others_match_loader_serialisation():
    import backfill_opensanctions_rich as B
    o = B._others(_parse())
    assert o['aliases'] == json.dumps(['Zorvan Keldar']) and o['topics'] == json.dumps(['sanction'])


# ------------------------------------------------------------------ ID rule (review B2)
def test_egyptian_national_id_still_confirms():
    assert mi.id_relation('26404101900276', ['26404101900276']) == 'match'
    assert mi.id_relation('26404101900276', '["26404101900276"]') == 'match'          # stored JSON list
    assert mi.id_relation('٢٦٤٠٤١٠١٩٠٠٢٧٦', ['26404101900276']) == 'match'           # Arabic digits
    assert mi.id_relation('28812011234567', ['26404101900276']) == 'conflict'
    assert mi.identity_verdict('26404101900276', listed_nids=['26404101900276'])['verdict'] == 'id_match'
    m = {'match_score': 80, 'watchlist_name_ar': 'نبيل على محمود البوشى', 'full_name': 'نبيل على محمود البوشى',
         'national_id': '26404101900276'}
    assert mi.decide(m, 'نبيل على محمود البوشى', national_id='26404101900276')['decision']['tier'] == 'CONFIRMED'


def test_foreign_or_short_ids_never_confirm_alone():
    assert mi.id_relation('123456', ['RU-123456']) is None                 # short, letters differ
    assert mi.id_relation('123456', ['123456']) is None                    # shorter than 8
    assert mi.id_relation('AB1234567', ['AB-123-4567']) == 'match_unverified'
    assert mi.id_relation('AB1234567', ['AB-123-4567'], 'Russia', ['russia']) == 'match'
    v = mi.identity_verdict('AB1234567', None, 'EG', ['AB1234567'], None, ['Russia'])
    assert v['verdict'] == 'corroborated' and v['identifier_match'] is False
    m = {'match_score': 82, 'full_name': 'Zorvan Keldar', 'national_id_numbers': '["12345678"]', 'countries': '["ru"]'}
    out = mi.decide(m, 'Zorvan Keldar', national_id='12345678')
    assert out['decision'].get('tier') != 'CONFIRMED' and out['match_score'] < 100


def test_passport_needs_the_same_country():
    v = mi.identity_verdict(None, None, 'Egypt', None, None, ['Russia'], query_passport='A12345678',
                            listed_passports=['A12345678'])
    assert v['verdict'] != 'id_match'
    v = mi.identity_verdict(None, None, 'Egypt', None, None, ['Egypt'], query_passport='A12345678',
                            listed_passports=['A12345678'])
    assert v['verdict'] == 'id_match'


# ------------------------------------------------------------------ re-review fixes
def test_governorate_must_be_known():
    assert mi.decode_egyptian_nid('26404101900276')['valid'] is True        # 19 = Ismailia
    assert mi.decode_egyptian_nid('26404109900276')['valid'] is False       # 99: no such governorate


def test_conflict_only_for_egyptian_side_records():
    q, other = '26404101900276', '28812011234567'
    assert mi.id_relation(q, [other]) == 'conflict'                         # no country: Egyptian side
    assert mi.id_relation(q, [other], 'EG', ['Egypt']) == 'conflict'
    assert mi.id_relation(q, [other], 'EG', ['ru']) is None                 # foreign record: no -25
    assert mi.id_relation(q, [other], 'EG', ['ru'], 'emlcu') == 'conflict'  # Egyptian list


def test_iso2_country_agreement():
    assert mi.countries_agree(('RU',), (['Russia'],)) is True
    assert mi.countries_agree(('Russian Federation',), ('russian',)) is True
    assert mi.countries_agree(('EG',), (['Russia'],)) is False
    assert mi.countries_agree((None,), ([],)) is None
    assert mi.id_relation('AB1234567', ['AB-123-4567'], 'Russian Federation', ['RU']) == 'match'
    v = mi.identity_verdict(None, None, 'Russian Federation', None, None, ['ru'])
    assert v['country'] == 'agree'


def test_exact_number_on_egyptian_list_still_confirms():
    typed = '29912341234567'                     # does not decode (month 12, day 34)
    assert mi.decode_egyptian_nid(typed)['valid'] is False
    for src in ('emlcu', 'INTERNAL_BLACKLIST', 'internal_pep'):
        assert mi.id_relation(typed, [typed], None, None, src) == 'match'
    assert mi.id_relation(typed, [typed]) == 'match_unverified'           # unknown list, no country
    m = {'match_score': 80, 'watchlist_name_ar': 'نبيل على محمود البوشى', 'full_name': 'نبيل على محمود البوشى',
         'national_id': typed, 'source': 'INTERNAL_BLACKLIST'}
    assert mi.decide(m, 'نبيل على محمود البوشى', national_id=typed)['decision']['tier'] == 'CONFIRMED'
