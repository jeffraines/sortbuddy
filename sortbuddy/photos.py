"""Which cards get a full-size photo and which a small one."""

from __future__ import annotations

SMALL_SIZE = (252, 352)  # cheap cards: a small photo, enough to recognise it later
SMALL_QUALITY = 80  # ~15-25 KB a card
CHEAP_RARITIES = {"common", "uncommon", "c", "u"}  # when there's no price to go by


def photo_tier(fields: dict | None, threshold: float) -> str:
    """'full' or 'small' photo for a card. Worth `threshold` (USD) or more,
    or unknown (not identified, or no price and not a common): full."""
    if not fields:
        return "full"
    price = max((p for p in (fields.get("price"), fields.get("price_foil"))
                 if isinstance(p, (int, float))), default=None)
    if price is not None:
        return "full" if price >= threshold else "small"
    rarity = str(fields.get("rarity") or "").strip().lower()
    return "small" if rarity in CHEAP_RARITIES else "full"
