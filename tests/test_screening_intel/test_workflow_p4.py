"""Phase 4: incomplete screening (P4-1), explanation (P4-2), action by list type (P4-3), G9."""
import json
import os
import re

import pytest

from screening import workflow as wf
from screening import result_view as rv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ----------------------------------------------------------------------- P4-1
def test_search_index_down_blocks():
    blk, warn = wf.completeness(es_degraded=True, freshness=[])
    assert [b['code'] for b in blk] == ['search_index'] and not warn
    assert blk[0]['en'] and blk[0]['ar']


def test_semantic_down_blocks():
    blk, _ = wf.completeness(semantic_degraded=True, freshness=[])
    assert [b['code'] for b in blk] == ['semantic']


def test_overdue_list_blocks_failed_list_within_age_warns():
    rows = [
        {'source': 'un', 'name': 'UN', 'state': 'red', 'problem': 'overdue', 'age_hours': 80.2, 'max_age_hours': 48},
        {'source': 'ofac', 'name': 'OFAC', 'state': 'red', 'problem': 'failed', 'age_hours': 20, 'max_age_hours': 48},
        {'source': 'eu', 'name': 'EU', 'state': 'red', 'problem': 'blocked', 'age_hours': 5, 'max_age_hours': 48},
        {'source': 'hmt', 'name': 'UK', 'state': 'green', 'problem': None, 'age_hours': 5, 'max_age_hours': 96},
    ]
    blk, warn = wf.completeness(freshness=rows)
    assert [(b['code'], b['source']) for b in blk] == [('list_overdue', 'un')]
    assert '80' in blk[0]['en'] and '48' in blk[0]['en']
    assert sorted(w['code'] for w in warn) == ['list_blocked', 'list_failed']


def test_failed_list_older_than_allowed_age_blocks():
    rows = [{'source': 'ofac', 'name': 'OFAC', 'state': 'red', 'problem': 'failed', 'age_hours': 60, 'max_age_hours': 48}]
    blk, _ = wf.completeness(freshness=rows)
    assert [b['code'] for b in blk] == ['list_overdue']


def test_unreadable_freshness_never_blocks():
    blk, warn = wf.completeness(freshness=None)
    assert blk == [] and warn == []


def test_adverse_media_error_is_a_warning_only():
    blk, warn = wf.completeness(adverse_error='timeout', freshness=[])
    assert not blk and [w['code'] for w in warn] == ['adverse_media']


@pytest.mark.parametrize('status,expected', [
    ('CLEAR', 'INCOMPLETE'), ('LOW_MATCH', 'INCOMPLETE'), ('POTENTIAL_MATCH', 'POTENTIAL_MATCH'),
    ('CONFIRMED_HIT', 'CONFIRMED_HIT'), ('REVIEW_REQUIRED', 'REVIEW_REQUIRED'), ('WHITE_LISTED', 'WHITE_LISTED')])
def test_finalize_status_never_clear_when_blocked(status, expected):
    assert wf.finalize_status(status, [{'code': 'search_index'}]) == expected
    assert wf.finalize_status(status, []) == status


def test_verdict_incomplete_without_alert():
    v = rv.overall([], [], [], {}, [], incomplete=[{'code': 'search_index'}])
    assert v[0] == 'danger' and 'incomplete' in v[1].lower()
    low = [{'tier': 'LOW', 'nature': None}]
    assert 'incomplete' in rv.overall(low, [], [], {}, [], incomplete=[{'code': 'x'}])[1].lower()


def test_verdict_hit_kept_when_incomplete():
    s = [{'tier': 'CONFIRMED', 'nature': None}]
    assert rv.overall(s, [], [], {}, [], incomplete=[{'code': 'x'}])[1] == 'Confirmed sanctions match'
    assert rv.overall([], [], [], {}, [])[1] == 'Clear — no match'


