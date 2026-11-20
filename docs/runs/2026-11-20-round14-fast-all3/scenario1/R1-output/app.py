#!/usr/bin/env python3
"""Meeting room booking system (v1).

Single self-contained web app: serves an HTML UI and a small JSON API.
Storage: data.json with atomic writes + a file lock (fcntl) so concurrent
requests cannot double-book. Standard library only.

Run:  python3 app.py [--port 8000] [--data data.json]
"""
import argparse
import json
import os
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    import fcntl  # POSIX file locking
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

# ---------------------------------------------------------------- config
ROOMS = [
    {"id": "aspen", "name": "Aspen", "capacity": 4},
    {"id": "birch", "name": "Birch", "capacity": 6},
    {"id": "cedar", "name": "Cedar", "capacity": 10},
    {"id": "dune", "name": "Dune", "capacity": 20},
]
ROOM_IDS = [r["id"] for r in ROOMS]
OPEN_MIN = 8 * 60          # 08:00
CLOSE_MIN = 18 * 60        # 18:00
SLOT_MIN = 30              # 30-minute slots
MAX_LEN_MIN = 4 * 60       # max booking length 4 hours
HORIZON_DAYS = 60          # booking horizon

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
_LOCK = threading.Lock()   # in-process lock
_LOCK_PATH = None          # file lock path (set in main / configure)


class BookingError(Exception):
    """User-facing error (HTTP 400)."""


# ---------------------------------------------------------------- helpers
def hhmm(minutes):
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def parse_hhmm(text):
    """'09:30' -> 570. Raises BookingError on bad input."""
    try:
        h, m = str(text).strip().split(":")
        h, m = int(h), int(m)
    except Exception:
        raise BookingError("Time must look like HH:MM (e.g. 09:30), got %r." % (text,))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise BookingError("Invalid time %r." % (text,))
    return h * 60 + m


def parse_date(text):
    try:
        return datetime.strptime(str(text).strip(), "%Y-%m-%d").date()
    except Exception:
        raise BookingError("Date must look like YYYY-MM-DD, got %r." % (text,))


def room_name(rid):
    for r in ROOMS:
        if r["id"] == rid:
            return r["name"]
    return rid


def validate_room(rid):
    rid = str(rid or "").strip().lower()
    if rid not in ROOM_IDS:
        raise BookingError("Unknown room %r. Choose one of: %s."
                           % (rid, ", ".join(ROOM_IDS)))
    return rid


