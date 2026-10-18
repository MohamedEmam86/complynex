# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

"""
Egyptian National ID (الرقم القومي) validator/decoder.

Format — 14 digits, positions 0-indexed:
    [0]      century digit:  2 -> born 1900-1999, 3 -> born 2000-2099
    [1:3]    YY  birth year within the century
    [3:5]    MM  birth month
    [5:7]    DD  birth day
    [7:9]    GG  governorate code (2 digits)
    [9:13]   SSSS  4-digit serial for that birth-date + governorate;
                    its last digit's parity encodes gender (odd=male, even=female)
    [13]     Z   final digit, commonly called a "check digit"

ON THE CHECK DIGIT: Egypt's civil registry has never published an official
check-digit algorithm. The most widely-referenced community formula uses
alternating weights [2,1] on digits 0-12, sums the products (digits > 9
reduced by 9), takes the result mod 9, and compares to digit 13. This
matches the majority of real IDs observed in practice, but is NOT an
official standard and MUST NOT be used as a hard rejection gate — a valid
OCR-read ID that fails this check may simply be one where our formula is
wrong, not a fraudulent document. We surface it as an advisory signal only.

`is_valid` rests entirely on the parts that ARE deterministic and publicly
verifiable: century, calendar date, governorate code, and basic plausibility.

This module is pure logic — no ML, no I/O — by design, so it can validate
and cross-check OCR output from Layer 3 without depending on it.
"""
import datetime

GOVERNORATES = {
    '01': {'ar': 'القاهرة', 'en': 'Cairo'},
    '02': {'ar': 'الإسكندرية', 'en': 'Alexandria'},
    '03': {'ar': 'بورسعيد', 'en': 'Port Said'},
    '04': {'ar': 'السويس', 'en': 'Suez'},
    '11': {'ar': 'دمياط', 'en': 'Damietta'},
    '12': {'ar': 'الدقهلية', 'en': 'Dakahlia'},
    '13': {'ar': 'الشرقية', 'en': 'Sharqia'},
    '14': {'ar': 'القليوبية', 'en': 'Qalyubia'},
    '15': {'ar': 'كفر الشيخ', 'en': 'Kafr El Sheikh'},
    '16': {'ar': 'الغربية', 'en': 'Gharbia'},
    '17': {'ar': 'المنوفية', 'en': 'Monufia'},
    '18': {'ar': 'البحيرة', 'en': 'Beheira'},
    '19': {'ar': 'الإسماعيلية', 'en': 'Ismailia'},
    '21': {'ar': 'الجيزة', 'en': 'Giza'},
    '22': {'ar': 'بني سويف', 'en': 'Beni Suef'},
    '23': {'ar': 'الفيوم', 'en': 'Fayoum'},
    '24': {'ar': 'المنيا', 'en': 'Minya'},
    '25': {'ar': 'أسيوط', 'en': 'Assiut'},
    '26': {'ar': 'سوهاج', 'en': 'Sohag'},
    '27': {'ar': 'قنا', 'en': 'Qena'},
    '28': {'ar': 'أسوان', 'en': 'Aswan'},
    '29': {'ar': 'الأقصر', 'en': 'Luxor'},
    '31': {'ar': 'البحر الأحمر', 'en': 'Red Sea'},
    '32': {'ar': 'الوادي الجديد', 'en': 'New Valley'},
    '33': {'ar': 'مطروح', 'en': 'Matrouh'},
    '34': {'ar': 'شمال سيناء', 'en': 'North Sinai'},
    '35': {'ar': 'جنوب سيناء', 'en': 'South Sinai'},
    '88': {'ar': 'مواليد خارج مصر', 'en': 'Born outside Egypt'},
}

MAX_PLAUSIBLE_AGE_YEARS = 120

# Alternating weights for the community-observed check-digit formula.
# Weights are applied to digits 0-12; products > 9 are reduced by 9;
# sum mod 9 should equal digit[13]. Advisory only — not an official spec.
_CHECK_WEIGHTS = [2, 1] * 7  # 14 values, last entry unused (that's digit[13])


def _compute_check_digit(nid_14: str) -> int:
    """Compute the expected check digit using the community-observed formula."""
    total = 0
    for i, w in enumerate(_CHECK_WEIGHTS):
        product = int(nid_14[i]) * w
        total += product - 9 if product > 9 else product
    return total % 9

