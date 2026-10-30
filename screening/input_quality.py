"""P3-11 — quality of the name entered for screening.

Checks the subject BEFORE it is screened and returns warnings for the analyst:
one word only, too short / too long, digits or symbols, Arabic and Latin
letters mixed, no nationality / country, and (for a person) no date of birth
and no ID. The warnings never block a screening; they are shown on the form,
returned by the API, saved with the result (screening_results.match_details
-> input_warnings) and printed in the report, so the evidence shows what the
decision was based on.

Pure Python (no Flask / DB), so every path - form, API, bulk, customer
screening - uses the same rules.
"""
import re
import unicodedata

LEVEL_WARNING = 'warning'
LEVEL_INFO = 'info'

MIN_LETTERS = 3
MAX_CHARS = 150

_PERSON_TYPES = {'', 'INDIVIDUAL', 'PERSON', 'NATURAL_PERSON', 'NATURAL PERSON'}
_PUNCT_PERSON = set(".-'’`ʼـ")           # dots, hyphen, apostrophes, tatweel
_PUNCT_ENTITY = _PUNCT_PERSON | set('&,()/+"“”:#;')
_DIGITS = re.compile(r'[0-9٠-٩۰-۹]')
_AR = re.compile(r'[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]')
_LAT = re.compile(r'[A-Za-zÀ-ɏḀ-ỿ]')

MESSAGES = {
    'single_word': (
        LEVEL_WARNING,
        'Only one name was entered. A single word matches many unrelated people and can miss '
        'the listed person - enter the full name (first, father, grandfather, family).',
        'تم إدخال اسم من كلمة واحدة. الفحص بكلمة واحدة يطابق أشخاصاً كثيرين لا علاقة لهم وقد لا يصل '
        'إلى الشخص المدرج — أدخل الاسم كاملاً (الاسم، الأب، الجد، العائلة).'),
    'two_words': (
        LEVEL_INFO,
        'Only two name parts were entered. Results will be broad and a hit cannot be judged on '
        'the name alone - add the full name if you have it.',
        'الاسم مكوّن من جزأين فقط؛ ستكون النتائج واسعة ولا يمكن الحكم على التطابق بالاسم وحده — '
        'أضف الاسم الكامل إن توفر.'),
    'too_short': (
        LEVEL_WARNING,
        'The name is too short to be screened reliably.',
        'الاسم قصير جداً ولا يصلح للفحص بشكل موثوق.'),
    'too_long': (
        LEVEL_WARNING,
        'The name is unusually long - check that only one name was entered.',
        'الاسم طويل بشكل غير معتاد — تأكد من إدخال اسم واحد فقط.'),
    'has_digits': (
        LEVEL_WARNING,
        'The name contains digits - check that an ID number or a typing error was not entered '
        'in the name field.',
        'الاسم يحتوي على أرقام — تأكد من عدم إدخال رقم هوية أو خطأ كتابي في خانة الاسم.'),
    'has_symbols': (
        LEVEL_WARNING,
        'The name contains symbols ({detail}) - remove them or check the input.',
        'الاسم يحتوي على رموز ({detail}) — احذفها أو راجع الإدخال.'),
    'mixed_scripts': (
        LEVEL_WARNING,
        'The name mixes Arabic and Latin letters - enter it in one script (screen the other '
        'spelling separately if needed).',
        'الاسم يخلط حروفاً عربية ولاتينية — أدخله بلغة واحدة (وافحص الكتابة الأخرى منفصلة عند الحاجة).'),
    'no_country': (
        LEVEL_INFO,
        'No nationality / country was given - a hit without an ID will be judged on the name alone.',
        'لم تُدخل الجنسية / الدولة — أي تطابق بدون رقم هوية سيُحكم عليه بالاسم وحده.'),
    'no_identifier': (
        LEVEL_INFO,
        'No date of birth and no ID - no hit can be confirmed; matches stay potential until the '
        'identity is checked.',
        'لا يوجد تاريخ ميلاد ولا رقم هوية — لا يمكن تأكيد أي تطابق، وتبقى النتائج محتملة حتى يتم '
        'التحقق من الهوية.'),
}


def is_person(entity_type):
    return str(entity_type or '').strip().upper() in _PERSON_TYPES


def _blank(v):
    return v is None or str(v).strip().lower() in ('', 'none', 'nan', 'null', 'n/a', '-')


def _warn(code, detail=''):
    level, en, ar = MESSAGES[code]
    return {'code': code, 'level': level,
            'en': en.format(detail=detail), 'ar': ar.format(detail=detail)}


def assess(name, entity_type='INDIVIDUAL', country=None, dob=None, national_id=None, passport=None):
    """List of warnings ({code, level, en, ar}) for the subject to be screened.
    Never raises; an empty list means nothing to flag."""
    try:
        return _assess(name, entity_type, country, dob, national_id, passport)
    except Exception:                                   # a check must never break a screening
        return []


def _assess(name, entity_type, country, dob, national_id, passport):
    out = []
    raw = str(name or '').strip()
    if not raw:
        return out
    person = is_person(entity_type)
    letters = [c for c in raw if unicodedata.category(c).startswith('L')]
    allowed = _PUNCT_PERSON if person else _PUNCT_ENTITY

    if len(letters) < MIN_LETTERS:
        out.append(_warn('too_short'))
    if len(raw) > MAX_CHARS:
        out.append(_warn('too_long'))
    if _DIGITS.search(raw):
        out.append(_warn('has_digits'))
    symbols = []
    for c in raw:
        cat = unicodedata.category(c)
        if cat[0] in 'LMNZ' or c in allowed:
            continue
        if c not in symbols:
            symbols.append(c)
    if symbols:
        out.append(_warn('has_symbols', ' '.join(symbols[:6])))
    if _AR.search(raw) and _LAT.search(raw):
        out.append(_warn('mixed_scripts'))

    if person:
        words = [w for w in re.split(r'\s+', raw)
                 if any(unicodedata.category(c).startswith('L') for c in w)]
        if len(words) == 1 and len(letters) >= MIN_LETTERS:
            out.append(_warn('single_word'))
        elif len(words) == 2:
            out.append(_warn('two_words'))

    if _blank(country):
        out.append(_warn('no_country'))
    if person and _blank(dob) and _blank(national_id) and _blank(passport):
        out.append(_warn('no_identifier'))
    return out


def codes(warnings):
    return [w.get('code') for w in (warnings or []) if isinstance(w, dict)]


def has_blocking_quality_issue(warnings):
    """True when a 'warning'-level item is present (shown more prominently).
    Nothing is ever blocked."""
    return any(isinstance(w, dict) and w.get('level') == LEVEL_WARNING for w in (warnings or []))
