#!/usr/bin/env python3
"""Meeting room booking system (v1.1).

Standard library only: run with `python3 app.py` and open http://localhost:8000/

Data is stored in a local SQLite file (bookings.db, created automatically).
"""
import json
import os
import re
import sqlite3
import sys
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = os.environ.get("BOOKINGS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookings.db"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

OPEN_HOUR = 8          # working hours 08:00-18:00
CLOSE_HOUR = 18
SLOT_MINUTES = 30
MAX_BOOKING_MINUTES = 4 * 60
MAX_DAYS_AHEAD = 60


def _admin_names_from_env():
    """ADMIN_NAMES env var: comma-separated names that may cancel any booking."""
    raw = os.environ.get("ADMIN_NAMES", "admin")
    return {n.strip().lower() for n in raw.split(",") if n.strip()}


ADMIN_NAMES = _admin_names_from_env()

ROOMS = [
    ("Cedar", 4),
    ("Birch", 6),
    ("Maple", 10),
    ("Oak", 20),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    capacity INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    date TEXT NOT NULL,          -- YYYY-MM-DD
    start TEXT NOT NULL,         -- HH:MM
    end TEXT NOT NULL,           -- HH:MM
    booker TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cancelled_at TEXT,            -- NULL = active, timestamp = cancelled
    UNIQUE (room_id, date, start)
);
CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date);
"""

# A cancelled booking keeps its row, so the old UNIQUE(room_id, date, start)
# constraint would block re-booking the freed slot. Replace it with a partial
# unique index that only covers active bookings.
ACTIVE_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_active_slot "
    "ON bookings(room_id, date, start) WHERE cancelled_at IS NULL"
)

# Columns added after v1.1; applied to existing databases by migrate().
MIGRATIONS = [
    ("bookings", "cancelled_at", "ALTER TABLE bookings ADD COLUMN cancelled_at TEXT"),
]


# ---------------------------------------------------------------- helpers
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _has_table_level_unique_slot(conn):
    """True if bookings still carries the old UNIQUE(room_id, date, start) constraint."""
    for idx in conn.execute("PRAGMA index_list(bookings)"):
        if idx["origin"] != "u":
            continue
        cols = [r["name"] for r in conn.execute("PRAGMA index_info(%s)" % idx["name"])]
        if cols == ["room_id", "date", "start"]:
            return True
    return False


def _rebuild_bookings_without_unique(conn):
    """SQLite cannot drop a table constraint: rebuild the table without UNIQUE.

    Cancelled rows keep their slot, so the table-level UNIQUE(room_id, date, start)
    would block re-booking a freed slot. The replacement is the partial unique
    index idx_bookings_active_slot (active rows only).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DROP TABLE IF EXISTS bookings_new")
        conn.execute(
            """CREATE TABLE bookings_new (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   room_id INTEGER NOT NULL REFERENCES rooms(id),
                   date TEXT NOT NULL,
                   start TEXT NOT NULL,
                   end TEXT NOT NULL,
                   booker TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   cancelled_at TEXT
               )"""
        )
        conn.execute(
            "INSERT INTO bookings_new (id, room_id, date, start, end, booker, created_at, cancelled_at) "
            "SELECT id, room_id, date, start, end, booker, created_at, cancelled_at FROM bookings"
        )
        conn.execute("DROP TABLE bookings")
        conn.execute("ALTER TABLE bookings_new RENAME TO bookings")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date)")
        conn.execute(ACTIVE_UNIQUE_INDEX)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def migrate(conn):
    """Bring an existing database up to date (safe to run on every start)."""
    for table, column, sql in MIGRATIONS:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if column not in cols:
            conn.execute(sql)
    # Old databases (v1/v1.1) still have the table-level UNIQUE constraint.
    if _has_table_level_unique_slot(conn):
        _rebuild_bookings_without_unique(conn)


def init_db():
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        migrate(conn)
        conn.execute(ACTIVE_UNIQUE_INDEX)
        for name, cap in ROOMS:
            conn.execute("INSERT OR IGNORE INTO rooms (name, capacity) VALUES (?, ?)", (name, cap))
    finally:
        conn.close()


def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        # never leak strptime internals ("day is out of range for month", ...)
        raise ValueError("invalid date (YYYY-MM-DD)")


def check_date_range(day):
    """Same rule for availability and booking: [today, today + MAX_DAYS_AHEAD]."""
    today = date.today()
    if day < today:
        raise ValueError("date must be between today and %d days ahead" % MAX_DAYS_AHEAD)
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        raise ValueError("date must be between today and %d days ahead" % MAX_DAYS_AHEAD)


def parse_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError("time must be HH:MM")
    h, m = int(value[:2]), int(value[3:])
    if h > 23 or m > 59:
        raise ValueError("invalid time")
    return h * 60 + m


def fmt(minutes):
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def slot_starts():
    """All valid slot start times in minutes from midnight."""
    return list(range(OPEN_HOUR * 60, CLOSE_HOUR * 60, SLOT_MINUTES))


