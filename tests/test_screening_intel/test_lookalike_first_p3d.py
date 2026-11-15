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


def _without_rule(monkeypatch, *args, **kw):
    # the same record judged as main judges it: no look-alike rule
    with monkeypatch.context() as mp:
        mp.setattr(mi, '_lookalike_first', lambda *a, **k: False)
        return mi.decide(*args, **kw)['match_score']


Q = 'سامي امبابي حسين امين'


def test_decide_is_a_floor_over_main_only(monkeypatch):
    # review 7 Nov: the rule never lowers what main gives, and lifts only to a LOW alert (LOW + 1)
    for raw in (40.0, 60.0, 80.0, 92.0, 99.0):
        for rec, kw in ((_rec(raw), {}), (_rec(raw, date_of_birth='1980-05-01'), {'dob': '1980-05-01'})):
            base = _without_rule(monkeypatch, dict(rec), Q, **kw)
            out = mi.decide(dict(rec), Q, **kw)['match_score']
            assert out == round(max(base, mi.LOW + 1), 2), (raw, kw, base, out)


def test_decide_identifier_conflict_is_untouched_at_high_fuzzy_scores(monkeypatch):
    # review 15 Nov blocker: the floor must not by-pass the name-structure averaging when the DOB or the
    # ID says "different person" - the rule has no effect: the result is exactly main's at any upstream score
    for raw in (80.0, 90.0, 99.0):
        for rec, kw in ((_rec(raw, date_of_birth='1980-05-01'), {'dob': '1962-11-20'}),
                        (_rec(raw, national_id='27001010100022'), {'national_id': '28001010100011'})):
            base = _without_rule(monkeypatch, dict(rec), Q, **kw)
            out = mi.decide(dict(rec), Q, **kw)
            assert out['match_score'] == base, (raw, kw, base, out['match_score'])
            assert not any('one letter' in r for r in out['decision']['reasons'])


def test_decide_record_with_several_name_forms(monkeypatch):
    # review 15 Nov blocker 2: the floored look-alike form must not win over a better real form of the
    # same record; the result is max(main, LOW + 1) without a conflict and exactly main with one
    forms = ('Samy Mahmoud Ali Hassan', 'Samy Mohamed Aly Hasan Elsayed', 'Mohamed Ali Hassan')
    q = 'سامي محمد علي حسن'
    for other in forms:
        for raw in (60.0, 85.0, 99.0):
            for extra, kw, conflict in (({}, {}, False),
                                        ({'date_of_birth': '1980-05-01'}, {'dob': '1962-11-20'}, True),
                                        ({'national_id': '27001010100022'}, {'national_id': '28001010100011'}, True)):
                rec = {'match_score': raw, 'watchlist_name_ar': 'سامح محمد علي حسن', 'original_name': other,
                       'source': 'internal_blacklist', **extra}
                base = _without_rule(monkeypatch, dict(rec), q, **kw)
                out = mi.decide(dict(rec), q, **kw)['match_score']
                want = base if conflict else round(max(base, mi.LOW + 1), 2)
                assert out == want, (other, raw, kw, base, out)


def test_name_match_keeps_the_unfloored_score():
    nm = mi.name_match('سامي امبابي حسين امين', 'سامح امبابي حسين امين')
    assert nm['lookalike_first'] and nm['score'] == mi.LOW + 1 and nm['score_unfloored'] <= nm['score']


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


def test_fix_decisions_refuses_before_the_relabel(tmp_path, monkeypatch, capsys):
    import sys as _sys
    ar = _load_apply_review()
    monkeypatch.setattr(ar, 'load_jsonl', lambda path: [{'id': 'a', 'cat': 'neg_lookalike_first', 'note': ''}])
    monkeypatch.setattr(ar, 'GOLD_DIR', str(tmp_path))
    monkeypatch.setattr(_sys, 'argv', ['gold_apply_review.py', '--fix-decisions', '--apply'])
    try:
        ar.main()
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError('--fix-decisions ran on data that was not relabelled')
    assert 'run --apply' in capsys.readouterr().out
