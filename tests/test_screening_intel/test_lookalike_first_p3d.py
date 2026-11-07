from screening import match_intel as mi


def s(a, b):
    return mi.name_match(a, b)['score']


def test_one_letter_first_name_rest_identical_is_low_alert():
    for q, l in (('سامي امبابي حسين امين', 'سامح امبابي حسين امين'),
                 ('محمود حفني ابراهيم سليم', 'محمد حفني ابراهيم سليم'),
                 ('احمد عبد الله محمد سالم', 'حامد عبد الله محمد سالم')):
        r = mi.name_match(q, l)
        assert r['lookalike_first'], (q, l)
        assert 75 <= r['score'] < 80, (q, l, r['score'])


def test_latin_one_letter_first_name():
    r = mi.name_match('Samy Ahmed Hassan Farag', 'Sami Ahmed Hassan Farag')
    assert r['score'] >= 75


def test_siblings_and_two_element_names_stay_different():
    assert s('كريم محمد فاروق عوض محمد', 'جويريه محمد فاروق عوض محمد') < 75
    assert s('سيد سعداوي عبده علي سيد', 'محمد سعداوي عبده علي سيد') < 75
    assert s('احمد علي', 'حامد علي') < 75
    assert s('Alexey Sergeevich BESPROZVANNYKH', 'Alexey Sergeevich GALCHENKOV') < 75


def test_rest_must_be_identical():
    # a different family element as well: not the rule
    assert s('سامي امبابي حسين امين', 'سامح امبابي حسين ابراهيم') < 75


def test_cross_script_veto_kept():
    assert s('Hamid Ali Omar', 'احمد علي عمر') < 75


def test_decide_keeps_it_below_potential():
    m = {'match_score': 92.0, 'full_name': 'سامح امبابي حسين امين', 'source': 'internal_blacklist'}
    out = mi.decide(m, 'سامي امبابي حسين امين')
    assert 75 <= out['match_score'] < 80
    assert any('one letter' in r for r in out['decision']['reasons'])