# Common OCR digit confusions, plus Eastern Arabic-Indic numerals in case an
# OCR engine returns them for a field that is always printed in Western digits.
_CONFUSABLE_MAP = {
    'O': '0', 'o': '0', 'D': '0',
    'I': '1', 'l': '1', 'i': '1', '|': '1',
    'Z': '2',
    'S': '5', 's': '5',
    'B': '8',
    'q': '9', 'g': '9',
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
}


def normalize(raw):
    """Strip separators/whitespace and fix common OCR digit confusions."""
    if raw is None:
        return ''
    cleaned = []
    for ch in str(raw).strip():
        if ch.isspace() or ch in '-_./':
            continue
        cleaned.append(_CONFUSABLE_MAP.get(ch, ch))
    return ''.join(cleaned)


def decode(raw_national_id):
    """
    Decode and validate a (possibly OCR-noisy) Egyptian national ID.

    Returns a dict:
        national_id, is_valid, errors (list[str]),
        dob (datetime.date | None), gender ('male'|'female'|None),
        governorate_code, governorate_name_ar, governorate_name_en,
        check_digit
    """
    errors = []
    national_id = normalize(raw_national_id)

    if len(national_id) != 14 or not national_id.isdigit():
        errors.append(f'Expected 14 digits, got {len(national_id)!r}: {national_id!r}')
        return {
            'national_id': national_id, 'is_valid': False, 'errors': errors,
            'dob': None, 'gender': None,
            'governorate_code': None, 'governorate_name_ar': None, 'governorate_name_en': None,
            'check_digit': None,
        }

    century_digit = national_id[0]
    yy = int(national_id[1:3])
    mm = int(national_id[3:5])
    dd = int(national_id[5:7])
    governorate_code = national_id[7:9]
    serial = national_id[9:13]
    check_digit = national_id[13]

    if century_digit == '2':
        year = 1900 + yy
    elif century_digit == '3':
        year = 2000 + yy
    else:
        errors.append(f"Invalid century digit '{century_digit}' (expected 2 or 3)")
        year = None

    dob = None
    if year is not None:
        try:
            dob = datetime.date(year, mm, dd)
        except ValueError:
            errors.append(f'Invalid calendar date: year={year} month={mm} day={dd}')

    if dob is not None:
        today = datetime.date.today()
        if dob > today:
            errors.append(f'Birth date {dob.isoformat()} is in the future')
        else:
            age_years = (today - dob).days / 365.25
            if age_years > MAX_PLAUSIBLE_AGE_YEARS:
                errors.append(f'Implausible age ({age_years:.0f} years) — likely a misread digit')

    governorate = GOVERNORATES.get(governorate_code)
    if governorate is None:
        errors.append(f"Unknown governorate code '{governorate_code}'")

    gender = None
    if serial:
        gender = 'male' if int(serial[-1]) % 2 == 1 else 'female'

    # Advisory check-digit verification (community formula — not an official spec).
    # A mismatch is a yellow flag, not a hard failure: `is_valid` is unaffected.
    check_digit_advisory = None
    check_digit_match = None
    if len(national_id) == 14 and national_id.isdigit():
        expected = _compute_check_digit(national_id)
        check_digit_advisory = expected
        check_digit_match = (expected == int(check_digit))

    return {
        'national_id': national_id,
        'is_valid': len(errors) == 0,
        'errors': errors,
        'dob': dob,
        'gender': gender,
        'governorate_code': governorate_code,
        'governorate_name_ar': governorate['ar'] if governorate else None,
        'governorate_name_en': governorate['en'] if governorate else None,
        'check_digit': check_digit,
        'check_digit_advisory_expected': check_digit_advisory,
        'check_digit_match': check_digit_match,  # None = not computed; True/False = advisory result
    }


def cross_check(decoded, candidate_dob=None, candidate_gender=None):
    """
    Compare values independently extracted by OCR from elsewhere on the card
    (a printed DOB field, a gender marker) against what's encoded in the
    national number itself. Returns a list of human-readable mismatch
    warnings (empty list = consistent, or nothing to compare).
    """
    warnings = []
    if not decoded.get('is_valid'):
        return warnings
    if candidate_dob is not None and decoded.get('dob') is not None:
        if candidate_dob != decoded['dob']:
            warnings.append(
                f"OCR-read date of birth ({candidate_dob}) does not match the date "
                f"encoded in the national ID ({decoded['dob']})"
            )
    if candidate_gender is not None and decoded.get('gender') is not None:
        if candidate_gender.lower() != decoded['gender']:
            warnings.append(
                f"OCR-read gender ({candidate_gender}) does not match the gender "
                f"encoded in the national ID ({decoded['gender']})"
            )
    return warnings
