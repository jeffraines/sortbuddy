"""SortBuddy as one window: camera view, card details and sorting together.

Start it with `sortbuddy-gui`, or double-click SortBuddy.bat on Windows.

Layout: settings on the left, the live camera in the middle, and on the
right either what was read off the captured card (Add cards) or a big
YES / NO (Sort). Closing the window always stops the camera cleanly.
"""

from __future__ import annotations

import difflib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np

from . import cli, lookup, ocr
from .camera import Camera
from .catalog import Card, Catalog
from .fingerprint import FingerprintIndex, hamming, phash
from .identify import Identifier
from .proposal import propose
from .rules import Rule, RuleError
from .session import Session
from .vision import extract_card

SETTINGS = Path.home() / ".sortbuddy-gui.json"
# Fields card lookups and OCR fill in, so rules can be checked before any card is known.
KNOWN_FIELDS = {"id", "name", "set", "set_name", "number", "rarity", "cost", "mana_cost", "colors",
                "color_identity", "type", "card_types", "subtypes", "power", "toughness", "keywords", "text",
                "artist", "year", "price", "price_foil", "foil", "language", "domain", "supertype", "energy",
                "might", "tags", "variant", "name_kr"}
NO_LOOKUP = "Off (fill in details yourself)"
DEFAULTS = {"catalog": str(Path("mycards") / "catalog.csv"), "camera": 0, "focus": "",
            "rule": "cost <= 3", "lookup": "auto", "version": 2}

# Colors
BG, SIDE, PANEL, LINE = "#121419", "#1a1d24", "#20242d", "#2c313c"
FG, DIM, FAINT = "#e9eaee", "#9aa0ae", "#5d6371"
ACCENT, GREEN, RED, AMBER = "#4f8cff", "#3ecf6e", "#ef5b5b", "#f5b942"
KIND_COLORS = {"ok": GREEN, "warn": AMBER, "error": RED, "": DIM}
FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"

# What the details panel shows, roughly in the order the parts appear on a
# card. Rows without a value for the current card are hidden, so Magic and
# Riftbound cards each show their own parts.
def _join(v):
    return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)


CARD_PARTS = [
    ("Name on card", lambda f: next((v for k, v in f.items() if k.startswith("name_")), "")),
    ("Mana cost", lambda f: " ".join(x for x in (f.get("mana_cost"), f"(total {f['cost']})" if "cost" in f else "") if x)
     if "mana_cost" in f else ""),
    ("Energy", lambda f: _join(f.get("energy", ""))),
    ("Power", lambda f: _join(f["power"]) if "power" in f and "toughness" not in f else ""),
    ("Might", lambda f: _join(f.get("might", ""))),
    ("Type", lambda f: " ".join(x for x in (f.get("supertype"), f.get("type")) if x)),
    ("Domain", lambda f: _join(f.get("domain", [])).title()),
    ("Colors", lambda f: _join(f.get("colors", [])).title()),
    ("Rules text", lambda f: f.get("text", "").replace(" / ", "\n")),
    ("Power / toughness", lambda f: f"{f['power']} / {f['toughness']}" if "toughness" in f else ""),
    ("Set", lambda f: " · ".join(str(x) for x in (f.get("set_name"), f.get("set")) if x)),
    ("Number", lambda f: str(f.get("number", ""))),
    ("Rarity", lambda f: str(f.get("rarity", "")).title()),
    ("Variant", lambda f: str(f.get("variant", "")).replace("_", " ")),
    ("Language", lambda f: {"EN": "English", "KR": "Korean", "KO": "Korean", "JP": "Japanese", "JA": "Japanese",
                            "ZH": "Chinese", "CN": "Chinese", "DE": "German", "FR": "French", "ES": "Spanish",
                            "IT": "Italian", "PT": "Portuguese", "RU": "Russian"}.get(f.get("language", ""), "")),
    ("Foil", lambda f: {"yes": "Yes (★ on bottom line)", "no": "No (• on bottom line)"}.get(f.get("foil", ""), "")),
    ("Artist", lambda f: f.get("artist", "")),
    ("Year", lambda f: str(f.get("year", ""))),
    ("Price", lambda f: f"${f['price']:.2f}" if isinstance(f.get("price"), (int, float)) else ""),
]


def to_photo(frame: np.ndarray, max_w: int, max_h: int) -> tk.PhotoImage:
    """BGR image -> Tk image scaled to fit, via PPM (no Pillow needed)."""
    h, w = frame.shape[:2]
    scale = min(max_w / w, max_h / h)
    if scale <= 0:
        scale = 1.0
    if abs(scale - 1.0) > 0.01:
        frame = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))),
                           interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return tk.PhotoImage(data=f"P6 {w} {h} 255 ".encode() + rgb.tobytes(), format="PPM")


