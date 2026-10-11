"""Generate a fake card set so the whole pipeline can be tried (and tested)
without any real card data. The cards are random shapes on colored frames:
nothing like real art, but distinct enough to fingerprint.

Display them on a phone or print them, hold them up to the webcam, and
you can exercise scan / plan / export end to end.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import cv2
import numpy as np

from .vision import CARD_H, CARD_W

DOMAINS = ["fury", "calm", "mind", "body", "chaos", "order"]
DOMAIN_BGR = {
    "fury": (40, 40, 200), "calm": (160, 140, 40), "mind": (200, 90, 60),
    "body": (40, 140, 230), "chaos": (150, 50, 130), "order": (60, 200, 220),
}
RARITIES = ["common", "uncommon", "rare", "epic"]


def render_card(seed: int, domain: str, name: str, number: str) -> np.ndarray:
    rng = random.Random(seed)
    img = np.full((CARD_H, CARD_W, 3), 25, np.uint8)
    cv2.rectangle(img, (8, 8), (CARD_W - 9, CARD_H - 9), DOMAIN_BGR[domain], -1)
    art = (20, 50, CARD_W - 20, 260)
    canvas = np.full((art[3] - art[1], art[2] - art[0], 3), 235, np.uint8)
    ah, aw = canvas.shape[:2]
    for _ in range(9):
        color = tuple(rng.randrange(256) for _ in range(3))
        x, y = rng.randrange(aw), rng.randrange(ah)
        if rng.random() < 0.5:
            cv2.circle(canvas, (x, y), rng.randrange(10, 60), color, -1)
        else:
            cv2.rectangle(canvas, (x, y), (x + rng.randrange(20, 90), y + rng.randrange(20, 90)), color, -1)
    img[art[1]:art[3], art[0]:art[2]] = canvas
    cv2.rectangle(img, art[:2], art[2:], (25, 25, 25), 2)
    cv2.putText(img, name, (22, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.rectangle(img, (20, 275), (CARD_W - 20, CARD_H - 40), (220, 220, 220), -1)
    cv2.putText(img, number, (22, CARD_H - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return img


def make_demo(out_dir: str | Path, n: int = 24, seed: int = 7) -> Path:
    out = Path(out_dir)
    (out / "images").mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    cards = []
    for i in range(1, n + 1):
        domain = DOMAINS[i % len(DOMAINS)]
        card = {
            "id": f"DEMO-{i:03d}",
            "name": f"Demo Card {i}",
            "set": "DEMO" if i <= n // 2 else "DEM2",
            "number": i,
            "domain": [domain],
            "cost": rng.randrange(0, 8),
            "rarity": rng.choice(RARITIES),
            "image": f"images/DEMO-{i:03d}.png",
        }
        cv2.imwrite(str(out / card["image"]), render_card(seed * 1000 + i, domain, card["name"], f"DEMO - {i:03d}/{n}"))
        cards.append(card)
    path = out / "catalog.json"
    path.write_text(json.dumps(cards, indent=2), encoding="utf-8")
    return path
