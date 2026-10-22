"""Fit & proper form definitions, scoring rules and the regulator Word export."""
import io
import zipfile

from governance.fp import forms as F
from governance.fp import service as S
from governance.fp.docx_fill import fill, control_values
from utils.rating_guides import GUIDES


def _cbe():
    d = F.get_form('cbe_psp_fp_2025')
    assert d, 'CBE form definition missing'
    return d


def test_all_forms_load():
    codes = {f['code'] for f in F.all_forms()}
    assert {'cbe_psp_fp_2025', 'internal_fp_annual', 'internal_fp_committee'} <= codes
    for f in F.all_forms():
        ids = [it['id'] for _s, it in S.iter_items(f)]
        assert len(ids) == len(set(ids)), f['code']


def test_cbe_mapping_covers_every_field_once():
    d = _cbe()
    used = []
    for _s, it in S.iter_items(d):
        if isinstance(it.get('docx'), dict):
            used += it['docx']['yes'] + it['docx']['no']
        elif it['type'] == 'grid':
            for row in it['docx']:
                for ix in row.values():
                    used += ix
        elif it.get('docx'):
            used += it['docx']
        used += it.get('details_docx', [])
        for o in it.get('options', []):
            used += o.get('docx', [])
    assert sorted(used) == list(range(1, d['docx_controls']))   # control 0 is the guidance block


def test_cbe_has_all_14_sections_and_regulator_wording():
    d = _cbe()
    assert [s['no'] for s in d['sections']] == [str(i) for i in range(1, 15)]
    s6 = next(s for s in d['sections'] if s['id'] == 's6')
    assert len([i for i in s6['items'] if i['type'] == 'yesno']) == 6
    assert 'convicted' in s6['items'][0]['en'] and 'حكم' in s6['items'][0]['ar']


def test_validation_and_flags():
    d = _cbe()
    issues = S.validate(d, {})
    assert issues
    a = {'s6_q2': 'yes'}
    assert any(f['no'] == '6.2' for f in S.adverse_flags(d, a))
    assert S.suggest_caps(d, a)['honesty'] == 3
    assert any(i[0] == '6.2' and i[3] == 'yes without details' for i in S.validate(d, a))
    a['s6_details'] = [{'qno': '6.2', 'details': 'closed'}]
    assert not any(i[0] == '6.2' for i in S.validate(d, a))


def test_score_rules():
    full = lambda *v: {k: {'score': str(x)} for (k, *_), x in zip(S.CRITERIA, v)}  # noqa: E731
    assert S.score_and_result(full(4, 4, 4, 4, 4)) == (4.0, 'fit')
    assert S.score_and_result(full(4, 2, 4, 4, 4))[1] == 'fit_with_conditions'
    assert S.score_and_result(full(5, 5, 1, 5, 5))[1] == 'not_fit'
    assert S.score_and_result({'honesty': {'score': '4'}}) == (None, None)


def test_docx_export_fills_original_form():
    d = _cbe()
    a = {'s2_name': 'Test Candidate (demo)', 's1_q3': 'psp', 's6_q1': 'no',
         's4_history': [{'employer': 'Example Co (demo)', 'title': 'Officer', 'from': '2010-01-01', 'to': '2012-01-01', 'reason': 'end of contract'}]}
    vals, sigs = control_values(d, a)
    assert vals[7] == ('text', 'Test Candidate (demo)') and vals[3] == ('check', True) and vals[265] == ('check', True)
    assert 533 in sigs and 538 in sigs
    data = fill(F.docx_path(d), d, a)
    xml = zipfile.ZipFile(io.BytesIO(data)).read('word/document.xml').decode()
    assert 'Test Candidate (demo)' in xml and 'Example Co (demo)' in xml and '01/01/2010' in xml and 'N/A' in xml


def test_rating_guides_are_bilingual():
    for key, g in GUIDES.items():
        assert g['title_ar'] and g['how_ar'], key
        assert all(lv['label_ar'] and lv['desc_ar'] for lv in g['levels']), key
    for key, gkey, *_ in S.CRITERIA:
        assert gkey in GUIDES
