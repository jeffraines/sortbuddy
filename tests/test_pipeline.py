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


def test_enroll_from_webcam_photos_then_identify(demo, tmp_path):
    """References taken with the webcam itself (no official images) work too."""
    from sortbuddy.cli import build_index, save_reference

    _, demo_catalog, _ = demo
    path = tmp_path / "mycards.csv"
    mine = Catalog([], tmp_path)
    rng = random.Random(9)
    originals = {}
    for card in list(demo_catalog.cards.values())[:12]:
        img = cv2.imread(str(demo_catalog.image_path(card)))
        originals[card.id] = img
        warped, _ = extract_card(fake_photo(img, rng))
        save_reference(mine, path, card.id, warped, name=card.name, cost=card.get("cost"))

    reloaded = Catalog.load(path)
    assert len(reloaded) == 12 and reloaded["DEMO-001"].get("cost") == demo_catalog["DEMO-001"].get("cost")

    index = build_index(str(path))
    for card_id, img in originals.items():
        warped, _ = extract_card(fake_photo(img, rng, upside_down=True))
        m = index.match(warped)
        assert m.card_id == card_id and m.confident(MAX_DISTANCE, MIN_MARGIN), (card_id, m)


class FakeCamera:
    """Stands in for a webcam: serves photos of the given cards, one per capture."""

    focus_label = "focus: auto"

    def __init__(self, cards, rng):
        self.photos = [fake_photo(c, rng) for c in cards]
        self.i = 0

    def read(self):
        return True, self.photos[min(self.i, len(self.photos) - 1)].copy()

    def handle_key(self, key):
        return False

    def release(self):
        pass


def test_enroll_flow_reads_names_and_saves(demo, tmp_path, monkeypatch):
    from sortbuddy import cli, ocr

    if not ocr.available():
        pytest.skip("rapidocr_onnxruntime not installed")
    _, demo_catalog, _ = demo
    cards = [cv2.imread(str(demo_catalog.image_path(demo_catalog[i]))) for i in ("DEMO-003", "DEMO-007")]
    cam = FakeCamera(cards, random.Random(4))
    # Per card: an idle frame, SPACE to capture, ENTER to accept what OCR read. Then Q.
    loop_keys = iter([255, ord(" "), 255, ord(" "), ord("q")])
    confirm_keys = iter([13, 13])

    def fake_show(window, frame):
        key = next(loop_keys)
        return key

    def fake_wait(_):
        cam.i += 1  # next card goes under the camera after each confirm
        return next(confirm_keys)

    monkeypatch.setattr(cli, "open_camera", lambda *a, **k: cam)
    monkeypatch.setattr(cli, "show", fake_show)
    monkeypatch.setattr(cv2, "imshow", lambda *a: None)
    monkeypatch.setattr(cv2, "waitKey", fake_wait)
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)

    path = tmp_path / "cards.csv"
    main(["enroll", str(path)])
    cat = Catalog.load(path)
    assert sorted(cat.cards) == ["DEMO-003", "DEMO-007"]
    assert cat["DEMO-003"].name == "Demo Card 3" and cat["DEMO-003"].get("number") == 3
    assert (tmp_path / cat["DEMO-007"].get("image")).exists()


def test_collector_info_ignores_flavor_text_and_power_toughness():
    """Text lines as read off a real Magic card (Divining Duelist, FRA #29)."""
    from sortbuddy.ocr import Line, _collector

    def at(text, x, y, h=18, w=200):
        return Line(text, 0.9, x, y, x + w, y + h)

    w, h = 630, 880
    lines = [
        at("Divining Duelist", 40, 40, 34, 300),
        at("Creature — Merfolk Wizard", 40, 470),
        at("They weren't clever then either.”", 40, 760),
        at("3/2", 470, 770, 30, 60),
        at("C 0029", 20, 835),
        at("FRA • EN", 20, 855),
        at("DAVID AUDEN NASH", 90, 855),
        at("™ & © 2026 Wizards of the Coast", 330, 860),
    ]
    assert _collector(lines, h, w) == ("FRA", 29)
    # Riftbound-style, including OCR dropping the space before the number.
    assert _collector([at("OGN • 029/298", 20, 850)], h, w) == ("OGN", 29)
    assert _collector([at("OGN029/298", 20, 850)], h, w) == ("OGN", 29)


SCRYFALL_DUELIST = {
    "object": "card", "name": "Divining Duelist", "set": "fra", "set_name": "Reality Fracture",
    "collector_number": "29", "mana_cost": "{2}{U}", "cmc": 3.0, "colors": ["U"], "color_identity": ["U"],
    "rarity": "common", "type_line": "Creature — Merfolk Wizard", "power": "3", "toughness": "2",
    "keywords": ["Flash"], "oracle_text": "Flash\nDraw a card, then discard a card.",
    "artist": "David Auden Nash", "released_at": "2026-10-02", "prices": {"usd": "0.25", "usd_foil": "0.38"},
}


