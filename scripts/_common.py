"""Shared bits for the test scripts: run them from anywhere, with or
without SortBuddy installed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sortbuddy import hardware  # noqa: E402


def fake_flag() -> bool:
    """--fake: run without hardware (prints what would happen)."""
    if "--fake" in sys.argv:
        sys.argv.remove("--fake")
        return True
    return False


def ask(prompt: str, default: str = "") -> str:
    try:
        v = input(f"{prompt} " + (f"[{default}] " if default else ""))
    except EOFError:  # input closed (e.g. piped): use the default, or quit
        return default or "q"
    return v.strip() or default


def where() -> str:
    return "Raspberry Pi" if hardware.on_raspberry_pi() else "not a Pi: using the FAKE board (nothing moves)"
