# SortBuddy

A small, cheap bulk sorter for trading card games, meant to live on a desk
rather than take over a table.

Commercial sorters split a stack into a dozen or more bins in one go, which
is why they're big and expensive. SortBuddy answers **one yes/no question per
pass**, so the machine needs only one moving part to steer cards (a flap
that sends each card left or right). A full sort takes a few passes
instead of one. See [docs/DESIGN.md](docs/DESIGN.md) for the hardware plan.

This repo is **phase 0: software only**. Point a webcam at a dark mat, hold up
one card at a time, and it tells you YES or NO for the rule you picked and
logs what it saw. That proves out identification before any motors get
involved, and the same code is meant to run on the eventual device.

## How it works

1. **Find the card** in the frame and flatten it to an upright rectangle
   (`sortbuddy/vision.py`).
2. **Identify it** by comparing a 256-bit perceptual hash against hashes of
   reference scans of every card (`sortbuddy/fingerprint.py`). Upside-down
   and sideways cards are fine.
3. **Look up its data** (set, number, cost, domain, rarity, anything else) in
   a catalog file (`sortbuddy/catalog.py`). Nothing about the card's cost or
   color is read off the image: once we know which card it is, every sort
   parameter is a lookup. Adding a sort parameter, or a whole new game, means
   editing data, not code.
4. **Decide** YES/NO with a rule like `cost <= 3` (`sortbuddy/rules.py`).
5. **Log** each card so a session can be exported as an inventory CSV
   (`sortbuddy/session.py`).

### Full sorts with only two piles

A two-pile machine can still put a stack completely in order, using binary
radix sort (`sortbuddy/radix.py`). Each value gets a number; pass 1 splits on
the lowest bit, pass 2 on the next, and so on. After each pass you restack
NO-pile-then-YES-pile and run it again.

| Sort by                 | Distinct values | Passes |
|-------------------------|-----------------|--------|
| Rarity                  | 4               | 2      |
| Domain / color          | 6               | 3      |
| Cost 0–7                | 8               | 3      |
| Collector number 1–300  | 300             | 9      |

The sort is stable, so sorting by cost and then by domain gives you cards
grouped by domain with cost in order within each group.

## Try it with your own cards (Windows + USB webcam)

**Easiest:** install Python from python.org, then double-click
`SortBuddy.bat`. The first time, it sets itself up (a few minutes); after
that it opens the SortBuddy window directly, no terminal needed. Right-click
it → *Send to → Desktop (create shortcut)* to keep it handy.

In the window: pick or create a card list, set the camera number
(*Find cameras* lists them), click **Add cards…**, then type a sort rule
and click **Start sorting**.

The same things from a terminal:

Any standard USB webcam (e.g. a Logitech C270/C920) works.

```powershell
# Python 3.10+ from python.org, then in the repo folder:
py -m venv .venv
.venv\Scripts\activate
pip install -e .

# Optional but recommended: reads card names off the card for you
pip install rapidocr_onnxruntime

# 1. Photograph some of your cards as references. A window opens:
#    hold a card flat and press SPACE. It reads the name and set/number
#    and shows them: ENTER saves, TAB tries another line as the name,
#    E lets you type it, ESC discards.
sortbuddy cameras                         # which --camera number is your webcam
sortbuddy enroll mycards\catalog.csv --camera 1
#    Blurry? Press [ and ] in the window to focus by hand (A = autofocus),
#    then start with e.g. --focus 120 next time.

# 2. Open mycards\catalog.csv in a spreadsheet and fill in columns
#    such as set, cost, domain, rarity. Use | for multiple values: fury|chaos

# 3. Sort:
sortbuddy scan mycards\catalog.csv --rule "cost <= 3"
```

You need **one photo per distinct card**, not per copy. A dozen cards is
enough to see it working. To sort a whole set you need one of each card in
that set. A card it has no reference for should show as not found rather than
being given a YES/NO, but check this with your own cards.

If you already have a list of cards (e.g. exported from an API) in the CSV
before you start, `enroll` walks through the cards that have no photo yet
and asks for each one by name, so you don't type anything.

### More commands

```sh
sortbuddy demo demo/             # 24 fake cards + catalog, no real cards needed
sortbuddy index demo/catalog.json

sortbuddy scan demo/catalog.json --rule "domain has fury or rarity in rare,epic"

# Full sort by domain:
sortbuddy plan demo/catalog.json --key domain
sortbuddy scan demo/catalog.json --key domain --pass 1   # then --pass 2, 3

# No webcam? Use photos:
sortbuddy identify demo/catalog.json photo1.jpg photo2.jpg --rule "cost <= 3"

# Turn session logs into an inventory (id, name, set, number, rarity, quantity):
sortbuddy export demo/catalog.json sessions/*.csv -o inventory.csv
```

In the scan window: `q` quits, `u` undoes the last card, `r` lets you rescan
the card in view.

Tips for the webcam:
- Use a plain, matte background that **contrasts with the card's border**
  (light mat for black-bordered cards, dark mat otherwise).
- Diffuse light from above; glare on foils is the main thing that confuses it.
- Fill a decent part of the frame with the card. Fingers on the edge are fine.
- Enroll and scan with the same camera and lighting. Matching works best
  when reference photos look like what it sees while sorting.

## What the sorter actually stores

Reference images are only needed when building the index. Matching uses
the index: one 256-bit fingerprint (32 bytes) per card, which can't be
turned back into the picture. A finished device would ship the
fingerprints plus the card facts it sorts on (set, number, cost, domain,
rarity), not card art. Where those facts come from, and the terms
attached to that source, still needs checking before anything is sold.

Catalog format (CSV or JSON). Any field you add can be used in rules and
sort plans:

```csv
id,name,set,number,domain,cost,rarity,image
OGN-001,Some Card,OGN,1,fury,2,common,images/OGN-001.png
OGN-002,Other Card,OGN,2,fury|chaos,5,rare,images/OGN-002.png
```

Reference images can be your own webcam photos (`enroll`) or existing
scans. If you have photos with background around the card,
`sortbuddy index catalog.csv --detect` crops the card out of each.

## Tests

```sh
pip install -e '.[dev]'
pytest
```

The tests render fake cards, then "photograph" them with perspective skew,
rotation, blur, noise and color casts to check the whole find → flatten →
identify path. On 300 generated cards every one is identified correctly.
That says the pipeline works, not that real foils under a desk lamp will;
that needs real cards.