def test_scryfall_lookup_fields(monkeypatch):
    from sortbuddy import lookup

    calls = []

    def fake_get(url):
        calls.append(url)
        if "&set=" in url and "set=fra" not in url:
            return None  # Scryfall has no set "they"
        return SCRYFALL_DUELIST if "/fra/29" in url or "fuzzy=Divining" in url else None

    monkeypatch.setattr(lookup, "_get", fake_get)
    fields, confirmed = lookup.scryfall("Divining Duelist", "FRA", 29)
    assert confirmed and lookup.card_id(fields) == "FRA-029"
    card = Card("FRA-029", fields)
    for rule in ["colors has blue", "cost <= 3", "subtypes has wizard", "keywords has flash",
                 "text contains draw a card", "card_types has creature and power >= 3", "price < 1"]:
        assert Rule(rule)(card), rule
    # OCR misread the set: found by name, flagged as unconfirmed printing.
    fields, confirmed = lookup.scryfall("Divining Duelist", "THEY", 3)
    assert not confirmed and fields["set"] == "FRA"


def test_foil_mark_on_bottom_line():
    from sortbuddy.ocr import Line, _foil

    def bottom(text):
        return [Line(text, 0.9, 20, 855, 220, 873)]

    assert _foil(bottom("LCI ★ EN"), 880, 630) is True
    assert _foil(bottom("LCI * EN"), 880, 630) is True   # OCR often reads the star as *
    assert _foil(bottom("LCI • EN"), 880, 630) is False
    assert _foil(bottom("LCI EN"), 880, 630) is None      # mark not read: don't guess


def test_collector_info_when_ocr_merges_rarity_and_artist():
    """Real OCR of Divining Duelist: 'C 0029' read without the space, and the
    artist (small caps) merged onto the 'FRA • EN' line in mixed case."""
    from sortbuddy.ocr import Line, _collector

    def at(text, x, y, w=200):
        return Line(text, 0.9, x, y, x + w, y + 18)

    for c_line, set_line in [("C0029", "FRA•EN David Auden Nash"), ("C0029", "FRA.EN DAVID AUDEN NASH"),
                             ("C 0029", "FRA • EN")]:
        assert _collector([at(c_line, 20, 835), at(set_line, 20, 855, 300)], 880, 630) == ("FRA", 29), (c_line, set_line)


def test_language_read_from_riftbound_bottom_line():
    from sortbuddy.ocr import Line, _collector, _details

    lines = [Line("OGN · 114/298 · KR", 0.9, 20, 855, 300, 873)]
    assert _collector(lines, 880, 630) == ("OGN", 114)
    assert _details(lines, 880, 630)["language"] == "KR"


def test_korean_card_keeps_english_and_korean_names():
    from sortbuddy.ocr import CardText
    from sortbuddy.proposal import propose

    def fake_riftcodex(name, set_code, number):
        assert (set_code, number) == ("OGN", 114)
        return {"name": "Progress Day", "set": "OGN", "number": 114, "energy": 6, "domain": ["mind"]}, True

    text = CardText(names=[], set_code="OGN", number=114, extra={"language": "KR"},
                    local_names=["진보의 날", "카드 4장을 뽑습니다."])
    p = propose(text, "", "card-001", fake_riftcodex, {})
    assert p.card_id == "OGN-114"
    assert p.fields["name"] == "Progress Day" and p.fields["name_kr"] == "진보의 날"
    assert p.fields["language"] == "KR"
    # Lookup off: the Korean name is the name.
    p = propose(text, "", "card-001", None, {})
    assert p.fields["name"] == "진보의 날" and p.card_id == "OGN-114"


def test_identify_without_enrolling_then_recognise(demo, tmp_path):
    from sortbuddy import ocr
    from sortbuddy.identify import Identifier

    if not ocr.available():
        pytest.skip("rapidocr_onnxruntime not installed")
    _, demo_catalog, _ = demo
    looked_up = []

    def fake_source(name, set_code, number):
        looked_up.append((set_code, number))
        card = demo_catalog.get(f"{set_code}-{number:03d}")
        return (dict(card.fields, set=set_code, number=number), True) if card else None

    path = tmp_path / "list.csv"
    ident = Identifier(Catalog([], tmp_path), path, FingerprintIndex([], np.zeros((0, 32), np.uint8)), fake_source)
    img = cv2.imread(str(demo_catalog.image_path(demo_catalog["DEMO-005"])))
    rng = random.Random(8)

    card = extract_card(fake_photo(img, rng))[0]
    r = ident.identify(card)
    assert r and r.card_id == "DEMO-005" and r.how == "bottom line" and r.new
    ident.learn(r, card)
    assert Catalog.load(path)["DEMO-005"].get("cost") == demo_catalog["DEMO-005"].get("cost")

    # Another photo of the same card: recognised from its picture, no lookup.
    looked_up.clear()
    r2 = ident.identify(extract_card(fake_photo(img, rng, upside_down=True))[0])
    assert r2.card_id == "DEMO-005" and r2.how == "known" and not looked_up
