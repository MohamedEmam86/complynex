"""Focused, DB-free checks for the governance / COI / training / GHE fixes."""
import json
import os
import sys
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from utils.arabic_pdf import shape, has_arabic, add_unicode_font  # noqa: E402


def test_shape_leaves_latin_text_alone():
    assert shape('AML 101') == 'AML 101'
    assert shape(None) == ''


def test_shape_uses_contextual_forms_and_visual_order():
    out = shape('محمد')
    # meem initial, haa medial, meem medial, dal final - reversed for LTR drawing
    assert out == 'ﺪﻤﺤﻣ'
    assert shape('لا') == 'ﻻ'  # lam-alef ligature
    assert not any('؀' <= c <= 'ۿ' for c in shape('الامتثال'))
    assert has_arabic('x م')


def test_certificate_pdf_with_arabic_text_renders():
    fpdf = pytest.importorskip('fpdf')
    pdf = fpdf.FPDF(orientation='L', unit='mm', format='A4')
    if not add_unicode_font(pdf):
        pytest.skip('DejaVu font not installed')
    pdf.add_page()
    pdf.set_font('CxUni', 'B', 20)
    pdf.cell(0, 10, shape('شهادة إتمام: مكافحة غسل الأموال'))
    assert bytes(pdf.output()).startswith(b'%PDF')


def test_general_form_has_microfinance_key_functions_and_activity_prefill():
    from governance.fp import service as S
    d = json.load(open(os.path.join(ROOT, 'governance', 'fp', 'forms', 'general_board_fp.json'), encoding='utf-8'))
    items = {it['id']: it for s in d['sections'] for it in s['items']}
    opts = {o['v'] for o in items['s3_function']['options']}
    for code in ('head_credit', 'mlro', 'head_collections', 'branch_network_manager'):
        assert code in opts and code in S.KF and S.KF[code][1]
    assert items['s1_q2']['prefill'] == 'institution.trade_name'
    assert items['s1_q3']['prefill'] == 'institution.activity'


@pytest.fixture
def babel_ctx():
    flask = pytest.importorskip('flask')
    flask_babel = pytest.importorskip('flask_babel')
    app = flask.Flask(__name__)
    flask_babel.Babel(app)
    with app.test_request_context():
        yield


def _ghe(**kw):
    d = {'estimated_value_egp': '100', 'event_date': date.today().isoformat(), 'is_government_official': None}
    d.update(kw)
    return d


def test_ghe_validation(babel_ctx):
    from models.ghe import GHEDeclaration as G
    assert G.validation_errors(_ghe()) == []
    assert G.validation_errors(_ghe(estimated_value_egp='-5'))
    assert G.validation_errors(_ghe(event_date=(date.today() + timedelta(days=3)).isoformat()))
    assert G.validation_errors(_ghe(is_government_official='on'))
    assert G.validation_errors(_ghe(is_government_official='on', government_official_details='Ministry',
                                    government_official_position='Director')) == []
