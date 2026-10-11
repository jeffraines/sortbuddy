"""A small window for running SortBuddy without a terminal.

Start it with `sortbuddy-gui`, or double-click SortBuddy.bat on Windows.
It runs the same commands as the CLI; the camera window and its keys are
unchanged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import cli, lookup
from .catalog import Catalog

SETTINGS = Path.home() / ".sortbuddy-gui.json"
DEFAULTS = {"catalog": str(Path("mycards") / "catalog.csv"), "camera": 0, "focus": "",
            "rule": "cost <= 3", "lookup": ""}
NO_LOOKUP = "None (fill in details yourself)"
RULE_EXAMPLES = ("e.g.  cost <= 3  ·  colors has blue  ·  rarity in rare,mythic  ·  price >= 1  ·  "
                 "subtypes has wizard  ·  text contains draw a card")


class LogWriter:
    """Sends print() output from the commands into the log box."""

    def __init__(self, text: tk.Text):
        self.text = text

    def write(self, s: str) -> None:
        if not s or s == "\a":
            return
        try:
            self.text.configure(state="normal")
            self.text.insert("end", s)
            self.text.see("end")
            self.text.configure(state="disabled")
        except tk.TclError:  # window already closed
            pass

    def flush(self) -> None:
        pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("SortBuddy")
        root.minsize(760, 540)
        self.settings = self._load_settings()

        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        # Card list
        ttk.Label(frm, text="Card list").grid(row=0, column=0, sticky="w", **pad)
        self.catalog_var = tk.StringVar(value=self.settings["catalog"])
        ttk.Entry(frm, textvariable=self.catalog_var).grid(row=0, column=1, sticky="ew", **pad)
        btns = ttk.Frame(frm)
        btns.grid(row=0, column=2, sticky="e")
        ttk.Button(btns, text="Open…", command=self.pick_catalog).pack(side="left")
        ttk.Button(btns, text="New…", command=self.new_catalog).pack(side="left", padx=(4, 0))
        self.count_var = tk.StringVar()
        ttk.Label(frm, textvariable=self.count_var, foreground="#666").grid(row=1, column=1, sticky="w", padx=8)

        # Camera
        ttk.Label(frm, text="Camera").grid(row=2, column=0, sticky="w", **pad)
        cam = ttk.Frame(frm)
        cam.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        self.camera_var = tk.IntVar(value=self.settings["camera"])
        ttk.Spinbox(cam, from_=0, to=9, width=4, textvariable=self.camera_var).pack(side="left")
        ttk.Button(cam, text="Find cameras", command=self.find_cameras).pack(side="left", padx=8)
        ttk.Label(cam, text="Focus").pack(side="left", padx=(16, 4))
        self.focus_var = tk.StringVar(value=self.settings["focus"])
        ttk.Entry(cam, width=6, textvariable=self.focus_var).pack(side="left")
        ttk.Label(cam, text="blank = auto; [ ] in camera window", foreground="#666").pack(side="left", padx=6)

        # Enroll
        ttk.Separator(frm).grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)
        row = ttk.Frame(frm)
        row.grid(row=4, column=0, columnspan=3, sticky="w", **pad)
        self.enroll_btn = ttk.Button(row, text="Add cards…", command=self.enroll)
        self.enroll_btn.pack(side="left")
        ttk.Button(row, text="Open card list in Excel", command=self.open_catalog).pack(side="left", padx=8)
        ttk.Label(row, text="Card details from").pack(side="left", padx=(16, 4))
        self.lookup_names = {NO_LOOKUP: "", **{label: key for key, (label, _) in lookup.SOURCES.items()}}
        current = next((k for k, v in self.lookup_names.items() if v == self.settings.get("lookup")), NO_LOOKUP)
        self.lookup_var = tk.StringVar(value=current)
        ttk.Combobox(row, textvariable=self.lookup_var, values=list(self.lookup_names),
                     state="readonly", width=30).pack(side="left")
        ttk.Label(frm, text="SPACE capture · ENTER save · TAB next name · E type · ESC discard · Q done",
                  foreground="#666").grid(row=5, column=0, columnspan=3, sticky="w", padx=8)

        # Sort
        ttk.Separator(frm).grid(row=6, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(frm, text="Sort rule").grid(row=7, column=0, sticky="w", **pad)
        self.rule_var = tk.StringVar(value=self.settings["rule"])
        ttk.Entry(frm, textvariable=self.rule_var).grid(row=7, column=1, sticky="ew", **pad)
        self.sort_btn = ttk.Button(frm, text="Start sorting", command=self.sort)
        self.sort_btn.grid(row=7, column=2, sticky="e", **pad)
        ttk.Label(frm, text=RULE_EXAMPLES, foreground="#666").grid(row=8, column=0, columnspan=3, sticky="w", padx=8)
        ttk.Button(frm, text="Export inventory…", command=self.export).grid(row=9, column=0, columnspan=2,
                                                                          sticky="w", **pad)

        # Log
        self.log = tk.Text(frm, height=12, state="disabled", wrap="word", font=("Consolas", 9))
        self.log.grid(row=10, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        frm.rowconfigure(10, weight=1)
        sys.stdout = sys.stderr = LogWriter(self.log)

        cli.ask = self._ask
        cli.tick = self._tick
        self.catalog_var.trace_add("write", lambda *_: self.refresh_count())
        self.refresh_count()
        root.protocol("WM_DELETE_WINDOW", self.quit)

    # ---- settings
    def _load_settings(self) -> dict:
        try:
            return {**DEFAULTS, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            return dict(DEFAULTS)

    def _save_settings(self) -> None:
        data = {"catalog": self.catalog_var.get(), "camera": self._camera(),
                "focus": self.focus_var.get().strip(), "rule": self.rule_var.get(),
                "lookup": self.lookup_names.get(self.lookup_var.get(), "")}
        try:
            SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def quit(self) -> None:
        self._save_settings()
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        self.root.destroy()

    # ---- helpers
    def _camera(self) -> int:
        try:
            return int(self.camera_var.get())
        except (tk.TclError, ValueError):
            return 0

    def _camera_args(self) -> list[str]:
        args = ["--camera", str(self._camera())]
        focus = self.focus_var.get().strip()
        if focus:
            if not focus.isdigit():
                raise ValueError("Focus must be a number 0-255, or blank for autofocus.")
            args += ["--focus", focus]
        return args

    def _ask(self, prompt: str) -> str:
        return simpledialog.askstring("SortBuddy", prompt.replace("[", "\n[", 1), parent=self.root) or ""

    def _tick(self) -> None:
        try:
            self.root.update()
        except tk.TclError:  # the window was closed mid-run
            pass

    def refresh_count(self) -> None:
        path = Path(self.catalog_var.get())
        try:
            cat = Catalog.load(path)
            with_photo = sum(1 for c in cat.cards.values()
                             if cat.image_path(c) and cat.image_path(c).exists())
            self.count_var.set(f"{len(cat)} cards, {with_photo} with photos")
        except FileNotFoundError:
            self.count_var.set("(new: created when you add the first card)")
        except Exception as e:  # noqa: BLE001 - show any parse problem to the user
            self.count_var.set(f"can't read: {e}")

    def run(self, argv: list[str]) -> None:
        """Run a CLI command in-process, keeping the window usable."""
        self._save_settings()
        for b in (self.enroll_btn, self.sort_btn):
            b.state(["disabled"])
        print(f"\n> sortbuddy {' '.join(argv)}")
        try:
            cli.main(argv)
        except SystemExit as e:
            if e.code not in (None, 0):
                messagebox.showerror("SortBuddy", str(e.code))
        except Exception as e:  # noqa: BLE001
            print(f"Error: {e!r}")
            messagebox.showerror("SortBuddy", f"Something went wrong:\n{e}")
        finally:
            for b in (self.enroll_btn, self.sort_btn):
                b.state(["!disabled"])
            self.refresh_count()

    # ---- actions
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
            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(path)])

    def find_cameras(self) -> None:
        print("\nLooking for cameras (a few seconds)...")
        self.root.update()
        self.run(["cameras"])

    def enroll(self) -> None:
        try:
            source = self.lookup_names.get(self.lookup_var.get(), "")
            self.run(["enroll", self.catalog_var.get(), *self._camera_args(),
                      *(["--lookup", source] if source else [])])
        except ValueError as e:
            messagebox.showerror("SortBuddy", str(e))

    def sort(self) -> None:
        path = self.catalog_var.get()
        rule = self.rule_var.get().strip()
        if not rule:
            messagebox.showerror("SortBuddy", "Type a sort rule first, e.g. cost <= 3")
            return
        if not cli._index_path(path).exists():
            if Path(path).exists():
                cli.build_index(path)
            else:
                messagebox.showerror("SortBuddy", "No card list yet. Add some cards first.")
                return
        log = Path(path).parent / "sessions" / f"{time.strftime('%Y%m%d-%H%M%S')}.csv"
        try:
            self.run(["scan", path, "--rule", rule, "--log", str(log), *self._camera_args()])
        except ValueError as e:
            messagebox.showerror("SortBuddy", str(e))

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
            self.run(["export", path, *logs, "-o", out])


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
