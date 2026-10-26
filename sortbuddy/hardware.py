"""The machine's moving parts on a Raspberry Pi: two servos and a stepper.

Wiring (see docs/WIRING.md):

    gate servo   signal -> GPIO18 (pin 12)   hardware PWM channel 0
    tray servo   signal -> GPIO19 (pin 35)   hardware PWM channel 1
    stepper      ULN2003 IN1..IN4 -> GPIO17, 27, 22, 23 (pins 11, 13, 15, 16)

Servos and stepper take their 5 V from the separate 5 V 5 A supply, never
from the Pi; only the grounds are joined.

Servos use the Pi's hardware PWM (rock steady, no jitter) through the Linux
sysfs interface; that needs one line in /boot/firmware/config.txt:

    dtoverlay=pwm-2chan,pin=18,func=2,pin2=19,func2=2

Without it, they fall back to gpiozero's software PWM, which works but can
twitch. The stepper uses gpiozero. On a computer without GPIO (the Windows
PC) everything runs against a fake board that just logs, so the rest of
SortBuddy can be tried anywhere.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

GATE_PIN, TRAY_PIN = 18, 19
STEPPER_PINS = (17, 27, 22, 23)
PWM_CHANNEL = {18: 0, 19: 1}   # GPIO -> hardware PWM channel (with the pwm-2chan overlay)

SERVO_HZ = 50
# Pulse widths for 0 and 180 deg. Measured on the MG90S copies in use: the
# common 0.5-2.4 ms range turned them ~220 deg, i.e. ~116 deg per ms around
# the 1.45 ms centre, so 180 real degrees is 1.45 +/- 0.78 ms. If a servo's
# angles look off, measure its full swing and adjust these.
MIN_PULSE_MS, MAX_PULSE_MS = 0.67, 2.23

# 28BYJ-48 half-step sequence (IN1..IN4); 4096 half-steps per output turn.
HALF_STEP = [(1, 0, 0, 0), (1, 1, 0, 0), (0, 1, 0, 0), (0, 1, 1, 0),
             (0, 0, 1, 0), (0, 0, 1, 1), (0, 0, 0, 1), (1, 0, 0, 1)]
STEPS_PER_TURN = 4096
# Each move starts and ends at RAMP_START s/step and speeds up over
# RAMP_STEPS steps: from standstill the motor stalls at speeds it can hold
# fine once turning, so ramping lets it run faster than a flat start.
RAMP_START, RAMP_STEPS = 0.003, 150


def angle_to_pulse_ms(angle: float, lo: float = MIN_PULSE_MS, hi: float = MAX_PULSE_MS) -> float:
    angle = max(0.0, min(180.0, float(angle)))
    return lo + (hi - lo) * angle / 180.0


# ------------------------------------------------------------------ servos
class Servo:
    """One hobby servo. `move(angle)` in degrees, 0-180."""

    def __init__(self, gpio: int, name: str = "", lo: float = MIN_PULSE_MS, hi: float = MAX_PULSE_MS):
        self.gpio, self.name, self.lo, self.hi = gpio, name or f"GPIO{gpio}", lo, hi
        self.angle: float | None = None

    def move(self, angle: float) -> None:
        self.angle = max(0.0, min(180.0, float(angle)))
        self._pulse(angle_to_pulse_ms(self.angle, self.lo, self.hi))

    def relax(self) -> None:
        """Stop sending pulses: the servo goes limp (no hum, no heat)."""
        self._pulse(None)

    def _pulse(self, ms: float | None) -> None:
        raise NotImplementedError

    def close(self) -> None:
        self.relax()


class SysfsServo(Servo):
    """Hardware PWM through /sys/class/pwm (needs the pwm-2chan overlay)."""

    ROOT = Path("/sys/class/pwm/pwmchip0")

    def __init__(self, gpio: int, name: str = "", **kw):
        super().__init__(gpio, name, **kw)
        self.ch = PWM_CHANNEL[gpio]
        self.dir = self.ROOT / f"pwm{self.ch}"
        if not self.dir.exists():
            (self.ROOT / "export").write_text(str(self.ch))
        # After an export, udev takes a moment to hand the new files to the
        # gpio group; until then writes fail with "permission denied".
        deadline = time.time() + 3
        while not all(os.access(self.dir / f, os.W_OK) for f in ("enable", "period", "duty_cycle")):
            if time.time() > deadline:
                raise PermissionError(
                    f"no write access to {self.dir}. Is your user in the gpio group? "
                    "Run: sudo usermod -aG gpio $USER  then log out and back in")
            time.sleep(0.05)
        self._write("enable", 0)
        self._write("duty_cycle", 0)
        self._write("period", int(1e9 / SERVO_HZ))

    def _write(self, attr: str, value) -> None:
        for attempt in range(20):
            try:
                (self.dir / attr).write_text(str(value))
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)

    def _pulse(self, ms: float | None) -> None:
        if ms is None:
            self._write("enable", 0)
            return
        self._write("duty_cycle", int(ms * 1e6))
        self._write("enable", 1)

    @classmethod
    def available(cls) -> bool:
        return (cls.ROOT / "export").exists()


class GpiozeroServo(Servo):
    """Software PWM through gpiozero (fallback; may twitch a little)."""

    def __init__(self, gpio: int, name: str = "", **kw):
        super().__init__(gpio, name, **kw)
        from gpiozero import Servo as _Servo  # noqa: PLC0415 - only on a Pi
        self._dev = _Servo(gpio, min_pulse_width=self.lo / 1000, max_pulse_width=self.hi / 1000,
                           frame_width=1 / SERVO_HZ)

    def _pulse(self, ms: float | None) -> None:
        if ms is None:
            self._dev.detach()
            return
        span = self.hi - self.lo
        self._dev.value = max(-1.0, min(1.0, (ms - self.lo) / span * 2 - 1))

    def close(self) -> None:
        self._dev.close()


# ----------------------------------------------------------------- stepper
class Stepper:
    """28BYJ-48 on a ULN2003 board. `step(n)`: + forward, - backward."""

    def __init__(self, pins=STEPPER_PINS, delay: float = 0.0015):
        self.pins, self.delay = tuple(pins), delay
        self._phase = 0
        self._stop = False
        self.position = 0  # half-steps since start

    def _set(self, levels) -> None:
        raise NotImplementedError

    def _delay_at(self, i: int, n: int) -> float:
        if self.delay <= 0 or self.delay >= RAMP_START:
            return self.delay
        k = min(i, n - 1 - i, RAMP_STEPS) / RAMP_STEPS
        return RAMP_START + (self.delay - RAMP_START) * k

    def step(self, n: int) -> None:
        d = 1 if n >= 0 else -1
        self._stop = False
        for i in range(abs(n)):
            if self._stop:
                break
            self._phase = (self._phase + d) % len(HALF_STEP)
            self._set(HALF_STEP[self._phase])
            self.position += d
            time.sleep(self._delay_at(i, abs(n)))
        self.release()

    def stop(self) -> None:
        """Stop a move in progress (from another thread)."""
        self._stop = True

    @property
    def stopped(self) -> bool:
        """True if the last move was cut short by stop()."""
        return self._stop

    def turn(self, turns: float) -> None:
        self.step(round(turns * STEPS_PER_TURN))

    def release(self) -> None:
        """All coils off, so the motor doesn't heat up while idle."""
        self._set((0, 0, 0, 0))

    def close(self) -> None:
        self.release()


