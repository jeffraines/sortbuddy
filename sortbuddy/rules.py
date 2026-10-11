"""Yes/no sort rules.

The machine has two output piles, so every pass answers one question about
each card. Rules are small expressions over catalog fields:

    set == OGN
    cost <= 3
    rarity in rare,epic
    domain has fury
    text contains draw a card
    set == OGN and rarity != common
    domain has fury or domain has calm

String comparisons are case-insensitive. `has` checks membership in a
list-valued field (a card with domains [fury, chaos] "has fury");
`contains` matches part of the text ("text contains flash"). `and`
binds tighter than `or`. No parentheses: if you need them, do two passes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .catalog import Card, _coerce

_CLAUSE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*(<=|>=|!=|==|=|<|>|\bin\b|\bhas\b|\bcontains\b)\s*(.+?)\s*$")


class RuleError(ValueError):
    pass


def _norm(v):
    return v.lower() if isinstance(v, str) else v


@dataclass
class Clause:
    field: str
    op: str
    value: object

    def test(self, card: Card) -> bool:
        actual = card.get(self.field)
        if actual is None:
            return self.op == "!="
        if self.op == "contains":
            items = actual if isinstance(actual, list) else [actual]
            return any(str(self.value).lower() in str(x).lower() for x in items)
        if self.op == "has":
            items = actual if isinstance(actual, list) else [actual]
            return _norm(self.value) in [_norm(x) for x in items]
        if self.op == "in":
            options = [_norm(x) for x in self.value]
            if isinstance(actual, list):
                return any(_norm(a) in options for a in actual)
            return _norm(actual) in options
        a, b = _norm(actual), _norm(self.value)
        if self.op == "==":
            return a == b
        if self.op == "!=":
            return a != b
        try:
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[self.op]
        except TypeError:
            return False


class Rule:
    """A parsed rule: OR of ANDs of clauses."""

    def __init__(self, text: str):
        self.text = text.strip()
        if not self.text:
            raise RuleError("empty rule")
        self.groups: list[list[Clause]] = []
        for group in re.split(r"\s+or\s+", self.text, flags=re.I):
            clauses = []
            for part in re.split(r"\s+and\s+", group, flags=re.I):
                m = _CLAUSE.match(part)
                if not m:
                    raise RuleError(f"can't parse {part!r} (expected e.g. 'cost <= 3')")
                field, op, raw = m.groups()
                op = "==" if op == "=" else op.lower()
                if op == "in":
                    value = [_coerce(x) for x in raw.split(",") if x.strip()]
                else:
                    value = _coerce(raw.strip("'\""))
                clauses.append(Clause(field, op, value))
            self.groups.append(clauses)

    def __call__(self, card: Card) -> bool:
        return any(all(c.test(card) for c in g) for g in self.groups)

    def __str__(self) -> str:
        return self.text