class QueueWriter:
    """print() output from any thread -> the log box (via a queue)."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s: str) -> None:
        if s and s != "\a":
            self.q.put(("log", s))

    def flush(self) -> None:
        pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = self._load_settings()
        self.events: queue.Queue = queue.Queue()  # (kind, payload) from worker threads
        self.cam: Camera | None = None
        self.mode: str | None = None  # None, "enroll" or "sort"
        self.loop_id = None
        self.photo = None
        self.found = None  # latest (warped card, corners) from the camera
        self.pending = None  # captured card waiting to be saved
        self.added = 0
        self.busy = False

        root.title("SortBuddy")
        root.configure(bg=BG)
        root.minsize(1100, 680)
        self._style()
        self._layout()
        self._maximize()

        sys.stdout = sys.stderr = QueueWriter(self.events)
        root.bind_all("<KeyPress>", self.on_key)
        root.bind_all("<Tab>", self.on_key)  # Tk's own Tab binding would win over <KeyPress>
        self._no_button_focus(root)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.catalog_var.trace_add("write", lambda *_: self.refresh_count())
        self.refresh_count()
        self.show_panel("idle")
        root.after(50, self.poll)

    # ------------------------------------------------------------------ look
    def _style(self) -> None:
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=SIDE, foreground=FG, fieldbackground=PANEL, bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE, troughcolor=PANEL, font=(FONT, 10))
        s.configure("TFrame", background=SIDE)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("Main.TFrame", background=BG)
        s.configure("TLabel", background=SIDE, foreground=FG)
        s.configure("Panel.TLabel", background=PANEL)
        s.configure("Dim.TLabel", foreground=DIM)
        s.configure("PanelDim.TLabel", background=PANEL, foreground=DIM, font=(FONT, 9))
        s.configure("Title.TLabel", font=(FONT, 20, "bold"))
        s.configure("Section.TLabel", foreground=DIM, font=(FONT, 9, "bold"))
        s.configure("Heading.TLabel", background=PANEL, font=(FONT, 16, "bold"))
        s.configure("TButton", background=PANEL, foreground=FG, padding=(12, 7), borderwidth=1, focusthickness=0)
        s.map("TButton", background=[("active", LINE), ("disabled", SIDE)], foreground=[("disabled", FAINT)])
        for name, color in (("Accent", ACCENT), ("Go", GREEN), ("Stop", RED)):
            s.configure(f"{name}.TButton", background=color, foreground="#0b0d12", font=(FONT, 11, "bold"),
                        padding=(14, 10), borderwidth=0)
            s.map(f"{name}.TButton", background=[("active", color), ("disabled", LINE)],
                  foreground=[("disabled", FAINT)])
        s.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG, padding=6)
        s.configure("Panel.TEntry", fieldbackground=BG)
        s.configure("TSpinbox", fieldbackground=PANEL, foreground=FG, arrowcolor=FG, padding=4)
        s.configure("TCombobox", fieldbackground=PANEL, foreground=FG, arrowcolor=FG, padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

    def _layout(self) -> None:
        r = self.root
        r.columnconfigure(1, weight=1)
        r.rowconfigure(0, weight=1)

        # ---- left: settings
        side = ttk.Frame(r, padding=(18, 16))
        side.grid(row=0, column=0, sticky="ns")
        side.columnconfigure(0, weight=1)
        ttk.Label(side, text="SortBuddy", style="Title.TLabel").grid(sticky="w")
        ttk.Label(side, text="Bulk card sorter", style="Dim.TLabel").grid(sticky="w", pady=(0, 14))

        def section(text):
            ttk.Label(side, text=text.upper(), style="Section.TLabel").grid(sticky="w", pady=(12, 4))

        section("Card list")
        self.catalog_var = tk.StringVar(value=self.settings["catalog"])
        ttk.Entry(side, textvariable=self.catalog_var, width=34).grid(sticky="ew")
        row = ttk.Frame(side)
        row.grid(sticky="ew", pady=(6, 0))
        ttk.Button(row, text="Open…", command=self.pick_catalog).pack(side="left")
        ttk.Button(row, text="New…", command=self.new_catalog).pack(side="left", padx=6)
        ttk.Button(row, text="Excel", command=self.open_catalog).pack(side="left")
        self.count_var = tk.StringVar()
        ttk.Label(side, textvariable=self.count_var, style="Dim.TLabel").grid(sticky="w", pady=(4, 0))

        section("Camera")
        row = ttk.Frame(side)
        row.grid(sticky="ew")
        self.camera_var = tk.StringVar(value=str(self.settings["camera"]))
        ttk.Spinbox(row, from_=0, to=9, width=4, textvariable=self.camera_var).pack(side="left")
        ttk.Button(row, text="Find cameras", command=self.find_cameras).pack(side="left", padx=6)
        row = ttk.Frame(side)
        row.grid(sticky="ew", pady=(6, 0))
        ttk.Label(row, text="Focus").pack(side="left")
        self.focus_var = tk.StringVar(value=self.settings["focus"])
        ttk.Entry(row, textvariable=self.focus_var, width=6).pack(side="left", padx=6)
        ttk.Label(row, text="blank = auto,  [ ] adjust", style="Dim.TLabel").pack(side="left")

        section("Card details from")
        self.lookup_names = {NO_LOOKUP: "", **{label: key for key, (label, _) in lookup.SOURCES.items()}}
        current = next((k for k, v in self.lookup_names.items() if v == self.settings.get("lookup")), NO_LOOKUP)
        self.lookup_var = tk.StringVar(value=current)
        ttk.Combobox(side, textvariable=self.lookup_var, values=list(self.lookup_names),
                     state="readonly").grid(sticky="ew")

        section("Add cards")
        self.enroll_btn = ttk.Button(side, text="Start adding cards", style="Accent.TButton",
                                     command=lambda: self.toggle("enroll"))
        self.enroll_btn.grid(sticky="ew")

        section("Sort")
        self.rule_var = tk.StringVar(value=self.settings["rule"])
        ttk.Entry(side, textvariable=self.rule_var).grid(sticky="ew")
        ttk.Label(side, text="cost <= 3 · colors has blue · price >= 1\nrarity in rare,mythic · foil == yes",
                  style="Dim.TLabel", justify="left").grid(sticky="w", pady=(4, 6))
        self.sort_btn = ttk.Button(side, text="Start sorting", style="Go.TButton",
                                   command=lambda: self.toggle("sort"))
        self.sort_btn.grid(sticky="ew")
        ttk.Button(side, text="Export inventory…", command=self.export).grid(sticky="ew", pady=(8, 0))

        section("Activity")
        self.log = tk.Text(side, height=8, width=36, bg=PANEL, fg=DIM, relief="flat", wrap="word",
                           font=(FONT, 9), highlightthickness=0, state="disabled", padx=8, pady=6)
        self.log.grid(sticky="nsew")
        side.rowconfigure(side.grid_size()[1] - 1, weight=1)

        # ---- middle: camera
        mid = ttk.Frame(r, style="Main.TFrame", padding=12)
        mid.grid(row=0, column=1, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)
        self.view = tk.Label(mid, bg="#000000", fg=DIM, font=(FONT, 14),
                             text="Camera is off\n\nClick “Start adding cards” or “Start sorting”")
        self.view.grid(row=0, column=0, sticky="nsew")
        self.view.bind("<Button-1>", lambda e: self.view.focus_set())
        self.status_var = tk.StringVar(value="")
        self.status = tk.Label(mid, textvariable=self.status_var, bg=BG, fg=DIM, font=(FONT, 11), anchor="w")
        self.status.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        # ---- right: context panel
        self.right = ttk.Frame(r, style="Panel.TFrame", padding=(20, 18), width=420)
        self.right.grid(row=0, column=2, sticky="ns")
        self.right.grid_propagate(False)
        self.right.columnconfigure(0, weight=1)
        self.right.rowconfigure(0, weight=1)
        self.panels = {"idle": self._idle_panel(), "enroll": self._enroll_panel(), "sort": self._sort_panel()}

    def _idle_panel(self) -> ttk.Frame:
        p = ttk.Frame(self.right, style="Panel.TFrame")
        ttk.Label(p, text="How it works", style="Heading.TLabel").pack(anchor="w")
        steps = ("1.  Add cards: hold each card under the camera and press Space. "
                 "SortBuddy reads it, looks up its details, and you press Enter to save.\n\n"
                 "2.  Or skip that: type a sort rule and Start sorting. Each card is "
                 "identified from its bottom line (set + number), added to your list, "
                 "and gets a big YES or NO. Cards already in your list are recognised "
                 "instantly from their picture.\n\n"
                 "Keys:  Space capture · Enter save · Tab next name guess · Esc discard · "
                 "[ ] focus · A autofocus · U undo · F11 full screen")
        tk.Label(p, text=steps, bg=PANEL, fg=DIM, font=(FONT, 10), justify="left", wraplength=370).pack(
            anchor="w", pady=(10, 0))
        return p

    def _enroll_panel(self) -> ttk.Frame:
        p = ttk.Frame(self.right, style="Panel.TFrame")
        p.columnconfigure(1, weight=1)
        top = ttk.Frame(p, style="Panel.TFrame")
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.thumb = tk.Label(top, bg=PANEL)
        self.thumb.pack(side="left", anchor="n")
        head = ttk.Frame(top, style="Panel.TFrame")
        head.pack(side="left", fill="x", expand=True, padx=(12, 0))
        ttk.Label(head, text="NAME", style="PanelDim.TLabel").pack(anchor="w")
        self.name_var = tk.StringVar()
        ttk.Entry(head, textvariable=self.name_var, style="Panel.TEntry", font=(FONT, 12, "bold")).pack(fill="x")
        ttk.Label(head, text="ID", style="PanelDim.TLabel").pack(anchor="w", pady=(8, 0))
        self.id_var = tk.StringVar()
        ttk.Entry(head, textvariable=self.id_var, style="Panel.TEntry").pack(fill="x")
        self.found_label = tk.Label(head, bg=PANEL, fg=DIM, font=(FONT, 10), anchor="w", justify="left",
                                    wraplength=200)
        self.found_label.pack(anchor="w", fill="x", pady=(8, 0))

        ttk.Label(p, text="INFORMATION PULLED FROM THIS CARD", style="PanelDim.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(16, 6))
        self.parts = ttk.Frame(p, style="Panel.TFrame")
        self.parts.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.parts.columnconfigure(1, weight=1)
        p.rowconfigure(2, weight=1)

        btns = ttk.Frame(p, style="Panel.TFrame")
        btns.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        self.capture_btn = ttk.Button(btns, text="Capture  (Space)", style="Accent.TButton", command=self.capture)
        self.capture_btn.pack(fill="x")
        row = ttk.Frame(btns, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        self.save_btn = ttk.Button(row, text="Save  (Enter)", style="Go.TButton", command=self.save)
        self.save_btn.pack(side="left", fill="x", expand=True)
        self.discard_btn = ttk.Button(row, text="Discard  (Esc)", command=self.discard)
        self.discard_btn.pack(side="left", fill="x", expand=True, padx=(8, 0))
        row = ttk.Frame(btns, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        self.next_btn = ttk.Button(row, text="Next name guess  (Tab)", command=self.next_name)
        self.next_btn.pack(side="left", fill="x", expand=True)
        self.relookup_btn = ttk.Button(row, text="Look up name", command=self.relookup)
        self.relookup_btn.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.added_var = tk.StringVar()
        ttk.Label(btns, textvariable=self.added_var, style="PanelDim.TLabel").pack(anchor="w", pady=(10, 0))
        return p

    def _sort_panel(self) -> ttk.Frame:
        p = ttk.Frame(self.right, style="Panel.TFrame")
        self.rule_label = tk.Label(p, bg=PANEL, fg=DIM, font=(FONT, 10), anchor="w", justify="left", wraplength=370)
        self.rule_label.pack(anchor="w", fill="x")
        self.verdict = tk.Label(p, text="—", bg=LINE, fg=FG, font=(FONT, 72, "bold"), height=1)
        self.verdict.pack(fill="x", pady=(12, 0), ipady=18)
        self.verdict_name = tk.Label(p, text="Show a card", bg=PANEL, fg=FG, font=(FONT, 14, "bold"),
                                     wraplength=370, justify="left", anchor="w")
        self.verdict_name.pack(anchor="w", fill="x", pady=(10, 0))
        self.counts_var = tk.StringVar(value="YES 0   ·   NO 0")
        ttk.Label(p, textvariable=self.counts_var, style="Heading.TLabel").pack(anchor="w", pady=(14, 4))
        ttk.Label(p, text="RECENT", style="PanelDim.TLabel").pack(anchor="w", pady=(10, 4))
        self.recent = tk.Listbox(p, bg=BG, fg=FG, relief="flat", highlightthickness=0, font=(FONT, 10),
                                 activestyle="none", selectbackground=BG, height=12)
        self.recent.pack(fill="both", expand=True)
        ttk.Button(p, text="Undo last  (U)", command=self.undo).pack(fill="x", pady=(10, 0))
        return p

    def _no_button_focus(self, widget) -> None:
        """Buttons mustn't hold keyboard focus, or Space would press them
        (e.g. Stop) instead of capturing a card."""
        for child in widget.winfo_children():
            if isinstance(child, (ttk.Button, tk.Listbox)):
                child.configure(takefocus=False)
            self._no_button_focus(child)

    def show_panel(self, name: str) -> None:
        for key, panel in self.panels.items():
            if key == name:
                panel.grid(row=0, column=0, sticky="nsew")
            else:
                panel.grid_forget()

    def _maximize(self) -> None:
        try:
            self.root.state("zoomed")  # Windows
        except tk.TclError:
            try:
                self.root.attributes("-zoomed", True)  # Linux
            except tk.TclError:
                pass

    # -------------------------------------------------------------- settings
    def _load_settings(self) -> dict:
        try:
            saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return dict(DEFAULTS)
        if saved.get("version", 1) < 2:
            saved["lookup"] = "auto"  # older versions saved "off" without anyone choosing it
        return {**DEFAULTS, **saved, "version": 2}

    def _save_settings(self) -> None:
        data = {"catalog": self.catalog_var.get(), "camera": self._camera_index(),
                "focus": self.focus_var.get().strip(), "rule": self.rule_var.get(),
                "lookup": self.lookup_names.get(self.lookup_var.get(), ""), "version": 2}
        try:
            SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _camera_index(self) -> int:
        try:
            return int(self.camera_var.get())
        except ValueError:
            return 0

    # ----------------------------------------------------------------- utils
    def say(self, text: str, color: str = DIM) -> None:
        self.status_var.set(text)
        self.status.configure(fg=color)

    def log_line(self, s: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", s)
        self.log.see("end")
        self.log.configure(state="disabled")

    def refresh_count(self) -> None:
        path = Path(self.catalog_var.get())
        try:
            cat = Catalog.load(path)
            photos = sum(1 for c in cat.cards.values() if cat.image_path(c) and cat.image_path(c).exists())
            self.count_var.set(f"{len(cat)} card{'s' * (len(cat) != 1)} · {photos} with photos")
        except FileNotFoundError:
            self.count_var.set("New list: created when you save the first card")
        except Exception as e:  # noqa: BLE001 - show any parse problem
            self.count_var.set(f"Can't read: {e}")

    def poll(self) -> None:
        """Handle results from worker threads (OCR, lookups, camera search)."""
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log_line(payload)
                elif kind == "proposal" and self.pending is not None and payload[0] is self.pending:
                    self._show_proposal(payload[1])
                elif kind == "identified":
                    self._on_identified(*payload)
                elif kind == "done":
                    payload()
        except queue.Empty:
            pass
        try:
            self.root.after(50, self.poll)
        except tk.TclError:
            pass

    def background(self, fn, *args) -> None:
        threading.Thread(target=fn, args=args, daemon=True).start()

    # ------------------------------------------------------------- run modes
    def toggle(self, mode: str) -> None:
        if self.mode == mode:
            self.stop()
        else:
            self.stop()
            self.start(mode)

    def start(self, mode: str) -> None:
        self._save_settings()
        path = Path(self.catalog_var.get())
        if mode == "sort":
            try:
                self.rule = Rule(self.rule_var.get())
            except RuleError as e:
                messagebox.showerror("SortBuddy", f"Sort rule problem: {e}")
                return
            if path.exists():
                self.catalog = Catalog.load(path)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                self.catalog = Catalog([], path.parent)
            if not self._rule_fields_ok():
                return
            idx = cli._index_path(str(path))
            if path.exists() and (not idx.exists() or idx.stat().st_mtime < path.stat().st_mtime):
                cli.build_index(str(path))
            index = FingerprintIndex.load(idx) if idx.exists() else FingerprintIndex([], np.zeros((0, 32), np.uint8))
            source_key = self.lookup_names.get(self.lookup_var.get(), "")
            source = lookup.SOURCES[source_key][1] if source_key else None
            use_ocr = ocr.available()
            if (source is None or not use_ocr) and len(index) == 0:
                messagebox.showerror("SortBuddy", "With card details lookup off (or OCR not installed), only cards "
                                     "already in your list can be recognised, and this list is empty.")
                return
            self.identifier = Identifier(self.catalog, path, index, source, use_ocr)
            self.check_foil = any(f in ("foil", "price") for f in self.rule.fields)
            self.session = Session(self.catalog)
            self.track = None
            self.unknown = 0
            self.log_path = path.parent / "sessions" / f"{time.strftime('%Y%m%d-%H%M%S')}.csv"
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.rule_label.configure(text=f"Rule:  {self.rule}   ·   {len(self.catalog)} cards in your list", fg=DIM)
            self.verdict.configure(text="—", bg=LINE, fg=FG)
            self.verdict_name.configure(text="Show a card")
            self.recent.delete(0, "end")
            self._update_counts()
        else:
            if path.exists():
                self.catalog = Catalog.load(path)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                self.catalog = Catalog([], path.parent)
            self.source_key = self.lookup_names.get(self.lookup_var.get(), "")
            self.use_ocr = ocr.available()
            if not self.use_ocr:
                print("Tip: pip install rapidocr_onnxruntime to read card names automatically.\n")
            self.added = 0
            self.added_var.set("")
            self.clear_pending()

        focus = self.focus_var.get().strip()
        if focus and not focus.isdigit():
            messagebox.showerror("SortBuddy", "Focus must be a number 0-255, or blank for autofocus.")
            return
        self.say(f"Opening camera {self._camera_index()}…")
        self.root.update()
        cam = Camera(self._camera_index(), focus=int(focus) if focus else None, quiet=True)
        if not cam.ok:
            self.say(f"Can't open camera {self._camera_index()}. Try another number or “Find cameras”.", RED)
            return
        self.cam = cam
        self.mode = mode
        self.show_panel(mode)
        (self.enroll_btn if mode == "enroll" else self.sort_btn).configure(
            text="Stop", style="Stop.TButton")
        self.say(f"Camera {cam.index} · {cam.size} · {cam.focus_label}")
        self.view.focus_set()
        self.loop()

    def stop(self) -> None:
        if self.loop_id:
            self.root.after_cancel(self.loop_id)
            self.loop_id = None
        if self.cam:
            self.cam.release()
            self.cam = None
        if self.mode == "enroll" and self.added:
            self.background(lambda: (cli.build_index(self.catalog_var.get()),
                                     self.events.put(("done", self.refresh_count))))
        if self.mode == "sort":
            y, n = self.session.counts()
            print(f"Sorted {y + n} cards ({y} yes, {n} no, {self.unknown} not identified). "
                  f"Log: {self.log_path.name}\n")
            if self.identifier.index.ids:
                self.identifier.index.save(cli._index_path(self.catalog_var.get()))
            self.refresh_count()
        self.mode = None
        self.pending = None
        self.enroll_btn.configure(text="Start adding cards", style="Accent.TButton")
        self.sort_btn.configure(text="Start sorting", style="Go.TButton")
        self.view.configure(image="", text="Camera is off\n\nClick “Start adding cards” or “Start sorting”")
        self.photo = None
        self.show_panel("idle")
        self.say("")

    def quit(self) -> None:
        self.stop()
        self._save_settings()
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        self.root.destroy()

    def loop(self) -> None:
        if not self.cam:
            return
        ok, frame = self.cam.read()
        if ok:
            self.found = extract_card(frame)
            color = (255, 140, 79) if self.found else None  # BGR of ACCENT
            if self.mode == "sort":
                color = self._sort_step()
            if self.found and color:
                k = max(2, frame.shape[1] // 300)
                cv2.polylines(frame, [self.found[1].astype(int)], True, color, k)
            w, h = self.view.winfo_width(), self.view.winfo_height()
            if w > 10 and h > 10:
                self.photo = to_photo(frame, w, h)
                self.view.configure(image=self.photo, text="")
            if self.mode == "enroll" and self.pending is None:
                self.say("Card found: press Space to capture" if self.found else
                         "Hold a card flat under the camera", GREEN if self.found else DIM)
        self.loop_id = self.root.after(15, self.loop)

    # --------------------------------------------------------------- sorting
    def _rule_fields_ok(self) -> bool:
        """Warn about rules that can never match, e.g. 'color' vs 'colors'."""
        known = set(KNOWN_FIELDS)
        for c in self.catalog.cards.values():
            known |= set(c.fields)
        unknown = [f for f in self.rule.fields if f not in known]
        if not unknown:
            return True
        hints = []
        for f in unknown:
            close = difflib.get_close_matches(f, sorted(known), n=1)
            hints.append(f"“{f}”" + (f" (did you mean “{close[0]}”?)" if close else ""))
        return messagebox.askyesno(
            "SortBuddy", "No card has a field called " + ", ".join(hints) + ", so this rule would "
            "answer NO for every card.\n\nFields include: name, set, number, rarity, cost, colors, "
            "domain, type, power, might, energy, foil, language, price.\n\nStart anyway?")

    def _sort_step(self):
        """Track the card in view; identify it once it holds still."""
        t = self.track
        if not self.found:
            if t:
                t["miss"] += 1
                if t["miss"] >= 6:  # card taken away: the next one is a new card
                    self.track = None
            if not self.track:
                self.say("Show a card", DIM)
            return None
        h = phash(self.found[0])
        if t and hamming(h, t["hash"]) <= 45:
            t.update(stable=t["stable"] + 1, miss=0, hash=h)
        else:
            t = self.track = {"hash": h, "stable": 1, "miss": 0, "state": "new", "result": None}
        if t["state"] == "new" and t["stable"] >= 3:
            t["state"] = "pending"
            t["start"] = time.time()
            img = self.found[0].copy()

            def work(track=t, img=img):
                try:
                    result = self.identifier.identify(img, self.check_foil)
                except Exception as e:  # noqa: BLE001 - e.g. offline: report, don't crash
                    print(f"Couldn't identify: {e}\n")
                    result = None
                self.events.put(("identified", (track, result, img)))
            self.background(work)
        if t["state"] == "pending":
            self.say("Identifying…", AMBER)
            return (66, 185, 245)
        if t["state"] == "done":
            yes = t.get("yes")
            return (66, 185, 245) if yes is None else (110, 207, 62) if yes else (91, 91, 239)
        return (200, 200, 200)

    def _on_identified(self, track, result, img) -> None:
        if self.mode != "sort":
            return
        track["state"] = "done"
        if result is None:
            self.unknown += 1
            track["yes"] = None
            self.verdict.configure(text="?", bg=AMBER, fg="#0b0d12")
            self.verdict_name.configure(text="Couldn't identify this card: set it aside")
            self.recent.insert(0, "?      Unknown card")
            self.recent.itemconfigure(0, fg=AMBER)
            self._update_counts()
            self.say("Not identified. Is the bottom line in focus and free of glare?", AMBER)
            return
        if result.new:
            self.identifier.learn(result, img)
            self.refresh_count()
            self.rule_label.configure(text=f"Rule:  {self.rule}   ·   {len(self.catalog)} cards in your list")
        card = Card(result.card_id, result.fields)
        yes = bool(self.rule(card))
        track["yes"] = yes
        self.session.record(result.card_id, yes, str(self.rule))
        self.session.save_log(self.log_path)
        self._show_verdict(card.name, yes)
        how = {"known": "recognised from its picture", "bottom line": "read from the bottom line",
               "name": "found by name"}[result.how]
        self.say(f"{card.name}  ·  {how}  ·  {result.seconds:.1f}s" + ("  ·  added to your list" if result.new else ""),
                 FG)
        self.root.bell()

    def _update_counts(self) -> None:
        y, n = self.session.counts()
        self.counts_var.set(f"YES {y}   ·   NO {n}" + (f"   ·   ? {self.unknown}" if self.unknown else ""))

    def _show_verdict(self, name: str, yes: bool) -> None:
        self.verdict.configure(text="YES" if yes else "NO", bg=GREEN if yes else RED, fg="#0b0d12")
        self.verdict_name.configure(text=name)
        self._update_counts()
        self.recent.insert(0, f"{'YES' if yes else 'NO '}   {name}")
        self.recent.itemconfigure(0, fg=GREEN if yes else RED)

    def undo(self) -> None:
        """Take back the last decision; the card in view gets decided again."""
        if self.mode != "sort":
            return
        s = self.session.undo()
        if not s:
            return
        self.session.save_log(self.log_path)
        if self.track:
            self.track.update(state="new", stable=0)
        if self.recent.size():
            self.recent.delete(0)
        self._update_counts()
        self.verdict.configure(text="—", bg=LINE, fg=FG)
        self.verdict_name.configure(text=f"Undid {self.catalog[s.card_id].name}")

    # ------------------------------------------------------------- enrolling
    def clear_pending(self) -> None:
        self.pending = None
        self.thumb.configure(image="")
        self.thumb_photo = None
        self.name_var.set("")
        self.id_var.set("")
        self.found_label.configure(text="Capture a card to see what's read from it.", fg=DIM)
        self._fill_parts({})
        for b in (self.save_btn, self.discard_btn, self.next_btn, self.relookup_btn):
            b.state(["disabled"])
        self.capture_btn.state(["!disabled"])

    def _fill_parts(self, fields: dict) -> None:
        for w in self.parts.winfo_children():
            w.destroy()
        row = 0
        for label, get in CARD_PARTS:
            value = get(fields)
            if not value:
                continue
            ttk.Label(self.parts, text=label, style="PanelDim.TLabel").grid(
                row=row, column=0, sticky="nw", pady=3, padx=(0, 14))
            tk.Label(self.parts, text=value, bg=PANEL, fg=FG, font=(FONT, 10), anchor="w", justify="left",
                     wraplength=250).grid(row=row, column=1, sticky="w", pady=3)
            row += 1

    def capture(self) -> None:
        if self.mode != "enroll":
            return
        if not self.found:
            self.say("No card in view: lay it flat on a plain background", AMBER)
            return
        img = self.found[0].copy()
        self.pending = {"img": img, "text": None, "names": [""], "i": 0, "cache": {}}
        pending = self.pending
        self.thumb_photo = to_photo(img, 150, 210)
        self.thumb.configure(image=self.thumb_photo)
        self.found_label.configure(text="Reading the card…", fg=DIM)
        self.capture_btn.state(["disabled"])
        self.discard_btn.state(["!disabled"])
        self.say("Reading the card…", DIM)

        def work():
            text = ocr.read_card(img) if self.use_ocr else None
            pending["text"] = text
            if text is not None:
                pending["img"] = text.upright
                pending["names"] = text.names or [""]
            self._propose_async(pending)

        self.background(work)

    def _propose_async(self, pending, name: str | None = None) -> None:
        """Runs in a worker thread: OCR result + lookup -> proposal."""
        source = lookup.SOURCES[self.source_key][1] if self.source_key else None
        name = pending["names"][pending["i"]] if name is None else name
        prop = propose(pending["text"], name, cli._next_auto_id(self.catalog), source, pending["cache"])
        self.events.put(("proposal", (pending, prop)))

    def _show_proposal(self, prop) -> None:
        p = self.pending
        p["prop"] = prop
        self.thumb_photo = to_photo(p["img"], 150, 210)
        self.thumb.configure(image=self.thumb_photo)
        self.name_var.set(prop.fields.get("name", ""))
        self.id_var.set(prop.card_id)
        if prop.message:
            msg, color = prop.message, KIND_COLORS[prop.kind]
        elif self.source_key:
            msg, color = "", DIM
        else:
            msg, color = "Card details lookup is off (left panel)", DIM
        if prop.card_id in self.catalog.cards:
            msg += "\nAlready in your list: Save replaces its photo"
        self.found_label.configure(text=msg.strip(), fg=color)
        self._fill_parts(prop.fields)
        for b in (self.save_btn, self.discard_btn, self.relookup_btn):
            b.state(["!disabled"])
        self.next_btn.state(["!disabled"] if len(p["names"]) > 1 else ["disabled"])
        n = len(p["names"])
        self.next_btn.configure(text=f"Next name guess  (Tab)  {p['i'] + 1}/{n}" if n > 1 else "Next name guess")
        self.say("Check the details, then Save (Enter) or Discard (Esc)", FG)

    def next_name(self) -> None:
        p = self.pending
        if not p or "prop" not in p or len(p["names"]) < 2:
            return
        p["i"] = (p["i"] + 1) % len(p["names"])
        self.found_label.configure(text="Looking up…", fg=DIM)
        self.background(self._propose_async, p)

    def relookup(self) -> None:
        p = self.pending
        name = self.name_var.get().strip()
        if not p or not name:
            return
        self.found_label.configure(text="Looking up…", fg=DIM)
        self.background(self._propose_async, p, name)

    def save(self) -> None:
        p = self.pending
        if not p or "prop" not in p:
            return
        card_id = self.id_var.get().strip() or p["prop"].card_id
        fields = dict(p["prop"].fields)
        if self.name_var.get().strip():
            fields["name"] = self.name_var.get().strip()
        try:
            cli.save_reference(self.catalog, self.catalog_var.get(), card_id, p["img"], **fields)
        except PermissionError:
            messagebox.showerror("SortBuddy", "Can't save: the card list is open in Excel. Close it and press Save again.")
            return
        self.added += 1
        self.added_var.set(f"{self.added} card(s) added this session")
        print(f"Saved {card_id}  {fields.get('name', '')}\n")
        self.refresh_count()
        self.clear_pending()

    def discard(self) -> None:
        if self.pending:
            self.clear_pending()
            self.say("Discarded", DIM)

    # ------------------------------------------------------------------ keys
    def on_key(self, e) -> str | None:
        typing = isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox))
        key = e.keysym
        if key == "F11":
            self.root.attributes("-fullscreen", not self.root.attributes("-fullscreen"))
            return "break"
        if key == "Escape":
            if self.pending:
                self.discard()
            elif self.root.attributes("-fullscreen"):
                self.root.attributes("-fullscreen", False)
            return "break"
        if key == "Return" and self.pending:
            self.save()
            return "break"
        if typing:
            return None
        if key == "space":
            if self.mode == "enroll" and not self.pending:
                self.capture()
            return "break"
        if key == "Tab" and self.pending:
            self.next_name()
            return "break"
        if self.cam and key in ("bracketleft", "bracketright", "a"):
            self.cam.handle_key(ord({"bracketleft": "[", "bracketright": "]", "a": "a"}[key]))
            if self.cam.focus is not None:
                self.focus_var.set(str(self.cam.focus))
            self.say(f"Camera {self.cam.index} · {self.cam.size} · {self.cam.focus_label}")
            return "break"
        if key == "u":
            self.undo()
            return "break"
        return None

    # --------------------------------------------------------------- actions
    def pick_catalog(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Card lists", "*.csv *.json"), ("All files", "*.*")])
        if path:
            self.catalog_var.set(path)

    def new_catalog(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="catalog.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            self.catalog_var.set(path)

    def open_catalog(self) -> None:
        path = Path(self.catalog_var.get())
        if not path.exists():
            messagebox.showinfo("SortBuddy", "No card list yet. Add some cards first.")
            return
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - opens in the user's default app (Excel)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])

    def find_cameras(self) -> None:
        if self.cam:
            messagebox.showinfo("SortBuddy", "Stop the camera first.")
            return
        print("Looking for cameras…\n")
        self.background(cli.main, ["cameras"])

    def export(self) -> None:
        path = self.catalog_var.get()
        sessions = Path(path).parent / "sessions"
        logs = filedialog.askopenfilenames(title="Pick the sorting sessions to count",
                                           initialdir=sessions if sessions.exists() else None,
                                           filetypes=[("Session logs", "*.csv")])
        if not logs:
            return
        out = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="inventory.csv",
                                           filetypes=[("CSV", "*.csv")])
        if out:
            try:
                cli.main(["export", path, *logs, "-o", out])
            except SystemExit as e:
                messagebox.showerror("SortBuddy", str(e.code))


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
