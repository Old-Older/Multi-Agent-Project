#!/usr/bin/env python3
"""Meeting room booking system - single-file web app, standard library only.

Run:  python3 booking_app.py      ->  http://localhost:8000
Data: bookings.json next to this script (created with seed data on first run).
"""

import json
import os
import re
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "0.0.0.0"
PORT = 8000
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookings.json")

# --- Configuration -----------------------------------------------------------
ROOMS = [
    {"id": "aurora", "name": "Aurora", "capacity": 8},
    {"id": "birch", "name": "Birch", "capacity": 4},
    {"id": "cedar", "name": "Cedar", "capacity": 12},
    {"id": "den", "name": "Den", "capacity": 20},
]
ROOM_BY_ID = {r["id"]: r for r in ROOMS}
OPEN_MIN = 8 * 60          # 08:00
CLOSE_MIN = 18 * 60        # 18:00
SLOT_MIN = 30              # 30-minute slots
MAX_DURATION_MIN = 4 * 60  # max 4 hours per booking

# One lock guards every read-modify-write of the JSON file, so concurrent
# requests can never double-book the same slot.
LOCK = threading.RLock()


# --- Time helpers ------------------------------------------------------------
def parse_date(s):
    """Return a date object for 'YYYY-MM-DD' or raise ValueError."""
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError("Date must be in YYYY-MM-DD format.")
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_time(s):
    """Return minutes since midnight for 'HH:MM' or raise ValueError."""
    if not isinstance(s, str) or not re.fullmatch(r"\d{2}:\d{2}", s):
        raise ValueError("Time must be in HH:MM format.")
    h, m = int(s[:2]), int(s[3:])
    if h > 23 or m > 59:
        raise ValueError("Time must be in HH:MM format.")
    return h * 60 + m


def fmt_time(minutes):
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def parse_duration(v):
    """Duration in minutes: integer number of minutes, or 'HH:MM'."""
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        v = v.strip()
        if re.fullmatch(r"\d+", v):
            return int(v)
        if re.fullmatch(r"\d{1,2}:\d{2}", v):
            return parse_time(v.zfill(5))
    raise ValueError("Duration must be a number of minutes (e.g. 60) or HH:MM.")


# --- Storage -----------------------------------------------------------------
def _seed():
    """Example bookings for today and tomorrow (only used on first run)."""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    return {
        "next_id": 4,
        "bookings": [
            {"id": 1, "room": "aurora", "date": today.isoformat(), "start": "09:00",
             "end": "10:00", "name": "Priya", "title": "Sprint planning"},
            {"id": 2, "room": "cedar", "date": today.isoformat(), "start": "13:30",
             "end": "15:00", "name": "Marco", "title": "Design review"},
            {"id": 3, "room": "birch", "date": tomorrow.isoformat(), "start": "10:00",
             "end": "11:00", "name": "Sam", "title": "1:1 catch-up"},
        ],
    }


def load_data():
    """Read the JSON file (caller must hold LOCK). Creates seed data if missing."""
    if not os.path.exists(DATA_FILE):
        data = _seed()
        save_data(data)
        return data
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("bookings", [])
    data.setdefault("next_id", 1)
    return data


def save_data(data):
    """Write atomically so a crash cannot leave a half-written file."""
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, DATA_FILE)


# --- Domain logic ------------------------------------------------------------
def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def validate_booking(data, room, day, start_min, duration_min, name, title):
    """Return (booking_dict, None) or (None, error_message)."""
    if room not in ROOM_BY_ID:
        return None, "Unknown room '%s'. Valid rooms: %s" % (
            room, ", ".join(r["id"] for r in ROOMS))
    if not name or not name.strip():
        return None, "Please enter your name."
    if not title or not title.strip():
        return None, "Please enter a title for the meeting."
    if duration_min <= 0:
        return None, "Duration must be greater than zero."
    if duration_min > MAX_DURATION_MIN:
        return None, "Bookings are limited to 4 hours (240 minutes)."
    if duration_min % SLOT_MIN != 0:
        return None, "Duration must be a multiple of 30 minutes."
    if start_min % SLOT_MIN != 0:
        return None, "Start time must be on a 30-minute boundary (e.g. 09:00 or 09:30)."
    end_min = start_min + duration_min
    if start_min < OPEN_MIN or end_min > CLOSE_MIN:
        return None, "Bookings must be within opening hours 08:00-18:00."
    if day < date.today():
        return None, "You cannot book a room in the past."
    if day == date.today() and end_min <= _now_minutes():
        return None, "That time has already passed today."

    for b in data["bookings"]:
        if b["room"] != room or b["date"] != day.isoformat():
            continue
        b_start = parse_time(b["start"])
        b_end = parse_time(b["end"])
        if overlaps(start_min, end_min, b_start, b_end):
            return None, ("%s is already booked %s-%s on %s by %s (%s). "
                          "Please pick another time or room." % (
                              ROOM_BY_ID[room]["name"], b["start"], b["end"],
                              b["date"], b["name"], b["title"]))

    booking = {
        "id": data["next_id"],
        "room": room,
        "date": day.isoformat(),
        "start": fmt_time(start_min),
        "end": fmt_time(end_min),
        "name": name.strip(),
        "title": title.strip(),
    }
    return booking, None


