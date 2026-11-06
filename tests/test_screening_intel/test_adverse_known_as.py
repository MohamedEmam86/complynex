from screening import adverse_relevance as ar


def test_units_compounds():
    assert ar._units('Abd El Aziz') == ['Abd El Aziz']
    assert ar._units('Nour El Din') == ['Nour El Din']
    assert ar._units('سعد الدين') == ['سعد الدين']
    # 'Abdullah' forms are a name element, NOT glued onto the previous element
    assert ar._units('عبد الله') == ['عبد الله']
    assert ar._units('Abd Allah') == ['Abd Allah']
    assert ar._units('Abdel Allah') == ['Abdel Allah']
    assert ar._units('محمد عبد الله خيرت الشاطر') == ['محمد', 'عبد الله', 'خيرت', 'الشاطر']


def test_known_as_forms_long_name():
    f = ar.known_as_forms('محمد خيرت سعد عبد اللطيف الشاطر')
    assert f == ['خيرت الشاطر', 'محمد خيرت الشاطر']          # second+family, first+second+family
    assert 'محمد الشاطر' not in f                            # first+family dropped for a long name
    assert ar._units('محمد خيرت سعد عبد اللطيف الشاطر') == ['محمد', 'خيرت', 'سعد', 'عبد اللطيف', 'الشاطر']
    assert ar.known_as_forms('محمد احمد') == []              # fewer than 3 elements


def test_known_as_forms_three_element_name():
    # a genuine 3-element name keeps second+family AND first+family (fam weight >= 8)
    f = ar.known_as_forms('خيرت سعد الشاطر')
    assert set(f) == {'سعد الشاطر', 'خيرت الشاطر'}
    # a 3-element name with a common family element gets no short forms
    assert ar.known_as_forms('محمد علي حسن') == []


def test_short_form_in_article_is_a_lead_not_strong():
    name = 'محمد خيرت سعد عبد اللطيف الشاطر'
    # the press short form is found, but only as a weak lead ('partial'), never 'strong'
    assert ar.name_presence(name, 'الحكم على خيرت الشاطر في قضية الإخوان') == 'partial'
    assert ar.name_presence(name, 'تأجيل محاكمة محمد خيرت الشاطر') == 'partial'
    # a different person sharing only the common first name + family name is NOT the subject
    assert ar.name_presence(name, 'محمد الشاطر صاحب محل بقالة في طنطا') is None
    assert ar.name_presence(name, 'خبر عن شخص آخر تماما') is None


def test_three_element_name_partial_coverage():
    name = 'خيرت سعد الشاطر'
    assert ar.name_presence(name, 'القبض على سعد الشاطر') == 'partial'
    assert ar.name_presence(name, 'خبر عن خيرت الشاطر') == 'partial'


def test_short_form_cannot_reach_high_alone():
    name = 'محمد خيرت سعد عبد اللطيف الشاطر'
    # a serious (severity-3) article found only through the short form -> at most MEDIUM
    r = ar.assess(name, [{'title': 'خيرت الشاطر متهم في قضية غسل اموال', 'description': ''}])
    assert r['hits'] and r['hits'][0]['name_match'] == 'partial'
    assert r['risk_level'] == 'MEDIUM'


def test_assess_high_requires_a_firm_match():
    # a basket of only partial hits, even severity 3, is capped at MEDIUM
    name = 'محمد خيرت سعد عبد اللطيف الشاطر'
    arts = [{'title': 'خيرت الشاطر في قضية تمويل الارهاب', 'description': ''},
            {'title': 'محمد خيرت الشاطر وغسل الاموال', 'description': ''}]
    r = ar.assess(name, arts)
    assert all(h['name_match'] == 'partial' for h in r['hits'])
    assert r['risk_level'] == 'MEDIUM'
    # an exact full-name hit with the same severity DOES reach HIGH
    r2 = ar.assess('احمد عز', [{'title': 'احمد عز متهم في قضية غسل اموال', 'description': ''}])
    assert r2['risk_level'] == 'HIGH'


def test_patronymic_without_family_still_matches():
    # a long patronymic name whose last element is NOT a rare family name:
    # no short forms, but first + a rare middle is still a lead
    name = 'احمد خيرت محمود حسن'
    assert ar.known_as_forms(name) == []
    assert ar.name_presence(name, 'القبض على احمد خيرت في قضية') == 'partial'
