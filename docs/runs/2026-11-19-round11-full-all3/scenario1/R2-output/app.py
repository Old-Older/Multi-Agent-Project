#!/usr/bin/env python3
"""Meeting Room Booking - a small, dependency-free web app.

Standard library only: http.server + sqlite3. No pip installs needed.

Run:  python3 app.py            (then open http://localhost:8000)
      PORT=9000 python3 app.py  (different port)
      ADMIN_KEY=secret python3 app.py

Data is stored in bookings.db (SQLite) next to this file.
"""

import csv
import io
import json
import os
import re
import sqlite3
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------
# Configuration (defaults agreed with the team)
# --------------------------------------------------------------------------
ROOMS = [
    ("Aspen", 4),
    ("Birch", 6),
    ("Cedar", 8),
    ("Dogwood", 10),
    ("Elm", 20),
]
DAY_START = 8 * 60          # 08:00 in minutes
DAY_END = 18 * 60           # 18:00 in minutes
SLOT_MINUTES = 30
WEEKDAYS = {0, 1, 2, 3, 4}  # Mon-Fri (date.weekday())
ADMIN_KEY = os.environ.get("ADMIN_KEY", "admin")
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookings.db"))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

SLOTS = list(range(DAY_START, DAY_END, SLOT_MINUTES))  # start minutes of each slot
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_TITLE = 200             # longest allowed purpose/title
MAX_NAME = 100              # longest allowed booker name
MAX_RANGE_DAYS = 366        # longest dashboard range (inclusive)
HEAVY_PCT = 70.0            # utilisation above this = heavily used
UNDER_PCT = 25.0            # utilisation below this = underused
MAX_REC_ROOMS = 3           # most underused rooms named in the recommendation
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS bookings (
                   id         INTEGER PRIMARY KEY AUTOINCREMENT,
                   room       TEXT    NOT NULL,
                   day        TEXT    NOT NULL,   -- YYYY-MM-DD
                   start_min  INTEGER NOT NULL,   -- minutes from midnight
                   end_min    INTEGER NOT NULL,
                   booker     TEXT    NOT NULL,   -- name
                   email      TEXT    NOT NULL,
                   title      TEXT    NOT NULL DEFAULT '',
                   created_at TEXT    NOT NULL
               )"""
        )
        # Index used by the conflict check.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_room_day ON bookings(room, day)")
        migrate_db(conn)


def migrate_db(conn):
    """Add the soft-delete columns to an existing bookings.db (idempotent).

    Cancelled bookings are kept as records (cancelled_at / cancelled_by) so the
    dashboard can report cancellation counts and rates. Older databases created
    before this feature simply lack the columns, so we ALTER TABLE ADD COLUMN
    for each missing one. Existing rows get NULL = still active.
    """
    have = {r[1] for r in conn.execute("PRAGMA table_info(bookings)").fetchall()}
    added = []
    for col, decl in (("cancelled_at", "TEXT"), ("cancelled_by", "TEXT")):
        if col not in have:
            conn.execute("ALTER TABLE bookings ADD COLUMN %s %s" % (col, decl))
            added.append(col)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_day ON bookings(day)")
    return added


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def hhmm(minutes):
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def parse_hhmm(text):
    """'09:30' -> 570. Raises ValueError on bad input."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(text or ""))
    if not m:
        raise ValueError("Time must look like HH:MM (e.g. 09:30).")
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        raise ValueError("Time out of range: %s" % text)
    return h * 60 + mi


