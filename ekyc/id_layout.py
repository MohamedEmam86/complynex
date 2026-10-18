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
Fixed-layout field positions for the Egyptian National ID card.

We deliberately avoid an ML object detector (YOLO) for field localization
per the project's licensing decision (Ultralytics YOLO is AGPL-3.0) — the
Egyptian National ID has a fixed, standardized ID-1 card layout, so a
perspective-corrected card image can be cropped with fixed fractional
boxes instead of running a detector.

⚠️ CALIBRATION WARNING — READ BEFORE TRUSTING THESE NUMBERS:
The fractional boxes below are best-effort estimates based on the publicly
known general layout of the post-2017 Egyptian smart national ID (photo
on one side, labeled Arabic fields on the other, national number along the
bottom). They have NOT been measured against a real card. This is
the single highest-value thing for Emam to provide next: even 5-10 real
(or realistic mock/expired) ID photos would let these boxes be measured
precisely instead of guessed. Until then, treat OCR field accuracy as
unverified — the capture design (video + multiple frames) and the
national-ID cross-check (ekyc/national_id.py) are what keep this layer
useful even with imperfect crops, by catching and correcting errors
rather than depending on crop precision alone.
"""

# ISO/IEC 7810 ID-1 card aspect ratio (width:height = 85.60mm : 53.98mm)
CARD_ASPECT_RATIO = 85.60 / 53.98

# Canonical size we warp every captured card frame to before cropping fields,
# chosen for a reasonable balance of OCR legibility vs memory/CPU cost.
CANONICAL_WIDTH = 1011
CANONICAL_HEIGHT = round(CANONICAL_WIDTH / CARD_ASPECT_RATIO)  # ~638

# Fractional boxes (x0, y0, x1, y1), each in [0, 1] of (CANONICAL_WIDTH, CANONICAL_HEIGHT).
# RTL layout: photo on the left third, labeled fields on the right two-thirds.
FRONT_FIELDS = {
    'full_name': (0.34, 0.18, 0.97, 0.36),
    'address': (0.34, 0.40, 0.97, 0.62),
    # Calibrated against a real card (eKYC session #80): the printed 14-digit
    # ID number sits at ~0.72-0.84 of card height, well above the bottom
    # serial-number strip (~0.88-0.98) that the previous box was actually
    # capturing instead. x0=0.34 (not 0.05) keeps the handwritten DOB stamp
    # under the photo out of the crop.
    'national_id': (0.34, 0.72, 0.98, 0.84),
    'id_serial': (0.05, 0.88, 0.40, 0.99),
    'photo': (0.02, 0.12, 0.30, 0.78),
}

BACK_FIELDS = {
    'occupation': (0.34, 0.10, 0.97, 0.24),
    'marital_status': (0.34, 0.26, 0.97, 0.40),
    'gender': (0.34, 0.42, 0.97, 0.56),
    'expiry_date': (0.34, 0.58, 0.97, 0.72),
}


def crop_fields(corrected_image, side='front'):
    """
    corrected_image: HxWx3 array already perspective-corrected to
    (CANONICAL_HEIGHT, CANONICAL_WIDTH) by ekyc.document_capture.correct_perspective.

    Returns {field_name: cropped_image_array}.
    """
    fields = FRONT_FIELDS if side == 'front' else BACK_FIELDS
    h, w = corrected_image.shape[:2]
    crops = {}
    for name, (x0, y0, x1, y1) in fields.items():
        crops[name] = corrected_image[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)]
    return crops
