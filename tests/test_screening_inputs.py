"""Manual screening input validation and the footer comment (no DB needed)."""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from screening.input_validation import validate_screen_inputs  # noqa: E402

TODAY = date(2026, 10, 24)


def _errors(**kw):
    args = dict(entity_type='INDIVIDUAL', threshold='55', dob='', national_id='', country='')
    args.update(kw)
    return validate_screen_inputs(today=TODAY, **args)[0]


def test_valid_input_passes_and_is_cleaned():
    errors, cleaned = validate_screen_inputs('entity', '70', '1990-05-05', '2900 5050 101234', 'Egypt',
                                             today=TODAY)
    assert errors == []
    assert cleaned == {'entity_type': 'ENTITY', 'threshold': 70,
                       'dob': date(1990, 5, 5), 'national_id': '29005050101234'}


def test_entity_type_must_be_allowed():
    assert _errors(entity_type='ROBOT')


def test_threshold_range_and_type():
    assert _errors(threshold='39')
    assert _errors(threshold='91')
    assert _errors(threshold='abc')
    assert not _errors(threshold='40')
    assert not _errors(threshold='')          # missing -> default


def test_dob_not_in_future_and_valid():
    assert _errors(dob='2026-10-25')
    assert _errors(dob='1990-13-01')
    assert not _errors(dob='2026-10-24')


def test_national_id_digits_and_egyptian_length():
    assert _errors(national_id='12AB')
    assert _errors(national_id='123456')                  # Egyptian (no country) -> 14 digits
    assert _errors(national_id='123456', country='مصر')
    assert not _errors(national_id='123456', country='France')
    assert not _errors(national_id='٢٩٠٠٥٠٥٠١٠١٢٣٤')    # Arabic-Indic digits accepted


def test_footer_has_no_html_comment():
    # An HTML comment here leaked into public pages as visible text.
    with open(os.path.join(ROOT, 'templates', 'partials', 'footer.html'), encoding='utf-8') as fh:
        assert '<!--' not in fh.read()
