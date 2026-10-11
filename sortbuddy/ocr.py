"""Read a card's name and set/collector number, so enrolling needs no typing.

Optional: needs `pip install rapidocr_onnxruntime` (bundles its models, no
separate install). Only used while enrolling, never per frame while sorting:
it takes around half a second a card.
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

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
    extra: dict = field(default_factory=dict)  # type line, power/toughness, artist, rules text
    foil: bool | None = None  # from the Magic bottom line: "LCI ★ EN" foil, "FRA • EN" not; None = can't tell
    lines: list[Line] = field(default_factory=list)
    upright: np.ndarray | None = None  # the card image turned the right way up
    local_names: list[str] = field(default_factory=list)  # name in the card's own language, e.g. Korean

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


_strip_engine = None


def _strip_ocr():
    """Same models, tuned for a thin strip: the default engine scales the
    *short* side up to 736 px, which makes a strip huge and slow."""
    global _strip_engine
    if _strip_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _strip_engine = RapidOCR(det_model_path=None, det_limit_type="max", det_limit_side_len=960)
        _strip_engine.use_angle_cls = False
    return _strip_engine


def installed() -> bool:
    """Is the OCR package there? (Doesn't load the models, which takes a moment.)"""
    import importlib.util
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def available() -> bool:
    try:
        _ocr()
        return True
    except OcrUnavailable:
        return False


# Extra text-recognition models for languages the default model can't read.
# Downloaded once, the first time a card in that language is captured, and
# checked against the hash of the file SortBuddy was tested with.
MODELS_DIR = Path.home() / ".sortbuddy" / "models"
_KOREAN = {
    "file": "korean_PP-OCRv5_rec_mobile.onnx",
    "url": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/master/"
           "onnx/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx",
    "sha256": "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b",
    "size_mb": 13,
    "script": re.compile("[\uac00-\ud7a3]"),  # Hangul syllables
}
LANGUAGE_MODELS = {"KR": _KOREAN, "KO": _KOREAN}
_lang_engines: dict[str, object] = {}


def _download_model(spec: dict) -> Path:
    path = MODELS_DIR / spec["file"]
    if path.exists():
        return path
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {spec['file']} ({spec['size_mb']} MB, one time)...")
    tmp = path.with_suffix(".part")
    req = urllib.request.Request(spec["url"], headers={"User-Agent": "SortBuddy/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    if digest != spec["sha256"]:
        tmp.unlink()
        raise OcrUnavailable(f"downloaded {spec['file']} doesn't match the expected file")
    tmp.replace(path)
    return path


def _language_engine(language: str):
    """OCR engine for a card language, or None if not needed / not available."""
    spec = LANGUAGE_MODELS.get(language)
    if spec is None:
        return None
    if spec["file"] not in _lang_engines:
        try:
            from rapidocr_onnxruntime import RapidOCR
            engine = RapidOCR(rec_model_path=str(_download_model(spec)))
            engine.use_angle_cls = False
        except Exception as e:  # noqa: BLE001 - offline etc.: carry on without it
            print(f"Can't read {language} text: {e}")
            return None
        _lang_engines[spec["file"]] = engine
    return _lang_engines[spec["file"]]


def _read(img: np.ndarray, engine=None) -> list[Line]:
    result, _ = (engine or _ocr())(img)
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
_LANGUAGE = re.compile(r"(?<![A-Z])(EN|JP|JA|DE|FR|ES|IT|PT|KO|KR|ZH|RU|CN)(?![A-Z])")
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
            next_to_lang = bool(re.match(r"\W{0,3}(EN|JP|JA|DE|FR|ES|IT|PT|KO|KR|ZH|RU|CN)(?![A-Z])", text[m.end():].lstrip()))
            score = (1 + 3 * has_lang + 3 * next_to_lang + (len(code) == 3)
                     + 2 * bool(re.search(r"\d{2,}", text)) - 2 * (words >= 3))
            if score > best_score:
                best_set, best_score = code, score
    # A line that *starts* with the number counts even if words follow:
    # "C 0015 Story Spotlight" (those words would make it look like prose).
    for ln in lines:
        if ln.y0 > 0.85 * card_h and ln.x0 < 0.5 * card_w and ln not in corner:
            m = re.match(r"\s*[CURMLTSP]?\s?(\d{2,4})(?!\d)(?!\s*/\s*\d)", ln.text)
            if m and not (len(m.group(1)) == 4 and 1990 <= int(m.group(1)) <= 2099):
                numbers.append((1 if m.group(1).startswith("0") else 2, int(m.group(1))))
    number = min(numbers)[1] if numbers else None
    return best_set, number


def _foil(lines: list[Line], card_h: int, card_w: int) -> bool | None:
    """Magic cards since 2023 mark foils in the bottom line: "LCI ★ EN" is
    foil, "LCI • EN" is not. Returns None when that mark wasn't read."""
    for ln in lines:
        if ln.y0 > 0.85 * card_h and ln.x0 < 0.5 * card_w and _LANGUAGE.search(ln.text):
            between = _LANGUAGE.split(ln.text)[0]
            # Only Magic's "SET ★ EN" layout: set code, mark, language. On
            # Riftbound ("OGN · 114/298 · KR") the dots are just separators.
            m = re.search(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{2,3}\s*([★☆✩✪*•·.∙])\s*$", between)
            if m:
                return m.group(1) in "★☆✩✪*"
    return None


# Magic's rarity letter before the collector number: "C 0029"
_RARITY = {"C": "common", "U": "uncommon", "R": "rare", "M": "mythic", "L": "land",
           "T": "token", "S": "special", "P": "promo"}


def _details(lines: list[Line], card_h: int, card_w: int) -> dict:
    """What can be read straight off the card without a database: the type
    line, power/toughness, artist and rules text. The mana cost is symbols,
    not text, so it needs the lookup."""
    out = {}
    for ln in sorted(lines, key=lambda ln: ln.y0):
        t = ln.text.strip()
        mid = 0.45 * card_h < ln.y0 < 0.7 * card_h
        if "type" not in out and mid and re.search(r"\s[—–-]\s?|[A-Za-z][—–]", t) and sum(c.isalpha() for c in t) >= 5:
            out["type"] = re.sub(r"\s*[—–-]\s*", " — ", _respace(t), count=1)
        m = re.fullmatch(r"(\d{1,2}|\*)\s*/\s*(\d{1,2}|\*)", t)
        if m and ln.x0 > 0.6 * card_w and ln.y0 > 0.75 * card_h:
            out["power"], out["toughness"] = (int(g) if g.isdigit() else g for g in m.groups())
        r = re.match(r"([CURMLTSP])\s?\d{2,4}\b", t)
        if r and ln.y0 > 0.85 * card_h and ln.x0 < 0.5 * card_w:
            out["rarity"] = _RARITY[r.group(1)]
        if ln.y0 > 0.85 * card_h and ln.x0 < 0.5 * card_w and _LANGUAGE.search(t):
            out.setdefault("language", _LANGUAGE.search(t).group(1))
            artist = _LANGUAGE.split(t, maxsplit=1)[-1]
            artist = re.sub(r"^[^A-Za-z]+", "", artist).strip()
            if len(artist) >= 4:
                out["artist"] = artist.title()
    body = [ln.text for ln in sorted(lines, key=lambda ln: ln.y0)
            if 0.57 * card_h < ln.y0 < 0.85 * card_h and ln.x0 < 0.5 * card_w
            and (_is_prose(ln.text) or ln.text.istitle())]
    if body and "type" in out:
        out["text"] = " / ".join(body)
    return out


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


STRIP_TOP = 0.86  # the collector line lives in the bottom ~14% of the card


def read_collector(card: np.ndarray) -> CardText:
    """Fast path (~0.1-0.2 s): read only the bottom strip, both ways up, for
    set code, number, language, rarity letter and foil mark. No name."""
    h, w = card.shape[:2]
    top = int(STRIP_TOP * h)
    best = (None, -1, card)
    for img in (card, cv2.rotate(card, cv2.ROTATE_180)):
        lines = _read(img[top:], _strip_ocr())
        for ln in lines:  # back to whole-card coordinates
            ln.y0 += top
            ln.y1 += top
        set_code, number = _collector(lines, h, w)
        score = 2 * (number is not None) + 2 * (set_code is not None) + bool(_LANGUAGE.search(" ".join(l.text for l in lines)))
        if score > best[1]:
            best = (lines, score, img)
    lines, _, img = best
    set_code, number = _collector(lines, h, w)
    return CardText([], set_code, number, _details(lines, h, w), _foil(lines, h, w), lines, img)


def read_card(card: np.ndarray, local_names: bool = True) -> CardText:
    """OCR a flattened card. Tries both ways up and keeps whichever reads better."""
    best, best_score, best_img = None, -1.0, card
    for img in (card, cv2.rotate(card, cv2.ROTATE_180)):
        lines = _read(img)
        score = sum(ln.score * len(ln.text) for ln in lines)
        if score > best_score:
            best, best_score, best_img = lines, score, img
    h, w = best_img.shape[:2]
    set_code, number = _collector(best, h, w)
    details = _details(best, h, w)
    names = _name_candidates(best, h)
    printed_names = []
    language = details.get("language", "EN")
    if language != "EN":
        # The default model reads English (and Chinese); on e.g. a Korean card
        # its name guesses are junk. Read the card again with that language's
        # model for the printed name; the lookup supplies the English one.
        names = [n for n in names if n.isascii()]
        engine = _language_engine(language) if local_names else None
        if engine is not None:
            script = LANGUAGE_MODELS[language]["script"]
            printed_names = [n for n in _name_candidates(_read(best_img, engine), h) if script.search(n)]
    return CardText(names, set_code, number, details, _foil(best, h, w), best, best_img, printed_names)
