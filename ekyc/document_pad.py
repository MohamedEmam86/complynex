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
Document presentation-attack detection (PAD): catches obvious printed
copies and screen replays of an ID card.

Per the brief, this is explicitly "the hardest layer and research-grade."
No real spoof OR genuine Egyptian ID samples exist yet — everything here
is grounded in well-documented physical/optical principles and validated
only against synthetic test cases (scripts/test_document_pad.py), which
prove the mechanics work, not real-world accuracy. Treat this layer's
output as ONE weighted signal in B7's risk fusion, never a standalone
gate, until real samples allow proper calibration and validation.

Two independent signals, combined via simple transparent voting (not a
trained classifier — there's no labeled data to train one on):

  1. Moire detection (single frame, frequency-domain): photographing a
     screen creates interference between the screen's pixel grid and the
     camera's sensor grid, visible as periodic fringe peaks in the
     image's frequency spectrum. A genuine printed/physical document
     doesn't produce this.

  2. Reflection/hologram variance (multi-frame, the capture's tilt
     sequence): genuine Egyptian ID cards carry holographic/reflective
     security features whose brightness changes with viewing angle. A
     flat printout or screen replay does not exhibit this once frames
     are perspective-corrected to the same canonical rectangle (removing
     ordinary geometric perspective change) — residual per-pixel
     brightness variance across the tilt sequence is the candidate
     "genuine card" signal.
"""
import cv2
import numpy as np

from ekyc.document_capture import correct_perspective

# ---- Signal 1: Moire (frequency-domain) ----

MOIRE_CENTER_MASK_FRACTION = 0.04   # fraction of image diagonal excluded as "DC/low-frequency content"
MOIRE_PEAK_ZSCORE_THRESHOLD = 6.0   # std-devs above the band mean to count as an anomalous peak
MOIRE_PEAK_COUNT_THRESHOLD = 12     # number of such peaks before flagging a frame suspicious


def detect_moire(image_bgr):
    """Frequency-domain check for screen-replay interference patterns on a single frame."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    spectrum = np.fft.fftshift(np.fft.fft2(gray))
    magnitude = np.log1p(np.abs(spectrum))

    h, w = magnitude.shape
    cy, cx = h // 2, w // 2
    yy, xx = np.mgrid[0:h, 0:w]
    radius = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    diagonal = np.sqrt(h ** 2 + w ** 2) / 2
    high_freq_mask = radius > (MOIRE_CENTER_MASK_FRACTION * diagonal)

    band = magnitude[high_freq_mask]
    band_mean, band_std = float(band.mean()), float(band.std())
    if band_std == 0:
        return {'moire_score': 0, 'is_suspicious': False}

    z_scores = (magnitude - band_mean) / band_std
    peak_count = int(np.sum((z_scores > MOIRE_PEAK_ZSCORE_THRESHOLD) & high_freq_mask))

    return {
        'moire_score': peak_count,
        'is_suspicious': peak_count > MOIRE_PEAK_COUNT_THRESHOLD,
    }


# ---- Signal 2: reflection/hologram variance across a tilt sequence ----

REFLECTION_VARIANCE_PERCENTILE = 99.0
# Std-dev units on a 0-255 brightness scale. NOT calibrated against a real
# hologram — purely a starting guess pending real capture data.
REFLECTION_SCORE_THRESHOLD = 18.0


def detect_reflection_variance(corrected_frames_bgr):
    """
    corrected_frames_bgr: frames already perspective-corrected to the same
    canonical rectangle (ekyc.document_capture.correct_perspective),
    ideally captured while the user tilts the card per the capture UI's
    instructions (see static/ekyc/js/capture.js).
    """
    if len(corrected_frames_bgr) < 3:
        return {'reflection_score': None, 'is_suspicious': None,
                'error': 'need at least 3 frames to measure variance across a tilt sequence'}

    stack = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in corrected_frames_bgr])
    per_pixel_std = stack.std(axis=0)
    score = float(np.percentile(per_pixel_std, REFLECTION_VARIANCE_PERCENTILE))

    return {
        'reflection_score': score,
        'is_suspicious': score < REFLECTION_SCORE_THRESHOLD,
    }


# ---- Fusion ----

# Moire's absolute threshold is validated (synthetic screen-replay
# reliably crosses it, clean cards reliably don't — see
# scripts/test_document_pad.py). Reflection-variance's absolute threshold
# is an honest placeholder pending real calibration data — only its
# *relative* ordering (genuine > flat) is validated. Weight accordingly:
# moire alone is enough to drop the score below the pass line; reflection
# alone is not, until it's been calibrated.
MOIRE_WEIGHT = 0.7
REFLECTION_WEIGHT = 0.3


def assess_document_pad(raw_frames_bgr):
    """
    raw_frames_bgr: the captured ID frames (not yet perspective-corrected).

    Moire is detected on the RAW frames, not the perspective-corrected
    ones: it's a fine, high-frequency pattern, and warpPerspective's
    resampling (interpolation acts as a mild low-pass filter, especially
    under scaling) measurably attenuates it — detecting it as close to
    the original camera-captured pixels as possible matters here. The
    reflection-variance check, in contrast, NEEDS the corrected/aligned
    frames, since it compares the same physical location across frames.

    Returns document_pad_score (0-100, higher = more confident it's a
    genuine physical document) and document_pad_pass, plus the
    constituent signals for transparency/audit.
    """
    moire_results = [detect_moire(f) for f in raw_frames_bgr]
    moire_suspicious_count = sum(1 for r in moire_results if r['is_suspicious'])
    moire_flag = moire_suspicious_count > len(moire_results) / 2

    corrected = [correct_perspective(f)[0] for f in raw_frames_bgr]
    reflection_result = detect_reflection_variance(corrected)
    reflection_flag = reflection_result.get('is_suspicious') is True

    score = 100.0 * (1 - (MOIRE_WEIGHT * moire_flag + REFLECTION_WEIGHT * reflection_flag))

    return {
        'document_pad_score': score,
        'document_pad_pass': score >= 50.0,
        'moire_flag': moire_flag,
        'moire_suspicious_frame_count': moire_suspicious_count,
        'reflection_flag': reflection_flag,
        'reflection_score': reflection_result.get('reflection_score'),
        'frames_analyzed': len(corrected),
    }
