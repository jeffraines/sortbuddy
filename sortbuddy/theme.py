"""Colors and font shared by the window app's parts."""

import sys

BG, SIDE, PANEL, LINE = "#121419", "#1a1d24", "#20242d", "#2c313c"
FG, DIM, FAINT = "#e9eaee", "#9aa0ae", "#5d6371"
ACCENT, GREEN, RED, AMBER = "#4f8cff", "#3ecf6e", "#ef5b5b", "#f5b942"
FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
