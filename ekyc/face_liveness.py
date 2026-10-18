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
Passive liveness / anti-spoofing via Silent-Face-Anti-Spoofing
(minivision-ai, Apache-2.0). Flags printed photos, screen replays, and
masks from a single captured frame.

Vendored under ekyc/vendor/silent_face/: MiniFASNet.py (architecture) and
resources/*.pth (pretrained weights) are theirs verbatim, used under the
Apache-2.0 license (see ekyc/vendor/silent_face/LICENSE). The face-bbox
and ensemble glue code below is ours — we reuse insightface's detector
(ekyc/face_match.py) instead of their bundled RetinaFace Caffe detector,
so the whole pipeline only loads one face detector, and we re-derive
their ToTensor preprocessing inline instead of vendoring their transform
module, since it's the textbook HWC-uint8-[0,255] -> CHW-float-[0,1]
conversion (no proprietary logic).

Decision logic is kept faithful to their reference test.py: both
MiniFASNet models output 3-class softmax (0=fake/print, 1=real,
2=fake/replay); their predictions are summed and the decision is
argmax(summed) == 1 — NOT a flat P(real) >= 0.5 cutoff, which can
disagree with argmax in ambiguous 3-way-close cases. We additionally
expose the raw P(real) probability as a calibrated score for risk fusion,
per the brief's "calibrated score, not just a boolean" requirement.

⚠️ Their reference pipeline assumes a 3:4 (portrait phone camera) capture
aspect ratio — our browser capture flow should aim for that framing;
deviating from it may reduce accuracy. Not benchmarked against Egyptian
ID/selfie captures specifically — see EKYC_MODULE.md's "Known limitations".
"""
import os
import threading

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from ekyc.vendor.silent_face.MiniFASNet import MiniFASNetV1, MiniFASNetV2, MiniFASNetV1SE, MiniFASNetV2SE

_MODEL_MAPPING = {
    'MiniFASNetV1': MiniFASNetV1,
    'MiniFASNetV2': MiniFASNetV2,
    'MiniFASNetV1SE': MiniFASNetV1SE,
    'MiniFASNetV2SE': MiniFASNetV2SE,
}

_MODEL_FILES = ['2.7_80x80_MiniFASNetV2.pth', '4_0_0_80x80_MiniFASNetV1SE.pth']
_SCALE_BY_FILENAME = {'2.7_80x80_MiniFASNetV2.pth': 2.7, '4_0_0_80x80_MiniFASNetV1SE.pth': 4.0}
_VENDOR_RESOURCES = os.path.join(os.path.dirname(__file__), 'vendor', 'silent_face', 'resources')

REAL_CLASS_INDEX = 1

_models = None
_lock = threading.Lock()


def _parse_model_name(filename):
    info = filename.split('_')[0:-1]
    h_input, w_input = (int(v) for v in info[-1].split('x'))
    model_type = filename.split('.pth')[0].split('_')[-1]
    return h_input, w_input, model_type


def _get_kernel(height, width):
    return (height + 15) // 16, (width + 15) // 16


def get_models():
    """Lazily load both MiniFASNet checkpoints (cached for the process lifetime)."""
    global _models
    if _models is None:
        with _lock:
            if _models is None:
                loaded = []
                for filename in _MODEL_FILES:
                    path = os.path.join(_VENDOR_RESOURCES, filename)
                    h_input, w_input, model_type = _parse_model_name(filename)
                    kernel_size = _get_kernel(h_input, w_input)
                    model = _MODEL_MAPPING[model_type](conv6_kernel=kernel_size)
                    state_dict = torch.load(path, map_location='cpu')
                    first_key = next(iter(state_dict))
                    if first_key.startswith('module.'):
                        state_dict = {k[7:]: v for k, v in state_dict.items()}
                    model.load_state_dict(state_dict)
                    model.eval()
                    loaded.append((model, (w_input, h_input)))
                _models = loaded
    return _models


def _get_new_box(src_w, src_h, bbox_xywh, scale):
    x, y, box_w, box_h = bbox_xywh
    scale = min((src_h - 1) / box_h, min((src_w - 1) / box_w, scale))
    new_width, new_height = box_w * scale, box_h * scale
    center_x, center_y = box_w / 2 + x, box_h / 2 + y
    left, top = center_x - new_width / 2, center_y - new_height / 2
    right, bottom = center_x + new_width / 2, center_y + new_height / 2
    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0
    if right > src_w - 1:
        left -= (right - src_w + 1)
        right = src_w - 1
    if bottom > src_h - 1:
        top -= (bottom - src_h + 1)
        bottom = src_h - 1
    return int(left), int(top), int(right), int(bottom)


def _crop_patch(image_bgr, bbox_xywh, scale, out_size):
    src_h, src_w = image_bgr.shape[:2]
    left, top, right, bottom = _get_new_box(src_w, src_h, bbox_xywh, scale)
    patch = image_bgr[top:bottom + 1, left:right + 1]
    return cv2.resize(patch, out_size)


def _to_tensor(patch_bgr):
    # NOTE: the reference implementation's to_tensor has its /255 normalization
    # commented out ("backward compatibility... modify by zkx") despite its
    # docstring still claiming [0,1] output — it actually returns raw [0,255]
    # float values, and the checkpoints were trained against that. Dividing
    # by 255 here (the "obviously correct" thing to do) silently produced
    # wrong predictions on the reference repo's own validated test images.
    arr = patch_bgr.astype(np.float32)
    return torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0)


def check_passive_liveness(image_bgr, bbox_xyxy):
    """
    image_bgr: full captured frame containing a face (BGR, as from cv2/insightface).
    bbox_xyxy: (x1, y1, x2, y2), e.g. from ekyc.face_match.detect_largest_face(...).bbox

    Returns:
        is_live: bool — argmax(summed 3-class softmax) == 'real', matching
            the reference implementation's decision rule exactly
        real_probability: float in [0,1] — calibrated P(real) for risk fusion
        engine: 'silent_face_minifasnet'
    """
    x1, y1, x2, y2 = bbox_xyxy
    bbox_xywh = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))

    summed_probs = np.zeros(3, dtype=np.float64)
    for (model, out_size), filename in zip(get_models(), _MODEL_FILES):
        scale = _SCALE_BY_FILENAME[filename]
        patch = _crop_patch(image_bgr, bbox_xywh, scale, out_size)
        tensor = _to_tensor(patch)
        with torch.no_grad():
            output = model(tensor)
            probs = F.softmax(output, dim=1).numpy()[0]
        summed_probs += probs

    winning_label = int(np.argmax(summed_probs))
    real_probability = float(summed_probs[REAL_CLASS_INDEX] / len(_MODEL_FILES))

    return {
        'is_live': winning_label == REAL_CLASS_INDEX,
        'real_probability': real_probability,
        'engine': 'silent_face_minifasnet',
    }
