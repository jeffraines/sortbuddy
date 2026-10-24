"""Camera test: both USB cameras, by port.

    python3 scripts/test_cameras.py          # list, measure fps, save snapshots
    python3 scripts/test_cameras.py --live   # live view with a focus score

Live view: hold a card at 12-14 cm and turn the lens (if it turns) until
the focus number is as high as it goes. Keys: 1/2 switch camera, s save
a snapshot, q quit.
"""
import sys
import time
from pathlib import Path

import cv2

try:  # quiet: probing cameras otherwise prints a wall of warnings
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except AttributeError:
    pass

import _common  # noqa: F401 - sets up the import path
from sortbuddy.cli import usb_cameras

live = "--live" in sys.argv
out = Path("camera-test")
out.mkdir(exist_ok=True)


def open_cam(path):
    cap = cv2.VideoCapture(path, cv2.CAP_V4L2) if path.startswith("/dev") else cv2.VideoCapture(int(path))
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return cap


def fourcc(cap):
    c = int(cap.get(cv2.CAP_PROP_FOURCC))
    return "".join(chr((c >> 8 * k) & 0xFF) for k in range(4))


def focus(frame):
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    return cv2.Laplacian(g[h // 4:3 * h // 4, w // 4:3 * w // 4], cv2.CV_64F).var()


cams = usb_cameras() or [(str(i), f"index {i}") for i in range(3)]
found = []
for path, port in cams:
    cap = open_cam(path)
    ok, frame = cap.read()
    if not ok:
        cap.release()
        continue
    t, n = time.time(), 0
    while n < 30 and time.time() - t < 5:
        ok, frame = cap.read()
        n += ok
    fps = n / (time.time() - t)
    snap = out / f"cam{len(found) + 1}-{port.replace(':', '_').replace('/', '_')}.jpg"
    cv2.imwrite(str(snap), frame)
    print(f"Camera {len(found) + 1}: port {port}  {frame.shape[1]}x{frame.shape[0]}  {fourcc(cap)}  "
          f"{fps:.0f} fps  focus {focus(frame):.0f}  -> {snap}")
    found.append((path, port))
    cap.release()

if not found:
    sys.exit("No cameras found. Check the USB plugs, then: lsusb  and  v4l2-ctl --list-devices")
if len(found) < 2:
    print("Only one camera found: for top + bottom, plug in the second one.")
print("Good: MJPG, ~30 fps. Two cameras at once? Live view shows them one at a time; "
      "SortBuddy reads both.")

if live:
    i = 0
    cap = open_cam(found[i][0])
    while True:
        ok, frame = cap.read()
        if not ok:
            print("No picture.")
            break
        f = focus(frame)
        view = cv2.resize(frame, (960, 540))
        cv2.putText(view, f"cam {i + 1} ({found[i][1]})  focus {f:.0f}", (15, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("SortBuddy camera test", view)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k in (ord("1"), ord("2")) and int(chr(k)) - 1 < len(found):
            cap.release()
            i = int(chr(k)) - 1
            cap = open_cam(found[i][0])
        if k == ord("s"):
            p = out / f"live-cam{i + 1}-{int(time.time())}.jpg"
            cv2.imwrite(str(p), frame)
            print(f"saved {p}")
    cap.release()
    cv2.destroyAllWindows()
