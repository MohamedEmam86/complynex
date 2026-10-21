import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from screening import adverse_relevance as ar


def A(t):
    return {'title': t, 'description': ''}


def test_whole_words_not_substrings():
    # حكم must not fire on محكمة / الحكومة; no risk term -> not adverse
    assert ar.classify('الحكومة تعلن خطة جديدة أمام المحكمة الدستورية')['severity'] == 0


def test_arabic_prefixes_and_phrases():
    c = ar.classify('القبض على متهم بغسل الأموال')
    assert 'Financial crime' in c['categories'] and c['severity'] == 3


def test_latin_prefix_terms():
    assert ar.classify('Businessman indicted for laundering funds')['severity'] == 3


def test_unrelated_article_dropped():
    r = ar.assess('Karim Samir Fathy Abdelaziz', [A('هل يعتزل كريم محمود عبدالعزيز؟')])
    # at most a weak mention (first + family name), never an adverse finding
    assert r['risk_level'] == 'CLEAR' and r['hits'] == []


def test_named_and_adverse():
    r = ar.assess('أحمد عز', [A('الحكم في دعوى حبس أحمد عز'), A('أحمد عز يحضر حفلا')])
    assert r['risk_level'] == 'MEDIUM' and len(r['hits']) == 1 and len(r['mentions']) == 1
    assert r['hits'][0]['name_match'] == 'exact'


def test_terror_high():
    r = ar.assess('Nicolas Maduro', [A('Nicolas Maduro charged with narco-terrorism')])
    assert r['risk_level'] == 'HIGH'


def test_two_part_name_needs_both():
    r = ar.assess('أحمد عز', [A('القبض على أحمد علي بتهمة النصب')])
    assert r['hits'] == []


def test_fighting_crime_is_not_adverse():
    assert ar.classify('المنتدى العربي لمكافحة الفساد')['severity'] == 0
    assert ar.classify('conference on combating money laundering')['severity'] == 0
