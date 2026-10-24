"""Both cameras at the same time, the way the machine will use them.

    python3 scripts/test_both_cameras.py

Reads the two cameras together for 10 seconds and reports the frame rate
of each. Both near 30 fps = the Pi's USB copes. If one drops to a few fps,
move the cameras to different ports (one blue, one black).
"""
import sys
import time

import cv2

try:  # quiet: probing cameras otherwise prints a wall of warnings
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except AttributeError:
    pass

import _common  # noqa: F401
from sortbuddy.cli import usb_cameras

cams = usb_cameras()
if len(cams) < 2:
    sys.exit(f"Found {len(cams)} camera(s); plug in both.")
caps = []
for path, port in cams[:2]:
    c = cv2.VideoCapture(path, cv2.CAP_V4L2)
    c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    c.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    c.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    caps.append((c, port))
counts = [0, 0]
t = time.time()
while time.time() - t < 10:
    for k, (c, _) in enumerate(caps):
        counts[k] += c.read()[0]
dt = time.time() - t
for k, (c, port) in enumerate(caps):
    print(f"camera {k + 1} (port {port}): {counts[k] / dt:.0f} fps")
    c.release()
print("OK" if min(counts) / dt > 15 else "Slow: try other USB ports, and check both say MJPG in test_cameras.py")
