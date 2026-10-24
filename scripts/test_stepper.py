"""Stepper (28BYJ-48 + ULN2003) test.

    python3 scripts/test_stepper.py

Turns a quarter turn forward and back, then lets you try distances and
speeds. The four LEDs on the ULN2003 board should blink in a running
pattern. If the motor only vibrates or hums, two IN wires are swapped:
check IN1..IN4 = GPIO17, 27, 22, 23.
"""
from _common import ask, fake_flag, hardware, where

fake = fake_flag()
print(f"Stepper on GPIO{', '.join(map(str, hardware.STEPPER_PINS))} - {where()}")
m = hardware.make_stepper(fake or None)
try:
    print("Quarter turn forward...")
    m.turn(0.25)
    print("...and back.")
    m.turn(-0.25)
    print("\nCommands: a number of turns (e.g. 0.5 or -1), 's 2' = 2 ms per step "
          "(bigger = slower, stronger; below ~1 ms it may stall), q = quit")
    while True:
        cmd = ask(f"[{m.delay * 1000:.1f} ms/step, position {m.position}] >")
        if cmd in ("q", "Q"):
            break
        if cmd.startswith("s "):
            try:
                m.delay = max(0.0008, float(cmd[2:]) / 1000)
            except ValueError:
                print("  e.g. s 2")
            continue
        try:
            m.turn(float(cmd))
        except ValueError:
            if cmd:
                print("  a number of turns, 's 2', or q")
    print("Coils released (the shaft turns freely by hand now).")
finally:
    m.close()
