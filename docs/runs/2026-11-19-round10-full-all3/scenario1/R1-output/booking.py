#!/usr/bin/env python3
"""Meeting room booking system - single-file, no dependencies.

Data is stored in a JSON file (default: bookings.json) next to this script.
Double bookings are prevented by an overlap check inside a file lock, so two
people booking at the same moment cannot both succeed.

Usage examples:
  python booking.py rooms
  python booking.py availability --date 2025-06-02
  python booking.py availability --date 2025-06-02 --room "Aurora"
  python booking.py book --room Aurora --date 2025-06-02 --start 09:00 --end 10:00 --by "Ana" --title "Sprint review"
  python booking.py cancel --id 3 --by "Ana"
  python booking.py list --date 2025-06-02
  python booking.py list --all
"""
import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta

try:
    import fcntl  # POSIX file locking
except ImportError:  # pragma: no cover - Windows
    fcntl = None

DATA_FILE = os.environ.get("BOOKING_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookings.json"))

ROOMS = [
    {"name": "Aurora", "capacity": 4, "location": "Floor 1", "equipment": ["TV", "whiteboard"]},
    {"name": "Borealis", "capacity": 8, "location": "Floor 1", "equipment": ["projector", "whiteboard"]},
    {"name": "Cascade", "capacity": 12, "location": "Floor 2", "equipment": ["projector", "video call"]},
    {"name": "Delta", "capacity": 20, "location": "Floor 2", "equipment": ["projector", "video call", "whiteboard"]},
]

OPEN_HOUR = 8   # rooms are bookable 08:00 - 18:00
CLOSE_HOUR = 18


# ---------------------------------------------------------------- storage
def _empty_db():
    return {"next_id": 1, "bookings": []}


def load_db():
    if not os.path.exists(DATA_FILE):
        return _empty_db()
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        try:
            db = json.load(fh)
        except json.JSONDecodeError:
            raise SystemExit(f"ERROR: data file {DATA_FILE} is not valid JSON. Fix or remove it.")
    db.setdefault("next_id", 1)
    db.setdefault("bookings", [])
    return db


def save_db(db):
    """Write atomically so a crash never leaves a half-written file."""
    directory = os.path.dirname(DATA_FILE) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".bookings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(db, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, DATA_FILE)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@contextmanager
def locked():
    """Exclusive lock around read-modify-write so concurrent bookings cannot race."""
    lock_path = DATA_FILE + ".lock"
    directory = os.path.dirname(lock_path) or "."
    os.makedirs(directory, exist_ok=True)
    with open(lock_path, "a+") as lock_fh:
        if fcntl is not None:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------- helpers
