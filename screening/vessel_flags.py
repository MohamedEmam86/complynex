# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Flag states (vessel screening).

Lists write a ship's flag in many ways: 'Panama', 'pa' (OpenSanctions), 'Korea, North', 'North Korea',
'St Kitts & Nevis', 'بنما' ... iso2(text) maps any of them to one ISO 3166 alpha-2 code, name(code) gives
the display name in English or Arabic. Unknown text maps to nothing (never guessed) and is shown as written.
"""
import re

# iso2: (English, Arabic)
COUNTRIES = {
    'af': ('Afghanistan', 'أفغانستان'), 'al': ('Albania', 'ألبانيا'), 'dz': ('Algeria', 'الجزائر'),
    'as': ('American Samoa', 'ساموا الأمريكية'), 'ad': ('Andorra', 'أندورا'), 'ao': ('Angola', 'أنغولا'),
    'ai': ('Anguilla', 'أنغويلا'), 'ag': ('Antigua and Barbuda', 'أنتيغوا وباربودا'),
    'ar': ('Argentina', 'الأرجنتين'), 'am': ('Armenia', 'أرمينيا'), 'aw': ('Aruba', 'أروبا'),
    'au': ('Australia', 'أستراليا'), 'at': ('Austria', 'النمسا'), 'az': ('Azerbaijan', 'أذربيجان'),
    'bs': ('Bahamas', 'جزر البهاما'), 'bh': ('Bahrain', 'البحرين'), 'bd': ('Bangladesh', 'بنغلاديش'),
    'bb': ('Barbados', 'باربادوس'), 'by': ('Belarus', 'بيلاروسيا'), 'be': ('Belgium', 'بلجيكا'),
    'bz': ('Belize', 'بليز'), 'bj': ('Benin', 'بنين'), 'bm': ('Bermuda', 'برمودا'), 'bt': ('Bhutan', 'بوتان'),
    'bo': ('Bolivia', 'بوليفيا'), 'ba': ('Bosnia and Herzegovina', 'البوسنة والهرسك'),
    'bw': ('Botswana', 'بوتسوانا'), 'br': ('Brazil', 'البرازيل'),
    'vg': ('British Virgin Islands', 'جزر العذراء البريطانية'), 'bn': ('Brunei', 'بروناي'),
    'bg': ('Bulgaria', 'بلغاريا'), 'bf': ('Burkina Faso', 'بوركينا فاسو'), 'bi': ('Burundi', 'بوروندي'),
    'cv': ('Cabo Verde', 'الرأس الأخضر'), 'kh': ('Cambodia', 'كمبوديا'), 'cm': ('Cameroon', 'الكاميرون'),
    'ca': ('Canada', 'كندا'), 'ky': ('Cayman Islands', 'جزر كايمان'),
    'cf': ('Central African Republic', 'جمهورية أفريقيا الوسطى'), 'td': ('Chad', 'تشاد'),
    'cl': ('Chile', 'تشيلي'), 'cn': ('China', 'الصين'), 'co': ('Colombia', 'كولومبيا'),
    'km': ('Comoros', 'جزر القمر'), 'cg': ('Congo', 'الكونغو'),
    'cd': ('Congo (Democratic Republic)', 'الكونغو الديمقراطية'), 'ck': ('Cook Islands', 'جزر كوك'),
    'cr': ('Costa Rica', 'كوستاريكا'), 'ci': ("Cote d'Ivoire", 'ساحل العاج'), 'hr': ('Croatia', 'كرواتيا'),
    'cu': ('Cuba', 'كوبا'), 'cw': ('Curacao', 'كوراساو'), 'cy': ('Cyprus', 'قبرص'),
    'cz': ('Czechia', 'التشيك'), 'dk': ('Denmark', 'الدنمارك'), 'dj': ('Djibouti', 'جيبوتي'),
    'dm': ('Dominica', 'دومينيكا'), 'do': ('Dominican Republic', 'جمهورية الدومينيكان'),
    'ec': ('Ecuador', 'الإكوادور'), 'eg': ('Egypt', 'مصر'), 'sv': ('El Salvador', 'السلفادور'),
    'gq': ('Equatorial Guinea', 'غينيا الاستوائية'), 'er': ('Eritrea', 'إريتريا'), 'ee': ('Estonia', 'إستونيا'),
    'sz': ('Eswatini', 'إسواتيني'), 'et': ('Ethiopia', 'إثيوبيا'), 'fo': ('Faroe Islands', 'جزر فارو'),
    'fj': ('Fiji', 'فيجي'), 'fi': ('Finland', 'فنلندا'), 'fr': ('France', 'فرنسا'), 'ga': ('Gabon', 'الغابون'),
    'gm': ('Gambia', 'غامبيا'), 'ge': ('Georgia', 'جورجيا'), 'de': ('Germany', 'ألمانيا'), 'gh': ('Ghana', 'غانا'),
    'gi': ('Gibraltar', 'جبل طارق'), 'gr': ('Greece', 'اليونان'), 'gd': ('Grenada', 'غرينادا'),
    'gt': ('Guatemala', 'غواتيمالا'), 'gn': ('Guinea', 'غينيا'), 'gw': ('Guinea-Bissau', 'غينيا بيساو'),
    'gy': ('Guyana', 'غيانا'), 'ht': ('Haiti', 'هايتي'), 'hn': ('Honduras', 'هندوراس'),
    'hk': ('Hong Kong', 'هونغ كونغ'), 'hu': ('Hungary', 'المجر'), 'is': ('Iceland', 'آيسلندا'),
    'in': ('India', 'الهند'), 'id': ('Indonesia', 'إندونيسيا'), 'ir': ('Iran', 'إيران'), 'iq': ('Iraq', 'العراق'),
    'ie': ('Ireland', 'أيرلندا'), 'im': ('Isle of Man', 'جزيرة مان'), 'il': ('Israel', 'إسرائيل'),
    'it': ('Italy', 'إيطاليا'), 'jm': ('Jamaica', 'جامايكا'), 'jp': ('Japan', 'اليابان'), 'jo': ('Jordan', 'الأردن'),
    'kz': ('Kazakhstan', 'كازاخستان'), 'ke': ('Kenya', 'كينيا'), 'ki': ('Kiribati', 'كيريباتي'),
    'kp': ('North Korea', 'كوريا الشمالية'), 'kr': ('South Korea', 'كوريا الجنوبية'), 'kw': ('Kuwait', 'الكويت'),
    'kg': ('Kyrgyzstan', 'قيرغيزستان'), 'la': ('Laos', 'لاوس'), 'lv': ('Latvia', 'لاتفيا'),
    'lb': ('Lebanon', 'لبنان'), 'ls': ('Lesotho', 'ليسوتو'), 'lr': ('Liberia', 'ليبيريا'), 'ly': ('Libya', 'ليبيا'),
    'li': ('Liechtenstein', 'ليختنشتاين'), 'lt': ('Lithuania', 'ليتوانيا'), 'lu': ('Luxembourg', 'لوكسمبورغ'),
    'mo': ('Macao', 'ماكاو'), 'mg': ('Madagascar', 'مدغشقر'), 'mw': ('Malawi', 'مالاوي'),
    'my': ('Malaysia', 'ماليزيا'), 'mv': ('Maldives', 'جزر المالديف'), 'ml': ('Mali', 'مالي'),
    'mt': ('Malta', 'مالطا'), 'mh': ('Marshall Islands', 'جزر مارشال'), 'mr': ('Mauritania', 'موريتانيا'),
    'mu': ('Mauritius', 'موريشيوس'), 'mx': ('Mexico', 'المكسيك'), 'fm': ('Micronesia', 'ميكرونيزيا'),
    'md': ('Moldova', 'مولدوفا'), 'mc': ('Monaco', 'موناكو'), 'mn': ('Mongolia', 'منغوليا'),
    'me': ('Montenegro', 'الجبل الأسود'), 'ma': ('Morocco', 'المغرب'), 'mz': ('Mozambique', 'موزمبيق'),
    'mm': ('Myanmar', 'ميانمار'), 'na': ('Namibia', 'ناميبيا'), 'nr': ('Nauru', 'ناورو'), 'np': ('Nepal', 'نيبال'),
    'nl': ('Netherlands', 'هولندا'), 'nz': ('New Zealand', 'نيوزيلندا'), 'ni': ('Nicaragua', 'نيكاراغوا'),
    'ne': ('Niger', 'النيجر'), 'ng': ('Nigeria', 'نيجيريا'), 'nu': ('Niue', 'نيوي'),
    'mk': ('North Macedonia', 'مقدونيا الشمالية'), 'no': ('Norway', 'النرويج'), 'om': ('Oman', 'عُمان'),
    'pk': ('Pakistan', 'باكستان'), 'pw': ('Palau', 'بالاو'), 'ps': ('Palestine', 'فلسطين'),
    'pa': ('Panama', 'بنما'), 'pg': ('Papua New Guinea', 'بابوا غينيا الجديدة'), 'py': ('Paraguay', 'باراغواي'),
    'pe': ('Peru', 'بيرو'), 'ph': ('Philippines', 'الفلبين'), 'pl': ('Poland', 'بولندا'),
    'pt': ('Portugal', 'البرتغال'), 'qa': ('Qatar', 'قطر'), 'ro': ('Romania', 'رومانيا'), 'ru': ('Russia', 'روسيا'),
    'rw': ('Rwanda', 'رواندا'), 'kn': ('Saint Kitts and Nevis', 'سانت كيتس ونيفيس'),
    'lc': ('Saint Lucia', 'سانت لوسيا'), 'vc': ('Saint Vincent and the Grenadines', 'سانت فنسنت والغرينادين'),
    'ws': ('Samoa', 'ساموا'), 'sm': ('San Marino', 'سان مارينو'),
    'st': ('Sao Tome and Principe', 'ساو تومي وبرينسيب'), 'sa': ('Saudi Arabia', 'السعودية'),
    'sn': ('Senegal', 'السنغال'), 'rs': ('Serbia', 'صربيا'), 'sc': ('Seychelles', 'سيشل'),
    'sl': ('Sierra Leone', 'سيراليون'), 'sg': ('Singapore', 'سنغافورة'), 'sx': ('Sint Maarten', 'سينت مارتن'),
    'sk': ('Slovakia', 'سلوفاكيا'), 'si': ('Slovenia', 'سلوفينيا'), 'sb': ('Solomon Islands', 'جزر سليمان'),
    'so': ('Somalia', 'الصومال'), 'za': ('South Africa', 'جنوب أفريقيا'), 'ss': ('South Sudan', 'جنوب السودان'),
    'es': ('Spain', 'إسبانيا'), 'lk': ('Sri Lanka', 'سريلانكا'), 'sd': ('Sudan', 'السودان'),
    'sr': ('Suriname', 'سورينام'), 'se': ('Sweden', 'السويد'), 'ch': ('Switzerland', 'سويسرا'),
    'sy': ('Syria', 'سوريا'), 'tw': ('Taiwan', 'تايوان'), 'tj': ('Tajikistan', 'طاجيكستان'),
    'tz': ('Tanzania', 'تنزانيا'), 'th': ('Thailand', 'تايلاند'), 'tl': ('Timor-Leste', 'تيمور الشرقية'),
    'tg': ('Togo', 'توغو'), 'to': ('Tonga', 'تونغا'), 'tt': ('Trinidad and Tobago', 'ترينيداد وتوباغو'),
    'tn': ('Tunisia', 'تونس'), 'tr': ('Turkey', 'تركيا'), 'tm': ('Turkmenistan', 'تركمانستان'),
    'tc': ('Turks and Caicos Islands', 'جزر توركس وكايكوس'), 'tv': ('Tuvalu', 'توفالو'),
    'ug': ('Uganda', 'أوغندا'), 'ua': ('Ukraine', 'أوكرانيا'), 'ae': ('United Arab Emirates', 'الإمارات'),
    'gb': ('United Kingdom', 'المملكة المتحدة'), 'us': ('United States', 'الولايات المتحدة'),
    'uy': ('Uruguay', 'أوروغواي'), 'uz': ('Uzbekistan', 'أوزبكستان'), 'vu': ('Vanuatu', 'فانواتو'),
    've': ('Venezuela', 'فنزويلا'), 'vn': ('Vietnam', 'فيتنام'), 'ye': ('Yemen', 'اليمن'),
    'zm': ('Zambia', 'زامبيا'), 'zw': ('Zimbabwe', 'زيمبابوي'),
}

# other spellings used by the lists
_ALIASES = {
    'korea north': 'kp', 'north korea': 'kp', 'korea dprk': 'kp', 'dprk': 'kp',
    'democratic people s republic of korea': 'kp', 'korea democratic people s republic of': 'kp',
    'korea south': 'kr', 'republic of korea': 'kr', 'korea republic of': 'kr', 'burma': 'mm',
    'st kitts and nevis': 'kn', 'saint kitts nevis': 'kn', 'st kitts nevis': 'kn', 'st kitts': 'kn',
    'st vincent and the grenadines': 'vc', 'st vincent and grenadines': 'vc', 'st vincent': 'vc',
    'saint vincent': 'vc', 'st lucia': 'lc', 'sao tome': 'st', 'tanzania united republic of': 'tz',
    'zanzibar': 'tz', 'tanzania zanzibar': 'tz', 'iran islamic republic of': 'ir', 'russian federation': 'ru',
    'syrian arab republic': 'sy', 'viet nam': 'vn', 'cape verde': 'cv', 'swaziland': 'sz',
    'kingdom of eswatini': 'sz', 'the bahamas': 'bs', 'bahamas the': 'bs', 'the gambia': 'gm', 'gambia the': 'gm',
    'uae': 'ae', 'uk': 'gb', 'great britain': 'gb', 'usa': 'us', 'united states of america': 'us',
    'turkiye': 'tr', 'hong kong sar': 'hk', 'hong kong china': 'hk', 'macau': 'mo', 'moldova republic of': 'md',
    'republic of moldova': 'md', 'bolivia plurinational state of': 'bo', 'venezuela bolivarian republic of': 've',
    'congo republic of the': 'cg', 'congo democratic republic of the': 'cd', 'drc': 'cd', 'ivory coast': 'ci',
    'cote divoire': 'ci', 'czech republic': 'cz', 'lao pdr': 'la', 'micronesia federated states of': 'fm',
    'the netherlands': 'nl', 'holland': 'nl', 'macedonia': 'mk', 'virgin islands british': 'vg', 'bvi': 'vg',
    'union of the comoros': 'km', 'comoros union of the': 'km', 'palestinian territories': 'ps',
    'east timor': 'tl', 'brunei darussalam': 'bn', 'guinea bissau': 'gw', 'kyrgyz republic': 'kg',
    'slovak republic': 'sk', 'the philippines': 'ph', 'antigua barbuda': 'ag', 'trinidad tobago': 'tt',
    'bosnia': 'ba', 'cook islands the': 'ck', 'marshall islands the': 'mh',
    'كوريا الديمقراطيه': 'kp', 'كوريا الشماليه': 'kp', 'الامارات العربيه المتحده': 'ae', 'الامارات': 'ae',
    'ايران': 'ir', 'روسيا الاتحاديه': 'ru', 'جزر القمر المتحده': 'km',
}

_UNKNOWN = {'none identified', 'not identified', 'unknown', 'unknown flag', 'not known', 'n a', 'na', 'none', 'unk', 'غير معروف'}


def _key(s):
    s = str(s or '').strip().lower()
    if re.search('[؀-ۿ]', s):
        s = s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي')
        return re.sub(r'\s+', ' ', s).strip()
    import unicodedata
    s = ''.join(ch for ch in unicodedata.normalize('NFKD', s) if not unicodedata.combining(ch))
    s = s.replace('&', ' and ')
    s = re.sub(r"[^a-z0-9]+", ' ', s)
    s = re.sub(r'\bsaint\b', 'st', s)
    return re.sub(r'\s+', ' ', s).strip()


_INDEX = {}
for _c, (_en, _ar) in COUNTRIES.items():
    _INDEX[_c] = _c
    _INDEX[_key(_en)] = _c
    _INDEX[_key(_ar)] = _c
for _a, _c in _ALIASES.items():
    _INDEX[_key(_a)] = _c


def iso2(text):
    """ISO alpha-2 code (lower case) of a flag written in any of the lists' ways, else None."""
    k = _key(text)
    if not k or k in _UNKNOWN:
        return None
    k = re.sub(r'^(flag of|flag|the)\s+', '', k)
    if k in _INDEX:
        return _INDEX[k]
    k2 = re.sub(r'\s*\(.*?\)\s*', ' ', str(text or '')).strip()      # 'Tanzania (Zanzibar)'
    if k2 and _key(k2) in _INDEX:
        return _INDEX[_key(k2)]
    try:                                                # demonyms and other forms of the shared table
        from screening.country_codes import to_iso2
        found = to_iso2(str(text))
        if len(found) == 1:
            return next(iter(found))
    except Exception:
        pass
    return None


def name(code_or_text, lang='en'):
    """Display name of a flag (English or Arabic); text that is not a known country stays as written."""
    if not code_or_text:
        return ''
    c = iso2(code_or_text)
    if c and c in COUNTRIES:
        return COUNTRIES[c][1 if lang == 'ar' else 0]
    return str(code_or_text).strip()


def canonical(text):
    """The English name a flag is stored under (vessel_profile.current_flag / flag_history), or the text
    as written when it is not a known country; None for empty / 'unknown'."""
    if not text or not str(text).strip():
        return None
    if _key(text) in _UNKNOWN:
        return None
    m = re.match(r'^(.*?)[\s(]+false(?: flag)?\)?$', str(text).strip(), re.I)
    if m and iso2(m.group(1)):          # 'Botswana False': a registry the ship claims falsely
        return COUNTRIES[iso2(m.group(1))][0] + ' (false flag)'
    c = iso2(text)
    return COUNTRIES[c][0] if c in COUNTRIES else re.sub(r'\s+', ' ', str(text).strip())
