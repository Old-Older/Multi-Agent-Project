#!/usr/bin/env python3
"""Meeting room booking system (v2) with a manager dashboard.

Single self-contained web app: serves an HTML UI (Bookings + Dashboard tabs)
and a small JSON API. Storage: data.json with atomic writes + a file lock
(fcntl) so concurrent requests cannot double-book. Standard library only.

v2 changes (all v1 behaviour kept):
  * cancel() RECORDS the cancellation ({"cancelled": true, "cancelled_at": iso})
    instead of deleting the record; cancelled records are ignored everywhere
    else (list, availability, conflict checks) so the slot is free again.
  * GET /api/dashboard?start&end  -> manager metrics for a date range.
  * GET /api/cancellations?start&end -> cancelled records in a range.
  * POST /api/demo-data -> insert demo bookings when the file has none.
  * UI: tab bar (Bookings | Dashboard) with inline SVG/CSS charts, no CDN.

Run:  python3 app.py [--port 8000] [--data data.json]
"""
import argparse
import json
import os
import random
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

# Dashboard thresholds (utilisation vs. available weekday hours in the range).
HEAVY_PCT = 60.0           # >= 60% -> "heavily used"
LOW_PCT = 20.0             # <= 20% -> "underused"
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

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


def is_cancelled(b):
    """True if the record was cancelled. Old data files have no flag."""
    return bool(b.get("cancelled"))


