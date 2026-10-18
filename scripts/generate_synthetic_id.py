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
Generates a synthetic Egyptian-ID-style test card with KNOWN ground-truth
text, for testing the OCR/validator pipeline plumbing only.

⚠️ This is NOT a substitute for real samples. Rendered text (clean font,
flat background, no glare/lamination/security pattern/compression noise)
is far easier to OCR than a phone photo of a real card. A pipeline that
passes this test proves the code path works end-to-end; it says nothing
about real-world accuracy. See ekyc/id_layout.py's calibration warning.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ekyc.id_layout import CANONICAL_WIDTH, CANONICAL_HEIGHT, FRONT_FIELDS, BACK_FIELDS  # noqa: E402

ARABIC_FONT_PATH = '/usr/share/fonts/opentype/fonts-hosny-amiri/Amiri-Regular.ttf'
LATIN_FONT_PATH = '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'

GROUND_TRUTH = {
    'full_name': 'أحمد محمد علي حسن',
    'address': '15 شارع النصر مدينة نصر القاهرة',
    'national_id': '29005150123415',  # valid: male, born 1990-05-15, Cairo (see ekyc/national_id.py tests)
}

BACK_GROUND_TRUTH = {
    'occupation': 'مهندس',
    'marital_status': 'أعزب',
    'gender': 'ذكر',
    'expiry_date': '15-05-2030',
}


def generate_canonical_card(face_image_bgr=None):
    """
    A flat, front-on rendering of the card with no perspective distortion.
    face_image_bgr: optional real face crop (np.ndarray, BGR) to paste into
    the photo region instead of a flat placeholder — needed to test face
    matching end-to-end, since a gray rectangle has no detectable face.
    """
    img = Image.new('RGB', (CANONICAL_WIDTH, CANONICAL_HEIGHT), color=(245, 245, 240))
    draw = ImageDraw.Draw(img)

    # Photo region: either a real face crop (for face-match testing) or a flat placeholder.
    x0, y0, x1, y1 = [round(v * CANONICAL_WIDTH if i % 2 == 0 else v * CANONICAL_HEIGHT)
                       for i, v in enumerate(FRONT_FIELDS['photo'])]
    if face_image_bgr is not None:
        face_rgb = face_image_bgr[:, :, ::-1]
        face_pil = Image.fromarray(face_rgb).resize((x1 - x0, y1 - y0))
        img.paste(face_pil, (x0, y0))
    else:
        draw.rectangle([x0, y0, x1, y1], fill=(200, 200, 200), outline=(120, 120, 120))

    arabic_font = ImageFont.truetype(ARABIC_FONT_PATH, 30)
    latin_font = ImageFont.truetype(LATIN_FONT_PATH, 34)

    def box_px(name):
        fx0, fy0, fx1, fy1 = FRONT_FIELDS[name]
        return round(fx0 * CANONICAL_WIDTH), round(fy0 * CANONICAL_HEIGHT), \
            round(fx1 * CANONICAL_WIDTH), round(fy1 * CANONICAL_HEIGHT)

    nx0, ny0, nx1, ny1 = box_px('full_name')
    draw.text((nx1 - 10, ny0 + 10), GROUND_TRUTH['full_name'], font=arabic_font,
               fill=(20, 20, 20), direction='rtl', anchor='ra')

    ax0, ay0, ax1, ay1 = box_px('address')
    draw.text((ax1 - 10, ay0 + 10), GROUND_TRUTH['address'], font=arabic_font,
               fill=(20, 20, 20), direction='rtl', anchor='ra')

    idx0, idy0, idx1, idy1 = box_px('national_id')
    draw.text((idx0 + 10, idy0 + 10), GROUND_TRUTH['national_id'], font=latin_font, fill=(0, 0, 0))

    return np.array(img)[:, :, ::-1]  # RGB -> BGR for OpenCV consumers


def generate_canonical_back_card():
    """
    A flat, front-on rendering of the back side (occupation/marital status/
    gender/expiry date — ekyc/id_layout.py's BACK_FIELDS). No photo region
    on this side of a real Egyptian national ID.
    """
    img = Image.new('RGB', (CANONICAL_WIDTH, CANONICAL_HEIGHT), color=(245, 245, 240))
    draw = ImageDraw.Draw(img)
    arabic_font = ImageFont.truetype(ARABIC_FONT_PATH, 30)

    def box_px(name):
        fx0, fy0, fx1, fy1 = BACK_FIELDS[name]
        return round(fx0 * CANONICAL_WIDTH), round(fy0 * CANONICAL_HEIGHT), \
            round(fx1 * CANONICAL_WIDTH), round(fy1 * CANONICAL_HEIGHT)

    for name, text in BACK_GROUND_TRUTH.items():
        x0, y0, x1, _ = box_px(name)
        draw.text((x1 - 10, y0 + 10), text, font=arabic_font, fill=(20, 20, 20), direction='rtl', anchor='ra')

    return np.array(img)[:, :, ::-1]  # RGB -> BGR for OpenCV consumers