def _now_minutes():
    n = datetime.now()
    return n.hour * 60 + n.minute


def free_rooms(data, day, start_min, duration_min, capacity):
    """List rooms with no overlapping booking for the requested window."""
    end_min = start_min + duration_min
    result = []
    for room in ROOMS:
        if capacity and room["capacity"] < capacity:
            continue
        busy = False
        for b in data["bookings"]:
            if b["room"] != room["id"] or b["date"] != day.isoformat():
                continue
            if overlaps(start_min, end_min, parse_time(b["start"]), parse_time(b["end"])):
                busy = True
                break
        result.append({"id": room["id"], "name": room["name"],
                       "capacity": room["capacity"], "free": not busy})
    return result


# --- HTTP handler ------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "BookingApp/1.0"

    def log_message(self, fmt, *args):  # quieter console
        print("%s - %s" % (self.address_string(), fmt % args))

    # helpers
    def _send(self, code, body, ctype="application/json"):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _error(self, code, message):
        self._json(code, {"error": message})

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Request body must be valid JSON.")

    # routes
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            if path in ("/", "/index.html"):
                return self._send(200, INDEX_HTML, "text/html")
            if path == "/api/rooms":
                return self._json(200, {"rooms": ROOMS, "open": "08:00",
                                        "close": "18:00", "slot_minutes": SLOT_MIN,
                                        "max_duration_minutes": MAX_DURATION_MIN})
            if path == "/api/bookings":
                return self._get_bookings(q)
            if path == "/api/availability":
                return self._get_availability(q)
            return self._error(404, "Not found")
        except ValueError as e:
            return self._error(400, str(e))
        except Exception as e:  # pragma: no cover - defensive
            return self._error(500, "Server error: %s" % e)

    def _get_bookings(self, q):
        with LOCK:
            data = load_data()
            bookings = list(data["bookings"])
        if q.get("date"):
            day = parse_date(q["date"]).isoformat()
            bookings = [b for b in bookings if b["date"] == day]
        elif q.get("upcoming", "1") not in ("0", "false"):
            today = date.today().isoformat()
            now = fmt_time(_now_minutes())
            bookings = [b for b in bookings
                        if b["date"] > today or (b["date"] == today and b["end"] > now)]
        bookings.sort(key=lambda b: (b["date"], b["start"], b["room"]))
        return self._json(200, {"bookings": bookings})

    def _get_availability(self, q):
        day = parse_date(q.get("date") or date.today().isoformat())
        start_min = parse_time(q.get("start") or "09:00")
        duration = parse_duration(q.get("duration") or 60)
        capacity = int(q.get("capacity") or 0)
        if duration <= 0 or duration % SLOT_MIN:
            raise ValueError("Duration must be a positive multiple of 30 minutes.")
        if start_min % SLOT_MIN:
            raise ValueError("Start time must be on a 30-minute boundary.")
        with LOCK:
            data = load_data()
            rooms = free_rooms(data, day, start_min, duration, capacity)
        return self._json(200, {"date": day.isoformat(), "start": fmt_time(start_min),
                                "end": fmt_time(start_min + duration),
                                "duration": duration, "rooms": rooms})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        if path != "/api/bookings":
            return self._error(404, "Not found")
        try:
            body = self._body()
            room = str(body.get("room", "")).strip().lower()
            day = parse_date(body.get("date"))
            start_min = parse_time(body.get("start"))
            duration = parse_duration(body.get("duration", 60))
            name = body.get("name", "")
            title = body.get("title", "")
        except ValueError as e:
            return self._error(400, str(e))
        with LOCK:  # read-modify-write under one lock: no double bookings
            data = load_data()
            booking, err = validate_booking(data, room, day, start_min, duration,
                                            name, title)
            if err:
                code = 409 if "already booked" in err else 400
                return self._error(code, err)
            data["bookings"].append(booking)
            data["next_id"] = booking["id"] + 1
            save_data(data)
        return self._json(201, {"booking": booking})

    def do_DELETE(self):
        path = urlparse(self.path).path.rstrip("/")
        m = re.fullmatch(r"/api/bookings/(\d+)", path)
        if not m:
            return self._error(404, "Not found")
        bid = int(m.group(1))
        with LOCK:
            data = load_data()
            remaining = [b for b in data["bookings"] if b["id"] != bid]
            if len(remaining) == len(data["bookings"]):
                return self._error(404, "Booking %d not found." % bid)
            data["bookings"] = remaining
            save_data(data)
        return self._json(200, {"deleted": bid})


