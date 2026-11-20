#!/usr/bin/env python3
"""Command-line interface for the meeting room booking system.

Shares the same data.json and locking as app.py, so CLI and web stay in sync.

  python3 cli.py list   [--date YYYY-MM-DD] [--room aspen]
  python3 cli.py book   --room aspen --date 2025-01-20 --start 09:00 --end 10:00 --booker Ann [--title "Sync"]
  python3 cli.py cancel --id 3
"""
import argparse
import sys
from datetime import date

import app


def cmd_list(a):
    day = app.parse_date(a.date).isoformat() if a.date else None
    room = app.validate_room(a.room) if a.room else None
    rows = app.list_bookings(day, room)
    if not rows:
        print("No bookings%s." % (" for %s" % day if day else ""))
        return 0
    print("%-4s %-10s %-6s %-12s %-16s %s" % ("ID", "DATE", "ROOM", "TIME", "BOOKER", "TITLE"))
    for b in rows:
        print("%-4d %-10s %-6s %-12s %-16s %s" % (
            b["id"], b["date"], app.room_name(b["room"]),
            "%s-%s" % (b["start"], b["end"]), b["booker"], b["title"]))
    return 0


def cmd_book(a):
    rec = app.book(a.room, a.date, a.start, a.end, a.booker, a.title)
    print("Booked #%d: %s %s %s-%s for %s (%s)" % (
        rec["id"], app.room_name(rec["room"]), rec["date"], rec["start"],
        rec["end"], rec["booker"], rec["title"]))
    return 0


def cmd_cancel(a):
    rec = app.cancel(a.id)
    print("Cancelled #%d: %s %s %s-%s (%s). Slot is free again." % (
        rec["id"], app.room_name(rec["room"]), rec["date"], rec["start"],
        rec["end"], rec["booker"]))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Meeting room booking CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list bookings (optionally for a date/room)")
    pl.add_argument("--date", help="YYYY-MM-DD")
    pl.add_argument("--room", help="room id, e.g. aspen")
    pl.set_defaults(func=cmd_list)

    pb = sub.add_parser("book", help="book a room")
    pb.add_argument("--room", required=True)
    pb.add_argument("--date", required=True, help="YYYY-MM-DD")
    pb.add_argument("--start", required=True, help="HH:MM")
    pb.add_argument("--end", required=True, help="HH:MM")
    pb.add_argument("--booker", required=True)
    pb.add_argument("--title", default="")
    pb.set_defaults(func=cmd_book)

    pc = sub.add_parser("cancel", help="cancel a booking by id")
    pc.add_argument("--id", required=True, type=int)
    pc.set_defaults(func=cmd_cancel)

    a = p.parse_args(argv)
    try:
        return a.func(a)
    except app.BookingError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
