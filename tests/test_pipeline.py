import random

import cv2
import numpy as np
import pytest

from sortbuddy.catalog import Card, Catalog
from sortbuddy.cli import MAX_DISTANCE, MIN_MARGIN, main
from sortbuddy.demo import make_demo
from sortbuddy.fingerprint import FingerprintIndex
from sortbuddy.radix import SortPlan, simulate
from sortbuddy.rules import Rule, RuleError
from sortbuddy.session import Debouncer
from sortbuddy.vision import extract_card


def fake_photo(card: np.ndarray, rng: random.Random, upside_down=False, sideways=False) -> np.ndarray:
    """Place a card on a dark mat with perspective skew, blur, noise and a lighting tint."""
    if upside_down:
        card = cv2.rotate(card, cv2.ROTATE_180)
    h, w = card.shape[:2]
    frame_w, frame_h = 960, 720
    cx, cy = frame_w / 2 + rng.uniform(-80, 80), frame_h / 2 + rng.uniform(-40, 40)
    scale = rng.uniform(1.0, 1.3)
    hw, hh = w * scale / 2, h * scale / 2
    dst = np.array([[cx - hw, cy - hh], [cx + hw, cy - hh], [cx + hw, cy + hh], [cx - hw, cy + hh]], np.float32)
    dst += np.array([[rng.uniform(-25, 25), rng.uniform(-25, 25)] for _ in range(4)], np.float32)
    if sideways:
        c = dst.mean(axis=0)
        dst = (dst - c) @ np.array([[0, -1], [1, 0]], np.float32) + c
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    frame = np.full((frame_h, frame_w, 3), (30, 28, 26), np.uint8)
    frame = cv2.warpPerspective(card, m, (frame_w, frame_h), dst=frame, borderMode=cv2.BORDER_TRANSPARENT)
    frame = cv2.GaussianBlur(frame, (3, 3), 0)
    tint = np.array([rng.uniform(0.8, 1.15) for _ in range(3)])
    frame = np.clip(frame * tint + np.random.default_rng(rng.randrange(1 << 30)).normal(0, 6, frame.shape), 0, 255)
    return frame.astype(np.uint8)


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo")
    path = make_demo(root, n=30)
    main(["index", str(path)])
    catalog = Catalog.load(path)
    index = FingerprintIndex.load(path.with_suffix(".index.npz"))
    return path, catalog, index


def test_identifies_cards_from_skewed_photos(demo):
    _, catalog, index = demo
    rng = random.Random(1)
    wrong = []
    for i, card in enumerate(catalog.cards.values()):
        img = cv2.imread(str(catalog.image_path(card)))
        photo = fake_photo(img, rng, upside_down=i % 3 == 0, sideways=i % 4 == 0)
        found = extract_card(photo)
        assert found is not None, f"no card found for {card.id}"
        m = index.match(found[0])
        if m.card_id != card.id or not m.confident(MAX_DISTANCE, MIN_MARGIN):
            wrong.append((card.id, m))
    assert not wrong


def test_no_card_in_empty_frame():
    assert extract_card(np.full((480, 640, 3), 30, np.uint8)) is None


def card(**fields):
    return Card(fields.pop("id", "x"), fields)


def test_rules():
    c = card(cost=2, rarity="Rare", set="OGN", domain=["fury", "chaos"])
    assert Rule("cost <= 3")(c)
    assert not Rule("cost > 2")(c)
    assert Rule("rarity == rare")(c)
    assert Rule("rarity in common,rare")(c)
    assert Rule("domain has Fury")(c)
    assert Rule("domain in calm,chaos")(c)
    assert Rule("set == OGN and rarity != common")(c)
    assert Rule("set == XYZ or cost = 2")(c)
    assert not Rule("set == XYZ and cost = 2")(c)
    assert Rule("missing != 5")(c)
    assert not Rule("missing == 5")(c)
    with pytest.raises(RuleError):
        Rule("cost is cheap")


def test_radix_plan_fully_sorts_in_log2_passes():
    rng = random.Random(3)
    cards = [card(id=str(i), cost=rng.randrange(0, 8), domain=[rng.choice(["fury", "calm", "mind"])]) for i in range(200)]
    plan = SortPlan("cost", list(range(8)))
    assert plan.passes == 3
    assert SortPlan("cost", list(range(8)), other=True).passes == 4
    out = simulate(plan, cards)
    assert [c.get("cost") for c in out] == sorted(c.get("cost") for c in cards)

    # Stable: sort by cost, then by domain -> grouped by domain, cost-ordered within.
    out = simulate(SortPlan("domain", ["calm", "fury", "mind"]), out)
    keys = [(c.get("domain")[0], c.get("cost")) for c in out]
    assert keys == sorted(keys)


def test_debouncer_decides_once_per_card():
    d = Debouncer(stable=3, gap=2)
    stream = ["A", "A", None, "A", "A", "A", "A", "A", "B", "B", "B", "B", None, None, "B", "B", "B"]
    fired = [x for x in (d.update(s) for s in stream) if x]
    assert fired == ["A", "B", "B"]


def test_export(demo, tmp_path):
    path, catalog, _ = demo
    log = tmp_path / "log.csv"
    log.write_text("timestamp,id,name,pile,rule\n1,DEMO-001,a,YES,r\n2,DEMO-001,a,NO,r\n3,DEMO-002,b,NO,r\n")
    out = tmp_path / "inv.csv"
    main(["export", str(path), str(log), "-o", str(out)])
    lines = out.read_text().splitlines()
    assert lines[0] == "id,name,set,number,rarity,quantity"
    assert lines[1].startswith("DEMO-001,Demo Card 1,DEMO,1,") and lines[1].endswith(",2")
