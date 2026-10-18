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
Ties together card perspective-correction (document_capture), fixed-ratio
field cropping (id_layout), OCR (ocr_engine), and the national-ID
validator/decoder (national_id) into one call: extract_id_fields().

extract_id_fields_multiframe() is the entry point the real pipeline should
use once video capture exists — it runs the capture-quality guard,
OCRs every usable frame, and takes a per-field consensus across frames
rather than trusting any single frame's read.

Field detection hierarchy:
  1. YOLO (best.onnx) — activated when EKYC_YOLO_MODEL env var points to
     the model file.  Crops detected fields from the perspective-corrected
     card image.  Falls back to (2) if no detections / low confidence.
  2. Fixed-% positions (id_layout.py) — reliable fallback while the YOLO
     model is being trained or isn't deployed yet.
"""
import logging
import os
import threading
import cv2
import numpy as np
from collections import Counter

from ekyc.capture_quality import filter_usable_frames
from ekyc.document_capture import correct_perspective
from ekyc.id_layout import crop_fields, FRONT_FIELDS, BACK_FIELDS
from ekyc.national_id import decode as decode_national_id
from ekyc.ocr_engine import read_text

logger = logging.getLogger(__name__)

# A field's consensus confidence below this routes the session to REVIEW
# rather than being silently accepted.
MIN_FIELD_CONFIDENCE = 0.55

# Downscale gate: 12 MP phone frames are 4000×3000 — passing them raw to
# perspective_correct + EasyOCR spikes RAM and slows the worker.  Shrink to
# this max dimension before any processing; text is still legible at 1600 px
# on the long side for a credit-card-sized document.
_MAX_INPUT_SIDE = 1600

# ---------------------------------------------------------------------------
# YOLO field detector (stub — activates when best.onnx is deployed)
# ---------------------------------------------------------------------------
_YOLO_MODEL_PATH = os.getenv(
    'EKYC_YOLO_MODEL',
    '/var/www/complynex/ekyc/models/best.onnx',
)
_YOLO_CLASS_NAMES = ['full_name', 'address', 'national_id', 'photo']
_YOLO_CONF_THRESHOLD = 0.45
_YOLO_INPUT_SIZE = 640

_yolo_session = None
_yolo_lock = threading.Lock()


def _get_yolo_session():
    """Lazy-load the ONNX session; returns None if best.onnx isn't present."""
    global _yolo_session
    if _yolo_session is not None:
        return _yolo_session
    if not os.path.exists(_YOLO_MODEL_PATH):
        return None
    with _yolo_lock:
        if _yolo_session is None:
            try:
                import onnxruntime as ort
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 1
                opts.inter_op_num_threads = 1
                _yolo_session = ort.InferenceSession(
                    _YOLO_MODEL_PATH,
                    sess_options=opts,
                    providers=['CPUExecutionProvider'],
                )
                logger.info("YOLO field detector loaded: %s", _YOLO_MODEL_PATH)
            except Exception as exc:
                logger.warning("YOLO load failed (%s) — using fixed-%% fallback", exc)
                return None
    return _yolo_session


def _yolo_crop_fields(corrected_bgr, side):
    """
    Run best.onnx on the perspective-corrected card.
    Returns {field_name: crop_array} or None on any failure / low confidence.
    YOLOv8 output format: [1, 4+num_classes, 8400] — xywh + per-class scores.
    """
    sess = _get_yolo_session()
    if sess is None:
        return None

    h, w = corrected_bgr.shape[:2]
    img = cv2.cvtColor(corrected_bgr, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (_YOLO_INPUT_SIZE, _YOLO_INPUT_SIZE))
    inp = (img.astype(np.float32) / 255.0).transpose(2, 0, 1)[np.newaxis]

    try:
        out = sess.run(None, {sess.get_inputs()[0].name: inp})[0]
    except Exception as exc:
        logger.warning("YOLO inference error: %s", exc)
        return None

    num_cls = len(_YOLO_CLASS_NAMES)
    preds = out[0].T                      # [8400, 4+num_cls]
    boxes_xywh = preds[:, :4]
    scores = preds[:, 4:4 + num_cls]
    class_ids = scores.argmax(axis=1)
    confidences = scores.max(axis=1)

    mask = confidences >= _YOLO_CONF_THRESHOLD
    if not mask.any():
        logger.debug("YOLO: no detections above threshold, using fixed-%% fallback")
        return None

    boxes_xywh = boxes_xywh[mask]
    class_ids = class_ids[mask]
    confidences = confidences[mask]

    # Sort by confidence descending so first occurrence per class wins
    order = confidences.argsort()[::-1]
    boxes_xywh, class_ids = boxes_xywh[order], class_ids[order]

    sx, sy = w / _YOLO_INPUT_SIZE, h / _YOLO_INPUT_SIZE
    x1 = ((boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2) * sx).clip(0, w).astype(int)
    y1 = ((boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2) * sy).clip(0, h).astype(int)
    x2 = ((boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2) * sx).clip(0, w).astype(int)
    y2 = ((boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2) * sy).clip(0, h).astype(int)

    expected = set(FRONT_FIELDS if side == 'front' else BACK_FIELDS)
    crops = {}
    for i in range(len(class_ids)):
        name = _YOLO_CLASS_NAMES[class_ids[i]]
        if name not in expected or name in crops:
            continue
        if x2[i] - x1[i] < 10 or y2[i] - y1[i] < 5:
            continue
        crops[name] = corrected_bgr[y1[i]:y2[i], x1[i]:x2[i]]

    if not crops:
        return None

    logger.debug("YOLO: detected %d field(s): %s", len(crops), list(crops.keys()))
    return crops


