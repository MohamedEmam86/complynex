"""Users see which KIND of list a match came from under ComplyNex's own names, never the data provider, the
publisher or a dataset code (owner decision, round 5). The superadmin also gets the real source. No database:
pure functions and a Flask request context with fake users."""
import json

import pytest

from screening import list_display as LD

TRADEMARKS = ('world-check', 'world check', 'dow jones', 'lexisnexis', 'refinitiv', 'factiva')
PROVIDER_WORDS = ('opensanctions', 'open sanctions', 'ofac', 'hm treasury', 'ofsi', 'emlcu', 'wikidata',
                  'gb_fcdo_sanctions', 'us_ofac_sdn', 'treasury')


def test_groups_and_default_names():
    assert LD.group_of('opensanctions', 'gb_fcdo_sanctions') == 'global_sanctions'
    assert LD.group_of('opensanctions_pep') == 'global_pep'
    assert LD.group_of('opensanctions', 'opensanctions_peps') == 'global_pep'
    assert LD.group_of('INTERNAL_PEP') == 'internal_pep'
    assert LD.group_of('INTERNAL_BLACKLIST') == 'local' and LD.group_of('emlcu_egypt') == 'local'
    assert LD.group_of('ofac') == 'international' and LD.group_of('un_consolidated') == 'international'
    assert LD.group_of('pma_ps_reg') == 'regulatory'
    for en, ar in LD.GROUPS.values():
        assert not any(t in en.lower() for t in TRADEMARKS)
        assert not any(p in en.lower() for p in PROVIDER_WORDS)
        assert ar
    assert LD.GROUPS['global_sanctions'][0] == 'ComplyNex Global Sanctions Lists'
    assert LD.GROUPS['global_sanctions'][1] == 'قوائم ComplyNex العالمية للعقوبات'


def test_also_listed_text_and_coverage_grouping():
    assert LD.text_display('OpenSanctions · gb_fcdo_sanctions', 'en') == 'ComplyNex Global Sanctions Lists'
    assert LD.text_display('OFAC SDN (US Treasury)', 'en') == 'International sanctions lists'
    rows = [{'source': 'opensanctions', 'records': 10, 'state': 'green', 'updated': '2026-11-01'},
            {'source': 'ofac', 'records': 5, 'state': 'amber', 'updated': '2026-11-03'},
            {'source': 'un', 'records': 2, 'state': 'green'},
            {'table': 'internal_blacklist', 'records': 3, 'state': 'green'},
            {'source': 'opensanctions_pep', 'records': 7, 'state': 'red'}]
    out = LD.coverage_rows(rows, 'en')
    names = [r['name'] for r in out]
    assert names == ['ComplyNex Global Sanctions Lists', 'ComplyNex Global PEP Database', 'ComplyNex Sanctions List',
                     'International sanctions lists']
    intl = out[-1]
    assert intl['records'] == 7 and intl['state'] == 'amber' and intl['updated'] == '2026-11-03'


@pytest.fixture()
def ctx():
    from flask import Flask
    from flask_babel import Babel
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 't'
    Babel(app)
    return app


class _U:
    is_authenticated = True

    def __init__(self, role):
        self.role = role


def _hit():
    return {'source': 'opensanctions', 'source_name': 'OpenSanctions', 'dataset': 'gb_fcdo_sanctions',
            'topics': '["sanction"]', 'list_type': 'SANCTIONS', 'full_name': 'Test Person', 'match_score': 91,
            'id': 123, 'entity_id': 'NK-abc', 'also_listed_in': ['OFAC SDN (US Treasury) · SDGT',
                                                                  'OpenSanctions · us_ofac_sdn'],
            'grouped_hits': [{'source': 'ofac', 'dataset': 'us_ofac_sdn', 'score': 90, 'tier': 'POTENTIAL'}],
            'properties': json.dumps({'sourceUrl': 'https://example.invalid/x'})}


def test_hit_card_under_our_names(ctx, monkeypatch):
    from screening import result_view as rv
    monkeypatch.setattr(LD, 'overrides', lambda force=False: {})
    with ctx.test_request_context('/'):
        monkeypatch.setattr(LD, 'can_see_sources', lambda user=None: False)
        v = rv.match_view(_hit(), 'SANCTIONS', {})
        shown = {k: v.get(k) for k in ('source', 'category', 'also_listed_in', 'url', 'ref', 'nature', 'source_real')}
        shown['grouped_hits'] = [{k: g.get(k) for k in ('source', 'source_label', 'dataset')} for g in v['grouped_hits']]
        text = json.dumps(shown, ensure_ascii=False, default=str).lower()
        assert v['source'] == 'ComplyNex Global Sanctions Lists' and v['category'] == 'Sanctions'
        assert v['also_listed_in'] == ['International sanctions lists']
        assert v['source_real'] is None and v['url'] is None
        assert not any(p in text for p in PROVIDER_WORDS), text
        # the superadmin: our name plus the real source in a muted line
        monkeypatch.setattr(LD, 'can_see_sources', lambda user=None: True)
        s = rv.match_view(_hit(), 'SANCTIONS', {})
        assert s['source'] == 'ComplyNex Global Sanctions Lists' and 'gb_fcdo_sanctions' in s['source_real']


def test_display_only_scores_unchanged(ctx, monkeypatch):
    """The card's score, tier and decision come from the stored result: the names never change them."""
    from screening import result_view as rv
    plain = rv.match_view(_hit(), 'SANCTIONS', {}, names=False)
    with ctx.test_request_context('/'):
        monkeypatch.setattr(LD, 'can_see_sources', lambda user=None: False)
        named = rv.match_view(_hit(), 'SANCTIONS', {})
    for k in ('score', 'tier', 'tier_label', 'identity', 'reasons', 'action', 'name_matched', 'workflow'):
        assert plain.get(k) == named.get(k), k


def test_api_hits_and_public_tree(monkeypatch):
    monkeypatch.setattr(LD, 'overrides', lambda force=False: {})
    from api.v1_common import hit_view
    h = hit_view(_hit())
    assert h['source'] == 'ComplyNex Global Sanctions Lists' and h['list_category'] == 'Sanctions'
    out = LD.public_tree({'hits': [_hit()]})
    text = json.dumps(out).lower()
    assert 'gb_fcdo' not in text and 'example.invalid' not in text and '"opensanctions"' not in text
    # an already-public hit is left alone
    assert LD.public_hit({'source': 'ComplyNex Global Sanctions Lists'}) == {'source': 'ComplyNex Global Sanctions Lists'}


def test_superadmin_names_override(monkeypatch):
    monkeypatch.setattr(LD, 'overrides', lambda force=False: {'international': {'en': 'Official lists', 'ar': ''}})
    assert LD.display('ofac', lang='en') == 'Official lists'
    assert LD.display('ofac', lang='ar') == 'قوائم العقوبات الدولية'
