"""P4-5 / P4-6 / P4-7 (p4-evidence): clearance scope, false-positive reasons, evidence pack hash."""
from screening import clearance_scope as CS
from screening import fp_reasons as FPR
from screening import evidence_pack as EP

ENTRY = {'id': 7, 'approved_by_name': 'Mlro One', 'approval_date': '2026-10-01 10:00:00'}
ROW = {'id': 11, 'full_name': 'Person A', 'aliases': '["P. A", "Alias Two"]', 'date_of_birth': '1970-01-02',
       'nationality': 'EG', 'list_type': 'SANCTIONS', 'source': 'un', 'is_active': 1}


def _hit(rid=11, src='un', score=88.0, ident=None):
    m = {'id': rid, 'source': src, 'full_name': 'Person A', 'match_score': score}
    if ident:
        m['decision'] = {'identity': ident, 'identifier_match': ident == 'id_match'}
    return m


def test_fingerprint_order_insensitive_and_name_moves():
    a = CS.fingerprint(CS.KIND_WATCHLIST, ROW)
    b = CS.fingerprint(CS.KIND_WATCHLIST, dict(ROW, aliases='Alias Two; p. a'))
    c = CS.fingerprint(CS.KIND_WATCHLIST, dict(ROW, full_name='Alias Two', aliases='["Person A", "P. A"]'))
    assert a == b == c


def test_fingerprint_changes_on_identifying_content():
    a = CS.fingerprint(CS.KIND_WATCHLIST, ROW)
    assert a != CS.fingerprint(CS.KIND_WATCHLIST, dict(ROW, date_of_birth='1971-01-02'))
    assert a != CS.fingerprint(CS.KIND_WATCHLIST, dict(ROW, aliases='["P. A", "Alias Two", "New AKA"]'))
    assert a != CS.fingerprint(CS.KIND_WATCHLIST, dict(ROW, list_type='PEP'))
    bl = {'id': 3, 'full_name': 'X', 'legal_status': None}
    assert CS.fingerprint(CS.KIND_BLACKLIST, bl) != CS.fingerprint(CS.KIND_BLACKLIST, dict(bl, legal_status='LIFTED'))


def test_record_key_kinds():
    assert CS.record_key({'id': 5, 'source': 'ofac'}) == ('watchlist', 5)
    assert CS.record_key({'entity_id': 9, 'id': 'x', 'source': 'INTERNAL_BLACKLIST'}) == ('internal_blacklist', 9)
    assert CS.record_key({'entity_id': 4, 'source': 'internal_pep'}) == ('internal_pep', 4)
    assert CS.record_key({'source': 'un'}) is None
    assert CS.record_key('x') is None


def _links(fp, active=True):
    return {('watchlist', 11): {'fingerprint': fp, 'is_active': active, 'cleared_at': '2026-10-01 10:00',
                                'cleared_by_name': 'Analyst'}}


def test_unchanged_cleared_record_is_not_raised():
    fp = CS.fingerprint(CS.KIND_WATCHLIST, ROW)
    kept, cleared = CS.classify([_hit()], ENTRY, _links(fp), {('watchlist', 11): (fp, True)})
    assert kept == [] and len(cleared) == 1
    assert cleared[0]['clearance']['state'] == CS.ST_CLEARED and cleared[0]['clearance']['by'] == 'Analyst'


def test_changed_relisted_identifier_new_come_back():
    fp = CS.fingerprint(CS.KIND_WATCHLIST, ROW)
    kept, cleared = CS.classify([_hit()], ENTRY, _links(fp), {('watchlist', 11): ('other', True)})
    assert cleared == [] and kept[0]['clearance']['state'] == CS.ST_CHANGED
    kept, cleared = CS.classify([_hit()], ENTRY, _links(fp, active=False), {('watchlist', 11): (fp, True)})
    assert cleared == [] and kept[0]['clearance']['state'] == CS.ST_RELISTED
    kept, cleared = CS.classify([_hit(ident='id_match')], ENTRY, _links(fp), {('watchlist', 11): (fp, True)})
    assert cleared == [] and kept[0]['clearance']['state'] == CS.ST_IDENTIFIER
    kept, cleared = CS.classify([_hit(rid=12)], ENTRY, _links(fp), {})
    assert cleared == [] and kept[0]['clearance']['state'] == CS.ST_NEW


