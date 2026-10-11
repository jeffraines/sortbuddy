"""Turning a noisy stream of per-frame matches into one decision per card,
and recording what was scanned so it can be exported as an inventory."""

from __future__ import annotations

import csv
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .catalog import Catalog


class Debouncer:
    """Decide once per card.

    Feed it one observation per frame: a card id, or None when no card is
    confidently identified. It returns a card id exactly once, when that id
    has been seen `stable` frames in a row. It won't fire again until the
    card leaves view for `gap` frames, or a *different* card becomes stable
    (so you can swap cards by hand without an empty frame in between).
    """

    def __init__(self, stable: int = 4, gap: int = 6):
        self.stable, self.gap = stable, gap
        self._candidate: str | None = None
        self._streak = 0
        self._empty = 0
        self._last_decided: str | None = None

    def update(self, card_id: str | None) -> str | None:
        if card_id is None:
            self._empty += 1
            self._streak = 0
            self._candidate = None
            if self._empty >= self.gap:
                self._last_decided = None
            return None
        self._empty = 0
        if card_id == self._candidate:
            self._streak += 1
        else:
            self._candidate, self._streak = card_id, 1
        if self._streak >= self.stable and card_id != self._last_decided:
            self._last_decided = card_id
            return card_id
        return None

    def reset(self) -> None:
        self._last_decided = None


@dataclass
class Scan:
    timestamp: float
    card_id: str
    yes: bool
    rule: str


class Session:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.scans: list[Scan] = []

    def record(self, card_id: str, yes: bool, rule: str) -> Scan:
        s = Scan(time.time(), card_id, yes, rule)
        self.scans.append(s)
        return s

    def undo(self) -> Scan | None:
        return self.scans.pop() if self.scans else None

    def counts(self) -> tuple[int, int]:
        yes = sum(s.yes for s in self.scans)
        return yes, len(self.scans) - yes

    def save_log(self, path: str | Path) -> None:
        with Path(path).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "id", "name", "pile", "rule"])
            for s in self.scans:
                card = self.catalog.get(s.card_id)
                name = card.name if card else s.card_id
                w.writerow([f"{s.timestamp:.3f}", s.card_id, name, "YES" if s.yes else "NO", s.rule])


def export_inventory(catalog: Catalog, log_paths: list[str | Path], out: str | Path,
                     columns: tuple[str, ...] = ("name", "set", "number", "rarity")) -> int:
    """Merge one or more session logs into a quantity-per-card CSV.

    Scan a card twice across passes of a multi-pass sort and it'd be counted
    twice, so only the first pass of each sort should be fed in here.
    Returns the number of distinct cards written.
    """
    counts: Counter[str] = Counter()
    for p in log_paths:
        with Path(p).open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                counts[row["id"]] += 1
    with Path(out).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", *columns, "quantity"])
        for card_id, qty in sorted(counts.items()):
            card = catalog.get(card_id)
            vals = [(card.get(c) if card else "") for c in columns]
            vals = ["|".join(map(str, v)) if isinstance(v, list) else ("" if v is None else v) for v in vals]
            w.writerow([card_id, *vals, qty])
    return len(counts)
