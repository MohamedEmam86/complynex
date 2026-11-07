import importlib.util
import os

from screening import match_intel as mi


def s(a, b):
    return mi.name_match(a, b)['score']


def test_one_letter_first_name_rest_identical_is_low_alert():
    for q, l in (('سامي امبابي حسين امين', 'سامح امبابي حسين امين'),
                 ('محمود حفني ابراهيم سليم', 'محمد حفني ابراهيم سليم'),
                 ('احمد عبد الله محمد سالم', 'حامد عبد الله محمد سالم')):
        r = mi.name_match(q, l)
        assert r['lookalike_first'], (q, l)
        assert mi.LOW <= r['score'] < mi.POTENTIAL, (q, l, r['score'])


def test_latin_one_letter_first_name():
    r = mi.name_match('Samy Ahmed Hassan Farag', 'Sami Ahmed Hassan Farag')
    assert r['score'] >= mi.LOW


def test_floor_follows_the_live_low_threshold(monkeypatch):
    # thresholds.apply() changes mi.LOW at run time: the floor must follow it
    monkeypatch.setattr(mi, 'LOW', 85.0)
    r = mi.name_match('سامي امبابي حسين امين', 'سامح امبابي حسين امين')
    assert r['lookalike_first'] and r['score'] >= 86.0


def test_siblings_and_two_element_names_stay_different():
    assert s('كريم محمد فاروق عوض محمد', 'جويريه محمد فاروق عوض محمد') < mi.LOW
    assert s('سيد سعداوي عبده علي سيد', 'محمد سعداوي عبده علي سيد') < mi.LOW
    assert s('احمد علي', 'حامد علي') < mi.LOW
    assert s('Alexey Sergeevich BESPROZVANNYKH', 'Alexey Sergeevich GALCHENKOV') < mi.LOW


def test_rest_must_be_identical():
    # a different family element as well: not the rule
    assert s('سامي امبابي حسين امين', 'سامح امبابي حسين ابراهيم') < mi.LOW


def test_cross_script_veto_kept():
    assert s('Hamid Ali Omar', 'احمد علي عمر') < mi.LOW


def _rec(score, **kw):
    m = {'match_score': score, 'full_name': 'سامح امبابي حسين امين', 'source': 'internal_blacklist'}
    m.update(kw)
    return m


def test_decide_raises_a_low_name_to_a_low_alert():
    out = mi.decide(_rec(60.0), 'سامي امبابي حسين امين')
    assert out['match_score'] >= mi.LOW
    assert any('one letter' in r for r in out['decision']['reasons'])


def test_decide_never_lowers_a_potential_hit():
    # review 7 Nov: the look-alike rule is a floor only; a DOB that agrees keeps the hit POTENTIAL
    out = mi.decide(_rec(92.0, date_of_birth='1980-05-01'), 'سامي امبابي حسين امين', dob='1980-05-01')
    assert out['match_score'] >= mi.POTENTIAL, out['match_score']
    plain = mi.decide(_rec(92.0), 'سامي امبابي حسين امين')
    assert plain['match_score'] >= mi.LOW


def test_decide_dob_conflict_wins_over_the_floor():
    out = mi.decide(_rec(80.0, date_of_birth='1980-05-01'), 'سامي امبابي حسين امين', dob='1962-11-20')
    assert out['match_score'] < mi.LOW, out['match_score']
    assert not any('one letter' in r for r in out['decision']['reasons'])


def _load_apply_review():
    p = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'gold_apply_review.py')
    spec = importlib.util.spec_from_file_location('gold_apply_review', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_review_decisions_fix_is_idempotent_and_keeps_the_note():
    ar = _load_apply_review()
    sample = {'a': {'id': 'a', 'cat': 'pos_lookalike_first_typo',
                    'note': 'x | was neg_lookalike_first; relabelled 2026-11-02 (owner rule)'},
              'b': {'id': 'b', 'cat': 'neg_sibling', 'note': ''},
              'c': {'id': 'c', 'cat': 'pos_lookalike_first_typo',
                    'note': 'x | was neg_lookalike_first; relabelled 2026-11-02 (owner rule)'}}
    doc = {'decisions': {'a': {'decision': 'correct', 'note': 'reviewer note'},
                         'b': {'decision': 'correct', 'note': ar.OVERRULED_NOTE, 'original_note': 'o'},
                         'c': {'decision': 'applied', 'note': 'n'}}}
    assert ar.overrule_lookalike(doc, sample) == 1
    a = doc['decisions']['a']
    assert a['decision'] == 'overruled' and a['original_note'] == 'reviewer note'
    assert a['note'] == ar.LOOKALIKE_NOTE
    assert doc['decisions']['b']['note'] == ar.OVERRULED_NOTE
    assert doc['decisions']['c']['decision'] == 'applied'
    assert ar.overrule_lookalike(doc, sample) == 0
    assert doc['decisions']['a']['original_note'] == 'reviewer note'