# ----------------------------------------------------------------------- P4-3
@pytest.mark.parametrize('m,expected', [
    ({'source': 'un'}, 'SANCTIONS'), ({'source': 'ofac'}, 'SANCTIONS'),
    ({'source': 'emlcu'}, 'EMLCU'), ({'source': 'INTERNAL_BLACKLIST'}, 'INTERNAL'),
    ({'source': 'internal_pep'}, 'PEP'), ({'source': 'pma_ps'}, 'PMA'),
    ({'source': 'pma_ps_reg', 'list_type': 'REGULATORY'}, 'REGULATORY'),
    ({'source': 'opensanctions_pep', 'topics': '["role.pep"]', 'dataset': 'peps'}, 'PEP'),
    ({'source': 'opensanctions', 'list_type': 'CONTEXT', 'topics': '', 'dataset': ''}, 'CONTEXT'),
    ({'source': 'opensanctions', 'topics': '["crime"]', 'dataset': 'interpol_red_notices'}, 'CRIME'),
])
def test_list_type(m, expected):
    assert wf.list_type_of(m) == expected


def test_default_table_matches_policy():
    t = wf.DEFAULT_TABLE
    for k in ('SANCTIONS', 'TERROR', 'UNCLASSIFIED'):
        assert t[k] == 'FREEZE_ESCALATE'
    assert t['PEP'] == 'EDD'
    assert t['CRIME'] == t['SANCTION_LINKED'] == 'MLRO_DECISION'
    for k in ('DEBARMENT', 'REG_ACTION', 'TRADE_RISK', 'EXPORT_CONTROL'):
        assert t[k] == 'REVIEW'
    assert t['CONTEXT'] == t['POI'] == 'INFORMATION'
    for k in ('INTERNAL', 'EMLCU', 'PMA'):
        assert t[k] == 'FREEZE_REPORT'
    assert t['REGULATORY'] == 'KYB_REVIEW'
    assert set(t) == set(wf.LIST_TYPES) and not wf.validate_table(t)


def test_migration_seeds_the_default_table():
    sql = open(os.path.join(ROOT, 'database', 'migrations', '20261116_p4_list_action_table.sql'), encoding='utf-8').read()
    seeded = json.loads(re.search(r"'(\{.*?\})'", sql, re.S).group(1))
    assert seeded == wf.DEFAULT_TABLE
    assert 'WHERE NOT EXISTS' in sql


def test_pep_is_never_a_rejection_or_freeze():
    a = wf.action_for({'source': 'internal_pep', 'decision': {'tier': 'CONFIRMED'}}, wf.DEFAULT_TABLE)
    assert a['code'] == 'EDD'
    assert 'freeze' not in a['step']['en'].lower() and 'not a reason to reject' in a['step']['en'].lower()


def test_action_text_follows_tier():
    t = wf.DEFAULT_TABLE
    conf = wf.action_for({'source': 'un', 'decision': {'tier': 'CONFIRMED'}}, t)
    pot = wf.action_for({'source': 'un', 'decision': {'tier': 'POTENTIAL'}}, t)
    low = wf.action_for({'source': 'un', 'decision': {'tier': 'LOW'}}, t)
    assert 'Freeze funds without delay' in conf['step']['en']
    assert pot['step']['en'].startswith('Hold')
    assert low['step']['en'].startswith('Low-confidence')
    assert conf['step']['ar'] and conf['label']['ar']


def test_lifted_listing_is_not_a_freeze():
    a = wf.action_for({'source': 'INTERNAL_BLACKLIST', 'legal_status': 'LIFTED', 'decision': {'tier': 'CONFIRMED'}},
                      wf.DEFAULT_TABLE)
    assert 'lifted' in a['step']['en'].lower() and 'no freeze' in a['step']['en'].lower()


def test_mlro_override_applies_and_invalid_rejected():
    t = dict(wf.DEFAULT_TABLE, CRIME='FREEZE_ESCALATE')
    assert wf.action_for({'source': 'opensanctions', 'topics': '["crime"]', 'dataset': 'x'}, t)['code'] == 'FREEZE_ESCALATE'
    assert wf.validate_table({'NOPE': 'EDD'}) and wf.validate_table({'PEP': 'NOPE'})


