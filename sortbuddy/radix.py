"""Full sorts on a two-pile machine, via binary radix sort.

A yes/no machine can put a stack into complete order, not just split it.
Give each value of the sort key a rank (0..k-1). On pass p, a card goes to
YES if bit p of its rank is 1. After each pass, restack with the NO pile
fed before the YES pile, keeping each pile's order. After ceil(log2(k))
passes the stack is sorted by rank: that's LSD radix sort, and it's stable,
so sorting by cost then by domain gives "by domain, then by cost within".

    cost 0..7  (8 values)  -> 3 passes
    6 domains + other      -> 3 passes
    collector #1..300      -> 9 passes

For this to work the machine must keep cards in order: the first card fed
into a pile ends up at the bottom of that pile, and the hopper feeds from
the bottom. Then "NO pile into the hopper first, YES pile on top of it".
"""

from __future__ import annotations

import math

from .catalog import Card

OTHER = "(other)"


class SortPlan:
    def __init__(self, key: str, values: list, other: bool = False):
        self.key = key
        # Ranks follow the given order. Unlisted values sort last, in their own
        # "(other)" bucket if asked for (it can cost an extra pass).
        self.values = list(values) + ([OTHER] if other else [])
        self._rank = {self._norm(v): i for i, v in enumerate(values)}

    @staticmethod
    def _norm(v):
        return v.lower() if isinstance(v, str) else v

    @property
    def passes(self) -> int:
        return max(1, math.ceil(math.log2(len(self.values))))

    def rank(self, card: Card) -> int:
        v = card.get(self.key)
        if isinstance(v, list):
            v = v[0] if v else None
        return self._rank.get(self._norm(v), len(self.values) - 1)

    def goes_yes(self, card: Card, pass_index: int) -> bool:
        return bool((self.rank(card) >> pass_index) & 1)

    def describe_pass(self, pass_index: int) -> list:
        """Values that go to the YES pile on this pass."""
        return [v for i, v in enumerate(self.values) if (i >> pass_index) & 1]


def simulate(plan: SortPlan, cards: list[Card]) -> list[Card]:
    """Run every pass in software; returns the final stack order."""
    stack = list(cards)
    for p in range(plan.passes):
        yes = [c for c in stack if plan.goes_yes(c, p)]
        no = [c for c in stack if not plan.goes_yes(c, p)]
        stack = no + yes
    return stack
