"""The rule builder widget: rows of  [field] [how] [values]  that make the
sort rule, a plain-English preview and how many of your cards match."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .catalog import Catalog
from .rulebuilder import BY_LABEL, Condition, visible_fields, choices, describe, from_rule, ops_for, rule_text
from .rules import Rule, RuleError
from .theme import AMBER, BG, DIM, FAINT, FG, FONT, GREEN, PANEL


class RuleBuilder(ttk.Frame):
    """Rows of  [field ▾] [how ▾] [values]  that together make the sort rule."""

    def __init__(self, parent, rule_var: tk.StringVar, catalog_path, on_change=None, game=lambda: ""):
        super().__init__(parent, style="Panel.TFrame")
        self.rule_var = rule_var
        self.catalog_path = catalog_path  # callable -> str
        self.on_change = on_change
        self.game = game  # callable -> "magic", "riftbound" or "" (both)
        self.rows: list[dict] = []
        self._catalog_cache = (None, None)
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text="What goes in the YES pile?", style="Heading.TLabel").grid(sticky="w")
        tk.Label(self, text="Pick a field and how to match it. Every condition must match.", bg=PANEL, fg=DIM,
                 font=(FONT, 9), justify="left", anchor="w", wraplength=330).grid(sticky="ew", pady=(2, 10))
        self.rows_frame = ttk.Frame(self, style="Panel.TFrame")
        self.rows_frame.grid(sticky="ew")
        self.rows_frame.columnconfigure(0, weight=1)
        self.add_btn = ttk.Button(self, text="+  Add condition", command=lambda: self.add_row())
        self.add_btn.grid(sticky="w", pady=(8, 0))

        self.preview = tk.Label(self, bg=PANEL, fg=FG, font=(FONT, 11, "bold"), anchor="w", justify="left",
                                wraplength=330)
        self.preview.grid(sticky="ew", pady=(14, 0))
        self.count = tk.Label(self, bg=PANEL, fg=DIM, font=(FONT, 9), anchor="w", justify="left", wraplength=330)
        self.count.grid(sticky="ew")

        adv = ttk.Frame(self, style="Panel.TFrame")
        adv.grid(sticky="ew", pady=(14, 0))
        self.adv_open = tk.BooleanVar(value=False)
        tk.Checkbutton(adv, text="Type the rule instead (advanced)", variable=self.adv_open, command=self._toggle_adv,
                       bg=PANEL, fg=DIM, selectcolor=BG, activebackground=PANEL, activeforeground=FG,
                       highlightthickness=0, bd=0, font=(FONT, 9)).pack(anchor="w")
        self.adv_entry = ttk.Entry(adv, textvariable=self.rule_var, style="Panel.TEntry")
        self.adv_entry.bind("<KeyRelease>", lambda e: self._typed())

        # Keep the preview right however the rule changes (builder, typing, settings).
        rule_var.trace_add("write", lambda *_: self._show(from_rule(rule_var.get()) or []))
        conditions = from_rule(rule_var.get()) if rule_var.get().strip() else []
        if conditions is None:  # a typed rule the builder can't show
            self.adv_open.set(True)
            self._toggle_adv()
            conditions = []
        for c in conditions or [Condition("rarity", "is any of")]:
            self.add_row(c, update=False)
        self._update(write=conditions is not None and bool(conditions))

    # -- rows
    def add_row(self, cond: Condition | None = None, update: bool = True) -> None:
        cond = cond or Condition("cost", "at most")
        row = {"cond": cond}
        f = ttk.Frame(self.rows_frame, style="Panel.TFrame")
        f.grid(sticky="ew", pady=(0, 10))
        f.columnconfigure(0, weight=1)
        row["frame"] = f
        top = ttk.Frame(f, style="Panel.TFrame")
        top.grid(sticky="ew")
        row["field"] = tk.StringVar(value=cond.spec.label)
        row["field_box"] = cb = ttk.Combobox(top, textvariable=row["field"], values=self._labels(), state="readonly",
                          width=17)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e, r=row: self._field_changed(r))
        row["op"] = tk.StringVar(value=cond.op)
        row["op_box"] = ttk.Combobox(top, textvariable=row["op"], state="readonly", width=10)
        row["op_box"].pack(side="left", padx=6)
        row["op_box"].bind("<<ComboboxSelected>>", lambda e: self._update())
        tk.Button(top, text="×", command=lambda r=row: self.remove_row(r), bg=PANEL, fg=DIM, activebackground=BG,
                  activeforeground=FG, relief="flat", bd=0, font=(FONT, 13), takefocus=False,
                  cursor="hand2").pack(side="left", padx=(2, 0))
        row["values_frame"] = ttk.Frame(f, style="Panel.TFrame")
        row["values_frame"].grid(sticky="ew", pady=(6, 0))
        self.rows.append(row)
        self._build_values(row)
        if update:
            self._update()

    def _labels(self) -> list[str]:
        return [s.label for s in visible_fields(self.game())]

    def remove_row(self, row: dict) -> None:
        row["frame"].destroy()
        self.rows.remove(row)
        self._update()

    def _field_changed(self, row: dict) -> None:
        spec = BY_LABEL[row["field"].get()]
        row["cond"] = Condition(spec.key, next(iter(ops_for(spec))))
        self._build_values(row)
        self._update()

    def _build_values(self, row: dict) -> None:
        cond, vf = row["cond"], row["values_frame"]
        for w in vf.winfo_children():
            w.destroy()
        ops = list(ops_for(cond.spec))
        row["op_box"].configure(values=ops)
        if row["op"].get() not in ops:
            row["op"].set(cond.op if cond.op in ops else ops[0])
        if cond.spec.kind == "choice":
            row["checks"] = {}
            selected = {str(v).lower() for v in cond.values}
            for i, v in enumerate(choices(cond.spec, self._catalog())):
                var = tk.BooleanVar(value=v.lower() in selected)
                label = v if cond.key in ("set", "language") else v.title()
                tk.Checkbutton(vf, text=label, variable=var, command=self._update, bg=PANEL, fg=FG,
                               selectcolor=BG, activebackground=PANEL, activeforeground=FG,
                               highlightthickness=0, bd=0, font=(FONT, 10), anchor="w").grid(
                    row=i // 3, column=i % 3, sticky="w", padx=(0, 10), pady=1)
                row["checks"][v] = var
            if not row["checks"]:
                tk.Label(vf, text="No values yet: sort or add some cards first", bg=PANEL, fg=FAINT,
                         font=(FONT, 9)).grid(sticky="w")
        else:
            row["checks"] = None
            row["entry_var"] = tk.StringVar(value=cond.values[0] if cond.values else "")
            e = ttk.Entry(vf, textvariable=row["entry_var"], width=10 if cond.spec.kind == "number" else 26,
                          style="Panel.TEntry")
            e.grid(sticky="w")
            e.bind("<KeyRelease>", lambda ev: self._update())
            hint = "a number, e.g. 3" if cond.spec.kind == "number" else "a word or phrase"
            tk.Label(vf, text=hint, bg=PANEL, fg=FAINT, font=(FONT, 9)).grid(row=0, column=1, sticky="w", padx=8)

    def conditions(self) -> list[Condition]:
        out = []
        for row in self.rows:
            cond = row["cond"]
            cond.op = row["op"].get()
            if row["checks"] is not None:
                cond.values = [v for v, var in row["checks"].items() if var.get()]
            else:
                text = row["entry_var"].get().strip()
                if cond.spec.kind == "number":
                    try:
                        float(text)
                    except ValueError:
                        text = ""
                cond.values = [text] if text else []
            out.append(cond)
        return out

    # -- output
    def _catalog(self):
        path = Path(self.catalog_path())
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        if self._catalog_cache[0] != (path, mtime):
            try:
                self._catalog_cache = ((path, mtime), Catalog.load(path))
            except Exception:  # noqa: BLE001 - a broken list just means no suggestions
                self._catalog_cache = ((path, mtime), None)
        return self._catalog_cache[1]

    def refresh(self) -> None:
        """Card list changed: refresh suggested values and the match count."""
        self.conditions()  # keep what's ticked
        for row in self.rows:
            row["field_box"].configure(values=self._labels())
            self._build_values(row)
        self._update(write=False)

    def _update(self, write: bool = True) -> None:
        conds = self.conditions()
        if write and not self.adv_open.get():
            self.rule_var.set(rule_text(conds))
        self._show(conds)

    def _typed(self) -> None:
        conds = from_rule(self.rule_var.get())
        self._show(conds or [], typed=True)

    def _show(self, conds, typed: bool = False) -> None:
        text = self.rule_var.get().strip()
        if not text:
            self.preview.configure(text="Pick at least one value", fg=AMBER)
            self.count.configure(text="")
        else:
            try:
                rule = Rule(text)
            except RuleError as e:
                self.preview.configure(text=f"Can't read this rule: {e}", fg=AMBER)
                self.count.configure(text="")
                if self.on_change:
                    self.on_change("")
                return
            summary = describe(conds) if conds else text
            self.preview.configure(text=f"YES pile:  {summary}", fg=GREEN)
            cat = self._catalog()
            if cat is not None and len(cat):
                n = sum(1 for c in cat.cards.values() if rule(c))
                self.count.configure(text=f"{n} of the {len(cat)} cards in your list would go to YES")
            else:
                self.count.configure(text="")
            if self.on_change:
                self.on_change(f"YES:  {summary}")
            return
        if self.on_change:
            self.on_change("")

    def _toggle_adv(self) -> None:
        if self.adv_open.get():
            self.adv_entry.pack(fill="x", pady=(6, 0))
            self.rows_frame.grid_remove()
            self.add_btn.grid_remove()
            self._typed()
        else:
            self.adv_entry.pack_forget()
            self.rows_frame.grid()
            self.add_btn.grid()
            conds = from_rule(self.rule_var.get())
            if conds:
                for row in list(self.rows):
                    row["frame"].destroy()
                self.rows.clear()
                for c in conds:
                    self.add_row(c, update=False)
            self._update()
