"""P2-6 / G5: linking the same person across lists (never on a name alone)."""
import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from screening import entity_links as EL          # noqa: E402
from screening.country_codes import to_iso2       # noqa: E402


def _builder():
    spec = importlib.util.spec_from_file_location('bel', os.path.join(ROOT, 'scripts', 'build_entity_links.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ country codes
@pytest.mark.parametrize('v,exp', [
    ('Egyptian', {'eg'}), ('مصرية', {'eg'}), ('IRAN (ISLAMIC REPUBLIC OF)', {'ir'}), ('Russia; Syria', {'ru', 'sy'}),
    ('["mx", "us"]', {'mx', 'us'}), ('Korea, North', {'kp'}), ('Bosnia and Herzegovina', {'ba'}),
    (None, set()), ('', set()), ('somewhere unknown', set()),
])
def test_to_iso2(v, exp):
    assert to_iso2(v) == exp


# ------------------------------------------------------------------ builder helpers
def test_builder_helpers():
    b = _builder()
    assert b.norm_id('29001011234567') == '29001011234567'
    assert b.norm_id('123') is None                    # too short
    assert b.norm_id('00000000') is None               # placeholder
    assert b.full_dates('1980-01-01') == set()         # 1 Jan = year only, never a full date
    assert b.full_dates('1980-05-17;1981-02-03') == {'1980-05-17', '1981-02-03'}
    assert b.kind('INDIVIDUAL') == 'P' and b.kind('ENTITY') == 'E'
    assert b.rank('emlcu') < b.rank('ofac') < b.rank('opensanctions')


# ------------------------------------------------------------------ runtime grouping
class FakeCur:
    def __init__(self, links, members, tables=True):
        self.links, self.members, self.tables = links, members, tables
        self.rows = []

    def execute(self, sql, params=None):
        if 'to_regclass' in sql:
            self.rows = [(self.tables,)]
        elif 'FROM screening_entity_links l JOIN' in sql:
            self.rows = [m for m in self.members if m[0] in params[0]]
        elif 'FROM screening_entity_links' in sql:
            ids = set(params[0])
            self.rows = [r for r in self.links if r[0] in ids]
        else:
            self.rows = []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    EL._TABLES['ok'] = None
    import screening.match_classifier as mc
    monkeypatch.setattr(mc, 'classify_match',
                        lambda m: 'PEP' if 'PEP' in str(m.get('list_type')) else 'SANCTIONS')
    yield
    EL._TABLES['ok'] = None


def _hits():
    return [
        {'id': 10, 'source': 'ofac', 'list_type': 'SANCTIONS', 'match_score': 91.0, 'full_name': 'Person A'},
        {'id': 11, 'source': 'opensanctions', 'list_type': 'SANCTIONS', 'match_score': 96.0, 'full_name': 'Person A'},
        {'id': 12, 'source': 'opensanctions_pep', 'list_type': 'PEP', 'match_score': 88.0, 'full_name': 'Person A'},
        {'id': 20, 'source': 'eu', 'list_type': 'SANCTIONS', 'match_score': 80.0, 'full_name': 'Someone Else'},
    ]


def _cur():
    links = [(10, 7, 'ofac', 'OFAC-1'), (11, 7, 'opensanctions', 'OS-x'), (12, 7, 'opensanctions_pep', 'OS-x')]
    members = [(7, 10, 'ofac', 'lead', 'SANCTIONS', 'ofac', 'Person A', None),
               (7, 11, 'opensanctions', 'os_referent', 'SANCTIONS', 'us_ofac_sdn', 'Person A', None),
               (7, 12, 'opensanctions_pep', 'os_id', 'PEP', 'peps', 'Person A', None),
               (7, 13, 'un', 'os_id', 'SANCTIONS', 'un_sc_sanctions', 'Person A', None)]
    return FakeCur(links, members)


def test_same_cluster_same_kind_becomes_one_hit():
    out = EL.annotate(_hits(), cur=_cur())
    ids = [m['id'] for m in out]
    assert 10 not in ids and 11 in ids                 # the best-scored sanctions hit leads ...
    prim = next(m for m in out if m['id'] == 11)
    assert [g['id'] for g in prim['grouped_hits']] == [10]   # ... and keeps the other one inside
    assert prim['cluster']['other_kinds'] == ['PEP']
    assert any('UN' in x or 'un' in x.lower() for x in prim['also_listed_in'])


def test_other_kind_kept_and_points_back():
    out = EL.annotate(_hits(), cur=_cur())
    pep = next(m for m in out if m['id'] == 12)        # a PEP record is never folded into a sanctions hit
    assert pep['cluster']['other_kinds'] == ['SANCTIONS']
    assert next(m for m in out if m['id'] == 20).get('cluster') is None   # unlinked hit untouched


def test_nothing_lost_without_tables_or_on_error():
    h = _hits()
    assert EL.annotate(h, cur=FakeCur([], [], tables=False)) == h

    class Boom(FakeCur):
        def execute(self, sql, params=None):
            raise RuntimeError('db down')
    h = _hits()
    assert EL.annotate(h, cur=Boom([], [])) == h


def test_internal_hit_maps_to_watchlist_copy():
    assert EL.watchlist_sid('internal_blacklist', 'IBL-ABC', 'x') == 'IBL-ABC'
    import hashlib
    exp = 'IBL-' + hashlib.md5('اسم تجريبي'.encode()).hexdigest()[:12].upper()
    assert EL.watchlist_sid('internal_blacklist', 'INTERNAL-9', ' اسم تجريبي ') == exp
    assert EL._hit_key({'source': 'INTERNAL_BLACKLIST', 'entity_id': 5, 'source_id': 'INTERNAL-9'}) == \
        ('int', 'internal_blacklist', 5)


def test_differences_report():
    rows = [{'label': 'OFAC', 'date_of_birth': '1970-03-02', 'nationality': 'Iraq', 'national_id_numbers': '["A1234567"]',
             'passport_numbers': None},
            {'label': 'UK', 'date_of_birth': '1971', 'nationality': 'Iraqi', 'national_id_numbers': '["A1234567"]',
             'passport_numbers': None},
            {'label': 'EU', 'date_of_birth': '1985-01-01', 'nationality': 'Syria', 'national_id_numbers': '["B7654321"]',
             'passport_numbers': None}]
    fields = {d['field'] for d in EL.differences(rows)}
    assert fields == {'Date of birth', 'Nationality', 'National / official ID'}
    assert EL.differences(rows[:2]) == []              # 1970 vs 1971 (±1 year) and Iraq = Iraqi agree


def test_unlink_needs_a_reason():
    with pytest.raises(ValueError):
        EL.unlink(object(), 1, 1, 'too short')