# --- Front-end (inline HTML/CSS/JS, no external dependencies) ----------------
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meeting Room Booking</title>
<style>
  :root { --bg:#f5f7fa; --card:#fff; --line:#dde3ea; --ink:#1f2933; --muted:#66727f;
          --accent:#2563eb; --free:#e8f7ee; --freeb:#b7e4c7; --busy:#fdecec; --busyb:#f5b5b5; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         background:var(--bg); color:var(--ink); font-size:15px; }
  header { background:var(--accent); color:#fff; padding:14px 18px; }
  header h1 { margin:0; font-size:19px; font-weight:600; }
  header p { margin:4px 0 0; font-size:13px; opacity:.9; }
  main { max-width:1100px; margin:0 auto; padding:16px; display:grid; gap:16px; }
  section { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; }
  h2 { margin:0 0 10px; font-size:16px; }
  label { display:block; font-size:12px; color:var(--muted); margin-bottom:3px; }
  input, select, button { font:inherit; }
  input, select { width:100%; padding:7px 8px; border:1px solid var(--line);
                  border-radius:7px; background:#fff; color:var(--ink); }
  button { padding:8px 14px; border:0; border-radius:7px; background:var(--accent);
           color:#fff; cursor:pointer; font-weight:600; }
  button.secondary { background:#e6ebf2; color:var(--ink); }
  button.danger { background:#dc2626; padding:5px 10px; font-size:13px; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .row { display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; }
  .row > div { flex:1 1 130px; min-width:110px; }
  .msg { margin-top:10px; padding:9px 11px; border-radius:7px; font-size:14px; display:none; }
  .msg.ok { display:block; background:var(--free); border:1px solid var(--freeb); }
  .msg.err { display:block; background:var(--busy); border:1px solid var(--busyb); }
  .grid-wrap { overflow-x:auto; }
  table { border-collapse:collapse; width:100%; min-width:560px; font-size:13px; }
  th, td { border:1px solid var(--line); padding:4px 6px; text-align:left; vertical-align:top; }
  th { background:#f0f3f7; font-weight:600; }
  td.slot { white-space:nowrap; color:var(--muted); width:64px; }
  .cell { border-radius:5px; padding:3px 5px; min-height:22px; cursor:pointer; }
  .cell.free { background:var(--free); border:1px solid var(--freeb); color:#1b6b3a; }
  .cell.busy { background:var(--busy); border:1px solid var(--busyb); color:#8a1c1c; }
  .cell b { display:block; font-weight:600; }
  .cell small { color:inherit; opacity:.85; }
  ul.bookings { list-style:none; margin:0; padding:0; display:grid; gap:8px; }
  ul.bookings li { border:1px solid var(--line); border-radius:8px; padding:9px 11px;
                   display:flex; gap:10px; align-items:center; justify-content:space-between;
                   flex-wrap:wrap; }
  .who { font-size:13px; color:var(--muted); }
  .pill { display:inline-block; background:#eef2f7; border-radius:20px; padding:1px 8px;
          font-size:12px; color:var(--muted); }
  .hint { font-size:12px; color:var(--muted); margin-top:6px; }
  @media (max-width:600px) { main { padding:10px; } section { padding:11px; } }
</style>
</head>
<body>
<header>
  <h1>Meeting Room Booking</h1>
  <p>Check availability, book a room, cancel a booking. Hours 08:00&ndash;18:00, 30-minute slots, max 4 hours.</p>
</header>
<main>

  <!-- 1. Availability -->
  <section>
    <h2>1. Availability</h2>
    <div class="row">
      <div><label for="avDate">Date</label><input type="date" id="avDate"></div>
      <div><button id="avToday" class="secondary">Today</button></div>
      <div><button id="avTomorrow" class="secondary">Tomorrow</button></div>
    </div>
    <div class="grid-wrap" style="margin-top:12px"><table id="grid"></table></div>
    <p class="hint">Green = free (click to book), red = booked (shows who and what).</p>
  </section>

  <!-- 2. Find a free room -->
  <section>
    <h2>2. Find a free room</h2>
    <div class="row">
      <div><label for="fDate">Date</label><input type="date" id="fDate"></div>
      <div><label for="fStart">Start</label><input type="time" id="fStart" step="1800" value="09:00"></div>
      <div><label for="fDur">Duration</label>
        <select id="fDur">
          <option value="30">30 min</option><option value="60" selected>1 hour</option>
          <option value="90">1.5 hours</option><option value="120">2 hours</option>
          <option value="180">3 hours</option><option value="240">4 hours</option>
        </select></div>
      <div><label for="fCap">Min capacity</label><input type="number" id="fCap" min="0" value="0"></div>
      <div><button id="fGo">Find rooms</button></div>
    </div>
    <div id="fResult" class="msg"></div>
  </section>

  <!-- 3. Book -->
  <section>
    <h2>3. Book a room</h2>
    <div class="row">
      <div><label for="bRoom">Room</label><select id="bRoom"></select></div>
      <div><label for="bDate">Date</label><input type="date" id="bDate"></div>
      <div><label for="bStart">Start</label><input type="time" id="bStart" step="1800" value="09:00"></div>
      <div><label for="bDur">Duration</label>
        <select id="bDur">
          <option value="30">30 min</option><option value="60" selected>1 hour</option>
          <option value="90">1.5 hours</option><option value="120">2 hours</option>
          <option value="180">3 hours</option><option value="240">4 hours</option>
        </select></div>
    </div>
    <div class="row" style="margin-top:10px">
      <div><label for="bName">Your name</label><input type="text" id="bName" placeholder="e.g. Alex"></div>
      <div style="flex:2 1 220px"><label for="bTitle">Title</label><input type="text" id="bTitle" placeholder="e.g. Weekly sync"></div>
      <div><button id="bGo">Book</button></div>
    </div>
    <div id="bMsg" class="msg"></div>
  </section>

  <!-- 4. Bookings + cancel -->
  <section>
    <h2>4. Bookings</h2>
    <div class="row">
      <div><label for="lDate">Date</label><input type="date" id="lDate"></div>
      <div><button id="lGo">Show this date</button></div>
      <div><button id="lUpcoming" class="secondary">All upcoming</button></div>
    </div>
    <ul class="bookings" id="list" style="margin-top:12px"></ul>
    <div id="lMsg" class="msg"></div>
  </section>

</main>
<script>
const $ = id => document.getElementById(id);
const todayISO = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
                         return d.toISOString().slice(0,10); };
const addDays = (iso, n) => { const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate()+n);
                              return d.toISOString().slice(0,10); };
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let ROOMS = [], OPEN = "08:00", CLOSE = "18:00", SLOT = 30;

function show(el, text, ok) { el.className = "msg " + (ok ? "ok" : "err"); el.innerHTML = text; }
function hide(el) { el.className = "msg"; el.innerHTML = ""; }

async function api(path, opts) {
  const r = await fetch(path, opts);
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(data.error || ("Request failed (" + r.status + ")"));
  return data;
}

function toMin(t) { return parseInt(t.slice(0,2),10)*60 + parseInt(t.slice(3,5),10); }
function toHHMM(m) { return String(Math.floor(m/60)).padStart(2,"0") + ":" + String(m%60).padStart(2,"0"); }

async function loadRooms() {
  const d = await api("/api/rooms");
  ROOMS = d.rooms; OPEN = d.open; CLOSE = d.close; SLOT = d.slot_minutes;
  $("bRoom").innerHTML = ROOMS.map(r =>
    `<option value="${r.id}">${esc(r.name)} (cap ${r.capacity})</option>`).join("");
}

async function renderGrid() {
  const day = $("avDate").value;
  const { bookings } = await api("/api/bookings?date=" + day);
  const slots = [];
  for (let m = toMin(OPEN); m < toMin(CLOSE); m += SLOT) slots.push(m);
  let html = "<tr><th>Time</th>" + ROOMS.map(r =>
    `<th>${esc(r.name)}<br><small>cap ${r.capacity}</small></th>`).join("") + "</tr>";
  for (const m of slots) {
    html += `<tr><td class="slot">${toHHMM(m)}</td>`;
    for (const r of ROOMS) {
      const b = bookings.find(b => b.room === r.id && toMin(b.start) <= m && m < toMin(b.end));
      if (b) {
        const first = toMin(b.start) === m;
        html += `<td><div class="cell busy" title="${esc(b.name)}: ${esc(b.title)}">` +
          (first ? `<b>${esc(b.name)}</b><small>${esc(b.title)}</small><small>${b.start}&ndash;${b.end}</small>` : "&nbsp;") +
          `</div></td>`;
      } else {
        html += `<td><div class="cell free" data-room="${r.id}" data-start="${toHHMM(m)}">free</div></td>`;
      }
    }
    html += "</tr>";
  }
  $("grid").innerHTML = html;
  document.querySelectorAll(".cell.free").forEach(c => c.onclick = () => {
    $("bRoom").value = c.dataset.room; $("bDate").value = day; $("bStart").value = c.dataset.start;
    $("bName").focus(); window.scrollTo({top: document.body.scrollHeight, behavior:"smooth"});
  });
}

async function findRooms() {
  const out = $("fResult");
  try {
    const q = new URLSearchParams({ date: $("fDate").value, start: $("fStart").value,
      duration: $("fDur").value, capacity: $("fCap").value || 0 });
    const d = await api("/api/availability?" + q);
    const free = d.rooms.filter(r => r.free), busy = d.rooms.filter(r => !r.free);
    let html = `<b>${d.date} ${d.start}&ndash;${d.end}</b>: `;
    html += free.length ? "free: " + free.map(r => `${esc(r.name)} (cap ${r.capacity})`).join(", ")
                        : "no rooms free for that window.";
    if (busy.length) html += `<br><span class="who">Booked: ${busy.map(r => esc(r.name)).join(", ")}</span>`;
    show(out, html, free.length > 0);
  } catch (e) { show(out, esc(e.message), false); }
}

async function book() {
  const msg = $("bMsg");
  try {
    const d = await api("/api/bookings", { method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ room: $("bRoom").value, date: $("bDate").value, start: $("bStart").value,
        duration: parseInt($("bDur").value,10), name: $("bName").value, title: $("bTitle").value }) });
    const b = d.booking;
    show(msg, `Booked <b>${esc(b.title)}</b> in ${esc(b.room)} on ${b.date} ${b.start}&ndash;${b.end} for ${esc(b.name)}.`, true);
    $("bTitle").value = "";
    $("avDate").value = b.date; $("lDate").value = b.date;
    await Promise.all([renderGrid(), listBookings(b.date)]);
  } catch (e) { show(msg, esc(e.message), false); }
}

async function listBookings(day) {
  const msg = $("lMsg"); hide(msg);
  const url = day ? "/api/bookings?date=" + day : "/api/bookings?upcoming=1";
  const { bookings } = await api(url);
  if (!bookings.length) {
    $("list").innerHTML = `<li class="who">No bookings ${day ? "on " + day : "upcoming"}.</li>`;
    return;
  }
  $("list").innerHTML = bookings.map(b => {
    const room = ROOMS.find(r => r.id === b.room);
    return `<li><div><b>${esc(b.title)}</b> <span class="pill">${esc(room ? room.name : b.room)}</span><br>
      <span class="who">${b.date} ${b.start}&ndash;${b.end} &middot; booked by ${esc(b.name)}</span></div>
      <button class="danger" data-id="${b.id}" data-label="${esc(b.title)} ${b.date} ${b.start}">Cancel</button></li>`;
  }).join("");
  document.querySelectorAll("#list button.danger").forEach(btn => btn.onclick = () => cancel(btn));
}

async function cancel(btn) {
  const id = btn.dataset.id;
  if (!confirm("Cancel booking \"" + btn.dataset.label + "\"? This cannot be undone.")) return;
  try {
    await api("/api/bookings/" + id, { method: "DELETE" });
    show($("lMsg"), "Booking cancelled &mdash; the slot is free again.", true);
    await Promise.all([renderGrid(), listBookings($("lDate").value || null)]);
  } catch (e) { show($("lMsg"), esc(e.message), false); }
}

(async function init() {
  const t = todayISO();
  ["avDate","fDate","bDate","lDate"].forEach(id => $(id).value = t);
  await loadRooms();
  await Promise.all([renderGrid(), listBookings(t)]);
  $("avDate").onchange = renderGrid;
  $("avToday").onclick = () => { $("avDate").value = todayISO(); renderGrid(); };
  $("avTomorrow").onclick = () => { $("avDate").value = addDays(todayISO(), 1); renderGrid(); };
  $("fGo").onclick = findRooms;
  $("bGo").onclick = book;
  $("lGo").onclick = () => listBookings($("lDate").value);
  $("lUpcoming").onclick = () => { $("lDate").value = ""; listBookings(null); };
})();
</script>
</body>
</html>
"""


def main():
    with LOCK:
        load_data()  # create seed file on first run
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("Meeting room booking running at http://localhost:%d" % PORT)
    print("Data file: %s" % DATA_FILE)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
