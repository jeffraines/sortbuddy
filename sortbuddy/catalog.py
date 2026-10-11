"""Card catalog: everything we know about each card, keyed by card id.

The core idea of SortBuddy: we never try to *see* cost, color or rarity on
the card. We identify which card it is once, then every sort parameter is a
lookup in this catalog. That keeps the vision cheap and makes adding a new
sort parameter (or a whole new game) a data change, not a code change.

Catalog files are JSON (a list of objects) or CSV. Each card needs an `id`;
every other column is a free-form field usable in sort rules. List-valued
fields (e.g. a card with two domains) are JSON arrays, or `|`-separated in
CSV. An optional `image` field points at a reference scan, relative to the
catalog file.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Card:
    id: str
    fields: dict = field(default_factory=dict)

    def get(self, name: str):
        if name == "id":
            return self.id
        return self.fields.get(name)

    @property
    def name(self) -> str:
        return str(self.fields.get("name", self.id))


def _coerce(value):
    if isinstance(value, str):
        v = value.strip()
        if "|" in v:
            return [_coerce(p) for p in v.split("|") if p.strip()]
        try:
            return int(v)
        except ValueError:
            pass
        try:
            return float(v)
        except ValueError:
            return v
    return value


class Catalog:
    def __init__(self, cards: list[Card], root: Path | None = None):
        self.cards = {c.id: c for c in cards}
        self.root = root or Path(".")

    def __len__(self) -> int:
        return len(self.cards)

    def __getitem__(self, card_id: str) -> Card:
        return self.cards[card_id]

    def get(self, card_id: str) -> Card | None:
        return self.cards.get(card_id)

    def image_path(self, card: Card) -> Path | None:
        img = card.fields.get("image")
        return (self.root / img) if img else None

    def values(self, field_name: str) -> list:
        """Every distinct value of a field, flattening list fields."""
        seen = []
        for c in self.cards.values():
            v = c.get(field_name)
            for x in v if isinstance(v, list) else [v]:
                if x is not None and x not in seen:
                    seen.append(x)
        return seen

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        path = Path(path)
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8") as f:
                rows = [{k: _coerce(v) for k, v in r.items() if v != ""} for r in csv.DictReader(f)]
        else:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(rows, dict):
                rows = rows.get("cards", [])
        cards = []
        for r in rows:
            r = dict(r)
            card_id = str(r.pop("id"))
            cards.append(Card(card_id, r))
        return cls(cards, path.parent)