def _get_crops(corrected_bgr, side):
    """Try YOLO field detector; fall back to fixed-%% positions if unavailable."""
    crops = _yolo_crop_fields(corrected_bgr, side)
    if crops is None:
        crops = crop_fields(corrected_bgr, side=side)
    return crops


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------

def _downscale_guard(image, max_side=_MAX_INPUT_SIDE):
    """Shrink to max_side on the long axis if needed; no-op otherwise."""
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return image
    scale = max_side / longest
    return cv2.resize(
        image,
        (round(w * scale), round(h * scale)),
        interpolation=cv2.INTER_AREA,
    )


def _clean_strip(crop_bgr):
    """
    5-step prep for a text-field crop:
      bilateral filter  — denoise while preserving character edges
      CLAHE             — local contrast boost for low-light / uneven exposures
      2× cubic upscale  — more pixels for EasyOCR's sub-pixel detector
      adaptive threshold— binarise against local background (guilloché pattern)
      unsharp mask      — sharpen strokes that adaptive-threshold softened

    NOT applied to the photo crop (face-match uses the colour image).
    """
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.bilateralFilter(g, 7, 50, 50)
    g = cv2.createCLAHE(2.0, (8, 8)).apply(g)
    g = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    clean = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11,
    )
    clean = cv2.filter2D(
        clean, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32),
    )
    return clean


# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

def _read_text_best_of(crop, rtl, debug_sink=None):
    """
    Tries the cleaned strip first (common path; one EasyOCR call).
    Falls back to the plain crop only when cleaned confidence is below
    MIN_FIELD_CONFIDENCE — keeps the per-frame OCR cost bounded.
    """
    cleaned_detections = [] if debug_sink is not None else None
    cleaned_text, cleaned_confidence = read_text(
        _clean_strip(crop), rtl=rtl, debug_sink=cleaned_detections,
    )

    if cleaned_confidence >= MIN_FIELD_CONFIDENCE:
        if debug_sink is not None:
            debug_sink.extend(cleaned_detections)
        return cleaned_text, cleaned_confidence, 'cleaned'

    plain_detections = [] if debug_sink is not None else None
    plain_text, plain_confidence = read_text(crop, rtl=rtl, debug_sink=plain_detections)

    if plain_confidence > cleaned_confidence:
        if debug_sink is not None:
            debug_sink.extend(plain_detections)
        return plain_text, plain_confidence, 'plain'
    if debug_sink is not None:
        debug_sink.extend(cleaned_detections)
    return cleaned_text, cleaned_confidence, 'cleaned'


