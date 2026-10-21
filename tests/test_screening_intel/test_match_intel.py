# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
"""Unit tests for the analyst decision logic (no database)."""
from screening import match_intel as mi


def test_normalisation_variants_are_equal():
    a = mi.tokens('أسامة أحمد محمد النجار')
    b = mi.tokens('اسامه احمد محمد النجار')
    assert a == b
    assert mi.tokens('عبدالرحمن') == mi.tokens('عبد الرحمن')


def test_long_vowel_changes_the_name():
    assert mi._same_token('محمد', 'محمود') == 0.0
    assert mi._same_token('حسن', 'حسين') == 0.0
    assert mi._same_token('حرمن', 'رحمن') > 0      # swapped letters (typo)
    assert mi._same_token('ثابت', 'سابت') > 0      # ث/س confusion


def test_extra_name_in_customer_record_still_matches():
    r = mi.name_match('ايمن فاروق السيد السيد الشاذلي محمد', 'ايمن فاروق السيد السيد الشاذلي')
    assert r['score'] >= 95 and r['cov_listed'] == 1.0


def test_short_listed_name_inside_longer_name_is_partial():
    r = mi.name_match('هاني نبيل حمدي الدسوقي', 'هاني نبيل')
    assert r['partial'] and r['score'] < 85


def test_different_family_is_not_a_match():
    r = mi.name_match('اشرف محمد احمد منصور', 'اشرف محمد احمد الصعيدي')
    assert r['score'] < 75


def test_latin_spellings():
    r = mi.name_match('Nabil Aly Mahmoud Elboushy', 'NABIL ALI MAHMOUD ALBWSHY')
    assert r['score'] >= 90


def test_national_id_decoding():
    d = mi.decode_egyptian_nid('26404101900276')
    assert d['valid'] and d['dob'] == '1964-04-10' and d['gender'] == 'M'
    assert not mi.decode_egyptian_nid('12345')['valid']


def test_identity_verdicts():
    assert mi.identity_verdict('26404101900276', listed_nids=['26404101900276'])['verdict'] == 'id_match'
    assert mi.identity_verdict('28812011234567', listed_nids=['26404101900276'])['verdict'] == 'id_conflict'
    assert mi.identity_verdict(None, '1990-01-01', None, None, '1960')['verdict'] == 'dob_conflict'
    assert mi.identity_verdict(None, None, 'EG', None, None, ['Palestinian'])['verdict'] == 'country_conflict'
    assert mi.identity_verdict(None, None, 'EG', None, None, ['Egyptian'])['verdict'] == 'corroborated'


def _m(score, ar, nid=None, nat=None):
    return {'match_score': score, 'watchlist_name_ar': ar, 'full_name': ar, 'national_id': nid,
            'nationality': nat, 'source_name': 'Internal Blacklist', 'category': 'Legal Order - Asset Freeze'}


def test_decision_tiers():
    name = 'نبيل علي محمود البوشي'
    # complete name, no identifiers -> confirmed on the name (agreed rule)
    assert mi.decide(_m(100, name), name)['decision']['tier'] == 'CONFIRMED'
    # same name, different valid ID -> never confirmed
    m = mi.decide(_m(100, name, nid='26404101900276'), name, national_id='28812011234567')
    assert m['decision']['tier'] != 'CONFIRMED'
    # ID match confirms even with a misspelt name
    m = mi.decide(_m(80, name, nid='26404101900276'), 'نبيل على محمود البوشى', national_id='26404101900276')
    assert m['decision']['tier'] == 'CONFIRMED' and m['match_score'] == 100
    # short listed form inside a longer name -> potential at most
    m = mi.decide(_m(100, 'هاني نبيل'), 'هاني نبيل حمدي الدسوقي')
    assert m['decision']['tier'] != 'CONFIRMED' and m['match_score'] <= 85
    # nationality contradicts and no ID -> not confirmed
    m = mi.decide(_m(100, name, nat='Palestinian'), name, nationality='EG')
    assert m['decision']['tier'] != 'CONFIRMED'


def test_dedupe_keeps_one_row_per_person():
    a = _m(100, 'نبيل علي محمود البوشي')
    b = dict(_m(98, 'نبيل على محمود البوشى'), source_name='Semantic', category='')
    out = mi.dedupe([b, a])
    assert len(out) == 1 and out[0]['match_score'] == 100 and out[0]['also_listed_in']


def test_overall_status():
    assert mi.overall_status([]) == 'CLEAR'
    assert mi.overall_status([{'match_score': 99, 'decision': {'tier': 'POTENTIAL'}}]) == 'POTENTIAL_MATCH'


def test_id_conflict_on_one_record_blocks_name_only_confirmation():
    name = 'نبيل علي محمود البوشي'
    with_id = _m(100, name, nid='26404101900276')
    without_id = dict(_m(100, name), source_name='EMLCU', category='Terrorism')
    out = mi.apply_decisions([with_id, without_id], name, national_id='28812011234567')
    assert all((m.get('decision') or {}).get('tier') != 'CONFIRMED' for m in out)
    assert mi.overall_status(out) != 'CONFIRMED_HIT'


def test_cross_script_names():
    r = mi.name_match('Hossam Thabet Ibrahim', 'حسام ثابت ابراهيم')
    assert r['score'] >= 80
    assert mi.name_match('Ahmed Fathy Ali', 'حسام ثابت ابراهيم')['score'] < 60
    assert mi.to_arabic('Hossam')            # always gives an Arabic rendering


def test_cross_script_match_does_not_confirm_on_name_alone():
    m = mi.decide({'match_score': 99, 'original_name': 'حسام ثابت ابراهيم', 'full_name': None},
                  'Hossam Thabet Ibrahim')
    assert m['decision']['tier'] != 'CONFIRMED'


def test_company_legal_forms_ignored():
    r = mi.name_match('شركة النور للمقاولات ش.م.م', 'النور للمقاولات')
    assert r['complete']
    assert mi.name_match('Al Nour Contracting Co. LLC', 'Al Nour Contracting')['complete']


def test_gender_from_national_id():
    v = mi.identity_verdict('29001011234561', listed_nids=['28501011234562'])   # different IDs anyway
    assert v['verdict'] == 'id_conflict'
    v = mi.identity_verdict('29001011234561', listed_gender='female')            # 13th digit 6 -> female? (6 even)
    assert v['verdict'] in ('gender_conflict', 'unknown', 'corroborated')
