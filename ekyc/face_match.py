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
Face matching (selfie vs ID photo) via ArcFace, served by insightface's
buffalo_l pack (SCRFD detector + w600k_r50 ArcFace recognition, ONNX/
onnxruntime — no TensorFlow).

AdaFace was the brief's stated primary choice (purpose-built for low-
quality phone selfies), but both available distributions were unusable
without unacceptable integration risk:
  - The official HF model (minchul/cvlface_adaface_ir50_ms1mv2) ships only
    a thin wrapper class via trust_remote_code — it imports `from models
    import get_model`, code that isn't included in the model repo at all,
    and reads `pretrained_model/model.yaml`/`model.pt` from undocumented
    relative paths. It is not actually self-contained.
  - The original GitHub repo (mk-minchul/AdaFace) has a real, self-
    contained inference.py, but its pretrained weights are Google-Drive-
    only — far less reliable to script than a package registry, and with
    no reference implementation we could run to verify a vendored port is
    bit-exact correct.
ArcFace is the brief's own documented fallback ("the production standard,
mature, MIT-licensed") and is already working cleanly here, so it ships
as the sole engine for v1. Revisit AdaFace if real selfie testing shows
ArcFace isn't robust enough once Emam can provide samples.

Loaded once per worker process (see ekyc/queue.py for why).
"""
import logging
import threading

import numpy as np

logger = logging.getLogger(__name__)

# Cosine similarity threshold for "same person" on insightface's buffalo_l
# (w600k_r50) embeddings. This is a conservative starting point from
# community benchmarks, NOT calibrated against real Egyptian ID/selfie
# pairs — tune once real capture data exists. TODO(B7): make configurable
# like screening_config rather than a code constant.
MATCH_THRESHOLD = 0.42

_face_app = None
_lock = threading.Lock()


def get_face_app():
    """Lazily construct and cache the insightface FaceAnalysis app (detection + recognition only)."""
    global _face_app
    if _face_app is None:
        with _lock:
            if _face_app is None:
                from insightface.app import FaceAnalysis
                logger.info("Loading insightface buffalo_l (detection+recognition) — first call only")
                # root must be set explicitly: insightface's default ('~/.insightface')
                # resolves to the complynex service user's $HOME (/home/complynex), which
                # doesn't exist and isn't writable — same class of crash as
                # ocr_engine.py's EasyOCR reader (PermissionError on mkdir).
                app = FaceAnalysis(name='buffalo_l', allowed_modules=['detection', 'recognition'],
                                    root='/var/www/complynex/ekyc/models/insightface',
                                    providers=['CPUExecutionProvider'])
                app.prepare(ctx_id=-1, det_size=(640, 640))
                _face_app = app
    return _face_app


def detect_largest_face(image_bgr):
    """Returns the insightface Face object with the largest bounding box, or None if no face found."""
    app = get_face_app()
    faces = app.get(image_bgr)
    if not faces:
        return None
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


def get_embedding(image_bgr):
    """Returns (embedding: np.ndarray[512] L2-normalized, face) for the largest detected face, or (None, None)."""
    face = detect_largest_face(image_bgr)
    if face is None:
        return None, None
    return face.normed_embedding, face


def verify(image1_bgr, image2_bgr, threshold=MATCH_THRESHOLD):
    """
    Compare the largest face in each image. Returns a calibrated result,
    not just a boolean:
        is_match: bool
        similarity: float in [-1, 1] (cosine similarity of L2-normalized embeddings)
        threshold: float used for this comparison
        engine: 'arcface_insightface'
        error: str | None — set if a face couldn't be found in either image
    """
    embedding1, face1 = get_embedding(image1_bgr)
    embedding2, face2 = get_embedding(image2_bgr)

    if embedding1 is None or embedding2 is None:
        missing = []
        if embedding1 is None:
            missing.append('image1')
        if embedding2 is None:
            missing.append('image2')
        return {
            'is_match': False, 'similarity': None, 'threshold': threshold,
            'engine': 'arcface_insightface', 'error': f"no face detected in: {', '.join(missing)}",
        }

    similarity = float(np.dot(embedding1, embedding2))
    return {
        'is_match': similarity >= threshold,
        'similarity': similarity,
        'threshold': threshold,
        'engine': 'arcface_insightface',
        'error': None,
    }
