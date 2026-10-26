"""Printable 1:1 cutting template for the foam-board scan station.

    python3 docs/build/make_foam_template.py      -> docs/build/foam-template.pdf

Every part for 5 mm foam board, laid out on A4 pages. Print at 100%
("Actual size", not "Fit to page") and check the 50 mm square on page 1.

The design (all in mm, along the channel = the direction the card travels):

  * a 70 mm wide channel: card 63 (sleeved ~66) + room to settle straight
  * the slide (floor A + walls B) rests 15 mm onto the window
  * the window: 2 mm acrylic 80 x 130, sandwiched between the lower hood
    (panels D + bottom plate F) and the upper hood (panels C + top plate E)
  * both cameras 130 mm from the window, centred where the card stops
  * the gate (flap G on the gate servo in panel C1) stops the card 115 mm
    along the window
  * joints are tabs in notches, glued from the outside only, so nothing
    sticky ends up where cards slide
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = Path(__file__).with_name("foam-template.pdf")
T = 5            # foam board thickness
CH = 70          # channel width (inside)
HOOD = 130       # hood / window length along the channel
CAM = 130        # window to camera
GATE_X = 115     # gate flap centre, from the slide end of the window
CARD_X = 67      # where the card's centre rests (camera centre)
W, H = 210, 297  # A4 in mm
M = 10           # page margin
PAGES = 10

GREY = (0.55, 0.55, 0.55)
BLUE = (0.1, 0.35, 0.75)


# ------------------------------------------------------------------ shapes
def outline(w, h, bottom=(), top=(), depth=T, tabs=False):
    """Rectangle w x h with notches cut into (or tabs sticking out of) the
    bottom and top edges at the given x intervals."""
    s = -depth if tabs else depth
    pts = [(0, 0)]
    for a, b in sorted(bottom):
        pts += [(a, 0), (a, s), (b, s), (b, 0)]
    pts += [(w, 0), (w, h)]
    for a, b in sorted(top, reverse=True):
        pts += [(b, h), (b, h - s), (a, h - s), (a, h)]
    pts += [(0, h)]
    return pts


def poly(c, pts, dx=0, dy=0):
    p = c.beginPath()
    p.moveTo(pts[0][0] + dx, pts[0][1] + dy)
    for x, y in pts[1:]:
        p.lineTo(x + dx, y + dy)
    p.close()
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.35)
    c.setDash()
    c.drawPath(p, stroke=1, fill=0)


def guide(c, x1, y1, x2, y2, color=GREY):
    c.setStrokeColorRGB(*color)
    c.setLineWidth(0.25)
    c.setDash(1.5, 1.2)
    c.line(x1, y1, x2, y2)
    c.setDash()


def guide_rect(c, x, y, w, h, color=GREY):
    c.setStrokeColorRGB(*color)
    c.setLineWidth(0.25)
    c.setDash(1.5, 1.2)
    c.rect(x, y, w, h)
    c.setDash()


def cut_rect(c, x, y, w, h):
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.35)
    c.setDash()
    c.rect(x, y, w, h)
    # cross-hatch: "cut this out"
    c.setStrokeColorRGB(*GREY)
    c.setLineWidth(0.15)
    c.line(x, y, x + w, y + h)
    c.line(x, y + h, x + w, y)


def text(c, x, y, s, size=3.2, bold=False, color=(0, 0, 0), anchor="left"):
    c.setFillColorRGB(*color)
    font = "Helvetica-Bold" if bold else "Helvetica"
    c.setFont(font, size)
    if anchor == "centre":
        c.drawCentredString(x, y, s)
    elif anchor == "right":
        c.drawRightString(x, y, s)
    else:
        c.drawString(x, y, s)


def arrow(c, x1, y1, x2, y2, color=BLUE):
    import math
    c.setStrokeColorRGB(*color)
    c.setFillColorRGB(*color)
    c.setLineWidth(0.4)
    c.setDash()
    c.line(x1, y1, x2, y2)
    a = math.atan2(y2 - y1, x2 - x1)
    p = c.beginPath()
    p.moveTo(x2, y2)
    p.lineTo(x2 - 2.5 * math.cos(a - 0.4), y2 - 2.5 * math.sin(a - 0.4))
    p.lineTo(x2 - 2.5 * math.cos(a + 0.4), y2 - 2.5 * math.sin(a + 0.4))
    p.close()
    c.drawPath(p, stroke=0, fill=1)


def plus(c, x, y, r=3):
    c.setStrokeColorRGB(*BLUE)
    c.setLineWidth(0.3)
    c.line(x - r, y, x + r, y)
    c.line(x, y - r, x, y + r)


class Place:
    """Draw a part with its lower-left corner at (x, y) on the page,
    optionally turned 90 degrees (anticlockwise) to fit."""

    def __init__(self, c, x, y, turned_h=None):
        self.c, self.x, self.y, self.turned_h = c, x, y, turned_h

    def __enter__(self):
        self.c.saveState()
        self.c.translate(self.x, self.y)
        if self.turned_h is not None:      # part height becomes page width
            self.c.translate(self.turned_h, 0)
            self.c.rotate(90)
        return self.c

    def __exit__(self, *exc):
        self.c.restoreState()


# ------------------------------------------------------------------ parts
SLIDE_TABS = [(15, 35), (70, 90), (125, 145)]
HOOD_TABS = [(20, 45), (85, 110)]


def part_A(c):  # slide floor, 175 x 70 + tabs (bbox 175 x 80)
    poly(c, outline(175, CH, SLIDE_TABS, SLIDE_TABS, tabs=True), 0, T)
    guide(c, 160, T, 160, T + CH)
    text(c, 6, T + CH - 8, "A  Slide floor  x1", 4.2, True)
    text(c, 6, T + CH - 14, "Cover the top with packing tape or a clear file-folder sheet.")
    text(c, 6, T + CH - 19, "Tabs go into the notches of walls B.")
    arrow(c, 40, T + 25, 120, T + 25)
    text(c, 80, T + 28, "card travels", 3, color=BLUE, anchor="centre")
    text(c, 167.5, T + 40, "on the", 2.6, anchor="centre")
    text(c, 167.5, T + 36, "window", 2.6, anchor="centre")
    text(c, 167.5, T + 28, "sand a", 2.6, anchor="centre")
    text(c, 167.5, T + 24, "bevel", 2.6, anchor="centre")
    text(c, 158, T + 3, "walls end", 2.4, color=GREY, anchor="right")


def part_B(c, n):  # slide wall, 160 x 30, notches at the bottom
    poly(c, outline(160, 30, bottom=SLIDE_TABS))
    text(c, 6, 21, f"B{n}  Slide wall  (make 2)", 4, True)
    text(c, 6, 15, "notched edge = bottom, flush with the floor's underside")
    text(c, 154, 9, "hood end", 2.8, color=BLUE, anchor="right")
    arrow(c, 120, 5, 154, 5)


def part_C(c, gate_side):  # upper hood panel, 130 x 130, notches on top
    poly(c, outline(HOOD, CAM, top=HOOD_TABS))
    name = "C1  Upper hood, GATE side" if gate_side else "C2  Upper hood, plain side"
    text(c, 6, CAM - 14, name, 4.2, True)
    text(c, 6, CAM - 20, "Notched edge = top (top plate E goes there).")
    text(c, 6, CAM - 25, "Straight edge = bottom, sits on the window.")
    text(c, 6, 4, "slide end", 3, color=BLUE)
    text(c, HOOD - 6, 4, "gate end", 3, color=BLUE, anchor="right")
    guide(c, CARD_X, 8, CARD_X, CAM - 34)
    text(c, CARD_X - 2, 80, "camera line", 2.6, color=GREY, anchor="right")
    if gate_side:
        # MG90S body 23 x 12.5; its shaft ~6 mm from one end -> on the + mark
        cut_rect(c, GATE_X + 6 - 23, 30 - 6.25, 23, 12.5)
        plus(c, GATE_X, 30)
        guide(c, GATE_X, 0, GATE_X, 22, BLUE)
        for i, s in enumerate(["Cut out: the gate servo goes through", "from outside, tabs on the outside",
                               "face, shaft on the + (if your servo's", "shaft is at the other end, flip", "the hole)."]):
            text(c, 71, 62 - 4 * i, s, 2.6)
        text(c, GATE_X - 2, 12, "flap", 2.6, color=BLUE, anchor="right")


def part_D(c, n):  # lower hood panel, 130 x 140, notches at the bottom
    h = CAM + 10
    poly(c, outline(HOOD, h, bottom=HOOD_TABS))
    text(c, 6, h - 10, f"D{n}  Lower hood panel  (make 2)", 4.2, True)
    text(c, 6, h - 16, "Straight edge = top, the window rests on it.")
    text(c, 6, h - 21, "Notched edge = bottom (bottom plate F goes there).")
    text(c, 6, 10, "slide end", 3, color=BLUE)
    text(c, HOOD - 6, 10, "gate end", 3, color=BLUE, anchor="right")
    guide(c, CARD_X, 16, CARD_X, h - 28)


def plate(c, label, lines, hole):
    poly(c, outline(HOOD, CH, HOOD_TABS, HOOD_TABS, tabs=True), 0, T)
    cy = T + CH / 2
    guide_rect(c, CARD_X - 16, cy - 16, 32, 32, BLUE)
    if hole:
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.35)
        c.circle(CARD_X, cy, 7)
    plus(c, CARD_X, cy, 9)
    text(c, 4, T + CH - 7, label, 4, True)
    for i, s in enumerate(lines):
        text(c, 4, T + 14 - 4.2 * i, s, 2.7)
    text(c, HOOD - 4, T + CH - 7, "gate end", 2.8, color=BLUE, anchor="right")


def part_E(c):
    plate(c, "E  Top plate", ["Camera board on top, lens down through", "the hole (cut it to your lens).",
                              "Tabs go into the C notches."], True)


def part_F(c):
    plate(c, "F  Bottom plate", ["Camera board inside, on this square,", "lens pointing up at the window.",
                                 "Tabs go into the D notches."], False)


def part_G(c):  # gate flap
    poly(c, [(0, 0), (55, 0), (55, 32), (0, 32)])
    guide_rect(c, 3, 18, 20, 11, BLUE)
    text(c, 4, 14, "G  Gate flap  x1", 3.6, True)
    text(c, 4, 9, "Glue the servo horn on the blue box;", 2.5)
    text(c, 4, 5, "bottom edge just touches the window.", 2.5)


def part_H(c):  # splice: joins upper and lower panels across the window
    poly(c, [(0, 0), (50, 0), (50, 42), (0, 42)])
    c.setFillColorRGB(0.85, 0.9, 1)
    c.rect(0, 20, 50, 2, stroke=0, fill=1)
    text(c, 3, 35, "H  Splice  (make 4)", 3.2, True)
    text(c, 3, 25, "upper panel C", 2.5)
    text(c, 3, 16, "window edge", 2.4, color=BLUE)
    text(c, 3, 9, "lower panel D", 2.5)
    text(c, 3, 3, "glue on the OUTSIDE", 2.4)


def part_J(c):  # joins slide wall B to upper panel C, outside
    poly(c, [(0, 0), (40, 0), (40, 25), (0, 25)])
    guide(c, 20, 0, 20, 14)
    text(c, 2.5, 19, "J  Joiner x2", 3, True)
    text(c, 2.5, 9, "wall B", 2.5)
    text(c, 22, 9, "panel C", 2.5)
    text(c, 2.5, 3, "outside, over the joint", 2.2)


def part_K(c, n):  # wedge, 30 degrees
    poly(c, [(0, 0), (180, 0), (180, 104)])
    text(c, 105, 8, f"K{n}  Wedge 30°  (make 2)", 4, True)
    text(c, 105, 3, "the lower hood sits on the long slope", 2.6)
    text(c, 20, 3, "30°", 3.4, color=BLUE)


def part_L(c):  # base, 220 x 100
    poly(c, [(0, 0), (220, 0), (220, 100), (0, 100)])
    for y in (10, 85):
        guide_rect(c, 20, y, 180, T)
    text(c, 24, 55, "L  Base  x1", 4.2, True)
    text(c, 24, 49, "Glue wedges K on the dashed lines (outside faces 80 apart).")
    text(c, 24, 44, "Tall end of the wedges = slide end.")


def part_acrylic(c):
    c.setFillColorRGB(0.9, 0.95, 1)
    c.rect(0, 0, CH + 2 * T, HOOD, stroke=0, fill=1)
    poly(c, [(0, 0), (CH + 2 * T, 0), (CH + 2 * T, HOOD), (0, HOOD)])
    guide(c, T, 0, T, HOOD)
    guide(c, T + CH, 0, T + CH, HOOD)
    guide(c, 0, 15, CH + 2 * T, 15, BLUE)
    guide(c, 0, GATE_X, CH + 2 * T, GATE_X, BLUE)
    text(c, 40, 100, "ACRYLIC window", 4, True, anchor="centre")
    text(c, 40, 94, "80 x 130 from 2 mm acrylic", 2.8, anchor="centre")
    for i, s in enumerate(["Lay the acrylic on this", "and mark it. Score 10-15x", "with a knife, snap over",
                           "the table edge."]):
        text(c, 40, 86 - 4 * i, s, 2.6, anchor="centre")
    text(c, 40, GATE_X + 2, "gate", 2.6, color=BLUE, anchor="centre")
    text(c, 40, 17, "slide floor ends here", 2.6, color=BLUE, anchor="centre")
    text(c, 40, 6, "slide end", 2.8, anchor="centre")


def part_M(c):  # sorter flap (later)
    poly(c, [(0, 0), (80, 0), (80, 100), (0, 100)])
    guide(c, 40, 0, 40, 66, BLUE)
    text(c, 4, 90, "M  Sorter flap  (later)", 3.6, True)
    text(c, 4, 84, "Cards land here after the gate.", 2.6)
    text(c, 4, 80, "Servo horn under the blue line:", 2.6)
    text(c, 4, 76, "tilt left = YES, right = NO,", 2.6)
    text(c, 4, 72, "level = straight on to ?", 2.6)


def part_N(c):  # servo bracket (later)
    poly(c, [(0, 0), (50, 0), (50, 40), (0, 40)])
    cut_rect(c, 25 - 11.5, 20 - 6.25, 23, 12.5)
    text(c, 3, 34, "N  Servo holder (x2, later)", 2.8, True)
    text(c, 3, 3, "two layers glued together", 2.4)



# ------------------------------------------------------------------ hopper
# Hopper coordinates along the travel direction, from the back face of the
# back wall: back wall 0-5, stack 5-101 (96 long: sleeved card 91 + room),
# front wall 101-106, lip 106-126. The friction wheel's centre is at 67.
WHEEL_U = 67
WHEEL_R = 20
GAP = 3          # front wall stops this far above the floor; the strip sets the real gap


def part_P1(c):  # hopper floor 126 x 70
    poly(c, [(0, 0), (126, 0), (126, CH), (0, CH)])
    cut_rect(c, WHEEL_U - 18, 28, 36, 14)
    guide_rect(c, 0, 0, 5, CH)
    guide_rect(c, 101, 0, 5, CH)
    guide_rect(c, 20, 42, 80, 5, BLUE)
    text(c, 8, CH - 8, "P1  Hopper floor  x1", 4, True)
    text(c, 8, CH - 13, "Tape or plastic sheet on top (not over the slot).", 2.6)
    text(c, WHEEL_U, 22, "wheel slot", 2.6, anchor="centre")
    text(c, 22, 49.5, "bracket Q goes UNDER the floor here", 2.4, color=BLUE)
    text(c, 2.5, 3, "back", 2.2, color=GREY)
    text(c, 103.5, 12, "front", 2.2, color=GREY, anchor="centre")
    text(c, 116, 40, "lip:", 2.5, anchor="centre")
    text(c, 116, 36, "rests on", 2.5, anchor="centre")
    text(c, 116, 32, "the slide", 2.5, anchor="centre")
    arrow(c, 110, 20, 124, 20)


def part_P2(c, n):  # hopper side wall 106 x 60
    poly(c, [(0, 0), (106, 0), (106, 60), (0, 60)])
    c.setFillColorRGB(0.92, 0.92, 0.92)
    c.rect(0, 0, 106, T, stroke=0, fill=1)
    guide_rect(c, 0, T, 5, 60 - T)
    guide_rect(c, 101, T + GAP, 5, 60 - T - GAP)
    text(c, 8, 50, f"P{n + 1}  Hopper side wall", 3.8, True)
    text(c, 8, 44, "Glued against the floor's edge (grey band = floor).", 2.6)
    text(c, 8, 39.5, "Back wall at the left, front wall at the right,", 2.6)
    text(c, 8, 35, f"its bottom {GAP} mm above the floor (the throat).", 2.6)
    text(c, 99, 12, "throat", 2.4, color=BLUE, anchor="right")


def part_P4(c):  # back wall
    poly(c, [(0, 0), (CH, 0), (CH, 55), (0, 55)])
    text(c, 4, 46, "P4  Back wall", 3.6, True)
    text(c, 4, 40, "stands on the floor,", 2.5)
    text(c, 4, 36, "between the side walls", 2.5)


def part_P5(c):  # front wall with two slots for the throat strip's screws
    h = 60 - T - GAP
    poly(c, [(0, 0), (CH, 0), (CH, h), (0, h)])
    for x in (17, 53):
        cut_rect(c, x - 1.75, 19, 3.5, 14)
    text(c, 4, h - 8, "P5  Front wall", 3.6, True)
    text(c, 4, h - 13, f"bottom edge {GAP} mm above the floor", 2.4)
    text(c, 4, 4, "slots: M3 screws for strip T", 2.3)


def part_T(c):  # throat strip, cut from plastic or leftover acrylic
    c.setFillColorRGB(0.9, 0.95, 1)
    c.rect(0, 0, CH, 40, stroke=0, fill=1)
    poly(c, [(0, 0), (CH, 0), (CH, 40), (0, 40)])
    for x in (17, 53):
        c.setStrokeColorRGB(0, 0, 0)
        c.circle(x, 29, 1.75)
    text(c, 4, 20, "T  Throat strip  (PLASTIC)", 3, True)
    text(c, 4, 15, "file-folder sheet or acrylic offcut;", 2.3)
    text(c, 4, 11, "screwed on the front wall's outside.", 2.3)
    text(c, 4, 5, "Bottom edge = the gap: ~1.5 cards.", 2.3, color=BLUE)


def part_Q(c):  # motor bracket, hangs under the floor
    poly(c, [(0, 0), (80, 0), (80, 50), (0, 50)])
    bx, bz = WHEEL_U - 20, 28          # motor body centre (floor u 20..100 -> bracket 0..80)
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.35)
    c.circle(bx, bz, 14.5)
    for dx in (-17.5, 17.5):
        c.circle(bx + dx, bz, 2.1)
    plus(c, bx, bz + 8, 4)
    text(c, 3, 45, "Q  Motor bracket  x1", 3.2, True)
    text(c, bx + 6, bz + 9, "shaft", 2.3, color=BLUE)
    text(c, 3, 9, "Top edge under the floor (blue line on P1).", 2.2)
    text(c, 3, 5, "Motor's flat front on THIS side, body", 2.2)
    text(c, 3, 1.5, "through the big hole. M3 screws in the tabs.", 2.2)


def part_R(c):  # brace
    poly(c, [(0, 0), (25, 0), (0, 25)])
    text(c, 2, 3, "R brace x2", 2.4, True)


def part_W(c):  # wheel disc
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.35)
    c.circle(WHEEL_R, WHEEL_R, WHEEL_R)
    c.circle(WHEEL_R, WHEEL_R, 2.5)
    guide(c, WHEEL_R - 1.5, WHEEL_R - 3, WHEEL_R - 1.5, WHEEL_R + 3, BLUE)
    guide(c, WHEEL_R + 1.5, WHEEL_R - 3, WHEEL_R + 1.5, WHEEL_R + 3, BLUE)
    text(c, WHEEL_R, WHEEL_R + 9, "W  Wheel", 3, True, anchor="centre")
    text(c, WHEEL_R, WHEEL_R - 9, "make 2,", 2.4, anchor="centre")
    text(c, WHEEL_R, WHEEL_R - 13, "glue together", 2.4, anchor="centre")


def part_S(c):  # stack weight
    poly(c, [(0, 0), (64, 0), (64, 86), (0, 86)])
    text(c, 4, 76, "S  Stack weight", 3.6, True)
    for i, s in enumerate(["Sits on top of the cards", "so the last few still", "press on the wheel.",
                           "Tape coins on top", "(about 30-50 g)."]):
        text(c, 4, 68 - 4.5 * i, s, 2.6)


def hopper_section(c, x0, y0):
    """Cross-section of the feeder, not to scale."""
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)
    c.line(x0, y0, x0 + 58, y0)                   # floor top, behind the slot
    c.line(x0 + 72, y0, x0 + 150, y0)             # floor after the slot
    c.line(x0, y0, x0, y0 + 40)                   # back wall
    c.line(x0 + 110, y0 + 4, x0 + 110, y0 + 40)   # front wall
    c.setStrokeColorRGB(*BLUE)
    c.line(x0 + 112, y0 + 1.5, x0 + 112, y0 + 26)  # throat strip
    c.setStrokeColorRGB(0, 0, 0)
    for i in range(7):                             # the stack
        c.line(x0 + 3, y0 + 1 + 1.6 * i, x0 + 106 - (8 if i == 0 else 0) + (14 if i == 0 else 0), y0 + 1 + 1.6 * i)
    c.circle(x0 + 65, y0 - 9, 10)                  # wheel
    c.rect(x0 + 15, y0 + 13, 60, 6)                # weight
    arrow(c, x0 + 122, y0 + 2, x0 + 145, y0 + 2)
    text(c, x0 + 65, y0 - 24, "wheel W turns, the bottom card goes out", 2.6, anchor="centre")
    text(c, x0 + 45, y0 + 21, "weight S", 2.4, anchor="centre")
    text(c, x0 + 114, y0 + 30, "strip T: gap ~1.5 cards", 2.4, color=BLUE)
    text(c, x0 + 128, y0 + 5, "to the slide", 2.4, color=BLUE)
    text(c, x0, y0 - 30, "Side view, not to scale. The strip lets one card under and holds the next one back.",
         2.6, color=GREY)


# ------------------------------------------------------------------ pages
def header(c, page, title):
    text(c, M, H - M - 4, f"SortBuddy scan station: {title}", 4.5, True)
    text(c, W - M, H - M - 4, f"page {page} / {PAGES}   ·   5 mm foam board   ·   print at 100%", 3,
         color=GREY, anchor="right")


def calibration(c, x, y):
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.35)
    c.rect(x, y, 50, 50)
    for i in range(0, 51, 10):
        c.line(x + i, y, x + i, y + 3)
        c.line(x, y + i, x + 3, y + i)
    text(c, x + 25, y + 28, "50 mm", 5, True, anchor="centre")
    text(c, x + 25, y + 21, "measure me", 3, anchor="centre")


def overview(c, x0, y0):
    """Schematic side view, not to scale."""
    c.setLineWidth(0.4)
    c.setStrokeColorRGB(0, 0, 0)
    # hood boxes
    c.rect(x0 + 60, y0 + 40, 60, 40)          # upper hood
    c.rect(x0 + 60, y0, 60, 40)               # lower hood
    c.setStrokeColorRGB(*BLUE)
    c.setLineWidth(1)
    c.line(x0 + 60, y0 + 40, x0 + 120, y0 + 40)   # window
    c.setLineWidth(0.6)
    c.setStrokeColorRGB(0, 0, 0)
    c.line(x0, y0 + 41.5, x0 + 67, y0 + 41.5)  # slide floor
    c.line(x0, y0 + 47, x0 + 60, y0 + 47)      # slide wall top
    c.line(x0 + 112, y0 + 40.5, x0 + 112, y0 + 48)  # gate
    c.circle(x0 + 112, y0 + 50, 1.6)
    c.rect(x0 + 84, y0 + 80, 12, 4)            # top camera
    c.rect(x0 + 84, y0 - 0.5 + 1, 12, 4)       # bottom camera
    arrow(c, x0 + 122, y0 + 40, x0 + 140, y0 + 30)
    text(c, x0 + 2, y0 + 50, "slide (A + B)", 3)
    text(c, x0 + 90, y0 + 86, "top camera (on E)", 3, anchor="centre")
    text(c, x0 + 90, y0 + 60, "upper hood C + E", 3, anchor="centre")
    text(c, x0 + 90, y0 + 20, "lower hood D + F", 3, anchor="centre")
    text(c, x0 + 90, y0 + 6, "bottom camera", 3, anchor="centre")
    text(c, x0 + 62, y0 + 36, "acrylic window", 2.8, color=BLUE)
    text(c, x0 + 112, y0 + 54, "gate G", 3, anchor="centre")
    text(c, x0 + 141, y0 + 26, "card out", 3, color=BLUE)
    text(c, x0, y0 - 6, "Side view, not to scale. The whole thing stands tilted 30° on wedges K.", 2.8, color=GREY)


def page1(c):
    header(c, 1, "how to use this template")
    y = H - M - 16
    lines = [
        ("Print", True),
        ("Print at 100% / 'Actual size' (NOT 'Fit to page'). Measure the 50 mm square: if it isn't 50 mm, fix the print setting.", False),
        ("Cut", True),
        ("Tape each page lightly onto the foam board, cut through paper and foam with a FRESH blade, 2-3 light passes.", False),
        ("Black solid lines = cut.  Crossed boxes = cut out (holes).  Dashed = guides, don't cut.", False),
        ("Notches are exactly 5 mm (the board thickness): cut on the inside of the line so the tabs fit snug.", False),
        ("Assemble (glue only on the OUTSIDE; nothing sticky where cards slide)", True),
        ("1. Lower hood: panels D1 + D2 stand upright, bottom plate F's tabs in their notches.", False),
        ("2. Window: acrylic 80 x 130 across the top edges of D (thin double-sided tape on those edges).", False),
        ("3. Upper hood: panels C1 + C2 on the acrylic, right above D; top plate E's tabs in their notches.", False),
        ("   Splices H (x4) on the outside across the C/D seam hold the hoods and the acrylic together.", False),
        ("4. Slide: walls B onto floor A (tabs in notches). Tape or plastic sheet on the floor's top.", False),
        ("   Its end slides between C1 and C2 onto the acrylic (15 mm). Joiners J outside, wall to panel.", False),
        ("5. Gate: servo through C1's cutout from outside, horn inside. Flap G glued to the horn.", False),
        ("   Set 'closed' in the control panel so the flap's edge just touches the window.", False),
        ("6. Cameras: top board on E, lens down through the hole; bottom board on F, lens up.", False),
        ("   Long side of the picture along the channel. Hot glue the board corners only, never the lens.", False),
        ("7. Stand: wedges K on base L, lower hood on the wedges, tall end under the slide.", False),
        ("8. Light: LED strip inside the upper hood around the camera, covered with tissue or paper.", False),
        ("   In the lower hood put it along the side walls, not next to the camera (glare off the acrylic).", False),
        ("9. Hopper (pages 9-10): walls P2-P5 around floor P1. Motor on bracket Q under the floor, wheel W", False),
        ("   (rubber bands round its rim) poking ~1 mm up through the slot. Strip T on the front wall sets the", False),
        ("   gap to ~1.5 cards. The floor's lip rests 20 mm onto the top of the slide.", False),
    ]
    for s, bold in lines:
        if bold:
            y -= 2
        text(c, M, y, s, 3.4 if bold else 2.9, bold)
        y -= 5 if bold else 4.4
    c.saveState()
    c.translate(M, 72)
    c.scale(0.85, 0.85)
    overview(c, 0, 0)
    c.restoreState()
    calibration(c, W - M - 50, 20)
    parts = ["Parts (5 mm foam):", "A slide floor x1", "B slide walls x2", "C1, C2 upper hood",
             "D1, D2 lower hood", "E top plate", "F bottom plate", "G gate flap",
             "H splices x4", "J joiners x2", "K wedges x2", "L base",
             "M, N sorter (later)", "P1-P5 hopper", "Q motor bracket", "R braces x2",
             "S weight, W wheel x2", "+ acrylic 80 x 130", "+ plastic strip T"]
    for i, s in enumerate(parts):
        text(c, W - M - 42, 150 - 4.3 * i, s, 2.9, i == 0)
    text(c, M, 14, "Card: 63 x 88 mm (sleeved ~66 x 91). Channel 70 mm. Cameras 130 mm from the window, "
         "centred where the card stops against the gate.", 2.8, color=GREY)


def main() -> None:
    c = canvas.Canvas(str(OUT), pagesize=A4)
    c.setTitle("SortBuddy foam-board scan station: cutting template")

    def page(draw):
        c.saveState()
        c.scale(mm, mm)
        draw()
        c.restoreState()
        c.showPage()

    def p2():
        header(c, 2, "slide, gate flap, joiners")
        top = H - M - 12
        with Place(c, M, top - 80):
            part_A(c)
        with Place(c, M, top - 80 - 12 - 30):
            part_B(c, 1)
        with Place(c, M, top - 80 - 12 - 30 - 10 - 30):
            part_B(c, 2)
        y = top - 80 - 12 - 30 - 10 - 30 - 12 - 32
        with Place(c, M, y):
            part_G(c)
        with Place(c, M + 65, y + 7):
            part_J(c)
        with Place(c, M + 115, y + 7):
            part_J(c)

    def p3():
        header(c, 3, "upper hood panels")
        top = H - M - 12
        with Place(c, M + 30, top - CAM):
            part_C(c, True)
        with Place(c, M + 30, top - CAM - 10 - CAM):
            part_C(c, False)

    def p_lower(n, plate_fn, title):
        def draw():
            header(c, 3 + n, title)
            top = H - M - 12
            with Place(c, M + 30, top - (CAM + 10)):
                part_D(c, n)
            with Place(c, M + 30, top - (CAM + 10) - 14 - (CH + 2 * T)):
                plate_fn(c)
        return draw

    def p6():
        header(c, 6, "base and splices")
        top = H - M - 12
        with Place(c, M, top - 220, turned_h=100):
            part_L(c)
        for i in range(4):
            with Place(c, M + 120, top - 42 - i * 50):
                part_H(c)

    def p7():
        header(c, 7, "stand wedges")
        top = H - M - 12
        with Place(c, M + 5, top - 104):
            part_K(c, 1)
        with Place(c, M + 5, top - 104 - 14 - 104):
            part_K(c, 2)

    def p8():
        header(c, 8, "acrylic window, sorter (later)")
        top = H - M - 12
        with Place(c, M + 5, top - HOOD):
            part_acrylic(c)
        with Place(c, M + 100, top - 100):
            part_M(c)
        with Place(c, M + 100, top - 100 - 14 - 40):
            part_N(c)
        with Place(c, M + 100, top - 100 - 14 - 40 - 8 - 40):
            part_N(c)

    def p9():
        header(c, 9, "hopper floor and side walls")
        top = H - M - 12
        with Place(c, M + 20, top - CH):
            part_P1(c)
        with Place(c, M + 30, top - CH - 12 - 60):
            part_P2(c, 1)
        with Place(c, M + 30, top - CH - 12 - 60 - 10 - 60):
            part_P2(c, 2)
        c.saveState()
        c.translate(M + 25, 34)
        c.scale(0.62, 0.62)
        hopper_section(c, 0, 0)
        c.restoreState()

    def p10():
        header(c, 10, "hopper walls, wheel, motor bracket")
        top = H - M - 12
        with Place(c, M, top - 55):
            part_P4(c)
        with Place(c, M + 80, top - (60 - T - GAP)):
            part_P5(c)
        y2 = top - 55 - 12 - 50
        with Place(c, M, y2):
            part_Q(c)
        with Place(c, M + 90, y2 + 5):
            part_W(c)
        with Place(c, M + 140, y2 + 5):
            part_W(c)
        y3 = y2 - 12 - 86
        with Place(c, M, y3):
            part_S(c)
        with Place(c, M + 75, y3 + 46):
            part_T(c)
        with Place(c, M + 75, y3 + 5):
            part_R(c)
        with Place(c, M + 110, y3 + 5):
            part_R(c)

    for draw in (lambda: page1(c), p2, p3,
                 p_lower(1, part_E, "lower hood D1, top plate E"),
                 p_lower(2, part_F, "lower hood D2, bottom plate F"),
                 p6, p7, p8, p9, p10):
        page(draw)
    c.save()
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