# ----------------------------------------------------------------------- G9
def test_identity_not_verifiable_when_customer_gave_nothing():
    st = wf.identity_status({'date_of_birth': '1970-01-01', 'decision': {'identity': 'unknown'}}, {'dob': False, 'nid': False})
    assert st['state'] == 'not_verifiable' and 'obtain' in st['en']


def test_identity_not_verifiable_when_list_has_no_identifiers():
    st = wf.identity_status({'decision': {'identity': 'unknown'}}, {'dob': True})
    assert st['state'] == 'not_verifiable' and 'no identifiers' in st['en']


def test_identity_verified_and_conflict():
    assert wf.identity_status({'decision': {'identity': 'id_match'}})['state'] == 'verified'
    assert wf.identity_status({'decision': {'identity': 'id_conflict'}})['state'] == 'conflict'


# ----------------------------------------------------------------------- P4-2
def _hit():
    return {'source': 'un', 'match_score': 88.0, 'legal_status': 'LIFTED',
            'decision': {'tier': 'POTENTIAL', 'identity': 'unknown', 'country': 'agree', 'dob': None,
                         'gender': 'differ',
                         'weak_alias': {'state': 'kept'},
                         'name': {'matched': [('محمد', 'محمد'), ('ali', 'علي'), ('hasan', 'hassan')],
                                  'missing_from_query': ['ibrahim'], 'extra_in_query': [],
                                  'order_ok': True, 'complete': False}}}


def test_explanation_lines():
    e = wf.explain(_hit())
    txt = ' '.join(e['en'])
    assert 'Name elements matched: 3' in txt
    assert '1 identical' in txt and '1 by transliteration' in txt and '1 as a spelling variant' in txt
    assert 'ibrahim' in txt and 'Nationality / country agrees' in txt
    assert 'Gender differs (information only)' in txt and 'weak alias' in txt and 'lifted' in txt
    assert 'List type: Sanctions' in txt
    assert len(e['ar']) == len(e['en'])


def test_explanation_without_decision():
    e = wf.explain({'source': 'ofac', 'match_score': 77})
    assert e['en'][0].startswith('Name similarity 77')


def test_annotate_keeps_every_hit_and_score():
    hits = [_hit(), {'source': 'ofac', 'match_score': 80.0}, 'not-a-dict']
    before = [dict(h) if isinstance(h, dict) else h for h in hits]
    out = wf.annotate(hits, {'dob': False, 'nid': False})
    assert len(out) == 3 and out[2] == 'not-a-dict'
    for b, a in zip(before[:2], out[:2]):
        assert a['match_score'] == b['match_score']
        assert set(a) - set(b) == {'workflow'}
        assert a['workflow']['action']['code'] and a['workflow']['explanation']['en']


def test_view_recomputes_for_old_results():
    w = rv._workflow({'source': 'emlcu', 'match_score': 90, 'decision': {'tier': 'POTENTIAL'}}, {'dob': None})
    assert w['action']['code'] == 'FREEZE_REPORT'
    assert w['identity_status']['state'] == 'not_verifiable'


# ----------------------------------------------------------------------- templates parse (no inline handlers)
@pytest.mark.parametrize('name', ['screening_result.html', 'list_actions.html', 'report.html', 'dashboard.html',
                                  'history.html', 'screening_history_full.html', 'bulk_results.html', 'list_versions.html'])
def test_templates_parse(name):
    from jinja2 import Environment
    src = open(os.path.join(ROOT, 'templates', 'screening', name), encoding='utf-8').read()
    Environment(extensions=['jinja2.ext.i18n', 'jinja2.ext.do', 'jinja2.ext.loopcontrols']).parse(src)
    if name == 'list_actions.html':
        assert not re.search(r'\son[a-z]+="', src)
