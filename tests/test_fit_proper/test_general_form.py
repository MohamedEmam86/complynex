"""The general board fit & proper questionnaire: any sector, no payment-institution wording."""
import json

from governance.fp import forms as F
from governance.fp import service as S


def test_general_form_is_default_and_sector_neutral():
    d = F.get_form('general_board_fp')
    assert d and d.get('default') and F.default_form()['code'] == 'general_board_fp'
    assert F.all_forms()[0]['code'] == 'general_board_fp'
    text = json.dumps(d, ensure_ascii=False)
    for word in ('PSP', 'PSO', 'payment institution', 'Payment Institution', 'مؤسسة الدفع', 'docx'):
        assert word not in text, word
    assert not F.docx_path(d)


def test_general_form_keeps_the_cbe_question_ids():
    gen = {it['id'] for _s, it in S.iter_items(F.get_form('general_board_fp'))}
    cbe = {it['id'] for _s, it in S.iter_items(F.get_form('cbe_psp_fp_2025'))}
    assert gen == cbe  # same answers structure, so assessment and caps work unchanged


def test_payment_form_says_it_is_for_payment_institutions():
    d = F.get_form('cbe_psp_fp_2025')
    assert d.get('sector') == 'payments' and 'Payment institutions only' in d['title_en']
