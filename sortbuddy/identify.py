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

import difflib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import lookup, ocr
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


# Fields the bottom line answers by itself (Riftbound sets are known by code).
QUICK_FIELDS = {"game", "face", "set", "number", "language", "foil", "id"}

# Picture matches this close (bits out of 256) are trusted without reading
# the bottom line; looser ones up to max_distance are checked.
SURE_DISTANCE, SURE_MARGIN = 40, 15


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

    def known(self, card: np.ndarray) -> tuple[str | None, bool]:
        """(card id or None, sure). A close picture match is sure; a looser
        one needs checking against the bottom line."""
        m = self.index.match(card) if len(self.index) else None
        if not m or not m.confident(self.max_distance, self.min_margin):
            return None, False
        return m.card_id, m.distance <= SURE_DISTANCE and m.margin >= SURE_MARGIN

    def identify(self, card: np.ndarray, check_foil: bool = False, needs: set | None = None) -> Result | None:
        """Safe to call from a worker thread (doesn't touch the catalog file).

        Foil is per copy, not per card: with `check_foil`, a card recognised
        from its picture still gets its bottom line read for the foil mark.

        `needs` is the set of fields the sort rule uses. If the bottom line
        alone answers them (game, set, number, language, foil, face), the
        card isn't looked up or read further: much faster, but it isn't
        added to your list either.
        """
        start = time.time()
        steps: list[str] = []
        known, sure = self.known(card)
        if known and self.catalog[known].get("face") == "back":
            return Result(known, dict(self.catalog[known].fields), "known", time.time() - start)
        quick = None
        if known and (not sure or check_foil) and self.use_ocr:
            quick = ocr.read_collector(card)
            mine = self.catalog[known].fields
            read_other = (quick.set_code and quick.number is not None and
                          (str(quick.set_code).upper(), quick.number) != (str(mine.get("set", "")).upper(), mine.get("number")))
            if read_other and not sure:
                known = None  # the bottom line says it's a different card: trust that
        if known:
            fields = dict(self.catalog[known].fields)
            fields.pop("foil", None)
            if quick is not None and quick.foil is not None:
                fields["foil"] = "yes" if quick.foil else "no"
                if quick.foil and "price_foil" in fields:
                    fields["price"] = fields["price_foil"]
            return Result(known, fields, "known", time.time() - start)
        if not self.use_ocr or self.source is None:
            return None

        t = time.time()
        quick = quick or ocr.read_collector(card)
        steps.append(f"bottom line {time.time() - t:.1f}s")
        if needs is not None and needs <= QUICK_FIELDS and quick.set_code:
            fields = {"face": "front", "set": quick.set_code,
                      "game": "riftbound" if quick.set_code.upper() in lookup.RIFTBOUND_SETS else "magic"}
            if quick.number is not None:
                fields["number"] = quick.number
            fields.update({k: v for k, v in quick.extra.items() if k in ("language",)})
            if quick.foil is not None:
                fields["foil"] = "yes" if quick.foil else "no"
            card_id = f"{quick.set_code}-{quick.number:03d}" if quick.number is not None else quick.set_code
            fields["name"] = card_id
            return Result(card_id, fields, "quick", time.time() - start, False, {"steps": steps})
        if quick.set_code and quick.number is not None:
            t = time.time()
            prop = propose(quick, "", "", self.source, {})
            steps.append(f"lookup {time.time() - t:.1f}s")
            if prop.found:
                return Result(prop.card_id, prop.fields, "bottom line", time.time() - start, True,
                              {"image": quick.upright, "steps": steps})

        t = time.time()
        full = ocr.read_card(card, local_names=False)
        steps.append(f"whole card {time.time() - t:.1f}s")
        if quick.set_code and not full.set_code:
            full.set_code = quick.set_code
        cache: dict = {}
        for name in full.names[:3] or [""]:
            prop = propose(full, name, "", self.source, cache)
            # Found by name alone (set not confirmed): only trust a near-exact
            # name. A wrong card is worse than a "?".
            if prop.found and (prop.kind == "ok" or _similar(name, prop.fields.get("name", "")) >= 0.85):
                return Result(prop.card_id, prop.fields, "name", time.time() - start, True,
                              {"image": full.upright, "steps": steps})
        self.last_steps = steps
        return None


    def teach_back(self, game: str, card: np.ndarray) -> str:
        """Remember what this game's card back looks like. Teaching it again
        adds another reference photo."""
        from .cli import save_reference

        card_id = "BACK-" + re.sub(r"[^a-z0-9]+", "-", game.lower()).strip("-")
        if card_id not in self.catalog.cards:
            save_reference(self.catalog, self.catalog_path, card_id, card,
                           name=f"{game} card back", face="back", game=game.lower())
        self.index.add(card_id, card)
        return card_id

    def learn(self, result: Result, card: np.ndarray) -> None:
        """Add a newly identified card to the list and the picture index.
        Call from the main thread: it writes the catalog file."""
        from .cli import save_reference

        img = result.extra.get("image", card)
        if result.how == "known":
            return
        existing = self.catalog.get(result.card_id)
        has_photo = existing is not None and self.catalog.image_path(existing) and \
            self.catalog.image_path(existing).exists()
        if not has_photo:
            fields = {k: v for k, v in result.fields.items() if k != "image"}
            save_reference(self.catalog, self.catalog_path, result.card_id, img, **fields)
        self.index.add(result.card_id, img)


def _similar(a: str, b: str) -> float:
    def norm(x):
        return re.sub(r"[^a-z0-9 ]", "", x.lower().split("//")[0]).strip()
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()
