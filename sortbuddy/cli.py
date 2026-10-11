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
import re
import sys
import time
from pathlib import Path

import cv2

from .catalog import Card, Catalog, _coerce
from .demo import make_demo
from .fingerprint import FingerprintIndex
from .radix import SortPlan
from .rules import Rule, RuleError
from .session import Debouncer, Session, export_inventory
from .vision import extract_card

MAX_DISTANCE = 60  # out of 256 bits
MIN_MARGIN = 8


def open_camera(index: int, quiet: bool = False):
    """Open a webcam. On Windows, use DirectShow: OpenCV's default (Media
    Foundation) can hang forever opening some USB webcams."""
    if not quiet:
        print(f"Opening camera {index}...", flush=True)
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        if quiet:
            return None
        sys.exit(f"Can't open camera {index}. Try another --camera number, or run: sortbuddy cameras")
    return cap


def cmd_cameras(args):
    try:  # probing missing indexes makes OpenCV log a wall of warnings
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except AttributeError:
        pass
    found = 0
    for i in range(args.max):
        cap = open_camera(i, quiet=True)
        if cap is None:
            continue
        ok, frame = cap.read()
        cap.release()
        size = f"{frame.shape[1]}x{frame.shape[0]}" if ok else "opened, but no picture"
        print(f"--camera {i}: {size}")
        found += 1
    if not found:
        print("No cameras found. Is the webcam plugged in and not in use by another app?")


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
    print(f"Indexed {len(index)} cards -> {out}")
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

    cap = open_camera(args.camera)
    print("Hold one card flat in view. SPACE captures, S skips (listed cards), Q finishes.")
    added = 0
    try:
        while True:
            want = todo[0] if todo else None
            ok, frame = cap.read()
            if not ok:
                break
            found = extract_card(frame)
            prompt = f"Show: {want.name} ({want.id})" if want else "Show any card, SPACE to capture"
            _overlay(frame, found[1] if found else None,
                     prompt if found else prompt + "  [no card found]",
                     (80, 220, 80) if found else (60, 60, 230))
            cv2.imshow("SortBuddy enroll", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s") and want:
                todo.pop(0)
            if key != ord(" "):
                continue
            if not found:
                print("No card found in that frame; adjust the card or lighting and try again.")
                continue
            if want:
                save_reference(catalog, path, want.id, found[0])
                todo.pop(0)
                print(f"Saved {want.id}")
            else:
                card_id = input("Card id (e.g. OGN-042, blank to discard): ").strip()
                if not card_id:
                    continue
                name = input("Name (optional): ").strip()
                save_reference(catalog, path, card_id, found[0], name=name)
                print(f"Saved {card_id}")
            added += 1
    finally:
        cap.release()
        cv2.destroyAllWindows()
    print(f"Captured {added} card(s) into {path}")
    if len(catalog):
        build_index(str(path))
    print("Fill in fields like set, cost, domain, rarity in the catalog to sort on them.")


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


def _overlay(frame, corners, text, color):
    if corners is not None:
        cv2.polylines(frame, [corners.astype(int)], True, color, 3)
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 44), (0, 0, 0), -1)
    cv2.putText(frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)


def cmd_scan(args):
    catalog, index = _load(args.catalog)
    decide, desc = _decider(args, catalog)
    session = Session(catalog)
    debounce = Debouncer(stable=args.stable)
    log = Path(args.log or f"sessions/{time.strftime('%Y%m%d-%H%M%S')}.csv")
    log.parent.mkdir(parents=True, exist_ok=True)

    cap = open_camera(args.camera)
    gui = not args.no_window
    print(f"Sorting on: {desc}")
    print("Show one card at a time. Keys (in the window): q quit, u undo last, r rescan.")
    banner, color = "Show a card", (200, 200, 200)
    try:
        while True:
            ok, frame = cap.read()
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
                _overlay(frame, corners, banner, color)
                cv2.putText(frame, status, (10, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (255, 255, 255), 1)
                try:
                    cv2.imshow("SortBuddy", frame)
                    key = cv2.waitKey(1) & 0xFF
                except cv2.error:
                    print("No GUI available (headless OpenCV?); continuing without a window.")
                    gui = False
                    continue
                if key == ord("q"):
                    break
                if key == ord("u") and (s := session.undo()):
                    session.save_log(log)
                    banner, color = f"Undid {catalog[s.card_id].name}", (200, 200, 200)
                    print(banner)
                if key == ord("r"):
                    debounce.reset()
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if gui:
            cv2.destroyAllWindows()
    y, n = session.counts()
    print(f"\n{len(session.scans)} cards ({y} yes, {n} no). Log: {log}")


def cmd_export(args):
    catalog = Catalog.load(args.catalog)
    n = export_inventory(catalog, args.logs, args.out)
    print(f"Wrote {n} distinct cards to {args.out}")


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

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
