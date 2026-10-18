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
Card detection + perspective correction for the ID capture flow.

Given a single video frame (or photo) that contains an ID card at some
angle, find its quadrilateral boundary and warp it to a canonical
fronto-parallel rectangle so that ekyc.id_layout's fixed field boxes line
up regardless of how the card was held.
"""
import logging

import cv2
import numpy as np

from ekyc.id_layout import CANONICAL_WIDTH, CANONICAL_HEIGHT

logger = logging.getLogger(__name__)

_MIN_AREA_FRACTION = 0.15
_MAX_AREA_FRACTION = 0.98
_CARD_ASPECT_RATIO = 85.60 / 53.98


def _order_corners(pts):
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    top_left = pts[np.argmin(s)]
    bottom_right = pts[np.argmax(s)]
    top_right = pts[np.argmin(diff)]
    bottom_left = pts[np.argmax(diff)]
    return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)


def find_card_corners(image):
    """
    Locate the largest card-like quadrilateral in image (BGR np.ndarray).
    Uses a robust Largest Contour approach to handle angles, glares, and 
    broken edges on real phone cameras.
    """
    h, w = image.shape[:2]
    frame_area = h * w

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    edges = cv2.Canny(blurred, 30, 150)
    
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    edges = cv2.dilate(edges, kernel, iterations=1)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Rank candidates by their rotated bounding-box area (see note below on
    # why box_area beats cv2.contourArea), not the raw contour area — a
    # broken-edge card contour can rank well outside the top 5 by raw area
    # while still tightly bounding the card.
    def _box_area(contour):
        (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
        return rw * rh

    contours = sorted(contours, key=_box_area, reverse=True)[:8]

    for contour in contours:
        rect = cv2.minAreaRect(contour)
        (cx, cy), (rw, rh), angle = rect

        if rw == 0 or rh == 0:
            continue

        # Use the rotated bounding box's area, not cv2.contourArea(contour):
        # real phone captures produce broken/glare-interrupted Canny edges, so
        # the traced contour is often a sparse outline whose shoelace-formula
        # area is tiny even though it clearly bounds a card-sized region —
        # contourArea was rejecting genuine card contours because of this.
        box_area = rw * rh
        if not (_MIN_AREA_FRACTION * frame_area <= box_area <= _MAX_AREA_FRACTION * frame_area):
            continue

        if rw < rh:
            rw, rh = rh, rw

        aspect_ratio = rw / rh

        if 1.2 < aspect_ratio < 2.2:
            box = cv2.boxPoints(rect)
            return _order_corners(box)

    return None


def correct_perspective(image, corners=None):
    """
    Warp image so the card fills a canonical rectangle.
    """
    if corners is None:
        corners = find_card_corners(image)

    if corners is None:
        logger.warning("Card boundary not detected — falling back to plain resize")
        return cv2.resize(image, (CANONICAL_WIDTH, CANONICAL_HEIGHT)), False

    destination = np.array([
        [0, 0],
        [CANONICAL_WIDTH - 1, 0],
        [CANONICAL_WIDTH - 1, CANONICAL_HEIGHT - 1],
        [0, CANONICAL_HEIGHT - 1],
    ], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(corners, destination)
    warped = cv2.warpPerspective(image, matrix, (CANONICAL_WIDTH, CANONICAL_HEIGHT))
    return warped, True
