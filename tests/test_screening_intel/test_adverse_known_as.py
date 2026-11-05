from screening import adverse_relevance as ar


def test_known_as_forms():
    f = ar.known_as_forms('محمد خيرت سعد عبد اللطيف الشاطر')
    assert 'خيرت الشاطر' in f and 'محمد خيرت الشاطر' in f
    assert ar._units('محمد خيرت سعد عبد اللطيف الشاطر') == ['محمد', 'خيرت', 'سعد', 'عبد اللطيف', 'الشاطر']
    assert ar.known_as_forms('محمد احمد') == []


def test_short_form_in_article_is_found():
    name = 'محمد خيرت سعد عبد اللطيف الشاطر'
    assert ar.name_presence(name, 'الحكم على خيرت الشاطر في قضية الإخوان') in ('partial', 'strong')
    assert ar.name_presence(name, 'تأجيل محاكمة محمد خيرت الشاطر') == 'strong'
    assert ar.name_presence(name, 'خبر عن شخص آخر تماما') is None
