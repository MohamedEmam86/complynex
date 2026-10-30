"""Fixes after the independent review of wave 1 (alias truncation, Hassan / Hussein, particles,
cross-script look-alikes, Arabic comma on queries, gender information badge)."""
from screening import match_intel as mi
from screening import alias_quality as aq
from screening import result_view as rv


def _score(q, l):
    return mi.name_match(q, l)['score']


def test_long_alias_list_never_caps_a_real_hit():
    filler = '|'.join(f'Filler Person Number {i} Zzq' for i in range(41))
    m = {'source': 'ofac', 'entity_type': 'INDIVIDUAL', 'full_name': 'Hamid Karzai Ahmadzai Something',
         'aliases': 'Hamid Karzai|' + filler + '|Hamid Karzai Ahmadzai',
         'properties': {'weak_aliases': ['Hamid Karzai']}, 'match_score': 90.0, 'decision': {}}
    assert aq.check(m, 'Hamid Karzai Ahmadzai') is None


def test_glued_arabic_alias_is_two_elements():
    assert not aq.is_short_alias('ابومحمد العراقي', True)
    assert aq.is_short_alias('حمزة', True)


def test_hussein_spellings_are_not_hassan():
    for lat in ('hucine', 'houcine', 'hassine', 'houssine', 'husseine'):
        assert mi._same_token(lat, 'حسن') < 0.85, lat
    assert _score('Houcine Ali Omar', 'حسن علي عمر') < 75
    assert mi._same_token('amine', 'امن') < 0.85


def test_true_final_e_spellings_still_match():
    assert mi._same_token('rachide', 'رشيد') >= 0.85
    assert mi._same_token('amine', 'امين') >= 0.85
    assert mi._same_token('mohsin', 'محسن') >= 0.85


def test_particles_are_kept_with_low_weight():
    assert _score('Nguyen Van Hai', 'Nguyen Thi Hai') < 75
    assert _score('Di Maria', 'Maria') < 100
    assert _score('Alfred de Zayas', 'آلفرد د زایاس') >= 80
    assert _score('Isabel dos Santos', 'Isabel dos Santos') == 100


def test_cross_script_lookalikes():
    # only meaningful when the learned dictionary knows the usual spelling
    if mi._xs_dict().get('hamed'):
        assert _score('Hamed Ali Omar', 'احمد علي عمر') < 80
    if mi._xs_dict().get('hosni'):
        assert _score('Hosni Ali Omar', 'حسين علي عمر') < 80
    assert _score('Hosni Ali Omar', 'حسني علي عمر') >= 90
    assert _score('Ahmed Ali Omar', 'احمد علي عمر') >= 90
    assert _score('Mohamed Ali', 'محمد علي') >= 90


def test_arabic_comma_only_on_listed_names():
    assert mi._uncomma('محمد علي، القاهرة', arabic_comma=False) == 'محمد علي، القاهرة'
    assert mi._uncomma('عزام، عبد الله') == 'عبد الله عزام'


def test_gender_differs_is_information_only():
    m = {'source': 'ofac', 'full_name': 'X Y', 'match_score': 90.0,
         'decision': {'gender': 'differ', 'identity': 'unknown', 'tier': 'POTENTIAL'}}
    v = rv.match_view(m, 'SANCTIONS', {})
    assert v['gender_differs'] is True
