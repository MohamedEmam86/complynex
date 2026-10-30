"""P3-11 input-quality warnings, P3-10 gender never lowers a hit, G8 weak aliases."""
from screening import input_quality as iq
from screening import alias_quality as aq
from screening import match_intel as mi


# ---------------------------------------------------------------- P3-11
def _codes(*a, **k):
    return set(iq.codes(iq.assess(*a, **k)))


def test_clean_full_input_has_no_warning():
    assert _codes('محمد أحمد علي حسن', 'INDIVIDUAL', 'EG', '1980-01-01') == set()
    assert _codes('Misr Trading Company', 'ENTITY', 'Egypt') == set()


def test_single_word_and_two_words():
    assert 'single_word' in _codes('محمد', 'INDIVIDUAL', 'EG', '1980-01-01')
    assert 'two_words' in _codes('Mohamed Ali', 'INDIVIDUAL', 'EG', '1980-01-01')
    # a one-word company name is normal
    assert 'single_word' not in _codes('Siemens', 'ENTITY', 'DE')


def test_digits_symbols_mixed_short():
    assert 'has_digits' in _codes('Ahmed 2 Ali Hassan', 'INDIVIDUAL', 'EG', '1980-01-01')
    assert 'has_digits' in _codes('احمد ٢ علي', 'INDIVIDUAL', 'EG', '1980-01-01')
    w = iq.assess('Ahmed @Ali Hassan!', 'INDIVIDUAL', 'EG', '1980-01-01')
    sym = [x for x in w if x['code'] == 'has_symbols']
    assert sym and '@' in sym[0]['en'] and '!' in sym[0]['ar']
    assert 'mixed_scripts' in _codes('Ahmed علي حسن', 'INDIVIDUAL', 'EG', '1980-01-01')
    assert 'too_short' in _codes('Al', 'INDIVIDUAL', 'EG', '1980-01-01')
    # apostrophes, hyphens and dots are normal in names; & and () in company names
    assert 'has_symbols' not in _codes("Abd-Allah O'Neil Jr.", 'INDIVIDUAL', 'EG', '1980-01-01')
    assert 'has_symbols' not in _codes('Smith & Sons (Egypt)', 'ENTITY', 'EG')


def test_missing_country_and_identifiers():
    c = _codes('محمد أحمد علي حسن', 'INDIVIDUAL')
    assert {'no_country', 'no_identifier'} <= c
    assert 'no_identifier' not in _codes('محمد أحمد علي حسن', 'INDIVIDUAL', 'EG', national_id='26404101900276')
    assert 'no_identifier' not in _codes('Misr Trading Company', 'ENTITY', 'EG')
    assert 'no_country' in _codes('Misr Trading Company', 'ENTITY', 'nan')


def test_every_warning_is_bilingual_and_never_raises():
    for w in iq.assess('x', 'INDIVIDUAL'):
        assert w['en'] and w['ar'] and w['level'] in ('warning', 'info')
    assert iq.assess(None) == [] and iq.assess('   ') == []
    assert isinstance(iq.assess(object()), list)


# ---------------------------------------------------------------- P3-10
def _hit(score, name, **kw):
    m = {'match_score': score, 'watchlist_name_ar': name, 'original_name': name,
         'source': 'emlcu', 'entity_type': 'INDIVIDUAL'}
    m.update(kw)
    return m


def test_gender_never_lowers_or_removes_a_hit():
    name = 'محمود عبد الرحمن سيد حسانين'
    q_nid = '26404101900276'                      # 13th digit odd -> male
    assert mi.decode_egyptian_nid(q_nid)['gender'] == 'M'
    base = mi.decide(_hit(90, name), name, national_id=q_nid)
    diff = mi.decide(_hit(90, name, gender='female'), name, national_id=q_nid)
    assert diff['match_score'] == base['match_score']
    assert diff['decision']['tier'] == base['decision']['tier']
    assert diff['decision']['identity'] != 'gender_conflict'
    assert diff['decision']['gender'] == 'differ'
    assert any('gender differs' in r for r in diff['decision']['reasons'])
    v = mi.identity_verdict(q_nid, listed_gender='female')
    assert v['verdict'] != 'gender_conflict' and v['gender'] == 'differ'


def test_legacy_engine_gender_weights_are_zero():
    # read the source: importing screening.config needs the production environment
    import os, re
    src = open(os.path.join(os.path.dirname(mi.__file__), 'config.py'), encoding='utf-8').read()
    for key in ('GENDER_MATCH_BONUS', 'GENDER_MISMATCH_PENALTY'):
        assert float(re.search(key + r'\s*=\s*(-?[0-9.]+)', src).group(1)) == 0.0


# ---------------------------------------------------------------- G8
def _ofac(score=88.0, **kw):
    m = {'match_score': score, 'full_name': 'Mohammed Hassan Al Rashidi', 'original_name': 'Mohammed Hassan Al Rashidi',
         'aliases': 'Abu Hamza Al Masri|Mohammed Al Rashidi', 'entity_type': 'INDIVIDUAL', 'source': 'ofac',
         'properties': '{"weak_aliases": ["Abu Hamza Al Masri"]}',
         'decision': {'tier': 'POTENTIAL', 'reasons': [], 'identifier_match': False, 'identity': 'unknown'}}
    m.update(kw)
    return m


def test_split_forms():
    strong, weak, _t = aq.split_forms(_ofac(aliases='Abu Hamza Al Masri|Hamza|Mohammed Al Rashidi|Abu'))
    assert 'Abu Hamza Al Masri' in weak and 'Hamza' in weak and 'Abu' in weak
    assert 'Mohammed Al Rashidi' in strong and 'Mohammed Hassan Al Rashidi' in strong
    # companies keep acronyms / one-word names as normal names
    s2, w2, _t2 = aq.split_forms({'full_name': 'Islamic Revolutionary Guard Corps', 'aliases': 'IRGC|Sepah',
                             'entity_type': 'Organization', 'properties': '{}'})
    assert w2 == [] and 'IRGC' in s2


def test_weak_alias_alone_never_alerts():
    m = aq.apply([_ofac()], 'Abu Hamza Al Masri')[0]
    assert m['match_score'] < mi.LOW and m['decision']['tier'] == 'BELOW'
    assert m['decision']['weak_alias']['state'] == 'capped'
    assert any('weak alias' in r for r in m['decision']['reasons'])


def test_short_alias_alone_never_alerts():
    m = aq.apply([_ofac(aliases='Hamza', properties='{}')], 'Hamza')[0]
    assert m['match_score'] < mi.LOW


def test_weak_alias_with_identifier_stays():
    hit = _ofac(decision={'tier': 'POTENTIAL', 'reasons': [], 'identifier_match': True, 'identity': 'corroborated'})
    m = aq.apply([hit], 'Abu Hamza Al Masri')[0]
    assert m['match_score'] == 88.0 and m['decision']['weak_alias']['state'] == 'kept'


def test_strong_name_is_untouched():
    for q in ('Mohammed Hassan Al Rashidi', 'Mohammed Al Rashidi'):
        m = aq.apply([_ofac()], q)[0]
        assert m['match_score'] == 88.0 and 'weak_alias' not in m['decision']


def test_internal_lists_untouched():
    m = aq.apply([_ofac(source='INTERNAL_BLACKLIST', is_internal=True)], 'Abu Hamza Al Masri')[0]
    assert m['match_score'] == 88.0
