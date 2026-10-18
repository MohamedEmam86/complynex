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
OCR engine for reading text out of cropped ID-card fields.

Engine choice: EasyOCR only. We planned to benchmark EasyOCR against
PaddleOCR per the original brief, but PaddlePaddle has no published wheel
for Python 3.14 (this server's interpreter) at all — confirmed against
PyPI's actual file listing, not just a local install failure. EasyOCR
installs and runs cleanly (it reuses the CPU PyTorch already on this box).
There is therefore no second engine as a fallback for v1; if EasyOCR's
real-world Arabic accuracy proves insufficient once real ID samples are
available, revisit (e.g. a Python 3.12 venv dedicated to the eKYC worker
process, which already runs isolated from the web app — see ekyc/worker.py).

Loaded once per worker process (the eKYC worker, never the web workers —
see ekyc/queue.py for why) and reused across jobs.
"""
import logging
import threading

logger = logging.getLogger(__name__)

_reader = None
_lock = threading.Lock()


def get_reader():
    """
    Lazily construct and cache the EasyOCR reader (Arabic + English, CPU).

    Fine-tuning hook: once real Egyptian ID samples are available, EasyOCR
    supports loading a custom-trained recognition network via the
    `recog_network` + `model_storage_directory` constructor arguments
    (see EasyOCR's custom-model training docs). This is the only place in
    the codebase that constructs the reader, so swapping in a fine-tuned
    model later is a one-line change here — nothing else in the pipeline
    needs to change.
    """
    global _reader
    if _reader is None:
        with _lock:
            if _reader is None:
                import easyocr
                logger.info("Loading EasyOCR reader (ar+en, CPU) — first call only")
                # Both directories must be set explicitly: EasyOCR's own default
                # for user_network_directory falls back to ~/.EasyOCR, and the
                # eKYC worker runs as the `complynex` service user whose $HOME
                # (/home/complynex) doesn't exist and isn't writable — leaving
                # this unset crashes the whole pipeline on first OCR call
                # (PermissionError trying to mkdir '/home/complynex').
                _reader = easyocr.Reader(
                    ['ar', 'en'], gpu=False, verbose=False,
                    model_storage_directory='/var/www/complynex/ekyc/models/easyocr',
                    user_network_directory='/var/www/complynex/ekyc/models/easyocr/user_network',
                )
    return _reader


def read_text(image, rtl=True, debug_sink=None):
    """
    Run OCR on a cropped field image (np.ndarray, BGR or grayscale).

    EasyOCR has no concept of script direction: it sorts detected text
    boxes left-to-right regardless of content, which silently scrambles
    word order for Arabic (e.g. a name detected as two boxes comes back
    in the wrong order). Since our field crops are single-line, sorting
    boxes by x-position — descending for RTL fields, ascending for LTR
    fields like the national ID digits — recovers correct reading order.

    This also affects the *inside* of a single box: when the 'ar' model
    detects several digit clusters close enough together to land in one
    box (e.g. the national ID's "286 08 22 21"), it still shapes/joins
    them as if laying out an RTL line, so the clusters come back reversed
    within that one box's text ("21 22 08 86") even though the field as a
    whole is read left-to-right. For LTR fields we therefore also reverse
    the space-separated clusters inside each box before joining.

    Returns (text, confidence): confidence is the mean of EasyOCR's
    per-detection confidence scores (0.0 if nothing detected).

    debug_sink: if given a list, every raw EasyOCR detection (text +
    confidence, before the join/sort above) is appended to it — lets a
    caller log/inspect exactly what the engine saw, not just the final
    joined string, without changing this function's normal return value.
    """
    reader = get_reader()
    detections = reader.readtext(image, detail=1)
    if debug_sink is not None:
        debug_sink.extend({'text': d[1], 'confidence': float(d[2])} for d in detections)
    if not detections:
        return '', 0.0
    detections.sort(key=lambda d: d[0][0][0], reverse=rtl)
    if rtl:
        texts = [d[1] for d in detections]
    else:
        texts = [' '.join(reversed(d[1].split())) for d in detections]
    confidences = [d[2] for d in detections]
    return ' '.join(texts).strip(), sum(confidences) / len(confidences)