def parse_day(text):
    try:
        return datetime.strptime(str(text).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValueError("Date must look like YYYY-MM-DD (e.g. 2025-06-02).")


def room_names():
    return [r[0] for r in ROOMS]


def room_capacity(name):
    for r, cap in ROOMS:
        if r.lower() == str(name).strip().lower():
            return cap
    return None


def canonical_room(name):
    for r, _ in ROOMS:
        if r.lower() == str(name).strip().lower():
            return r
    return None


def validate_booking(room, day, start, end, booker, email):
    """Return (clean_dict, error_message)."""
    room = canonical_room(room)
    if not room:
        return None, "Unknown room. Choose one of: %s." % ", ".join(room_names())
    try:
        d = parse_day(day)
    except ValueError as e:
        return None, str(e)
    if d.weekday() not in WEEKDAYS:
        return None, "Rooms can only be booked Monday to Friday."
    if d < date.today():
        return None, "That date is in the past. Pick today or a later date."
    try:
        s = parse_hhmm(start)
        e = parse_hhmm(end)
    except ValueError as exc:
        return None, str(exc)
    if s % SLOT_MINUTES or e % SLOT_MINUTES:
        return None, "Times must be on %d-minute boundaries (e.g. 09:00, 09:30)." % SLOT_MINUTES
    if s < DAY_START or e > DAY_END:
        return None, "Bookings must be within %s-%s." % (hhmm(DAY_START), hhmm(DAY_END))
    if e <= s:
        return None, "End time must be after start time."
    booker = (booker or "").strip()
    email = (email or "").strip()
    if not booker:
        return None, "Your name is required."
    if len(booker) > MAX_NAME:
        return None, "Your name is too long (max %d characters)." % MAX_NAME
    if not EMAIL_RE.match(email):
        return None, "A valid email is required (used to identify you for cancellation)."
    return {
        "room": room,
        "day": d.isoformat(),
        "start_min": s,
        "end_min": e,
        "booker": booker,
        "email": email,
    }, None


def find_conflict(conn, room, day, start, end, exclude_id=None):
    """Server-side double-booking check: overlapping [start, end) on same room+day.

    Cancelled bookings are ignored, so a cancelled slot is free immediately.
    """
    sql = ("SELECT * FROM bookings WHERE room = ? AND day = ? "
           "AND cancelled_at IS NULL AND start_min < ? AND end_min > ?")
    params = [room, day, end, start]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    return conn.execute(sql + " ORDER BY start_min", params).fetchall()


def row_to_dict(row):
    return {
        "id": row["id"],
        "room": row["room"],
        "date": row["day"],
        "start": hhmm(row["start_min"]),
        "end": hhmm(row["end_min"]),
        "booker": row["booker"],
        "email": row["email"],
        "title": row["title"],
        "created_at": row["created_at"],
        "cancelled_at": row["cancelled_at"] if "cancelled_at" in row.keys() else None,
        "cancelled_by": row["cancelled_by"] if "cancelled_by" in row.keys() else None,
    }


def create_booking(data):
    """Insert a booking atomically. Returns (booking_dict, error)."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")  # serialise writers -> no race on conflict check
        conflicts = find_conflict(conn, data["room"], data["day"], data["start_min"], data["end_min"])
        if conflicts:
            c = conflicts[0]
            conn.rollback()
            return None, ("That slot is already booked: %s %s-%s by %s."
                          % (c["room"], hhmm(c["start_min"]), hhmm(c["end_min"]), c["booker"]))
        cur = conn.execute(
            "INSERT INTO bookings (room, day, start_min, end_min, booker, email, title, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (data["room"], data["day"], data["start_min"], data["end_min"],
             data["booker"], data["email"], data.get("title", ""),
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (cur.lastrowid,)).fetchone()
        return row_to_dict(row), None
    finally:
        conn.close()


def cancel_booking(booking_id, email=None, admin_key=None):
    """Cancel if requester is the booker (email match) or supplies the admin key.

    Returns (booking_dict, error_message, error_code). error_code is 404 when the
    booking does not exist and 403 when the requester is not allowed to cancel.
    """
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not row:
            return None, "Booking not found.", 404
        if row["cancelled_at"]:
            return None, "That booking was already cancelled.", 409
        is_admin = isinstance(admin_key, str) and admin_key != "" and admin_key == ADMIN_KEY
        is_owner = isinstance(email, str) and email.strip().lower() == row["email"].lower()
        if not (is_admin or is_owner):
            if isinstance(admin_key, str) and admin_key != "":
                # The caller tried to act as an admin but the key was wrong.
                msg = ("That admin key is not correct, so you cannot cancel this booking. "
                       "Enter the admin key shown when the server started, or cancel with "
                       "the email address that made the booking.")
            else:
                msg = ("Only the person who booked this room (same email) or an admin "
                       "can cancel it.")
            return None, msg, 403
        # Soft delete: keep the record (so the dashboard can count cancellations)
        # but mark it cancelled. Every availability/conflict query ignores
        # cancelled rows, so the slot is free again immediately.
        who = "admin" if is_admin else row["email"]
        conn.execute("UPDATE bookings SET cancelled_at = ?, cancelled_by = ? WHERE id = ?",
                     (datetime.now().isoformat(timespec="seconds"), who, booking_id))
        conn.commit()
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return row_to_dict(row), None, None
    finally:
        conn.close()


def availability(day_text):
    """Return {room: [{start, end, status, booking}]} for one day."""
    d = parse_day(day_text)
    out = {}
    open_day = d.weekday() in WEEKDAYS
    with connect() as conn:
        rows = conn.execute("SELECT * FROM bookings WHERE day = ? AND cancelled_at IS NULL "
                            "ORDER BY start_min",
                            (d.isoformat(),)).fetchall()
    for room, cap in ROOMS:
        slots = []
        for s in SLOTS:
            e = s + SLOT_MINUTES
            if not open_day:
                slots.append({"start": hhmm(s), "end": hhmm(e), "status": "closed", "booking": None})
                continue
            hit = None
            for r in rows:
                if r["room"] == room and r["start_min"] < e and r["end_min"] > s:
                    hit = r
                    break
            slots.append({
                "start": hhmm(s),
                "end": hhmm(e),
                "status": "booked" if hit else "free",
                "booking": row_to_dict(hit) if hit else None,
            })
        out[room] = {"capacity": cap, "slots": slots}
    return {"date": d.isoformat(), "weekday": d.strftime("%A"), "open": open_day, "rooms": out}


def bookings_for_email(email, day=None):
    """Bookings for one email; when day is given BOTH filters are applied."""
    sql = "SELECT * FROM bookings WHERE lower(email) = lower(?) AND cancelled_at IS NULL"
    params = [(email or "").strip()]
    if day:
        sql += " AND day = ?"
        params.append(parse_day(day).isoformat())
    sql += " ORDER BY day, start_min"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row_to_dict(r) for r in rows]


def all_bookings(day=None):
    sql, params = "SELECT * FROM bookings WHERE cancelled_at IS NULL", []
    if day:
        sql += " AND day = ?"
        params.append(parse_day(day).isoformat())
    sql += " ORDER BY day, start_min, room"
    with connect() as conn:
        return [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def bookings_csv(day=None):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "room", "date", "start", "end", "booker", "email", "title", "created_at"])
    for b in all_bookings(day):
        w.writerow([b["id"], b["room"], b["date"], b["start"], b["end"],
                    b["booker"], b["email"], b["title"], b["created_at"]])
    return buf.getvalue()


# --------------------------------------------------------------------------
# Dashboard (manager view)
# --------------------------------------------------------------------------
def parse_range(from_text, to_text):
    """Validate the dashboard range. Returns (from_date, to_date). Raises ValueError."""
    if not from_text or not to_text:
        raise ValueError("Both from and to are required (YYYY-MM-DD).")
    try:
        d_from = parse_day(from_text)
        d_to = parse_day(to_text)
    except ValueError:
        raise ValueError("Dates must look like YYYY-MM-DD (e.g. 2025-06-02).")
    if d_from > d_to:
        raise ValueError("The 'from' date must be on or before the 'to' date.")
    span = (d_to - d_from).days + 1
    if span > MAX_RANGE_DAYS:
        raise ValueError("The range is too long: %d days, the maximum is %d."
                         % (span, MAX_RANGE_DAYS))
    return d_from, d_to


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def dashboard(from_text, to_text, room=None):
    """Aggregate the bookings table for a date range (manager dashboard).

    Only bookings whose date falls inside [from, to] are used. Cancelled
    bookings count towards the cancellation figures but NOT towards hours
    reserved / utilisation.
    """
    d_from, d_to = parse_range(from_text, to_text)
    room_filter = None
    if room:
        room_filter = canonical_room(room)
        if not room_filter:
            raise ValueError("Unknown room. Choose one of: %s." % ", ".join(room_names()))
    # NOTE: the range filter must be re-applied on every request (no caching).
    # `day` is stored as a zero-padded 'YYYY-MM-DD' TEXT column, so a plain
    # string BETWEEN is a correct date range comparison for every day in
    # [from, to] - not just the first one.
    with connect() as conn:
        rows = conn.execute(
            "SELECT room, day, start_min, end_min, cancelled_at FROM bookings "
            "WHERE day BETWEEN ? AND ? ORDER BY day, start_min",
            (d_from.isoformat(), d_to.isoformat())).fetchall()
    if room_filter:
        rows = [r for r in rows if r["room"] == room_filter]

    # Available hours: every weekday in the range x the 10 open hours per day.
    weekdays = 0
    d = d_from
    while d <= d_to:
        if d.weekday() in WEEKDAYS:
            weekdays += 1
        d += timedelta(days=1)
    open_hours = (DAY_END - DAY_START) / 60.0
    available_hours = weekdays * open_hours

    per_room = {}
    for name, cap in ROOMS:
        if room_filter and name != room_filter:
            continue
        per_room[name] = {"room": name, "capacity": cap, "bookings": 0, "hours": 0.0,
                          "cancelled": 0, "utilisation_pct": 0.0, "flag": "normal"}
    by_weekday = {n: 0 for n in WEEKDAY_NAMES}
    by_hour = {h: 0 for h in range(DAY_START // 60, DAY_END // 60)}
    by_date = {}
    cancelled_by_week = {}
    total_bookings = total_cancelled = 0
    total_minutes = 0

    for r in rows:
        cancelled = r["cancelled_at"] is not None
        day = datetime.strptime(r["day"], "%Y-%m-%d").date()
        info = per_room.get(r["room"])
        if info is None:
            continue
        if cancelled:
            total_cancelled += 1
            info["cancelled"] += 1
            wk = day - timedelta(days=day.weekday())
            cancelled_by_week[wk.isoformat()] = cancelled_by_week.get(wk.isoformat(), 0) + 1
            continue
        minutes = r["end_min"] - r["start_min"]
        total_bookings += 1
        total_minutes += minutes
        info["bookings"] += 1
        info["hours"] += minutes / 60.0
        by_weekday[WEEKDAY_NAMES[day.weekday()]] += 1
        by_date[r["day"]] = by_date.get(r["day"], 0) + 1
        for h in range(r["start_min"] // 60, (r["end_min"] - 1) // 60 + 1):
            if h in by_hour:
                by_hour[h] += 1

    rooms_out = []
    for name, _cap in ROOMS:
        info = per_room.get(name)
        if not info:
            continue
        info["hours"] = round(info["hours"], 1)
        info["utilisation_pct"] = _pct(info["hours"], available_hours)
        if info["utilisation_pct"] > HEAVY_PCT:
            info["flag"] = "heavy"
        elif info["utilisation_pct"] < UNDER_PCT:
            info["flag"] = "underused"
        rooms_out.append(info)

    top_dates = sorted(by_date.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    totals = {
        "bookings": total_bookings,
        "hours": round(total_minutes / 60.0, 1),
        "cancelled": total_cancelled,
        "cancellation_rate_pct": _pct(total_cancelled, total_cancelled + total_bookings),
    }
    trend = [{"week_start": k, "cancelled": v} for k, v in sorted(cancelled_by_week.items())]
    summary, recommendation = build_summary(rooms_out, totals, available_hours, weekdays)
    return {
        "range": {"from": d_from.isoformat(), "to": d_to.isoformat(),
                  "days": (d_to - d_from).days + 1, "weekdays": weekdays,
                  "available_hours_per_room": round(available_hours, 1)},
        "room_filter": room_filter,
        "rooms": rooms_out,
        "by_weekday": [{"weekday": k, "bookings": v} for k, v in by_weekday.items()],
        "by_hour": [{"hour": "%02d-%02d" % (h, h + 1), "bookings": v}
                    for h, v in by_hour.items()],
        "top_dates": [{"date": k, "bookings": v} for k, v in top_dates],
        "totals": totals,
        "cancelled_trend": trend,
        "thresholds": {"heavy_pct": HEAVY_PCT, "under_pct": UNDER_PCT},
        "summary": summary,
        "recommendation": recommendation,
    }


def build_summary(rooms_out, totals, available_hours, weekdays):
    """Plain-English summary + recommendation for the manager."""
    if not rooms_out:
        return "No rooms in this view.", ""
    ranked = sorted(rooms_out, key=lambda r: -r["utilisation_pct"])
    busiest = ranked[0]
    quietest = ranked[-1]
    parts = []
    if totals["bookings"] == 0 and totals["cancelled"] == 0:
        parts.append("No bookings in this period.")
    else:
        parts.append("%s is the busiest room (%s%% utilisation, %d bookings, %s h reserved)."
                     % (busiest["room"], busiest["utilisation_pct"], busiest["bookings"],
                        busiest["hours"]))
        if quietest["room"] != busiest["room"]:
            parts.append("%s is the quietest (%s%% utilisation)."
                         % (quietest["room"], quietest["utilisation_pct"]))
        parts.append("%d bookings reserved %s h in total; %d cancelled (%s%% cancellation rate)."
                     % (totals["bookings"], totals["hours"], totals["cancelled"],
                        totals["cancellation_rate_pct"]))
    summary = " ".join(parts)

    heavy = [r for r in ranked if r["flag"] == "heavy"]
    under = [r for r in ranked if r["flag"] == "underused"]
    rec = []
    if heavy:
        rec.append("%s %s heavily used (over %s%%) - consider moving some bookings to a "
                   "quieter room or adding capacity."
                   % (", ".join(r["room"] for r in heavy),
                      "is" if len(heavy) == 1 else "are", HEAVY_PCT))
    else:
        rec.append("No room is heavily used (none is over %s%% utilisation)." % HEAVY_PCT)
    if under:
        # Cap the list so the sentence stays readable: name at most
        # MAX_REC_ROOMS rooms (the least used first) and summarise the rest.
        shown = under[-MAX_REC_ROOMS:][::-1] if len(under) > MAX_REC_ROOMS else under
        names = ", ".join(r["room"] for r in shown)
        extra = len(under) - len(shown)
        if extra > 0:
            names += " and %d more" % extra
        rec.append("%s %s underused (under %s%%) - consider moving bookings there or "
                   "reallocating the room."
                   % (names, "is" if len(under) == 1 else "are", UNDER_PCT))
    if not heavy and not under:
        rec.append("All rooms are between %s%% and %s%% utilisation - no reallocation needed."
                   % (UNDER_PCT, HEAVY_PCT))
    return summary, " ".join(rec)


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------
PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meeting Room Booking</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f5f6f8;color:#1d2330}
 header{background:#1f3a5f;color:#fff;padding:14px 22px}
 header h1{margin:0;font-size:20px}
 header p{margin:4px 0 0;font-size:13px;opacity:.85}
 main{max-width:1180px;margin:0 auto;padding:18px}
 section{background:#fff;border:1px solid #dde1e8;border-radius:8px;padding:16px;margin-bottom:18px}
 h2{margin:0 0 12px;font-size:16px}
 label{display:block;font-size:12px;font-weight:600;margin-bottom:3px;color:#44506a}
 input,select{padding:7px 8px;border:1px solid #c3cad6;border-radius:5px;font-size:14px;width:100%;box-sizing:border-box}
 .row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
 .row>div{flex:1 1 150px}
 button{padding:8px 14px;border:0;border-radius:5px;background:#1f6feb;color:#fff;font-size:14px;cursor:pointer}
 button.ghost{background:#e8edf5;color:#1f3a5f}
 button.danger{background:#c62828}
 button:disabled{opacity:.5;cursor:not-allowed}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border:1px solid #e2e6ee;padding:6px 8px;text-align:left;vertical-align:top}
 th{background:#f0f3f8;font-size:12px}
 .slot{display:inline-block;margin:2px;padding:4px 6px;border-radius:4px;font-size:12px;border:1px solid #cfd6e2;background:#eefaf0;cursor:pointer}
 .slot.booked{background:#fdecec;border-color:#f0b4b4;cursor:not-allowed;color:#8a1c1c}
 .slot.closed{background:#f1f1f1;color:#999;cursor:not-allowed}
 .slot.sel{outline:2px solid #1f6feb}
 .msg{padding:9px 12px;border-radius:6px;margin-bottom:12px;font-size:14px}
 .msg.ok{background:#e6f6ea;border:1px solid #a9dcb6}
 .msg.err{background:#fdecec;border:1px solid #f0b4b4}
 .muted{color:#6b7688;font-size:12px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px}
 .card{border:1px solid #e2e6ee;border-radius:6px;padding:10px}
 .card h3{margin:0 0 6px;font-size:14px}
 .legend span{margin-right:12px;font-size:12px}
</style></head>
<body>
<header>
  <h1>Meeting Room Booking</h1>
  <p>5 rooms &middot; 30-minute slots &middot; 08:00&ndash;18:00, Mon&ndash;Fri</p>
</header>
<main>
  <div id="flash"></div>

  <section>
    <h2>1. Check availability</h2>
    <div class="row">
      <div><label for="availDate">Date</label><input type="date" id="availDate"></div>
      <div style="flex:0 0 auto"><button onclick="loadAvailability()">Show availability</button></div>
      <div style="flex:0 0 auto"><button class="ghost" onclick="stepDay(-1)">&larr; Prev day</button></div>
      <div style="flex:0 0 auto"><button class="ghost" onclick="stepDay(1)">Next day &rarr;</button></div>
    </div>
    <p class="legend muted" style="margin-top:10px">
      <span style="color:#2e7d32">&#9632; free</span>
      <span style="color:#8a1c1c">&#9632; booked</span>
      <span style="color:#999">&#9632; closed</span>
      &nbsp;Click a free slot to prefill the booking form.
    </p>
    <div id="availability" class="grid"></div>
  </section>

  <section>
    <h2>2. Book a room</h2>
    <form id="bookForm" onsubmit="return submitBooking(event)">
      <div class="row">
        <div><label for="bRoom">Room</label><select id="bRoom"></select></div>
        <div><label for="bDate">Date</label><input type="date" id="bDate" required></div>
        <div><label for="bStart">Start</label><select id="bStart"></select></div>
        <div><label for="bEnd">End</label><select id="bEnd"></select></div>
      </div>
      <div class="row" style="margin-top:10px">
        <div><label for="bName">Your name</label><input id="bName" required placeholder="Ada Lovelace"></div>
        <div><label for="bEmail">Your email</label><input id="bEmail" type="email" required placeholder="ada@example.com"></div>
        <div><label for="bTitle">Purpose (optional, max 200 characters)</label><input id="bTitle" maxlength="200" placeholder="Sprint planning"></div>
        <div style="flex:0 0 auto"><button type="submit">Book room</button></div>
      </div>
    </form>
  </section>

  <section>
    <h2>3. My bookings</h2>
    <div class="row">
      <div><label for="myEmail">Your email</label><input id="myEmail" type="email" placeholder="ada@example.com"></div>
      <div style="flex:0 0 auto"><button onclick="loadMine()">Show my bookings</button></div>
      <div style="flex:0 0 auto"><button class="ghost" onclick="exportCsv()">Export all to CSV</button></div>
    </div>
    <div id="mine" style="margin-top:12px"></div>
  </section>

  <section>
    <h2>Admin</h2>
    <div class="row">
      <div><label for="adminKey">Admin key (needed to see and cancel anyone's booking)</label><input id="adminKey" type="password" placeholder="admin"></div>
      <div style="flex:0 0 auto"><button class="ghost" onclick="loadAll()">Show all bookings</button></div>
    </div>
    <div id="all" style="margin-top:12px"></div>
  </section>
  <section>
    <h2>Dashboard (manager)</h2>
    <p class="muted" style="margin-top:0">Admin key required. Figures come from the booking records for the
      selected dates only. Cancelled bookings are counted in the cancellation figures but
      <strong>not</strong> in hours reserved or utilisation. Utilisation = hours reserved &divide;
      (weekdays in range &times; 10 open hours). Heavily used = over <span id="thHeavy">70</span>%,
      underused = under <span id="thUnder">25</span>%.</p>
    <div class="row">
      <div><label for="dashKey">Admin key</label><input id="dashKey" type="password" placeholder="admin"></div>
      <div><label for="dashFrom">From</label><input type="date" id="dashFrom"></div>
      <div><label for="dashTo">To</label><input type="date" id="dashTo"></div>
      <div><label for="dashRoom">Room</label><select id="dashRoom"><option value="">All rooms</option></select></div>
      <div style="flex:0 0 auto"><button onclick="loadDashboard()">Refresh</button></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div style="flex:0 0 auto"><button class="ghost" onclick="preset(7)">Last 7 days</button></div>
      <div style="flex:0 0 auto"><button class="ghost" onclick="preset(30)">Last 30 days</button></div>
      <div style="flex:0 0 auto"><button class="ghost" onclick="preset(90)">Last 90 days</button></div>
      <div style="flex:0 0 auto"><button class="ghost" onclick="preset('month')">This month</button></div>
    </div>
    <div id="dash" style="margin-top:14px"></div>
  </section>
</main>
<script>
const ROOMS = __ROOMS__;
const SLOTS = __SLOTS__;
const $ = id => document.getElementById(id);

function todayStr(){ const d=new Date(); return localDate(d); }
function localDate(d){ return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0'); }
async function api(url, opts){
  let res;
  try { res = await fetch(url, opts); }
  catch(e){ flash('Cannot reach the server. Is it still running?', false); return null; }
  let data;
  try { data = await res.json(); }
  catch(e){ flash('Unexpected server response.', false); return null; }
  if(!res.ok){ flash(data.error || ('Request failed (' + res.status + ')'), false); return null; }
  return data;
}
function flash(text, ok){
  $('flash').innerHTML = text ? `<div class="msg ${ok?'ok':'err'}">${esc(text)}</div>` : '';
  if(text) window.scrollTo({top:0,behavior:'smooth'});
}
function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function init(){
  $('bRoom').innerHTML = ROOMS.map(r=>`<option value="${esc(r.name)}">${esc(r.name)} (${r.capacity} people)</option>`).join('');
  const opts = SLOTS.map(s=>`<option value="${s}">${s}</option>`).join('');
  $('bStart').innerHTML = opts;
  $('bEnd').innerHTML = opts;
  $('bStart').value = '09:00'; $('bEnd').value = '10:00';
  $('availDate').value = todayStr(); $('bDate').value = todayStr();
  const saved = localStorage.getItem('bookerEmail');
  if(saved){ $('bEmail').value = saved; $('myEmail').value = saved; }
  $('dashRoom').innerHTML = '<option value="">All rooms</option>' +
    ROOMS.map(r=>`<option value="${esc(r.name)}">${esc(r.name)}</option>`).join('');
  preset(30);  // default dashboard range: last 30 days
  loadAvailability();
}

function stepDay(n){
  const d = new Date($('availDate').value + 'T00:00:00');
  d.setDate(d.getDate()+n);
  $('availDate').value = localDate(d);
  loadAvailability();
}

async function loadAvailability(){
  try {
    const day = $('availDate').value;
    if(!day){ flash('Pick a date first.', false); return; }
    const data = await api('/api/availability?date=' + encodeURIComponent(day));
    if(!data) return;
    if(!data.open){
      $('availability').innerHTML = `<p class="muted">${esc(data.weekday)} ${esc(data.date)} is outside Mon&ndash;Fri. Rooms are closed.</p>`;
      return;
    }
    $('availability').innerHTML = Object.entries(data.rooms).map(([room, info])=>{
      const slots = info.slots.map(s=>{
        if(s.status==='booked'){
          const b=s.booking;
          return `<span class="slot booked" title="${esc(b.booker)} &mdash; ${esc(b.title||'')}">${s.start} ${esc(b.booker)}</span>`;
        }
        if(s.status==='closed') return `<span class="slot closed">${s.start}</span>`;
        return `<span class="slot" onclick="pick('${esc(room)}','${s.start}','${s.end}')">${s.start}</span>`;
      }).join('');
      return `<div class="card"><h3>${esc(room)} <span class="muted">(${info.capacity} people)</span></h3>${slots}</div>`;
    }).join('');
  } catch(e){
    $('availability').innerHTML = '';
    flash('Could not load availability: ' + (e && e.message ? e.message : e), false);
  }
}

function pick(room, start, end){
  $('bRoom').value = room;
  $('bDate').value = $('availDate').value;
  $('bStart').value = start;
  $('bEnd').value = end;
  $('bName').focus();
  flash(`Selected ${room} ${start}-${end}. Fill in your name and email, then press "Book room".`, true);
}

async function submitBooking(ev){
  ev.preventDefault();
  const body = {
    room: $('bRoom').value, date: $('bDate').value,
    start: $('bStart').value, end: $('bEnd').value,
    booker: $('bName').value, email: $('bEmail').value, title: $('bTitle').value
  };
  const res = await fetch('/api/bookings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  let data;
  try { data = await res.json(); } catch(e){ flash('Unexpected server response.', false); return false; }
  if(!res.ok){ flash(data.error || 'Booking failed', false); return false; }
  localStorage.setItem('bookerEmail', body.email);
  $('myEmail').value = body.email;
  flash(`Booked ${data.booking.room} on ${data.booking.date} ${data.booking.start}-${data.booking.end}.`, true);
  $('availDate').value = body.date;
  loadAvailability(); loadMine();
  return false;
}

async function loadMine(){
  try {
    const email = $('myEmail').value.trim();
    if(!email){ flash('Enter your email to see your bookings.', false); return; }
    localStorage.setItem('bookerEmail', email);
    const data = await api('/api/bookings?email=' + encodeURIComponent(email));
    if(!data) return;
    $('mine').innerHTML = renderTable(data.bookings, 'mine');
  } catch(e){
    $('mine').innerHTML = '';
    flash('Could not load your bookings: ' + (e && e.message ? e.message : e), false);
  }
}

async function loadAll(){
  try {
    const key = $('adminKey').value.trim();
    if(!key){ flash('Enter the admin key to see all bookings.', false); return; }
    const data = await api('/api/bookings?admin_key=' + encodeURIComponent(key));
    if(!data) return;
    $('all').innerHTML = renderTable(data.bookings, 'all');
  } catch(e){
    $('all').innerHTML = '';
    flash('Could not load all bookings: ' + (e && e.message ? e.message : e), false);
  }
}

function renderTable(list, source){
  if(!list.length) return '<p class="muted">No bookings.</p>';
  const rows = list.map(b=>`<tr>
    <td>${esc(b.date)}</td><td>${esc(b.start)}&ndash;${esc(b.end)}</td><td>${esc(b.room)}</td>
    <td>${esc(b.booker)}<br><span class="muted">${esc(b.email)}</span></td><td>${esc(b.title)}</td>
    <td><button class="danger" onclick="cancelBooking(${b.id},'${source}')">Cancel</button></td></tr>`).join('');
  return `<table><thead><tr><th>Date</th><th>Time</th><th>Room</th><th>Booker</th><th>Purpose</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function cancelBooking(id, source){
  if(!confirm('Cancel booking #' + id + '?')) return;
  // Explicit identity per table: "My bookings" cancels as the email typed there,
  // the admin table cancels with the admin key typed in the Admin box.
  const body = source === 'all'
    ? {admin_key: $('adminKey').value.trim()}
    : {email: $('myEmail').value.trim()};
  if(source === 'all' && !body.admin_key){
    flash('Enter the admin key in the Admin box to cancel someone else\'s booking.', false);
    return;
  }
  if(source !== 'all' && !body.email){
    flash('Enter your email in "My bookings" to cancel your booking.', false);
    return;
  }
  let res, data;
  try {
    res = await fetch('/api/bookings/' + id, {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    data = await res.json();
  } catch(e){
    flash('Could not cancel the booking: ' + (e && e.message ? e.message : e), false);
    return;
  }
  if(!res.ok){ flash(data.error || 'Cancel failed', false); return; }
  flash(`Cancelled ${data.booking.room} on ${data.booking.date} ${data.booking.start}-${data.booking.end}. The slot is free again.`, true);
  loadAvailability(); loadMine();
  if(source === 'all') loadAll();
  if($('dash').innerHTML) loadDashboard();
}

function exportCsv(){
  const day = $('availDate').value;
  window.location = '/api/bookings.csv' + (day ? '?date=' + encodeURIComponent(day) : '');
}

init();

// ---------------- Dashboard (manager) ----------------
function preset(kind){
  const today = new Date();
  let from, to;
  if(kind === 'month'){
    from = new Date(today.getFullYear(), today.getMonth(), 1);
    to = new Date(today.getFullYear(), today.getMonth()+1, 0);
  } else {
    to = today;
    from = new Date(today.getTime());
    from.setDate(from.getDate() - (kind - 1));
  }
  $('dashFrom').value = localDate(from);
  $('dashTo').value = localDate(to);
  loadDashboard();
}

function barChart(items, labelKey, valueKey, colour){
  // Inline SVG bar chart - no external libraries.
  if(!items.length) return '<p class="muted">No data.</p>';
  const max = Math.max(1, ...items.map(i=>i[valueKey]));
  const w = 34, gap = 12, h = 120, pad = 18;
  const width = items.length * (w + gap) + pad;
  const bars = items.map((it, i)=>{
    const bh = Math.round(h * it[valueKey] / max);
    const x = pad + i * (w + gap);
    return `<rect x="${x}" y="${h - bh}" width="${w}" height="${bh}" fill="${colour}" rx="2"></rect>`
      + `<text x="${x + w/2}" y="${h - bh - 4}" font-size="10" text-anchor="middle" fill="#44506a">${it[valueKey]}</text>`
      + `<text x="${x + w/2}" y="${h + 13}" font-size="10" text-anchor="middle" fill="#6b7688">${esc(it[labelKey])}</text>`;
  }).join('');
  return `<svg viewBox="0 0 ${width} ${h + 20}" width="100%" height="150" role="img">${bars}</svg>`;
}

function roomBars(rooms){
  if(!rooms.length) return '<p class="muted">No rooms.</p>';
  return rooms.map(r=>{
    const pct = Math.min(100, r.utilisation_pct);
    const colour = r.flag === 'heavy' ? '#c62828' : (r.flag === 'underused' ? '#e08a00' : '#1f6feb');
    return `<div style="margin-bottom:6px"><div class="muted">${esc(r.room)} &mdash; ${r.utilisation_pct}%</div>
      <div style="background:#eef1f6;border-radius:4px;height:14px"><div style="width:${pct}%;height:14px;background:${colour};border-radius:4px"></div></div></div>`;
  }).join('');
}

function flagBadge(flag){
  if(flag === 'heavy') return '<span style="color:#c62828;font-weight:600">heavily used</span>';
  if(flag === 'underused') return '<span style="color:#e08a00;font-weight:600">underused</span>';
  return '<span class="muted">normal</span>';
}

async function loadDashboard(){
  try {
    const key = $('dashKey').value.trim();
    if(!key){ $('dash').innerHTML = ''; flash('Enter the admin key to open the dashboard.', false); return; }
    const from = $('dashFrom').value, to = $('dashTo').value;
    if(!from || !to){ flash('Pick both a from and a to date.', false); return; }
    const room = $('dashRoom').value;
    const url = '/api/dashboard?from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to)
      + '&admin_key=' + encodeURIComponent(key) + (room ? '&room=' + encodeURIComponent(room) : '');
    const data = await api(url);
    if(!data) return;
    $('thHeavy').textContent = data.thresholds.heavy_pct;
    $('thUnder').textContent = data.thresholds.under_pct;
    const t = data.totals;
    const rows = data.rooms.map(r=>`<tr><td>${esc(r.room)}</td><td>${r.capacity}</td><td>${r.bookings}</td>
      <td>${r.hours}</td><td>${r.utilisation_pct}%</td><td>${r.cancelled}</td><td>${flagBadge(r.flag)}</td></tr>`).join('');
    const trend = data.cancelled_trend.length
      ? barChart(data.cancelled_trend, 'week_start', 'cancelled', '#c62828')
      : '<p class="muted">No cancellations in this range.</p>';
    $('dash').innerHTML = `
      <div class="msg ok"><strong>Summary:</strong> ${esc(data.summary)}<br><strong>Recommendation:</strong> ${esc(data.recommendation)}</div>
      <p class="muted">Range ${esc(data.range.from)} to ${esc(data.range.to)} (${data.range.days} days, ${data.range.weekdays} weekdays, ${data.range.available_hours_per_room} available hours per room)${data.room_filter ? ' &middot; room filter: ' + esc(data.room_filter) : ''}.</p>
      <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(150px,1fr));margin-bottom:14px">
        <div class="card"><h3>${t.bookings}</h3><span class="muted">bookings</span></div>
        <div class="card"><h3>${t.hours} h</h3><span class="muted">hours reserved</span></div>
        <div class="card"><h3>${t.cancelled}</h3><span class="muted">cancelled</span></div>
        <div class="card"><h3>${t.cancellation_rate_pct}%</h3><span class="muted">cancellation rate</span></div>
      </div>
      <h3 style="font-size:14px">Utilisation per room</h3>${roomBars(data.rooms)}
      <h3 style="font-size:14px;margin-top:14px">Busiest days of the week</h3>${barChart(data.by_weekday, 'weekday', 'bookings', '#1f6feb')}
      <h3 style="font-size:14px">Busiest times of day</h3>${barChart(data.by_hour, 'hour', 'bookings', '#2e7d32')}
      <h3 style="font-size:14px">Top 5 busiest dates</h3>${barChart(data.top_dates, 'date', 'bookings', '#6a3fb5')}
      <h3 style="font-size:14px">Cancellations per week</h3>${trend}
      <h3 style="font-size:14px;margin-top:14px">Per-room detail</h3>
      <table><thead><tr><th>Room</th><th>Capacity</th><th>Bookings</th><th>Hours reserved</th><th>Utilisation</th><th>Cancelled</th><th>Flag</th></tr></thead><tbody>${rows}</tbody></table>`;
  } catch(e){
    $('dash').innerHTML = '';
    flash('Could not load the dashboard: ' + (e && e.message ? e.message : e), false);
  }
}
</script>
</body></html>
"""


def render_page():
    rooms = [{"name": n, "capacity": c} for n, c in ROOMS]
    slots = [hhmm(s) for s in SLOTS]
    return (PAGE.replace("__ROOMS__", json.dumps(rooms))
                .replace("__SLOTS__", json.dumps(slots)))


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------
class BadRequest(Exception):
    """Raised for malformed request bodies; answered with HTTP 400."""


class Handler(BaseHTTPRequestHandler):
    server_version = "RoomBooking/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers -----------------------------------------------------------
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise BadRequest("Request body is not valid JSON.")
        if not isinstance(data, dict):
            raise BadRequest("Request body must be a JSON object.")
        return data

    def _query(self):
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        path, q = self._query()
        try:
            if path in ("/", "/index.html"):
                self._send(200, render_page(), "text/html; charset=utf-8")
            elif path == "/api/rooms":
                self._json(200, {"rooms": [{"name": n, "capacity": c} for n, c in ROOMS],
                                 "slots": [hhmm(s) for s in SLOTS],
                                 "day_start": hhmm(DAY_START), "day_end": hhmm(DAY_END)})
            elif path == "/api/availability":
                day = (q.get("date") or [""])[0]
                if not day:
                    self._json(400, {"error": "date query parameter is required (YYYY-MM-DD)"})
                    return
                try:
                    self._json(200, availability(day))
                except ValueError as e:
                    self._json(400, {"error": str(e)})
            elif path == "/api/bookings":
                email = (q.get("email") or [""])[0]
                day = (q.get("date") or [""])[0]
                admin_key = (q.get("admin_key") or [""])[0]
                try:
                    if email:
                        # "my bookings": email filter, plus the date filter when given.
                        self._json(200, {"bookings": bookings_for_email(email, day or None)})
                    elif admin_key == ADMIN_KEY:
                        self._json(200, {"bookings": all_bookings(day or None)})
                    else:
                        self._json(403, {"error": (
                            "The full booking list is admin-only. Add ?admin_key=... "
                            "(the key printed when the server started), or use "
                            "?email=you@example.com to see your own bookings.")})
                except ValueError as e:
                    self._json(400, {"error": str(e)})
            elif path == "/api/dashboard":
                admin_key = (q.get("admin_key") or [""])[0]
                if admin_key != ADMIN_KEY:
                    self._json(403, {"error": (
                        "The dashboard is admin-only. Enter the admin key (the key "
                        "printed when the server started).")})
                    return
                from_text = (q.get("from") or [""])[0]
                to_text = (q.get("to") or [""])[0]
                room = (q.get("room") or [""])[0]
                try:
                    self._json(200, dashboard(from_text, to_text, room or None))
                except ValueError as e:
                    self._json(400, {"error": str(e)})
            elif path == "/api/bookings.csv":
                day = (q.get("date") or [""])[0]
                try:
                    data = bookings_csv(day or None)
                except ValueError as e:
                    self._json(400, {"error": str(e)})
                    return
                self._send(200, data, "text/csv; charset=utf-8",
                           {"Content-Disposition": 'attachment; filename="bookings.csv"'})
            elif path == "/health":
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "Not found"})
        except BadRequest as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # pragma: no cover - defensive
            self._json(500, {"error": "Server error: %s" % e})

    def do_POST(self):
        path, _ = self._query()
        if path != "/api/bookings":
            self._json(404, {"error": "Not found"})
            return
        try:
            body = self._body()
        except BadRequest as e:
            self._json(400, {"error": str(e)})
            return
        data, err = validate_booking(body.get("room"), body.get("date"), body.get("start"),
                                     body.get("end"), body.get("booker"), body.get("email"))
        if err:
            self._json(400, {"error": err})
            return
        data["title"] = str(body.get("title") or "").strip()
        if len(data["title"]) > MAX_TITLE:
            self._json(400, {"error": (
                "The purpose/title is too long: %d characters, the maximum is %d. "
                "Please shorten it." % (len(data["title"]), MAX_TITLE))})
            return
        booking, err = create_booking(data)
        if err:
            self._json(409, {"error": err})
            return
        self._json(201, {"booking": booking})

    def do_DELETE(self):
        path, _ = self._query()
        m = re.match(r"^/api/bookings/(\d+)$", path)
        if not m:
            self._json(404, {"error": "Not found"})
            return
        try:
            body = self._body()
        except BadRequest as e:
            self._json(400, {"error": str(e)})
            return
        booking, err, code = cancel_booking(int(m.group(1)), body.get("email"), body.get("admin_key"))
        if err:
            self._json(code or 403, {"error": err})
            return
        self._json(200, {"booking": booking})

    def do_HEAD(self):
        self.do_GET()


def main():
    init_db()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("Meeting Room Booking running at http://localhost:%d" % PORT)
    print("Admin key: %s   (override with ADMIN_KEY=...)" % ADMIN_KEY)
    print("Database: %s" % DB_PATH)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
