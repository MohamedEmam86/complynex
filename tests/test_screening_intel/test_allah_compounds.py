"""X-Allah compounds written glued or split, in both scripts (generic name forms)."""
from screening import match_intel as m


def s(a, b):
    return m.name_match(a, b)['score']


def test_allah_compound_glued_or_split():
    assert s('Hassan Nasrallah', 'Hassan Nasr Allah') >= 90
    assert s('Mohamed Fadlallah', 'Mohamed Fadl Allah') >= 90
    assert s('Hassan Nasrullah', 'Hassan Nasrallah') >= 90
    assert s('حسن نصرالله', 'حسن نصر الله') >= 90
    assert s('محمد فضل الله', 'محمد فضلالله') >= 90


def test_allah_compound_cross_script():
    assert s('Hassan Nasrallah', 'حسن نصر الله') >= 90
    assert s('Hassan Nasr Allah', 'حسن نصرالله') >= 90
    assert s('Mohamed Fadlallah', 'محمد فضل الله') >= 90
    assert s('Khairallah Ali', 'خير الله علي') >= 90


def test_first_part_alone_is_not_the_compound():
    assert s('Nasr', 'Nasrallah') < 75
    assert s('Hassan Nasr', 'Hassan Nasrallah') < 75
    assert s('Hassan Nasr', 'حسن نصر الله') < 75
    assert s('حسن نصر', 'حسن نصرالله') < 75


def test_abd_allah_unchanged_and_lookalike_words_untouched():
    assert s('Ali Abdallah', 'Ali Abd Allah') >= 95
    assert s('Ali Abdallah', 'علي عبد الله') >= 95
    assert m.normalize('محمد عبد الله') == 'محمد عبد الله'
    assert m.normalize('Mullah Omar') == 'mulah omar'
    assert 'jamilah' in m.normalize('Jamilah')
