"""eKYC: three sessions on fictional sample cards (the faces are placeholders):
one onboarded after review, one waiting for an officer because the card could
not be read (the customer's own entry is used), one link not yet opened.
Images are encrypted into the demo's own ekyc_storage like real captures."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, 'ekyc_samples')


def _frames(who, side, n):
    out = []
    for i in range(n):
        with open(os.path.join(SAMPLES, f'{who}_{side}_{i}.jpg'), 'rb') as f:
            out.append(f.read())
    return out


def _capture(session, who):
    from ekyc.secure_storage import save_frame
    from models.ekyc import EkycDocument
    for role, side, n in (('ID_FRONT_VIDEO', 'front', 3), ('ID_BACK_VIDEO', 'back', 2), ('SELFIE_VIDEO', 'selfie', 2)):
        for data in _frames(who, side, n):
            path, size, key = save_frame(session['session_token'], role, data)
            EkycDocument.create(session['id'], role, path, encryption_key_id=key, file_size=size, mime_type='image/jpeg')


def seed(ctx):
    from database.db import get_db
    from models.ekyc import EkycSession, EkycResult, EkycAuditLog
    from models.aml import Customer
    ctx.commit()
    db = get_db()
    co, mlro = ctx.uid('co'), ctx.uid('mlro')

    # 1. Mona — clear card, reviewed, approved and onboarded
    s = EkycSession.create(document_type='NATIONAL_ID', customer_reference='CUST-10241', created_by=co, locale='ar')
    EkycSession.record_consent(s['id'], 'demo consent', '10.0.0.21', declared_national_id='29508140123468',
                               declared_name_ar='منى سامح عبد الفتاح النجار')
    _capture(s, 'mona')
    EkycResult.upsert(s['id'], extracted_full_name_ar='منى سامح عبد الفتاح النجار', national_id='29508140123468',
                      national_id_valid=True, dob='1995-08-14', gender='female', governorate_code='01',
                      governorate_name='القاهرة', ocr_confidence=0.82, ocr_engine_used='easyocr',
                      face_match_score=0.91, face_match_engine='arcface_insightface', passive_liveness_score=0.99,
                      passive_liveness_pass=True, active_liveness_pass=True, active_liveness_challenge='blink',
                      document_pad_score=96, document_pad_pass=True, back_card_detected=True, back_ocr_confidence=0.71,
                      extracted_address='١٢ شارع النيل العجوزة الجيزة', extracted_occupation='مهندسة',
                      extracted_marital_status='آنسة', id_expiry_raw='2029-05-12', risk_score=96.5, decision='PASS',
                      decision_reasons=json.dumps(['All checks passed.']), screening_result='CLEAR',
                      field_sources=json.dumps({'extracted_address': 'manual', 'extracted_full_name_ar': 'confirmed',
                                                'national_id': 'confirmed'}),
                      final_name='منى سامح عبد الفتاح النجار', final_national_id='29508140123468',
                      final_address='١٢ شارع النيل، العجوزة، الجيزة', processed_at=ctx.ago(3))
    EkycSession.record_review(s['id'], co, notes='Address punctuation corrected from the card image (demo).')
    EkycSession.record_decision(s['id'], 'APPROVED', mlro, 'All checks clear (demo).')
    cid = Customer.create({'customer_type': 'INDIVIDUAL', 'full_name': 'منى سامح عبد الفتاح النجار',
                           'date_of_birth': '1995-08-14', 'nationality': 'Egypt', 'id_type': 'NATIONAL_ID',
                           'id_number': '29508140123468', 'id_expiry_date': '2029-05-12',
                           'address': '١٢ شارع النيل، العجوزة، الجيزة', 'country': 'EGYPT'})
    if cid:
        EkycSession.record_onboarding(s['id'], cid, user_id=mlro)

    # 2. Youssef — card unreadable (worn), customer's own entry used, waiting for an officer
    s2 = EkycSession.create(document_type='NATIONAL_ID', customer_reference='CUST-10242', created_by=co, locale='ar')
    EkycSession.record_consent(s2['id'], 'demo consent', '10.0.0.37', declared_national_id='28807210104571',
                               declared_name_ar='يوسف كمال حسن الشربيني')
    _capture(s2, 'youssef')
    reasons = ["National ID could not be validated: Expected 14 digits, got 0: ''",
               'Low OCR confidence on: national_id, full_name',
               'Name and/or national ID could not be read with confidence — routed to manual review rather than auto-approved',
               'National ID could not be read from the card; the number the customer entered is used — check it against the card image',
               'Name could not be read from the card with confidence; the name the customer entered is used — check it against the card image',
               'Selfie does not match ID photo (similarity=0.21, threshold=0.40)']
    EkycResult.upsert(s2['id'], extracted_full_name_ar='يوسف كمال حسن الشربيني', national_id='28807210104571',
                      national_id_valid=True, dob='1988-07-21', gender='male', governorate_code='01',
                      governorate_name='القاهرة', ocr_confidence=0.24, ocr_engine_used='easyocr', face_match_score=0.21,
                      face_match_engine='arcface_insightface', passive_liveness_score=0.97, passive_liveness_pass=True,
                      active_liveness_pass=True, active_liveness_challenge='smile', document_pad_score=88,
                      document_pad_pass=True, back_card_detected=True, back_ocr_confidence=0.63,
                      extracted_address='١٢ شارع النيل العجوزة الجيزة', extracted_occupation='محاسب',
                      extracted_marital_status='متزوج', risk_score=58.0, decision='REVIEW',
                      decision_reasons=json.dumps(reasons), screening_result='CLEAR',
                      field_sources=json.dumps({k: 'declared' for k in ('national_id', 'dob', 'gender', 'governorate_name',
                                                                         'extracted_full_name_ar')}),
                      processed_at=ctx.ago(1))
    EkycSession.update_status(s2['id'], 'NEEDS_REVIEW')

    # 3. a link created this morning, not opened yet
    EkycSession.create(document_type='NATIONAL_ID', customer_reference='CUST-10243', created_by=co, locale='ar')

    # spread the timeline: Mona 4 days ago, Youssef yesterday
    db.execute("UPDATE ekyc_session SET created_at = created_at - interval '4 days', consent_given_at = consent_given_at - interval '4 days' WHERE id = %s", (s['id'],))
    db.execute("UPDATE ekyc_session SET created_at = created_at - interval '1 day', consent_given_at = consent_given_at - interval '1 day' WHERE id = %s", (s2['id'],))
    db.commit()
