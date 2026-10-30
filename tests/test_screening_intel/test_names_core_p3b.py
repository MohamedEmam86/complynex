"""Phase 3 (names-core): foreign names written in Arabic / Persian script, long-vowel variants, initials,
compounds written as one or two elements. Names here are invented or generic."""
from screening import match_intel as mi


def s(a, b):
    return mi.name_match(a, b)['score']


def test_persian_urdu_letters_are_read_as_arabic():
    assert mi.tokens('صدیق احمد') == ['صديق', 'احمد']
    assert mi.tokens('رابرت گوردون') == ['رابرت', 'جوردون']
    assert s('Siddique Ahmed', 'صدیق احمد') >= 80
    assert s('Peter Larsen', 'پیتر لارسن') >= 80


def test_foreign_name_written_in_arabic():
    assert s('Inna Yuryevna Petrenko', 'يننا يورييفنا بيترينكو') >= 80     # doubled letters, given name first
    assert s('Elaine Marshall', 'الين مارشال') >= 80                     # El- that is not the article
    assert s('Owen Mabena', 'ووين مابينا') >= 80
    assert s('Chuck Morton', 'تشاك مورتون') >= 80
    assert s("Mish'an Kadhim", 'مشعان كاظم') >= 80                       # apostrophe inside the word


def test_initials_and_letter_names():
    assert s('George W. Scott', 'جورج دبليو. سكوت') >= 80
    # an initial alone carries almost no identity
    assert mi._weight('w') < 1


def test_compound_written_as_one_or_two_elements():
    assert s('Mohammad Khoshnevis', 'محمد خوش نويس') >= 80
    assert s('Salma Bibi', 'سلمى بي بي') >= 80


def test_phonetic_abdul_in_arabic_script():
    assert mi.tokens('ابدول مانان') == mi.tokens('عبد مانان')
    assert s('Abdulkadir Omar Abdullahi', 'ابدولكادير عمر ابدوللاهي') >= 80


def test_long_vowel_variants():
    assert s('ميرفت محمد علي', 'مرفت محمد علي') >= 80
    assert s('شيرين احمد حسن', 'شرين احمد حسن') >= 80
    assert s('جيهان سعيد محمود', 'جهان سعيد محمود') >= 80
    assert s('نيرمين علي', 'نرمين علي') >= 80
    # a long vowel elsewhere still makes another name
    assert mi._same_token('محمد', 'محمود') == 0.0
    assert mi._same_token('حسن', 'حسين') == 0.0
    assert s('محمد علي حسن', 'محمود علي حسن') < 75


def test_titles_from_other_languages():
    assert s('Haji Mohammad Noor', 'حاجي محمد نور') >= 80
    assert s('Mme Sophie Laurent', 'صوفي لوران') >= 80


def test_no_learned_pair_against_the_sounds():
    # a rare dictionary pair that the sounds contradict does not make a match on its own
    assert mi.loose_ratio('borisovich', 'بافلوفيتج') < 0.7
    assert mi.loose_ratio('jorge', 'خورخي') >= 0.7


def test_alignment_takes_best_pairs_first():
    r = mi.name_match('Anna Petrova Ivanova', 'اننا بيتروفا يفانوفا')
    assert r['score'] >= 80 and r['complete']
