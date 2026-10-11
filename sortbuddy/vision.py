"""Find a card in a camera frame and flatten it to a standard upright image.

Works best with the card on a plain, dark, non-glossy background (a playmat
works well). Fingers covering a corner are tolerated as long as most of the
card's outline is visible.
"""

from __future__ import annotations

import cv2
import numpy as np

# Standard TCG card is 63 x 88 mm. Warped cards are rendered at this size.
CARD_W, CARD_H = 315, 440
CARD_ASPECT = CARD_H / CARD_W  # ~1.397
# Cards are cut out of the full-resolution frame at this size: enough detail
# to read the small print. Fingerprinting shrinks them back down.
WARP_W, WARP_H = 2 * CARD_W, 2 * CARD_H


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Return corners ordered top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        dtype=np.float32,
    )


def _quad(contour: np.ndarray) -> np.ndarray:
    """Simplify a contour to 4 corners."""
    hull = cv2.convexHull(contour)
    peri = cv2.arcLength(hull, True)
    for eps in (0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype(np.float32)
    # Fingers or glare broke the outline; fall back to the rotated bounding box.
    return cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32)


def find_card(frame: np.ndarray, min_area_frac: float = 0.05) -> np.ndarray | None:
    """Locate the largest card-shaped quadrilateral. Returns 4 corners or None."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 30, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    frame_area = gray.shape[0] * gray.shape[1]
    best, best_area = None, 0.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area_frac * frame_area or area <= best_area:
            continue
        quad = _quad(c)
        (w, h) = cv2.minAreaRect(quad)[1]
        if min(w, h) == 0:
            continue
        aspect = max(w, h) / min(w, h)
        if abs(aspect - CARD_ASPECT) > 0.25:
            continue
        best, best_area = quad, area
    return None if best is None else order_corners(best)


def warp_card(frame: np.ndarray, corners: np.ndarray, size: tuple[int, int] = (WARP_W, WARP_H)) -> np.ndarray:
    """Perspective-correct the card to an upright portrait image of `size`."""
    tl, tr, br, bl = corners
    top = np.linalg.norm(tr - tl)
    left = np.linalg.norm(bl - tl)
    if top > left:
        # Card is lying sideways; rotate the corner order so the long edge is vertical.
        corners = np.array([tr, br, bl, tl], dtype=np.float32)
    w, h = size
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(frame, m, (w, h))


def extract_card(frame: np.ndarray, detect_width: int = 960) -> tuple[np.ndarray, np.ndarray] | None:
    """Find and warp the card in one go. Returns (warped, corners) or None.

    The outline is found on a downscaled copy (fast, and edge detection is
    tuned for roughly this size); the card is then cut from the full frame.
    """
    scale = min(1.0, detect_width / frame.shape[1])
    small = frame if scale == 1.0 else cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    corners = find_card(small)
    if corners is None:
        return None
    corners = corners / scale
    return warp_card(frame, corners), corners
