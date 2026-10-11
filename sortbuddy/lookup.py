"""Fill in a card's details from an online card database while enrolling.

Only used while enrolling on a computer; the sorter itself never needs the
internet. Each source takes what OCR read (name, set code, number) and
returns catalog fields, or None if it can't find the card.

Currently: Magic: The Gathering via Scryfall (https://scryfall.com/docs/api),
free to use with a descriptive User-Agent and modest request rates.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "SortBuddy/0.1 (personal card sorter)"
COLOR_NAMES = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


class LookupError_(RuntimeError):
    """The database couldn't be reached (offline, timeout...)."""


def _get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise LookupError_(f"Scryfall error {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise LookupError_(f"can't reach Scryfall ({e})") from e
    finally:
        time.sleep(0.1)  # Scryfall asks for 50-100 ms between requests


def _same_name(a: str, b: str) -> bool:
    def norm(s):
        return re.sub(r"[^a-z0-9]", "", s.lower())
    # Double-faced cards are named "Front // Back"; OCR sees the front.
    return norm(a) == norm(b) or norm(a.split("//")[0]) == norm(b)


def _num(v):
    """'3' -> 3, '*' or None stays as-is, '0.25' -> 0.25."""
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def _fields(card: dict) -> dict:
    face = card.get("card_faces", [{}])[0]
    get = lambda k, default=None: card.get(k, face.get(k, default))  # noqa: E731 - front face fallback
    colors = get("colors") or []
    type_line = get("type_line", "")
    types, _, subtypes = type_line.partition("—")
    prices = card.get("prices") or {}
    fields = {
        "name": card.get("name", ""),
        "set": card.get("set", "").upper(),
        "set_name": card.get("set_name", ""),
        "number": _num(card.get("collector_number", "")),
        "rarity": card.get("rarity", ""),
        "cost": int(card.get("cmc", 0)),
        "mana_cost": get("mana_cost", ""),
        "colors": [COLOR_NAMES.get(c, c) for c in colors] or ["colorless"],
        "color_identity": [COLOR_NAMES.get(c, c) for c in card.get("color_identity", [])] or ["colorless"],
        "type": type_line,
        "card_types": types.split(),           # e.g. ["Legendary", "Creature"]
        "subtypes": subtypes.split(),           # e.g. ["Merfolk", "Wizard"]
        "power": _num(get("power")),
        "toughness": _num(get("toughness")),
        "keywords": card.get("keywords", []),
        "text": get("oracle_text", "").replace("\n", " / "),
        "artist": card.get("artist", ""),
        "year": int(card["released_at"][:4]) if card.get("released_at") else None,
        "price": _num(prices.get("usd")),       # USD, non-foil, as of enrolling
        "price_foil": _num(prices.get("usd_foil")),
    }
    return {k: v for k, v in fields.items() if v not in (None, "", [])}


def scryfall(name: str, set_code: str | None = None, number: int | None = None) -> tuple[dict, bool] | None:
    """Returns (fields, printing_confirmed). Without a set code that Scryfall
    recognises, the card is found by name and the printing is a guess."""
    api = "https://api.scryfall.com/cards"
    q = urllib.parse.quote
    if set_code and number is not None:
        card = _get(f"{api}/{q(set_code.lower())}/{number}")
        if card and (not name or _same_name(card["name"], name)):
            return _fields(card), True
    if not name:
        return None
    if set_code:
        for mode in ("exact", "fuzzy"):
            card = _get(f"{api}/named?{mode}={q(name)}&set={q(set_code.lower())}")
            if card:
                return _fields(card), True
    card = _get(f"{api}/named?fuzzy={q(name)}")
    return (_fields(card), False) if card else None


SOURCES = {
    "mtg": ("Magic: The Gathering (Scryfall)", scryfall),
}


def card_id(fields: dict) -> str:
    n = fields.get("number")
    return f"{fields['set']}-{n:03d}" if isinstance(n, int) else f"{fields['set']}-{n}"
