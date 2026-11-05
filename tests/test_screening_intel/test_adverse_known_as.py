from screening import adverse_relevance as ar


def test_known_as_forms():
    f = ar.known_as_forms('محمد خيرت سعد عبد اللطيف الشاطر')
    # second+family (the best form) and first+second+family only
    assert f == ['خيرت الشاطر', 'محمد خيرت الشاطر']
    # the first+family short form is too weak and must NOT be generated
    assert 'محمد الشاطر' not in f
    assert ar._units('محمد خيرت سعد عبد اللطيف الشاطر') == ['محمد', 'خيرت', 'سعد', 'عبد اللطيف', 'الشاطر']
    # fewer than four elements -> no short forms
    assert ar.known_as_forms('محمد احمد') == []
    assert ar.known_as_forms('خيرت سعد الشاطر') == []


def test_units_compounds():
    assert ar._units('Abd El Aziz') == ['Abd El Aziz']
    assert ar._units('Nour El Din') == ['Nour El Din']
    assert ar._units('سعد الدين') == ['سعد الدين']


def test_short_form_in_article_is_a_lead_not_strong():
    name = 'محمد خيرت سعد عبد اللطيف الشاطر'
    # the press short form is found, but only as a lead (partial / known_as), never 'strong'
    assert ar.name_presence(name, 'الحكم على خيرت الشاطر في قضية الإخوان') in ('partial', 'known_as')
    assert ar.name_presence(name, 'تأجيل محاكمة محمد خيرت الشاطر') in ('partial', 'known_as')
    # a different person who shares only the common first name + family name is NOT the subject
    assert ar.name_presence(name, 'محمد الشاطر صاحب محل بقالة في طنطا') is None
    assert ar.name_presence(name, 'خبر عن شخص آخر تماما') is None


def test_short_form_cannot_reach_high_alone():
    name = 'محمد خيرت سعد عبد اللطيف الشاطر'
    # a serious (severity-3) article found only through the short form -> at most MEDIUM
    r = ar.assess(name, [{'title': 'خيرت الشاطر متهم في قضية غسل اموال', 'description': ''}])
    assert r['hits'] and r['hits'][0]['name_match'] in ('partial', 'known_as')
    assert r['risk_level'] == 'MEDIUM'


def test_patronymic_without_family_still_matches():
    # a long patronymic name whose last element is NOT a rare family name:
    # no short forms are generated, but first + a rare middle is still a lead
    name = 'احمد خيرت محمود حسن'
    assert ar.known_as_forms(name) == []
    assert ar.name_presence(name, 'القبض على احمد خيرت في قضية') in ('partial', 'known_as')