def test_legacy_entry_shows_hits_with_note_and_no_entry_changes_nothing():
    kept, cleared = CS.classify([_hit(), _hit(rid=12)], ENTRY, {}, {})
    assert cleared == [] and len(kept) == 2 and all(m['clearance']['state'] == CS.ST_LEGACY for m in kept)
    ms = [_hit()]
    kept, cleared = CS.classify(ms, None, {}, {})
    assert kept == ms and cleared == [] and 'clearance' not in ms[0]


def test_missing_current_state_never_hides():
    fp = CS.fingerprint(CS.KIND_WATCHLIST, ROW)
    kept, cleared = CS.classify([_hit()], ENTRY, _links(fp), {})
    assert cleared == [] and len(kept) == 1


def test_filter_hits_fails_open():
    class Boom:
        def cursor(self, *a, **k):
            raise RuntimeError('db down')
        def rollback(self):
            pass
    ms = [_hit()]
    ctx = {'entry': ENTRY, 'links': _links('x'), 'summary': {}, 'suppress_all': False}
    kept, cleared = CS.filter_hits(Boom(), ms, ctx)
    assert kept == ms and cleared == [] and 'clearance' not in ms[0]
    assert CS.lookup(Boom(), 'NAME') is None


def test_entry_applies_identity_guard():
    e = {'national_id': '29001011234567', 'date_of_birth': '1990-01-01'}
    assert CS.entry_applies(e) and CS.entry_applies(e, national_id='29001011234567')
    assert not CS.entry_applies(e, national_id='29101011234567')
    assert not CS.entry_applies({'date_of_birth': '1990-01-01'}, dob='1991-01-01')
    assert CS.entry_applies({'id': 1}, national_id='29101011234567', dob='1991-01-01')
    assert not CS.entry_applies(None)


def test_name_keys():
    assert CS.name_keys('MOHAMED ALIHASSAN', 'Mohamed  Ali-Hassan') == ['MOHAMED ALIHASSAN', 'MOHAMED  ALI-HASSAN', 'MOHAMED ALI-HASSAN']
    assert CS.name_keys('احمد', None) == ['احمد']


def test_fp_reasons_rules():
    assert FPR.validate([]) is not None
    assert FPR.validate(['gender_differs']) is not None
    assert FPR.validate(['gender_differs', 'common_name']) is not None
    assert FPR.validate(['gender_differs', 'dob_differs']) is None
    assert FPR.validate(['other'], 'short') is not None
    assert FPR.validate(['other'], 'the customer is a company registered in 2021, not the listed person') is None
    assert FPR.parse('dob_differs,bogus,dob_differs') == ['dob_differs']
    assert FPR.as_text(['dob_differs']).startswith('[FP reasons: ')
    assert FPR.as_text([]) == ''


def test_evidence_pack_hash_is_canonical():
    a = {'b': 1, 'a': [1, 2], 'c': {'y': 'ع', 'x': None}}
    b = {'c': {'x': None, 'y': 'ع'}, 'a': [1, 2], 'b': 1}
    assert EP.content_hash(a) == EP.content_hash(b)
    assert EP.content_hash(a) != EP.content_hash(dict(a, b=2))
    assert len(EP.content_hash(a)) == 64


def test_templates_parse():
    import os
    from jinja2 import Environment
    env = Environment(extensions=['jinja2.ext.i18n'])
    env.install_null_translations()
    base = os.path.join(os.path.dirname(__file__), '..', '..', 'templates', 'screening')
    for t in ('_fp_reasons.html', '_cleared_hits.html', 'evidence_pack.html'):
        env.parse(open(os.path.join(base, t), encoding='utf-8').read())
