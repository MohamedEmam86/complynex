"""eKYC: the customer's own entry (consent page) and how it meets the card read."""
from ekyc.national_id import decode


def _valid_nid():
    # Build a checksum-valid fictional number: born 1990-05-12, Cairo (01).
    body = '2900512' + '01' + '1234'
    for check in '0123456789':
        if decode(body + check)['is_valid']:
            return body + check
    raise AssertionError('no valid check digit found')


def test_names_agree_folds_spelling():
    from ekyc.pipeline import names_agree
    assert names_agree('أحمد محمد علي حسن', 'احمد محمد علي')
    assert not names_agree('أحمد محمد علي', 'محمود سامي عادل')
    assert not names_agree('٤ = = ؟', 'احمد محمد علي')


def test_declared_used_when_card_unreadable():
    from ekyc.pipeline import _apply_declared_identity
    nid = _valid_nid()
    session = {'declared_national_id': nid, 'declared_name_ar': 'احمد محمد علي حسن'}
    out = _apply_declared_identity(session, {}, None, None, {})
    assert out['decoded']['national_id'] == nid
    assert out['name'] == 'احمد محمد علي حسن'
    assert out['field_sources']['national_id'] == 'declared'
    assert out['field_sources']['extracted_full_name_ar'] == 'declared'
    assert out['names_to_screen'] == ['احمد محمد علي حسن']
    assert len(out['reasons']) == 2


def test_mismatch_goes_to_review_and_screens_both_names():
    from ekyc.pipeline import _apply_declared_identity
    nid = _valid_nid()
    other = decode(nid)
    session = {'declared_national_id': nid, 'declared_name_ar': 'محمود سامي عادل'}
    out = _apply_declared_identity(session, other, 'احمد محمد علي حسن', 0.9, {})
    assert any('differs' in r for r in out['reasons'])
    assert out['names_to_screen'] == ['احمد محمد علي حسن', 'محمود سامي عادل']


def test_agreeing_read_adds_no_reason():
    from ekyc.pipeline import _apply_declared_identity
    nid = _valid_nid()
    session = {'declared_national_id': nid, 'declared_name_ar': 'احمد محمد علي'}
    out = _apply_declared_identity(session, decode(nid), 'أحمد محمد علي حسن', 0.9, {})
    assert out['reasons'] == []
    assert out['names_to_screen'] == ['أحمد محمد علي حسن']


def test_readings_settled_front():
    from ekyc.ocr_pipeline import _readings_settled
    nid = _valid_nid()
    frame = {'fields': {'national_id': {'text': nid, 'confidence': 0.6},
                        'full_name': {'text': 'احمد محمد', 'confidence': 0.8}}}
    weak = {'fields': {'national_id': {'text': '123', 'confidence': 0.2},
                       'full_name': {'text': '؟', 'confidence': 0.1}}}
    assert _readings_settled([frame, frame], 'front')
    assert not _readings_settled([frame, weak], 'front')


def test_queue_name(monkeypatch):
    from ekyc import queue
    from utils import demo
    monkeypatch.setattr(demo, '_MARKER', '/nonexistent/.demo_instance')
    monkeypatch.delenv('COMPLYNEX_DEMO', raising=False)
    monkeypatch.delenv('EKYC_QUEUE', raising=False)
    assert queue.queue_name() == 'ekyc'
    monkeypatch.setenv('COMPLYNEX_DEMO', '1')
    assert queue.queue_name() == 'ekyc_demo'
    monkeypatch.setenv('EKYC_QUEUE', 'custom')
    assert queue.queue_name() == 'custom'
