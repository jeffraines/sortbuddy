"""Is the card lit well? Too much light washes parts of it out to pure white
(often one glare spot, especially on foils); too little leaves it dark and
noisy. Both make the small print on the bottom line hard to read."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

WASHED_OUT = 250   # grey level at which detail is gone
TOO_DARK = 70      # average grey of the card's inside below this: too dark
BRIGHT = 205       # above this: bright, though not yet lost


@dataclass
class Light:
    verdict: str        # "good", "bright", "glare", "dark"
    message: str
    washed_out: float   # fraction of the card that is pure white
    brightness: float   # average grey level of the card's inside, 0-255
    glare_spot: bool    # the washed-out part is one patch rather than spread out

    @property
    def ok(self) -> bool:
        return self.verdict == "good"


def assess(card: np.ndarray) -> Light:
    """Judge the lighting of a flattened card image."""
    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY) if card.ndim == 3 else card
    h, w = gray.shape
    inside = gray[int(0.06 * h): int(0.94 * h), int(0.06 * w): int(0.94 * w)]  # skip the border
    washed = gray >= WASHED_OUT
    washed_frac = float(washed.mean())
    brightness = float(inside.mean())

    spot = False
    if washed_frac > 0.003:
        n, _, stats, _ = cv2.connectedComponentsWithStats(washed.astype(np.uint8), connectivity=8)
        biggest = stats[1:, cv2.CC_STAT_AREA].max() if n > 1 else 0
        spot = biggest > 0.6 * washed.sum()

    if washed_frac > 0.01 and spot:
        return Light("glare", f"Glare spot: {washed_frac:.0%} of the card is washed out. "
                              "Move the light to the side or soften it (paper diffuser)", washed_frac, brightness, True)
    if washed_frac > 0.01:
        return Light("bright", f"Too bright: {washed_frac:.0%} of the card is washed out. Turn the light down",
                     washed_frac, brightness, False)
    if brightness < TOO_DARK:
        return Light("dark", "Too dark: turn the light up", washed_frac, brightness, spot)
    if brightness > BRIGHT:
        return Light("bright", "A bit bright: turn the light down a little", washed_frac, brightness, spot)
    return Light("good", "Light: good", washed_frac, brightness, spot)


def glare_mask(frame: np.ndarray) -> np.ndarray:
    """Where the picture is washed out (for painting it red on screen)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return gray >= WASHED_OUT
