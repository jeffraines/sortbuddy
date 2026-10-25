"""Control panel: drive every part of the machine by hand, with both
cameras live, to test and tune it.

    sortbuddy-control            (or: python3 -m sortbuddy.control)
    sortbuddy-control --fake     (no hardware: nothing moves, buttons just log)

Sliders move the servos as you drag them; "set" stores the current angle as
that position. Save writes everything to ~/.sortbuddy/hardware.json, which
the machine uses from then on.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import cv2

from . import hardware
from .camera import truncated

try:  # quiet: probing cameras otherwise prints a wall of warnings
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except AttributeError:
    pass
from .theme import ACCENT, AMBER, BG, DIM, FG, FONT, GREEN, LINE, PANEL, RED, SIDE

PREVIEW_W, PREVIEW_H = 480, 270
PREVIEW_MS = 125   # preview refresh: 8 per second is plenty to aim and focus
JOGS = [("« 1", -1.0), ("« ¼", -0.25), ("« 1/16", -1 / 16), ("1/16 »", 1 / 16), ("¼ »", 0.25), ("1 »", 1.0)]


CAMERA_FPS = 15   # plenty for a card lying still; half the USB load of 30


def open_camera(path) -> cv2.VideoCapture | None:
    cap = cv2.VideoCapture(path, cv2.CAP_V4L2) if isinstance(path, str) else cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def find_cameras() -> list[tuple[str | int, str]]:
    """(path, port) for both cameras by USB port on the Pi; the first two webcams elsewhere."""
    from .cli import usb_cameras
    return (usb_cameras() or [(i, f"camera {i}") for i in range(2)])[:2]


class CameraFeed(threading.Thread):
    """Keeps the newest frame of one camera, so the window never waits.

    Every frame is taken off the camera (grab) so nothing piles up, but only
    the ones the window asks for are decoded (retrieve): decoding 720p JPEGs
    from two cameras nonstop keeps a Pi 4 busy enough to drop USB data.
    If the camera stops sending frames, it is closed and opened again."""

    STALL = 3.0  # seconds without a frame before reconnecting

    def __init__(self, path, port: str):
        super().__init__(daemon=True)
        self.path, self.port = path, port
        self.cap = open_camera(path)
        self.frame = None
        self.fps = 0.0
        self.restarts = 0
        self.broken = 0   # frames cut short over USB, skipped
        self.wanted = threading.Event()
        self.running = True

    def run(self) -> None:
        n, t, last = 0, time.time(), time.time()
        while self.running:
            ok = self.cap.grab() if self.cap is not None else False
            now = time.time()
            if ok:
                last = now
                n += 1
                if self.wanted.is_set():
                    ok, frame = self.cap.retrieve()
                    if ok and truncated(frame):
                        self.broken += 1
                    elif ok:
                        self.frame = frame
                        self.wanted.clear()
            elif now - last > self.STALL:
                if self.cap is not None:
                    self.cap.release()
                time.sleep(0.5)
                self.cap = open_camera(self.path)
                self.restarts += 1
                last = time.time()
            else:
                time.sleep(0.05)
            if now - t >= 1:
                self.fps, n, t = n / (now - t), 0, now
        if self.cap is not None:
            self.cap.release()


class ControlPanel:
    def __init__(self, root: tk.Tk, fake: bool | None):
        self.root = root
        root.title("SortBuddy control panel" + (" (FAKE board)" if fake or not hardware.on_raspberry_pi() else ""))
        root.configure(bg=BG)
        self.m = hardware.Machine(fake=fake)
        self.a = self.m.a
        self.jobs: queue.Queue = queue.Queue()
        self.busy = tk.StringVar(value="ready")
        self.status = "ready"   # set by the motor thread, shown by the window
        threading.Thread(target=self._worker, daemon=True).start()

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=(FONT, 10))
        style.configure("TLabelframe", background=SIDE, bordercolor=LINE)
        style.configure("TLabelframe.Label", background=SIDE, foreground=ACCENT, font=(FONT, 11, "bold"))
        style.configure("TFrame", background=SIDE)
        style.configure("TLabel", background=SIDE, foreground=FG)
        style.configure("Dim.TLabel", background=SIDE, foreground=DIM)
        style.configure("TButton", background=PANEL, foreground=FG, bordercolor=LINE, padding=(8, 4))
        style.map("TButton", background=[("active", LINE)])
        style.configure("Go.TButton", background=GREEN, foreground="#000")
        style.configure("Stop.TButton", background=RED, foreground="#fff", font=(FONT, 11, "bold"))
        style.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG, bordercolor=LINE)
        style.configure("Horizontal.TScale", background=SIDE, troughcolor=PANEL)

        left = tk.Frame(root, bg=BG)
        left.pack(side="left", fill="y", padx=10, pady=10)
        right = tk.Frame(root, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=10)

        self.servo_box(left, "Gate servo (GPIO18)", self.m.gate,
                       [("closed", "gate_closed"), ("open", "gate_open")])
        self.servo_box(left, "Tray servo (GPIO19)", self.m.tray,
                       [("level", "tray_level"), ("yes", "tray_yes"), ("no", "tray_no")])
        self.stepper_box(left)
        self.machine_box(left)

        bar = tk.Frame(left, bg=BG)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="STOP", style="Stop.TButton", command=self.stop).pack(side="left")
        ttk.Button(bar, text="Save settings", command=self.save).pack(side="left", padx=8)
        tk.Label(bar, textvariable=self.busy, bg=BG, fg=AMBER, font=(FONT, 10)).pack(side="left")

        self.camera_area(right)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.bind("<Escape>", lambda e: self.stop())

    # ----------------------------------------------------------- servos
    def servo_box(self, parent, title: str, servo: hardware.Servo, presets) -> None:
        box = ttk.LabelFrame(parent, text=title, padding=8)
        box.pack(fill="x", pady=(0, 8))
        angle = tk.DoubleVar(value=servo.angle if servo.angle is not None else 90)
        label = ttk.Label(box, width=7)
        label.grid(row=0, column=3, sticky="e")

        def moved(*_):
            a = round(angle.get())
            label.config(text=f"{a:>3}°")
            servo.move(a)

        ttk.Scale(box, from_=0, to=180, variable=angle, length=300, command=moved).grid(
            row=0, column=0, columnspan=3, sticky="we")
        label.config(text=f"{round(angle.get()):>3}°")
        for col, (name, attr) in enumerate(presets):
            cell = ttk.Frame(box)
            cell.grid(row=1, column=col, padx=2, pady=(6, 0), sticky="w")
            value = ttk.Label(cell, style="Dim.TLabel")

            def go(attr=attr):
                angle.set(getattr(self.a, attr))
                moved()

            def store(attr=attr, value=value):
                setattr(self.a, attr, round(angle.get()))
                value.config(text=f"{getattr(self.a, attr):.0f}°")

            ttk.Button(cell, text=name, width=7, command=go).pack(side="left")
            ttk.Button(cell, text="set", width=4, command=store).pack(side="left", padx=2)
            value.config(text=f"{getattr(self.a, attr):.0f}°")
            value.pack(side="left")
        ttk.Button(box, text="relax", width=6, command=servo.relax).grid(row=1, column=3, pady=(6, 0), sticky="e")

    # ---------------------------------------------------------- stepper
    def stepper_box(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="Feeder stepper (GPIO17/27/22/23)", padding=8)
        box.pack(fill="x", pady=(0, 8))
        f = self.m.feeder
        self.speed = tk.DoubleVar(value=self.a.step_ms)
        speed_label = ttk.Label(box, width=16)

        def speed(*_):
            ms = round(self.speed.get(), 1)
            self.a.step_ms = ms
            f.delay = ms / 1000
            per_turn = hardware.STEPS_PER_TURN * ms / 1000
            speed_label.config(text=f"{ms:.1f} ms/step  {per_turn:.0f} s/turn")

        ttk.Label(box, text="speed  fast", style="Dim.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Scale(box, from_=0.8, to=10, variable=self.speed, length=170, command=speed).grid(row=0, column=1, columnspan=4)
        ttk.Label(box, text="slow", style="Dim.TLabel").grid(row=0, column=5, sticky="w")
        speed_label.grid(row=1, column=0, columnspan=6, sticky="w")
        speed()
        for col, (text, turns) in enumerate(JOGS):
            ttk.Button(box, text=text, width=6, command=lambda t=turns: self.run(f"turn {t:+g}", f.turn, t)).grid(
                row=2, column=col, padx=1, pady=(6, 0))
        self.position = ttk.Label(box, style="Dim.TLabel")
        self.position.grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))

        row = ttk.Frame(box)
        row.grid(row=4, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(row, text="feed distance").pack(side="left")
        self.feed_steps = tk.StringVar(value=str(self.a.feed_steps))

        def set_feed(*_):
            try:
                self.a.feed_steps = self.m.feed_steps = max(0, int(self.feed_steps.get()))
            except ValueError:
                pass

        self.feed_steps.trace_add("write", set_feed)
        ttk.Entry(row, textvariable=self.feed_steps, width=6).pack(side="left", padx=4)
        ttk.Label(row, text="steps", style="Dim.TLabel").pack(side="left")
        ttk.Button(row, text="test feed", command=lambda: self.run("feed", self.feed)).pack(side="left", padx=6)
        self.refresh_position()

    def refresh_position(self) -> None:
        p = self.m.feeder.position
        self.position.config(text=f"position {p:+d} steps ({p / hardware.STEPS_PER_TURN:+.3f} turns)")
        if self.status != self.busy.get():
            self.busy.set(self.status)
        self.root.after(100, self.refresh_position)

    def feed(self) -> None:
        self.m.feed()

    # ---------------------------------------------------------- machine
    def machine_box(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="Machine", padding=8)
        box.pack(fill="x")
        for col, (text, job) in enumerate([("feed", self.feed),
                                           ("→ YES", lambda: self.m.drop("yes")),
                                           ("→ NO", lambda: self.m.drop("no")),
                                           ("→ ?", lambda: self.m.drop("?")),
                                           ("ready", self.m.ready)]):
            ttk.Button(box, text=text, width=7, command=lambda t=text, j=job: self.run(t, j)).grid(
                row=0, column=col, padx=1)
        row = ttk.Frame(box)
        row.grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Button(row, text="Run cycle", style="Go.TButton", command=self.cycle).pack(side="left")
        self.repeat = tk.BooleanVar(value=False)
        self.repeating = False
        tk.Checkbutton(row, text="repeat until STOP", variable=self.repeat,
                       command=lambda: setattr(self, "repeating", self.repeat.get()), bg=SIDE, fg=FG,
                       selectcolor=PANEL, activebackground=SIDE, activeforeground=FG).pack(side="left", padx=6)
        settle = tk.StringVar(value=str(self.a.settle))

        def set_settle(*_):
            try:
                self.a.settle = max(0.0, float(settle.get()))
            except ValueError:
                pass

        settle.trace_add("write", set_settle)
        ttk.Label(row, text="settle").pack(side="left", padx=(6, 2))
        ttk.Entry(row, textvariable=settle, width=5).pack(side="left")
        ttk.Label(row, text="s", style="Dim.TLabel").pack(side="left")
        ttk.Label(box, text="cycle: feed → YES, feed → NO, feed → ?", style="Dim.TLabel").grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))

    def cycle(self) -> None:
        def go():
            while True:
                for verdict in ("yes", "no", "?"):
                    if self.stopping:
                        return
                    self.status = f"cycle: feed → {verdict}"
                    self.feed()
                    if self.stopping:
                        return
                    time.sleep(0.3)  # stands in for the scan
                    self.m.drop(verdict)
                if not self.repeating:
                    return
        self.run("cycle", go)

    # ---------------------------------------------------------- jobs
    stopping = False

    def run(self, name: str, fn, *args) -> None:
        """Queue a motor job: they run one at a time, off the window thread."""
        self.jobs.put((name, fn, args))

    def _worker(self) -> None:
        while True:
            name, fn, args = self.jobs.get()
            if fn is None:
                return
            self.stopping = False
            self.status = f"{name}…"
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001 - show it, keep the panel alive
                print(f"{name}: {e}", file=sys.stderr)
                self.status = f"{name} failed: {e}"
                continue
            self.status = "stopped" if self.stopping else "ready"

    def stop(self) -> None:
        self.stopping = True
        while not self.jobs.empty():
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break
        self.m.feeder.stop()
        self.status = "stopping…"

    def save(self) -> None:
        self.a.save()
        self.status = f"saved to {hardware.SETTINGS}"

    # ---------------------------------------------------------- cameras
    def camera_area(self, parent) -> None:
        self.feeds = [f for f in (CameraFeed(path, port) for path, port in find_cameras()) if f.cap is not None]
        for feed in self.feeds:
            feed.start()
        self.views = []
        names = ["Top camera", "Bottom camera"]
        for i, feed in enumerate(self.feeds):
            box = ttk.LabelFrame(parent, text=f"{names[i]}  ·  port {feed.port}", padding=4)
            box.pack(fill="both", expand=True, pady=(0, 8))
            view = tk.Label(box, bg="#000")
            view.pack()
            info = ttk.Label(box, style="Dim.TLabel")
            info.pack(anchor="w")
            self.views.append((feed, view, info))
        if not self.feeds:
            tk.Label(parent, text="No cameras found.\nPlug them in, then restart the panel.",
                     bg=BG, fg=DIM, font=(FONT, 12)).pack(pady=40)
        else:
            ttk.Button(parent, text="Snapshot both", command=self.snapshot).pack(anchor="w")
            self.refresh_cameras()

    def refresh_cameras(self) -> None:
        from .gui import to_photo
        for feed, view, info in self.views:
            frame, feed.frame = feed.frame, None
            feed.wanted.set()
            if frame is not None:
                feed.last = frame
                view.image = to_photo(frame, PREVIEW_W, PREVIEW_H)
                view.config(image=view.image)
                small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None, fx=0.5, fy=0.5)
                sharp = cv2.Laplacian(small, cv2.CV_64F).var()
                info.config(text=f"{frame.shape[1]}×{frame.shape[0]}  {feed.fps:.0f} fps  focus {sharp:.0f}"
                            + (f"  broken frames skipped {feed.broken}" if feed.broken else "")
                            + (f"  reconnected {feed.restarts}×" if feed.restarts else ""))
        self.root.after(PREVIEW_MS, self.refresh_cameras)

    def snapshot(self) -> None:
        out = Path("camera-test")
        out.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for i, (feed, _, _) in enumerate(self.views):
            frame = getattr(feed, "last", None)
            if frame is not None:
                cv2.imwrite(str(out / f"{stamp}-cam{i + 1}.jpg"), frame)
        self.status = f"snapshots in {out.resolve()}"

    # ---------------------------------------------------------- quit
    def quit(self) -> None:
        self.stop()
        self.jobs.put(("quit", None, ()))
        for feed in self.feeds:
            feed.running = False
        for feed in self.feeds:   # let each camera finish its read before Python exits
            feed.join(timeout=2)
        try:
            self.m.close()
        finally:
            self.root.destroy()


def hide_jpeg_warnings() -> None:
    """libjpeg prints "Corrupt JPEG data" for every broken frame straight to
    stderr; the panel counts those itself. Python's own messages still show."""
    sys.stderr = os.fdopen(os.dup(2), "w", buffering=1)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)


def main() -> None:
    fake = True if "--fake" in sys.argv else None
    if "--verbose" not in sys.argv:
        hide_jpeg_warnings()
    root = tk.Tk()
    ControlPanel(root, fake)
    root.mainloop()


if __name__ == "__main__":
    main()
