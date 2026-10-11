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
from .fingerprint import FingerprintIndex, hamming, phash, sharpness
from .identify import Identifier
from .proposal import propose
from .rules import Rule, RuleError
from .gui_rules import RuleBuilder
from .session import Session
from .theme import ACCENT, AMBER, BG, DIM, FAINT, FG, FONT, GREEN, LINE, PANEL, RED, SIDE
from .vision import extract_card_checked

SETTINGS = Path.home() / ".sortbuddy-gui.json"
# Fields card lookups and OCR fill in, so rules can be checked before any card is known.
KNOWN_FIELDS = {"id", "name", "set", "set_name", "number", "rarity", "cost", "mana_cost", "colors",
                "color_identity", "type", "card_types", "subtypes", "power", "toughness", "keywords", "text",
                "artist", "year", "price", "price_foil", "foil", "language", "domain", "supertype", "energy",
                "might", "tags", "variant", "name_kr", "game", "face"}
NO_LOOKUP = "Off (fill in details yourself)"
RESOLUTIONS = ["1920 × 1080", "1280 × 720", "640 × 480"]
DEFAULTS = {"catalog": str(Path("mycards") / "catalog.csv"), "camera": 0, "focus": "",
            "rule": "cost <= 3", "lookup": "auto", "version": 2}

