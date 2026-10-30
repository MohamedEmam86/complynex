from screening import list_category as LC
from screening.match_classifier import classify_match


def test_topics_win_most_serious():
    assert LC.categorize('["role.pep", "crime"]') == 'CRIME'
    assert LC.categorize(['sanction', 'role.pep']) == 'SANCTIONS'
    assert LC.categorize('["sanction.linked"]') == 'SANCTION_LINKED'
    assert LC.categorize('["crime.terror"]') == 'TERROR'
    assert LC.categorize('["debarment"]') == 'DEBARMENT'
    assert LC.categorize('["reg.warn"]') == 'REG_ACTION'
    assert LC.categorize('["role.rca"]') == 'PEP'
    assert LC.categorize('["sanction.counter"]') == 'COUNTER_SANCTIONS'
    assert LC.categorize('["export.control.linked"]') == 'EXPORT_CONTROL'
    assert LC.categorize('["fin.bank"]', 'ext_ru_egrul') == 'CONTEXT'
    assert LC.categorize('{sanction,role.pep}') == 'SANCTIONS'


def test_empty_topics_use_dataset():
    assert LC.categorize('[]', 'ext_ru_egrul') == 'CONTEXT'
    assert LC.categorize('', 'ua_nsdc_sanctions') == 'SANCTIONS'
    assert LC.categorize(None, 'il_mod_terrorists') == 'TERROR'
    assert LC.categorize('[]', 'in_mha_banned') == 'TERROR'
    assert LC.categorize('[]', 'us_tx_med_exclusions') == 'DEBARMENT'
    assert LC.categorize('[]', 'au_abf_sanctioned_sponsors') == 'REG_ACTION'
    assert LC.categorize('[]', 'iadb_sanctions') == 'DEBARMENT'
    assert LC.categorize('[]', 'tr_wanted') == 'CRIME'
    assert LC.categorize('[]', 'me_acp_peps') == 'PEP'
    assert LC.categorize('[]', 'shu_uyghur_companies') == 'TRADE_RISK'
    assert LC.categorize('[]', 'fr_tresor_gels_avoir') == 'SANCTIONS'
    assert LC.categorize('[]', 'tokyo_mou_detention') == 'CONTEXT'
    assert LC.categorize('[]', 'us_fincen_special_measures') == 'SANCTIONS'
    assert LC.categorize('[]', 'us_ofac_enforcement_actions') == 'REG_ACTION'


def test_unknown_dataset_is_strict():
    for ds in ('us_ofac_sdn', 'eu_fsf', 'eu_travel_bans', 'ua_sfms_blacklist', 'kg_fiu_national',
               'pk_proscribed_persons', 'some_new_list'):
        assert LC._dataset_cat(ds) in ('SANCTIONS', 'TERROR', 'UNCLASSIFIED'), ds
    assert LC.categorize('[]', None) == 'UNCLASSIFIED'


def test_several_datasets_worst_wins():
    assert LC.categorize('[]', ['ext_ru_egrul', 'ua_nsdc_sanctions']) == 'SANCTIONS'
    assert LC.categorize('["role.pep"]', ['wikidata', 'ua_nsdc_sanctions']) == 'SANCTIONS'


def test_for_match_stored_values():
    assert LC.for_match({'source': 'opensanctions', 'list_type': 'SANCTIONS'}) == 'SANCTIONS'
    assert LC.for_match({'source': 'opensanctions', 'list_type': 'OpenSanctions'}) == 'UNCLASSIFIED'
    # stored category never gets milder because of stale topics
    assert LC.for_match({'source': 'opensanctions', 'list_type': 'CRIME', 'topics': '["poi"]'}) == 'CRIME'
    # new topics make it stricter than the stored category
    assert LC.for_match({'source': 'opensanctions', 'list_type': 'REG_ACTION', 'topics': '["sanction"]'}) == 'SANCTIONS'
    assert LC.for_match({'source': 'opensanctions_pep', 'list_type': 'PEP', 'topics': '[]', 'dataset': 'wikidata'}) == 'PEP'
    assert LC.for_match({'source': 'ofac', 'list_type': 'SANCTIONS'}) is None


def test_nature_note():
    n = LC.nature({'source': 'opensanctions', 'topics': '[]', 'dataset': 'ext_ru_egrul'})
    assert n['code'] == 'CONTEXT' and n['kind'] == 'OTHER' and 'سجل الشركات الروسي' in n['note']


def test_classifier_uses_category():
    assert classify_match({'source': 'opensanctions', 'list_type': 'SANCTIONS', 'topics': '[]',
                           'dataset': 'ext_ru_egrul'}) == 'OTHER'
    assert classify_match({'source': 'opensanctions', 'list_type': 'SANCTIONS', 'topics': '["debarment"]'}) == 'OTHER'
    assert classify_match({'source': 'opensanctions', 'list_type': 'SANCTIONS', 'topics': '["sanction"]'}) == 'SANCTIONS'
    assert classify_match({'source': 'opensanctions', 'list_type': 'OpenSanctions', 'topics': '["wanted"]'}) == 'SANCTIONS'
    assert classify_match({'source': 'opensanctions', 'list_type': 'SANCTIONS', 'topics': '["role.pep"]'}) == 'PEP'
    assert classify_match({'source': 'opensanctions', 'list_type': 'CONTEXT'}) == 'OTHER'
    assert classify_match({'source': 'ofac', 'list_type': 'SANCTIONS'}) == 'SANCTIONS'


def test_match_view_kind_and_action_follow_nature():
    from screening import result_view as rv
    v = rv.match_view({'source': 'opensanctions', 'list_type': 'SANCTIONS', 'topics': '[]',
                       'dataset': 'ext_ru_egrul', 'match_score': 90}, 'SANCTIONS', {})
    assert v['kind'] == 'OTHER' and 'Freeze' not in (v.get('action') or '')
    v = rv.match_view({'source': 'opensanctions', 'list_type': 'OpenSanctions', 'topics': '["sanction"]',
                       'match_score': 97}, 'PEP', {})
    assert v['kind'] == 'SANCTIONS'


def test_overall_no_freeze_for_crime():
    from screening import result_view as rv
    crime = {'tier': 'CONFIRMED', 'nature': {'code': 'CRIME'}}
    assert 'Freeze' not in rv.overall([crime], [], [], None, [])[2]
    real = {'tier': 'CONFIRMED', 'nature': None}
    assert 'Freeze' in rv.overall([real], [], [], None, [])[2]