class GpiozeroStepper(Stepper):
    def __init__(self, pins=STEPPER_PINS, delay: float = 0.0015):
        super().__init__(pins, delay)
        from gpiozero import DigitalOutputDevice  # noqa: PLC0415 - only on a Pi
        self._outs = [DigitalOutputDevice(p) for p in self.pins]
        self._levels = (None,) * len(self.pins)

    def _set(self, levels) -> None:
        # Only touch the pins that change: one per half-step, so less time
        # spent in Python per step.
        for out, old, v in zip(self._outs, self._levels, levels):
            if v != old:
                out.value = v
        self._levels = tuple(levels)

    def close(self) -> None:
        self.release()
        for o in self._outs:
            o.close()


# ------------------------------------------------------------- fake board
@dataclass
class FakeLog:
    events: list = field(default_factory=list)


class FakeServo(Servo):
    def __init__(self, gpio: int, name: str = "", log: FakeLog | None = None, **kw):
        super().__init__(gpio, name, **kw)
        self.log = log or FakeLog()

    def _pulse(self, ms):
        self.log.events.append((self.name, "off" if ms is None else round(ms, 3)))


class FakeStepper(Stepper):
    def __init__(self, pins=STEPPER_PINS, delay: float = 0.0, log: FakeLog | None = None):
        super().__init__(pins, delay)
        self.log = log or FakeLog()
        self.levels = (0, 0, 0, 0)

    def _set(self, levels):
        self.levels = tuple(levels)


