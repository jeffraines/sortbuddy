"""Both cameras at the same time, the way the machine will use them.

    python3 scripts/test_both_cameras.py            # 720p, 15 fps, both together
    python3 scripts/test_both_cameras.py --modes    # also each alone, and smaller sizes

Reads the cameras for a few seconds and reports, per camera, the frame rate
and how many frames arrived cut short (grey bottom, "Corrupt JPEG data").
--modes tries several setups to find which one the Pi's USB copes with.
"""
import os
import sys
import time

import cv2

try:  # quiet: probing cameras otherwise prints a wall of warnings
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except AttributeError:
    pass

import _common  # noqa: F401
from sortbuddy.camera import truncated
from sortbuddy.cli import usb_cameras

SECONDS = 6


def run(paths, w, h, fps):
    caps = []
    for path, port in paths:
        c = cv2.VideoCapture(path, cv2.CAP_V4L2)
        c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        c.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        c.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        c.set(cv2.CAP_PROP_FPS, fps)
        caps.append((c, port))
    good, bad = [0] * len(caps), [0] * len(caps)
    t = time.time()
    while time.time() - t < SECONDS:
        for k, (c, _) in enumerate(caps):
            ok, frame = c.read()
            if ok and truncated(frame):
                bad[k] += 1
            elif ok:
                good[k] += 1
    dt = time.time() - t
    out = []
    for k, (c, port) in enumerate(caps):
        total = good[k] + bad[k]
        out.append(f"port {port}: {total / dt:4.1f} fps, {100 * bad[k] / max(1, total):3.0f}% broken")
        c.release()
    time.sleep(0.5)
    return out


cams = usb_cameras()
if not cams:
    sys.exit("No cameras found.")
print(f"Found {len(cams)} camera(s): " + ", ".join(p for _, p in cams))
print("(Corrupt JPEG lines are hidden; the % broken column counts them.)\n")

# libjpeg prints its warnings straight to stderr; hide them during the test.
devnull = os.open(os.devnull, os.O_WRONLY)
saved = os.dup(2)
os.dup2(devnull, 2)

tests = [("both", cams[:2], 1280, 720, 15)]
if "--modes" in sys.argv:
    tests = ([(f"alone {p}", [(path, p)], 1280, 720, 15) for path, p in cams[:2]]
             + [("both", cams[:2], 1280, 720, 30), ("both", cams[:2], 1280, 720, 15),
                ("both", cams[:2], 960, 540, 15), ("both", cams[:2], 640, 480, 15)])
try:
    for name, paths, w, h, fps in tests:
        result = run(paths, w, h, fps)
        os.write(saved, f"{name:>16} {w}x{h} @{fps}:  {' | '.join(result)}\n".encode())
finally:
    os.dup2(saved, 2)
print("\n0% broken = good. If 'alone' is fine but 'both' isn't, it's USB bandwidth;\n"
      "if even 'alone' breaks, it's that camera, its cable, or power.")
