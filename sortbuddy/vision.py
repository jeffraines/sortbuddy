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


def _inside(inner: np.ndarray, outer: np.ndarray) -> bool:
    poly = order_corners(outer).reshape(-1, 1, 2)
    return all(cv2.pointPolygonTest(poly, (float(x), float(y)), True) > -3 for x, y in inner)


ART_GAP = 0.33     # see _lopsided
BORDER_GAP = 0.06  # see _innermost_card


def _gaps(outer: np.ndarray, inner: np.ndarray) -> list[float]:
    """Margins between two outlines (top, bottom, left, right) as a share of
    the outer's longer side."""
    o, i = order_corners(outer), order_corners(inner)
    long_side = max(float(np.linalg.norm(o[3] - o[0])), float(np.linalg.norm(o[1] - o[0]))) or 1.0
    return [float(np.linalg.norm(g)) / long_side for g in (
        (i[0] + i[1] - o[0] - o[1]) / 2, (o[3] + o[2] - i[3] - i[2]) / 2,
        (i[0] + i[3] - o[0] - o[3]) / 2, (o[1] + o[2] - i[1] - i[2]) / 2)]


def _lopsided(outer: np.ndarray, inner: np.ndarray) -> bool:
    """True if `inner` leaves a big gap on one side of `outer`. A card's own
    art box leaves the whole text box below it (or the name and type line
    beside it, when sideways); a card lying in a box only a small margin."""
    return max(_gaps(outer, inner)) > ART_GAP


def _innermost_card(clean: list) -> tuple[float, np.ndarray]:
    """From card-shaped outlines (largest first), skip containers: if a clean
    outline holds another one that's clearly smaller (< 80% of its area), the
    outer one is a box opening, tray or sleeve and the inner one is the card.
    A card's own printed frame (a thin even margin inside it) and its art box
    (a lopsided one) don't count."""
    area, quad = clean[0]
    changed = True
    while changed:
        changed = False
        for a, q in clean:
            if 0.2 * area < a < 0.8 * area and _inside(q, quad):
                if _lopsided(quad, q):
                    continue  # the card's own art box, not a card inside a box
                if np.mean(_gaps(quad, q)) < BORDER_GAP:
                    continue  # a thin even margin: the card's own border and its printed frame
                area, quad, changed = a, q, True
                break
    return area, quad


def _profile(gray: np.ndarray, a: np.ndarray, b: np.ndarray, inward: np.ndarray, depth: float) -> np.ndarray:
    """Brightness going in from the edge a-b: averaged along the edge, one
    value per pixel of depth. A card's border reads the same on every side."""
    h, w = gray.shape
    t = np.linspace(0.2, 0.8, 30)[:, None]
    line = a + (b - a) * t
    steps = np.arange(int(depth))[:, None, None]
    pts = line[None] + steps * inward
    x = np.clip(pts[..., 0].round().astype(int), 0, w - 1)
    y = np.clip(pts[..., 1].round().astype(int), 0, h - 1)
    return np.median(gray[y, x].astype(np.float32), axis=1)


ASPECT_SLACK = 0.03  # outlines this close to a card's shape are left alone


