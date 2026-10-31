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
