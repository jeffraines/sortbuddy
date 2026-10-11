"""Read a card's name and set/collector number, so enrolling needs no typing.

Optional: needs `pip install rapidocr_onnxruntime` (bundles its models, no
separate install). Only used while enrolling, never per frame while sorting:
it takes around half a second a card.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np


class OcrUnavailable(RuntimeError):
    pass


@dataclass
class Line:
    text: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class CardText:
    names: list[str] = field(default_factory=list)  # best guess first
    set_code: str | None = None
    number: int | None = None
    foil: bool | None = None  # from the Magic bottom line: "LCI ★ EN" foil, "FRA • EN" not; None = can't tell
    lines: list[Line] = field(default_factory=list)
    upright: np.ndarray | None = None  # the card image turned the right way up

    @property
    def name(self) -> str:
        return self.names[0] if self.names else ""

    def card_id(self) -> str:
        if self.set_code and self.number is not None:
            return f"{self.set_code}-{self.number:03d}"
        if self.name:
            return re.sub(r"[^A-Za-z0-9]+", "-", self.name).strip("-").lower()
        return ""


_engine = None


def _ocr():
    global _engine
    if _engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as e:
            raise OcrUnavailable("pip install rapidocr_onnxruntime") from e
        _engine = RapidOCR()
        # We decide orientation for the whole card ourselves (below), so
        # per-line rotation guessing would only hide upside-down cards.
        _engine.use_angle_cls = False
    return _engine


def available() -> bool:
    try:
        _ocr()
        return True
    except OcrUnavailable:
        return False


def _read(img: np.ndarray) -> list[Line]:
    result, _ = _ocr()(img)
    lines = []
    for box, text, score in result or []:
        pts = np.array(box, dtype=np.float32)
        lines.append(Line(text.strip(), float(score), *pts.min(axis=0), *pts.max(axis=0)))
    return lines


# Collector info sits in the bottom-left corner on Magic, Riftbound and
# Pokemon cards, e.g. Magic "C 0029" / "FRA • EN", Riftbound "OGN • 029/298".
# The same corner can also hold flavor text, the artist and the copyright
# line, and power/toughness ("3/2") sits just right of it, so each guess is
# scored rather than taking the first match.

# "029/298", "29 / 298" (but not a power/toughness like "3/2")
_FRACTION = re.compile(r"(?<!\d)(\d{1,4})\s*/\s*(\d{1,4})(?!\d)")
# "C 0029", "0029", "R029": an optional rarity letter, then the number
_NUMBER = re.compile(r"(?:^|\s|(?<=[A-Z]))(\d{2,4})(?=\s|$)")
# 3-4 character set codes: FRA, FDN, OGN, SFD, M21... Matched case-sensitively:
# set codes are printed in capitals, sentence words like "They" aren't.
# (OCR often drops the space before the number: "OGN029/298")
_SET = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{2,3})(?![A-Za-z])")
_LANGUAGE = re.compile(r"(?<![A-Z])(EN|JP|JA|DE|FR|ES|IT|PT|KO|ZH|RU|CN)(?![A-Z])")
_NOT_SETS = {"THE", "AND", "LLC", "INC", "TM"}


def _is_prose(text: str) -> bool:
    """Flavor text, artist credits, copyright: not collector info."""
    letters = [c for c in text if c.isalpha()]
    lower = sum(c.islower() for c in letters)
    return "©" in text or (len(letters) > 3 and lower > 0.4 * len(letters))


def _collector(lines: list[Line], card_h: int, card_w: int) -> tuple[str | None, int | None]:
    # A line with a language code is collector info even if OCR also merged
    # the artist ("FRA • EN David Auden Nash") into it.
    corner = [ln for ln in lines
              if ln.y0 > 0.85 * card_h and ln.x0 < 0.5 * card_w
              and (_LANGUAGE.search(ln.text) or not _is_prose(ln.text))]
    best_set, best_score = None, 0
    numbers: list[tuple[int, int]] = []  # (priority, number)
    for ln in corner:
        text = re.sub(r"[•·★☆✩✪*∙]", " ", ln.text)
        words = len(re.findall(r"[A-Za-z]{2,}", text))
        has_lang = bool(_LANGUAGE.search(text))

        for m in _FRACTION.finditer(text):
            if len(m.group(1)) >= 2 or len(m.group(2)) >= 2:
                numbers.append((0, int(m.group(1))))
        for m in _NUMBER.finditer(text):
            digits = m.group(1)
            if not (1990 <= int(digits) <= 2099 and len(digits) == 4):  # not a year
                numbers.append((1 if digits.startswith("0") else 2, int(digits)))

        for m in _SET.finditer(text):
            code = m.group(1)
            if text[m.end():m.end() + 1].isdigit():
                # Runs straight into a number: "OGN029/298", "C0029" (rarity C,
                # number 0029). Trailing digits belong to the number.
                code = code.rstrip("0123456789")
            if len(code) < 3:
                continue
            if sum(c.isalpha() for c in code) >= 2:
                code = code[0] + code[1:].replace("0", "O")  # OCR reads O as zero
            if code in _NOT_SETS or _LANGUAGE.fullmatch(code):
                continue
            next_to_lang = bool(re.match(r"\W{0,3}(EN|JP|JA|DE|FR|ES|IT|PT|KO|ZH|RU|CN)(?![A-Z])", text[m.end():].lstrip()))
            score = (1 + 3 * has_lang + 3 * next_to_lang + (len(code) == 3)
                     + 2 * bool(re.search(r"\d{2,}", text)) - 2 * (words >= 3))
            if score > best_score:
                best_set, best_score = code, score
    number = min(numbers)[1] if numbers else None
    return best_set, number


def _foil(lines: list[Line], card_h: int, card_w: int) -> bool | None:
    """Magic cards since 2023 mark foils in the bottom line: "LCI ★ EN" is
    foil, "LCI • EN" is not. Returns None when that mark wasn't read."""
    for ln in lines:
        if ln.y0 > 0.85 * card_h and ln.x0 < 0.5 * card_w and _LANGUAGE.search(ln.text):
            between = _LANGUAGE.split(ln.text)[0]
            if re.search(r"[★☆✩✪*]", between):
                return True
            if re.search(r"[A-Z0-9]\s*[•·.∙]\s*$", between):
                return False
    return None


