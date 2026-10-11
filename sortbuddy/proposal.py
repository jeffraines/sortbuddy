"""Turn what OCR read off a card (plus an optional database lookup) into a
suggested card id and catalog fields. Shared by the CLI and the window app."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import lookup


@dataclass
class Proposal:
    card_id: str
    fields: dict
    found: bool = False        # details came from the card database
    message: str = ""          # e.g. "Found: Reality Fracture #29"
    kind: str = ""             # "ok", "warn", "error" or "" (no lookup)
    foil: bool | None = None
    extra: dict = field(default_factory=dict)


def look_up(source, name: str, set_code, number) -> tuple[dict | None, str, str]:
    """Returns (fields or None, message, kind)."""
    if source is None or not (name or set_code):
        return None, "", ""
    try:
        found = source(name, set_code, number)
    except lookup.LookupError_ as e:
        return None, f"Lookup failed: {e}", "error"
    if not found:
        return None, "Not found in the card database", "warn"
    fields, confirmed = found
    if confirmed:
        return fields, f"Found: {fields.get('set_name', fields['set'])} #{fields['number']}", "ok"
    return fields, "Found by name only: check the set/number", "warn"


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()


def propose(text, name: str, auto_id: str, source=None, cache: dict | None = None) -> Proposal:
    """Suggest an id and fields for a captured card.

    `text` is the OCR result (or None), `name` the name guess to use (OCR
    can offer several). Lookups are cached per name in `cache`.
    """
    set_code = text.set_code if text else None
    number = text.number if text else None
    key = (name, set_code, number)
    if cache is not None and key in cache:
        info, message, kind = cache[key]
    else:
        info, message, kind = look_up(source, name, set_code, number)
        if cache is not None:
            cache[key] = (info, message, kind)

    if info:
        fields = dict(info)
        card_id = lookup.card_id(info)
    else:
        fields = {"name": name} if name else {}
        fields.update(text.extra if text else {})  # type line, P/T, artist read by OCR
        if set_code:
            fields["set"] = set_code
        if number is not None:
            fields["number"] = number
        if set_code and number is not None:
            card_id = f"{set_code}-{number:03d}"
        else:
            card_id = slug(name) or auto_id

    if text and text.extra.get("language"):
        fields["language"] = text.extra["language"]
    foil = text.foil if text else None
    if foil is not None:
        fields["foil"] = "yes" if foil else "no"
        if foil and "price_foil" in fields:
            fields["price"] = fields["price_foil"]  # price of the copy in hand
    return Proposal(card_id, fields, bool(info), message, kind, foil)
