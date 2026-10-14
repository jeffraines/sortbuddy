"""US market prices and their history, kept on your own computer.

Prices come from TCGCSV (tcgcsv.com), a free daily copy of TCGplayer's
prices. TCGCSV keeps only today's prices, so SortBuddy stores one snapshot a
day in a small SQLite file; the history (and so the trends) grows from the
day you start. Run `sortbuddy prices update` once a day (or let the app do it).

Matching a card to a TCGplayer product: by game, set code and collector
number. One card number can have several products (normal, parallel / alt
art, SP...), and SortBuddy can't yet tell those apart, so a lookup returns the
cheapest (`base`) and the dearest (`top`) printing.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

BASE = "https://tcgcsv.com/tcgplayer"
USER_AGENT = "SortBuddy/0.1 (personal card sorter; github.com/jeffraines/sortbuddy)"
PAUSE = 0.25  # seconds between requests, as TCGCSV asks
CATEGORIES = {"onepiece": 68, "pokemon": 3, "pokemon-jp": 85, "riftbound": 89, "magic": 1}
DEFAULT_DB = Path.home() / ".sortbuddy" / "prices.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY, game TEXT, group_id INTEGER, set_code TEXT, set_name TEXT,
    name TEXT, number TEXT, num INTEGER, rarity TEXT, url TEXT);
CREATE INDEX IF NOT EXISTS products_lookup ON products (game, num);
CREATE TABLE IF NOT EXISTS prices (
    day TEXT, product_id INTEGER, subtype TEXT, market REAL, low REAL, mid REAL,
    PRIMARY KEY (day, product_id, subtype));
CREATE TABLE IF NOT EXISTS updates (game TEXT, day TEXT, PRIMARY KEY (game, day));
"""


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def _get(url: str, tries: int = 3) -> list[dict]:
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r).get("results") or []
        except (OSError, ValueError):
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return []


def card_number(number: str) -> int | None:
    """The collector number as an int: 'OP09-004' -> 4, '001/298' -> 1, '123a' -> 123."""
    if not number:
        return None
    part = number.split("-")[-1].split("/")[0]
    m = re.match(r"\D*(\d+)", part)
    return int(m.group(1)) if m else None


def _extended(product: dict) -> dict:
    return {e.get("name"): e.get("value") for e in product.get("extendedData") or []}


def update(db: sqlite3.Connection, games: list[str], day: str | None = None,
           progress=print, fetch=_get) -> int:
    """Download today's prices for `games` (keys of CATEGORIES). Skips a game
    already updated today. Returns the number of price rows stored."""
    day = day or date.today().isoformat()
    stored = 0
    for game in games:
        if db.execute("SELECT 1 FROM updates WHERE game=? AND day=?", (game, day)).fetchone():
            progress(f"{game}: already up to date for {day}")
            continue
        cat = CATEGORIES[game]
        groups = fetch(f"{BASE}/{cat}/groups")
        progress(f"{game}: {len(groups)} sets")
        for i, g in enumerate(groups, 1):
            gid = g["groupId"]
            products = fetch(f"{BASE}/{cat}/{gid}/products")
            time.sleep(PAUSE)
            prices = fetch(f"{BASE}/{cat}/{gid}/prices")
            time.sleep(PAUSE)
            rows = []
            for p in products:
                ext = _extended(p)
                number = ext.get("Number") or ""
                if not number:
                    continue  # sealed product (boxes, packs, decks)
                rows.append((p["productId"], game, gid, g.get("abbreviation") or "", g.get("name") or "",
                             p.get("name") or "", number, card_number(number), ext.get("Rarity") or "",
                             p.get("url") or ""))
            db.executemany("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            cards = {r[0] for r in rows}
            price_rows = [(day, q["productId"], q.get("subTypeName") or "Normal", q.get("marketPrice"),
                           q.get("lowPrice"), q.get("midPrice"))
                          for q in prices if q.get("productId") in cards]
            db.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?)", price_rows)
            stored += len(price_rows)
            if i % 10 == 0 or i == len(groups):
                progress(f"{game}: {i}/{len(groups)} sets")
        db.execute("INSERT OR REPLACE INTO updates VALUES (?,?)", (game, day))
        db.commit()
    return stored


@dataclass
class Price:
    base: float | None          # cheapest printing with this number (market price, USD)
    top: float | None           # dearest printing (alt art / parallel / SP)
    product_id: int | None      # the base printing
    name: str = ""
    day: str = ""


def _latest_day(db: sqlite3.Connection) -> str | None:
    row = db.execute("SELECT max(day) FROM prices").fetchone()
    return row[0] if row else None


def find_products(db: sqlite3.Connection, game: str, set_code: str | None, number: int | None,
                  name: str = "") -> list[tuple]:
    """Products for a card. One Piece numbers carry their set ('OP09-004'),
    also when reprinted in another set; other games go by the set's code."""
    if number is None:
        return []
    rows = db.execute("SELECT product_id, set_code, name, number FROM products WHERE game=? AND num=?",
                      (game, number)).fetchall()
    if set_code:
        sc = set_code.upper()
        if game == "onepiece":
            rows = [r for r in rows if r[3].upper().startswith(sc + "-")]
        else:
            rows = [r for r in rows if r[1].upper() == sc]
    if name and len(rows) > 1:
        key = re.sub(r"\W", "", name.lower())
        same = [r for r in rows if re.sub(r"\(.*?\)|\W", "", r[2].lower()).startswith(key[:12])]
        rows = same or rows
    return rows


