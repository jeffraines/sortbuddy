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

Everything happens in one window: settings on the left, the live camera in
the middle, and on the right either the information read from the card
you just captured or a big YES / NO while sorting. Pick the card list and
camera (*Find cameras* lists them), choose where card details come from
(Magic or Riftbound), click **Start adding cards**, then type a sort rule
and click **Start sorting**. Keys: Space capture, Enter save, Tab next name
guess, Esc discard, [ ] focus, U undo, F11 full screen.

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

## Sorting without adding cards first

You don't have to add cards before sorting. In **Start sorting**, each card
that holds still under the camera is identified, fastest way first:

1. **Already in your list?** Recognised from its picture (milliseconds).
2. **Bottom line:** OCR reads just the bottom strip for set + number
   (`FRA • EN` / `C 0029`, `OGN · 114/298 · KR`, ~0.2 s) and looks the card
   up in that set's card list, downloaded once and kept in
   `~/.sortbuddy/cache` (refreshed weekly for prices).
3. **Name:** otherwise the whole card is read and looked up by name (~1 s).

Cards found by 2 or 3 are added to your list with their photo, so the list
builds itself as you sort and the next copy, or the next pass of a
multi-pass sort, is recognised instantly. Cards that can't be identified get
a **?**: set them aside. If the rule uses `foil` or `price`, a recognised
card's bottom line is still read for its foil mark (foil is per copy).

The app warns before sorting if a rule names a field no card has (e.g.
`color` instead of `colors`), since such a rule says NO to everything.
Korean names (`name_kr`) are only read in **Add cards** mode; sorting skips
them for speed.

### Picking the rule

No typing needed: in the panel on the right (camera off), pick a field and
how to match it, e.g. **Rarity** *is any of* Rare, Epic; **Cost** *at most* 3;
**Color** *is any of* Blue. Add more conditions with **+ Add condition**
(all must match). It shows the rule in plain English and how many cards in
your list would go to YES. Fields include **Game** (Magic / Riftbound) and
**Face up or down**. Riftbound domains are also saved as colors (Mind =
blue, Fury = red, Calm = green, Body = orange, Chaos = purple, Order =
yellow), so one Color rule works for both games; **Domain** is offered when
"Card details from" is set to Riftbound.

### Card backs, face up / face down, sorting by game

While sorting, put a card face down under the camera and click **This is a
card back…**, then pick its game. From then on that back is recognised
instantly from its picture (teach it a couple of times for reliability). Its
`face` is `back` and `game` is the game, so **Face up or down** splits a pile
into face up / face down, and **Game** separates a mixed box whichever way up
the cards are. Card backs are left out of inventory exports.

### Camera

The sidebar has the picture size, focus (Auto, or a slider; the C920 moves in
steps of 5), live frames per second and a sharpness reading for the card in
view. **Find best focus** tries focus settings with a card under the camera
and keeps the sharpest. If fps is low at 1920 × 1080, try 1280 × 720.

### Mistakes it guards against

- Stacks and overlapping cards: the top card's own outline is found inside
  the pile (in simulation: the top card of 94/100 messy stacks and 100/100
  overlaps, none confidently mistaken for another card). With no clean
  outline it still reads the card, but only trusts the bottom line.
- Nudging a card doesn't decide it again; it only counts again once it's
  clearly a different card or was taken away (another copy).
- Picture matches that aren't close are checked against the bottom line.
  Cards keep up to 5 reference photos, added as they're identified.
- A card found only by name must match the name closely, and a Magic set
  code never leads to a Riftbound card (or vice versa); otherwise it's a "?".

## Riftbound cards: details filled in automatically

Choose **Card details from: Riftbound (Riftcodex)** (or `--lookup riftbound`).
The card is found by the set and number on its bottom line (`OGN · 114/298`),
so it works for any printing language: a Korean card is looked up as the
same card as the English one. Saved fields: `name`, `set`, `set_name`,
`number`, `rarity`, `domain`, `type`, `supertype`, `energy` (also as
`cost`), `power`, `might`, `text`, `artist`, `tags`, and `variant` for
alternate art / signature / overnumbered printings. Rule examples:
`domain has mind`, `cost >= 5`, `type == unit`, `rarity in rare,epic`.

Data comes from [Riftcodex](https://api.riftcodex.com/docs), a community
Riftbound card database. SortBuddy downloads a set's card list the first
time it needs it (a few requests) and keeps it in memory while enrolling.

### Korean (and other non-English) cards

The language code on the bottom line (`KR`) tells SortBuddy to read the
card again with a Korean text model, so the printed name is saved as
`name_kr` (진보의 날) next to the English `name` from the lookup (Progress
Day). The model (13 MB) downloads automatically the first time you capture
a Korean card, into `~/.sortbuddy/models`, and is checked against the
hash of the file SortBuddy was tested with.

## Magic cards: details filled in automatically

Choose **Card details from: Magic: The Gathering (Scryfall)** in the app
(or `sortbuddy enroll ... --lookup mtg`). After OCR reads the name and the
set/number in the bottom-left corner, SortBuddy looks the card up on
[Scryfall](https://scryfall.com) and saves everything sortable:

| Field | Example (Divining Duelist) | Rule example |
|---|---|---|
| `set`, `set_name`, `number` | FRA, Reality Fracture, 29 | `set == FRA` |
| `rarity` | common | `rarity in rare,mythic` |
| `cost`, `mana_cost` | 3, {2}{U} | `cost <= 3` |
| `colors`, `color_identity` | blue | `colors has blue` |
| `card_types`, `subtypes`, `type` | Creature; Merfolk, Wizard | `subtypes has wizard` |
| `power`, `toughness` | 3, 2 | `power >= 3` |
| `keywords`, `text` | Flash; rules text | `keywords has flash`, `text contains draw a card` |
| `artist`, `year` | David Auden Nash, 2026 | `year >= 2020` |
| `price`, `price_foil` | 0.25, 0.38 (USD, when enrolled) | `price >= 1` |
| `foil` | yes / no, from the bottom line: `LCI ★ EN` foil, `FRA • EN` not | `foil == yes` |

For a foil, `price` is the foil price. Cards printed before the star/dot
mark (around 2023) leave `foil` empty.

If the set code couldn't be read, the card is found by name and the window
says so; check it's the right printing before saving. Only enrolling uses
the internet; sorting never does.

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
