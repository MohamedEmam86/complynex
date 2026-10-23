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
The eKYC verification pipeline: orchestrates every layer (national-ID
validation, OCR, face match, liveness, document-PAD) into one risk score
and PASS/REVIEW/FAIL decision, then auto-routes the extracted identity
through the existing screening engine.

Runs inside the dedicated eKYC worker process (ekyc/worker.py), never the
web workers — see ekyc/queue.py for why.
"""
import json
import logging

import cv2
import numpy as np
from flask import current_app

from ekyc.document_pad import assess_document_pad
from ekyc.face_liveness import check_passive_liveness
from ekyc.gov_verification import verify_with_government_database
from ekyc.face_match import detect_largest_face, get_embedding, verify as face_verify
from ekyc.id_layout import crop_fields
from ekyc.document_capture import correct_perspective
from ekyc.ocr_pipeline import extract_id_fields_multiframe
from ekyc.risk_engine import fuse_risk, apply_screening_override
from ekyc.secure_storage import read_frame
from models.ekyc import EkycDocument, EkycResult, EkycConfig, EkycSession, EkycAuditLog

logger = logging.getLogger(__name__)


def _decode_frames(documents, doc_role):
    frames = []
    for doc in documents:
        if doc['doc_role'] != doc_role:
            continue
        data = read_frame(doc['stored_path'], key_version=doc['encryption_key_id'])
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            frames.append(frame)
    return frames


def _best_id_photo_crop(id_frames):
    """Perspective-corrects the first ID frame and crops the photo region for face matching."""
    if not id_frames:
        return None
    corrected, _ = correct_perspective(id_frames[0])
    crops = crop_fields(corrected, side='front')
    return crops.get('photo')


def _best_face_match(id_photo, selfie_frames):
    """Tries every selfie frame against the ID photo, keeps the highest-similarity result."""
    best = {'is_match': False, 'similarity': None, 'threshold': None,
            'engine': 'arcface_insightface', 'error': 'no selfie frames available'}
    best_frame = None
    if id_photo is None:
        return {'is_match': False, 'similarity': None, 'threshold': None,
                'engine': 'arcface_insightface', 'error': 'could not crop a photo from the ID card'}, None

    for frame in selfie_frames:
        result = face_verify(id_photo, frame)
        if result['similarity'] is not None and (best['similarity'] is None or result['similarity'] > best['similarity']):
            best = result
            best_frame = frame
    return best, best_frame


def run_pipeline(session_id):
    session = EkycSession.get_by_id(session_id)
    documents = EkycDocument.list_for_session(session_id)
    existing_result = EkycResult.get_for_session(session_id) or {}

    id_frames = _decode_frames(documents, 'ID_FRONT_VIDEO')
    id_back_frames = _decode_frames(documents, 'ID_BACK_VIDEO')
    selfie_frames = _decode_frames(documents, 'SELFIE_VIDEO')

    # ---- OCR + national ID (front) ----
    ocr_result = extract_id_fields_multiframe(id_frames, side='front') if id_frames else {
        'card_detected': False, 'fields': {}, 'national_id_decoded': None,
        'frames_total': 0, 'frames_usable': 0, 'frame_quality_issues': [],
        'low_confidence_fields': [], 'retake_required': True,
    }
    EkycAuditLog.log(session_id, 'OCR_COMPLETED',
                      details=f"frames_usable={ocr_result.get('frames_usable')}/{ocr_result.get('frames_total')}")

    # ---- Browser OCR hint (draft-only, see static/ekyc/js/capture.js's
    # readIdHint()) — informational only: surfaced to the reviewing officer
    # via raw_signals below, never fed into ocr_result/fuse_risk/decision.
    client_ocr_hint = next(
        (doc.get('client_ocr_hint') for doc in documents
         if doc['doc_role'] == 'ID_FRONT_VIDEO' and doc.get('client_ocr_hint')),
        None,
    )
    ocr_hint_agrees_national_id = None
    if client_ocr_hint and client_ocr_hint.get('national_id'):
        server_national_id = (ocr_result.get('national_id_decoded') or {}).get('national_id')
        if server_national_id:
            ocr_hint_agrees_national_id = client_ocr_hint['national_id'] == server_national_id

    # ---- OCR (back) — occupation/marital_status/gender/expiry_date fields,
    # per ekyc/id_layout.py's BACK_FIELDS. Optional: only present when the
    # capture flow collected a back-side image (currently NATIONAL_ID
    # sessions; see ekyc/routes.py's BACK_SIDE_REQUIRED_TYPES).
    ocr_back_result = extract_id_fields_multiframe(id_back_frames, side='back') if id_back_frames else {
        'card_detected': False, 'fields': {}, 'frames_total': 0, 'frames_usable': 0,
        'frame_quality_issues': [], 'low_confidence_fields': [], 'retake_required': True,
    }
    if id_back_frames:
        EkycAuditLog.log(session_id, 'OCR_BACK_COMPLETED',
                          details=f"frames_usable={ocr_back_result.get('frames_usable')}/{ocr_back_result.get('frames_total')}")

    # ---- Face match + passive liveness ----
    id_photo = _best_id_photo_crop(id_frames)
    face_match_result, matched_selfie_frame = _best_face_match(id_photo, selfie_frames)
    EkycAuditLog.log(session_id, 'FACE_MATCH_COMPLETED', details=str(face_match_result.get('similarity')))

    if matched_selfie_frame is not None:
        face = detect_largest_face(matched_selfie_frame)
        passive_liveness_result = (check_passive_liveness(matched_selfie_frame, face.bbox) if face
                                    else {'is_live': False, 'real_probability': None, 'engine': 'silent_face_minifasnet'})
    else:
        passive_liveness_result = {'is_live': False, 'real_probability': None, 'engine': 'silent_face_minifasnet'}
    EkycAuditLog.log(session_id, 'PASSIVE_LIVENESS_COMPLETED',
                      details=str(passive_liveness_result.get('real_probability')))

    # ---- Document presentation-attack detection ----
    # Front + back combined: a spoofed card is just as likely to be replayed/
    # printed on whichever side was easier to fake, and moire/reflection are
    # per-frame signals independent of which field layout that frame uses.
    pad_frames = id_frames + id_back_frames
    document_pad_result = (assess_document_pad(pad_frames) if len(pad_frames) >= 3 else {
        'document_pad_score': None, 'document_pad_pass': False,
        'moire_flag': False, 'reflection_flag': False, 'frames_analyzed': len(pad_frames),
    })
    EkycAuditLog.log(session_id, 'DOCUMENT_PAD_COMPLETED', details=str(document_pad_result.get('document_pad_score')))

    # ---- Active liveness (client-evaluated at upload time, see ekyc/routes.py) ----
    # NULL means "not evaluated" (manual-selfie fallback because the
    # in-browser detector failed to load) — must stay None here, not get
    # coerced to False, or fuse_risk() can't tell it apart from "evaluated
    # and failed". See ekyc/routes.py's upload_capture.
    raw_active_liveness_pass = existing_result.get('active_liveness_pass')
    active_liveness_pass = None if raw_active_liveness_pass is None else bool(raw_active_liveness_pass)
    active_liveness_challenge = existing_result.get('active_liveness_challenge')

    # ---- Government-database verification (pluggable seam, not yet configured) ----
    decoded_preview = ocr_result.get('national_id_decoded') or {}
    name_preview = (ocr_result.get('fields', {}).get('full_name') or {}).get('text')
    gov_verification_result = verify_with_government_database(decoded_preview.get('national_id'), name_preview)
    EkycAuditLog.log(session_id, 'GOV_VERIFICATION_SKIPPED', details=gov_verification_result['note'])

    # ---- Risk fusion ----
    weights = EkycConfig.get_all_weights()
    threshold_pass = EkycConfig.get_float('risk_threshold_pass')
    threshold_review = EkycConfig.get_float('risk_threshold_review')
    fused = fuse_risk(ocr_result, face_match_result, passive_liveness_result, active_liveness_pass,
                       active_liveness_challenge, document_pad_result, weights, threshold_pass, threshold_review)
    decision, override_reasons = fused['decision'], []

    # ---- Cross-check against what the customer typed on the consent page ----
    # The card read is authoritative when it is readable; the customer's
    # own entry fills the gap when it is not (bad light, worn card), and a
    # disagreement between the two always goes to an officer.
    decoded = ocr_result.get('national_id_decoded') or {}
    name_field = ocr_result.get('fields', {}).get('full_name') or {}
    name = name_field.get('text')
    if name and not _name_tokens(name):
        name = None  # nothing but OCR noise (digits, symbols) — never screen that
    identity = _apply_declared_identity(session, decoded, name, name_field.get('confidence'),
                                        existing_result.get('field_sources'))
    decoded, name = identity['decoded'], identity['name']
    if identity['reasons'] and decision == 'PASS':
        decision = 'REVIEW'

    # ---- Screening hook ----
    # Hits are written into screening_history/screening_queue with
    # source_module='eKYC' — the same tables and disposition workflow
    # Customer KYC and Merchant KYC already use (see aml/routes.py) — so
    # officers disposition eKYC hits in the existing /screening/queue UI
    # rather than a second, eKYC-only disposition system.
    screening_result = None
    screening_history_id = None
    pending_screening_matches = 0
    for screen_name in identity['names_to_screen']:
        history_id, result_label, pending = _run_screening(session_id, screen_name, decoded)
        pending_screening_matches += pending
        if screening_history_id is None or pending:
            screening_history_id = history_id
        if result_label and (screening_result is None or pending):
            screening_result = result_label
        EkycAuditLog.log(session_id, 'SCREENING_COMPLETED', details=f"{screen_name}: {result_label}")

    if screening_result:
        decision, override_reasons = apply_screening_override(decision, screening_result)

    reasons = fused['reasons'] + identity['reasons'] + override_reasons

    EkycResult.upsert(
        session_id,
        extracted_full_name_ar=name,
        national_id=decoded.get('national_id'),
        national_id_valid=decoded.get('is_valid'),
        dob=decoded.get('dob'),
        gender=decoded.get('gender'),
        governorate_code=decoded.get('governorate_code'),
        governorate_name=decoded.get('governorate_name_ar'),
        ocr_confidence=_avg_confidence(ocr_result),
        ocr_engine_used='easyocr',
        face_match_score=face_match_result.get('similarity'),
        face_match_engine=face_match_result.get('engine'),
        passive_liveness_score=passive_liveness_result.get('real_probability'),
        passive_liveness_pass=passive_liveness_result.get('is_live'),
        document_pad_score=document_pad_result.get('document_pad_score'),
        document_pad_pass=document_pad_result.get('document_pad_pass'),
        back_card_detected=ocr_back_result.get('card_detected') if id_back_frames else None,
        back_ocr_confidence=_avg_confidence(ocr_back_result) if id_back_frames else None,
        extracted_address=(ocr_result.get('fields', {}).get('address') or {}).get('text') or None,
        extracted_occupation=(ocr_back_result.get('fields', {}).get('occupation') or {}).get('text') or None,
        extracted_marital_status=(ocr_back_result.get('fields', {}).get('marital_status') or {}).get('text') or None,
        id_expiry_raw=(ocr_back_result.get('fields', {}).get('expiry_date') or {}).get('text') or None,
        risk_score=fused['risk_score'],
        decision=decision,
        decision_reasons=json.dumps(reasons),
        screening_result=screening_result,
        screening_history_id=screening_history_id,
        field_sources=json.dumps(identity['field_sources']),
        raw_signals=json.dumps({
            'declared': identity['declared'],
            'ocr': _json_safe(ocr_result), 'ocr_back': _json_safe(ocr_back_result),
            'face_match': _json_safe(face_match_result),
            'passive_liveness': _json_safe(passive_liveness_result),
            'document_pad': _json_safe(document_pad_result), 'fused': _json_safe(fused),
            'gov_verification': _json_safe(gov_verification_result),
            'ocr_hint': client_ocr_hint, 'ocr_hint_agrees_national_id': ocr_hint_agrees_national_id,
        }),
        processed_at=_now(),
    )
    EkycAuditLog.log(session_id, 'DECISION_MADE', details=f"decision={decision} risk_score={fused['risk_score']}")

    # ---- Session-level status (back office's worklist) ----
    # PASS with no screening hit needing a human look still stops at
    # DECISION_PENDING, not an auto-onboard — an officer always makes the
    # final Approve/Reject call (see ekyc/routes.py's session_decision).
    # Anything the pipeline itself wasn't confident about, or that produced
    # a screening hit pending disposition, goes to NEEDS_REVIEW instead.
    if decision == 'PASS' and pending_screening_matches == 0:
        EkycSession.update_status(session_id, 'DECISION_PENDING')
    else:
        EkycSession.update_status(session_id, 'NEEDS_REVIEW')


_ARABIC_FOLD = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ة': 'ه', 'ى': 'ي'})


def _name_tokens(name):
    """Arabic-letter words of a name, with common spelling variants folded."""
    import re
    letters_only = re.sub(r'[^\u0621-\u064A\s]', ' ', name or '')
    return [t for t in letters_only.translate(_ARABIC_FOLD).split() if len(t) > 1]


def names_agree(a, b):
    """Same person by name: first names match and most words are shared."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb or ta[0] != tb[0]:
        return False
    shared = len(set(ta) & set(tb))
    return shared / min(len(set(ta)), len(set(tb))) >= 0.6