def price_for(db: sqlite3.Connection, game: str, set_code: str | None, number: int | None,
              name: str = "", day: str | None = None) -> Price | None:
    rows = find_products(db, game, set_code, number, name)
    if not rows:
        return None
    day = day or _latest_day(db)
    found = []
    for pid, _, pname, _ in rows:
        r = db.execute("SELECT min(market) FROM prices WHERE product_id=? AND day=? AND market IS NOT NULL",
                       (pid, day)).fetchone()
        if r and r[0] is not None:
            found.append((r[0], pid, pname))
    if not found:
        return Price(None, None, rows[0][0], rows[0][2], day or "")
    found.sort()
    return Price(found[0][0], found[-1][0], found[0][1], found[0][2], day or "")


def history(db: sqlite3.Connection, product_id: int) -> list[tuple[str, float]]:
    return db.execute("SELECT day, min(market) FROM prices WHERE product_id=? AND market IS NOT NULL "
                      "GROUP BY day ORDER BY day", (product_id,)).fetchall()


@dataclass
class Trend:
    now: float | None
    change_7d: float | None    # fraction, 0.25 = +25%
    change_30d: float | None
    comeback: bool             # fell or stayed flat for months, now rising fast
    days: int                  # how much history there is


def _price_on_or_before(hist: list[tuple[str, float]], day: str) -> float | None:
    best = None
    for d, p in hist:
        if d <= day:
            best = p
        else:
            break
    return best


def trend(hist: list[tuple[str, float]], today: str | None = None,
          rise: float = 0.3, quiet_days: int = 60) -> Trend:
    """Price changes, and the 'comeback' flag: the price was at or below its
    level of `quiet_days` ago for that whole stretch (forgotten), and has
    risen at least `rise` in the last two weeks (relevant again)."""
    if not hist:
        return Trend(None, None, None, False, 0)
    today = today or hist[-1][0]
    now = _price_on_or_before(hist, today)
    t = date.fromisoformat(today)

    def change(days: int) -> float | None:
        before = _price_on_or_before(hist, (t - timedelta(days=days)).isoformat())
        return (now / before - 1) if (now is not None and before) else None

    first = date.fromisoformat(hist[0][0])
    comeback = False
    start = (t - timedelta(days=quiet_days + 14)).isoformat()
    turn = (t - timedelta(days=14)).isoformat()
    quiet = [p for d, p in hist if start <= d <= turn]
    if now and quiet and (t - first).days >= quiet_days + 14:
        low = min(quiet)
        stayed_down = max(quiet) <= quiet[0] * 1.1  # no rally during the quiet stretch
        comeback = stayed_down and low > 0 and now >= low * (1 + rise)
    return Trend(now, change(7), change(30), comeback, (t - first).days)


def movers(db: sqlite3.Connection, game: str, max_price: float | None = None, min_price: float = 0.25,
           limit: int = 50) -> list[dict]:
    """Cards of a game whose price rose most over 7 and 30 days, comebacks
    first. For a buy watchlist: set `max_price` to look only at cheap cards."""
    day = _latest_day(db)
    if not day:
        return []
    rows = db.execute("SELECT p.product_id, p.name, p.set_code, p.number, p.rarity, min(q.market) "
                      "FROM products p JOIN prices q ON q.product_id=p.product_id "
                      "WHERE p.game=? AND q.day=? AND q.market IS NOT NULL GROUP BY p.product_id",
                      (game, day)).fetchall()
    out = []
    for pid, name, set_code, number, rarity, now in rows:
        if now < min_price or (max_price is not None and now > max_price):
            continue
        tr = trend(history(db, pid), day)
        if tr.change_7d is None and tr.change_30d is None:
            continue
        out.append({"product_id": pid, "name": name, "set": set_code, "number": number, "rarity": rarity,
                    "price": now, "change_7d": tr.change_7d, "change_30d": tr.change_30d,
                    "comeback": tr.comeback, "history_days": tr.days})
    out.sort(key=lambda r: (not r["comeback"], -(r["change_30d"] or r["change_7d"] or 0)))
    return out[:limit]


GAMES_BY_FIELD = {"onepiece": "onepiece", "one piece": "onepiece", "pokemon": "pokemon",
                  "riftbound": "riftbound", "magic": "magic"}


def card_key(fields: dict) -> tuple[str, str | None, int | None, str] | None:
    """(game, set code, number, name) for a catalog card, or None if the game isn't priced."""
    game = GAMES_BY_FIELD.get(str(fields.get("game") or "").lower())
    if not game:
        return None
    lang = str(fields.get("language") or "").lower()
    if game == "pokemon" and lang in ("ja", "jp"):
        game = "pokemon-jp"
    number = fields.get("number")
    if isinstance(number, str):
        number = card_number(number)
    return game, (str(fields.get("set") or "") or None), number, str(fields.get("name") or "")


def owned_report(db: sqlite3.Connection, cards: list[tuple[str, dict, int]]) -> list[dict]:
    """Price, trend and comeback flag for cards you own: [(id, fields, quantity)]."""
    out = []
    day = _latest_day(db)
    for card_id, fields, qty in cards:
        key = card_key(fields)
        pr = price_for(db, *key) if key else None
        tr = trend(history(db, pr.product_id), day) if pr and pr.product_id else None
        out.append({"id": card_id, "name": fields.get("name", ""), "quantity": qty,
                    "price": pr.base if pr else None, "top_printing": pr.top if pr else None,
                    "value": (pr.base or 0) * qty if pr else None,
                    "change_7d": tr.change_7d if tr else None, "change_30d": tr.change_30d if tr else None,
                    "comeback": bool(tr and tr.comeback), "matched": pr.name if pr else ""})
    out.sort(key=lambda r: (not r["comeback"], -(r["value"] or 0)))
    return out
