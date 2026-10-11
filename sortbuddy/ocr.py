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


# "029/298", "29 / 298"
_FRACTION = re.compile(r"(\d{1,4})\s*/\s*\d{1,4}")
# "C 0029", "0029", "R029": a rarity letter followed by the number
_NUMBER = re.compile(r"(?:^|\s|[A-Z])(\d{2,4})(?:\s|$)")
# 3-4 character set codes: FDN, OGN, SFD, BLB, M21... ("EN" etc. are language codes)
# (OCR often drops the space before the number: "OGN029/298")
_SET = re.compile(r"(?<![A-Z0-9])([A-Z][A-Z0-9]{2,3})(?![A-Z])")
_NOT_SETS = {"EN", "JP", "TM", "THE", "AND", "LLC", "INC"}


def _collector(lines: list[Line], card_h: int) -> tuple[str | None, int | None]:
    bottom = [ln for ln in lines if ln.y0 > 0.85 * card_h]
    set_code = number = None
    for ln in bottom:
        text = ln.text.upper().replace("•", " ").replace("·", " ")
        if number is None:
            m = _FRACTION.search(text) or _NUMBER.search(" " + text + " ")
            if m:
                number = int(m.group(1))
        if set_code is None:
            for code in _SET.findall(text):
                if sum(c.isalpha() for c in code) >= 2:
                    code = code[0] + code[1:].replace("0", "O")  # OCR reads O as zero
                if code not in _NOT_SETS:
                    set_code = code
                    break
    return set_code, number


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
    h = best_img.shape[0]
    set_code, number = _collector(best, h)
    return CardText(_name_candidates(best, h), set_code, number, best, best_img)
