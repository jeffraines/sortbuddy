"""Command line entry point.

    sortbuddy demo      ./demo                         # fake card set to play with
    sortbuddy index     ./demo/catalog.json            # build fingerprint index
    sortbuddy cameras                                  # which --camera number is which
    sortbuddy enroll    ./mycards/catalog.csv          # photograph your own cards as references
    sortbuddy identify  ./demo/catalog.json photo.jpg  # identify cards in still photos
    sortbuddy scan      ./demo/catalog.json --rule "cost <= 3"
    sortbuddy plan      ./demo/catalog.json --key cost
    sortbuddy scan      ./demo/catalog.json --key cost --pass 1
    sortbuddy export    ./demo/catalog.json sessions/*.csv -o inventory.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from . import lookup, ocr
from .proposal import propose
from .camera import Camera, open_camera, overlay, show
from .catalog import Card, Catalog, _coerce
from .demo import make_demo
from .fingerprint import FingerprintIndex
from .radix import SortPlan
from .rules import Rule, RuleError
from .session import Debouncer, Session, export_inventory
from .vision import extract_card

# Hooks so the window app (gui.py) can drive the same camera loops:
# `ask` prompts for a line of text, `tick` runs once per camera frame.
ask = input
tick = None

MAX_DISTANCE = 60  # out of 256 bits
MIN_MARGIN = 8


def cmd_cameras(args):
    try:  # probing missing indexes makes OpenCV log a wall of warnings
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except AttributeError:
        pass
    found = 0
    for i in range(args.max):
        cam = Camera(i, quiet=True)
        if not cam.ok:
            continue
        ok, _ = cam.read()
        print(f"--camera {i}: {cam.size}" + ("" if ok else " (opened, but no picture)"))
        cam.release()
        found += 1
    if not found:
        print("No cameras found. Is the webcam plugged in and not in use by another app?")


def usb_cameras() -> list[tuple[str, str]]:
    """(stable path, USB port) for each camera on Linux, by the port it's
    plugged into: /dev/v4l/by-path stays the same after a restart, unlike
    /dev/video0, /dev/video1... which can swap between two identical cameras."""
    root = Path("/dev/v4l/by-path")
    if not root.exists():
        return []
    out, seen = [], set()
    for p in sorted(root.iterdir()):
        # Newer systems list each USB camera twice ("-usb-" and "-usbv2-"),
        # and the Pi's own video chips (codec, ISP) appear here too: keep
        # one entry per real USB camera.
        m = re.search(r"-usb(?:v\d+)?-(.+)-video-index0$", p.name)
        if not m:
            continue
        dev = os.path.realpath(p)
        if dev in seen:
            continue
        seen.add(dev)
        out.append((str(p), m.group(1)))
    return out


def cmd_hw(args):
    from . import hardware
    fake = True if args.fake else None
    if args.part == "cameras":
        cams = usb_cameras()
        if not cams:
            print("No /dev/v4l/by-path cameras (not Linux?). Falling back to numbered cameras:")
            return cmd_cameras(argparse.Namespace(max=6))
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for i, (path, port) in enumerate(cams):
            cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            ok, frame = cap.read()
            t, n = time.time(), 0
            while ok and n < 30 and time.time() - t < 5:
                ok, frame = cap.read()
                n += 1
            fps = n / max(1e-6, time.time() - t)
            code = int(cap.get(cv2.CAP_PROP_FOURCC))
            fourcc = "".join(chr((code >> 8 * k) & 0xFF) for k in range(4))
            if ok:
                snap = out / f"camera-{i}-{port.replace(':', '_')}.jpg"
                cv2.imwrite(str(snap), frame)
                print(f"camera {i}: port {port}  {frame.shape[1]}x{frame.shape[0]} {fourcc} {fps:.0f} fps"
                      f"  -> {snap}\n    {path}")
            else:
                print(f"camera {i}: port {port}  opened but no picture\n    {path}")
            cap.release()
        return
    if args.part == "servo":
        servo = hardware.make_servo(hardware.GATE_PIN if args.which == "gate" else hardware.TRAY_PIN,
                                    args.which, fake)
        try:
            if args.angle is not None:
                servo.move(args.angle)
                print(f"{args.which} servo at {args.angle} deg")
                time.sleep(1)
            else:
                print(f"Sweeping the {args.which} servo: 90 -> 60 -> 120 -> 90 (Ctrl+C to stop)")
                for a in (90, 60, 90, 120, 90):
                    servo.move(a)
                    print(f"  {a} deg")
                    time.sleep(0.8)
        finally:
            servo.close()
        return
    if args.part == "stepper":
        stepper = hardware.make_stepper(fake)
        try:
            print(f"Stepper: {args.turns:+} turn(s) ({round(args.turns * hardware.STEPS_PER_TURN)} half-steps)")
            stepper.turn(args.turns)
            print("Done; coils released.")
        finally:
            stepper.close()
        return
    if args.part == "cycle":
        m = hardware.Machine(fake=fake)
        try:
            for verdict in ("yes", "no", "?"):
                print(f"Card -> {verdict}")
                m.drop(verdict)
                time.sleep(0.5)
            if args.feed:
                print("Feeder: one push")
                m.feed()
        finally:
            m.close()


def _index_path(catalog_path: str) -> Path:
    return Path(catalog_path).with_suffix(".index.npz")


def _load(catalog_path: str) -> tuple[Catalog, FingerprintIndex]:
    catalog = Catalog.load(catalog_path)
    idx_path = _index_path(catalog_path)
    if not idx_path.exists():
        sys.exit(f"No index at {idx_path}. Run: sortbuddy index {catalog_path}")
    return catalog, FingerprintIndex.load(idx_path)


def _sort_plan(key: str, text: str | None, catalog: Catalog) -> SortPlan:
    known = catalog.values(key)
    if text:
        vals = [_coerce(v) for v in text.split(",") if v.strip()]
        listed = {str(v).lower() for v in vals}
        return SortPlan(key, vals, other=any(str(v).lower() not in listed for v in known))
    try:
        return SortPlan(key, sorted(known))
    except TypeError:
        return SortPlan(key, sorted(known, key=str))


def _decider(args, catalog: Catalog):
    """Returns (card -> bool, description) for --rule or --key/--pass."""
    if args.rule:
        try:
            rule = Rule(args.rule)
        except RuleError as e:
            sys.exit(f"Bad rule: {e}")
        return rule, str(rule)
    if args.key:
        plan = _sort_plan(args.key, args.values, catalog)
        p = args.pass_ - 1
        if not 0 <= p < plan.passes:
            sys.exit(f"--pass must be 1..{plan.passes} for this key")
        yes_vals = ", ".join(map(str, plan.describe_pass(p)))
        return (lambda c: plan.goes_yes(c, p)), f"{args.key} pass {p + 1}/{plan.passes} (YES: {yes_vals})"
    sys.exit("Give a --rule, or a --key and --pass")


def cmd_demo(args):
    path = make_demo(args.out, n=args.count)
    print(f"Wrote {path} and images. Next: sortbuddy index {path}")


def build_index(catalog_path: str, detect: bool = False) -> FingerprintIndex:
    catalog = Catalog.load(catalog_path)
    images, missing = {}, []
    for card in catalog.cards.values():
        p = catalog.image_path(card)
        img = cv2.imread(str(p)) if p else None
        if img is None:
            missing.append(card.id)
            continue
        # Reference scans are usually already tight crops, but photos may not be.
        found = extract_card(img) if detect else None
        images[card.id] = found[0] if found else img
    index = FingerprintIndex.from_images(images)
    out = _index_path(catalog_path)
    index.save(out)
    print(f"Indexed {len(index)} cards ({out.name})")
    if missing:
        print(f"{len(missing)} cards have no readable image (e.g. {', '.join(missing[:5])})")
    return index


def cmd_index(args):
    build_index(args.catalog, args.detect)


def save_reference(catalog: Catalog, catalog_path: str | Path, card_id: str, warped, **fields) -> Card:
    """Store a flattened card photo as the reference image for `card_id`."""
    safe = re.sub(r"[^\w.-]+", "_", card_id)
    rel = f"images/{safe}.png"
    (catalog.root / "images").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(catalog.root / rel), warped)
    card = catalog.get(card_id) or Card(card_id, {})
    card.fields.update({k: v for k, v in fields.items() if v not in (None, "")})
    card.fields["image"] = rel
    catalog.add(card)
    catalog.save(catalog_path)
    return card


def _next_auto_id(catalog: Catalog) -> str:
    n = 1
    while f"card-{n:03d}" in catalog.cards:
        n += 1
    return f"card-{n:03d}"


KIND_COLORS = {"ok": (80, 220, 80), "warn": (0, 200, 255), "error": (60, 60, 230)}


def _confirm(catalog: Catalog, card_img, text, auto_id: str, source=None):
    """Show what was read off the card; returns (card_id, fields) or None.

    ENTER saves, TAB tries the next text line as the name, E types it in
    instead, ESC throws the capture away. With a lookup `source`, the card's
    details come from the card database.
    """
    names = (text.names if text else []) or [""]
    cache: dict = {}
    i = 0
    typed_id = None
    while True:
        prop = propose(text, names[i], auto_id, source, cache)
        fields, info = prop.fields, prop.fields if prop.found else None
        card_id = typed_id or prop.card_id

        h = 640
        img = cv2.resize(card_img, (int(card_img.shape[1] * h / card_img.shape[0]), h))
        panel = np.zeros((h, 680, 3), np.uint8)
        white, grey = (255, 255, 255), (200, 200, 200)
        rows = [("Name:  " + (fields.get("name") or "(none read)"), white),
                ("Id:    " + card_id, white)]
        if prop.message:
            rows.append((prop.message, KIND_COLORS.get(prop.kind, grey)))
        if info:
            colors = "/".join(info.get("colors", []))
            price = f"${fields['price']}" if "price" in fields else ""
            rows.append((f"{info.get('mana_cost', '')}  cost {info.get('cost', '')}  {colors}  {info.get('rarity', '')}  {price}", grey))
            rows.append((info.get("type", "")[:42], grey))
        else:
            rows.append(("Set: " + str(fields.get("set", "-")) + "    #: " + str(fields.get("number", "-")), grey))
        if prop.foil is not None:
            rows.append(("Foil (star on bottom line)" if prop.foil else "Non-foil (dot on bottom line)",
                         (0, 215, 255) if prop.foil else grey))
        rows += [("", None),
                 ("ENTER  save", (80, 220, 80)),
                 (f"TAB    next guess for name ({i + 1}/{len(names)})", grey),
                 ("E      type it in", grey),
                 ("ESC    discard", (60, 60, 230))]
        if card_id in catalog.cards:
            rows.append(("Already enrolled: ENTER replaces its photo", (0, 200, 255)))
        if text is None:
            rows.insert(0, ("(no OCR: pip install rapidocr_onnxruntime)", (0, 200, 255)))
        for r, (line, color) in enumerate(rows):
            if color:
                cv2.putText(panel, line, (16, 46 + 42 * r), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
        cv2.imshow("SortBuddy enroll", np.hstack([img, panel]))
        key = cv2.waitKey(30) & 0xFF
        if tick:
            tick()
        if key == 13:
            break
        if key == 27:
            return None
        if key == 9:
            i = (i + 1) % len(names)
        if key == ord("e"):
            print("(Leave blank to keep what's in brackets.)")
            new_name = (ask(f"Name [{fields.get('name', '')}]: ") or "").strip()
            if new_name and new_name != names[i]:
                # Look the typed name up too; the next pass shows the result.
                names.insert(i + 1, new_name)
                i += 1
                continue
            typed_id = (ask(f"Card id [{card_id}]: ") or "").strip() or None
            card_id = typed_id or card_id
            break
    return card_id, fields


def cmd_enroll(args):
    path = Path(args.catalog)
    if path.exists():
        catalog = Catalog.load(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        catalog = Catalog([], path.parent)
    # Cards already listed in the catalog but without a photo are asked for in order.
    todo = [c for c in catalog.cards.values()
            if not (catalog.image_path(c) and catalog.image_path(c).exists())]
    use_ocr = not todo and not args.no_ocr and ocr.available()
    if not todo and not args.no_ocr and not use_ocr:
        print("Tip: pip install rapidocr_onnxruntime to have card names read automatically.")

    source = lookup.SOURCES[args.lookup][1] if args.lookup else None
    if source:
        print(f"Card details from: {lookup.SOURCES[args.lookup][0]}")
    cam = open_camera(args.camera, args.focus)
    print("Hold one card flat in view. SPACE captures, S skips (listed cards), Q finishes.")
    added = 0
    try:
        while True:
            want = todo[0] if todo else None
            ok, frame = cam.read()
            if not ok:
                break
            found = extract_card(frame)
            prompt = f"Show: {want.name} ({want.id})" if want else "Show a card, SPACE to capture"
            overlay(frame, found[1] if found else None,
                    prompt if found else prompt + "  [no card found]",
                    (80, 220, 80) if found else (60, 60, 230),
                    f"{cam.focus_label}   [ ] focus   A auto   Q done")
            key = show("SortBuddy enroll", frame)
            if tick:
                tick()
            if key == ord("q"):
                break
            if cam.handle_key(key):
                continue
            if key == ord("s") and want:
                todo.pop(0)
            if key != ord(" "):
                continue
            if not found:
                print("No card found in that frame; adjust the card or lighting and try again.")
                continue
            try:
                if want:
                    save_reference(catalog, path, want.id, found[0])
                    todo.pop(0)
                    print(f"Saved {want.id}")
                    added += 1
                    continue
                card_img, text = found[0], None
                if use_ocr:
                    text = ocr.read_card(card_img)
                    card_img = text.upright
                result = _confirm(catalog, card_img, text, _next_auto_id(catalog), source)
                if result:
                    card_id, fields = result
                    save_reference(catalog, path, card_id, card_img, **fields)
                    print(f"Saved {card_id}: {fields.get('name', '')}")
                    added += 1
            except PermissionError:
                # Excel locks a CSV while it's open.
                print(f"Couldn't save: {path} is open in another program (Excel?). Close it and capture again.")
    finally:
        cam.release()
        cv2.destroyAllWindows()
    print(f"Captured {added} card(s) into {path}")
    if len(catalog):
        build_index(str(path))
    print("Fill in fields like cost, domain, rarity in the catalog to sort on them.")


def cmd_identify(args):
    catalog, index = _load(args.catalog)
    decide, desc = _decider(args, catalog) if (args.rule or args.key) else (None, None)
    for path in args.images:
        frame = cv2.imread(path)
        found = extract_card(frame) if frame is not None else None
        if not found:
            print(f"{path}: no card found")
            continue
        m = index.match(found[0])
        card = catalog.get(m.card_id)
        ok = m.confident(MAX_DISTANCE, MIN_MARGIN)
        line = f"{path}: {card.name if card else m.card_id} (distance {m.distance}, margin {m.margin})"
        if not ok:
            line += " UNSURE"
        elif decide:
            line += f" -> {'YES' if decide(card) else 'NO'}"
        print(line)


def cmd_plan(args):
    catalog = Catalog.load(args.catalog)
    plan = _sort_plan(args.key, args.values, catalog)
    print(f"Sorting by {args.key}: {', '.join(map(str, plan.values))}")
    print(f"{plan.passes} pass(es) on a two-pile machine.\n")
    for p in range(plan.passes):
        print(f"Pass {p + 1}: YES pile gets {', '.join(map(str, plan.describe_pass(p)))}")
        print(f"         sortbuddy scan {args.catalog} --key {args.key} --pass {p + 1}"
              + (f" --values {args.values}" if args.values else ""))
    print("\nAfter each pass: load the NO pile into the hopper first, then the YES pile on top.")


def cmd_scan(args):
    catalog, index = _load(args.catalog)
    decide, desc = _decider(args, catalog)
    session = Session(catalog)
    debounce = Debouncer(stable=args.stable)
    log = Path(args.log or f"sessions/{time.strftime('%Y%m%d-%H%M%S')}.csv")
    log.parent.mkdir(parents=True, exist_ok=True)

    cam = open_camera(args.camera, args.focus)
    gui = not args.no_window
    print(f"Sorting on: {desc}")
    print("Show one card at a time. Keys (in the window): q quit, u undo last, r rescan.")
    banner, color = "Show a card", (200, 200, 200)
    try:
        while True:
            ok, frame = cam.read()
            if not ok:
                break
            found = extract_card(frame)
            corners, seen, status = None, None, "no card"
            if found:
                warped, corners = found
                m = index.match(warped)
                if m and m.confident(MAX_DISTANCE, MIN_MARGIN):
                    seen = m.card_id
                    status = f"{catalog[m.card_id].name}  d={m.distance} gap={m.margin}"
                elif m:
                    status = f"unsure (best {m.card_id} d={m.distance} gap={m.margin})"
            decided = debounce.update(seen)
            if decided:
                card: Card = catalog[decided]
                yes = bool(decide(card))
                session.record(decided, yes, desc)
                session.save_log(log)
                y, n = session.counts()
                banner = f"{'YES' if yes else 'NO '}  {card.name}   [yes {y} / no {n}]"
                color = (80, 220, 80) if yes else (60, 60, 230)
                print(banner, flush=True)
                if args.beep:
                    print("\a", end="", flush=True)
            if gui:
                overlay(frame, corners, banner, color, f"{status}   |   {cam.focus_label}")
                try:
                    key = show("SortBuddy", frame)
                    if tick:
                        tick()
                except cv2.error:
                    print("No GUI available (headless OpenCV?); continuing without a window.")
                    gui = False
                    continue
                if key == ord("q"):
                    break
                cam.handle_key(key)
                if key == ord("u") and (s := session.undo()):
                    session.save_log(log)
                    banner, color = f"Undid {catalog[s.card_id].name}", (200, 200, 200)
                    print(banner)
                if key == ord("r"):
                    debounce.reset()
    except KeyboardInterrupt:
        pass
    finally:
        cam.release()
        if gui:
            cv2.destroyAllWindows()
    y, n = session.counts()
    print(f"\n{len(session.scans)} cards ({y} yes, {n} no). Log: {log}")


def cmd_export(args):
    catalog = Catalog.load(args.catalog)
    n = export_inventory(catalog, args.logs, args.out)
    print(f"Wrote {n} distinct cards to {args.out}")


def cmd_listings(args):
    from .listings import export_listings
    catalog = Catalog.load(args.catalog)
    from . import pricedb
    db = pricedb.connect(pricedb.DEFAULT_DB) if pricedb.DEFAULT_DB.exists() else None
    n = export_listings(catalog, args.photos, args.out, args.min_usd, args.krw_per_usd, db)
    print(f"Wrote {n} listings to {args.out}")


def _owned(catalog, logs):
    from collections import Counter
    counts = Counter()
    for p in logs:
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not row["id"].startswith("BACK-"):
                    counts[row["id"]] += 1
    return [(cid, dict(catalog[cid].fields) if catalog.get(cid) else {}, n) for cid, n in counts.items()]


def _pct(v):
    return "" if v is None else f"{v:+.0%}"


def cmd_prices(args):
    from . import pricedb
    db = pricedb.connect(args.db)
    if args.action == "update":
        n = pricedb.update(db, args.games)
        print(f"Stored {n} prices.")
    elif args.action == "movers":
        for game in args.games:
            print(f"\n== {game}: biggest risers" + (f" under ${args.max_price}" if args.max_price else "") + " ==")
            for r in pricedb.movers(db, game, max_price=args.max_price, limit=args.limit):
                flag = "  COMEBACK" if r["comeback"] else ""
                print(f"{r['number']:<12} {r['name'][:40]:<40} ${r['price']:>8.2f}  7d {_pct(r['change_7d']):>6}"
                      f"  30d {_pct(r['change_30d']):>6}{flag}")
    elif args.action == "report":
        catalog = Catalog.load(args.catalog)
        rows = pricedb.owned_report(db, _owned(catalog, args.logs))
        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"])
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {len(rows)} cards to {args.out}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sortbuddy", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("demo", help="generate a fake card set to try things out")
    p.add_argument("out")
    p.add_argument("--count", type=int, default=24)
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("index", help="fingerprint every catalog image")
    p.add_argument("catalog")
    p.add_argument("--detect", action="store_true", help="reference images are photos; find the card in each")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("cameras", help="list webcams and their --camera numbers")
    p.add_argument("--max", type=int, default=5)
    p.set_defaults(fn=cmd_cameras)

    p = sub.add_parser("enroll", help="photograph your own cards with the webcam as references")
    p.add_argument("catalog", help="catalog .csv or .json (created if missing)")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--focus", type=int, help="manual focus 0-255 (default: autofocus)")
    p.add_argument("--no-ocr", action="store_true", help="don't read names off cards")
    p.add_argument("--lookup", choices=sorted(lookup.SOURCES),
                   help="fill in card details from an online database: auto picks by set code, "
                        "mtg = Scryfall, riftbound = Riftcodex")
    p.set_defaults(fn=cmd_enroll)

    def add_decision(p):
        p.add_argument("--rule", help='yes/no rule, e.g. "cost <= 3"')
        p.add_argument("--key", help="field for a multi-pass full sort")
        p.add_argument("--values", help="comma-separated order of values for --key (default: sorted)")
        p.add_argument("--pass", dest="pass_", type=int, default=1, help="which pass of a --key sort (1-based)")

    p = sub.add_parser("identify", help="identify cards in still images")
    p.add_argument("catalog")
    p.add_argument("images", nargs="+")
    add_decision(p)
    p.set_defaults(fn=cmd_identify)

    p = sub.add_parser("scan", help="live webcam sorting")
    p.add_argument("catalog")
    add_decision(p)
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--focus", type=int, help="manual focus 0-255 (default: autofocus)")
    p.add_argument("--stable", type=int, default=4, help="frames a match must hold before deciding")
    p.add_argument("--log", help="session log CSV (default: sessions/<time>.csv)")
    p.add_argument("--no-window", action="store_true")
    p.add_argument("--beep", action="store_true", help="terminal bell on each decision")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("plan", help="show the passes needed to fully sort by a field")
    p.add_argument("catalog")
    p.add_argument("--key", required=True)
    p.add_argument("--values")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("export", help="merge session logs into an inventory CSV")
    p.add_argument("catalog")
    p.add_argument("logs", nargs="+")
    p.add_argument("-o", "--out", default="inventory.csv")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("hw", help="test the machine's hardware: cameras, servos, stepper")
    p.add_argument("part", choices=["cameras", "servo", "stepper", "cycle"])
    p.add_argument("which", nargs="?", choices=["gate", "tray"], default="gate", help="servo: which one")
    p.add_argument("--angle", type=float, help="servo: go to this angle (0-180) instead of sweeping")
    p.add_argument("--turns", type=float, default=0.25, help="stepper: turns (negative = backwards)")
    p.add_argument("--feed", action="store_true", help="cycle: also run the feeder once")
    p.add_argument("--fake", action="store_true", help="no hardware: just print what would happen")
    p.add_argument("-o", "--out", default="camera-test", help="cameras: folder for test snapshots")
    p.set_defaults(fn=cmd_hw)

    p = sub.add_parser("prices", help="US prices (TCGCSV), trends and risers")
    p.add_argument("action", choices=["update", "movers", "report"],
                   help="update: download today's prices; movers: biggest risers; report: your cards' prices")
    p.add_argument("--games", nargs="+", default=["onepiece", "riftbound", "pokemon"],
                   help="onepiece riftbound pokemon pokemon-jp magic")
    p.add_argument("--db", default=str(Path.home() / ".sortbuddy" / "prices.db"))
    p.add_argument("--max-price", type=float, help="movers: only cards cheaper than this (USD)")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--catalog", help="report: your card list")
    p.add_argument("--logs", nargs="*", default=[], help="report: session logs (which cards you own)")
    p.add_argument("-o", "--out", default="price-report.csv")
    p.set_defaults(fn=cmd_prices)

    p = sub.add_parser("listings", help="sale listings (photos + text) for the valuable cards photographed")
    p.add_argument("catalog")
    p.add_argument("photos", nargs="+", help="photo folders of sorting sessions")
    p.add_argument("-o", "--out", default="listings")
    p.add_argument("--min-usd", type=float, default=1.0, help="only cards worth at least this")
    p.add_argument("--krw-per-usd", type=float, default=1400.0, help="exchange rate for asking prices")
    p.set_defaults(fn=cmd_listings)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
