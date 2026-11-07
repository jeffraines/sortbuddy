"""Labels for the feeder exploded view.

    openscad --imgsize=2000,1400 --autocenter --viewall --camera=0,0,0,55,0,25,0 \\
        --colorscheme=Tomorrow -o raw.png docs/build/print/feeder_exploded.scad
    python3 docs/build/print/annotate_feeder.py raw.png docs/build/feeder-exploded.png
"""
import sys
from PIL import Image, ImageDraw, ImageFont
src, out = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGB")
d = ImageDraw.Draw(im)
F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
big, med, small = ImageFont.truetype(FB, 30), ImageFont.truetype(FB, 24), ImageFont.truetype(F, 20)
ink, lead = (30, 30, 30), (90, 90, 90)

def label(num, title, lines, at, target, anchor="l"):
    x, y = at
    t0 = f"{num}  {title}" if num else title
    w0 = d.textlength(t0, font=med)
    ax = x + w0 + 12 if target[0] > x + w0 else x - 12
    d.line([target, (ax, y + 14)], fill=lead, width=2)
    d.ellipse([target[0] - 6, target[1] - 6, target[0] + 6, target[1] + 6], fill=lead)
    t = f"{num}  {title}" if num else title
    w = d.textlength(t, font=med)
    tx = x if anchor == "l" else x - w
    d.text((tx, y), t, font=med, fill=ink)
    for i, s in enumerate(lines):
        w2 = d.textlength(s, font=small)
        d.text((x if anchor == "l" else x - w2, y + 32 + 25 * i), s, font=small, fill=(70, 70, 70))

d.text((120, 170), "SortBuddy feeder: exploded view", font=big, fill=ink)
d.text((120, 210), "Numbers = assembly order.  Cards go in face up.", font=small, fill=(90, 90, 90))

label("7", "Stack weight", ["on top of the cards", "+ coins/nuts to 30-50 g"], (900, 270), (790, 320))
label("", "Hopper", ["wheel slot in the floor,", "bracket screws underneath"], (120, 470), (450, 540), "l")
label("5", "Throat strip", ["outside of the front wall,", "chamfered side against it.", "Gap: 1 card passes, 2 don't", "2x M3 x 10: head inside the hopper,", "washer + nut outside on the strip"], (960, 400), (905, 520))
label("4", "Motor bracket", ["flange under the hopper floor", "on the faint groove line.", "2x M3 x 6 into the pilot holes", "(no longer: 8+ pokes through the floor)"], (120, 630), (585, 720))
label("2", "28BYJ-48 motor", ["ears on the bracket's flat side,", "body through the big hole.", "2x M3 x 8: head on the ear side,", "washer + nut on the back"], (860, 930), (735, 800))
label("1 + 3", "Wheel + rubber", ["wheel_spaced.stl: its 3 mm hub keeps it", "clear of the screw heads. Rubber in the", "groove, push all the way onto the shaft.", "Pokes ~1 mm above the hopper floor"], (120, 880), (600, 860))
label("6", "Slide", ["hopper lip rests 20 mm on its floor,", "between the walls. Prop up the hopper."], (1240, 1000), (1200, 820))

bbox = (90, 150, 1720, 1140)
im.crop(bbox).save(out)
