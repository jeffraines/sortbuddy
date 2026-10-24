"""Guided check of the whole machine, one part at a time.

    python3 scripts/test_all.py          (add --fake to try without hardware)

Asks before each step, so you can stop if something looks wrong.
"""
import time

from _common import ask, fake_flag, hardware, where

fake = fake_flag()
print(f"SortBuddy hardware check - {where()}\n")
print("Before starting: wiring as in docs/WIRING.md, motor adapter plugged in,")
print("capacitor stripe to the GND rail, nothing touching the servo horns.\n")


def step(title):
    return ask(f"\n== {title} == run it? (y/n)", "y").lower().startswith("y")


if step("Gate servo (GPIO18)"):
    s = hardware.make_servo(hardware.GATE_PIN, "gate", fake or None)
    for a in (90, 60, 90):
        s.move(a)
        time.sleep(0.6)
    s.close()
    print("Moved 90 -> 60 -> 90?", ask("(y/n)", "y"))

if step("Tray servo (GPIO19)"):
    s = hardware.make_servo(hardware.TRAY_PIN, "tray", fake or None)
    for a in (90, 65, 90, 115, 90):
        s.move(a)
        time.sleep(0.6)
    s.close()
    print("Rolled one way, then the other?", ask("(y/n)", "y"))

if step("Stepper (GPIO17/27/22/23)"):
    m = hardware.make_stepper(fake or None)
    m.turn(0.25)
    m.turn(-0.25)
    m.close()
    print("Quarter turn and back?", ask("(y/n)", "y"))

if step("Cameras"):
    import subprocess
    import sys
    from pathlib import Path
    subprocess.run([sys.executable, str(Path(__file__).with_name("test_cameras.py"))])

if step("Full cycle: YES, NO, ? in the machine's order"):
    mach = hardware.Machine(fake=fake or None)
    for v in ("yes", "no", "?"):
        print(f"  card -> {v}")
        mach.drop(v)
        time.sleep(0.4)
    mach.close()

print("\nDone. Anything that didn't move right: send me what you saw.")
