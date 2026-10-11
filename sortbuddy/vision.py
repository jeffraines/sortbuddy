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
# A card never fills more than this share of the picture; anything bigger
# (the floor of a box, a playmat) is the surroundings.
MAX_CARD_FRAC = 0.5

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


def _card_shaped(quad: np.ndarray, contour_area: float) -> bool:
    """A real card seen from above is close to a rectangle: square-ish
    corners, equal opposite sides, and its outline fills the box. Two
    overlapping cards make a lopsided outline that fails this."""
    q = order_corners(quad)
    sides = [np.linalg.norm(q[(i + 1) % 4] - q[i]) for i in range(4)]
    if min(sides) == 0:
        return False
    if max(sides[0], sides[2]) / min(sides[0], sides[2]) > 1.3:
        return False
    if max(sides[1], sides[3]) / min(sides[1], sides[3]) > 1.3:
        return False
    for i in range(4):
        u, v = q[i - 1] - q[i], q[(i + 1) % 4] - q[i]
        cos = abs(float(np.dot(u, v))) / (np.linalg.norm(u) * np.linalg.norm(v))
        if cos > 0.34:  # more than ~20 degrees off square
            return False
    quad_area = cv2.contourArea(q)
    # The outline should fill the 4-corner box almost exactly: overlapping
    # cards stick out of it (> 1) or leave notches (< 1).
    return quad_area > 0 and 0.85 < contour_area / quad_area < 1.05


def _straight(contour: np.ndarray, quad: np.ndarray, area: float) -> bool:
    """A card's edges are straight lines; the outline of a stack has steps
    where the cards underneath stick out. Simulated: a single card's outline
    stays within ~0.4% of its size of the fitted rectangle (90% of points),
    a stack's strays 1.3-6%."""
    pts = contour.reshape(-1, 2)[::2].astype(np.float32)
    poly = order_corners(quad).reshape(-1, 1, 2)
    dev = np.array([abs(cv2.pointPolygonTest(poly, (float(x), float(y)), True)) for x, y in pts])
    return float(np.percentile(dev, 90)) <= 0.008 * np.sqrt(area)


def find_card_checked(frame: np.ndarray, min_area_frac: float = 0.05) -> tuple[np.ndarray | None, str]:
    """Locate the (top) card. Returns (corners or None, note), note being:

    ""         a clean card outline
    "rough"    no clean outline (e.g. a messy stack, overlapping cards):
               the corners are a best guess, so only trust what can be read
               off the card, not a picture match
    "several"  separate cards side by side; the largest is returned

    Cards in a stack or overlapping each other merge into one blob, but the
    top card's own edge (or its printed frame) still forms a clean rectangle
    inside it, so outlines inside blobs are searched as well.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 30, 120)
    # Only slightly thickened edges: thickening more merges the top card's
    # edge with the cards under it (simulated stacks: 75/80 top cards found
    # this way vs ~10% with the old, thicker edges).
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, hierarchy = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return None, ""

    frame_area = gray.shape[0] * gray.shape[1]
    fh, fw = gray.shape
    clean, rough, biggest_blob = [], None, 0.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area_frac * frame_area or area > MAX_CARD_FRAC * frame_area:
            continue  # too small, or too big to be a card (e.g. the floor of a box)
        x, y, bw, bh = cv2.boundingRect(c)
        if x <= 2 or y <= 2 or x + bw >= fw - 3 or y + bh >= fh - 3:
            continue  # runs off the picture: box walls, the table edge, a hand
        quad = _quad(c)
        (w, h) = cv2.minAreaRect(quad)[1]
        if min(w, h) == 0:
            continue
        aspect = max(w, h) / min(w, h)
        # The biggest card-sized shape (e.g. a whole small stack) is the fallback
        # when no clean outline is found. Not just outermost shapes: in a box,
        # the outermost one is the box floor, already skipped above.
        biggest_blob = max(biggest_blob, area)
        if abs(aspect - CARD_ASPECT) <= 0.35 and (rough is None or area > rough[0]):
            rough = (area, quad)
        hull_area = cv2.contourArea(cv2.convexHull(c))
        solid = hull_area > 0 and area / hull_area > 0.975  # no dents (two overlapping cards: <= 0.97)
        if abs(aspect - CARD_ASPECT) <= 0.25 and solid and _card_shaped(quad, area) and _straight(c, quad, area):
            clean.append((area, quad))

    # A clean outline must be a good part of the biggest shape: the top card of
    # a stack is, a card's art box (also a rectangle) isn't.
    clean = [(a, q) for a, q in clean if a >= 0.45 * biggest_blob]
    if clean:
        clean.sort(key=lambda x: -x[0])
        area, quad = clean[0]
        centre = quad.mean(axis=0)
        apart = [q for a, q in clean[1:] if 0.6 < a / area and
                 np.linalg.norm(q.mean(axis=0) - centre) > 0.5 * np.sqrt(area)]
        return order_corners(quad), ("several" if apart else "")
    if rough is not None:
        return order_corners(rough[1]), "rough"
    return None, ""


def find_card(frame: np.ndarray, min_area_frac: float = 0.05) -> np.ndarray | None:
    """Locate the card in view. Returns 4 corners or None."""
    return find_card_checked(frame, min_area_frac)[0]


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


def extract_card_checked(frame: np.ndarray, detect_width: int = 960):
    """Find and warp the card. Returns ((warped, corners) or None, problem).

    The outline is found on a downscaled copy (fast, and edge detection is
    tuned for roughly this size); the card is then cut from the full frame.
    """
    scale = min(1.0, detect_width / frame.shape[1])
    small = frame if scale == 1.0 else cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    corners, note = find_card_checked(small)
    if corners is None:
        return None, note
    corners = corners / scale
    return (warp_card(frame, corners), corners), note


def extract_card(frame: np.ndarray, detect_width: int = 960) -> tuple[np.ndarray, np.ndarray] | None:
    """Find and warp the card in one go. Returns (warped, corners) or None.
    Only clean outlines; use extract_card_checked to also get rough ones."""
    found, note = extract_card_checked(frame, detect_width)
    return found if note != "rough" else None
