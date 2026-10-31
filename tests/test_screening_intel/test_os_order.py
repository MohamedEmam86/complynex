"""OpenSanctions deterministic record (churn fix): the same entity in two exports -> same row."""
import json
import random
import importlib.util
import os

from screening.format_handlers import OpenSanctionsHandler, expand_rich, _os_pick_referent, _os_pick_dataset
from screening.data_updater_enhanced import EnhancedDataUpdater as U

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _entity():
    return {
        'id': 'Q-test-1', 'caption': 'Zed Example Person', 'schema': 'Person',
        'referents': ['xx-abc', 'ofac-12345', 'aa-1'],
        'datasets': ['zz_list', 'us_ofac_sdn', 'aa_list'],
        'first_seen': '2020-01-02T03:04:05',
        'properties': {
            'name': ['Zed Example Person', 'Example, Zed'], 'alias': ['Z. Example', 'Zed  Example'],
            'topics': ['sanction', 'crime'], 'country': ['ru', 'ae'],
            'birthDate': ['1970-05-01', '1969'], 'nationality': ['ru', 'ae'],
            'passportNumber': ['P2', 'P1'], 'idNumber': ['ID9', 'ID1'], 'address': ['B street', 'A street'],
            'notes': ['note b', 'note a'], 'gender': ['male'],
        },
    }


def _shuffle(d, seed):
    rnd = random.Random(seed)
    d = json.loads(json.dumps(d))
    for k in ('datasets', 'referents'):
        rnd.shuffle(d[k])
    p = d['properties']
    for k, v in p.items():
        if isinstance(v, list):
            rnd.shuffle(v)
    names = p['name'] + p['alias']
    rnd.shuffle(names)
    cut = rnd.randint(1, len(names))
    p['name'], p['alias'] = names[:cut], names[cut:]
    return d


def _rich(d):
    return expand_rich(OpenSanctionsHandler(rich=True)._parse_line(json.dumps(d)))


def test_shuffled_exports_give_the_same_rich_record():
    base = _rich(_entity())
    for seed in range(25):
        other = _rich(_shuffle(_entity(), seed))
        assert other['full_name'] == base['full_name'] == 'Zed Example Person'
        assert U._content_hash(other) == U._content_hash(base)
        for k in ('aliases', 'topics', 'countries', 'dataset', 'source_url', 'list_type', 'details',
                  'date_of_birth', 'nationality', 'passport_numbers', 'addresses', 'properties'):
            assert other.get(k) == base.get(k), k


def test_rich_record_values():
    e = _rich(_entity())
    assert e['aliases'] == sorted(e['aliases']) and 'Zed Example Person' not in e['aliases']
    assert 'Zed Example' in e['aliases'] and 'Zed  Example' not in e['aliases']   # whitespace collapsed
    assert e['dataset'] == 'us_ofac_sdn'                 # priority list, not "the first"
    assert e['source_url'] == 'ofac-12345'               # OFAC referent kept (entity links use it)
    assert e['date_of_birth'] == '1969;1970-05-01'
    assert e['source'] == 'opensanctions'


def test_caption_missing_falls_back_to_sorted_first_name():
    d = _entity()
    d['caption'] = ''
    assert _rich(d)['full_name'] == 'Example, Zed'


def test_legacy_record_unchanged_when_rich_is_off():
    d = _entity()
    e = OpenSanctionsHandler(rich=False)._parse_line(json.dumps(d))
    assert e['full_name'] == 'Zed Example Person'          # names[0], as before
    assert e['aliases'] == ['Example, Zed', 'Z. Example', 'Zed  Example']
    assert e['dataset'] == 'zz_list' and e['source_url'] == 'xx-abc'
    assert e['date_of_birth'] == '1970-05-01' and e['nationality'] == 'ru'
    assert '_rich' not in e and '_os_rich' not in e


def test_pickers():
    assert _os_pick_dataset([]) == 'OpenSanctions'
    assert _os_pick_dataset(['b', 'a']) == 'a'
    assert _os_pick_referent(['b', 'a']) == 'a'
    assert _os_pick_referent([]) is None


def test_backfill_full_record_and_simulation():
    spec = importlib.util.spec_from_file_location('bf', os.path.join(BASE, 'scripts', 'backfill_opensanctions_rich.py'))
    bf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bf)
    e = _rich(_entity())
    full = bf._full(U, e)
    assert tuple(full) == bf.FULL_COLS
    assert full['content_hash'] == U._content_hash(e)
    assert full['list_type'] == e['list_type'] and full['year_of_birth'] == 1969
    rnd = random.Random(3)
    line = json.dumps(_entity())
    for _ in range(10):
        e2 = expand_rich(OpenSanctionsHandler(rich=True)._parse_line(bf._shuffled_line(line, rnd)))
        assert U._content_hash(e2) == U._content_hash(e) and e2['full_name'] == e['full_name']
    assert bf.FULL_SQL.count('%s') == 1