def _fit_aspect(gray: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Trim an outline that's too long for a card back to card shape.

    When a card underneath sticks out past one end of the top card and both
    have dark borders, the two merge into one outline a few percent too long.
    Every card is 88 x 63 mm, so the overhang shows as a wrong shape. The cut
    goes where the end looks like the card's own sides (same border, same
    width), trying both ends; if nothing matches clearly it's left alone.
    """
    tl, tr, br, bl = order_corners(quad).astype(np.float32)
    w = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    h = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    if min(w, h) < 40:
        return quad
    sides = [np.linalg.norm(tr - tl), np.linalg.norm(br - bl), np.linalg.norm(bl - tl), np.linalg.norm(br - tr)]
    if max(sides[0], sides[1]) > 1.025 * min(sides[0], sides[1]) or \
            max(sides[2], sides[3]) > 1.025 * min(sides[2], sides[3]):
        return quad  # seen at a slant: the shape is off from perspective, not an overhang
    ratio = max(w, h) / min(w, h)
    if ratio > CARD_ASPECT * (1 + ASPECT_SLACK):
        trim_long = True                                   # too long
    elif ratio < CARD_ASPECT * (1 - ASPECT_SLACK):
        trim_long = False                                  # too wide
    else:
        return quad
    along_w = (w >= h) == trim_long                        # trimming the tl->tr direction?
    rails = [(tl, tr), (bl, br)] if along_w else [(tl, bl), (tr, br)]
    length = float(np.linalg.norm(rails[0][1] - rails[0][0]) + np.linalg.norm(rails[1][1] - rails[1][0])) / 2
    other = float(min(w, h) if trim_long else max(w, h))
    keep = (other * CARD_ASPECT if trim_long else other / CARD_ASPECT) / length
    axis = (rails[0][1] - rails[0][0] + rails[1][1] - rails[1][0]) / 2
    axis /= np.linalg.norm(axis) or 1.0
    side = np.array([-axis[1], axis[0]], np.float32)       # across the rails
    if np.dot(side, rails[1][0] - rails[0][0]) < 0:
        side = -side
    depth = max(6.0, 0.07 * min(w, h))

    def cut(f: float):
        return tuple(s + (e - s) * f for s, e in rails)

    # What the card's edge looks like, from its two sides (rails).
    (s0, e0), (s1, e1) = rails
    mid = lambda s, e: (s + (e - s) * 0.25, s + (e - s) * 0.75)
    ref = (_profile(gray, *mid(s0, e0), side, depth) + _profile(gray, *mid(s1, e1), -side, depth)) / 2

    def misfit(pos: float, inward: np.ndarray) -> float:
        return float(np.mean(np.abs(_profile(gray, *cut(pos), inward, depth) - ref)))

    as_is = min(misfit(0.0, axis), misfit(1.0, -axis))      # the better of the two current ends
    best = (np.inf, None)
    step = 1.0 / length
    for from_start in (False, True):                       # cut off the end, or the start
        for f in np.arange(keep - 0.015, min(keep + 0.015, 1 - 2 * step), step):
            pos = 1 - f if from_start else f
            m = misfit(pos, axis if from_start else -axis)
            if m < best[0]:
                best = (m, (from_start, pos))
    if best[1] is None or best[0] > max(12.0, 1.5 * as_is):
        return quad  # no end that looks like the card's sides: leave it
    from_start, pos = best[1]
    a, b = cut(pos)
    new = [a, e0, e1, b] if from_start else [s0, a, b, s1]
    return order_corners(np.array(new, np.float32))


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
        area, quad = _innermost_card(clean)
        centre = quad.mean(axis=0)
        apart = [q for a, q in clean[1:] if 0.6 < a / area and
                 np.linalg.norm(q.mean(axis=0) - centre) > 0.5 * np.sqrt(area)]
        return order_corners(_fit_aspect(blur, quad)), ("several" if apart else "")
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


class Stabilizer:
    """Low-pass filter for the card outline over time, like the eye does.

    Small frame-to-frame jitter is averaged out; a different outline must
    show up in several frames in a row before it replaces the current one;
    a few frames with no card don't drop it. Feed it every frame."""

    def __init__(self, hold: int = 3, switch_after: int = 3, smoothing: float = 0.5):
        self.corners: np.ndarray | None = None
        self.note = ""
        self.hold, self.switch_after, self.smoothing = hold, switch_after, smoothing
        self.missing = 0
        self.candidate: np.ndarray | None = None
        self.candidate_count = 0

    @staticmethod
    def _shift(a: np.ndarray, b: np.ndarray) -> float:
        """Largest corner movement, relative to the card's size."""
        size = np.linalg.norm(a[2] - a[0])
        return float(np.max(np.linalg.norm(a - b, axis=1)) / max(size, 1.0))

    def update(self, corners: np.ndarray | None, note: str) -> tuple[np.ndarray | None, str]:
        if corners is None:
            self.missing += 1
            if self.missing > self.hold:
                self.corners, self.candidate, self.candidate_count = None, None, 0
            return self.corners, self.note
        self.missing = 0
        if self.corners is None:
            self.corners, self.note = corners.astype(np.float32), note
        elif self._shift(self.corners, corners) < 0.06:  # same outline, a little jitter: average
            self.corners = (self.smoothing * self.corners + (1 - self.smoothing) * corners).astype(np.float32)
            self.note = note
            self.candidate, self.candidate_count = None, 0
        else:  # a different outline: only switch once it has held for a few frames
            if self.candidate is not None and self._shift(self.candidate, corners) < 0.06:
                self.candidate_count += 1
            else:
                self.candidate, self.candidate_count = corners.astype(np.float32), 1
            if self.candidate_count >= self.switch_after:
                self.corners, self.note = self.candidate, note
                self.candidate, self.candidate_count = None, 0
        return self.corners, self.note
