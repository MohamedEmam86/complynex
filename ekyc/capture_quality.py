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
Capture-quality guard: cheap per-frame checks (resolution, blur, brightness,
glare) run BEFORE OCR. A hopeless frame wastes OCR time and can quietly
drag down a multi-frame consensus, so it's filtered out here instead; if
every frame in a clip fails, the caller should ask the user to retake
rather than attempt to extract anything.

These thresholds are heuristic starting points, not calibrated against
real captures (no real ID footage exists yet — see id_layout.py's
calibration warning, the same caveat applies here). Expect to tune them
once real capture samples are available.
"""
import cv2

MIN_WIDTH = 640
MIN_HEIGHT = 400
MIN_LAPLACIAN_VARIANCE = 60.0     # below this -> blurry
MIN_MEAN_BRIGHTNESS = 40.0        # below this -> too dark
MAX_MEAN_BRIGHTNESS = 235.0       # above this -> overexposed
MAX_GLARE_PIXEL_FRACTION = 0.12   # fraction of near-blown-out pixels -> glare/reflection


def assess_frame(frame_bgr):
    """Returns (is_usable: bool, reasons: list[str], metrics: dict)."""
    reasons = []
    h, w = frame_bgr.shape[:2]
    if w < MIN_WIDTH or h < MIN_HEIGHT:
        reasons.append(f'resolution too low ({w}x{h}, need at least {MIN_WIDTH}x{MIN_HEIGHT})')

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if laplacian_var < MIN_LAPLACIAN_VARIANCE:
        reasons.append(f'image too blurry (sharpness={laplacian_var:.1f})')

    mean_brightness = float(gray.mean())
    if mean_brightness < MIN_MEAN_BRIGHTNESS:
        reasons.append(f'image too dark (brightness={mean_brightness:.1f})')
    elif mean_brightness > MAX_MEAN_BRIGHTNESS:
        reasons.append(f'image overexposed (brightness={mean_brightness:.1f})')

    glare_fraction = float((gray > 250).mean())
    if glare_fraction > MAX_GLARE_PIXEL_FRACTION:
        reasons.append(f'glare/reflection detected ({glare_fraction:.0%} of pixels blown out)')

    metrics = {
        'width': w, 'height': h,
        'sharpness': laplacian_var,
        'brightness': mean_brightness,
        'glare_fraction': glare_fraction,
    }
    return len(reasons) == 0, reasons, metrics


def filter_usable_frames(frames):
    """Returns (usable_frames, assessments) — assessments cover ALL input frames, in order."""
    assessments = [assess_frame(f) for f in frames]
    usable = [f for f, (ok, _, _) in zip(frames, assessments) if ok]
    return usable, assessments