def _apply_declared_identity(session, decoded, name, name_confidence, field_sources):
    """Merge the card read with the customer's own entry (consent page).

    Returns dict(decoded, name, reasons, field_sources, names_to_screen, declared).
    """
    from ekyc.national_id import decode as decode_national_id
    from ekyc.ocr_pipeline import MIN_FIELD_CONFIDENCE

    sources = dict(field_sources or {})
    reasons = []
    declared_nid = (session or {}).get('declared_national_id')
    declared_name = (session or {}).get('declared_name_ar')
    ocr_nid = decoded.get('national_id') if decoded.get('is_valid') else None
    names = []

    if declared_nid:
        if ocr_nid and ocr_nid != declared_nid:
            reasons.append(f"National ID read from the card ({ocr_nid}) differs from the number "
                           f"the customer entered ({declared_nid}) — check the card image")
        elif not ocr_nid:
            declared_decoded = decode_national_id(declared_nid)
            if declared_decoded.get('is_valid'):
                decoded = declared_decoded
                for field in ('national_id', 'dob', 'gender', 'governorate_name'):
                    sources[field] = 'declared'
                reasons.append('National ID could not be read from the card; the number the customer '
                               'entered is used — check it against the card image')

    name_readable = bool(name) and len(_name_tokens(name)) >= 2 and (name_confidence or 0) >= MIN_FIELD_CONFIDENCE
    if declared_name:
        if name_readable and not names_agree(name, declared_name):
            reasons.append(f"Name read from the card ({name}) differs from the name the customer "
                           f"entered ({declared_name}) — check the card image")
            names = [name, declared_name]
        elif not name_readable:
            name = declared_name
            sources['extracted_full_name_ar'] = 'declared'
            reasons.append('Name could not be read from the card with confidence; the name the customer '
                           'entered is used — check it against the card image')
    if not names and name:
        names = [name]

    return {
        'decoded': decoded, 'name': name, 'reasons': reasons, 'field_sources': sources,
        'names_to_screen': names,
        'declared': {'national_id': declared_nid, 'name_ar': declared_name},
    }


