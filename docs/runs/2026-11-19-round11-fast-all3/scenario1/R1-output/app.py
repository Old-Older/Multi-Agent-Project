#!/usr/bin/env python3
"""Meeting room booking web app - standard library only.

Start:  python3 app.py            (then open http://localhost:8000)
Data:   bookings.json (created automatically next to this file)
"""
import json
import os
import threading
import uuid
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))
DATA_FILE = os.environ.get("BOOKINGS_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookings.json"))

ROOMS = [("Aspen", 4), ("Birch", 6), ("Cedar", 10), ("Dune", 20)]
ROOM_NAMES = [r[0] for r in ROOMS]
DAY_START = 8 * 60      # 08:00 in minutes
DAY_END = 18 * 60       # 18:00
SLOT = 30
MAX_HOURS = 4
MAX_DAYS_AHEAD = 60

# One global lock around every read-modify-write of the JSON store.
LOCK = threading.RLock()


# ---------------------------------------------------------------- storage
def _empty():
    return {"bookings": []}


def load():
    with LOCK:
        if not os.path.exists(DATA_FILE):
            return _empty()
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (ValueError, OSError):
            return _empty()
        if not isinstance(data, dict) or not isinstance(data.get("bookings"), list):
            return _empty()
        return data


def save(data):
    with LOCK:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, DATA_FILE)


# ---------------------------------------------------------------- helpers
def hhmm(minutes):
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def parse_time(text):
    """'09:30' -> 570. Raises ValueError on bad input."""
    text = (text or "").strip()
    try:
        h, m = text.split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        raise ValueError("Time must look like HH:MM (e.g. 09:30).")
    if not (0 <= h <= 23 and m in (0, 30)):
        raise ValueError("Time must be on a 30-minute boundary (e.g. 09:00 or 09:30).")
    return h * 60 + m


def parse_date(text):
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Date must look like YYYY-MM-DD.")


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def active_bookings(data):
    return [b for b in data["bookings"] if not b.get("cancelled")]


def conflicts(data, room, day, start, end, ignore_id=None):
    out = []
    for b in active_bookings(data):
        if b["room"] != room or b["date"] != day:
            continue
        if ignore_id and b["id"] == ignore_id:
            continue
        if overlaps(start, end, b["start"], b["end"]):
            out.append(b)
    return out


def validate_booking(data, room, day_s, start_s, end_s, title, booker, today=None):
    """Return (booking_dict, None) or (None, error_message)."""
    today = today or date.today()
    if room not in ROOM_NAMES:
        return None, "Please choose a valid room."
    if not (booker or "").strip():
        return None, "Booker name is required."
    if not (title or "").strip():
        return None, "Title is required."
    try:
        day = parse_date(day_s)
    except ValueError as e:
        return None, str(e)
    try:
        start = parse_time(start_s)
        end = parse_time(end_s)
    except ValueError as e:
        return None, str(e)
    if day.weekday() > 4:
        return None, "Bookings are only possible Monday to Friday."
    if day < today:
        return None, "You cannot book a date in the past."
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        return None, "You can only book up to %d days ahead." % MAX_DAYS_AHEAD
    if start < DAY_START or end > DAY_END:
        return None, "Bookings must be between 08:00 and 18:00."
    if end <= start:
        return None, "End time must be after start time."
    if end - start > MAX_HOURS * 60:
        return None, "A booking may be at most %d hours long." % MAX_HOURS
    clash = conflicts(data, room, day.isoformat(), start, end)
    if clash:
        c = clash[0]
        return None, "Double booking: %s is already booked %s-%s on %s (%s, booked by %s)." % (
            room, hhmm(c["start"]), hhmm(c["end"]), c["date"], c["title"], c["booker"])
    return {
        "id": uuid.uuid4().hex[:12],
        "room": room,
        "date": day.isoformat(),
        "start": start,
        "end": end,
        "title": title.strip(),
        "booker": booker.strip(),
        "created": datetime.now().isoformat(timespec="seconds"),
        "cancelled": False,
    }, None


def add_booking(room, day_s, start_s, end_s, title, booker, today=None):
    """Validate + persist under the lock. Returns (booking, error)."""
    with LOCK:
        data = load()
        booking, err = validate_booking(data, room, day_s, start_s, end_s, title, booker, today)
        if err:
            return None, err
        data["bookings"].append(booking)
        save(data)
        return booking, None


