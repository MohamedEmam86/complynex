"""Local / internal lists: a client never sees the sheet, file or dataset a listed record came from (owner
decision, round 4). Only the platform superadmin sees the real category. No database needed."""
import json

from screening import source_mask as SM


class _U:
    def __init__(self, role):
        self.role = role
        self.is_authenticated = True


SHEET_A = 'order sheet 0001 of the unit'          # stand-ins for real sheet names (never real data in tests)
SHEET_B = 'terror unit 10-11-2026 n2'


def _hit(category, source='INTERNAL_BLACKLIST', **kw):
    m = {'source': source, 'category': category, 'list_type': category, 'full_name': 'Test Person',
         'match_score': 92, 'properties': json.dumps({'sheet': category, 'case_number': '12/2026'}),
         'details': {'sheet': category, 'file_name': 'upload_2026.xlsx'}, 'dataset': 'local_upload_7'}
    m.update(kw)
    return m


def test_generic_categories():
    assert SM.public_code('امر النائب العام') == 'FREEZE_ORDER'
    assert SM.public_code('الإرهابيين الوحدة 10-11-2026ن2') == 'TERROR'
    assert SM.public_code('قائمة الكيانات الإرهابية') == 'TERROR_ENTITIES'
    assert SM.public_code('لجنة عقوبات مجلس الأمن 1267') == 'UN_COMMITTEE'
    assert SM.public_code('anything else') == 'INTERNAL'
    assert SM.public_label('FREEZE_ORDER', 'en') == 'Egyptian local list – asset-freeze order'
    assert SM.public_label('TERROR', 'ar') == 'قائمة الإرهابيين المصرية'


def test_client_sees_no_sheet_file_or_dataset():
    admin = _U('admin')
    for raw in (SHEET_A, SHEET_B, 'امر النائب العام', 'الإرهابيين الوحدة 10-11-2026ن2'):
        out = SM.mask_match(_hit(raw), user=admin, lang='en')
        text = json.dumps(out, ensure_ascii=False)
        assert raw not in text and 'upload_2026.xlsx' not in text and 'local_upload_7' not in text
        assert out['category'] in {en for en, _ar in SM.LABELS.values()}
        assert out['list_type'].upper() in ('SANCTIONS', 'PEP')
        assert json.loads(out['properties'])['case_number'] == '12/2026'     # the facts stay


def test_superadmin_keeps_the_real_source():
    sup = _U('superadmin')
    hit = _hit(SHEET_A)
    assert SM.mask_match(hit, user=sup) is hit
    assert SM.mask_matches([hit], user=sup)[0]['category'] == SHEET_A
    # an API answer is masked even for a superadmin's key
    assert SM.mask_matches([hit], user=sup, force=True)[0]['category'] != SHEET_A


def test_public_lists_untouched_and_nested_hits_masked():
    admin = _U('admin')
    ofac = {'source': 'ofac', 'dataset': 'us_ofac_sdn', 'category': 'SDGT', 'list_type': 'SANCTIONS'}
    assert SM.mask_match(ofac, user=admin) is ofac
    hit = _hit(SHEET_B, cluster={'members': [{'source': 'internal_blacklist', 'list_type': SHEET_A, 'label': 'x'}]},
               grouped_hits=[{'source': 'INTERNAL_BLACKLIST', 'dataset': SHEET_A, 'list_type': SHEET_A}])
    out = SM.mask_matches([hit, ofac], user=admin)
    text = json.dumps(out, ensure_ascii=False)
    assert SHEET_A not in text and SHEET_B not in text
    assert out[1]['dataset'] == 'us_ofac_sdn'


def test_result_page_view_and_api_hit():
    from screening import result_view as rv
    from api.v1_common import hit_view
    m = SM.mask_match(_hit('امر النائب العام'), user=_U('compliance_officer'), lang='en')
    view = rv.match_view(m, 'sanctions', {})
    text = json.dumps(view, ensure_ascii=False, default=str)
    assert 'النائب العام' not in text and 'upload_2026' not in text
    assert view['category'] == 'Egyptian local list – asset-freeze order'
    h = hit_view(SM.mask_matches([_hit(SHEET_B)], force=True)[0])
    assert h['list_category'] == 'Egyptian terrorist list' and SHEET_B not in json.dumps(h)