def parse_date(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(f"ERROR: invalid date '{text}'. Use YYYY-MM-DD, e.g. 2025-06-02.")


def parse_time(text):
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError:
        raise SystemExit(f"ERROR: invalid time '{text}'. Use 24h HH:MM, e.g. 09:30.")


def slot(date_s, start_s, end_s):
    """Return (start_dt, end_dt) for a booking, validating order and opening hours."""
    d = parse_date(date_s)
    start, end = parse_time(start_s), parse_time(end_s)
    if start >= end:
        raise SystemExit("ERROR: end time must be after start time.")
    if start.hour < OPEN_HOUR or (end.hour, end.minute) > (CLOSE_HOUR, 0):
        raise SystemExit(f"ERROR: rooms can only be booked between {OPEN_HOUR:02d}:00 and {CLOSE_HOUR:02d}:00.")
    return datetime.combine(d, start), datetime.combine(d, end)


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def room_names():
    return [r["name"] for r in ROOMS]


def find_room(name):
    for r in ROOMS:
        if r["name"].lower() == name.strip().lower():
            return r
    raise SystemExit(f"ERROR: unknown room '{name}'. Known rooms: {', '.join(room_names())}.")


def active_bookings(db, day=None):
    out = []
    for b in db["bookings"]:
        if b.get("status") != "active":
            continue
        if day is not None and b["date"] != day:
            continue
        out.append(b)
    return out


def fmt_booking(b):
    return (f"#{b['id']:<3} {b['date']} {b['start']}-{b['end']}  {b['room']:<9} "
            f"{b['title']}  (booked by {b['booked_by']})")


def free_slots(day, room, db):
    """List free intervals for one room on one day, clipped to opening hours."""
    day_start = datetime.combine(day, datetime.min.time()).replace(hour=OPEN_HOUR)
    day_end = datetime.combine(day, datetime.min.time()).replace(hour=CLOSE_HOUR)
    busy = []
    for b in active_bookings(db, day.isoformat()):
        if b["room"].lower() != room.lower():
            continue
        busy.append((datetime.combine(day, parse_time(b["start"])),
                     datetime.combine(day, parse_time(b["end"]))))
    busy.sort()
    free, cursor = [], day_start
    for s, e in busy:
        if s > cursor:
            free.append((cursor, min(s, day_end)))
        cursor = max(cursor, e)
    if cursor < day_end:
        free.append((cursor, day_end))
    return [(s, e) for s, e in free if s < e]


# ---------------------------------------------------------------- commands
def cmd_rooms(args):
    print(f"{'Room':<10}{'Seats':<7}{'Location':<11}Equipment")
    print("-" * 60)
    for r in ROOMS:
        print(f"{r['name']:<10}{r['capacity']:<7}{r['location']:<11}{', '.join(r['equipment'])}")


def cmd_availability(args):
    day = parse_date(args.date)
    if bool(args.start) != bool(args.end):
        raise SystemExit("ERROR: give both --start and --end, or neither.")
    if args.start and args.end:
        slot(args.date, args.start, args.end)  # validate before printing anything
    if args.min_capacity is not None and args.min_capacity < 1:
        raise SystemExit("ERROR: --min-capacity must be 1 or more.")
    db = load_db()
    rooms = [find_room(args.room)] if args.room else ROOMS
    if args.min_capacity:
        rooms = [r for r in rooms if r["capacity"] >= args.min_capacity]
        if not rooms:
            print(f"No room seats {args.min_capacity} or more.")
            return
    print(f"Availability on {day.strftime('%A %d %B %Y')} (rooms open {OPEN_HOUR:02d}:00-{CLOSE_HOUR:02d}:00)\n")
    for r in rooms:
        free = free_slots(day, r["name"], db)
        booked = [b for b in active_bookings(db, day.isoformat()) if b["room"].lower() == r["name"].lower()]
        if free:
            spans = ", ".join(f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}" for s, e in free)
        else:
            spans = "FULLY BOOKED"
        print(f"{r['name']} ({r['capacity']} seats): FREE {spans}")
        for b in sorted(booked, key=lambda x: x["start"]):
            print(f"    booked {b['start']}-{b['end']}  {b['title']} (#{b['id']}, {b['booked_by']})")
    if args.start and args.end:
        s, e = slot(args.date, args.start, args.end)
        fits = [r["name"] for r in rooms
                if any(fs <= s and e <= fe for fs, fe in free_slots(day, r["name"], db))]
        print("\nRooms free for the whole " + f"{args.start}-{args.end} slot: " + (", ".join(fits) if fits else "none"))


def cmd_book(args):
    room = find_room(args.room.strip())
    start_dt, end_dt = slot(args.date, args.start, args.end)
    if start_dt < datetime.now():
        raise SystemExit(f"ERROR: {args.date} {args.start} is in the past; book a future slot.")
    if not args.by.strip():
        raise SystemExit("ERROR: --by (who is booking) is required.")
    with locked():
        db = load_db()
        for b in active_bookings(db, args.date):
            if b["room"].lower() != room["name"].lower():
                continue
            b_s = datetime.combine(parse_date(b["date"]), parse_time(b["start"]))
            b_e = datetime.combine(parse_date(b["date"]), parse_time(b["end"]))
            if overlaps(start_dt, end_dt, b_s, b_e):
                raise SystemExit(
                    f"ERROR: double booking. {room['name']} is already booked "
                    f"{b['start']}-{b['end']} by {b['booked_by']} (#{b['id']}, {b['title']}).\n"
                    f"Run: python booking.py availability --date {args.date} --room {room['name']}")
        booking = {
            "id": db["next_id"],
            "room": room["name"],
            "date": args.date,
            "start": args.start,
            "end": args.end,
            "title": args.title.strip() or "Meeting",
            "booked_by": args.by.strip(),
            "status": "active",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        db["next_id"] += 1
        db["bookings"].append(booking)
        save_db(db)
    print(f"Booked #{booking['id']}: {fmt_booking(booking)}")


def cmd_cancel(args):
    with locked():
        db = load_db()
        target = next((b for b in db["bookings"] if b["id"] == args.id), None)
        if target is None:
            raise SystemExit(f"ERROR: no booking with id {args.id}.")
        if target.get("status") != "active":
            raise SystemExit(f"ERROR: booking #{args.id} is already cancelled.")
        if not args.by or not args.by.strip():
            raise SystemExit(f"ERROR: --by is required so we know who cancelled (booking #{args.id} belongs to {target['booked_by']}).")
        if target["booked_by"].lower() != args.by.strip().lower():
            raise SystemExit(f"ERROR: booking #{args.id} belongs to {target['booked_by']}, not {args.by}.")
        target["status"] = "cancelled"
        target["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
        target["cancelled_by"] = args.by.strip()
        save_db(db)
    print(f"Cancelled #{target['id']}: {fmt_booking(target)}")
    print("The slot is free again - check with: python booking.py availability --date " + target["date"])


def cmd_list(args):
    db = load_db()
    if args.all:
        rows = db["bookings"]
        title = "All bookings (including cancelled)"
    elif args.date:
        rows = [b for b in db["bookings"] if b["date"] == args.date]
        title = f"Bookings on {args.date}"
    else:
        today = date.today().isoformat()
        rows = [b for b in db["bookings"] if b["date"] >= today]
        title = f"Upcoming bookings (from {today})"
    if not args.all:
        rows = [b for b in rows if b.get("status") == "active"]
    if args.by:
        rows = [b for b in rows if b["booked_by"].lower() == args.by.strip().lower()]
    if not rows:
        print(f"{title}: none.")
        return
    print(title + ":")
    for b in sorted(rows, key=lambda x: (x["date"], x["start"], x["room"])):
        mark = "" if b.get("status") == "active" else "  [CANCELLED]"
        print("  " + fmt_booking(b) + mark)


def cmd_demo(args):
    """Create a few sample bookings so the system can be tried immediately."""
    with locked():
        db = load_db()
        if db["bookings"]:
            print("Data file already has bookings; demo not added.")
            return
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        samples = [
            ("Aurora", tomorrow, "09:00", "10:00", "Daily stand-up", "Ana"),
            ("Borealis", tomorrow, "10:00", "11:30", "Sprint review", "Ben"),
            ("Cascade", tomorrow, "14:00", "15:00", "Client call", "Chen"),
        ]
        for room, d, s, e, title, by in samples:
            db["bookings"].append({
                "id": db["next_id"], "room": room, "date": d, "start": s, "end": e,
                "title": title, "booked_by": by, "status": "active",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })
            db["next_id"] += 1
        save_db(db)
    print(f"Added {len(samples)} sample bookings for {tomorrow}.")


# ---------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(description="Meeting room booking system (no double bookings).")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("rooms", help="list rooms").set_defaults(func=cmd_rooms)

    a = sub.add_parser("availability", help="show free slots for a day")
    a.add_argument("--date", required=True, help="YYYY-MM-DD")
    a.add_argument("--room", help="limit to one room")
    a.add_argument("--min-capacity", type=int, help="only rooms seating at least N")
    a.add_argument("--start", help="also check which rooms are free for this start time")
    a.add_argument("--end", help="...and end time")
    a.set_defaults(func=cmd_availability)

    b = sub.add_parser("book", help="book a room")
    b.add_argument("--room", required=True)
    b.add_argument("--date", required=True)
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    b.add_argument("--by", required=True, help="your name")
    b.add_argument("--title", default="Meeting")
    b.set_defaults(func=cmd_book)

    c = sub.add_parser("cancel", help="cancel a booking by id")
    c.add_argument("--id", type=int, required=True)
    c.add_argument("--by", required=True, help="your name (must match the booking owner)")
    c.set_defaults(func=cmd_cancel)

    l = sub.add_parser("list", help="list bookings")
    l.add_argument("--date")
    l.add_argument("--by")
    l.add_argument("--all", action="store_true", help="include cancelled bookings")
    l.set_defaults(func=cmd_list)

    sub.add_parser("demo", help="add sample bookings").set_defaults(func=cmd_demo)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