def generate_photographed_scene(canonical_bgr, angle_degrees=8, scale=0.8):
    """
    Place the canonical card onto a larger neutral background with a
    perspective skew, simulating a card held at a slight angle in front
    of a phone camera, to exercise document_capture's corner detection.
    """
    import cv2

    h, w = canonical_bgr.shape[:2]
    scene_w, scene_h = round(w / scale * 1.3), round(h / scale * 1.3)
    scene = np.full((scene_h, scene_w, 3), 180, dtype=np.uint8)

    cx, cy = scene_w / 2, scene_h / 2
    half_w, half_h = (w * scale) / 2, (h * scale) / 2

    theta = np.radians(angle_degrees)
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    corners_dst = []
    for sx, sy in [(-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h)]:
        rx = sx * cos_t - sy * sin_t
        ry = sx * sin_t + sy * cos_t
        corners_dst.append([cx + rx, cy + ry])
    corners_dst = np.array(corners_dst, dtype=np.float32)

    corners_src = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(corners_src, corners_dst)
    warped_card = cv2.warpPerspective(canonical_bgr, matrix, (scene_w, scene_h),
                                       borderMode=cv2.BORDER_TRANSPARENT)

    mask = np.zeros((scene_h, scene_w), dtype=np.uint8)
    import cv2 as _cv2
    _cv2.fillConvexPoly(mask, corners_dst.astype(np.int32), 255)
    scene[mask > 0] = warped_card[mask > 0]
    return scene


def simulate_screen_replay(canonical_bgr, grid_period_px=3.3, angle_degrees=7):
    """
    Simulates photographing a screen displaying the card image: modulates
    brightness with a fine periodic grid (the screen's pixel structure) at
    an angle/period that doesn't align with the image's own pixel grid,
    which is what produces moire interference fringes when re-sampled by
    a camera sensor.
    """
    h, w = canonical_bgr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    theta = np.radians(angle_degrees)
    rotated_x = xx * np.cos(theta) + yy * np.sin(theta)
    pattern = 0.55 + 0.45 * np.sin(2 * np.pi * rotated_x / grid_period_px)
    modulated = (canonical_bgr.astype(np.float32) * pattern[:, :, None]).clip(0, 255).astype(np.uint8)
    return modulated


def _add_specular_highlight(scene_bgr, angle_degrees):
    """
    Simulates a hologram/security-feature reflection: a bright spot near
    where the photo placeholder sits, whose position shifts as the
    simulated tilt angle changes — standing in for how a real holographic
    foil's reflection moves and changes intensity as viewing angle changes.
    """
    h, w = scene_bgr.shape[:2]
    cx, cy = w * 0.3, h * 0.45
    shift = angle_degrees * 3
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - (cx + shift)) ** 2 + (yy - cy) ** 2)
    intensity = np.clip(1 - dist / 40, 0, 1) * 180
    highlighted = scene_bgr.astype(np.float32) + intensity[:, :, None]
    return highlighted.clip(0, 255).astype(np.uint8)


def generate_tilt_sequence(canonical_bgr, num_frames=5, with_hologram=True):
    """
    A sequence of frames sweeping through a range of tilt angles, as the
    capture UI instructs the user to do with the physical card.
    with_hologram=True adds a simulated angle-dependent reflective
    highlight (standing in for a genuine card's security feature);
    with_hologram=False produces a sequence representing a flat
    printout/screen replay, where nothing changes beyond ordinary
    perspective distortion.
    """
    frames = []
    for i in range(num_frames):
        angle = -10 + (20 * i / (num_frames - 1))
        scene = generate_photographed_scene(canonical_bgr, angle_degrees=angle)
        if with_hologram:
            scene = _add_specular_highlight(scene, angle)
        frames.append(scene)
    return frames


if __name__ == '__main__':
    canonical = generate_canonical_card()
    Image.fromarray(canonical[:, :, ::-1]).save('/tmp/synthetic_id_canonical.png')
    print("Wrote /tmp/synthetic_id_canonical.png")

    scene = generate_photographed_scene(canonical)
    Image.fromarray(scene[:, :, ::-1]).save('/tmp/synthetic_id_scene.png')
    print("Wrote /tmp/synthetic_id_scene.png")
