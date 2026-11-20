#!/usr/bin/env python3
"""Meeting room booking app - single file, standard library only.

Run:  python3 app.py            (serves http://localhost:8000)
      PORT=9000 python3 app.py  (custom port)
"""
import json
import os
import re
import sqlite3
import sys
import threading
from datetime import date as date_cls, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DB_PATH = os.environ.get("BOOKING_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookings.db"))
PORT = int(os.environ.get("PORT", "8000"))

OPEN_HOUR = 8
CLOSE_HOUR = 18
SLOT_MINUTES = 30
MAX_BOOKING_MINUTES = 4 * 60

DEFAULT_ROOMS = [("Aurora", 8), ("Birch", 4), ("Cedar", 12), ("Dune", 20)]

_lock = threading.Lock()


# ---------------------------------------------------------------- database
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS rooms (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT NOT NULL UNIQUE,
                   capacity INTEGER NOT NULL)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS bookings (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   room_id INTEGER NOT NULL REFERENCES rooms(id),
                   date TEXT NOT NULL,
                   start TEXT NOT NULL,
                   end TEXT NOT NULL,
                   booker TEXT NOT NULL,
                   title TEXT NOT NULL DEFAULT '',
                   status TEXT NOT NULL DEFAULT 'active',
                   created_at TEXT NOT NULL)"""
        )
        # One active booking per (room, date, start) makes double booking
        # impossible at the storage level; cancelled rows are excluded.
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS ux_active_slot
                   ON bookings(room_id, date, start) WHERE status = 'active'"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_bookings_date ON bookings(date)")
        if conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0:
            conn.executemany("INSERT INTO rooms(name, capacity) VALUES (?, ?)", DEFAULT_ROOMS)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------- helpers
def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def hhmm(mins):
    return "%02d:%02d" % (mins // 60, mins % 60)


def all_slots():
    out = []
    t = OPEN_HOUR * 60
    while t < CLOSE_HOUR * 60:
        out.append(hhmm(t))
        t += SLOT_MINUTES
    return out


SLOTS = all_slots()
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ApiError(400, "date must be in YYYY-MM-DD format")
    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        raise ApiError(400, "date is not a valid calendar date")


def parse_time(value, field):
    if not isinstance(value, str) or not TIME_RE.match(value):
        raise ApiError(400, "%s must be in HH:MM format" % field)
    m = minutes(value)
    if m % SLOT_MINUTES:
        raise ApiError(400, "%s must be on a %d-minute boundary" % (field, SLOT_MINUTES))
    return m


def room_rows(conn):
    return [dict(r) for r in conn.execute("SELECT id, name, capacity FROM rooms ORDER BY id")]


def booking_dict(row):
    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "room": row["room_name"] if "room_name" in row.keys() else None,
        "date": row["date"],
        "start": row["start"],
        "end": row["end"],
        "booker": row["booker"],
        "title": row["title"],
        "status": row["status"],
    }


BOOKING_SELECT = (
    "SELECT b.id, b.room_id, r.name AS room_name, b.date, b.start, b.end, "
    "b.booker, b.title, b.status FROM bookings b JOIN rooms r ON r.id = b.room_id"
)


def active_bookings_for(conn, day):
    return [
        dict(r)
        for r in conn.execute(
            BOOKING_SELECT + " WHERE b.date = ? AND b.status = 'active' ORDER BY b.start, b.room_id",
            (day,),
        )
    ]


def busy_slots(bookings):
    busy = set()
    for b in bookings:
        t = minutes(b["start"])
        end = minutes(b["end"])
        while t < end:
            busy.add(hhmm(t))
            t += SLOT_MINUTES
    return busy


# ---------------------------------------------------------------- API
def api_rooms():
    conn = connect()
    try:
        return 200, {"rooms": room_rows(conn)}
    finally:
        conn.close()


def api_availability(query):
    day = parse_date((query.get("date") or [""])[0])
    conn = connect()
    try:
        rooms = room_rows(conn)
        bookings = active_bookings_for(conn, day.isoformat())
        result = []
        for room in rooms:
            busy = busy_slots([b for b in bookings if b["room_id"] == room["id"]])
            slots = [
                {"start": s, "end": hhmm(minutes(s) + SLOT_MINUTES),
                 "status": "busy" if s in busy else "free"}
                for s in SLOTS
            ]
            result.append({
                "room_id": room["id"],
                "room": room["name"],
                "capacity": room["capacity"],
                "slots": slots,
                "free_count": sum(1 for s in slots if s["status"] == "free"),
            })
        return 200, {"date": day.isoformat(), "slots": SLOTS, "rooms": result}
    finally:
        conn.close()


def api_bookings(query):
    day = parse_date((query.get("date") or [""])[0])
    conn = connect()
    try:
        rows = conn.execute(
            BOOKING_SELECT + " WHERE b.date = ? ORDER BY b.start, b.room_id", (day.isoformat(),)
        ).fetchall()
        return 200, {"date": day.isoformat(), "bookings": [booking_dict(r) for r in rows]}
    finally:
        conn.close()


def validate_booking(payload):
    if not isinstance(payload, dict):
        raise ApiError(400, "request body must be a JSON object")
    try:
        room_id = int(payload.get("room_id"))
    except (TypeError, ValueError):
        raise ApiError(400, "room_id is required and must be an integer")
    day = parse_date(payload.get("date"))
    start = parse_time(payload.get("start"), "start")
    end = parse_time(payload.get("end"), "end")
    booker = (payload.get("booker") or "").strip() if isinstance(payload.get("booker"), str) else ""
    title = payload.get("title") or ""
    if not isinstance(title, str):
        raise ApiError(400, "title must be text")
    title = title.strip()
    if not booker:
        raise ApiError(400, "booker name is required")
    if len(booker) > 80:
        raise ApiError(400, "booker name is too long (max 80 characters)")
    if len(title) > 120:
        raise ApiError(400, "title is too long (max 120 characters)")
    if end <= start:
        raise ApiError(400, "end time must be after start time")
    if start < OPEN_HOUR * 60 or end > CLOSE_HOUR * 60:
        raise ApiError(400, "bookings must be within %s-%s" % (hhmm(OPEN_HOUR * 60), hhmm(CLOSE_HOUR * 60)))
    if end - start > MAX_BOOKING_MINUTES:
        raise ApiError(400, "bookings may be at most 4 hours long")
    today = date_cls.today()
    if day < today:
        raise ApiError(400, "cannot book in the past")
    if day == today and start <= datetime.now().hour * 60 + datetime.now().minute:
        raise ApiError(400, "cannot book a slot that has already started")
    return room_id, day.isoformat(), hhmm(start), hhmm(end), booker, title


def api_create_booking(payload):
    room_id, day, start, end, booker, title = validate_booking(payload)
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")  # serialise writers: atomic check + insert
        room = conn.execute("SELECT id, name FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if room is None:
            raise ApiError(400, "unknown room_id %s" % room_id)
        clash = conn.execute(
            """SELECT id, start, end, booker, title FROM bookings
               WHERE room_id = ? AND date = ? AND status = 'active'
                 AND start < ? AND end > ?""",
            (room_id, day, end, start),
        ).fetchone()
        if clash is not None:
            raise ApiError(
                409,
                "%s is already booked %s-%s on %s by %s%s. Please pick another slot."
                % (room["name"], clash["start"], clash["end"], day, clash["booker"],
                   (" (%s)" % clash["title"]) if clash["title"] else ""),
            )
        try:
            cur = conn.execute(
                """INSERT INTO bookings(room_id, date, start, end, booker, title, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', ?)""",
                (room_id, day, start, end, booker, title, datetime.now().isoformat(timespec="seconds")),
            )
        except sqlite3.IntegrityError:
            raise ApiError(409, "That slot was just booked by someone else. Please pick another slot.")
        conn.execute("COMMIT")
        row = conn.execute(BOOKING_SELECT + " WHERE b.id = ?", (cur.lastrowid,)).fetchone()
        return 201, {"booking": booking_dict(row)}
    except ApiError:
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def api_cancel_booking(booking_id):
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(BOOKING_SELECT + " WHERE b.id = ?", (booking_id,)).fetchone()
        if row is None:
            raise ApiError(404, "booking %s not found" % booking_id)
        if row["status"] == "cancelled":
            raise ApiError(409, "booking %s is already cancelled" % booking_id)
        conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        conn.execute("COMMIT")
        row = conn.execute(BOOKING_SELECT + " WHERE b.id = ?", (booking_id,)).fetchone()
        return 200, {"booking": booking_dict(row)}
    except ApiError:
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "RoomBook/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status, message):
        self._send(status, {"error": message})

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "request body must be valid JSON")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if path == "/" or path == "/index.html":
                self._send(200, PAGE.encode("utf-8"), "text/html")
            elif path == "/api/rooms":
                self._send(*api_rooms())
            elif path == "/api/availability":
                self._send(*api_availability(query))
            elif path == "/api/bookings":
                self._send(*api_bookings(query))
            elif path == "/health":
                self._send(200, {"ok": True})
            else:
                self._error(404, "not found")
        except ApiError as e:
            self._error(e.status, e.message)
        except Exception as e:  # pragma: no cover
            self._error(500, "internal error: %s" % e)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path == "/api/bookings":
                self._send(*api_create_booking(self._read_json()))
                return
            m = re.match(r"^/api/bookings/(\d+)/cancel$", path)
            if m:
                self._send(*api_cancel_booking(int(m.group(1))))
                return
            self._error(404, "not found")
        except ApiError as e:
            self._error(e.status, e.message)
        except Exception as e:  # pragma: no cover
            self._error(500, "internal error: %s" % e)


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meeting Room Booking</title>
<style>
  :root { --line:#d8dee6; --free:#e8f6ec; --free-b:#9fd3ae; --busy:#fbe4e4; --busy-b:#e6a3a3;
          --accent:#2f6feb; --ink:#1d2430; --muted:#6b7684; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; color:var(--ink); background:#f5f7fa; }
  header { background:#fff; border-bottom:1px solid var(--line); padding:12px 20px; display:flex; gap:16px; align-items:center; flex-wrap:wrap; }
  h1 { font-size:17px; margin:0; }
  main { padding:16px 20px 40px; max-width:1180px; margin:0 auto; }
  .card { background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin-bottom:16px; }
  .card h2 { font-size:14px; margin:0 0 10px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
  label { display:block; font-size:12px; color:var(--muted); margin-bottom:3px; }
  input, select, button { font:inherit; }
  input, select { padding:6px 8px; border:1px solid var(--line); border-radius:6px; background:#fff; color:var(--ink); }
  button { padding:7px 14px; border-radius:6px; border:1px solid var(--accent); background:var(--accent); color:#fff; cursor:pointer; }
  button.secondary { background:#fff; color:var(--accent); }
  button.danger { background:#fff; color:#b42318; border-color:#e6a3a3; padding:3px 10px; font-size:12px; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .row { display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end; }
  .grid-wrap { overflow-x:auto; }
  table.grid { border-collapse:collapse; width:100%; min-width:760px; }
  table.grid th, table.grid td { border:1px solid var(--line); padding:0; text-align:center; font-size:11px; }
  table.grid th { background:#f0f3f7; padding:5px 2px; font-weight:600; color:var(--muted); }
  table.grid th.room, table.grid td.room { text-align:left; padding:6px 10px; font-size:13px; white-space:nowrap; background:#fafbfc; }
  table.grid td.room small { color:var(--muted); }
  td.slot { height:30px; cursor:pointer; }
  td.slot.free { background:var(--free); }
  td.slot.free:hover { background:var(--free-b); }
  td.slot.busy { background:var(--busy); cursor:not-allowed; }
  td.slot.past { background:#eef0f3; cursor:not-allowed; }
  .legend { display:flex; gap:14px; font-size:12px; color:var(--muted); margin-top:8px; }
  .sw { display:inline-block; width:12px; height:12px; border-radius:3px; vertical-align:-2px; margin-right:4px; border:1px solid var(--line); }
  #msg { padding:8px 12px; border-radius:6px; margin-bottom:12px; display:none; font-size:13px; }
  #msg.ok { display:block; background:#e8f6ec; border:1px solid var(--free-b); }
  #msg.err { display:block; background:#fbe4e4; border:1px solid var(--busy-b); }
  table.list { border-collapse:collapse; width:100%; }
  table.list th, table.list td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); font-size:13px; }
  table.list th { font-size:11px; text-transform:uppercase; color:var(--muted); letter-spacing:.04em; }
  tr.cancelled td { color:var(--muted); text-decoration:line-through; }
  tr.cancelled td:last-child { text-decoration:none; }
  .pill { font-size:11px; padding:1px 7px; border-radius:10px; background:#eef0f3; color:var(--muted); }
  .pill.active { background:#e8f6ec; color:#1f7a3d; }
  .empty { color:var(--muted); font-size:13px; }
  .two { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:820px) { .two { grid-template-columns:1fr; } }
</style>
</head>
<body>
<header>
  <h1>Meeting Room Booking</h1>
  <div class="row">
    <div><label for="date">Date</label><input type="date" id="date"></div>
    <button class="secondary" id="today">Today</button>
    <button class="secondary" id="next">Next day &rsaquo;</button>
  </div>
</header>
<main>
  <div id="msg"></div>

  <section class="card">
    <h2>Availability &mdash; click a green slot to book</h2>
    <div class="grid-wrap"><table class="grid" id="grid"></table></div>
    <div class="legend">
      <span><span class="sw" style="background:var(--free)"></span>free</span>
      <span><span class="sw" style="background:var(--busy)"></span>booked</span>
      <span><span class="sw" style="background:#eef0f3"></span>past / closed</span>
    </div>
  </section>

  <div class="two">
    <section class="card">
      <h2>Book a room</h2>
      <form id="form">
        <div class="row" style="margin-bottom:10px">
          <div><label for="room">Room</label><select id="room"></select></div>
          <div><label for="start">Start</label><select id="start"></select></div>
          <div><label for="end">End</label><select id="end"></select></div>
        </div>
        <div class="row" style="margin-bottom:10px">
          <div style="flex:1"><label for="booker">Your name *</label><input id="booker" required maxlength="80" placeholder="e.g. Sam Rivera"></div>
          <div style="flex:1"><label for="title">Title (optional)</label><input id="title" maxlength="120" placeholder="e.g. Sprint planning"></div>
        </div>
        <button type="submit" id="submit">Book room</button>
        <span class="empty" id="formhint" style="margin-left:8px">Max 4 hours, 08:00&ndash;18:00.</span>
      </form>
    </section>

    <section class="card">
      <h2>Bookings on <span id="listdate"></span></h2>
      <table class="list" id="list"></table>
      <div class="empty" id="listempty" style="display:none">No bookings for this day.</div>
    </section>
  </div>
</main>
<script>
const $ = id => document.getElementById(id);
let rooms = [], slots = [], avail = {};

function todayStr() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}
function nowHHMM() {
  const d = new Date();
  return String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}
function flash(text, ok) {
  const m = $('msg');
  m.textContent = text;
  m.className = ok ? 'ok' : 'err';
  clearTimeout(flash.t);
  flash.t = setTimeout(() => { m.className = ''; m.textContent = ''; }, 6000);
}
async function api(path, opts) {
  const res = await fetch(path, opts);
  let body = {};
  try { body = await res.json(); } catch (e) {}
  if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
  return body;
}

function fillSelects() {
  $('room').innerHTML = rooms.map(r =>
    `<option value="${r.id}">${r.name} (${r.capacity} seats)</option>`).join('');
  const opts = slots.map(s => `<option value="${s}">${s}</option>`).join('');
  $('start').innerHTML = opts;
  $('end').innerHTML = opts;
  $('start').value = slots[0];
  $('end').value = slots[1] || slots[0];
}

function renderGrid() {
  const d = $('date').value;
  const isToday = d === todayStr();
  const now = nowHHMM();
  let html = '<tr><th class="room">Room</th>' +
    slots.map(s => `<th>${s}</th>`).join('') + '</tr>';
  for (const room of avail.rooms || []) {
    html += `<tr><td class="room">${room.room}<br><small>${room.capacity} seats &middot; ${room.free_count} free</small></td>`;
    for (const slot of room.slots) {
      const past = isToday && slot.start < now;
      const cls = slot.status === 'busy' ? 'busy' : (past ? 'past' : 'free');
      const title = slot.status === 'busy' ? 'Booked' : (past ? 'Past' : 'Free - click to book');
      html += `<td class="slot ${cls}" data-room="${room.room_id}" data-start="${slot.start}" title="${title}"></td>`;
    }
    html += '</tr>';
  }
  $('grid').innerHTML = html;
  $('grid').querySelectorAll('td.slot.free').forEach(td => {
    td.addEventListener('click', () => {
      $('room').value = td.dataset.room;
      $('start').value = td.dataset.start;
      const i = slots.indexOf(td.dataset.start);
      $('end').value = slots[Math.min(i + 2, slots.length - 1)];
      $('booker').focus();
      $('form').scrollIntoView({behavior:'smooth', block:'center'});
    });
  });
}

function renderList(data) {
  $('listdate').textContent = data.date;
  const rows = data.bookings || [];
  $('listempty').style.display = rows.length ? 'none' : 'block';
  let html = '<tr><th>Time</th><th>Room</th><th>Booker</th><th>Title</th><th></th></tr>';
  for (const b of rows) {
    const cancelled = b.status === 'cancelled';
    html += `<tr class="${cancelled ? 'cancelled' : ''}">
      <td>${b.start}&ndash;${b.end}</td>
      <td>${b.room}</td>
      <td>${esc(b.booker)}</td>
      <td>${esc(b.title) || '<span class="empty">&mdash;</span>'}</td>
      <td>${cancelled
        ? '<span class="pill">cancelled</span>'
        : `<span class="pill active">booked</span> <button class="danger" data-id="${b.id}">Cancel</button>`}</td>
    </tr>`;
  }
  $('list').innerHTML = html;
  $('list').querySelectorAll('button.danger').forEach(btn => {
    btn.addEventListener('click', () => cancelBooking(btn.dataset.id));
  });
}
function esc(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function load() {
  const d = $('date').value;
  try {
    const [a, b] = await Promise.all([
      api('/api/availability?date=' + d),
      api('/api/bookings?date=' + d)
    ]);
    avail = a;
    renderGrid();
    renderList(b);
  } catch (e) { flash(e.message, false); }
}

async function cancelBooking(id) {
  if (!confirm('Cancel this booking?')) return;
  try {
    const r = await api('/api/bookings/' + id + '/cancel', {method:'POST'});
    flash('Cancelled ' + r.booking.room + ' ' + r.booking.start + '-' + r.booking.end + '. Slot is free again.', true);
    await load();
  } catch (e) { flash(e.message, false); await load(); }
}

$('form').addEventListener('submit', async ev => {
  ev.preventDefault();
  const payload = {
    room_id: Number($('room').value),
    date: $('date').value,
    start: $('start').value,
    end: $('end').value,
    booker: $('booker').value.trim(),
    title: $('title').value.trim()
  };
  if (!payload.booker) { flash('Please enter your name.', false); return; }
  $('submit').disabled = true;
  try {
    const r = await api('/api/bookings', {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)
    });
    flash('Booked ' + r.booking.room + ' on ' + r.booking.date + ' ' + r.booking.start + '-' + r.booking.end + '.', true);
    $('title').value = '';
    await load();
  } catch (e) {
    flash(e.message, false);
    await load();
  } finally { $('submit').disabled = false; }
});

$('date').addEventListener('change', load);
$('today').addEventListener('click', () => { $('date').value = todayStr(); load(); });
$('next').addEventListener('click', () => {
  const d = new Date($('date').value + 'T12:00:00');
  d.setDate(d.getDate() + 1);
  $('date').value = d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
  load();
});

(async function init() {
  $('date').value = todayStr();
  try {
    const r = await api('/api/rooms');
    rooms = r.rooms;
    const a = await api('/api/availability?date=' + $('date').value);
    slots = a.slots;
    fillSelects();
    await load();
  } catch (e) { flash(e.message, false); }
})();
</script>
</body>
</html>
"""


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("Meeting room booking running at http://localhost:%d  (Ctrl+C to stop)" % PORT)
    print("Database: %s" % DB_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