def _ocr_canonical(corrected, side, card_detected, debug_sink=None):
    crops = _get_crops(corrected, side)

    fields = {}
    for name, crop in crops.items():
        if name == 'photo':
            continue
        raw_detections = [] if debug_sink is not None else None
        text, confidence, variant = _read_text_best_of(
            crop, rtl=(name != 'national_id'), debug_sink=raw_detections,
        )
        fields[name] = {'text': text, 'confidence': confidence}
        if debug_sink is not None:
            debug_sink.setdefault('raw_ocr', {})[name] = raw_detections
            debug_sink.setdefault('crops', {})[name] = crop
            debug_sink.setdefault('preprocessing', {})[name] = variant

    result = {'card_detected': card_detected, 'fields': fields, 'national_id_decoded': None}

    if side == 'front' and 'national_id' in fields:
        result['national_id_decoded'] = decode_national_id(fields['national_id']['text'])

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_id_fields(image_bgr, side='front', debug_sink=None):
    """
    image_bgr: raw captured frame (np.ndarray, BGR) with card + background.

    Returns:
        card_detected (bool)
        fields: {field_name: {'text': str, 'confidence': float}}
        national_id_decoded: decode() result for 'national_id' on front side

    debug_sink: if given a dict, receives 'raw_ocr', 'crops', 'preprocessing'
    keys for the first frame — for diagnosing real captures without changing
    the return value.
    """
    # Downscale before any processing — large phone images spike RAM
    image_bgr = _downscale_guard(image_bgr)

    # Mobile phones upload portrait frames for landscape cards
    h, w = image_bgr.shape[:2]
    if h > w:
        logger.info("Portrait frame — rotating 90° CCW for OCR")
        image_bgr = cv2.rotate(image_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)

    corrected, card_detected = correct_perspective(image_bgr)
    return _ocr_canonical(corrected, side, card_detected, debug_sink=debug_sink)


def extract_id_fields_from_canonical(canonical_bgr, side='front', debug_sink=None):
    """
    For input already perspective-corrected (test fixtures, pre-processed
    frames) — skips corner detection entirely.
    """
    return _ocr_canonical(canonical_bgr, side, card_detected=True, debug_sink=debug_sink)


def _consensus(readings):
    """
    readings: list of (text, confidence) from multiple frames for one field.
    Returns (text, confidence, agreement_ratio).
    """
    if not readings:
        return '', 0.0, 0.0
    normalized = [text.strip() for text, _ in readings]
    winner, count = Counter(normalized).most_common(1)[0]
    matching_confidences = [conf for text, conf in readings if text.strip() == winner]
    return winner, sum(matching_confidences) / len(matching_confidences), count / len(readings)


def extract_id_fields_multiframe(frames, side='front', debug_sink=None):
    """
    frames: list of raw video frames (np.ndarray, BGR) of the same card.

    Runs capture-quality guard → per-frame OCR → per-field consensus.
    Valid national_id readings are preferred in consensus even at lower
    confidence (structural validity trumps OCR score).

    Returns extract_id_fields() dict plus:
        frames_total, frames_usable, frame_quality_issues
        frame_agreement: {field_name: float}
        low_confidence_fields: [str]  — route to REVIEW if non-empty
        retake_required: True if no usable frame survived quality filter
    """
    usable_frames, assessments = filter_usable_frames(frames)
    quality_issues = [reasons for ok, reasons, _ in assessments if not ok]

    if not usable_frames:
        return {
            'card_detected': False, 'fields': {}, 'national_id_decoded': None,
            'frames_total': len(frames), 'frames_usable': 0,
            'frame_quality_issues': quality_issues, 'frame_agreement': {},
            'low_confidence_fields': [], 'retake_required': True,
        }

    per_frame = [
        extract_id_fields(f, side=side, debug_sink=(debug_sink if i == 0 else None))
        for i, f in enumerate(usable_frames)
    ]
    card_detected = sum(r['card_detected'] for r in per_frame) >= len(per_frame) / 2

    field_names = set()
    for r in per_frame:
        field_names.update(r['fields'].keys())

    fields = {}
    frame_agreement = {}
    for name in field_names:
        readings = [
            (r['fields'][name]['text'], r['fields'][name]['confidence'])
            for r in per_frame if name in r['fields']
        ]
        if name == 'national_id':
            valid_readings = [
                (text, conf) for text, conf in readings
                if decode_national_id(text)['is_valid']
            ]
            if valid_readings:
                readings = valid_readings
        text, confidence, agreement = _consensus(readings)
        fields[name] = {'text': text, 'confidence': confidence}
        frame_agreement[name] = agreement

    low_confidence_fields = [
        name for name, f in fields.items() if f['confidence'] < MIN_FIELD_CONFIDENCE
    ]

    national_id_decoded = None
    if side == 'front' and 'national_id' in fields:
        national_id_decoded = decode_national_id(fields['national_id']['text'])

    return {
        'card_detected': card_detected,
        'fields': fields,
        'national_id_decoded': national_id_decoded,
        'frames_total': len(frames),
        'frames_usable': len(usable_frames),
        'frame_quality_issues': quality_issues,
        'frame_agreement': frame_agreement,
        'low_confidence_fields': low_confidence_fields,
        'retake_required': False,
    }
