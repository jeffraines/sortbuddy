"""Perceptual fingerprints for card images.

A card is identified by comparing a 256-bit perceptual hash (pHash) of the
flattened card against a pre-built index of reference images. This is cheap
enough to run on a Raspberry Pi Zero, and the whole index for a set of a few
thousand cards fits in well under a megabyte (32 bytes per card), so it could
even live in an ESP32-S3's PSRAM later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .vision import CARD_H, CARD_W

HASH_SIZE = 16  # 16x16 = 256 bits
HASH_BYTES = HASH_SIZE * HASH_SIZE // 8


def normalize(card: np.ndarray) -> np.ndarray:
    """Bring a card image to a canonical size, grayscale, and contrast."""
    if card.shape[:2] != (CARD_H, CARD_W):
        card = cv2.resize(card, (CARD_W, CARD_H), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY) if card.ndim == 3 else card
    # Trim the outer border: it's the same on every card and the warp is least
    # accurate there.
    m = 12
    gray = gray[m:-m, m:-m]
    return cv2.equalizeHist(gray)


def phash(card: np.ndarray) -> np.ndarray:
    """256-bit perceptual hash (DCT based), packed into HASH_BYTES uint8s.

    Keeps the 16x16 lowest-frequency DCT terms and records whether each is
    above the median. Low frequencies describe the card's overall layout and
    color masses, which survive blur, sensor noise and uneven lighting far
    better than pixel-level detail does.
    """
    g = normalize(card).astype(np.float32)
    small = cv2.resize(g, (64, 64), interpolation=cv2.INTER_AREA)
    low = cv2.dct(small)[:HASH_SIZE, :HASH_SIZE].ravel()
    bits = low > np.median(low[1:])
    return np.packbits(bits)


def sharpness(card: np.ndarray) -> float:
    """How in-focus a flattened card is: variance of the Laplacian over the
    bottom part (small text, so it's the most focus-sensitive). Higher is
    sharper; only meaningful compared between frames of the same setup."""
    h = card.shape[0]
    region = card[int(0.55 * h):]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) if region.ndim == 3 else region
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def hamming(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Bit distance between one hash `a` and one or many hashes `b`."""
    return np.unpackbits(np.bitwise_xor(a, b), axis=-1).sum(axis=-1)


@dataclass
class Match:
    card_id: str
    distance: int
    margin: int  # how much closer the best match is than the runner-up
    flipped: bool  # card was upside down

    def confident(self, max_distance: int, min_margin: int) -> bool:
        # A slightly looser match is fine when it's far closer than anything else.
        return ((self.distance <= max_distance and self.margin >= min_margin)
                or (self.distance <= max_distance + 15 and self.margin >= 40))


class FingerprintIndex:
    """Reference hashes for every known card."""

    def __init__(self, ids: list[str], hashes: np.ndarray):
        self.ids = list(ids)
        self.hashes = hashes.reshape(-1, HASH_BYTES).astype(np.uint8)

    def __len__(self) -> int:
        return len(self.ids)

    @classmethod
    def from_images(cls, images: dict[str, np.ndarray]) -> "FingerprintIndex":
        ids = list(images)
        hashes = np.stack([phash(images[i]) for i in ids]) if ids else np.zeros((0, HASH_BYTES), np.uint8)
        return cls(ids, hashes)

    def add(self, card_id: str, card: np.ndarray, keep: int = 5) -> None:
        """Learn another reference photo of a card. Several photos per card
        (different light, focus, angle) make recognition more robust; only
        the newest `keep` are kept."""
        rows = [i for i, x in enumerate(self.ids) if x == card_id]
        if len(rows) >= keep:
            drop = rows[0]
            del self.ids[drop]
            self.hashes = np.delete(self.hashes, drop, axis=0)
        self.ids.append(card_id)
        self.hashes = np.vstack([self.hashes, phash(card)[None, :]])

    def save(self, path: str | Path) -> None:
        np.savez_compressed(path, ids=np.array(self.ids), hashes=self.hashes)

    @classmethod
    def load(cls, path: str | Path) -> "FingerprintIndex":
        data = np.load(path, allow_pickle=False)
        return cls([str(i) for i in data["ids"]], data["hashes"])

    def match(self, card: np.ndarray) -> Match | None:
        """Best match for a flattened card, trying both orientations. The
        margin is measured against the closest *other* card, so several
        photos of the same card don't count against each other."""
        if len(self) == 0:
            return None
        ids = np.array(self.ids)
        best: Match | None = None
        for flipped, img in ((False, card), (True, cv2.rotate(card, cv2.ROTATE_180))):
            d = hamming(phash(img), self.hashes)
            i = int(np.argmin(d))
            others = d[ids != ids[i]]
            # Nothing else to compare with: measure against how far apart
            # unrelated cards typically are (about half the bits).
            second = int(others.min()) if others.size else HASH_BYTES * 4
            m = Match(self.ids[i], int(d[i]), second - int(d[i]), flipped)
            if best is None or m.distance < best.distance:
                best = m
        return best
