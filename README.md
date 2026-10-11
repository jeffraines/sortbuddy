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

## Try it

```sh
pip install -e .                 # Python 3.10+, numpy, opencv-python

sortbuddy demo demo/             # 24 fake cards + catalog, for playing with
sortbuddy index demo/catalog.json

# Hold cards (or demo images on your phone screen) up to the webcam:
sortbuddy scan demo/catalog.json --rule "cost <= 3"
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

## Using real cards

You need a catalog and a reference image for each card:

```json
[
  {"id": "OGN-001", "name": "...", "set": "OGN", "number": 1,
   "domain": ["fury"], "cost": 2, "rarity": "common",
   "image": "images/OGN-001.png"}
]
```

CSV works too (`|` separates list values). Any field you add can be used in
rules and sort plans. Then `sortbuddy index catalog.json` once, and scan.

Reference images can be official card-gallery images. If you only have
photos, `sortbuddy index catalog.json --detect` crops the card out of each.

Building a real Riftbound catalog (and an importer for whatever source has
the data) is the next step; see the roadmap in the design doc.

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
