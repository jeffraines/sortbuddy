"""Turn the photos taken while sorting into ready-to-post sale listings.

While sorting with photos on, every saved photo gets a line in the session's
`photos.csv` (which card, photo size, price at the time). `export_listings`
reads those, keeps the cards worth listing, and writes for each one a folder
with its photos and a `listing.txt` (Korean and English title, price and
description to paste into Bunjang / Danggeun / anywhere), plus a
`listings.csv` overview sorted by value.

Nothing is uploaded anywhere: the marketplaces have no public upload API, and
condition still has to be checked by eye before posting.
"""

from __future__ import annotations

import csv
import math
import shutil
from collections import defaultdict
from pathlib import Path

from .catalog import Catalog

MANIFEST = "photos.csv"
MANIFEST_COLUMNS = ["file", "id", "name", "tier", "price_usd", "side"]

GAME_KO = {"onepiece": "원피스 카드게임", "pokemon": "포켓몬 카드게임",
           "riftbound": "리프트바운드", "magic": "매직 더 개더링"}
GAME_EN = {"onepiece": "One Piece Card Game", "pokemon": "Pokémon TCG",
           "riftbound": "Riftbound", "magic": "Magic: The Gathering"}
LANG_KO = {"ko": "한글판", "kr": "한글판", "en": "영문판", "ja": "일본판", "jp": "일본판",
           "zh": "중국판", "cn": "중국판"}
LANG_EN = {"ko": "Korean", "kr": "Korean", "en": "English", "ja": "Japanese", "jp": "Japanese",
           "zh": "Chinese", "cn": "Chinese"}


def append_manifest(folder: Path, row: dict) -> None:
    """Note one saved photo in the session's photos.csv."""
    path = folder / MANIFEST
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in MANIFEST_COLUMNS})


def krw(usd: float, rate: float) -> int:
    """A tidy asking price in won: to 500 below ₩10,000, to 1,000 above."""
    won = usd * rate
    step = 500 if won < 10_000 else 1_000
    return max(step, int(math.ceil(won / step) * step))


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in " -_.()" else "_" for ch in name).strip()[:80]


def listing_text(card_id: str, fields: dict, qty: int, usd: float | None, rate: float) -> str:
    game = str(fields.get("game") or "").lower()
    lang = str(fields.get("language") or "").lower()
    name = str(fields.get("name") or card_id)
    name_ko = str(fields.get("name_ko") or "")
    set_code = str(fields.get("set") or "").upper()
    number = fields.get("number")
    code = f"{set_code}-{number:03d}" if set_code and isinstance(number, int) else card_id
    rarity = str(fields.get("rarity") or "").upper()
    foil = " 포일" if fields.get("foil") is True else ""

    title_ko = " ".join(p for p in [f"[{GAME_KO[game]}]" if game in GAME_KO else "", name_ko or name,
                                    code, rarity + foil, LANG_KO.get(lang, "")] if p)
    title_en = " ".join(p for p in [name, code, rarity, "Foil" if foil else "",
                                    LANG_EN.get(lang, ""), f"({GAME_EN[game]})" if game in GAME_EN else ""] if p)
    price_line_ko = (f"희망가: {krw(usd, rate):,}원 (미국 시세 약 ${usd:.2f} 기준, 확인 후 조정)"
                     if usd is not None else "희망가: (시세 확인 필요)")
    price_line_en = f"Asking: about ${usd:.2f} (US market)" if usd is not None else "Asking: (check price)"
    qty_ko = f"수량: {qty}장" if qty > 1 else "수량: 1장"
    return "\n".join([
        "=== 한국어 ===",
        title_ko,
        "",
        price_line_ko,
        qty_ko,
        "상태: (직접 확인 후 기재: 민트 / 니어민트 / 사용감 있음)",
        "사진 속 실물 카드 그대로 발송합니다.",
        "택배 / 직거래 가능",
        "",
        "=== English ===",
        title_en,
        "",
        price_line_en,
        f"Quantity: {qty}",
        "Condition: (check and fill in: NM / LP / MP)",
        "The card in the photos is the card you get.",
        "",
        f"(SortBuddy id: {card_id})",
    ]) + "\n"


def export_listings(catalog: Catalog, photo_dirs: list[str | Path], out: str | Path,
                    min_usd: float = 1.0, krw_per_usd: float = 1400.0) -> int:
    """Write one listing folder per card worth at least `min_usd` (or with
    no known price, so it gets checked by hand). Returns the number of listings."""
    photos: dict[str, list[Path]] = defaultdict(list)
    copies: dict[str, int] = defaultdict(int)
    prices: dict[str, float] = {}
    full: set[str] = set()  # cards with at least one full-size photo
    for d in map(Path, photo_dirs):
        manifest = d / MANIFEST
        if not manifest.exists():
            continue
        with manifest.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                card_id = row.get("id") or ""
                if not card_id or card_id.startswith("BACK-"):
                    continue
                if row.get("side", "front") in ("", "front"):
                    copies[card_id] += 1
                photos[card_id].append(d / row["file"])
                if row.get("tier", "full") != "small":
                    full.add(card_id)
                p = _num(row.get("price_usd"))
                if p is not None:
                    prices[card_id] = max(prices.get(card_id, 0.0), p)

    rows = []
    for card_id, files in photos.items():
        card = catalog.get(card_id)
        fields = dict(card.fields) if card else {}
        usd = prices.get(card_id)
        if usd is None:
            usd = max((v for v in (_num(fields.get("price")), _num(fields.get("price_foil"))) if v is not None),
                      default=None)
        if usd is not None and usd < min_usd:
            continue
        if usd is None and card_id not in full and min_usd > 0:
            continue  # no price, and judged bulk (e.g. a common) when photographed
        rows.append((usd if usd is not None else math.inf, card_id, fields, files))

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (-r[0], r[1]))
    with (out / "listings.csv").open("w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel shows Korean
        w = csv.writer(f)
        w.writerow(["#", "id", "name", "name_ko", "set", "number", "rarity", "language", "quantity",
                    "price_usd", "asking_krw", "folder"])
        for i, (usd, card_id, fields, files) in enumerate(rows, 1):
            usd = None if usd == math.inf else usd
            qty = max(1, copies.get(card_id, 0))
            folder = out / _safe(f"{i:03d} {card_id} {fields.get('name', '')}")
            folder.mkdir(exist_ok=True)
            for n, src in enumerate(files, 1):
                if src.exists():
                    shutil.copy2(src, folder / f"{n:02d}{src.suffix}")
            (folder / "listing.txt").write_text(listing_text(card_id, fields, qty, usd, krw_per_usd),
                                                encoding="utf-8")
            w.writerow([i, card_id, fields.get("name", ""), fields.get("name_ko", ""), fields.get("set", ""),
                        fields.get("number", ""), fields.get("rarity", ""), fields.get("language", ""), qty,
                        "" if usd is None else f"{usd:.2f}",
                        "" if usd is None else krw(usd, krw_per_usd), folder.name])
    return len(rows)