def validate_booking(room_id, day, start, end, booker):
    """Return (start_min, end_min, booker) or raise ValueError with a message."""
    if not isinstance(booker, str) or not booker.strip():
        raise ValueError("booker name is required")
    booker = booker.strip()
    if len(booker) > 80:
        raise ValueError("booker name is too long")
    if isinstance(room_id, bool) or not isinstance(room_id, int):
        raise ValueError("room must be a room id (integer)")
    s, e = parse_time(start), parse_time(end)
    if s % SLOT_MINUTES or e % SLOT_MINUTES:
        raise ValueError("times must be on %d-minute boundaries" % SLOT_MINUTES)
    if s < OPEN_HOUR * 60 or e > CLOSE_HOUR * 60:
        raise ValueError("bookings must be within working hours %02d:00-%02d:00" % (OPEN_HOUR, CLOSE_HOUR))
    if e <= s:
        raise ValueError("end must be after start")
    if e - s > MAX_BOOKING_MINUTES:
        raise ValueError("max booking length is %d hours" % (MAX_BOOKING_MINUTES // 60))
    check_date_range(day)
    if day == date.today():
        now = datetime.now()
        if s < now.hour * 60 + now.minute:
            raise ValueError("cannot book a start time that has already passed today")
    return s, e, booker


def room_exists(conn, room_id):
    return conn.execute("SELECT 1 FROM rooms WHERE id = ?", (room_id,)).fetchone() is not None


def booking_dict(row):
    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "room": row["room_name"] if "room_name" in row.keys() else None,
        "date": row["date"],
        "start": row["start"],
        "end": row["end"],
        "booker": row["booker"],
        "created_at": row["created_at"] if "created_at" in row.keys() else None,
        "cancelled_at": row["cancelled_at"] if "cancelled_at" in row.keys() else None,
        "cancelled": bool(row["cancelled_at"]) if "cancelled_at" in row.keys() else False,
    }


SELECT_BOOKINGS = """
SELECT b.id, b.room_id, r.name AS room_name, b.date, b.start, b.end, b.booker,
       b.created_at, b.cancelled_at
FROM bookings b JOIN rooms r ON r.id = b.room_id
"""


# ---------------------------------------------------------------- core logic
def list_rooms():
    conn = connect()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name, capacity FROM rooms ORDER BY id")]
    finally:
        conn.close()


def list_bookings(day=None, room_id=None, booker=None, upcoming=False, include_cancelled=False):
    """Active bookings only, unless include_cancelled=True (cancelled rows are kept for stats)."""
    conn = connect()
    try:
        sql, args = SELECT_BOOKINGS + " WHERE 1=1", []
        if not include_cancelled:
            sql += " AND b.cancelled_at IS NULL"
        if day is not None:
            sql += " AND b.date = ?"
            args.append(day)
        if room_id is not None:
            sql += " AND b.room_id = ?"
            args.append(room_id)
        if booker is not None:
            sql += " AND lower(b.booker) = lower(?)"
            args.append(booker)
        if upcoming:
            sql += " AND b.date >= ?"
            args.append(date.today().isoformat())
        sql += " ORDER BY b.date, b.start, r.id"
        return [booking_dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def availability(day, room_id=None):
    """Return per-room slot lists for a date."""
    rooms = list_rooms()
    if room_id is not None:
        rooms = [r for r in rooms if r["id"] == room_id]
    booked = list_bookings(day, room_id)
    result = []
    for room in rooms:
        slots = []
        for s in slot_starts():
            e = s + SLOT_MINUTES
            hit = None
            for b in booked:
                if b["room_id"] != room["id"]:
                    continue
                bs, be = parse_time(b["start"]), parse_time(b["end"])
                if bs < e and s < be:
                    hit = b
                    break
            slots.append({
                "start": fmt(s),
                "end": fmt(e),
                "free": hit is None,
                "booking": hit,
            })
        result.append({"room_id": room["id"], "room": room["name"], "capacity": room["capacity"], "slots": slots})
    return {"date": day, "slot_minutes": SLOT_MINUTES, "rooms": result}


def create_booking(payload):
    """Create a booking atomically. Raises ValueError (400) or Conflict (409)."""
    if not isinstance(payload, dict):
        raise ValueError("JSON object expected")
    room_id = payload.get("room_id")
    if isinstance(room_id, str) and room_id.isdigit():
        room_id = int(room_id)
    day = parse_date(payload.get("date"))
    s, e, booker = validate_booking(room_id, day, payload.get("start"), payload.get("end"), payload.get("booker"))
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")   # serialise writers: atomic check + insert
        if not room_exists(conn, room_id):
            raise ValueError("unknown room")
        clash = conn.execute(
            "SELECT id FROM bookings WHERE room_id = ? AND date = ? AND start < ? AND end > ?"
            " AND cancelled_at IS NULL",
            (room_id, day.isoformat(), fmt(e), fmt(s)),
        ).fetchone()
        if clash:
            raise Conflict("that slot is already booked")
        try:
            cur = conn.execute(
                "INSERT INTO bookings (room_id, date, start, end, booker, created_at) VALUES (?,?,?,?,?,?)",
                (room_id, day.isoformat(), fmt(s), fmt(e), booker, datetime.now().isoformat(timespec="seconds")),
            )
        except sqlite3.IntegrityError:
            raise Conflict("that slot is already booked")
        conn.execute("COMMIT")
        row = conn.execute(SELECT_BOOKINGS + " WHERE b.id = ?", (cur.lastrowid,)).fetchone()
        return booking_dict(row)
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def cancel_booking(booking_id, booker):
    """Mark a booking cancelled if the name matches (or is an admin).

    The row is kept (cancelled_at set) so the dashboard can report cancellation
    rates; every availability/booking query filters cancelled_at IS NULL, so the
    slot becomes free again. Returns True if cancelled, None if not found.
    """
    if not isinstance(booker, str) or not booker.strip():
        raise ValueError("booker name is required to cancel")
    booker = booker.strip()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id, booker, cancelled_at FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return None  # not found
        if row["booker"].lower() != booker.lower() and booker.lower() not in ADMIN_NAMES:
            conn.execute("ROLLBACK")
            raise PermissionError("only the booker or an admin can cancel this booking")
        if row["cancelled_at"]:
            conn.execute("ROLLBACK")
            return None  # already cancelled -> treated as not found
        conn.execute("UPDATE bookings SET cancelled_at = ? WHERE id = ?",
                     (datetime.now().isoformat(timespec="seconds"), booking_id))
        conn.execute("COMMIT")
        return True
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


class Conflict(Exception):
    pass


# ---------------------------------------------------------------- dashboard stats
MAX_RANGE_DAYS = 366
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def parse_range(start_raw, end_raw):
    """Validate a dashboard date range. Returns (start_date, end_date), inclusive."""
    if not start_raw or not end_raw:
        raise ValueError("start and end dates are required (YYYY-MM-DD)")
    start, end = parse_date(start_raw), parse_date(end_raw)
    if start > end:
        raise ValueError("start date must be on or before the end date")
    span = (end - start).days + 1
    if span > MAX_RANGE_DAYS:
        raise ValueError("date range must be at most %d days" % MAX_RANGE_DAYS)
    return start, end


def available_hours(start, end):
    """Bookable hours in the range: 10h per weekday (Mon-Fri)."""
    days = (end - start).days + 1
    weekdays = sum(1 for i in range(days) if (start + timedelta(days=i)).weekday() < 5)
    return weekdays * (CLOSE_HOUR - OPEN_HOUR)


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def compute_stats(start, end):
    """Aggregate bookings created in [start, end] (inclusive) for the dashboard."""
    s_iso, e_iso = start.isoformat(), end.isoformat()
    conn = connect()
    try:
        rows = conn.execute(
            SELECT_BOOKINGS + " WHERE b.date BETWEEN ? AND ? ORDER BY b.date, b.start",
            (s_iso, e_iso),
        ).fetchall()
    finally:
        conn.close()

    rooms = list_rooms()
    per_room = {r["id"]: {"room_id": r["id"], "room": r["name"], "capacity": r["capacity"],
                          "bookings": 0, "cancelled": 0, "hours": 0.0} for r in rooms}
    by_dow = {name: 0 for name in DAY_NAMES}
    by_hour = {h: 0 for h in range(OPEN_HOUR, CLOSE_HOUR)}
    by_date = {}
    day = start
    while day <= end:
        by_date[day.isoformat()] = 0
        day += timedelta(days=1)

    total = cancelled = 0
    minutes = 0
    for row in rows:
        room = per_room.get(row["room_id"])
        if room is None:
            continue
        total += 1
        room["bookings"] += 1
        by_date[row["date"]] = by_date.get(row["date"], 0) + 1
        if row["cancelled_at"]:
            cancelled += 1
            room["cancelled"] += 1
            continue
        length = parse_time(row["end"]) - parse_time(row["start"])
        minutes += length
        room["hours"] += length / 60.0
        by_dow[DAY_NAMES[parse_date(row["date"]).weekday()]] += 1
        by_hour[parse_time(row["start"]) // 60] += 1

    avail = available_hours(start, end)
    room_rows = []
    for r in rooms:
        info = per_room[r["id"]]
        util = _pct(info["hours"], avail)
        if info["bookings"] == 0:
            suggestion = "unused in this range — consider merging or downsizing"
        elif util < 15:
            suggestion = "underused — consider merging or downsizing"
        elif util > 60:
            suggestion = "heavily used — consider a larger room"
        else:
            suggestion = "well used — keep as is"
        room_rows.append({
            "room_id": info["room_id"], "room": info["room"], "capacity": info["capacity"],
            "bookings": info["bookings"], "cancelled": info["cancelled"],
            "hours": round(info["hours"], 2),
            "cancellation_rate": _pct(info["cancelled"], info["bookings"]),
            "available_hours": avail, "utilisation": util, "suggestion": suggestion,
        })

    used = [r for r in room_rows if r["bookings"] > 0]
    busiest_dow = max(DAY_NAMES, key=lambda d: by_dow[d]) if total else None
    busiest_hour = max(by_hour, key=lambda h: by_hour[h]) if total else None
    busiest_date = max(by_date, key=lambda d: by_date[d]) if total else None
    most_used = max(used, key=lambda r: (r["hours"], r["bookings"])) if used else None
    least_used = min(room_rows, key=lambda r: (r["hours"], r["bookings"])) if room_rows else None

    if total == 0:
        summary = ("No bookings were created between %s and %s, so there is nothing to "
                   "analyse yet. Book some rooms (or widen the date range) and the "
                   "charts will fill in." % (s_iso, e_iso))
    else:
        parts = ["%d booking(s) were created between %s and %s, reserving %.1f hour(s) "
                 "of room time (%.1f%% of the %d available hours)."
                 % (total, s_iso, e_iso, minutes / 60.0, _pct(minutes / 60.0, avail), avail)]
        if most_used:
            parts.append("%s is the most used room (%.1f h, %.1f%% utilisation)."
                         % (most_used["room"], most_used["hours"], most_used["utilisation"]))
        if least_used:
            parts.append("%s is the least used (%.1f h, %.1f%%)."
                         % (least_used["room"], least_used["hours"], least_used["utilisation"]))
        if busiest_dow and by_dow[busiest_dow]:
            parts.append("%s is the busiest day of the week (%d booking(s))"
                         % (busiest_dow, by_dow[busiest_dow]))
            if busiest_date and by_date[busiest_date]:
                parts[-1] += ", and %s the busiest date (%d)." % (busiest_date, by_date[busiest_date])
            else:
                parts[-1] += "."
        if busiest_hour is not None and by_hour[busiest_hour]:
            parts.append("The busiest start time is %02d:00-%02d:00 (%d booking(s))."
                         % (busiest_hour, busiest_hour + 1, by_hour[busiest_hour]))
        parts.append("Overall cancellation rate is %.1f%% (%d of %d bookings)."
                     % (_pct(cancelled, total), cancelled, total))
        summary = " ".join(parts)

    return {
        "range": {"start": s_iso, "end": e_iso, "days": (end - start).days + 1,
                  "available_hours_per_room": avail},
        "totals": {
            "bookings": total,
            "cancelled": cancelled,
            "active": total - cancelled,
            "hours_reserved": round(minutes / 60.0, 2),
            "cancellation_rate": _pct(cancelled, total),
            "rooms_total": len(room_rows),
            "rooms_used": len(used),
            "rooms_unused": len(room_rows) - len(used),
        },
        "rooms": room_rows,
        "by_day_of_week": [{"day": d, "bookings": by_dow[d]} for d in DAY_NAMES],
        "by_date": [{"date": d, "bookings": by_date[d]} for d in sorted(by_date)],
        "by_hour": [{"hour": h, "label": "%02d:00" % h, "bookings": by_hour[h]}
                    for h in range(OPEN_HOUR, CLOSE_HOUR)],
        "busiest": {"day_of_week": busiest_dow, "date": busiest_date,
                    "hour": busiest_hour},
        "summary": summary,
    }


# ---------------------------------------------------------------- dashboard page
def _esc(value):
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _hbar_rows(items, unit=""):
    """items: list of (label, value, text). Horizontal CSS bars."""
    top = max([v for _, v, _ in items] + [1])
    out = ['<div class="hbars">']
    for label, value, text in items:
        width = 100.0 * value / top
        out.append('<div class="hrow"><span class="hlab">%s</span>'
                   '<span class="htrack"><span class="hfill" style="width:%.1f%%"></span></span>'
                   '<span class="hval">%s</span></div>' % (_esc(label), width, _esc(text)))
    out.append("</div>")
    return "".join(out)


def _svg_bars(items, title, unit="bookings"):
    """items: list of (label, value). Vertical SVG bar chart, no JS."""
    w, h, pad_l, pad_b, pad_t = 640, 200, 34, 34, 12
    n = max(len(items), 1)
    plot_w, plot_h = w - pad_l - 10, h - pad_b - pad_t
    top = max([v for _, v in items] + [1])
    bw = plot_w / n
    parts = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="%s">'
             % (w, h, _esc(title))]
    # y grid
    for frac in (0, 0.5, 1):
        y = pad_t + plot_h * (1 - frac)
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="grid"/>'
                     % (pad_l, y, w - 10, y))
        parts.append('<text x="%d" y="%.1f" class="axis" text-anchor="end">%d</text>'
                     % (pad_l - 4, y + 4, round(top * frac)))
    for i, (label, value) in enumerate(items):
        bh = plot_h * value / top
        x = pad_l + i * bw + bw * 0.15
        y = pad_t + plot_h - bh
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" class="bar">'
                     '<title>%s: %d %s</title></rect>'
                     % (x, y, bw * 0.7, bh, _esc(label), value, unit))
        if value:
            parts.append('<text x="%.1f" y="%.1f" class="val" text-anchor="middle">%d</text>'
                         % (x + bw * 0.35, y - 3, value))
        parts.append('<text x="%.1f" y="%d" class="axis" text-anchor="middle">%s</text>'
                     % (x + bw * 0.35, h - pad_b + 14, _esc(label)))
    parts.append("</svg>")
    return "".join(parts)


