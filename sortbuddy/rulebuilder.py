"""Build a sort rule by picking a field and how to match it, instead of typing.

This is the screen-free part: the fields, turning picks into a rule and a
plain-English description, and reading a saved rule back. The widget is in
gui_rules.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import lookup
from .catalog import Catalog
from .rules import Rule, RuleError


@dataclass
class FieldSpec:
    label: str
    key: str
    kind: str                      # "choice", "number" or "text"
    values: list = field(default_factory=list)  # suggested choices (your list adds more)
    contains: bool = False         # choice matched as "contains" (e.g. type lines)
    game: str = ""                 # only offered for this game ("" = always)


FIELDS = [
    FieldSpec("Game", "game", "choice", ["magic", "riftbound", "pokemon", "one piece", "lorcana", "yu-gi-oh"]),
    FieldSpec("Face up or down", "face", "choice", ["front", "back"]),
    FieldSpec("Rarity", "rarity", "choice",
              ["common", "uncommon", "rare", "mythic", "epic", "showcase", "special", "promo", "token", "land"]),
    FieldSpec("Cost (mana / energy)", "cost", "number"),
    FieldSpec("Color", "colors", "choice",
              ["white", "blue", "black", "red", "green", "orange", "purple", "yellow", "colorless"]),
    FieldSpec("Domain (Riftbound)", "domain", "choice", ["fury", "calm", "mind", "body", "chaos", "order"],
              game="riftbound"),
    FieldSpec("Card type", "type", "choice",
              ["Unit", "Spell", "Gear", "Rune", "Legend", "Battlefield",
               "Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Land", "Planeswalker", "Battle",
               "Legendary"], contains=True),
    FieldSpec("Set", "set", "choice"),
    FieldSpec("Price (USD)", "price", "number"),
    FieldSpec("Foil", "foil", "choice", ["yes", "no"]),
    FieldSpec("Language", "language", "choice", ["EN", "KR", "JP", "ZH", "FR", "DE", "ES", "IT", "PT"]),
    FieldSpec("Power", "power", "number"),
    FieldSpec("Might (Riftbound)", "might", "number", game="riftbound"),
    FieldSpec("Toughness (Magic)", "toughness", "number", game="magic"),
    FieldSpec("Keyword (Magic)", "keywords", "choice",
              ["Flying", "Flash", "Trample", "Deathtouch", "Haste", "Lifelink", "Reach", "Vigilance",
               "First strike", "Menace", "Ward", "Defender", "Hexproof", "Indestructible"], game="magic"),
    FieldSpec("Creature type (Magic)", "subtypes", "choice", game="magic"),
    FieldSpec("Collector number", "number", "number"),
    FieldSpec("Year", "year", "number"),
    FieldSpec("Name", "name", "text"),
    FieldSpec("Rules text", "text", "text"),
    FieldSpec("Artist", "artist", "text"),
]
BY_KEY = {f.key: f for f in FIELDS}
BY_LABEL = {f.label: f for f in FIELDS}

CHOICE_OPS = {"is any of": "in", "is none of": "not in"}
CONTAINS_OPS = {"is any of": "contains"}
NUMBER_OPS = {"at most": "<=", "at least": ">=", "exactly": "==", "less than": "<", "more than": ">"}
TEXT_OPS = {"contains": "contains"}


def visible_fields(game: str) -> list[FieldSpec]:
    """Fields to offer: game-specific ones only when that game is chosen.
    (Riftbound domains are also saved as colors, so Color covers both.)"""
    return [f for f in FIELDS if not f.game or f.game == game]


def ops_for(spec: FieldSpec) -> dict:
    if spec.kind == "number":
        return NUMBER_OPS
    if spec.kind == "text":
        return TEXT_OPS
    return CONTAINS_OPS if spec.contains else CHOICE_OPS


@dataclass
class Condition:
    key: str
    op: str                         # label, e.g. "is any of", "at most"
    values: list = field(default_factory=list)  # choices, or one number / text

    @property
    def spec(self) -> FieldSpec:
        return BY_KEY[self.key]

    def complete(self) -> bool:
        return bool([v for v in self.values if str(v).strip()])

    def rule_text(self) -> str:
        sym = ops_for(self.spec)[self.op]
        vals = [str(v).strip() for v in self.values if str(v).strip()]
        if sym in ("in", "not in"):
            return f"{self.key} {sym} {','.join(vals)}"
        if sym == "contains":
            return f"{self.key} contains {'|'.join(vals)}"
        return f"{self.key} {sym} {vals[0]}"

    def describe(self) -> str:
        label = self.spec.label.split(" (")[0]
        vals = [str(v).strip() for v in self.values if str(v).strip()]
        if self.spec.kind == "choice":
            shown = " or ".join(v if self.key in ("set", "language") else v.title() for v in vals)
            if self.key == "face":
                return "Card is " + " or ".join("face up" if v == "front" else "face down" for v in vals)
            verb = "is not" if self.op == "is none of" else "is"
            return f"{label} {verb} {shown}"
        if self.spec.kind == "text":
            return f"{label} contains “{vals[0]}”"
        return f"{label} {self.op} {vals[0]}"


def rule_text(conditions: list[Condition]) -> str:
    return " and ".join(c.rule_text() for c in conditions if c.complete())


def describe(conditions: list[Condition]) -> str:
    parts = [c.describe() for c in conditions if c.complete()]
    return ", and ".join(parts) if parts else ""


def from_rule(text: str) -> list[Condition] | None:
    """Read a saved rule back into conditions; None if it uses things the
    builder can't show (OR, unknown fields or operators)."""
    try:
        rule = Rule(text)
    except RuleError:
        return None
    if len(rule.groups) != 1:
        return None
    out = []
    for c in rule.groups[0]:
        spec = BY_KEY.get(c.field)
        if not spec:
            return None
        ops = {sym: label for label, sym in ops_for(spec).items()}
        if c.op not in ops:
            return None
        values = c.value if isinstance(c.value, list) else [c.value]
        out.append(Condition(spec.key, ops[c.op], [str(v) for v in values]))
    return out


def choices(spec: FieldSpec, catalog: Catalog | None) -> list[str]:
    """Suggested values plus whatever your list actually has, de-duplicated."""
    seen, out = set(), []

    def add(v):
        if v is None or v == "":
            return
        key = str(v).lower()
        if key not in seen:
            seen.add(key)
            out.append(str(v))
    for v in spec.values:
        add(v)
    if catalog is not None:
        for v in catalog.values(spec.key):
            add(v.title() if spec.key in ("subtypes", "keywords") and isinstance(v, str) else v)
    if spec.key == "set":
        for f in sorted(lookup.CACHE_DIR.glob("*.json")) if lookup.CACHE_DIR.exists() else []:
            add(f.stem.split("-", 1)[-1])
    return out
