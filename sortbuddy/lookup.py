"""Fill in a card's details from an online card database while enrolling.

Only used while enrolling on a computer; the sorter itself never needs the
internet. Each source takes what OCR read (name, set code, number) and
returns catalog fields, or None if it can't find the card.

Currently:
- Magic: The Gathering via Scryfall (https://scryfall.com/docs/api), free to
  use with a descriptive User-Agent and modest request rates.
- Riftbound via Riftcodex (https://api.riftcodex.com/docs), a community card
  database. Found by set + collector number, so it works for any language
  printing (a Korean card's OGN 114 is the same card as the English one).
"""

from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "SortBuddy/0.1 (personal card sorter)"
COLOR_NAMES = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


class LookupError_(RuntimeError):
    """The database couldn't be reached (offline, timeout...)."""


def _get(url: str, site: str = "Scryfall") -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise LookupError_(f"{site} error {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise LookupError_(f"can't reach {site} ({e})") from e
    finally:
        time.sleep(0.1)  # Scryfall asks for 50-100 ms between requests


def _same_name(a: str, b: str) -> bool:
    if not b.isascii():
        return True  # OCR read a non-English printing; can't compare names
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
        "game": "magic",
    }
    return {k: v for k, v in fields.items() if v not in (None, "", [])}


# Whole sets are downloaded once and kept on disk, so after the first card
# of a set every lookup is local (and works offline). Refreshed after a week
# so prices stay current.
CACHE_DIR = Path.home() / ".sortbuddy" / "cache"
CACHE_DAYS = 7
_set_cache: dict[str, list] = {}


def _cached_set(key: str, fetch) -> list:
    """A set's card list: from memory, else disk, else download. Old copies
    on disk are only replaced by a successful download, never deleted."""
    if key in _set_cache:
        return _set_cache[key]
    path = CACHE_DIR / f"{key}.json"
    stale = None
    try:
        stale = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - path.stat().st_mtime < CACHE_DAYS * 86400:
            _set_cache[key] = stale
            return stale
    except (OSError, ValueError):
        pass
    try:
        cards = fetch()
    except LookupError_:
        cards = []
    if not cards and stale:
        _set_cache[key] = stale  # offline or site down: the older copy is fine
        return stale
    _set_cache[key] = cards
    if cards:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cards), encoding="utf-8")
        except OSError:
            pass
    return cards


def _scryfall_set(set_code: str) -> list:
    """Every printing in a Magic set (a few requests, then cached)."""
    def fetch():
        cards = []
        url = f"https://api.scryfall.com/cards/search?q=e%3A{urllib.parse.quote(set_code.lower())}&unique=prints&order=set"
        while url:
            data = _get(url)
            if not data:
                break
            cards += data.get("data", [])
            url = data.get("next_page") if data.get("has_more") else None
        return cards
    return _cached_set(f"mtg-{set_code.upper()}", fetch)


def _best_name(cards: list, name: str, min_ratio: float = 0.75):
    """The card in `cards` whose name is closest to what OCR read."""
    if not name or not name.isascii():
        return None
    def norm(x):
        return re.sub(r"[^a-z0-9 ]", "", x.lower().split("//")[0]).strip()
    target = norm(name)
    best, best_ratio = None, 0.0
    for c in cards:
        r = difflib.SequenceMatcher(None, norm(c.get("name", "")), target).ratio()
        if r > best_ratio:
            best, best_ratio = c, r
    return best if best_ratio >= min_ratio else None


def scryfall(name: str, set_code: str | None = None, number: int | None = None,
             fuzzy: bool = True) -> tuple[dict, bool] | None:
    """Returns (fields, printing_confirmed). Without a set code that Scryfall
    recognises, the card is found by name and the printing is a guess."""
    api = "https://api.scryfall.com/cards"
    q = urllib.parse.quote
    if set_code and number is not None:
        same = [c for c in _scryfall_set(set_code) if c.get("collector_number") == str(number)]
        if not same:
            card = _get(f"{api}/{q(set_code.lower())}/{number}")
            same = [card] if card else []
        match = next((c for c in same if not name or _same_name(c["name"], name)), None)
        if match:
            return _fields(match), True
    if not name:
        return None
    if set_code:
        # Number missing or misread: match the name within the set, locally.
        match = _best_name(_scryfall_set(set_code), name)
        if match:
            return _fields(match), True
        for mode in ("exact", "fuzzy"):
            card = _get(f"{api}/named?{mode}={q(name)}&set={q(set_code.lower())}")
            if card:
                return _fields(card), True
    card = _get(f"{api}/named?{'fuzzy' if fuzzy else 'exact'}={q(name)}")
    return (_fields(card), False) if card else None


RIFTCODEX = "https://api.riftcodex.com"
# Each Riftbound domain has a color; saved as `colors` so one rule like
# "colors has blue" works for Magic and Riftbound cards alike.
DOMAIN_COLORS = {"fury": "red", "calm": "green", "mind": "blue", "body": "orange",
                 "chaos": "purple", "order": "yellow"}