def cancel_booking(booking_id):
    with LOCK:
        data = load()
        for b in data["bookings"]:
            if b["id"] == booking_id:
                if b.get("cancelled"):
                    return False, "That booking was already cancelled."
                b["cancelled"] = True
                b["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
                save(data)
                return True, None
        return False, "Booking not found."


def add_recurring(room, day_s, start_s, end_s, title, booker, weeks, today=None):
    """Book the same slot for N consecutive weeks, skipping conflicts."""
    with LOCK:
        try:
            weeks = int(weeks)
        except (TypeError, ValueError):
            return None, "Number of weeks must be a whole number."
        if not 1 <= weeks <= 26:
            return None, "Number of weeks must be between 1 and 26."
        try:
            first = parse_date(day_s)
        except ValueError as e:
            return None, str(e)
        created, skipped = [], []
        for i in range(weeks):
            d = first + timedelta(weeks=i)
            booking, err = add_booking(room, d.isoformat(), start_s, end_s, title, booker, today)
            if err:
                skipped.append({"date": d.isoformat(), "reason": err})
            else:
                created.append(booking)
        return {"created": created, "skipped": skipped}, None


def availability(day_s, room_filter=None, start_s=None, end_s=None):
    """Grid of rooms x slots for a date, plus optional 'free room' filter."""
    try:
        day = parse_date(day_s)
    except ValueError as e:
        return {"error": str(e)}
    data = load()
    day_iso = day.isoformat()
    slots = list(range(DAY_START, DAY_END, SLOT))
    rooms = []
    for name, cap in ROOMS:
        if room_filter and room_filter != name:
            continue
        cells = []
        for s in slots:
            busy = conflicts(data, name, day_iso, s, s + SLOT)
            cells.append({"start": hhmm(s), "end": hhmm(s + SLOT),
                          "free": not busy,
                          "title": busy[0]["title"] if busy else "",
                          "booker": busy[0]["booker"] if busy else ""})
        rooms.append({"name": name, "capacity": cap, "cells": cells})
    result = {"date": day_iso, "weekday": day.strftime("%A"), "weekend": day.weekday() > 4,
              "slots": [hhmm(s) for s in slots], "rooms": rooms}
    if start_s and end_s:
        try:
            st, en = parse_time(start_s), parse_time(end_s)
        except ValueError as e:
            result["free_rooms_error"] = str(e)
        else:
            free = []
            for name, cap in ROOMS:
                if not conflicts(data, name, day_iso, st, en):
                    free.append({"name": name, "capacity": cap})
            result["free_rooms"] = free
            result["free_rooms_for"] = "%s-%s" % (hhmm(st), hhmm(en))
    return result


def list_bookings(booker=None, include_cancelled=False, upcoming_only=False):
    data = load()
    out = []
    today = date.today().isoformat()
    for b in data["bookings"]:
        if not include_cancelled and b.get("cancelled"):
            continue
        if booker and b["booker"].strip().lower() != booker.strip().lower():
            continue
        if upcoming_only and b["date"] < today:
            continue
        out.append(b)
    out.sort(key=lambda b: (b["date"], b["start"], b["room"]))
    return out


# ---------------------------------------------------------------- HTML
CSS = """
body{font-family:system-ui,Arial,sans-serif;margin:0;background:#f4f6f8;color:#1d2733}
header{background:#1f3a5f;color:#fff;padding:14px 22px}
header h1{margin:0;font-size:20px}
nav a{color:#cfe0f5;margin-right:16px;text-decoration:none;font-size:14px}
nav a:hover{color:#fff}
main{max-width:1150px;margin:18px auto;padding:0 16px}
.card{background:#fff;border-radius:8px;padding:16px 18px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.12)}
h2{margin:0 0 12px;font-size:17px}
label{display:block;font-size:13px;margin:8px 0 3px;color:#445}
input,select{padding:6px 8px;border:1px solid #b9c4d0;border-radius:5px;font-size:14px}
button{background:#1f6feb;color:#fff;border:0;border-radius:5px;padding:7px 14px;font-size:14px;cursor:pointer}
button:hover{background:#1558c0}
button.danger{background:#c62828}button.danger:hover{background:#a01f1f}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #dde3ea;padding:5px 7px;text-align:left}
th{background:#eef2f7}
.free{background:#e6f6ea;color:#1b6b32;text-align:center}
.busy{background:#fde7e7;color:#a01f1f;text-align:center;font-weight:600}
.weekend{background:#f0f0f0;color:#888;text-align:center}
.msg{padding:10px 12px;border-radius:6px;margin-bottom:14px;font-size:14px}
.err{background:#fde7e7;color:#a01f1f;border:1px solid #f3b6b6}
.ok{background:#e6f6ea;color:#1b6b32;border:1px solid #b6e0c2}
.warn{background:#fff6e0;color:#7a5a00;border:1px solid #f0dca0}
.muted{color:#667;font-size:13px}
.grid-scroll{overflow-x:auto}
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def page(title, body, msg=""):
    return """<!doctype html><html><head><meta charset="utf-8">
<title>%s - Room Booking</title><style>%s</style></head><body>
<header><h1>Meeting Room Booking</h1>
<nav><a href="/">Availability</a><a href="/book">Book a room</a>
<a href="/bookings">All bookings / cancel</a><a href="/my">My bookings</a></nav></header>
<main>%s%s</main></body></html>""" % (esc(title), CSS, msg, body)


def msg_html(kind, text):
    return '<div class="msg %s">%s</div>' % (kind, esc(text))


def availability_html(day_s, room_filter="", start_s="", end_s=""):
    data = availability(day_s, room_filter or None, start_s or None, end_s or None)
    if "error" in data:
        return page("Availability", '<div class="card">%s</div>' % msg_html("err", data["error"]))
    opts = "".join('<option value="%s"%s>%s (%d)</option>' % (
        n, " selected" if n == room_filter else "", n, c) for n, c in ROOMS)
    form = """<div class="card"><h2>Check availability</h2>
<form method="get" action="/">
<label>Date</label><input type="date" name="date" value="%s" required>
<label>Room (optional)</label><select name="room"><option value="">All rooms</option>%s</select>
<label>Find a free room for (optional)</label>
<input type="time" name="start" step="1800" value="%s"> to
<input type="time" name="end" step="1800" value="%s">
<button type="submit">Check</button></form></div>""" % (esc(data["date"]), opts, esc(start_s), esc(end_s))

    extra = ""
    if "free_rooms" in data:
        if data["free_rooms"]:
            items = ", ".join("<b>%s</b> (%d)" % (esc(r["name"]), r["capacity"]) for r in data["free_rooms"])
            extra = msg_html("ok", "Free rooms for %s on %s: %s" % (data["free_rooms_for"], data["date"], items))
        else:
            extra = msg_html("err", "No room is free for %s on %s." % (data["free_rooms_for"], data["date"]))
    elif "free_rooms_error" in data:
        extra = msg_html("err", data["free_rooms_error"])

    head = "".join("<th>%s</th>" % s for s in data["slots"])
    rows = []
    for r in data["rooms"]:
        cells = []
        for c in r["cells"]:
            if data["weekend"]:
                cells.append('<td class="weekend">-</td>')
            elif c["free"]:
                cells.append('<td class="free">free</td>')
            else:
                cells.append('<td class="busy" title="%s - %s">%s<br><span style="font-weight:400">%s</span></td>'
                             % (esc(c["title"]), esc(c["booker"]), esc(c["title"]), esc(c["booker"])))
        rows.append("<tr><th>%s (%d)</th>%s</tr>" % (esc(r["name"]), r["capacity"], "".join(cells)))
    grid = """<div class="card"><h2>%s %s</h2>%s<div class="grid-scroll"><table>
<tr><th>Room</th>%s</tr>%s</table></div>
<p class="muted">Green = free, red = booked (title and booker shown). Slots are 30 minutes, 08:00-18:00.</p></div>""" % (
        esc(data["weekday"]), esc(data["date"]),
        msg_html("warn", "This is a weekend - bookings are only possible Monday to Friday.") if data["weekend"] else "",
        head, "".join(rows))
    return page("Availability", form + extra + grid)


def book_form_html(prefill=None, msg=""):
    p = prefill or {}
    today = date.today().isoformat()
    opts = "".join('<option value="%s"%s>%s (%d)</option>' % (
        n, " selected" if p.get("room") == n else "", n, c) for n, c in ROOMS)
    body = """<div class="card"><h2>Book a room</h2>
<form method="post" action="/book">
<label>Room</label><select name="room">%s</select>
<label>Date (Mon-Fri, up to %d days ahead)</label><input type="date" name="date" value="%s" required>
<label>Start</label><input type="time" name="start" step="1800" value="%s" required>
<label>End (max %d hours)</label><input type="time" name="end" step="1800" value="%s" required>
<label>Title</label><input type="text" name="title" value="%s" required>
<label>Booker name</label><input type="text" name="booker" value="%s" required>
<label>Repeat weekly for N weeks (optional, conflicts are skipped)</label>
<input type="number" name="weeks" min="1" max="26" value="%s">
<button type="submit">Book</button></form>
<p class="muted">Overlapping bookings for the same room are rejected by the server.</p></div>""" % (
        opts, MAX_DAYS_AHEAD, esc(p.get("date") or today), esc(p.get("start") or "09:00"),
        MAX_HOURS, esc(p.get("end") or "10:00"), esc(p.get("title") or ""),
        esc(p.get("booker") or ""), esc(p.get("weeks") or "1"))
    return page("Book a room", body, msg)


def bookings_table(rows, show_cancel=True):
    if not rows:
        return '<p class="muted">No bookings.</p>'
    out = ["<table><tr><th>Date</th><th>Time</th><th>Room</th><th>Title</th><th>Booked by</th>%s</tr>" %
           ("<th>Action</th>" if show_cancel else "")]
    for b in rows:
        action = ""
        if show_cancel:
            action = ('<td><form method="post" action="/cancel" style="margin:0">'
                      '<input type="hidden" name="id" value="%s">'
                      '<button class="danger" type="submit">Cancel</button></form></td>' % esc(b["id"]))
        out.append("<tr><td>%s</td><td>%s-%s</td><td>%s</td><td>%s</td><td>%s</td>%s</tr>" % (
            esc(b["date"]), hhmm(b["start"]), hhmm(b["end"]), esc(b["room"]),
            esc(b["title"]), esc(b["booker"]), action))
    out.append("</table>")
    return "".join(out)


def bookings_html(msg=""):
    rows = list_bookings(upcoming_only=True)
    body = '<div class="card"><h2>Upcoming bookings</h2>%s<p class="muted">Anyone can cancel. Cancelled bookings disappear from availability immediately.</p></div>' % bookings_table(rows)
    return page("Bookings", body, msg)


def my_html(booker="", msg=""):
    rows = list_bookings(booker) if booker else []
    body = """<div class="card"><h2>My bookings</h2>
<form method="get" action="/my"><label>Your name</label>
<input type="text" name="booker" value="%s" required> <button type="submit">Show</button></form>
%s</div>""" % (esc(booker), bookings_table(rows) if booker else '<p class="muted">Enter your name to see your bookings.</p>')
    return page("My bookings", body, msg)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "RoomBooking/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, html):
        data = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/":
            day = q.get("date") or date.today().isoformat()
            self._send(200, availability_html(day, q.get("room", ""), q.get("start", ""), q.get("end", "")))
        elif u.path == "/book":
            self._send(200, book_form_html())
        elif u.path == "/bookings":
            self._send(200, bookings_html())
        elif u.path == "/my":
            self._send(200, my_html(q.get("booker", "")))
        elif u.path == "/api/availability":
            self._json(200, availability(q.get("date") or date.today().isoformat(),
                                         q.get("room"), q.get("start"), q.get("end")))
        elif u.path == "/api/bookings":
            self._json(200, {"bookings": list_bookings(q.get("booker"), upcoming_only=True)})
        else:
            self._send(404, page("Not found", '<div class="card">Page not found. <a href="/">Go to availability</a></div>'))

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8")).items()}
        if u.path == "/book":
            weeks = (form.get("weeks") or "1").strip() or "1"
            if weeks != "1":
                res, err = add_recurring(form.get("room"), form.get("date"), form.get("start"),
                                         form.get("end"), form.get("title"), form.get("booker"), weeks)
                if err:
                    self._send(400, book_form_html(form, msg_html("err", err)))
                    return
                parts = []
                if res["created"]:
                    parts.append(msg_html("ok", "Booked %d week(s): %s" % (
                        len(res["created"]), ", ".join(b["date"] for b in res["created"]))))
                if res["skipped"]:
                    parts.append(msg_html("warn", "Skipped %d week(s): %s" % (
                        len(res["skipped"]), "; ".join("%s (%s)" % (s["date"], s["reason"]) for s in res["skipped"]))))
                if not res["created"]:
                    parts.append(msg_html("err", "No week could be booked."))
                self._send(200, bookings_html("".join(parts)))
                return
            booking, err = add_booking(form.get("room"), form.get("date"), form.get("start"),
                                       form.get("end"), form.get("title"), form.get("booker"))
            if err:
                self._send(400, book_form_html(form, msg_html("err", err)))
                return
            self._send(200, bookings_html(msg_html("ok", "Booked %s %s %s-%s for %s." % (
                booking["room"], booking["date"], hhmm(booking["start"]), hhmm(booking["end"]), booking["booker"]))))
        elif u.path == "/cancel":
            ok, err = cancel_booking(form.get("id", ""))
            if ok:
                self._send(200, bookings_html(msg_html("ok", "Booking cancelled - the slot is free again.")))
            else:
                self._send(400, bookings_html(msg_html("err", err)))
        else:
            self._send(404, page("Not found", '<div class="card">Page not found.</div>'))


def make_server(host=HOST, port=PORT):
    return ThreadingHTTPServer((host, port), Handler)


def main():
    srv = make_server()
    print("Meeting room booking running at http://localhost:%d  (Ctrl+C to stop)" % srv.server_address[1])
    print("Data file: %s" % DATA_FILE)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