KIND_COLORS = {"ok": GREEN, "warn": AMBER, "error": RED, "": DIM}
SAME_CARD = 85  # picture difference (bits of 256) still counted as the same card being moved

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
                           interpolation=cv2.INTER_LINEAR)
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
        self.catalog_var.trace_add("write", lambda *_: (self.refresh_count(), self.builder.refresh()))
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
        ttk.Label(row, text="Picture").pack(side="left")
        self.res_var = tk.StringVar(value=self.settings.get("resolution", RESOLUTIONS[0]))
        ttk.Combobox(row, textvariable=self.res_var, values=RESOLUTIONS, state="readonly", width=12).pack(
            side="left", padx=6)
        ttk.Label(row, text="(applies on start)", style="Dim.TLabel").pack(side="left")

        row = ttk.Frame(side)
        row.grid(sticky="ew", pady=(6, 0))
        ttk.Label(row, text="Focus").pack(side="left")
        self.focus_var = tk.StringVar(value=str(self.settings["focus"]))
        self.auto_focus = tk.BooleanVar(value=not self.focus_var.get().strip())
        tk.Checkbutton(row, text="Auto", variable=self.auto_focus, command=self._auto_toggled, bg=SIDE, fg=FG,
                       selectcolor=PANEL, activebackground=SIDE, activeforeground=FG, highlightthickness=0,
                       bd=0, font=(FONT, 10)).pack(side="left", padx=(6, 4))
        self.focus_scale = ttk.Scale(row, from_=0, to=250, command=self._focus_slid, length=130)
        self.focus_scale.pack(side="left")
        self.focus_label = ttk.Label(row, text="", width=4, style="Dim.TLabel")
        self.focus_label.pack(side="left", padx=4)
        try:
            self.focus_scale.set(float(self.focus_var.get() or 120))
        except ValueError:
            self.focus_scale.set(120)
        self._show_focus()
        row = ttk.Frame(side)
        row.grid(sticky="ew", pady=(6, 0))
        self.best_focus_btn = ttk.Button(row, text="Find best focus", command=self.find_best_focus)
        self.best_focus_btn.pack(side="left")
        self.cam_info = ttk.Label(row, text="", style="Dim.TLabel")
        self.cam_info.pack(side="left", padx=8)

        section("Card details from")
        self.lookup_names = {NO_LOOKUP: "", **{label: key for key, (label, _) in lookup.SOURCES.items()}}
        current = next((k for k, v in self.lookup_names.items() if v == self.settings.get("lookup")), NO_LOOKUP)
        self.lookup_var = tk.StringVar(value=current)
        lk = ttk.Combobox(side, textvariable=self.lookup_var, values=list(self.lookup_names), state="readonly")
        lk.grid(sticky="ew")
        lk.bind("<<ComboboxSelected>>", lambda e: self.builder.refresh())

        section("Add cards")
        self.enroll_btn = ttk.Button(side, text="Start adding cards", style="Accent.TButton",
                                     command=lambda: self.toggle("enroll"))
        self.enroll_btn.grid(sticky="ew")

        section("Sort")
        self.rule_var = tk.StringVar(value=self.settings["rule"])
        self.rule_summary = tk.Label(side, text="", bg=SIDE, fg=FG, font=(FONT, 10), anchor="w", justify="left",
                                     wraplength=300)
        self.rule_summary.grid(sticky="ew", pady=(0, 2))
        ttk.Label(side, text="Change it in the panel on the right", style="Dim.TLabel").grid(sticky="w", pady=(0, 6))
        self.sort_btn = ttk.Button(side, text="Start sorting", style="Go.TButton",
                                   command=lambda: self.toggle("sort"))
        self.sort_btn.grid(sticky="ew")
        self.sound_var = tk.BooleanVar(value=bool(self.settings.get("sound", False)))
        tk.Checkbutton(side, text="Sound when a card is decided", variable=self.sound_var, bg=SIDE, fg=DIM,
                       selectcolor=PANEL, activebackground=SIDE, activeforeground=FG, highlightthickness=0,
                       bd=0, font=(FONT, 9)).grid(sticky="w", pady=(6, 0))
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
        """Camera off: the rule builder (scrolls if it gets tall) and a short how-to."""
        outer = ttk.Frame(self.right, style="Panel.TFrame")
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        canvas = tk.Canvas(outer, bg=PANEL, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        p = ttk.Frame(canvas, style="Panel.TFrame")
        win = canvas.create_window((0, 0), window=p, anchor="nw")
        p.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
                        if self.mode is None else None)

        self.builder = RuleBuilder(p, self.rule_var, self.catalog_var.get, on_change=self._rule_changed,
                                   game=lambda: self.lookup_names.get(self.lookup_var.get(), "")
                                   if self.lookup_names.get(self.lookup_var.get(), "") in ("magic", "riftbound") else "")
        self.builder.pack(fill="x")
        ttk.Separator(p).pack(fill="x", pady=16)
        ttk.Label(p, text="How it works", style="Heading.TLabel").pack(anchor="w")
        steps = ("Card backs: put one face down under the camera while sorting and click "
                 "“This is a card back…”. Then “Face up or down” and “Game” work for face-down "
                 "cards too, e.g. split a mixed box by game, or face up vs face down.\n\n"
                 "Start sorting: each card is identified from its bottom line (set + number), added to "
                 "your list, and gets a big YES or NO. Cards already in your list are recognised "
                 "instantly from their picture. You don't have to add cards first.\n\n"
                 "Add cards: for checking each card's details yourself (and Korean names).\n\n"
                 "Keys:  Space capture · Enter save · Tab next name guess · Esc discard · "
                 "[ ] focus · A autofocus · U undo · F11 full screen")
        tk.Label(p, text=steps, bg=PANEL, fg=DIM, font=(FONT, 9), justify="left", wraplength=330).pack(
            anchor="w", pady=(8, 0))
        return outer

    def _rule_changed(self, summary: str) -> None:
        self.rule_summary.configure(text=summary or "No rule yet: pick what goes in the YES pile",
                                    fg=FG if summary else AMBER)
        self.rule_description = summary

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
        row = ttk.Frame(p, style="Panel.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="Undo last  (U)", command=self.undo).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="This is a card back…", command=self.teach_back).pack(
            side="left", fill="x", expand=True, padx=(8, 0))
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
                "resolution": self.res_var.get(), "sound": self.sound_var.get(),
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
                if not self.rule_var.get().strip():
                    messagebox.showinfo("SortBuddy", "First pick what goes in the YES pile (panel on the right).")
                    return
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
            self.last_hash = None
            self.empty = 0
            self.unknown = 0
            self.log_path = path.parent / "sessions" / f"{time.strftime('%Y%m%d-%H%M%S')}.csv"
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.rule_label.configure(text=f"{self.rule_description}   ·   {len(self.catalog)} card{'s' * (len(self.catalog) != 1)} in your list",
                                      fg=DIM)
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
        width, height = (int(x) for x in self.res_var.get().split(" × "))
        self.say(f"Opening camera {self._camera_index()}…")
        self.root.update()
        cam = Camera(self._camera_index(), width, height, focus=int(focus) if focus.isdigit() else None, quiet=True)
        if not cam.ok:
            self.say(f"Can't open camera {self._camera_index()}. Try another number or “Find cameras”.", RED)
            return
        self.cam = cam
        self.mode = mode
        self.show_panel(mode)
        (self.enroll_btn if mode == "enroll" else self.sort_btn).configure(
            text="Stop", style="Stop.TButton")
        self.say(f"Camera {cam.index} · {cam.size} · {cam.focus_label}")
        self.frame_times: list[float] = []
        self.sharp = None
        self.sweep = None
        self.view.focus_set()
        self.loop()

    def stop(self) -> None:
        self.sweep = None
        self.cam_info.configure(text="")
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
            self.builder.refresh()
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
            self.found, self.problem = extract_card_checked(frame)
            self._camera_stats()
            if self.sweep:
                self._sweep_step()
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
            if self.mode == "enroll" and self.pending is None and not self.sweep:
                if self.problem == "several":
                    self.say("One card at a time, please", AMBER)
                else:
                    self.say("Card found: press Space to capture" if self.found else
                             "Hold a card flat under the camera", GREEN if self.found else DIM)
        self.loop_id = self.root.after(15, self.loop)

    # ---------------------------------------------------------------- camera
    def _show_focus(self) -> None:
        auto = self.auto_focus.get()
        self.focus_label.configure(text="auto" if auto else str(int(self.focus_scale.get())))
        self.focus_scale.state(["disabled"] if auto else ["!disabled"])

    def _focus_slid(self, value) -> None:
        if self.auto_focus.get():
            return
        v = int(round(float(value) / 5) * 5)  # the C920 focuses in steps of 5
        self.focus_var.set(str(v))
        self._show_focus()
        if self.cam:
            self.cam.set_focus(v)

    def _auto_toggled(self) -> None:
        if self.auto_focus.get():
            self.focus_var.set("")
            if self.cam:
                self.cam.set_focus(None)
        else:
            self._focus_slid(self.focus_scale.get())
        self._show_focus()

    def _camera_stats(self) -> None:
        """Frames per second, and how sharp the card is (updated a few times a second)."""
        now = time.time()
        self.frame_times = [t for t in self.frame_times if now - t < 2] + [now]
        if len(self.frame_times) % 5 == 0:
            if self.found:
                self.sharp = sharpness(self.found[0])
            fps = (len(self.frame_times) - 1) / max(1e-6, self.frame_times[-1] - self.frame_times[0])
            sharp = f"  ·  sharpness {self.sharp:.0f}" if self.found and self.sharp is not None else ""
            self.cam_info.configure(text=f"{fps:.0f} fps{sharp}")

    def find_best_focus(self) -> None:
        """Try focus settings with a card in view and keep the sharpest."""
        if not self.cam:
            messagebox.showinfo("SortBuddy", "Start the camera first (Add cards or Sort), with a card under it.")
            return
        self.auto_focus.set(False)
        self._show_focus()
        self.sweep = {"stage": "coarse", "values": list(range(0, 251, 25)), "i": 0, "wait": 8, "scores": {}}
        self.cam.set_focus(self.sweep["values"][0])
        self.best_focus_btn.state(["disabled"])

    def _sweep_step(self) -> None:
        sw = self.sweep
        if not self.found:
            self.say("Finding best focus: put a card under the camera", AMBER)
            return
        if sw["wait"] > 0:  # give the lens time to move
            sw["wait"] -= 1
            return
        v = sw["values"][sw["i"]]
        sw["scores"][v] = max(sw["scores"].get(v, 0), sharpness(self.found[0]))
        self.say(f"Finding best focus… trying {v}", AMBER)
        sw["i"] += 1
        if sw["i"] < len(sw["values"]):
            self.cam.set_focus(sw["values"][sw["i"]])
            sw["wait"] = 6
            return
        best = max(sw["scores"], key=sw["scores"].get)
        if sw["stage"] == "coarse":
            fine = [x for x in range(best - 20, best + 21, 5) if 0 <= x <= 250]
            sw.update(stage="fine", values=fine, i=0, wait=8)
            self.cam.set_focus(fine[0])
            return
        self.sweep = None
        self.best_focus_btn.state(["!disabled"])
        self.focus_scale.set(best)
        self._focus_slid(best)
        self._save_settings()
        self.say(f"Best focus: {best} (saved)", GREEN)

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
        """Track the card in view; identify it once it holds still.

        A card is decided once. It only counts again if it's clearly a
        different card, or the view was empty for a moment (taken away),
        so nudging it or a flicker in detection doesn't re-decide it."""
        if self.problem == "several":
            self.say("One card at a time, please", AMBER)
            return None
        if not self.found:
            self.empty += 1
            if self.empty >= 8:  # card taken away: the next card is new, even another copy
                self.track, self.last_hash = None, None
            if not self.track:
                self.say("Show a card", DIM)
            return None
        self.empty = 0
        h = phash(self.found[0])
        t = self.track
        if t and hamming(h, t["hash"]) <= SAME_CARD:
            t.update(stable=t["stable"] + 1, hash=h)
        elif self.last_hash is not None and hamming(h, self.last_hash) <= SAME_CARD and t:
            t.update(stable=t["stable"] + 1, hash=h)  # same card as just decided, only moved
        else:
            t = self.track = {"hash": h, "stable": 1, "state": "new", "yes": None}
        if t["state"] == "new" and t["stable"] >= 3:
            t["state"] = "pending"
            t["job"] = t.get("job", 0) + 1
            img = self.found[0].copy()

            def work(track=t, img=img, job=t["job"]):
                try:
                    result = self.identifier.identify(img, self.check_foil)
                except Exception as e:  # noqa: BLE001 - e.g. offline: report, don't crash
                    print(f"Couldn't identify: {e}\n")
                    result = None
                self.events.put(("identified", (track, result, img, job)))
            self.background(work)
        if t["state"] == "pending":
            self.say("Identifying…", AMBER)
            return (66, 185, 245)
        if t["state"] == "done":
            yes = t.get("yes")
            return (66, 185, 245) if yes is None else (110, 207, 62) if yes else (91, 91, 239)
        return (200, 200, 200)

    def _on_identified(self, track, result, img, job) -> None:
        if self.mode != "sort" or track.get("job") != job or track["state"] != "pending":
            return  # stale: the card was re-decided (e.g. a card back was just taught)
        track["state"] = "done"
        self.last_hash = track["hash"]
        if result is None:
            self.unknown += 1
            track["yes"] = None
            self.verdict.configure(text="?", bg=AMBER, fg="#0b0d12")
            self.verdict_name.configure(text="Couldn't identify this card: set it aside.\n"
                                             "If it's a card back, click “This is a card back…” to teach it.")
            self.recent.insert(0, "?      Unknown card")
            self.recent.itemconfigure(0, fg=AMBER)
            self._update_counts()
            self.say("Not identified. Is the bottom line in focus and free of glare?", AMBER)
            return
        if result.new:
            self.identifier.learn(result, img)
            self.refresh_count()
            self.rule_label.configure(text=f"{self.rule_description}   ·   {len(self.catalog)} card{'s' * (len(self.catalog) != 1)} in your list")
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
        if self.sound_var.get():
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

    def teach_back(self) -> None:
        """Remember the card back in view as a game's back, then decide it."""
        if self.mode != "sort" or not self.found:
            messagebox.showinfo("SortBuddy", "Put a card face down under the camera first.")
            return
        img = self.found[0].copy()
        win = tk.Toplevel(self.root, bg=PANEL, padx=20, pady=16)
        win.title("Card back")
        win.transient(self.root)
        tk.Label(win, text="Which game's card back is this?", bg=PANEL, fg=FG, font=(FONT, 12, "bold")).pack(
            anchor="w", pady=(0, 10))

        def pick(game):
            win.destroy()
            card_id = self.identifier.teach_back(game, img)
            print(f"Learned the {game} card back ({card_id}).\n")
            self.refresh_count()
            if self.track:  # decide the back in view now
                self.track.update(state="new", stable=3)
        for game in ("Magic", "Riftbound", "Pokemon", "One Piece", "Lorcana", "Yu-Gi-Oh"):
            ttk.Button(win, text=game, command=lambda g=game: pick(g)).pack(fill="x", pady=2)
        win.grab_set()

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
        if key in ("bracketleft", "bracketright"):
            current = float(self.focus_var.get() or self.focus_scale.get())
            self.focus_scale.set(current + (5 if key == "bracketright" else -5))
            self._focus_slid(self.focus_scale.get())
            return "break"
        if key == "a":
            self.auto_focus.set(not self.auto_focus.get())
            self._auto_toggled()
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
