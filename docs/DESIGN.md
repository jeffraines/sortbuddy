# SortBuddy hardware design notes

Goal: a sorter you can keep on a desk and build for roughly $80–120, aimed
at people (and small shops) with boxes of bulk. It doesn't try to be fast or
perfect. Pull your valuable cards out first; this is for bulk.

## Why two piles

The commercial machines (TCG Machines' 13-bin unit, Roca, CardMill) get their
size and price from routing each card to one of many bins in a single pass.
A machine that only answers yes/no needs:

- one feeder (pick the next card off the stack),
- one camera station,
- one diverter (a flap that sends the card up or down / left or right),
- two output trays.

Multi-bin sorts are done in passes with binary radix sort (see README). A
3- or 4-pile version later would cut the passes (base-4 radix sorts 300
collector numbers in 5 passes instead of 9) at the cost of a second flap.

## Card path

```
  hopper (stack, face up)
     │  bottom card pulled out by a rubber pick roller
     ▼
  throat gap ≈ 1 card thick  ← separation pad stops double feeds
     │
     ▼
  camera station: card stops briefly under the camera + diffuse LED light
     │  exit rollers
     ▼
  servo flap ──► YES tray
            └──► NO tray
```

Footprint target: about the size of a shoebox, with the hopper on top.

### Feeding (the hard part)

The feeder has to take exactly one card at a time, quickly, without
scuffing it. Options, roughly from simplest to gentlest:

1. **Friction pick from the bottom of the stack** (what card shufflers and
   printer paper trays do). A rubber roller under the stack pushes the
   bottom card forward through a gap about one card thick. The stack's
   weight gives grip; a rubber separation pad (or a slow reverse-spinning
   roller, as in printers) holds back the card above. Cheap, fast, proven.
   The risk is scuffing card backs; mitigate with soft silicone rollers,
   light stack weight, and only touching the back face.
2. **Friction pick from the top** with a sprung roller pressing down. Same
   idea, but the hopper must push the stack up as it shrinks. More parts.
3. **Vacuum pick**: a suction cup lifts the top card and drops it into the
   rollers. Gentlest and handles slightly bent cards, but slower and needs a
   small pump and valve.

Start with (1): it's the shuffler mechanism, so there's a lot of prior art,
and it's the smallest. Test it with a few hundred bulk commons and check for
wear before anything else gets built on top of it.

Unsleeved cards only. Sleeves change thickness and friction and would need
their own tuning.

### Keeping order

Multi-pass sorts only work if the machine preserves order: the hopper feeds
from the bottom, and each tray stacks cards in arrival order (first card in
ends up on the bottom). Then after a pass you put the NO pile in the hopper
and the YES pile on top of it. The trays should drop cards flat onto the
stack, so a slight downhill slope with a backstop works better than letting
them fly.

### Camera station

The card should be still and in the same place every time, which makes
vision much easier than the hand-held webcam case: no searching for the
card, fixed focus, fixed lighting. A stop (the exit rollers holding
position) for ~100 ms is enough for a sharp frame.

- Light: diffuse LEDs around the camera, with a matte white hood to keep
  out room light and cut glare on foils.
- Camera faces the card front. With a bottom pick roller, the roller touches
  the bottom face, so cards go in **face up** (roller on the back), and the
  camera sits above the path looking down.

### Sorting gate

A small servo (SG90 class) moving a thin flap between two positions after
the exit rollers. One moving part, and the card is already moving, so the
flap only nudges it.

### Jams and double feeds

- IR break-beam sensors at the throat and after the flap detect a card that
  didn't arrive or never left. Stop and show an error rather than
  guess.
- A double feed shows up as an unidentifiable image (two overlapped edges)
  or a too-long beam break. Stop.
- An unidentified card (unknown, foil glare, damaged): stop and ask, or
  route it to NO and log it as "unknown" so it can be pulled later.

## Electronics

Two realistic paths:

| | Raspberry Pi Zero 2 W + Camera Module 3 | ESP32-S3 + OV2640/OV5640 |
|---|---|---|
| Runs this repo's Python as is | Yes | No, needs a C++ port |
| Card index in memory | Easy | 32 bytes/card, so ~10k cards is ~320 KB of PSRAM; fits |
| Bluetooth LE | Yes | Yes |
| Boot time | ~20 s | ~1 s |
| Rough cost (board + camera) | ~$15 + ~$25 | ~$10–20 total |

Recommendation: build the prototype on the Pi Zero 2 W so this code runs
unchanged, then decide whether an ESP32 port is worth it for cost.

Other parts: a 3.5" touchscreen for choosing the rule and starting passes,
one small DC gear motor or stepper for the pick and exit rollers (one
motor plus a belt can drive both), the servo, two IR break-beams, an LED
ring, and a 5 V supply.

**No Wi-Fi.** Bluetooth LE is enough to send the inventory to a phone, and
the touchscreen covers everything else. Card data and reference fingerprints
ship on the device and are updated by USB or over BLE from the companion
app when a new set comes out.

Very rough BOM: $40 compute + camera, $15–20 screen, $15 motors and
drivers, $5 sensors and LEDs, $10–20 rollers, bearings and fasteners, plus
3D-printed body. Roughly $85–100 before shipping. These are estimates, not
quotes.

## Data and export

Every card that passes the camera is identified, so collecting inventory is
free: it's a by-product of sorting, not a slower separate mode. Export is a
CSV of id, name, set, number, rarity, quantity (`sortbuddy export`), which
can be mapped to whatever format a deck-building app imports.

For a multi-pass sort, only the first pass should count toward inventory
(otherwise each card is counted once per pass). The device should tag logs
with the pass number to make this automatic.

## Roadmap

0. **Webcam prototype** (this repo): identify cards held up to a webcam,
   yes/no by rule, log, export.
1. **Real data**: a Riftbound catalog with fields and reference images for
   every card, plus an importer. Measure identification accuracy on real
   cards, including foils, under desk lighting. Decide whether hashing alone
   is enough or if reading the collector number (bottom-left text, via OCR)
   should be a tiebreaker for near-identical printings.
2. **Feeder bench test**: just the pick roller and throat. Feed a stack of
   bulk through a few hundred times; check for double feeds and wear.
3. **Integrated prototype**: feeder + camera station + flap + trays on a Pi
   Zero 2 W, driven by this code with a hardware output in place of the
   on-screen YES/NO.
4. **Touchscreen UI and BLE export** to a phone / deck-building app.
5. Enclosure, cost-down, maybe a 3–4 pile variant.
