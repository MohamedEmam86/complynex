from screening import regulatory as reg

C = [{'id': 1, 'list_type': 'SANCTIONS'}, {'id': 2, 'list_type': 'REGULATORY'}, {'id': 3, 'list_type': 'regulatory'}]


def test_scope_kyb_default():
    assert reg.included('INDIVIDUAL', None, None, 'kyb') is False
    assert reg.included('INDIVIDUAL', 'KYB', None, 'kyb') is True       # KYB director / UBO
    assert reg.included('ENTITY', None, None, 'kyb') is True
    assert reg.included('MERCHANT', 'API', None, 'kyb') is True
    assert reg.included(None, None, None, 'kyb') is False


def test_scope_all_off_and_override():
    assert reg.included('INDIVIDUAL', None, None, 'all') is True
    assert reg.included('ENTITY', 'KYB', None, 'off') is False
    assert reg.included('INDIVIDUAL', None, True, 'off') is True
    assert reg.included('ENTITY', 'KYB', False, 'all') is False


def test_apply_filters_only_regulatory():
    assert [c['id'] for c in reg.apply(C, False)] == [1]
    assert [c['id'] for c in reg.apply(C, True)] == [1, 2, 3]
    assert reg.apply([], False) == []


def test_is_regulatory_by_source_suffix():
    assert reg.is_regulatory({'source': 'pma_ps_reg', 'list_type': 'SANCTIONS'})
    assert not reg.is_regulatory({'source': 'pma_ps', 'list_type': 'SANCTIONS'})


def test_screening_type_pairs():
    assert reg.included('INDIVIDUAL', ('API', 'KYB'), None, 'kyb') is True
    assert reg.included('INDIVIDUAL', ('Manual', None), None, 'kyb') is False
    assert reg.included('INDIVIDUAL', 'KYB_DIRECTOR', None, 'kyb') is True


def test_regulatory_hit_is_not_a_sanctions_hit():
    from screening.match_classifier import classify_match
    assert classify_match({'list_type': 'REGULATORY', 'source': 'pma_ps_reg', 'topics': '["reg.action"]'}) == 'OTHER'
    assert classify_match({'list_type': 'SANCTIONS', 'source': 'pma_ps'}) == 'SANCTIONS'


def test_importer_dates():
    import importlib.util, os
    p = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'import_regulatory_list.py')
    spec = importlib.util.spec_from_file_location('irl', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.iso_date('15/03/2024') == '2024-03-15T00:00:00'
    assert m.iso_date('٢٠٢٤-٠٣-١٥') == '2024-03-15T00:00:00'
    assert m.iso_date('45366') == '2024-03-15T00:00:00'
    assert m.iso_date('') == ''
    assert m.iso_date('March 2024') is None
