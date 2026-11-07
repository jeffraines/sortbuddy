"""Feeder drawing: the labelled exploded view plus a strip of screw close-ups.

    python3 docs/build/print/compose_feeder.py main.png motor.png throat.png bracket.png out.png
(main.png from annotate_feeder.py; the three close-ups rendered with
 -D 'VIEW="motor"' etc., --imgsize=800,500 --camera=0,0,0,75,0,20,0)
"""
import sys
from PIL import Image, ImageDraw, ImageFont

main, motor, throat, bracket, out = sys.argv[1:6]
F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
head, txt, note = ImageFont.truetype(FB, 22), ImageFont.truetype(F, 17), ImageFont.truetype(F, 16)
ink, grey = (30, 30, 30), (95, 95, 95)

top = Image.open(main).convert("RGB")
W = top.width
pw, ph = W // 3, 400
s = pw / 800                                   # close-ups are 800 x 500

def panel(path, title, sub, parts, left, right, dx=0):
    im = Image.open(path).convert("RGB").resize((pw, int(500 * s)))
    p = Image.new("RGB", (pw, ph), (248, 248, 248))
    p.paste(im, (dx, 50))
    d = ImageDraw.Draw(p)
    d.text((14, 8), title, font=head, fill=ink)
    d.text((14, 34), sub, font=note, fill=grey)
    for name, (x, y), side in parts:
        x, y = int(x * s) + dx, int(y * s) + 50
        w = d.textlength(name, font=txt)
        if side == "right":
            d.line([(x + 8, y), (x + 40, y)], fill=grey, width=1)
            d.text((x + 46, y - 10), name, font=txt, fill=ink)
            continue
        up = side == "up"
        ty = y - 80 if up else y + 70
        d.line([(x, y + (-8 if up else 8)), (x, ty + (18 if up else -2))], fill=grey, width=1)
        d.text((max(4, min(pw - w - 4, x - w / 2)), ty), name, font=txt, fill=ink)
    d.text((14, ph - 26), left, font=note, fill=(40, 90, 160))
    w = d.textlength(right, font=note)
    d.text((pw - w - 14, ph - 26), right, font=note, fill=(40, 90, 160))
    return p

pm = panel(motor, "Motor to bracket", "2x M3 x 8, one per ear",
           [("screw head", (252, 234), "up"), ("motor ear", (348, 230), "down"), ("bracket", (426, 240), "up"),
            ("washer", (520, 262), "down"), ("nut", (590, 266), "up")],
           "<- wheel side", "back (motor body) ->")
pt = panel(throat, "Throat strip", "2x M3 x 10, one per slot",
           [("screw head", (244, 234), "up"), ("front wall", (334, 230), "down"), ("strip", (432, 240), "up"),
            ("washer", (520, 262), "down"), ("nut", (590, 266), "up")],
           "<- inside the hopper", "outside ->")
pb = panel(bracket, "Bracket to hopper floor", "2x M3 x 6, from below",
           [("hopper floor (pilot hole)", (610, 80), "right"), ("bracket flange", (610, 240), "right"),
            ("M3 x 6, no longer", (430, 370), "right")],
           "", "", dx=-150)

canvas = Image.new("RGB", (W, top.height + ph + 20), (248, 248, 248))
canvas.paste(top, (0, 0))
for i, p in enumerate((pm, pt, pb)):
    canvas.paste(p, (i * pw, top.height + 10))
d = ImageDraw.Draw(canvas)
for i in (1, 2):
    d.line([(i * pw, top.height + 20), (i * pw, top.height + ph)], fill=(220, 220, 220), width=2)
canvas.save(out)