def _riftcodex_set(set_code: str) -> list:
    """Every card in a Riftbound set (~4 requests, then cached)."""
    key = set_code.upper()

    def fetch():
        cards, page = [], 1
        while True:
            data = _get(f"{RIFTCODEX}/cards?set_id={urllib.parse.quote(key)}&size=100&page={page}", "Riftcodex")
            if not data:
                break
            cards += data.get("items", [])
            if page >= data.get("pages", 1):
                break
            page += 1
        return cards
    return _cached_set(f"riftbound-{key}", fetch)


def _riftcodex_fields(card: dict) -> dict:
    attrs = card.get("attributes") or {}
    cls = card.get("classification") or {}
    text = card.get("text") or {}
    st = card.get("set") or {}
    meta = card.get("metadata") or {}
    fields = {
        "name": card.get("name", ""),
        "set": st.get("set_id", "").upper(),
        "set_name": st.get("label", ""),
        "number": card.get("collector_number"),
        "rarity": (cls.get("rarity") or "").lower(),
        "domain": [d.lower() for d in cls.get("domain") or []],
        "type": cls.get("type", ""),
        "supertype": cls.get("supertype"),
        "cost": attrs.get("energy"),     # energy cost
        "energy": attrs.get("energy"),
        "power": attrs.get("power"),     # power (rune) cost
        "might": attrs.get("might"),
        "text": (text.get("plain") or "").replace("\n", " / "),
        "artist": (card.get("media") or {}).get("artist", ""),
        "tags": card.get("tags") or [],
        "variant": ", ".join(k for k in ("alternate_art", "overnumbered", "signature") if meta.get(k)),
        "colors": [DOMAIN_COLORS.get(d.lower(), d.lower()) for d in cls.get("domain") or []] or ["colorless"],
        "game": "riftbound",
    }
    return {k: v for k, v in fields.items() if v not in (None, "", [])}


def riftcodex(name: str, set_code: str | None = None, number: int | None = None,
              fuzzy: bool = True) -> tuple[dict, bool] | None:
    """Returns (fields, printing_confirmed), like scryfall()."""
    if set_code and number is not None:
        same = [c for c in _riftcodex_set(set_code) if c.get("collector_number") == number]
        if same:
            # The plain printing first; alternate art / signature share the number.
            same.sort(key=lambda c: sum(bool((c.get("metadata") or {}).get(k))
                                        for k in ("alternate_art", "overnumbered", "signature")))
            if not name or any(_same_name(c["name"], name) for c in same):
                match = next((c for c in same if not name or _same_name(c["name"], name)), same[0])
                return _riftcodex_fields(match), True
    if set_code and name:
        match = _best_name(_riftcodex_set(set_code), name)
        if match:
            return _riftcodex_fields(match), True
    if not name or not name.isascii():
        return None
    data = _get(f"{RIFTCODEX}/cards/name?{'fuzzy' if fuzzy else 'exact'}={urllib.parse.quote(name)}&size=5",
                "Riftcodex")
    items = (data or {}).get("items", []) if isinstance(data, dict) else data or []
    if not fuzzy:
        items = [c for c in items if _same_name(c.get("name", ""), name)]
    return (_riftcodex_fields(items[0]), False) if items else None


# Riftbound set codes (from Riftcodex /sets); anything else is tried as Magic.
RIFTBOUND_SETS = {"OGN", "OGS", "SFD", "UNL", "VEN", "OPP", "PR", "JDG"}


def auto(name: str, set_code: str | None = None, number: int | None = None) -> tuple[dict, bool] | None:
    """Pick the database from the set code: Riftbound sets go to Riftcodex,
    everything else to Scryfall (then Riftcodex by name as a last resort)."""
    if set_code and set_code.upper() in RIFTBOUND_SETS:
        return riftcodex(name, set_code, number) or scryfall(name, None, None, fuzzy=False)
    if set_code:
        # A set code we read is a Magic one (or unknown): stay in Magic, with an
        # exact-name fallback in case the set code itself was misread.
        return scryfall(name, set_code, number) or scryfall(name, None, None, fuzzy=False)
    # Only a name: an exact match in either game beats a fuzzy one.
    return (scryfall(name, fuzzy=False) or riftcodex(name, fuzzy=False)
            or scryfall(name) or riftcodex(name))


SOURCES = {
    "auto": ("Auto: Magic or Riftbound", auto),
    "mtg": ("Magic: The Gathering (Scryfall)", scryfall),
    "riftbound": ("Riftbound (Riftcodex)", riftcodex),
}


def card_id(fields: dict) -> str:
    n = fields.get("number")
    return f"{fields['set']}-{n:03d}" if isinstance(n, int) else f"{fields['set']}-{n}"