def booking_hours(b):
    """Reserved hours of one booking (end - start)."""
    return (parse_hhmm(b["end"]) - parse_hhmm(b["start"])) / 60.0


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
    """Active (not cancelled) bookings, optionally filtered by day/room."""
    data = load()
    out = []
    for b in data["bookings"]:
        if is_cancelled(b):
            continue
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
    booked there any more. Cancelled bookings never make a slot busy.
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
            if is_cancelled(b):
                continue  # cancelled records free their slot
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
    """Mark a booking cancelled (record kept for the dashboard)."""
    try:
        bid = int(booking_id)
    except Exception:
        raise BookingError("Booking id must be a number, got %r." % (booking_id,))
    with _FileLock():
        data = load()
        for b in data["bookings"]:
            if b["id"] == bid:
                if is_cancelled(b):
                    break  # already cancelled -> same error as "not found"
                b["cancelled"] = True
                b["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
                save(data)
                return b
    raise BookingError("No booking with id %d (it may already be cancelled)." % bid)


def list_cancellations(start=None, end=None):
    """Cancelled records, optionally limited to a date range (inclusive)."""
    data = load()
    out = []
    for b in data["bookings"]:
        if not is_cancelled(b):
            continue
        if start and b["date"] < start:
            continue
        if end and b["date"] > end:
            continue
        out.append(b)
    out.sort(key=lambda b: (b["date"], b["start"], b["room"]))
    return out


# ---------------------------------------------------------------- dashboard
def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def _status(util):
    if util >= HEAVY_PCT:
        return "heavily used"
    if util <= LOW_PCT:
        return "underused"
    return "balanced"


def _weekdays_between(start, end):
    """Number of Mon-Fri days in [start, end] (weekends count as 0 available)."""
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def dashboard(start=None, end=None):
    """Manager metrics for an inclusive date range.

    Cancelled bookings are counted separately and never contribute to booked
    counts or reserved hours. Utilisation compares reserved hours with the
    room's available hours = weekdays in range x (CLOSE-OPEN) hours.
    """
    today = date.today()
    end_d = parse_date(end) if end else today
    start_d = parse_date(start) if start else end_d - timedelta(days=29)
    if start_d > end_d:
        raise BookingError("start (%s) must be on or before end (%s)."
                           % (start_d.isoformat(), end_d.isoformat()))
    s_iso, e_iso = start_d.isoformat(), end_d.isoformat()
    days = (end_d - start_d).days + 1
    open_hours = (CLOSE_MIN - OPEN_MIN) / 60.0
    avail_hours = _weekdays_between(start_d, end_d) * open_hours

    data = load()
    active, cancelled = [], []
    for b in data["bookings"]:
        if not (s_iso <= b["date"] <= e_iso):
            continue
        (cancelled if is_cancelled(b) else active).append(b)

    # ---- per room
    per_room = []
    for r in ROOMS:
        rb = [b for b in active if b["room"] == r["id"]]
        rc = [b for b in cancelled if b["room"] == r["id"]]
        hours = round(sum(booking_hours(b) for b in rb), 2)
        util = _pct(hours, avail_hours)
        per_room.append({
            "id": r["id"], "name": r["name"], "capacity": r["capacity"],
            "bookings": len(rb), "hours": hours,
            "utilisation_pct": util, "available_hours": round(avail_hours, 2),
            "cancelled": len(rc),
            "cancellation_rate_pct": _pct(len(rc), len(rb) + len(rc)),
            "status": _status(util),
        })

    # ---- totals
    total_bookings = len(active)
    total_hours = round(sum(booking_hours(b) for b in active), 2)
    total_cancelled = len(cancelled)
    busiest = quietest = None
    if total_bookings:
        # busiest = most bookings, then most hours; quietest = the reverse
        ranked = sorted(per_room, key=lambda x: (x["bookings"], x["hours"]), reverse=True)
        busiest = ranked[0]["name"]
        quietest = sorted(per_room, key=lambda x: (x["bookings"], x["hours"]))[0]["name"]
    totals = {
        "bookings": total_bookings,
        "hours": total_hours,
        "cancelled": total_cancelled,
        "cancellation_rate_pct": _pct(total_cancelled, total_bookings + total_cancelled),
        "busiest_room": busiest,
        "quietest_room": quietest,
    }

    # ---- by weekday / by hour / heatmap
    by_weekday = [{"weekday": i, "name": WEEKDAY_NAMES[i], "bookings": 0, "hours": 0.0}
                  for i in range(7)]
    hours_list = list(range(OPEN_MIN // 60, CLOSE_MIN // 60))  # 08..17
    by_hour = [{"hour": h, "label": "%02d:00" % h, "bookings": 0} for h in hours_list]
    heatmap = [[0 for _ in hours_list] for _ in range(7)]
    for b in active:
        wd = parse_date(b["date"]).weekday()
        by_weekday[wd]["bookings"] += 1
        by_weekday[wd]["hours"] = round(by_weekday[wd]["hours"] + booking_hours(b), 2)
        bs, be = parse_hhmm(b["start"]), parse_hhmm(b["end"])
        for idx, h in enumerate(hours_list):
            # a booking counts in every hour it overlaps
            if overlaps(bs, be, h * 60, (h + 1) * 60):
                by_hour[idx]["bookings"] += 1
                heatmap[wd][idx] += 1

    # ---- top 5 (weekday, hour) slots
    slots = []
    for wd in range(7):
        for idx, h in enumerate(hours_list):
            if heatmap[wd][idx]:
                slots.append({"weekday": wd, "weekday_name": WEEKDAY_NAMES[wd],
                              "hour": h, "label": "%s %02d:00" % (WEEKDAY_NAMES[wd], h),
                              "count": heatmap[wd][idx]})
    slots.sort(key=lambda x: (-x["count"], x["weekday"], x["hour"]))
    top_slots = slots[:5]

    # ---- daily series (every day in the range, zero-filled)
    daily = []
    d = start_d
    while d <= end_d:
        daily.append({"date": d.isoformat(), "weekday": WEEKDAY_NAMES[d.weekday()],
                      "bookings": 0, "hours": 0.0})
        d += timedelta(days=1)
    index = {row["date"]: row for row in daily}
    for b in active:
        row = index.get(b["date"])
        if row is not None:
            row["bookings"] += 1
            row["hours"] = round(row["hours"] + booking_hours(b), 2)

    cancelled_by_room = [{"id": r["id"], "name": r["name"],
                          "cancelled": sum(1 for b in cancelled if b["room"] == r["id"])}
                         for r in ROOMS]

    return {
        "range": {"start": s_iso, "end": e_iso, "days": days,
                  "weekdays": _weekdays_between(start_d, end_d),
                  "available_hours_per_room": round(avail_hours, 2)},
        "per_room": per_room,
        "totals": totals,
        "by_weekday": by_weekday,
        "by_hour": by_hour,
        "heatmap": heatmap,
        "top_slots": top_slots,
        "daily": daily,
        "cancelled_by_room": cancelled_by_room,
        "cancellations": total_cancelled,
        "cancelled": total_cancelled,
        "empty": total_bookings == 0,
    }


# ---------------------------------------------------------------- demo data
DEMO_BOOKERS = ["Ann", "Bob", "Cy", "Dee", "Eve", "Fay", "Gus", "Hana", "Ivo", "Jo"]
DEMO_TITLES = ["Standup", "1:1", "Design review", "Sprint planning", "Interview",
               "Client call", "Retro", "Budget review", "Workshop", "Sync"]
# Rough popularity weights: small rooms are used more often than the big one.
DEMO_ROOM_WEIGHTS = {"aspen": 4, "birch": 3, "cedar": 2, "dune": 1}


def demo_data():
    """Insert demo bookings over the last 90 days, only if there are none yet."""
    with _FileLock():
        data = load()
        if data["bookings"]:
            return {"inserted": 0, "skipped": True,
                    "reason": "The data file already has bookings."}
        rnd = random.Random(20240501)  # deterministic demo data
        today = date.today()
        inserted = 0
        for offset in range(89, -1, -1):
            day = today - timedelta(days=offset)
            if day.weekday() >= 5:
                continue  # weekends: rooms are closed
            n = rnd.choice([0, 1, 2, 2, 3, 3, 4, 5])
            used = []  # (room, start, end) to avoid overlaps in demo data
            for _ in range(n):
                rid = rnd.choices(list(DEMO_ROOM_WEIGHTS), weights=list(DEMO_ROOM_WEIGHTS.values()))[0]
                start = rnd.randrange(OPEN_MIN, CLOSE_MIN - SLOT_MIN, SLOT_MIN)
                length = rnd.choice([30, 60, 60, 60, 90, 120])
                end = min(start + length, CLOSE_MIN)
                if any(u[0] == rid and overlaps(start, end, u[1], u[2]) for u in used):
                    continue
                used.append((rid, start, end))
                rec = {
                    "id": data["next_id"],
                    "room": rid,
                    "date": day.isoformat(),
                    "start": hhmm(start),
                    "end": hhmm(end),
                    "booker": rnd.choice(DEMO_BOOKERS),
                    "title": rnd.choice(DEMO_TITLES),
                    "created": datetime.now().isoformat(timespec="seconds"),
                }
                data["next_id"] += 1
                if rnd.random() < 0.12:  # ~12% cancelled
                    rec["cancelled"] = True
                    rec["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
                data["bookings"].append(rec)
                inserted += 1
        save(data)
    return {"inserted": inserted}


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
/* ---- tabs */
nav.tabs{display:flex;gap:6px;background:#fff;border-bottom:1px solid var(--line);padding:0 20px}
nav.tabs button{background:transparent;color:#4a5a6a;border:0;border-bottom:3px solid transparent;border-radius:0;padding:11px 16px;font-weight:600}
nav.tabs button.active{color:#1f3a5f;border-bottom-color:#1f3a5f}
/* ---- dashboard */
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:14px}
.kpi{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi .v{font-size:24px;font-weight:700;color:#1f3a5f}
.kpi .k{font-size:12px;color:#6b7a8a;text-transform:uppercase;letter-spacing:.04em}
.summary{background:#eef4fb;border:1px solid #c9dbf0;border-radius:10px;padding:12px 14px;margin-bottom:14px;font-size:14px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:14px}
.pill{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;text-transform:uppercase;letter-spacing:.03em}
.pill.heavy{background:#fde8e8;color:#a32020}
.pill.balanced{background:#e8f0fb;color:#1f4f8a}
.pill.under{background:#fff4d6;color:#8a6100}
.rec{font-size:13px;color:#4a5a6a;margin:4px 0 10px}
.ubar{height:14px;background:#eef2f7;border-radius:7px;overflow:hidden;margin:3px 0 2px}
.ubar span{display:block;height:100%;background:#2e9e5b}
.ubar span.heavy{background:#d64545}
.ubar span.under{background:#e0a800}
.empty{background:#fff;border:1px dashed var(--line);border-radius:10px;padding:26px;text-align:center;color:#6b7a8a}
svg text{font:11px system-ui,sans-serif;fill:#4a5a6a}
</style></head><body>
<header><h1>Meeting Room Booking</h1>
<p>Aspen (4) &middot; Birch (6) &middot; Cedar (10) &middot; Dune (20) &nbsp;|&nbsp; 08:00&ndash;18:00, 30-min slots, max 4 h, up to 60 days ahead</p></header>
<nav class="tabs">
  <button id="tab-bookings" class="active" data-tab="bookings">Bookings</button>
  <button id="tab-dashboard" data-tab="dashboard">Dashboard</button>
</nav>
<main>
<div id="view-bookings">
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
</div>

<div id="view-dashboard" style="display:none">
  <div class="bar">
    <div><label for="d_start">Start</label><input type="date" id="d_start"></div>
    <div><label for="d_end">End</label><input type="date" id="d_end"></div>
    <div><button id="d_apply">Apply</button></div>
    <div><button class="ghost" data-preset="7">Last 7 days</button></div>
    <div><button class="ghost" data-preset="30">Last 30 days</button></div>
    <div><button class="ghost" data-preset="90">Last 90 days</button></div>
    <div><button class="ghost" data-preset="month">This month</button></div>
    <div><button class="ghost" data-preset="all">All time</button></div>
  </div>
  <div id="d_msg" class="msg"></div>
  <div id="d_body"></div>
</div>
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
</script>
<script>
/* ================= Dashboard tab (inline SVG/CSS only, no libraries) ===== */
const D = { data: null };
const fmt1 = n => (Math.round(n*10)/10).toString();
const esc2 = s => String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function dmsg(text, kind){ const m=$('#d_msg'); m.className='msg '+(kind||''); m.textContent=text||''; }

/* Horizontal bar chart: rows = [{label, value, text}] */
function hbar(rows, opts){
  opts = opts || {};
  const max = Math.max(1, ...rows.map(r=>r.value));
  const rowH = 26, labelW = 90, valW = 70, w = 520;
  const h = rows.length*rowH + 6;
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" role="img" aria-label="${esc2(opts.title||'bar chart')}">`;
  rows.forEach((r,i)=>{
    const y = i*rowH + 4;
    const bw = Math.max(0, (w-labelW-valW) * (r.value/max));
    out += `<text x="0" y="${y+14}">${esc2(r.label)}</text>`;
    out += `<rect x="${labelW}" y="${y+3}" width="${bw}" height="16" rx="3" fill="${opts.color||'#1f3a5f'}"></rect>`;
    out += `<text x="${labelW+bw+6}" y="${y+15}">${esc2(r.text!=null?r.text:r.value)}</text>`;
  });
  return out + '</svg>';
}

/* Vertical bar chart: labels along x, values up */
function vbar(items, opts){
  opts = opts || {};
  const max = Math.max(1, ...items.map(i=>i.value));
  const w = 520, h = 170, pad = 24, bw = (w-pad*2)/items.length;
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" role="img" aria-label="${esc2(opts.title||'bar chart')}">`;
  items.forEach((it,i)=>{
    const bh = (h-pad-18) * (it.value/max);
    const x = pad + i*bw + bw*0.15, y = h-pad-bh;
    out += `<rect x="${x}" y="${y}" width="${bw*0.7}" height="${bh}" rx="2" fill="${opts.color||'#2e6da4'}"><title>${esc2(it.label)}: ${it.value}</title></rect>`;
    if(it.value) out += `<text x="${x+bw*0.35}" y="${y-3}" text-anchor="middle">${it.value}</text>`;
    out += `<text x="${x+bw*0.35}" y="${h-8}" text-anchor="middle">${esc2(it.label)}</text>`;
  });
  return out + '</svg>';
}

/* Heatmap: weekday rows x hour columns */
function heatmapSvg(matrix, hours){
  const cell = 40, labelW = 44, top = 18;
  const w = labelW + hours.length*cell, h = top + 7*cell + 4;
  const max = Math.max(1, ...matrix.flat());
  let out = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" role="img" aria-label="Bookings by weekday and hour">`;
  hours.forEach((hr,j)=>{ out += `<text x="${labelW+j*cell+cell/2}" y="12" text-anchor="middle">${hr}</text>`; });
  matrix.forEach((row,i)=>{
    out += `<text x="0" y="${top+i*cell+cell/2+4}">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][i]}</text>`;
    row.forEach((v,j)=>{
      const a = v ? 0.15 + 0.85*(v/max) : 0;
      out += `<rect x="${labelW+j*cell+1}" y="${top+i*cell+1}" width="${cell-2}" height="${cell-2}" rx="3" fill="rgba(31,58,95,${a.toFixed(2)})"><title>${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][i]} ${hours[j]}: ${v}</title></rect>`;
      if(v) out += `<text x="${labelW+j*cell+cell/2}" y="${top+i*cell+cell/2+4}" text-anchor="middle" fill="${a>0.55?'#fff':'#1d2733'}">${v}</text>`;
    });
  });
  return out + '</svg>';
}

function summaryText(d){
  const t = d.totals, r = d.range;
  if(!t.bookings) return `No bookings in this range (${r.start} to ${r.end}).`;
  const busiestDay = d.by_weekday.slice().sort((a,b)=>b.bookings-a.bookings)[0];
  const busiestHour = d.by_hour.slice().sort((a,b)=>b.bookings-a.bookings)[0];
  const heavy = d.per_room.filter(x=>x.status==='heavily used').map(x=>x.name);
  const under = d.per_room.filter(x=>x.status==='underused').map(x=>x.name);
  let s = `Between ${r.start} and ${r.end} there were ${t.bookings} bookings totalling ${fmt1(t.hours)} reserved hours`;
  s += `, and ${t.cancelled} cancellation${t.cancelled===1?'':'s'} (${fmt1(t.cancellation_rate_pct)}%).`;
  s += ` ${t.busiest_room} was the busiest room and ${t.quietest_room} the quietest.`;
  if(busiestDay.bookings) s += ` ${busiestDay.name} was the busiest day (${busiestDay.bookings} bookings)`;
  if(busiestHour.bookings) s += ` and ${busiestHour.label} the busiest hour (${busiestHour.bookings}).`;
  if(heavy.length) s += ` Heavily used: ${heavy.join(', ')}.`;
  if(under.length) s += ` Underused: ${under.join(', ')}.`;
  return s;
}

function recommendation(d){
  const heavy = d.per_room.filter(x=>x.status==='heavily used').sort((a,b)=>b.utilisation_pct-a.utilisation_pct);
  const under = d.per_room.filter(x=>x.status==='underused').sort((a,b)=>a.utilisation_pct-b.utilisation_pct);
  if(heavy.length && under.length){
    return `${heavy[0].name} is heavily used — consider moving some meetings to ${under[0].name} (underused).`;
  }
  if(heavy.length) return `${heavy[0].name} is heavily used — consider adding capacity or shortening meetings.`;
  if(under.length) return `${under[0].name} is underused — consider consolidating meetings there or repurposing it.`;
  return 'Room usage is balanced across all rooms — no allocation change needed.';
}

function renderDashboard(d){
  D.data = d;
  const body = $('#d_body');
  if(d.empty){
    body.innerHTML = `<div class="empty"><p><strong>No bookings in this range</strong> (${esc2(d.range.start)} to ${esc2(d.range.end)}).</p>
      <p class="hint">Pick another date range, or load a realistic demo set to see the charts.</p>
      <button id="d_demo">Load demo data</button></div>`;
    const b = $('#d_demo'); if(b) b.onclick = loadDemo;
    return;
  }
  const t = d.totals;
  const kpis = [
    ['Total bookings', t.bookings],
    ['Hours reserved', fmt1(t.hours)],
    ['Cancellation rate', fmt1(t.cancellation_rate_pct)+'%'],
    ['Busiest room', t.busiest_room || '—'],
    ['Quietest room', t.quietest_room || '—'],
  ].map(([k,v])=>`<div class="kpi"><div class="k">${k}</div><div class="v">${esc2(v)}</div></div>`).join('');

  const roomBars = hbar(d.per_room.map(r=>({label:r.name, value:r.bookings})), {title:'Bookings per room'});
  const hourBars = hbar(d.per_room.map(r=>({label:r.name, value:r.hours, text:fmt1(r.hours)+' h'})), {title:'Hours reserved per room', color:'#2e9e5b'});

  const util = d.per_room.map(r=>{
    const cls = r.status==='heavily used'?'heavy':(r.status==='underused'?'under':'');
    const pill = r.status==='heavily used'?'heavy':(r.status==='underused'?'under':'balanced');
    return `<div><div><strong>${esc2(r.name)}</strong> <span class="pill ${pill}">${esc2(r.status)}</span>
      <span class="hint">${fmt1(r.utilisation_pct)}% of ${fmt1(r.available_hours)} available h</span></div>
      <div class="ubar"><span class="${cls}" style="width:${Math.min(100,r.utilisation_pct)}%"></span></div></div>`;
  }).join('');

  const wdBars = vbar(d.by_weekday.map(w=>({label:w.name, value:w.bookings})), {title:'Bookings by weekday'});
  const hrBars = vbar(d.by_hour.map(h=>({label:h.label, value:h.bookings})), {title:'Bookings by hour of day', color:'#8a5a00'});
  const heat = heatmapSvg(d.heatmap, d.by_hour.map(h=>h.label));
  const top = d.top_slots.length
    ? '<ol>' + d.top_slots.map(s=>`<li>${esc2(s.label)} — ${s.count} booking${s.count===1?'':'s'}</li>`).join('') + '</ol>'
    : '<p class="hint">No busy slots in this range.</p>';
  const cancelBars = hbar(d.cancelled_by_room.map(r=>({label:r.name, value:r.cancelled})), {title:'Cancellations per room', color:'#d64545'});

  body.innerHTML = `
    <div class="summary">${esc2(summaryText(d))}</div>
    <div class="kpis">${kpis}</div>
    <div class="card"><h2 style="margin-top:0">Room allocation advice</h2>
      <p class="rec">${esc2(recommendation(d))}</p>${util}
      <p class="hint">Utilisation = reserved hours / available hours. Available hours = weekdays in the range &times; 10 h (08:00&ndash;18:00); weekends count as 0 available hours. Status: heavily used &ge; 60%, underused &le; 20%, otherwise balanced.</p>
    </div>
    <div class="grid2">
      <div class="card"><h2 style="margin-top:0">Bookings per room</h2>${roomBars}</div>
      <div class="card"><h2 style="margin-top:0">Hours reserved per room</h2>${hourBars}</div>
      <div class="card"><h2 style="margin-top:0">Busiest days (bookings by weekday)</h2>${wdBars}</div>
      <div class="card"><h2 style="margin-top:0">Busiest times (bookings by hour)</h2>${hrBars}</div>
    </div>
    <div class="card"><h2 style="margin-top:0">Weekday &times; hour heatmap</h2>${heat}
      <h2>Top 5 busiest slots</h2>${top}</div>
    <div class="card"><h2 style="margin-top:0">Cancellations</h2>
      <p>${t.cancelled} cancellation${t.cancelled===1?'':'s'} in this period &mdash; ${fmt1(t.cancellation_rate_pct)}% of all bookings in the range.</p>
      ${cancelBars}</div>`;
}

function loadDashboard(){
  const s = $('#d_start').value, e = $('#d_end').value;
  dmsg('');
  api(`/api/dashboard?start=${encodeURIComponent(s)}&end=${encodeURIComponent(e)}`)
    .then(renderDashboard)
    .catch(err=>{ dmsg(err.message,'err'); $('#d_body').innerHTML=''; });
}
function setRange(days){
  const end = new Date(), start = new Date();
  if(days === 'month'){ start.setDate(1); }
  else if(days === 'all'){ start.setFullYear(start.getFullYear()-5); }
  else { start.setDate(end.getDate() - (days-1)); }
  $('#d_start').value = iso(start); $('#d_end').value = iso(end);
  loadDashboard();
}
function loadDemo(){
  dmsg('');
  api('/api/demo-data',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>{ dmsg(r.inserted ? `Inserted ${r.inserted} demo bookings.` : (r.reason || 'Demo data not inserted.'), r.inserted?'ok':'err');
               setRange(90); })
    .catch(err=>dmsg(err.message,'err'));
}
function showTab(name){
  $('#view-bookings').style.display = name==='bookings' ? '' : 'none';
  $('#view-dashboard').style.display = name==='dashboard' ? '' : 'none';
  document.querySelectorAll('nav.tabs button').forEach(b=>b.classList.toggle('active', b.dataset.tab===name));
  if(name==='dashboard' && !D.data) loadDashboard();
}

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
  // tabs + dashboard controls
  document.querySelectorAll('nav.tabs button').forEach(b=>{ b.onclick=()=>showTab(b.dataset.tab); });
  document.querySelectorAll('[data-preset]').forEach(b=>{ b.onclick=()=>setRange(b.dataset.preset); });
  $('#d_apply').onclick=loadDashboard;
  setRange(30);
  load();
});
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "BookingSystem/2.0"

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
            if u.path == "/api/cancellations":
                start = (q.get("start") or [""])[0] or None
                end = (q.get("end") or [""])[0] or None
                if start:
                    start = parse_date(start).isoformat()
                if end:
                    end = parse_date(end).isoformat()
                if start and end and start > end:
                    raise BookingError("start (%s) must be on or before end (%s)." % (start, end))
                rows = list_cancellations(start, end)
                return self._json(200, {"cancellations": [self._decorate(b) for b in rows],
                                        "count": len(rows)})
            if u.path == "/api/dashboard":
                start = (q.get("start") or [""])[0] or None
                end = (q.get("end") or [""])[0] or None
                return self._json(200, dashboard(start, end))
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
            if u.path == "/api/demo-data":
                return self._json(200, demo_data())
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
