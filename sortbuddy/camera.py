"""Webcam setup: resolution, focus, and a window that fits on screen."""

from __future__ import annotations

import sys

import cv2


class Camera:
    """A webcam opened at high resolution, with manual focus control.

    Webcams with autofocus (e.g. Logitech C920) tend to focus on the table
    behind a card. Manual focus fixes that: adjust it live with [ and ],
    then pass the value as --focus next time.
    """

    FOCUS_STEP = 5  # C920 focus moves in steps of 5, range 0-255

    def __init__(self, index: int, width: int = 1920, height: int = 1080,
                 focus: int | None = None, quiet: bool = False):
        self.index = index
        if not quiet:
            print(f"Opening camera {index}...", flush=True)
        # On Windows OpenCV's default backend (Media Foundation) can hang
        # forever opening some USB webcams; DirectShow doesn't.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(index, backend)
        self.ok = self.cap.isOpened()
        if not self.ok:
            self.cap.release()
            return
        # Compressed MJPG is needed for HD at a usable frame rate over USB 2;
        # uncompressed, a C920 gives only 5 fps at 1080p. Some Windows drivers
        # only take the format if it's set again after the size, so set both.
        mjpg = cv2.VideoWriter_fourcc(*"MJPG")
        self.cap.set(cv2.CAP_PROP_FOURCC, mjpg)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FOURCC, mjpg)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.focus: int | None = None
        if focus is not None:
            self.set_focus(focus)

    def read(self):
        return self.cap.read()

    def release(self) -> None:
        self.cap.release()

    @property
    def codec(self) -> str:
        """The format the camera is actually sending, e.g. MJPG or YUY2."""
        code = int(self.cap.get(cv2.CAP_PROP_FOURCC))
        text = "".join(chr((code >> 8 * i) & 0xFF) for i in range(4)).strip("\x00 ")
        return text if text.isprintable() and text else "?"

    @property
    def size(self) -> str:
        return f"{int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}"

    def set_focus(self, value: int | None) -> None:
        """Manual focus at `value` (0-255), or None for autofocus."""
        if value is None:
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
            self.focus = None
            return
        value = max(0, min(255, int(value)))
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        self.cap.set(cv2.CAP_PROP_FOCUS, value)
        self.focus = value

    def handle_key(self, key: int) -> bool:
        """[ / ] adjust focus, A returns to autofocus. True if the key was used."""
        if key in (ord("["), ord("]")):
            start = self.focus if self.focus is not None else int(self.cap.get(cv2.CAP_PROP_FOCUS) or 0)
            self.set_focus(start + (self.FOCUS_STEP if key == ord("]") else -self.FOCUS_STEP))
            print(f"Focus {self.focus} (use --focus {self.focus} to start here next time)")
            return True
        if key == ord("a"):
            self.set_focus(None)
            print("Autofocus on")
            return True
        return False

    @property
    def focus_label(self) -> str:
        return "focus: auto" if self.focus is None else f"focus: {self.focus}"


def open_camera(index: int, focus: int | None = None, width: int = 1920, height: int = 1080) -> Camera:
    cam = Camera(index, width, height, focus)
    if not cam.ok:
        sys.exit(f"Can't open camera {index}. Try another --camera number, or run: sortbuddy cameras")
    print(f"Camera {index}: {cam.size}, {cam.focus_label}. Keys: [ ] focus, A autofocus.")
    return cam


def show(window: str, frame, max_width: int = 1100) -> int:
    """Show a frame scaled to fit the screen; returns the key pressed (or -1)."""
    scale = min(1.0, max_width / frame.shape[1])
    if scale < 1.0:
        frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.imshow(window, frame)
    return cv2.waitKey(1) & 0xFF


def overlay(frame, corners, text: str, color, footer: str = "") -> None:
    """Card outline, a banner across the top, and a status line at the bottom."""
    k = frame.shape[1] / 960  # keep text readable once the window is scaled down
    if corners is not None:
        cv2.polylines(frame, [corners.astype(int)], True, color, max(2, int(3 * k)))
    cv2.rectangle(frame, (0, 0), (frame.shape[1], int(44 * k)), (0, 0, 0), -1)
    cv2.putText(frame, text, (int(10 * k), int(30 * k)), cv2.FONT_HERSHEY_SIMPLEX, 0.8 * k, color, max(1, int(2 * k)))
    if footer:
        y = frame.shape[0] - int(12 * k)
        cv2.rectangle(frame, (0, y - int(24 * k)), (frame.shape[1], frame.shape[0]), (0, 0, 0), -1)
        cv2.putText(frame, footer, (int(10 * k), y), cv2.FONT_HERSHEY_SIMPLEX, 0.55 * k, (255, 255, 255), max(1, int(k)))
