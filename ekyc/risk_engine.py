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
Fuses every eKYC signal (OCR/national-ID validity, face match, passive +
active liveness, document presentation-attack detection) into one
transparent risk score and a PASS/REVIEW/FAIL decision with human-
readable reasons.

Pure logic, no I/O — directly unit-testable (scripts/test_risk_engine.py)
independent of the database/worker/queue.
"""


def _ocr_subscore(ocr_result):
    if ocr_result.get('retake_required'):
        return 0.0, ['No usable ID frames after the capture-quality guard — a retake is needed']

    reasons = []
    score = 100.0

    decoded = ocr_result.get('national_id_decoded')
    if not decoded or not decoded.get('is_valid'):
        score -= 50.0
        errors = (decoded or {}).get('errors') or ['could not read a national ID number']
        reasons.append(f"National ID could not be validated: {'; '.join(errors)}")

    fields = ocr_result.get('fields', {})
    low_confidence = ocr_result.get('low_confidence_fields', [])
    if fields:
        score -= 30.0 * (len(low_confidence) / len(fields))
        if low_confidence:
            reasons.append(f"Low OCR confidence on: {', '.join(low_confidence)}")

    return max(0.0, score), reasons


def _face_match_subscore(face_match_result):
    if face_match_result.get('error'):
        return 0.0, [f"Face match failed: {face_match_result['error']}"]
    similarity = face_match_result.get('similarity') or 0.0
    score = max(0.0, min(100.0, similarity * 100))
    reasons = []
    if not face_match_result.get('is_match'):
        reasons.append(f"Selfie does not match ID photo (similarity={similarity:.2f}, "
                        f"threshold={face_match_result.get('threshold')})")
    return score, reasons


def _passive_liveness_subscore(passive_result):
    prob = passive_result.get('real_probability')
    if prob is None:
        return 0.0, ['Passive liveness could not be evaluated']
    score = prob * 100
    reasons = []
    if not passive_result.get('is_live'):
        reasons.append(f"Passive liveness check failed (real_probability={prob:.2f})")
    return score, reasons


def _active_liveness_subscore(active_liveness_pass, active_liveness_challenge):
    # None = "not evaluated" (selfie captured via the manual fallback
    # because the in-browser detector failed to load — see
    # static/ekyc/js/capture.js's runManualSelfieCapture), distinct from
    # False = "evaluated and failed". Returning None here tells fuse_risk()
    # to drop this layer's weight entirely rather than scoring it 0 — a
    # customer shouldn't be pushed toward FAIL because of a detector bug on
    # our side, not anything about them.
    if active_liveness_pass is None:
        return None, ["Active liveness not evaluated (selfie captured via manual fallback)"]
    if active_liveness_pass:
        return 100.0, []
    return 0.0, [f"Active liveness challenge ('{active_liveness_challenge}') was not completed"]


def _document_pad_subscore(document_pad_result):
    score = document_pad_result.get('document_pad_score')
    if score is None:
        return 0.0, ['Document presentation-attack check could not be evaluated']
    reasons = []
    if not document_pad_result.get('document_pad_pass'):
        flags = []
        if document_pad_result.get('moire_flag'):
            flags.append('moire/screen-replay pattern detected')
        if document_pad_result.get('reflection_flag'):
            flags.append('no angle-dependent reflection detected (expected from a genuine card)')
        reasons.append(f"Document presentation-attack check failed: {', '.join(flags) or 'low confidence'}")
    return score, reasons


def fuse_risk(ocr_result, face_match_result, passive_liveness_result, active_liveness_pass,
              active_liveness_challenge, document_pad_result, weights, threshold_pass, threshold_review):
    """
    weights: dict with keys ocr, face_match, passive_liveness, active_liveness, document_pad
    (see models.ekyc.EkycConfig.get_all_weights).

    Returns {risk_score, decision, reasons, sub_scores}.
    """
    ocr_score, ocr_reasons = _ocr_subscore(ocr_result)
    face_score, face_reasons = _face_match_subscore(face_match_result)
    passive_score, passive_reasons = _passive_liveness_subscore(passive_liveness_result)
    active_score, active_reasons = _active_liveness_subscore(active_liveness_pass, active_liveness_challenge)
    pad_score, pad_reasons = _document_pad_subscore(document_pad_result)

    sub_scores = {
        'ocr': ocr_score, 'face_match': face_score, 'passive_liveness': passive_score,
        'active_liveness': active_score, 'document_pad': pad_score,
    }
    # active_liveness_score is None when that layer wasn't evaluated at all
    # (manual-capture fallback) — exclude it from the weighted sum and
    # renormalize the remaining weights, instead of scoring it 0 (which
    # would unfairly drag a real customer toward FAIL for a problem that's
    # ours, not theirs).
    scored_keys = [key for key in sub_scores if sub_scores[key] is not None]
    weight_total = sum(weights[key] for key in scored_keys) or 1.0
    risk_score = sum(sub_scores[key] * weights[key] for key in scored_keys) / weight_total

    reasons = ocr_reasons + face_reasons + passive_reasons + active_reasons + pad_reasons

    if risk_score >= threshold_pass:
        decision = 'PASS'
    elif risk_score >= threshold_review:
        decision = 'REVIEW'
    else:
        decision = 'FAIL'

    # Hard gate: with no usable ID read at all, there's no identity to
    # weigh other signals against — a high score from face/liveness/PAD
    # alone can't outweigh that, so this overrides the weighted result
    # rather than just contributing 20% of it.
    if ocr_result.get('retake_required') and decision != 'FAIL':
        decision = 'FAIL'

    # Hard gate: name and/or national ID specifically unreadable/invalid
    # can't auto-PASS even when frames were usable and every other signal
    # (face match, liveness, PAD) scored well enough to outweigh it in the
    # weighted sum above — those are presence/liveness checks, not identity
    # checks, and PASS is supposed to mean "AI confirmed who this is". Caps
    # at REVIEW rather than forcing FAIL: the person may well be exactly who
    # they claim, a human just needs to read the field AI couldn't.
    decoded = ocr_result.get('national_id_decoded')
    full_name_readable = (
        bool((ocr_result.get('fields', {}).get('full_name') or {}).get('text'))
        and 'full_name' not in (ocr_result.get('low_confidence_fields') or [])
    )
    identity_unreadable = not full_name_readable or not decoded or not decoded.get('is_valid')
    if identity_unreadable and decision == 'PASS':
        decision = 'REVIEW'
        reasons.append('Name and/or national ID could not be read with confidence — '
                        'routed to manual review rather than auto-approved')

    return {
        'risk_score': round(risk_score, 2),
        'decision': decision,
        'reasons': reasons or ['All checks passed.'],
        'sub_scores': sub_scores,
    }


def apply_screening_override(decision, screening_result):
    """
    A sanctions/PEP hit must never be silently auto-passed regardless of
    biometric score: a confirmed hit or potential match caps the decision
    at REVIEW (a human must look at any real compliance hit) even if
    every other signal scored perfectly.
    """
    if screening_result in ('CONFIRMED_HIT', 'POTENTIAL_MATCH') and decision == 'PASS':
        return 'REVIEW', [f"Screening result '{screening_result}' requires manual review regardless of biometric score"]
    return decision, []
