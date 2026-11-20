#!/usr/bin/env python3
"""Meeting room booking web app.

Single self-contained file, Python 3 standard library only.

Run:  python3 app.py            -> http://localhost:8000
Data: bookings.db (sqlite) next to this script.

Design notes
------------
* Rooms live in a `rooms` table so they can be edited later.
* Bookings are soft-deleted: cancelling sets `cancelled_at`, so history is kept
  but the slot is immediately free again (records never go stale).
* Double bookings are prevented by checking for overlapping ACTIVE bookings and
  inserting inside one `BEGIN IMMEDIATE` transaction, so two concurrent
  requests cannot both succeed.
* Overlap test for half-open intervals [start, end):
      new_start < existing_end AND new_end > existing_start
* Every request is validated strictly: text fields must be JSON strings,
  numeric fields must be real JSON integers (booleans and floats are rejected),
  and no request can ever produce a 500 traceback - unexpected errors are
  returned as a JSON message.
"""

import csv
import io
import json
import os
import re
import sqlite3
import sys
from datetime import date as date_cls, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("BOOKINGS_DB", os.path.join(BASE_DIR, "bookings.db"))

DAY_START = "08:00"
DAY_END = "19:00"
SLOT_MINUTES = 15

DEFAULT_ROOMS = [
    ("Aurora", 8),
    ("Birch", 4),
    ("Cedar", 12),
    ("Dune", 6),
]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL UNIQUE,
                capacity INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS bookings (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id      INTEGER NOT NULL REFERENCES rooms(id),
                date         TEXT NOT NULL,          -- YYYY-MM-DD
                start_time   TEXT NOT NULL,          -- HH:MM
                end_time     TEXT NOT NULL,          -- HH:MM
                booker       TEXT NOT NULL,
                title        TEXT NOT NULL,
                notes        TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL,
                cancelled_at TEXT,                   -- NULL = active
                cancelled_by TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_bookings_slot
                ON bookings(room_id, date, cancelled_at);
            """
        )
        # Seed the default rooms once.
        if conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0:
            conn.executemany("INSERT INTO rooms(name, capacity) VALUES (?, ?)", DEFAULT_ROOMS)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
class ApiError(Exception):
    """Raised for client errors; carries an HTTP status and readable message."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def from_minutes(mins):
    return "%02d:%02d" % (mins // 60, mins % 60)


def as_text(value, label, required=True, max_len=200):
    """Return a stripped string, or raise 400.

    Only JSON strings are accepted: numbers, lists, objects, booleans and null
    are rejected with a readable message instead of crashing on .strip().
    """
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, "%s must be text (a JSON string), not %s." % (label, type(value).__name__))
    value = value.strip()
    if required and not value:
        raise ApiError(400, "%s is required." % label)
    if len(value) > max_len:
        raise ApiError(400, "%s must be at most %d characters." % (label, max_len))
    return value


def as_int(value, label, minimum=None, maximum=None, default=None):
    """Return a real integer, or raise 400.

    Booleans (true/false) and floats (1.5, 1.0) are rejected: they are almost
    always a client bug and silently truncating them books the wrong thing.
    """
    if value is None or value == "":
        if default is not None:
            return default
        raise ApiError(400, "%s is required." % label)
    if isinstance(value, bool):
        raise ApiError(400, "%s must be a whole number, not true/false." % label)
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        raise ApiError(400, "%s must be a whole number (e.g. 2), not %s." % (label, value))
    elif isinstance(value, str):
        text = value.strip()
        if not re.match(r"^[+-]?\d+$", text):
            raise ApiError(400, "%s must be a whole number (e.g. 2), not %r." % (label, value))
        number = int(text)
    else:
        raise ApiError(400, "%s must be a whole number, not %s." % (label, type(value).__name__))
    if minimum is not None and number < minimum:
        raise ApiError(400, "%s must be at least %d." % (label, minimum))
    if maximum is not None and number > maximum:
        raise ApiError(400, "%s must be at most %d." % (label, maximum))
    return number


def validate_date(value):
    value = as_text(value, "Date")
    if not DATE_RE.match(value):
        raise ApiError(400, "Date must be in YYYY-MM-DD format.")
    try:
        date_cls.fromisoformat(value)
    except ValueError:
        raise ApiError(400, "Date %r is not a real calendar date." % value)
    return value


def validate_time(value, label):
    value = as_text(value, label)
    if not TIME_RE.match(value):
        raise ApiError(400, "%s must be a time in HH:MM format." % label)
    mins = to_minutes(value)
    if mins % SLOT_MINUTES != 0:
        raise ApiError(400, "%s must be on a %d-minute boundary (e.g. 09:15)." % (label, SLOT_MINUTES))
    if mins < to_minutes(DAY_START) or mins > to_minutes(DAY_END):
        raise ApiError(400, "%s must be between %s and %s." % (label, DAY_START, DAY_END))
    return value


def clean_text(value, label, required=True, max_len=200):
    return as_text(value, label, required=required, max_len=max_len)


def free_gaps(bookings):
    """Return list of (start, end) free gaps in the working day."""
    gaps = []
    cursor = to_minutes(DAY_START)
    day_end = to_minutes(DAY_END)
    for b in sorted(bookings, key=lambda x: x["start"]):
        s, e = to_minutes(b["start"]), to_minutes(b["end"])
        if s > cursor:
            gaps.append({"start": from_minutes(cursor), "end": from_minutes(s)})
        cursor = max(cursor, e)
    if cursor < day_end:
        gaps.append({"start": from_minutes(cursor), "end": from_minutes(day_end)})
    return gaps


def booking_row_to_dict(row):
    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "room": row["room_name"],
        "date": row["date"],
        "start": row["start_time"],
        "end": row["end_time"],
        "booker": row["booker"],
        "title": row["title"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "cancelled_at": row["cancelled_at"],
        "cancelled_by": row["cancelled_by"],
    }


BOOKING_SELECT = """
    SELECT b.*, r.name AS room_name
    FROM bookings b JOIN rooms r ON r.id = b.room_id
"""


# --------------------------------------------------------------------------
# Core operations
# --------------------------------------------------------------------------
def list_rooms():
    conn = connect()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name, capacity FROM rooms ORDER BY id")]
    finally:
        conn.close()


def get_room(conn, room_id):
    row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if row is None:
        raise ApiError(400, "Unknown room id %r." % room_id)
    return row


def list_bookings(date=None, room_id=None, include_cancelled=False):
    sql = BOOKING_SELECT + " WHERE 1=1"
    params = []
    if date:
        sql += " AND b.date = ?"
        params.append(date)
    if room_id:
        sql += " AND b.room_id = ?"
        params.append(room_id)
    if not include_cancelled:
        sql += " AND b.cancelled_at IS NULL"
    sql += " ORDER BY b.date, b.start_time, r.name"
    conn = connect()
    try:
        return [booking_row_to_dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def availability(date):
    validate_date(date)
    conn = connect()
    try:
        rooms = [dict(r) for r in conn.execute("SELECT id, name, capacity FROM rooms ORDER BY id")]
        rows = conn.execute(
            BOOKING_SELECT + " WHERE b.date = ? AND b.cancelled_at IS NULL ORDER BY b.start_time",
            (date,),
        ).fetchall()
    finally:
        conn.close()
    by_room = {r["id"]: [] for r in rooms}
    for row in rows:
        by_room[row["room_id"]].append(booking_row_to_dict(row))
    out = []
    for r in rooms:
        booked = by_room[r["id"]]
        out.append({
            "room_id": r["id"],
            "room": r["name"],
            "capacity": r["capacity"],
            "bookings": booked,
            "free": free_gaps(booked),
        })
    return {"date": date, "day_start": DAY_START, "day_end": DAY_END, "rooms": out}


def _find_conflict(conn, room_id, day, start, end):
    """Return the first active booking overlapping [start, end) or None."""
    return conn.execute(
        BOOKING_SELECT + """
        WHERE b.room_id = ? AND b.date = ? AND b.cancelled_at IS NULL
          AND ? < b.end_time AND ? > b.start_time
        ORDER BY b.start_time LIMIT 1
        """,
        (room_id, day, start, end),
    ).fetchone()


def create_bookings(payload):
    """Create one booking, or a weekly series when repeat_weeks > 0.

    All-or-nothing: if any week conflicts, nothing is created.
    """
    room_id = as_int(payload.get("room_id"), "Room")
    day = validate_date(payload.get("date"))
    start = validate_time(payload.get("start"), "Start time")
    end = validate_time(payload.get("end"), "End time")
    if to_minutes(end) <= to_minutes(start):
        raise ApiError(400, "End time must be after start time.")
    booker = clean_text(payload.get("booker"), "Your name", max_len=100)
    title = clean_text(payload.get("title"), "Title", max_len=200)
    notes = clean_text(payload.get("notes"), "Notes", required=False, max_len=2000)
    repeat_weeks = as_int(payload.get("repeat_weeks"), "Repeat weeks",
                          minimum=0, maximum=52, default=0)

    base = date_cls.fromisoformat(day)
    dates = [(base + timedelta(weeks=w)).isoformat() for w in range(repeat_weeks + 1)]

    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")  # serialise check + insert
        room = get_room(conn, room_id)
        conflicts = []
        for d in dates:
            hit = _find_conflict(conn, room_id, d, start, end)
            if hit is not None:
                conflicts.append(
                    "Room %s is already booked %s-%s on %s (%s)"
                    % (room["name"], hit["start_time"], hit["end_time"], d, hit["title"])
                )
        if conflicts:
            conn.execute("ROLLBACK")
            if len(conflicts) == 1:
                raise ApiError(409, conflicts[0])
            raise ApiError(
                409,
                "Nothing was booked: %d of %d weeks conflict. First conflict: %s"
                % (len(conflicts), len(dates), conflicts[0]),
            )
        created = now_iso()
        ids = []
        for d in dates:
            cur = conn.execute(
                """INSERT INTO bookings(room_id, date, start_time, end_time, booker,
                                        title, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (room_id, d, start, end, booker, title, notes, created),
            )
            ids.append(cur.lastrowid)
        conn.execute("COMMIT")
    except ApiError:
        raise
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()

    rows = list_bookings(room_id=room_id, include_cancelled=True)
    created_rows = [r for r in rows if r["id"] in ids]
    return {"created": created_rows, "count": len(created_rows)}


def cancel_booking(booking_id, cancelled_by=""):
    cancelled_by = clean_text(cancelled_by, "Your name", required=False, max_len=100)
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(BOOKING_SELECT + " WHERE b.id = ?", (booking_id,)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            raise ApiError(404, "Booking %s does not exist." % booking_id)
        if row["cancelled_at"] is not None:
            conn.execute("ROLLBACK")
            raise ApiError(409, "Booking %s was already cancelled at %s." % (booking_id, row["cancelled_at"]))
        conn.execute(
            "UPDATE bookings SET cancelled_at = ?, cancelled_by = ? WHERE id = ?",
            (now_iso(), cancelled_by, booking_id),
        )
        conn.execute("COMMIT")
        row = conn.execute(BOOKING_SELECT + " WHERE b.id = ?", (booking_id,)).fetchone()
        return booking_row_to_dict(row)
    except ApiError:
        raise
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def export_csv():
    rows = list_bookings(include_cancelled=False)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "room", "date", "start", "end", "booker", "title", "notes", "created_at"])
    for r in rows:
        writer.writerow([r["id"], r["room"], r["date"], r["start"], r["end"],
                         r["booker"], r["title"], r["notes"], r["created_at"]])
    return buf.getvalue()


# --------------------------------------------------------------------------
# HTML UI (inline, no build step)
# --------------------------------------------------------------------------
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meeting Room Booking</title>
<style>
  :root { --ink:#1d2433; --muted:#5b6577; --line:#d8dee9; --accent:#2f6fed;
          --ok:#1f7a45; --err:#b3261e; --bg:#f6f8fb; }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         color:var(--ink); background:var(--bg); }
  header { background:#fff; border-bottom:1px solid var(--line); padding:14px 24px; }
  header h1 { margin:0; font-size:20px; }
  header p { margin:4px 0 0; color:var(--muted); font-size:13px; }
  main { max-width:1180px; margin:0 auto; padding:18px 24px 60px; }
  section { background:#fff; border:1px solid var(--line); border-radius:10px;
            padding:16px 18px; margin-bottom:18px; }
  h2 { font-size:16px; margin:0 0 12px; }
  label { display:block; font-size:12px; font-weight:600; color:var(--muted);
          margin-bottom:4px; text-transform:uppercase; letter-spacing:.03em; }
  input, select, textarea, button { font:inherit; }
  input, select, textarea { width:100%; padding:7px 9px; border:1px solid var(--line);
          border-radius:6px; background:#fff; color:var(--ink); }
  textarea { resize:vertical; min-height:56px; }
  button { cursor:pointer; border:1px solid var(--accent); background:var(--accent);
           color:#fff; padding:8px 14px; border-radius:6px; font-weight:600; }
  button.secondary { background:#fff; color:var(--accent); }
  button.danger { background:#fff; color:var(--err); border-color:var(--err); padding:4px 10px; font-size:13px; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .row { display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end; }
  .row > div { flex:1 1 150px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(250px, 1fr)); gap:12px; }
  .card { border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
  .card h3 { margin:0 0 2px; font-size:15px; }
  .cap { color:var(--muted); font-size:12px; margin-bottom:8px; }
  .slot { display:flex; justify-content:space-between; gap:8px; font-size:13px;
          padding:3px 0; border-top:1px dashed var(--line); }
  .slot:first-of-type { border-top:none; }
  .booked { color:var(--err); }
  .free { color:var(--ok); }
  .who { color:var(--muted); font-size:12px; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { font-size:12px; text-transform:uppercase; color:var(--muted); letter-spacing:.03em; }
  .banner { padding:10px 14px; border-radius:8px; margin-bottom:14px; font-weight:600; display:none; }
  .banner.ok { display:block; background:#e7f5ec; color:var(--ok); border:1px solid #b7e0c6; }
  .banner.err { display:block; background:#fdecea; color:var(--err); border:1px solid #f5c2bd; }
  .muted { color:var(--muted); }
  .empty { color:var(--muted); font-style:italic; font-size:13px; }
  .hint { color:var(--muted); font-size:12px; margin-top:6px; }
</style>
</head>
<body>
<header>
  <h1>Meeting Room Booking</h1>
  <p>Check availability, book a room, cancel a booking. Overlapping bookings are blocked automatically.</p>
</header>
<main>
  <div id="banner" class="banner" role="status" aria-live="polite"></div>

  <section>
    <h2>1. Availability</h2>
    <div class="row" style="margin-bottom:12px">
      <div style="flex:0 0 220px">
        <label for="viewDate">Date</label>
        <input type="date" id="viewDate">
      </div>
      <div style="flex:0 0 auto">
        <button class="secondary" id="todayBtn" type="button">Today</button>
      </div>
      <div style="flex:0 0 auto">
        <a href="/api/export.csv"><button class="secondary" type="button">Download CSV</button></a>
      </div>
    </div>
    <div id="grid" class="grid"></div>
  </section>

  <section>
    <h2>2. Book a room for <span id="formDate" class="muted"></span></h2>
    <form id="bookForm">
      <div class="row">
        <div><label for="fRoom">Room</label><select id="fRoom" name="room_id" required></select></div>
        <div><label for="fDate">Date</label><input type="date" id="fDate" name="date" required></div>
        <div><label for="fStart">Start</label><input type="time" id="fStart" name="start" step="900" min="08:00" max="19:00" required></div>
        <div><label for="fEnd">End</label><input type="time" id="fEnd" name="end" step="900" min="08:00" max="19:00" required></div>
      </div>
      <div class="row" style="margin-top:12px">
        <div><label for="fBooker">Your name</label><input id="fBooker" name="booker" required maxlength="100"></div>
        <div style="flex:2 1 260px"><label for="fTitle">Title</label><input id="fTitle" name="title" required maxlength="200" placeholder="e.g. Sprint planning"></div>
        <div style="flex:0 0 150px"><label for="fRepeat">Repeat weekly</label>
          <select id="fRepeat" name="repeat_weeks">
            <option value="0">No repeat</option>
            <option value="1">+1 week</option>
            <option value="3">+3 weeks</option>
            <option value="7">+7 weeks</option>
            <option value="11">+11 weeks</option>
            <option value="25">+25 weeks</option>
            <option value="51">+51 weeks</option>
          </select>
        </div>
      </div>
      <div class="row" style="margin-top:12px">
        <div style="flex:1 1 100%"><label for="fNotes">Notes (optional)</label><textarea id="fNotes" name="notes" maxlength="2000"></textarea></div>
      </div>
      <div style="margin-top:12px"><button type="submit" id="bookBtn">Book room</button></div>
      <p class="hint">The date here always follows the availability date above, so you book the day you are looking at.</p>
    </form>
  </section>

  <section>
    <h2>3. Bookings on <span id="listDate" class="muted"></span></h2>
    <table>
      <thead><tr><th>Time</th><th>Room</th><th>Title</th><th>Booked by</th><th>Notes</th><th></th></tr></thead>
      <tbody id="bookingsBody"></tbody>
    </table>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

function todayISO() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}

function banner(msg, kind) {
  const el = $("banner");
  el.textContent = msg;
  el.className = "banner " + (kind || "ok");
  if (msg) window.scrollTo({top: 0, behavior: "smooth"});
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) throw new Error((data && data.error) || ("Request failed (" + res.status + ")"));
  return data;
}

let rooms = [];
let currentBookings = [];

async function loadRooms() {
  rooms = await api("/api/rooms");
  const sel = $("fRoom");
  sel.innerHTML = rooms.map((r) =>
    '<option value="' + r.id + '">' + esc(r.name) + " (" + r.capacity + " seats)</option>").join("");
}

// Keep the booking form's date in step with the availability date.
function syncFormDate() {
  const d = $("viewDate").value;
  $("fDate").value = d;
  $("formDate").textContent = d || "(choose a date)";
}

async function loadAvailability() {
  const date = $("viewDate").value;
  const data = await api("/api/availability?date=" + encodeURIComponent(date));
  $("grid").innerHTML = data.rooms.map((room) => {
    const booked = room.bookings.length
      ? room.bookings.map((b) =>
          '<div class="slot booked"><span>' + esc(b.start) + "&ndash;" + esc(b.end) + "</span>" +
          '<span class="who">' + esc(b.title) + " &middot; " + esc(b.booker) + "</span></div>").join("")
      : '<div class="empty">No bookings</div>';
    const free = room.free.length
      ? room.free.map((g) =>
          '<div class="slot free"><span>Free</span><span>' + esc(g.start) +
          "&ndash;" + esc(g.end) + "</span></div>").join("")
      : '<div class="empty">Fully booked</div>';
    return '<div class="card"><h3>' + esc(room.room) + "</h3>" +
      '<div class="cap">' + room.capacity + " seats</div>" + booked + free + "</div>";
  }).join("");
}

async function loadBookings() {
  const date = $("viewDate").value;
  $("listDate").textContent = date;
  const rows = await api("/api/bookings?date=" + encodeURIComponent(date));
  currentBookings = rows;
  const body = $("bookingsBody");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty">No bookings on this date.</td></tr>';
    return;
  }
  body.innerHTML = rows.map((b) =>
    "<tr><td>" + esc(b.start) + "&ndash;" + esc(b.end) + "</td><td>" + esc(b.room) +
    "</td><td>" + esc(b.title) + "</td><td>" + esc(b.booker) +
    '</td><td class="who">' + esc(b.notes) + "</td>" +
    '<td><button class="danger" data-cancel="' + b.id + '">Cancel</button></td></tr>").join("");
}

async function refresh() {
  try {
    await Promise.all([loadAvailability(), loadBookings()]);
  } catch (e) { banner(e.message, "err"); }
}

$("viewDate").addEventListener("change", () => { syncFormDate(); refresh(); });
$("todayBtn").addEventListener("click", () => {
  $("viewDate").value = todayISO();
  syncFormDate();
  refresh();
});

$("bookingsBody").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-cancel]");
  if (!btn) return;
  const id = btn.getAttribute("data-cancel");
  const b = currentBookings.find((x) => String(x.id) === String(id));
  const what = b
    ? b.room + ", " + b.date + " " + b.start + "-" + b.end + " (" + b.title + ", booked by " + b.booker + ")"
    : "booking " + id;
  if (!confirm("Cancel this booking?\n\n" + what + "\n\nThe slot becomes free again immediately.")) return;
  const who = prompt("Your name (optional, recorded with the cancellation):", "");
  if (who === null) return;
  btn.disabled = true;
  try {
    const c = await api("/api/bookings/" + id + "/cancel", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({cancelled_by: who})
    });
    banner("Cancelled: " + c.room + " " + c.start + "-" + c.end + " on " + c.date + " (" + c.title + "). The slot is free again.", "ok");
    // Refresh both the availability grid and the bookings list so the freed slot shows at once.
    await refresh();
  } catch (e) {
    banner(e.message, "err");
    btn.disabled = false;
  }
});

$("bookForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const payload = {
    room_id: Number(f.room_id.value),
    date: f.date.value,
    start: f.start.value,
    end: f.end.value,
    booker: f.booker.value,
    title: f.title.value,
    notes: f.notes.value,
    repeat_weeks: Number(f.repeat_weeks.value)
  };
  $("bookBtn").disabled = true;
  try {
    const res = await api("/api/bookings", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    const first = res.created[0];
    banner("Booked " + first.room + " " + first.start + "-" + first.end + " on " + first.date +
           (res.count > 1 ? " and " + (res.count - 1) + " more weekly booking(s)." : "."), "ok");
    $("viewDate").value = first.date;
    syncFormDate();
    f.title.value = "";
    f.notes.value = "";
    await refresh();
  } catch (e) {
    banner(e.message, "err");
  } finally {
    $("bookBtn").disabled = false;
  }
});

(async function init() {
  const t = todayISO();
  $("viewDate").value = t;
  $("fStart").value = "09:00";
  $("fEnd").value = "10:00";
  syncFormDate();
  try {
    await loadRooms();
    await refresh();
  } catch (e) { banner(e.message, "err"); }
})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "RoomBooking/1.1"

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers -----------------------------------------------------------
    def _send(self, status, body, content_type="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj))

    def _error(self, status, message):
        self._json(status, {"error": message})

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            raise ApiError(400, "Invalid Content-Length header.")
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Request body must be valid JSON.")
        if not isinstance(data, dict):
            raise ApiError(400, "Request body must be a JSON object.")
        return data

    # -- routing -----------------------------------------------------------
    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def _route(self, method):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            if method == "GET" and path in ("/", "/index.html"):
                return self._send(200, INDEX_HTML, "text/html; charset=utf-8")
            if method == "GET" and path == "/api/rooms":
                return self._json(200, list_rooms())
            if method == "GET" and path == "/api/availability":
                day = (query.get("date") or [""])[0]
                return self._json(200, availability(day))
            if method == "GET" and path == "/api/bookings":
                day = (query.get("date") or [""])[0]
                if day:
                    validate_date(day)
                room = (query.get("room") or [""])[0]
                room_id = None
                if room:
                    room_id = as_int(room, "room")
                inc = (query.get("include_cancelled") or ["0"])[0].lower() in ("1", "true", "yes")
                return self._json(200, list_bookings(day or None, room_id, inc))
            if method == "GET" and path == "/api/export.csv":
                return self._send(
                    200, export_csv(), "text/csv; charset=utf-8",
                    {"Content-Disposition": 'attachment; filename="bookings.csv"'},
                )
            if method == "POST" and path == "/api/bookings":
                return self._json(201, create_bookings(self._read_json()))
            m = re.match(r"^/api/bookings/(\d+)/cancel$", path)
            if method == "POST" and m:
                payload = self._read_json()
                return self._json(200, cancel_booking(int(m.group(1)), payload.get("cancelled_by", "")))
            if path.startswith("/api/"):
                return self._error(404, "Unknown API endpoint: %s" % path)
            return self._error(404, "Not found.")
        except ApiError as exc:
            return self._error(exc.status, exc.message)
        except Exception as exc:  # pragma: no cover - defensive
            # Never leak a traceback page: always answer with JSON.
            sys.stderr.write("Unhandled error on %s %s: %r\n" % (method, self.path, exc))
            return self._error(500, "Server error: %s" % exc)


def make_server(host="127.0.0.1", port=8000):
    return ThreadingHTTPServer((host, port), Handler)


def main():
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("Usage: python3 app.py [port]")
            return 2
    init_db()
    httpd = make_server("0.0.0.0", port)
    print("Meeting room booking running at http://localhost:%d" % port)
    print("Data file: %s" % DB_PATH)
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
