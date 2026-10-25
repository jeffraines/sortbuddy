"""Servo test and calibration.

    python3 scripts/test_servo.py gate      # GPIO18
    python3 scripts/test_servo.py tray      # GPIO19
    python3 scripts/test_servo.py gate --loop [MIN MAX DEG_PER_SEC]
                                            # sweep back and forth until Ctrl+C
                                            # (default 10 170 90)

1. Sweeps gently around the middle (90 deg).
2. Then you nudge it by hand to find the real positions:
     a / d   -5 / +5 deg        A / D   -1 / +1 deg
     number  go to that angle   r       relax (go limp)
     q       quit and print the angles to put in SortBuddy
"""
import time

from _common import ask, fake_flag, hardware, where
import sys

fake = fake_flag()
loop = "--loop" in sys.argv
if loop:
    i = sys.argv.index("--loop")
    nums = [float(x) for x in sys.argv[i + 1:i + 4]]
    del sys.argv[i:]
    lo_deg, hi_deg, speed = (nums + [10, 170, 90][len(nums):])[:3]
which = sys.argv[1] if len(sys.argv) > 1 else ask("Which servo, gate or tray?", "gate")
pin = hardware.GATE_PIN if which == "gate" else hardware.TRAY_PIN
print(f"{which} servo on GPIO{pin} - {where()}")
servo = hardware.make_servo(pin, which, fake or None)
print(f"Driver: {type(servo).__name__}"
      + ("  (software PWM: may twitch; see docs/PI_SETUP.md step 4)" if type(servo).__name__ == "GpiozeroServo" else ""))

if loop:
    print(f"Sweeping {lo_deg:.0f} <-> {hi_deg:.0f} deg at {speed:.0f} deg/s. Ctrl+C to stop.")
    tick = 0.02                       # one servo frame
    step = speed * tick
    angle, d = 90.0, 1
    try:
        while True:
            angle += d * step
            if angle >= hi_deg or angle <= lo_deg:
                angle = max(lo_deg, min(hi_deg, angle))
                d = -d
                print(f"  {angle:.0f} deg")
            servo.move(angle)
            time.sleep(tick)
    except KeyboardInterrupt:
        print("\nStopped; back to 90 and relaxed.")
        servo.move(90)
        time.sleep(0.5)
    finally:
        servo.close()
    sys.exit(0)

try:
    print("\nSweep: 90 -> 70 -> 110 -> 90")
    for a in (90, 70, 90, 110, 90):
        servo.move(a)
        print(f"  {a:>3} deg  (pulse {hardware.angle_to_pulse_ms(a):.2f} ms)")
        time.sleep(0.7)
    print("\nDid it move smoothly, without buzzing? Now find the positions.")
    print("a/d = -5/+5, A/D = -1/+1, a number = go there, r = relax, q = quit")
    angle, marks = 90.0, {}
    while True:
        cmd = ask(f"[{angle:.0f} deg] >")
        if cmd == "":
            continue
        if cmd in ("q", "Q"):
            break
        step = {"a": -5, "d": 5, "A": -1, "D": 1}.get(cmd)
        if step is not None:
            angle = max(0, min(180, angle + step))
        elif cmd == "r":
            servo.relax()
            print("  relaxed")
            continue
        elif cmd.startswith("m "):
            marks[cmd[2:].strip()] = angle
            print(f"  marked {cmd[2:].strip()} = {angle:.0f}")
            continue
        else:
            try:
                angle = max(0, min(180, float(cmd)))
            except ValueError:
                print("  ? (a/d/A/D, a number, r, 'm name' to mark, q)")
                continue
        servo.move(angle)
    if marks:
        print("\nMarked angles:", ", ".join(f"{k}={v:.0f}" for k, v in marks.items()))
    print("Tip: 'm closed' / 'm open' (gate) or 'm level' / 'm yes' / 'm no' (tray) marks a position.")
finally:
    servo.close()