def on_raspberry_pi() -> bool:
    try:
        return "raspberry pi" in Path("/proc/device-tree/model").read_text(errors="ignore").lower()
    except OSError:
        return False


def make_servo(gpio: int, name: str = "", fake: bool | None = None, **kw) -> Servo:
    if fake or (fake is None and not on_raspberry_pi()):
        return FakeServo(gpio, name, **kw)
    if gpio in PWM_CHANNEL and SysfsServo.available():
        # With the pwm-2chan overlay the pin belongs to the PWM hardware, so
        # software PWM can't take it over: report the real problem instead.
        return SysfsServo(gpio, name, **kw)
    return GpiozeroServo(gpio, name, **kw)


def make_stepper(fake: bool | None = None, **kw) -> Stepper:
    if fake or (fake is None and not on_raspberry_pi()):
        return FakeStepper(**kw)
    return GpiozeroStepper(**kw)


# ----------------------------------------------------------------- machine
SETTINGS = Path.home() / ".sortbuddy" / "hardware.json"


@dataclass
class Angles:
    """Positions in degrees and feeder settings; tune these on the real
    build (the control panel saves them to ~/.sortbuddy/hardware.json)."""
    gate_closed: float = 90
    gate_open: float = 30
    tray_level: float = 90
    tray_yes: float = 65    # rolled ~25 deg one way
    tray_no: float = 115    # ...and the other
    settle: float = 0.35    # seconds for a card to slide off
    feed_steps: int = 2600  # half-steps per card (wheel: ~0.6 turn moves a card ~80 mm)
    feed_return: bool = False  # True for a pusher that must come back after each card
    step_ms: float = 1.5    # stepper speed, ms per half-step

    @classmethod
    def load(cls, path: Path = SETTINGS) -> "Angles":
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            return cls()
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def save(self, path: Path = SETTINGS) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))


class Machine:
    """Gate + rolling scan tray + feeder, in the safe order: a card is only
    fed when the tray is level and the gate is closed."""

    def __init__(self, fake: bool | None = None, angles: Angles | None = None, feed_steps: int | None = None):
        self.a = angles or Angles.load()
        self.gate = make_servo(GATE_PIN, "gate", fake)
        self.tray = make_servo(TRAY_PIN, "tray", fake)
        self.feeder = make_stepper(fake)
        if not isinstance(self.feeder, FakeStepper):
            self.feeder.delay = self.a.step_ms / 1000
        self.feed_steps = feed_steps if feed_steps is not None else self.a.feed_steps
        self.ready()

    def ready(self) -> None:
        self.tray.move(self.a.tray_level)
        self.gate.move(self.a.gate_closed)
        time.sleep(self.a.settle)

    def feed(self) -> None:
        """Send one card out of the hopper: the friction wheel turns forward
        (a pusher, with feed_return, also comes back afterwards)."""
        start = self.feeder.position
        self.feeder.step(self.feed_steps)
        if self.a.feed_return and not self.feeder.stopped:
            self.feeder.step(start - self.feeder.position)

    def drop(self, verdict: str) -> None:
        """'yes', 'no' or anything else ('?'): send the card on, then reset."""
        if verdict == "yes":
            self.tray.move(self.a.tray_yes)
        elif verdict == "no":
            self.tray.move(self.a.tray_no)
        else:
            self.gate.move(self.a.gate_open)
        time.sleep(self.a.settle)
        self.ready()

    def close(self) -> None:
        for part in (self.gate, self.tray, self.feeder):
            part.close()