def _respace(text: str) -> str:
    """Put back spaces the OCR model drops: "DiviningDuelist" -> "Divining Duelist"."""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _name_candidates(lines: list[Line], card_h: int) -> list[str]:
    """Card names are usually the biggest text on the card; ties go to the
    higher line. Returns every plausible line, best first."""
    words = [ln for ln in lines
             if ln.score >= 0.5 and sum(c.isalpha() for c in ln.text) >= 3 and ln.y0 < 0.85 * card_h]
    if not words:
        return []
    tallest = max(ln.height for ln in words)
    big = sorted((ln for ln in words if ln.height >= 0.85 * tallest), key=lambda ln: ln.y0)
    rest = sorted((ln for ln in words if ln.height < 0.85 * tallest), key=lambda ln: -ln.height)
    seen, out = set(), []
    for ln in big + rest:
        name = _respace(ln.text)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def read_card(card: np.ndarray) -> CardText:
    """OCR a flattened card. Tries both ways up and keeps whichever reads better."""
    best, best_score, best_img = None, -1.0, card
    for img in (card, cv2.rotate(card, cv2.ROTATE_180)):
        lines = _read(img)
        score = sum(ln.score * len(ln.text) for ln in lines)
        if score > best_score:
            best, best_score, best_img = lines, score, img
    h, w = best_img.shape[:2]
    set_code, number = _collector(best, h, w)
    return CardText(_name_candidates(best, h), set_code, number, _foil(best, h, w), best, best_img)
