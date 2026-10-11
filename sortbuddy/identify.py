"""Work out which card is in front of the camera, without enrolling first.

Fastest first:
1. Its picture matches a card already in your list (milliseconds).
2. Read the bottom line (set + number, ~0.2 s) and look it up in the set
   list cached on disk (instant after the first card of a set).
3. Read the whole card for its name and look that up (~1 s, online).

Cards identified by 2 or 3 are added to your list with their photo, so the
next time (another copy, or the next pass of a multi-pass sort) step 1
recognises them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import ocr
from .catalog import Catalog
from .fingerprint import FingerprintIndex
from .proposal import propose


@dataclass
class Result:
    card_id: str
    fields: dict
    how: str               # "known", "bottom line", "name"
    seconds: float
    new: bool = False      # wasn't in the list before
    extra: dict = field(default_factory=dict)


class Identifier:
    def __init__(self, catalog: Catalog, catalog_path: str | Path, index: FingerprintIndex,
                 source, use_ocr: bool = True, max_distance: int = 60, min_margin: int = 8):
        """`source` is a lookup function from lookup.SOURCES, or None: then
        only cards already in the list can be recognised."""
        self.catalog = catalog
        self.catalog_path = Path(catalog_path)
        self.index = index
        self.source = source
        self.use_ocr = use_ocr
        self.max_distance, self.min_margin = max_distance, min_margin

    def known(self, card: np.ndarray) -> str | None:
        m = self.index.match(card) if len(self.index) else None
        return m.card_id if m and m.confident(self.max_distance, self.min_margin) else None

    def identify(self, card: np.ndarray, check_foil: bool = False) -> Result | None:
        """Safe to call from a worker thread (doesn't touch the catalog file).

        Foil is per copy, not per card: with `check_foil`, a card recognised
        from its picture still gets its bottom line read for the foil mark.
        """
        start = time.time()
        known = self.known(card)
        if known:
            fields = dict(self.catalog[known].fields)
            fields.pop("foil", None)
            if check_foil and self.use_ocr:
                foil = ocr.read_collector(card).foil
                if foil is not None:
                    fields["foil"] = "yes" if foil else "no"
                    if foil and "price_foil" in fields:
                        fields["price"] = fields["price_foil"]
            return Result(known, fields, "known", time.time() - start)
        if not self.use_ocr or self.source is None:
            return None

        quick = ocr.read_collector(card)
        if quick.set_code and quick.number is not None:
            prop = propose(quick, "", "", self.source, {})
            if prop.found:
                return Result(prop.card_id, prop.fields, "bottom line", time.time() - start, True,
                              {"image": quick.upright})

        full = ocr.read_card(card)
        cache: dict = {}
        for name in full.names[:3] or [""]:
            prop = propose(full, name, "", self.source, cache)
            if prop.found:
                return Result(prop.card_id, prop.fields, "name", time.time() - start, True,
                              {"image": full.upright})
        return None

    def learn(self, result: Result, card: np.ndarray) -> None:
        """Add a newly identified card to the list and the picture index.
        Call from the main thread: it writes the catalog file."""
        from .cli import save_reference

        img = result.extra.get("image", card)
        existing = self.catalog.get(result.card_id)
        has_photo = existing is not None and self.catalog.image_path(existing) and \
            self.catalog.image_path(existing).exists()
        if not has_photo:
            fields = {k: v for k, v in result.fields.items() if k != "image"}
            save_reference(self.catalog, self.catalog_path, result.card_id, img, **fields)
        self.index.add(result.card_id, img)