def _run_screening(session_id, name, decoded):
    """
    Screens the OCR'd identity and records the outcome the same way
    Customer KYC / Merchant KYC already do (aml/routes.py): one
    screening_history row, plus one screening_queue row per match scoring
    >=70 (the same threshold used there) for an officer to disposition in
    the existing /screening/queue UI. source_module='eKYC' is how
    screening.routes._update_source_screening_status routes a resolved
    queue item's side effects back onto this ekyc_session.

    Returns (screening_history_id, screening_result, pending_match_count).
    """
    from database.db import get_db
    from screening.complynex_engine import ComplyNexScreeningEngine

    db = get_db()
    screening_result = None
    history_id = None
    matches = []
    try:
        engine = ComplyNexScreeningEngine(current_app.config['DATABASE'])
        screen_outcome = engine.screen_person(
            name=name,
            date_of_birth=decoded.get('dob'),
            nationality='Egypt',
            entity_type='INDIVIDUAL',
            national_id=decoded.get('national_id'),
        )
        screening_result = screen_outcome.get('screening_result')
        matches = screen_outcome.get('matches', [])
        engine.close()
    except Exception:
        logger.exception(f"Screening lookup failed for eKYC session {session_id}")
        return None, None, 0

    high_risk = [m for m in matches if m.get('match_score', 0) >= 70.0]

    cur = db.execute('''
        INSERT INTO screening_history
            (entity_name, entity_type, screening_type, source_module, source_record_id,
             total_matches_found, high_risk_matches, auto_cleared_matches, highest_score,
             screening_result, matches_json, status)
        VALUES (%s, 'INDIVIDUAL', 'eKYC Onboarding', 'eKYC', %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (name, session_id, len(matches), len(high_risk), len(matches) - len(high_risk),
          screen_outcome.get('highest_score', 0.0), screening_result, json.dumps({'matches': matches}),
          'Pending Review' if high_risk else 'Completed'))
    history_id = cur.fetchone()['id']
    db.commit()

    for match in high_risk:
        priority = 'High' if match.get('match_score', 0) >= 90 else 'Medium'
        db.execute('''
            INSERT INTO screening_queue
                (screening_history_id, entity_name, entity_type, match_name, match_score,
                 list_source, match_details, priority, status, source_module, source_record_id, created_at)
            VALUES (%s, %s, 'INDIVIDUAL', %s, %s, %s, %s, %s, 'Pending', 'eKYC', %s, CURRENT_TIMESTAMP)
        ''', (history_id, name, match.get('full_name', match.get('watchlist_name_ar', '')),
              match.get('match_score', 0), match.get('source', match.get('dataset', 'Unknown')),
              json.dumps(match), priority, session_id))
    db.commit()

    return history_id, screening_result, len(high_risk)


def _avg_confidence(ocr_result):
    fields = ocr_result.get('fields') or {}
    confidences = [f['confidence'] for f in fields.values() if f.get('confidence') is not None]
    # EasyOCR confidences are numpy float32/64 — psycopg2 has no adapter for
    # numpy scalar types, so this must be cast to a native Python float.
    return round(float(sum(confidences) / len(confidences)), 2) if confidences else None


def _json_safe(d):
    """Strips non-JSON-serializable values (e.g. datetime.date) for the raw_signals audit dump."""
    return json.loads(json.dumps(d, default=str))


def _now():
    from datetime import datetime
    return datetime.now()
