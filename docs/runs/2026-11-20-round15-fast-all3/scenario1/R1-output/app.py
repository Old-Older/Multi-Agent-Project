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
    UNIQUE (room_id, date, start)
);
CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date);
"""


# ---------------------------------------------------------------- helpers
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()
    try:
        conn.executescript(SCHEMA)
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
    }


SELECT_BOOKINGS = """
SELECT b.id, b.room_id, r.name AS room_name, b.date, b.start, b.end, b.booker
FROM bookings b JOIN rooms r ON r.id = b.room_id
"""


# ---------------------------------------------------------------- core logic
def list_rooms():
    conn = connect()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name, capacity FROM rooms ORDER BY id")]
    finally:
        conn.close()


def list_bookings(day=None, room_id=None, booker=None, upcoming=False):
    conn = connect()
    try:
        sql, args = SELECT_BOOKINGS + " WHERE 1=1", []
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
            "SELECT id FROM bookings WHERE room_id = ? AND date = ? AND start < ? AND end > ?",
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
    """Delete a booking if the name matches (or is an admin). Returns True if deleted."""
    if not isinstance(booker, str) or not booker.strip():
        raise ValueError("booker name is required to cancel")
    booker = booker.strip()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id, booker FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return None  # not found
        if row["booker"].lower() != booker.lower() and booker.lower() not in ADMIN_NAMES:
            conn.execute("ROLLBACK")
            raise PermissionError("only the booker or an admin can cancel this booking")
        conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
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
  <p>Pick a date, click a free slot to book it, and cancel your own bookings from the grid or the "My bookings" list.</p>
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