def render_dashboard(start, end, error=None):
    """Server-rendered manager dashboard: plain HTML/CSS/SVG, no JavaScript."""
    today = date.today()
    default_end = today
    default_start = today - timedelta(days=29)
    quick = []
    for days in (7, 30, 90):
        qs = "start=%s&end=%s" % ((today - timedelta(days=days - 1)).isoformat(), today.isoformat())
        quick.append('<a class="btn%s" href="/dashboard?%s">%d days</a>'
                     % (" active" if (end - start).days + 1 == days and end == today else "", qs, days))

    head = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Room usage dashboard</title>
<style>
  :root { --ink:#1d2733; --muted:#5b6b7c; --line:#e6ebf1; --accent:#1f6feb; --warn:#c94b4b; }
  * { box-sizing:border-box; }
  body { font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; margin:0; color:var(--ink); background:#f5f7fa; }
  header { background:#1f3a5f; color:#fff; padding:14px 20px; display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; }
  header h1 { margin:0; font-size:20px; }
  header p { margin:4px 0 0; font-size:13px; opacity:.85; }
  header a { color:#fff; font-size:13px; }
  main { padding:18px 20px 60px; max-width:1100px; margin:0 auto; }
  .card { background:#fff; border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,.08); padding:14px; margin-top:16px; }
  .card h2 { margin:0 0 10px; font-size:15px; }
  .card p.note { margin:0 0 10px; font-size:12px; color:var(--muted); }
  form.range { display:flex; flex-wrap:wrap; gap:12px; align-items:flex-end; }
  form.range label { display:flex; flex-direction:column; font-size:12px; font-weight:600; gap:4px; }
  form.range input { font:inherit; padding:7px 9px; border:1px solid #c6cfda; border-radius:6px; }
  .btn, button { font:inherit; cursor:pointer; border-radius:6px; border:1px solid #c6cfda; background:#fff; padding:7px 12px; text-decoration:none; color:var(--ink); }
  .btn.active { background:#1f6feb; border-color:#1f6feb; color:#fff; font-weight:600; }
  button.primary { background:#1f6feb; border-color:#1f6feb; color:#fff; font-weight:600; }
  .quick { display:flex; gap:8px; flex-wrap:wrap; }
  .err { background:#fdeaea; border:1px solid var(--warn); color:#7a1f1f; padding:10px 12px; border-radius:8px; margin-top:12px; font-size:14px; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-top:16px; }
  .kpi { background:#fff; border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,.08); padding:14px; }
  .kpi .k { font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
  .kpi .v { font-size:26px; font-weight:700; margin-top:4px; }
  .kpi .s { font-size:12px; color:var(--muted); margin-top:2px; }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th, td { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; }
  th { background:#f0f4f9; font-size:12px; }
  td.num, th.num { text-align:right; }
  .hbars { display:flex; flex-direction:column; gap:6px; }
  .hrow { display:grid; grid-template-columns:110px 1fr 90px; gap:8px; align-items:center; font-size:13px; }
  .htrack { background:#eef2f7; border-radius:4px; height:14px; display:block; overflow:hidden; }
  .hfill { display:block; height:100%; background:#1f6feb; border-radius:4px; }
  .hval { color:var(--muted); font-size:12px; text-align:right; }
  svg.chart { width:100%; height:auto; display:block; }
  svg .bar { fill:#1f6feb; }
  svg .grid { stroke:#e6ebf1; stroke-width:1; }
  svg .axis { fill:#5b6b7c; font-size:11px; }
  svg .val { fill:#1d2733; font-size:10px; }
  .summary { font-size:14px; line-height:1.55; }
  .empty { background:#fff; border:1px dashed #c6cfda; border-radius:10px; padding:18px; margin-top:16px; font-size:14px; color:var(--muted); }
  .tag { font-size:12px; padding:2px 7px; border-radius:10px; background:#eef2f7; }
  .tag.hot { background:#fdeaea; color:#7a1f1f; }
  .tag.cold { background:#e8f7ec; color:#1f5c33; }
</style>
</head>
<body>
<header>
  <div>
    <h1>Room usage dashboard</h1>
    <p>Manager view of how the meeting rooms are used. Data comes from the booking records.</p>
  </div>
  <a href="/">&larr; Back to booking page</a>
</header>
<main>
"""

    form = """
  <div class="card">
    <h2>Date range</h2>
    <form class="range" method="get" action="/dashboard">
      <label>From <input type="date" name="start" value="%s" required></label>
      <label>To <input type="date" name="end" value="%s" required></label>
      <button type="submit" class="primary">Show</button>
      <span class="quick">%s</span>
    </form>
    <p class="note">Inclusive range, at most %d days. Default: the last 30 days. Quick buttons show the last 7 / 30 / 90 days up to today.</p>
  </div>
""" % (start.isoformat(), end.isoformat(), "".join(quick), MAX_RANGE_DAYS)

    if error:
        return head + form + '<div class="err">%s</div></main></body></html>' % _esc(error)

    stats = compute_stats(start, end)
    t = stats["totals"]
    rng = stats["range"]

    kpis = """
  <div class="kpis">
    <div class="kpi"><div class="k">Total bookings</div><div class="v">%d</div><div class="s">%d active, %d cancelled</div></div>
    <div class="kpi"><div class="k">Total time reserved</div><div class="v">%.1f h</div><div class="s">cancelled bookings excluded</div></div>
    <div class="kpi"><div class="k">Cancellation rate</div><div class="v">%.1f%%</div><div class="s">%d of %d bookings</div></div>
    <div class="kpi"><div class="k">Rooms used</div><div class="v">%d / %d</div><div class="s">%d unused in this range</div></div>
  </div>
""" % (t["bookings"], t["active"], t["cancelled"], t["hours_reserved"],
       t["cancellation_rate"], t["cancelled"], t["bookings"],
       t["rooms_used"], t["rooms_total"], t["rooms_unused"])

    if t["bookings"] == 0:
        empty = """
  <div class="empty">
    <strong>No bookings in this range.</strong>
    <p>There are no booking records between %s and %s, so there is nothing to chart yet.
    Book a room on the <a href="/">booking page</a>, or pick a wider date range above.</p>
  </div>
""" % (rng["start"], rng["end"])
        return head + form + kpis + empty + "</main></body></html>"

    # per-room table + bars
    room_rows = []
    for r in stats["rooms"]:
        cls = "hot" if r["utilisation"] > 60 else ("cold" if r["utilisation"] < 15 else "")
        room_rows.append(
            "<tr><td>%s</td><td class=\"num\">%d</td><td class=\"num\">%d</td>"
            "<td class=\"num\">%.1f h</td><td class=\"num\">%.1f%%</td>"
            "<td><span class=\"tag %s\">%s</span></td></tr>"
            % (_esc(r["room"]), r["bookings"], r["cancelled"], r["hours"],
               r["utilisation"], cls, _esc(r["suggestion"])))
    room_table = """
  <div class="card">
    <h2>Bookings and reserved time per room</h2>
    <p class="note">Utilisation = hours reserved (non-cancelled) / available hours in the range
      (%d h per weekday per room). Suggestion: under 15%% = underused, over 60%% = heavily used.</p>
    <table>
      <thead><tr><th>Room</th><th class="num">Bookings</th><th class="num">Cancelled</th>
        <th class="num">Hours reserved</th><th class="num">Utilisation</th><th>Allocation suggestion</th></tr></thead>
      <tbody>%s</tbody>
    </table>
    <h2 style="margin-top:16px">Bookings per room</h2>
    %s
    <h2 style="margin-top:16px">Hours reserved per room</h2>
    %s
  </div>
""" % (rng["available_hours_per_room"], "".join(room_rows),
       _hbar_rows([(r["room"], r["bookings"], "%d" % r["bookings"]) for r in stats["rooms"]]),
       _hbar_rows([(r["room"], r["hours"], "%.1f h" % r["hours"]) for r in stats["rooms"]]))

    dow = _svg_bars([(d["day"][:3], d["bookings"]) for d in stats["by_day_of_week"]],
                    "Bookings by day of week")
    dates = stats["by_date"]
    if len(dates) > 62:   # keep the chart readable for long ranges
        step = (len(dates) + 61) // 62
        dates = dates[::step]
    date_chart = _svg_bars([(d["date"][5:], d["bookings"]) for d in dates],
                           "Bookings per calendar date")
    hours = _svg_bars([(h["label"][:2], h["bookings"]) for h in stats["by_hour"]],
                      "Bookings by hour of day")
    charts = """
  <div class="card">
    <h2>Busiest days of the week</h2>
    <p class="note">Number of non-cancelled bookings starting on each weekday.</p>
    %s
  </div>
  <div class="card">
    <h2>Bookings per calendar date</h2>
    <p class="note">Non-cancelled bookings per day in the selected range%s.</p>
    %s
  </div>
  <div class="card">
    <h2>Busiest times of day</h2>
    <p class="note">Non-cancelled bookings by start hour (working hours 08:00&ndash;18:00).</p>
    %s
  </div>
""" % (dow, " (sampled for readability)" if len(dates) < len(stats["by_date"]) else "", date_chart, hours)

    cancel_rows = "".join(
        "<tr><td>%s</td><td class=\"num\">%d</td><td class=\"num\">%d</td><td class=\"num\">%.1f%%</td></tr>"
        % (_esc(r["room"]), r["cancelled"], r["bookings"], r["cancellation_rate"])
        for r in stats["rooms"])
    cancel = """
  <div class="card">
    <h2>Cancellations per room</h2>
    <p class="note">Cancellation rate = cancelled bookings / all bookings created in the range.</p>
    <table>
      <thead><tr><th>Room</th><th class="num">Cancelled</th><th class="num">Total bookings</th>
        <th class="num">Cancellation rate</th></tr></thead>
      <tbody>%s
        <tr><th>All rooms</th><th class="num">%d</th><th class="num">%d</th><th class="num">%.1f%%</th></tr>
      </tbody>
    </table>
  </div>
""" % (cancel_rows, t["cancelled"], t["bookings"], t["cancellation_rate"])

    summary = """
  <div class="card">
    <h2>What this suggests</h2>
    <p class="summary">%s</p>
  </div>
""" % _esc(stats["summary"])

    return head + form + kpis + summary + room_table + charts + cancel + "</main></body></html>"


# ---------------------------------------------------------------- HTTP layer
def parse_room_param(room):
    """Resolve a ?room= query value (id or name) to a room id. Raises ValueError."""
    if room in (None, "", "all"):
        return None
    if room.isdigit():
        room_id = int(room)
        if not any(r["id"] == room_id for r in list_rooms()):
            raise ValueError("unknown room")
        return room_id
    match = [r for r in list_rooms() if r["name"].lower() == room.lower()]
    if not match:
        raise ValueError("unknown room")
    return match[0]["id"]


class Handler(BaseHTTPRequestHandler):
    server_version = "RoomBooker/1.1"

    def log_message(self, fmt_, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt_ % args))

    # -- helpers
    def send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_html(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("invalid JSON body")

    def error(self, status, message):
        self.send_json(status, {"error": message})

    def method_not_allowed(self):
        self.send_json(405, {"error": "method %s is not allowed on %s" % (self.command, urlparse(self.path).path)})

    # -- routes
    def do_GET(self):
        parsed = urlparse(self.path)
        path, qs = parsed.path.rstrip("/") or "/", parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                return self.send_html(200, INDEX_HTML)
            if path == "/dashboard":
                start_raw = (qs.get("start") or [None])[0]
                end_raw = (qs.get("end") or [None])[0]
                if not start_raw and not end_raw:
                    end = date.today()
                    start = end - timedelta(days=29)
                else:
                    start, end = parse_range(start_raw, end_raw)
                return self.send_html(200, render_dashboard(start, end))
            if path == "/api/stats":
                start_raw = (qs.get("start") or [None])[0]
                end_raw = (qs.get("end") or [None])[0]
                if not start_raw and not end_raw:
                    end = date.today()
                    start = end - timedelta(days=29)
                else:
                    start, end = parse_range(start_raw, end_raw)
                return self.send_json(200, compute_stats(start, end))
            if path == "/api/rooms":
                return self.send_json(200, {"rooms": list_rooms()})
            if path == "/api/availability":
                day = parse_date((qs.get("date") or [""])[0])
                check_date_range(day)
                room_id = parse_room_param((qs.get("room") or [None])[0])
                return self.send_json(200, availability(day.isoformat(), room_id))
            if path == "/api/bookings":
                day = (qs.get("date") or [None])[0]
                if day:
                    day = parse_date(day).isoformat()
                room_id = parse_room_param((qs.get("room") or [None])[0])
                booker = (qs.get("booker") or [None])[0]
                if booker is not None:
                    booker = booker.strip()
                    if not booker:
                        raise ValueError("booker filter must not be empty")
                upcoming = (qs.get("upcoming") or ["0"])[0] not in ("", "0", "false", "no")
                return self.send_json(200, {"bookings": list_bookings(day, room_id, booker, upcoming)})
            return self.error(404, "not found")
        except ValueError as exc:
            return self.error(400, str(exc))
        except Exception:
            return self.error(500, "internal server error")

    def do_HEAD(self):
        return self.do_GET()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path != "/api/bookings":
            return self.error(404, "not found")
        try:
            payload = self.read_json()
            booking = create_booking(payload)
            return self.send_json(201, {"booking": booking})
        except Conflict as exc:
            return self.error(409, str(exc))
        except ValueError as exc:
            return self.error(400, str(exc))
        except Exception:
            return self.error(500, "internal server error")

    def do_DELETE(self):
        path = urlparse(self.path).path.rstrip("/")
        m = re.fullmatch(r"/api/bookings/(\d+)", path)
        if not m:
            return self.error(404, "not found")
        booking_id = int(m.group(1))
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSON object expected")
            booker = payload.get("booker")
            result = cancel_booking(booking_id, booker)
            if result is None:
                return self.error(404, "booking not found")
            return self.send_json(200, {"cancelled": booking_id})
        except PermissionError as exc:
            return self.error(403, str(exc))
        except ValueError as exc:
            return self.error(400, str(exc))
        except Exception:
            return self.error(500, "internal server error")

    def do_PUT(self):
        return self.method_not_allowed()

    def do_PATCH(self):
        return self.method_not_allowed()

    def do_OPTIONS(self):
        return self.method_not_allowed()


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meeting Room Booking</title>
<style>
  :root { --free:#e8f7ec; --free-b:#3a9d5d; --busy:#fdeaea; --busy-b:#c94b4b; --ink:#1d2733; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; margin:0; color:var(--ink); background:#f5f7fa; }
  header { background:#1f3a5f; color:#fff; padding:14px 20px; }
  header h1 { margin:0; font-size:20px; }
  header p { margin:4px 0 0; font-size:13px; opacity:.85; }
  main { padding:18px 20px 60px; max-width:1200px; margin:0 auto; }
  .bar { display:flex; flex-wrap:wrap; gap:12px; align-items:flex-end; background:#fff; padding:14px; border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,.08); }
  .bar label { display:flex; flex-direction:column; font-size:12px; font-weight:600; gap:4px; }
  .bar input, .bar select { font:inherit; padding:7px 9px; border:1px solid #c6cfda; border-radius:6px; background:#fff; }
  button { font:inherit; cursor:pointer; border-radius:6px; border:1px solid #c6cfda; background:#fff; padding:7px 12px; }
  button.primary { background:#1f6feb; border-color:#1f6feb; color:#fff; font-weight:600; }
  button.danger { background:#fff; border-color:#c94b4b; color:#c94b4b; padding:3px 8px; font-size:12px; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .msg { margin:12px 0; padding:10px 12px; border-radius:8px; font-size:14px; display:none; }
  .msg.ok { display:block; background:#e8f7ec; border:1px solid var(--free-b); }
  .msg.err { display:block; background:#fdeaea; border:1px solid var(--busy-b); }
  .grid-wrap { overflow-x:auto; margin-top:16px; background:#fff; border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,.08); }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th, td { border-bottom:1px solid #e6ebf1; padding:6px 8px; text-align:left; vertical-align:top; }
  th { background:#f0f4f9; position:sticky; top:0; font-size:12px; }
  td.slot { min-width:150px; }
  .free { background:var(--free); border-left:3px solid var(--free-b); cursor:pointer; }
  .free:hover { background:#d5f0dd; }
  .busy { background:var(--busy); border-left:3px solid var(--busy-b); }
  .who { font-weight:600; }
  .mine { outline:2px solid #1f6feb; outline-offset:-2px; }
  .hint { font-size:12px; color:#5b6b7c; margin-top:10px; }
  .legend { display:flex; gap:16px; font-size:12px; margin-top:10px; }
  .legend span::before { content:""; display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:5px; vertical-align:-2px; }
  .legend .l-free::before { background:var(--free); border:1px solid var(--free-b); }
  .legend .l-busy::before { background:var(--busy); border:1px solid var(--busy-b); }
  .panel { margin-top:20px; background:#fff; border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,.08); padding:14px; }
  .panel h2 { margin:0 0 8px; font-size:15px; }
  .panel table { font-size:13px; }
  .panel td, .panel th { padding:5px 8px; }
  .empty { color:#5b6b7c; font-size:13px; }
  dialog { border:none; border-radius:12px; padding:0; width:min(440px, 92vw); box-shadow:0 10px 40px rgba(0,0,0,.25); }
  dialog form { padding:18px; display:flex; flex-direction:column; gap:12px; }
  dialog h2 { margin:0; font-size:17px; }
  dialog label { display:flex; flex-direction:column; font-size:12px; font-weight:600; gap:4px; }
  dialog input, dialog select { font:inherit; padding:8px; border:1px solid #c6cfda; border-radius:6px; }
  .row { display:flex; gap:10px; }
  .row > * { flex:1; }
  .actions { display:flex; justify-content:flex-end; gap:8px; margin-top:4px; }
  .dlgmsg { font-size:13px; padding:8px 10px; border-radius:6px; display:none; }
  .dlgmsg.err { display:block; background:#fdeaea; border:1px solid var(--busy-b); }
  .dlgmsg.ok { display:block; background:#e8f7ec; border:1px solid var(--free-b); }
</style>
</head>
<body>
<header>
  <h1>Meeting Room Booking</h1>
  <p>Pick a date, click a free slot to book it, and cancel your own bookings from the grid or the "My bookings" list.
     Managers: <a href="/dashboard" style="color:#fff">open the usage dashboard &rarr;</a></p>
</header>
<main>
  <div class="bar">
    <label>Date <input type="date" id="date"></label>
    <label>Room <select id="room"><option value="all">All rooms</option></select></label>
    <label>Your name <input id="me" placeholder="e.g. Alex" autocomplete="off"></label>
    <button type="button" id="prev" title="Previous day">&#8592; Prev</button>
    <button type="button" id="today">Today</button>
    <button type="button" id="next" title="Next day">Next &#8594;</button>
    <button type="button" id="refresh">Refresh</button>
  </div>
  <div class="msg" id="msg"></div>
  <div class="legend"><span class="l-free">Free (click to book)</span><span class="l-busy">Booked</span></div>
  <div class="grid-wrap"><table id="grid"></table></div>
  <p class="hint">Working hours 08:00&ndash;18:00, 30-minute slots, max 4 hours per booking, from today up to 60 days ahead.
     Only the person who booked (or an admin) can cancel.</p>

  <div class="panel">
    <h2>My bookings</h2>
    <div id="mineInfo" class="empty">Enter your name above to see your upcoming bookings.</div>
    <table id="mine"></table>
  </div>
</main>

<dialog id="dlg">
  <form id="bookForm">
    <h2>Book a room</h2>
    <div id="dlgInfo" class="hint"></div>
    <label>Your name <input id="dlgName" required maxlength="80" autocomplete="off"></label>
    <div class="row">
      <label>Start <select id="dlgStart"></select></label>
      <label>End <select id="dlgEnd"></select></label>
    </div>
    <div id="dlgMsg" class="dlgmsg"></div>
    <div class="actions">
      <button type="button" id="dlgCancel">Cancel</button>
      <button type="submit" class="primary" id="dlgOk">Book</button>
    </div>
  </form>
</dialog>

<script>
const $ = (id) => document.getElementById(id);
const SLOT = 30, OPEN = 8 * 60, CLOSE = 18 * 60, MAXLEN = 240, MAXDAYS = 60;
let state = { date: null, rooms: [], data: null, pending: null };

function isoDate(d) { return d.toISOString().slice(0, 10); }
function today() { const d = new Date(); return isoDate(new Date(d.getTime() - d.getTimezoneOffset() * 60000)); }
function maxDate() { return shiftDate(today(), MAXDAYS); }
function shiftDate(iso, days) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return isoDate(new Date(d.getTime() - d.getTimezoneOffset() * 60000));
}
function clampDate(iso) {
  if (!iso) return today();
  if (iso < today()) return today();
  if (iso > maxDate()) return maxDate();
  return iso;
}
function toMin(t) { return Number(t.slice(0, 2)) * 60 + Number(t.slice(3)); }
function toTime(m) { return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0"); }
function showMsg(text, ok) {
  const el = $("msg");
  el.textContent = text;
  el.className = "msg " + (ok ? "ok" : "err");
  if (ok) setTimeout(() => { if (el.textContent === text) el.className = "msg"; }, 4000);
}
function dlgMsg(text, ok) {
  const el = $("dlgMsg");
  el.textContent = text || "";
  el.className = "dlgmsg" + (text ? (ok ? " ok" : " err") : "");
}
function myName() { return $("me").value.trim(); }
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

async function api(path, opts) {
  const res = await fetch(path, opts);
  let body = {};
  try { body = await res.json(); } catch (e) {}
  if (!res.ok) throw new Error(body.error || ("HTTP " + res.status));
  return body;
}

async function loadRooms() {
  const { rooms } = await api("/api/rooms");
  state.rooms = rooms;
  const sel = $("room");
  sel.innerHTML = '<option value="all">All rooms</option>' +
    rooms.map(r => `<option value="${r.id}">${esc(r.name)} (${r.capacity})</option>`).join("");
}

async function loadGrid() {
  const room = $("room").value;
  const q = `/api/availability?date=${state.date}` + (room !== "all" ? `&room=${room}` : "");
  state.data = await api(q);
  render();
}

function render() {
  const data = state.data;
  const table = $("grid");
  if (!data || !data.rooms.length) { table.innerHTML = "<tr><td>No rooms.</td></tr>"; return; }
  const slotCount = data.rooms[0].slots.length;
  let html = "<thead><tr><th>Time</th>" +
    data.rooms.map(r => `<th>${esc(r.name)}<br><span style="font-weight:400">cap ${r.capacity}</span></th>`).join("") +
    "</tr></thead><tbody>";
  for (let i = 0; i < slotCount; i++) {
    const s = data.rooms[0].slots[i];
    html += `<tr><th>${s.start}&ndash;${s.end}</th>`;
    for (const room of data.rooms) {
      const slot = room.slots[i];
      if (slot.free) {
        html += `<td class="slot free" data-room="${room.id}" data-start="${slot.start}" data-end="${slot.end}">Free</td>`;
      } else {
        const b = slot.booking;
        const mine = myName() && b.booker.toLowerCase() === myName().toLowerCase();
        const isStart = b.start === slot.start;
        html += `<td class="slot busy${mine ? " mine" : ""}">` +
          (isStart ? `<div class="who">${esc(b.booker)}</div><div>${b.start}&ndash;${b.end}</div>` : `<div style="opacity:.6">${b.start}&ndash;${b.end}</div>`) +
          (mine ? `<button type="button" class="danger" data-cancel="${b.id}">Cancel</button>` : "") +
          `</td>`;
      }
    }
    html += "</tr>";
  }
  table.innerHTML = html + "</tbody>";
}

async function cancelBooking(id) {
  const name = myName();
  if (!name) { showMsg("Enter your name first so we can verify the cancellation.", false); $("me").focus(); return; }
  if (!confirm(`Cancel booking #${id}?`)) return;
  try {
    await api(`/api/bookings/${id}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ booker: name }) });
    showMsg(`Booking #${id} cancelled — the slot is free again.`, true);
    await loadGrid();
    await loadMine();
  } catch (e) { showMsg("Cancel failed: " + e.message, false); }
}

async function loadMine() {
  const name = myName();
  const table = $("mine"), info = $("mineInfo");
  if (!name) {
    table.innerHTML = "";
    info.textContent = "Enter your name above to see your upcoming bookings.";
    info.className = "empty";
    return;
  }
  let bookings = [];
  try {
    const res = await api(`/api/bookings?booker=${encodeURIComponent(name)}&upcoming=1`);
    bookings = res.bookings;
  } catch (e) {
    info.textContent = "Could not load your bookings: " + e.message;
    info.className = "empty";
    table.innerHTML = "";
    return;
  }
  if (!bookings.length) {
    table.innerHTML = "";
    info.textContent = `No upcoming bookings for ${name}.`;
    info.className = "empty";
    return;
  }
  info.textContent = `${bookings.length} upcoming booking(s) for ${name}:`;
  info.className = "empty";
  table.innerHTML = "<thead><tr><th>Date</th><th>Time</th><th>Room</th><th></th></tr></thead><tbody>" +
    bookings.map(b => `<tr><td>${b.date}</td><td>${b.start}&ndash;${b.end}</td><td>${esc(b.room)}</td>` +
      `<td><button type="button" class="danger" data-cancel="${b.id}">Cancel</button></td></tr>`).join("") +
    "</tbody>";
}

$("grid").addEventListener("click", (ev) => {
  const cancelBtn = ev.target.closest("[data-cancel]");
  if (cancelBtn) { cancelBooking(cancelBtn.dataset.cancel); return; }
  const cell = ev.target.closest("td.free");
  if (cell) openDialog(Number(cell.dataset.room), cell.dataset.start);
});

$("mine").addEventListener("click", (ev) => {
  const cancelBtn = ev.target.closest("[data-cancel]");
  if (cancelBtn) cancelBooking(cancelBtn.dataset.cancel);
});

function bookedRanges(roomId) {
  const room = state.data && state.data.rooms.find(r => r.room_id === roomId);
  const ranges = [];
  if (!room) return ranges;
  for (const slot of room.slots) {
    if (slot.free) continue;
    const b = slot.booking;
    if (!ranges.some(r => r.id === b.id)) ranges.push({ id: b.id, s: toMin(b.start), e: toMin(b.end) });
  }
  return ranges;
}

function overlaps(ranges, s, e) { return ranges.some(r => r.s < e && s < r.e); }

function fillStarts(roomId) {
  const ranges = bookedRanges(roomId);
  const sel = $("dlgStart");
  sel.innerHTML = "";
  for (let m = OPEN; m < CLOSE; m += SLOT) {
    const opt = document.createElement("option");
    opt.value = toTime(m);
    opt.textContent = toTime(m);
    if (overlaps(ranges, m, m + SLOT)) { opt.disabled = true; opt.textContent += " (booked)"; }
    sel.appendChild(opt);
  }
  return ranges;
}

function fillEnds(roomId, startMin) {
  const ranges = bookedRanges(roomId);
  const sel = $("dlgEnd");
  sel.innerHTML = "";
  const last = Math.min(startMin + MAXLEN, CLOSE);
  let firstFree = null;
  for (let m = startMin + SLOT; m <= last; m += SLOT) {
    const opt = document.createElement("option");
    opt.value = toTime(m);
    opt.textContent = toTime(m);
    if (overlaps(ranges, startMin, m)) { opt.disabled = true; opt.textContent += " (booked)"; }
    else if (firstFree === null) firstFree = toTime(m);
    sel.appendChild(opt);
  }
  if (firstFree) sel.value = firstFree;
  return firstFree;
}

function openDialog(roomId, start) {
  const room = state.rooms.find(r => r.id === roomId);
  state.pending = { roomId };
  $("dlgInfo").textContent = `${room.name} (cap ${room.capacity}) on ${state.date}`;
  $("dlgName").value = myName();
  dlgMsg("");
  fillStarts(roomId);
  $("dlgStart").value = start;
  const firstFree = fillEnds(roomId, toMin(start));
  if (!firstFree) dlgMsg("That start time is already booked — pick another start time.", false);
  $("dlg").showModal();
}

$("dlgStart").addEventListener("change", () => {
  const firstFree = fillEnds(state.pending.roomId, toMin($("dlgStart").value));
  if (!firstFree) dlgMsg("That start time is already booked — pick another start time.", false);
  else dlgMsg("");
});

$("dlgEnd").addEventListener("change", () => dlgMsg(""));

$("dlgCancel").addEventListener("click", () => $("dlg").close());

$("bookForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const name = $("dlgName").value.trim();
  if (!name) { dlgMsg("Please enter your name.", false); return; }
  const start = $("dlgStart").value, end = $("dlgEnd").value;
  if (!start || !end) { dlgMsg("Pick a start and end time.", false); return; }
  if (toMin(end) <= toMin(start)) { dlgMsg("End time must be after the start time.", false); return; }
  if (toMin(end) - toMin(start) > MAXLEN) { dlgMsg("A booking can be at most 4 hours.", false); return; }
  if (overlaps(bookedRanges(state.pending.roomId), toMin(start), toMin(end))) {
    dlgMsg("That time range overlaps an existing booking — pick another end time.", false);
    return;
  }
  $("me").value = name;
  try {
    const res = await api("/api/bookings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ room_id: state.pending.roomId, date: state.date, start: start, end: end, booker: name }),
    });
    $("dlg").close();
    showMsg(`Booked ${res.booking.room} on ${res.booking.date} ${res.booking.start}–${res.booking.end}.`, true);
    await loadGrid();
    await loadMine();
  } catch (e) { dlgMsg("Booking failed: " + e.message, false); }
});

function goTo(iso) {
  state.date = clampDate(iso);
  $("date").value = state.date;
  loadGrid().catch(e => showMsg(e.message, false));
}

$("date").addEventListener("change", () => goTo($("date").value));
$("room").addEventListener("change", () => loadGrid().catch(e => showMsg(e.message, false)));
$("me").addEventListener("input", () => { if (state.data) render(); });
$("me").addEventListener("change", () => loadMine());
$("prev").addEventListener("click", () => goTo(shiftDate(state.date, -1)));
$("next").addEventListener("click", () => goTo(shiftDate(state.date, 1)));
$("today").addEventListener("click", () => goTo(today()));
$("refresh").addEventListener("click", () => { loadGrid().catch(e => showMsg(e.message, false)); loadMine(); });

(async function init() {
  state.date = today();
  $("date").value = state.date;
  $("date").min = today();
  $("date").max = maxDate();
  try { await loadRooms(); await loadGrid(); await loadMine(); } catch (e) { showMsg("Could not load: " + e.message, false); }
})();
</script>
</body>
</html>
"""


def make_server(host=HOST, port=PORT):
    return ThreadingHTTPServer((host, port), Handler)


def main():
    init_db()
    server = make_server()
    print("Meeting room booking system running at http://%s:%d/" % (HOST, PORT))
    print("Database: %s" % DB_PATH)
    print("Admin names (may cancel any booking): %s" % ", ".join(sorted(ADMIN_NAMES)))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
