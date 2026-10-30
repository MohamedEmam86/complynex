"""Phase 3: Franco-Arabic (P3-7), dialect spellings (P3-8), company words (P3-6).
Names below are invented for the tests."""
from screening import match_intel as mi
from screening import name_variants as nv
from screening import company_match as cm


def s(a, b):
    return mi.name_match(a, b)['score']


# ---------------------------------------------------------------- Franco-Arabic
def test_franco_digits_read_as_letters():
    assert nv.franco('mo7amed') == 'mohamed'
    assert nv.franco('3ali') == 'ali'
    assert nv.franco('5aled') == 'khaled'
    assert nv.franco("7'alil") == 'khalil'
    assert nv.franco('s3d') == 'sad'
    assert nv.franco('ra2fat') == 'rafat'


def test_franco_leaves_number_tokens_alone():
    assert nv.franco('unit 8200') == 'unit 8200'
    assert nv.franco('ahmed ali') == 'ahmed ali'


def test_franco_name_matches_arabic_and_latin():
    assert s('Mo7amed A7med 3ali Sha7at', 'محمد احمد علي شحات') >= 80
    assert s('Mo7amed A7med 3ali Sha7at', 'Mohamed Ahmed Ali Shahat') >= 95
    assert s('5aled Ma7moud Fat7y', 'خالد محمود فتحي') >= 80


def test_franco_does_not_merge_different_names():
    assert s('Ma7moud 3ali 7assan Darwish', 'محمد علي حسن درويش') < 75
    assert s('Ma7moud Sa3d Ibrahim Gad', 'Mohamed Saad Ibrahim Gad') < 75


# ---------------------------------------------------------------- dialect spellings
def test_accents_folded_not_cut():
    assert mi.normalize('Saïd') == mi.normalize('Said')
    assert mi.normalize('Hüseyin Şahin') == mi.normalize('Huseyin Shahin')


def test_maghrebi_spellings():
    assert s('Houcine Rachid Benali', 'Hussein Rachid Benali') >= 90
    assert s('Hacen Larbi Toumi', 'Hassan Larbi Toumi') >= 90
    assert s('Youcef Kamel Brahimi', 'Youssef Kamel Brahimi') >= 90
    assert s('Sidi ould Salem', 'Sidi bin Salem') >= 95


def test_turkish_and_gulf_spellings():
    assert s('Mehmet Ali Yilmaz', 'Mohamed Ali Yilmaz') >= 90
    assert s('Mohd Rashid Al Nuaimi', 'Mohamed Rashid Al Nuaimi') >= 90


def test_dialect_forms_keep_names_apart():
    assert nv.canon('hacen') != nv.canon('hucine')
    assert s('Hacen Omar Belkacem Saidi', 'Hussein Omar Belkacem Saidi') < 75
    # an ordinary element is returned unchanged
    assert nv.canon('belkacem') == 'belkacem'


def test_foreign_spelling_still_compared_as_written():
    # the dialect rule is only a second chance: a spelling that fits an Arabic rendering as written keeps it
    assert s('Husayn Al-Shami', 'حوساين الشامي') >= 80


# ---------------------------------------------------------------- companies
def test_company_synonyms():
    assert cm.same_class(mi.normalize('trading'), mi.normalize('trade'))
    assert s('Nilestar Trade House', 'Nilestar Trading House') >= 95
    assert s('Orion Intl Logistics Group', 'Orion International Logistics Group') >= 95
    assert s('Crescent Organisation for Relief', 'Crescent Organization for Relief') >= 95
    assert s('بنك الواحة الوطني', 'مصرف الواحة الوطني') >= 95
    assert s('Zarqa Industries Holding', 'Zarqa Industry Holdings') >= 95


def test_company_generic_words_do_not_make_a_match():
    assert s('Alpha Star Trading', 'Beta Moon Trading') < 75
    assert s('Nile Bank', 'Delta Banque') < 75
    assert not cm.same_class('trade', 'bank')
