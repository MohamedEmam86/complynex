"""Wave 2c: particle-only differences and clean standard transliterations (invented / generic names)."""
from screening import match_intel as m


def s(a, b):
    return m.name_match(a, b)['score']


def test_particle_only_difference_single_element_is_not_a_match():
    assert s('Maria', 'Di Maria') < 75
    assert s('Hai', 'Van Hai') < 75
    assert s('Nguyen Van Hai', 'Nguyen Thi Hai') < 75


def test_particle_difference_with_two_elements_still_matches():
    assert s('Isabel Santos', 'Isabel dos Santos') >= 95


def test_standard_transliterations_are_strong():
    for lat, ar in [('Hamid', 'حامد'), ('Hamid', 'حميد'), ('Hamed', 'حامد'), ('Majid', 'ماجد'),
                    ('Rashid', 'رشيد'), ('Khalid', 'خالد'), ('Walid', 'وليد'), ('Sayed', 'سيد')]:
        assert s(lat, ar) >= 95, (lat, ar)
    assert s('Hamid Ali', 'حامد علي') >= 95


def test_no_initial_vowel_drop_and_lookalikes_stay_apart():
    for lat, ar in [('Hamid', 'احمد'), ('Hamed', 'احمد'), ('Ahmed', 'حامد'),
                    ('Hassan', 'حسين'), ('Hussein', 'حسن')]:
        assert s(lat, ar) < 75, (lat, ar)
    assert s('Ahmed', 'احمد') >= 95


def test_a_rare_learned_pair_never_scores_below_no_learned_pair(monkeypatch):
    # the weekly dictionary rebuild (15 Nov 2026) learned hamid -> حامد at 3% next to حميد: that must not
    # weaken Hamid = حامد below the standard transliteration it got with no learned pair
    for learned in ({'hamid': [['حميد', 4400]]}, {'hamid': [['حميد', 4400], ['حامد', 141]]},
                    {'hamid': [['حميد', 4400], ['حامد', 12]]}):
        monkeypatch.setattr(m, '_XS_DICT', learned)
        assert s('Hamid', 'حامد') >= 95, learned
        assert s('Hamid', 'حميد') >= 95, learned
        assert s('Hamid', 'احمد') < 75, learned
    monkeypatch.setattr(m, '_XS_DICT', {'sayed': [['سيد', 53112], ['سعيد', 2118]],
                                        'hamed': [['حامد', 600], ['حمد', 27]]})
    assert s('Sayed', 'سعيد') < 95          # Sayed is سيد: a canon spelling of another name stays weak
    assert s('Hamed', 'حمد') < 95           # حمد is Hamad: a rare pair of another length stays weak
    assert s('Hamed', 'حامد') >= 95
    monkeypatch.setattr(m, '_XS_DICT', None)
