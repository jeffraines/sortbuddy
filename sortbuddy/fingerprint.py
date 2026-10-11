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
        return self.distance <= max_distance and self.margin >= min_margin


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

    def add(self, card_id: str, card: np.ndarray) -> None:
        """Learn one more card (or replace its fingerprint)."""
        h = phash(card)[None, :]
        if card_id in self.ids:
            self.hashes[self.ids.index(card_id)] = h
        else:
            self.ids.append(card_id)
            self.hashes = np.vstack([self.hashes, h])

    def save(self, path: str | Path) -> None:
        np.savez_compressed(path, ids=np.array(self.ids), hashes=self.hashes)

    @classmethod
    def load(cls, path: str | Path) -> "FingerprintIndex":
        data = np.load(path, allow_pickle=False)
        return cls([str(i) for i in data["ids"]], data["hashes"])

    def match(self, card: np.ndarray) -> Match | None:
        """Best match for a flattened card, trying both orientations."""
        if len(self) == 0:
            return None
        best: Match | None = None
        for flipped, img in ((False, card), (True, cv2.rotate(card, cv2.ROTATE_180))):
            d = hamming(phash(img), self.hashes)
            order = np.argsort(d)
            first = int(d[order[0]])
            second = int(d[order[1]]) if len(order) > 1 else HASH_BYTES * 8
            m = Match(self.ids[order[0]], first, second - first, flipped)
            if best is None or m.distance < best.distance:
                best = m
        return best