def validate_window(day, start, end):
    """Validate date + time window; returns (day, start_min, end_min)."""
    day = parse_date(day)
    today = date.today()
    if day < today:
        raise BookingError("Cannot book in the past (%s)." % day.isoformat())
    if day > today + timedelta(days=HORIZON_DAYS):
        raise BookingError("Bookings are limited to %d days ahead (latest %s)."
                           % (HORIZON_DAYS, (today + timedelta(days=HORIZON_DAYS)).isoformat()))
    s = parse_hhmm(start)
    e = parse_hhmm(end)
    if s % SLOT_MIN or e % SLOT_MIN:
        raise BookingError("Times must be on %d-minute boundaries." % SLOT_MIN)
    if s < OPEN_MIN or e > CLOSE_MIN:
        raise BookingError("Bookings must be within working hours %s-%s."
                           % (hhmm(OPEN_MIN), hhmm(CLOSE_MIN)))
    if e <= s:
        raise BookingError("End time must be after start time.")
    if e - s > MAX_LEN_MIN:
        raise BookingError("Maximum booking length is %d hours." % (MAX_LEN_MIN // 60))
    return day, s, e


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------- storage
def _empty():
    return {"bookings": [], "next_id": 1}


def load():
    if not os.path.exists(DATA_PATH):
        return _empty()
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return _empty()
    data.setdefault("bookings", [])
    data.setdefault("next_id", 1)
    return data


def save(data):
    """Atomic write: temp file in same dir + fsync + os.replace."""
    d = os.path.dirname(DATA_PATH) or "."
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as e:
        raise BookingError("Cannot create the data directory %r: %s" % (d, e))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".data-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, DATA_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class _FileLock:
    """Cross-process exclusive lock around read-modify-write."""

    def __enter__(self):
        _LOCK.acquire()
        self._fh = None
        if fcntl is not None and _LOCK_PATH:
            self._fh = open(_LOCK_PATH, "a+")
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            if self._fh is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                self._fh.close()
        finally:
            _LOCK.release()
        return False


# ---------------------------------------------------------------- core ops
def list_bookings(day=None, room=None):
    data = load()
    out = []
    for b in data["bookings"]:
        if day and b["date"] != day:
            continue
        if room and b["room"] != room:
            continue
        out.append(b)
    out.sort(key=lambda b: (b["date"], b["start"], b["room"]))
    return out


def availability(day, room=None):
    """Return per-room list of 30-min slots with free/busy + booking info.

    Past dates are answered with the real bookings for that day (so "was Aspen
    free last Tuesday?" is answerable) and flagged read-only: nothing can be
    booked there any more.
    """
    day = parse_date(day).isoformat()
    rooms = [validate_room(room)] if room else ROOM_IDS
    bookings = list_bookings(day=day)
    past = day < date.today().isoformat()
    result = []
    for rid in rooms:
        rb = [b for b in bookings if b["room"] == rid]
        slots = []
        for m in range(OPEN_MIN, CLOSE_MIN, SLOT_MIN):
            s, e = hhmm(m), hhmm(m + SLOT_MIN)
            hit = None
            for b in rb:
                if overlaps(m, m + SLOT_MIN, parse_hhmm(b["start"]), parse_hhmm(b["end"])):
                    hit = b
                    break
            slots.append({
                "start": s, "end": e,
                "free": hit is None,
                "booking": ({"id": hit["id"], "booker": hit["booker"],
                             "title": hit["title"], "start": hit["start"],
                             "end": hit["end"]} if hit else None),
            })
        result.append({"room": rid, "name": room_name(rid), "slots": slots})
    return {"date": day, "rooms": result, "past": past, "read_only": past}


def book(room, day, start, end, booker, title=""):
    rid = validate_room(room)
    day, s, e = validate_window(day, start, end)
    booker = str(booker or "").strip()
    if not booker:
        raise BookingError("Booker name is required.")
    title = str(title or "").strip() or "Meeting"
    with _FileLock():
        data = load()
        for b in data["bookings"]:
            if b["room"] != rid or b["date"] != day.isoformat():
                continue
            if overlaps(s, e, parse_hhmm(b["start"]), parse_hhmm(b["end"])):
                raise BookingError(
                    "Conflict: %s is already booked %s-%s on %s by %s (%r)."
                    % (room_name(rid), b["start"], b["end"], b["date"],
                       b["booker"], b["title"]))
        rec = {
            "id": data["next_id"],
            "room": rid,
            "date": day.isoformat(),
            "start": hhmm(s),
            "end": hhmm(e),
            "booker": booker,
            "title": title,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        data["next_id"] += 1
        data["bookings"].append(rec)
        save(data)
    return rec


def cancel(booking_id):
    try:
        bid = int(booking_id)
    except Exception:
        raise BookingError("Booking id must be a number, got %r." % (booking_id,))
    with _FileLock():
        data = load()
        for i, b in enumerate(data["bookings"]):
            if b["id"] == bid:
                data["bookings"].pop(i)
                save(data)
                return b
    raise BookingError("No booking with id %d (it may already be cancelled)." % bid)


# ---------------------------------------------------------------- HTTP
PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Meeting Room Booking</title>
<style>
:root{--free:#e8f7ee;--freeb:#2e9e5b;--busy:#fde8e8;--busyb:#d64545;--ink:#1d2733;--line:#d7dee6}
*{box-sizing:border-box}
body{margin:0;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:#f5f7fa}
header{background:#1f3a5f;color:#fff;padding:14px 20px}
header h1{margin:0;font-size:19px}
header p{margin:3px 0 0;opacity:.8;font-size:13px}
main{max-width:1100px;margin:0 auto;padding:16px 20px 60px}
.bar{display:flex;gap:12px;flex-wrap:wrap;align-items:end;background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:14px}
label{display:block;font-size:12px;font-weight:600;color:#4a5a6a;margin-bottom:3px}
input,select,button{font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:7px;background:#fff}
button{cursor:pointer;background:#1f3a5f;color:#fff;border-color:#1f3a5f}
button.ghost{background:#fff;color:#1f3a5f}
button.danger{background:#d64545;border-color:#d64545}
button:disabled{opacity:.5;cursor:not-allowed}
.msg{padding:10px 12px;border-radius:8px;margin-bottom:12px;display:none;white-space:pre-wrap}
.msg.err{display:block;background:#fde8e8;border:1px solid #f0b4b4;color:#8a1f1f}
.msg.ok{display:block;background:#e8f7ee;border:1px solid #a9dcbd;color:#1c6b3c}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}
th{background:#eef2f7;font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:#4a5a6a}
td.slot{padding:0}
td.slot button{width:100%;border:0;border-radius:0;padding:7px 6px;font-size:12px;text-align:left;background:var(--free);color:var(--freeb);font-weight:600}
td.slot button.busy{background:var(--busy);color:var(--busyb);cursor:not-allowed}
td.slot button:hover:not(.busy){outline:2px solid var(--freeb);outline-offset:-2px}
h2{font-size:15px;margin:22px 0 8px}
.hint{font-size:12px;color:#6b7a8a;margin:6px 0 0}
#form{display:none;background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:14px}
#form .row{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
</style></head><body>
<header><h1>Meeting Room Booking</h1>
<p>Aspen (4) &middot; Birch (6) &middot; Cedar (10) &middot; Dune (20) &nbsp;|&nbsp; 08:00&ndash;18:00, 30-min slots, max 4 h, up to 60 days ahead</p></header>
<main>
<div class="bar">
  <div><label for="date">Date</label><input type="date" id="date"></div>
  <div><label for="room">Room</label><select id="room"><option value="">All rooms</option></select></div>
  <div><button id="refresh" class="ghost">Refresh</button></div>
  <div><button id="newbtn">New booking</button></div>
</div>
<div id="msg" class="msg"></div>

<div id="form">
  <div class="row">
    <div><label for="f_room">Room</label><select id="f_room"></select></div>
    <div><label for="f_date">Date</label><input type="date" id="f_date"></div>
    <div><label for="f_start">Start</label><select id="f_start"></select></div>
    <div><label for="f_end">End</label><select id="f_end"></select></div>
    <div><label for="f_booker">Booker</label><input id="f_booker" placeholder="Your name"></div>
    <div><label for="f_title">Title</label><input id="f_title" placeholder="Meeting title"></div>
    <div><button id="f_submit">Book</button></div>
    <div><button id="f_cancel" class="ghost">Close</button></div>
  </div>
</div>

<h2>Availability</h2>
<div id="pastnote" class="msg err" style="display:none"></div>
<table id="grid"><thead></thead><tbody></tbody></table>
<p class="hint">Green = free (click to book) &middot; red = booked (hover to see who).</p>

<h2>Bookings for the day</h2>
<table id="list"><thead><tr><th>Room</th><th>Time</th><th>Booker</th><th>Title</th><th></th></tr></thead><tbody></tbody></table>

<h2>Upcoming bookings</h2>
<p class="hint">All bookings from today onwards, across all rooms. Cancel here if you cannot find the booking on the day view.</p>
<table id="upcoming"><thead><tr><th>Date</th><th>Room</th><th>Time</th><th>Booker</th><th>Title</th><th></th></tr></thead><tbody></tbody></table>
</main>
<script>
const $ = s => document.querySelector(s);
const ROOMS = __ROOMS__;
const OPEN = 8*60, CLOSE = 18*60, STEP = 30;
const hhmm = m => String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0');
const today = new Date();
const iso = d => d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
let lastBooker = '';
try { lastBooker = localStorage.getItem('lastBooker') || ''; } catch(e) {}

function msg(text, kind){ const m=$('#msg'); m.className='msg '+(kind||''); m.textContent=text||''; }
function api(path, opts){
  return fetch(path, opts).then(async r => {
    const j = await r.json().catch(()=>({error:'Bad response from server'}));
    if(!r.ok) throw new Error(j.error || ('HTTP '+r.status));
    return j;
  });
}
function fillSelects(){
  const roomOpts = ROOMS.map(r=>`<option value="${r.id}">${r.name} (${r.capacity})</option>`).join('');
  $('#room').innerHTML = '<option value="">All rooms</option>'+roomOpts;
  $('#f_room').innerHTML = roomOpts;
  let s='', e='';
  for(let m=OPEN;m<=CLOSE;m+=STEP){ s+=`<option value="${hhmm(m)}">${hhmm(m)}</option>`; if(m>OPEN) e+=`<option value="${hhmm(m)}">${hhmm(m)}</option>`; }
  $('#f_start').innerHTML=s; $('#f_end').innerHTML=e;
}
function openForm(room, start){
  $('#form').style.display='block';
  if(room) $('#f_room').value=room;
  $('#f_date').value=$('#date').value;
  $('#f_date').min=$('#date').min; $('#f_date').max=$('#date').max;
  if(start){
    const [h,mi]=start.split(':').map(Number);
    const m=h*60+mi+60;
    $('#f_start').value=start;
    $('#f_end').value=hhmm(Math.min(m,CLOSE));
  }
  if(lastBooker && !$('#f_booker').value) $('#f_booker').value=lastBooker;
  $('#f_booker').focus();
}
function load(){
  const d=$('#date').value, r=$('#room').value;
  msg('');
  api(`/api/availability?date=${d}${r?'&room='+r:''}`).then(data=>{
    const times=[]; for(let m=OPEN;m<CLOSE;m+=STEP) times.push(hhmm(m));
    const head='<tr><th>Time</th>'+data.rooms.map(x=>`<th>${x.name}</th>`).join('')+'</tr>';
    $('#grid').querySelector('thead').innerHTML=head;
    const body=times.map((t,i)=>{
      const cells=data.rooms.map(x=>{
        const s=x.slots[i];
        if(s.free) return `<td class="slot"><button data-room="${x.room}" data-start="${s.start}">free</button></td>`;
        const b=s.booking;
        return `<td class="slot"><button class="busy" title="${esc(b.booker)}: ${esc(b.title)} (${esc(b.start)}-${esc(b.end)})">${esc(b.booker)}</button></td>`;
      }).join('');
      return `<tr><th>${t}</th>${cells}</tr>`;
    }).join('');
    $('#grid').querySelector('tbody').innerHTML=body;
    const note=$('#pastnote');
    if(data.past){
      note.style.display='block';
      note.textContent='This date is in the past: the grid shows the bookings that were made that day. Past days are read-only, so slots cannot be booked.';
    } else { note.style.display='none'; note.textContent=''; }
    $('#grid').querySelectorAll('button[data-room]').forEach(btn=>{
      btn.onclick=()=>openForm(btn.dataset.room, btn.dataset.start);
    });
  }).catch(e=>msg(e.message,'err'));
  api(`/api/bookings?date=${d}${r?'&room='+r:''}`).then(data=>{
    const rows=data.bookings.map(b=>`<tr><td>${b.room_name}</td><td>${b.start}&ndash;${b.end}</td><td>${esc(b.booker)}</td><td>${esc(b.title)}</td>
      <td><button class="danger" data-id="${b.id}">Cancel</button></td></tr>`).join('');
    $('#list').querySelector('tbody').innerHTML = rows || '<tr><td colspan="5">No bookings for this day.</td></tr>';
    $('#list').querySelectorAll('button[data-id]').forEach(btn=>{
      btn.onclick=()=>{
        if(!confirm('Cancel this booking?')) return;
        api('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:Number(btn.dataset.id)})})
          .then(()=>{ msg('Booking cancelled. The slot is free again.','ok'); load(); })
          .catch(e=>msg(e.message,'err'));
      };
    });
  }).catch(e=>msg(e.message,'err'));
  loadUpcoming();
}
function cancelBooking(id){
  if(!confirm('Cancel this booking?')) return;
  api('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:Number(id)})})
    .then(()=>{ msg('Booking cancelled. The slot is free again.','ok'); load(); })
    .catch(e=>msg(e.message,'err'));
}
function loadUpcoming(){
  api('/api/bookings').then(data=>{
    const rows=data.bookings.map(b=>`<tr><td>${esc(b.date)}</td><td>${esc(b.room_name)}</td><td>${esc(b.start)}&ndash;${esc(b.end)}</td><td>${esc(b.booker)}</td><td>${esc(b.title)}</td>
      <td><button class="danger" data-id="${b.id}">Cancel</button></td></tr>`).join('');
    $('#upcoming').querySelector('tbody').innerHTML = rows || '<tr><td colspan="6">No bookings yet.</td></tr>';
    $('#upcoming').querySelectorAll('button[data-id]').forEach(btn=>{
      btn.onclick=()=>cancelBooking(btn.dataset.id);
    });
  }).catch(e=>msg(e.message,'err'));
}
function esc(s){ return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

document.addEventListener('DOMContentLoaded',()=>{
  fillSelects();
  $('#date').value = iso(today);
  $('#date').min = iso(today);
  $('#date').max = iso(new Date(Date.now()+60*864e5));
  $('#date').onchange=load; $('#room').onchange=load; $('#refresh').onclick=load;
  $('#newbtn').onclick=()=>openForm($('#room').value||ROOMS[0].id, null);
  $('#f_cancel').onclick=()=>{ $('#form').style.display='none'; };
  $('#form').addEventListener('keydown',ev=>{
    if(ev.key==='Enter'){ ev.preventDefault(); $('#f_submit').click(); }
  });
  $('#f_submit').onclick=()=>{
    const body={room:$('#f_room').value,date:$('#f_date').value,start:$('#f_start').value,
                end:$('#f_end').value,booker:$('#f_booker').value,title:$('#f_title').value};
    api('/api/book',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
      .then(b=>{ lastBooker=b.booker; try{ localStorage.setItem('lastBooker',b.booker); }catch(e){}
                 msg(`Booked ${b.room_name} ${b.date} ${b.start}-${b.end} for ${b.booker}.`,'ok');
                 $('#form').style.display='none'; $('#date').value=b.date; load(); })
      .catch(e=>msg(e.message,'err'));
  };
  load();
});
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "BookingSystem/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

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

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise BookingError("Request body must be valid JSON.")

    def _decorate(self, b):
        d = dict(b)
        d["room_name"] = room_name(b["room"])
        return d

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                page = PAGE.replace("__ROOMS__", json.dumps(ROOMS))
                return self._send(200, page, "text/html")
            if u.path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if u.path == "/api/rooms":
                return self._json(200, {"rooms": ROOMS, "open": hhmm(OPEN_MIN),
                                        "close": hhmm(CLOSE_MIN), "slot_minutes": SLOT_MIN,
                                        "max_hours": MAX_LEN_MIN // 60,
                                        "horizon_days": HORIZON_DAYS})
            if u.path == "/api/availability":
                day = (q.get("date") or [date.today().isoformat()])[0]
                room = (q.get("room") or [""])[0] or None
                return self._json(200, availability(day, room))
            if u.path == "/api/bookings":
                day = (q.get("date") or [""])[0] or None
                room = (q.get("room") or [""])[0] or None
                if room:
                    room = validate_room(room)
                if day:
                    day = parse_date(day).isoformat()
                return self._json(200, {"bookings": [self._decorate(b) for b in list_bookings(day, room)]})
            return self._json(404, {"error": "Not found: %s" % u.path})
        except BookingError as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:  # pragma: no cover
            return self._json(500, {"error": "Server error: %s" % e})

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = self._body()
            if u.path == "/api/book":
                rec = book(body.get("room"), body.get("date"), body.get("start"),
                           body.get("end"), body.get("booker"), body.get("title"))
                return self._json(201, self._decorate(rec))
            if u.path == "/api/cancel":
                rec = cancel(body.get("id"))
                return self._json(200, {"cancelled": self._decorate(rec)})
            return self._json(404, {"error": "Not found: %s" % u.path})
        except BookingError as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:  # pragma: no cover
            return self._json(500, {"error": "Server error: %s" % e})


def main(argv=None):
    global DATA_PATH, _LOCK_PATH
    ap = argparse.ArgumentParser(description="Meeting room booking system")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--data", default=DATA_PATH)
    a = ap.parse_args(argv)
    DATA_PATH = os.path.abspath(a.data)
    _LOCK_PATH = DATA_PATH + ".lock"
    data_dir = os.path.dirname(DATA_PATH) or "."
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError as e:
        sys.stderr.write("Cannot create the data directory %r: %s\n"
                         "Choose another location with --data <file>.\n" % (data_dir, e))
        return 2
    if not os.access(data_dir, os.W_OK):
        sys.stderr.write("Data directory %r is not writable; choose another location with --data <file>.\n"
                         % (data_dir,))
        return 2
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("Meeting room booking system running at http://%s:%d/" % (a.host, a.port))
    print("Data file: %s" % DATA_PATH)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
