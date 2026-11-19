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


# ---------------------------------------------------------------- dashboard analytics
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HOURS = list(range(8, 18))          # 08:00 .. 17:00 (the 17:00 hour ends at 18:00)
DAY_HOURS = (DAY_END - DAY_START) / 60.0   # 10 available hours per weekday
MAX_RANGE_DAYS = 366
HEAVY = 0.75
LIGHT = 0.25


def _pct(x):
    return int(round(x * 100))


def _hours(b):
    return (b["end"] - b["start"]) / 60.0


def _hour_overlap(b, hour):
    """Hours of booking b that fall inside the clock hour starting at `hour`."""
    lo = max(b["start"], hour * 60)
    hi = min(b["end"], (hour + 1) * 60)
    return max(0, hi - lo) / 60.0


def _status(utilisation):
    if utilisation >= HEAVY:
        return "Heavily used"
    if utilisation <= LIGHT:
        return "Underused"
    return "Balanced"


def _empty_stats(start_s, end_s, error):
    return {
        "range": {"start": start_s, "end": end_s, "days": 0, "weekdays": 0, "error": error},
        "totals": {"bookings": 0, "cancelled": 0, "all_created": 0, "cancel_rate": 0.0,
                   "hours_reserved": 0.0, "avg_hours": 0.0, "unique_bookers": 0},
        "per_room": [{"room": n, "capacity": c, "bookings": 0, "hours": 0.0, "cancelled": 0,
                      "cancel_rate": 0.0, "utilisation": 0.0, "avg_hours": 0.0,
                      "busiest_weekday": "-", "busiest_hour": "-", "share_of_hours": 0.0,
                      "status": "Underused"} for n, c in ROOMS],
        "by_weekday": [{"name": WEEKDAY_NAMES[i], "short": WEEKDAY_SHORT[i], "bookings": 0, "hours": 0.0}
                       for i in range(7)],
        "by_hour": [{"hour": h, "label": "%02d:00" % h, "bookings": 0, "hours": 0.0} for h in HOURS],
        "by_room_hour": [{"room": n, "cells": [0] * len(HOURS)} for n, _c in ROOMS],
        "by_week": [],
        "top_days": [],
        "busiest_day": "-",
        "busiest_hour": "-",
        "quietest_room": "-",
        "busiest_room": "-",
        "recommendations": [error] if error else ["No bookings in this range yet."],
    }


def dashboard_stats(start_s, end_s, today=None):
    """Aggregate booking records for the inclusive date range start_s..end_s.

    Pure read-only function: it never writes the data file. Cancelled bookings are
    counted in the cancellation rate but never as usage (bookings/hours).
    """
    today = today or date.today()
    try:
        start = parse_date(start_s)
        end = parse_date(end_s)
    except ValueError as e:
        return _empty_stats(start_s, end_s, str(e))
    if start > end:
        return _empty_stats(start.isoformat(), end.isoformat(),
                            "Start date must be on or before the end date.")
    days = (end - start).days + 1
    if days > MAX_RANGE_DAYS:
        return _empty_stats(start.isoformat(), end.isoformat(),
                            "Range is too long - please pick at most %d days." % MAX_RANGE_DAYS)

    weekdays = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            weekdays += 1
        d += timedelta(days=1)

    data = load()
    in_range = []
    for b in data["bookings"]:
        try:
            bd = parse_date(b.get("date"))
        except ValueError:
            continue
        if start <= bd <= end:
            in_range.append(b)

    active = [b for b in in_range if not b.get("cancelled")]
    cancelled = [b for b in in_range if b.get("cancelled")]

    # ---- per room
    per_room = []
    room_hours = {}
    room_bookings = {}
    room_cancelled = {}
    room_weekday = {}
    room_hour = {}
    room_hour_matrix = {}
    for name, cap in ROOMS:
        room_hours[name] = 0.0
        room_bookings[name] = 0
        room_cancelled[name] = 0
        room_weekday[name] = [0] * 7
        room_hour[name] = [0] * len(HOURS)
        room_hour_matrix[name] = [0] * len(HOURS)
    for b in active:
        name = b.get("room")
        if name not in room_hours:
            continue
        room_bookings[name] += 1
        room_hours[name] += _hours(b)
        room_weekday[name][parse_date(b["date"]).weekday()] += 1
        for i, h in enumerate(HOURS):
            if _hour_overlap(b, h) > 0:
                room_hour[name][i] += 1
                room_hour_matrix[name][i] += 1
    for b in cancelled:
        name = b.get("room")
        if name in room_cancelled:
            room_cancelled[name] += 1

    total_hours = sum(room_hours.values())
    available = weekdays * DAY_HOURS
    for name, cap in ROOMS:
        hrs = room_hours[name]
        nb = room_bookings[name]
        nc = room_cancelled[name]
        util = (hrs / available) if available else 0.0
        wd = room_weekday[name]
        busiest_wd = WEEKDAY_NAMES[wd.index(max(wd))] if nb else "-"
        hr = room_hour[name]
        busiest_hr = ("%02d:00" % HOURS[hr.index(max(hr))]) if nb else "-"
        per_room.append({
            "room": name,
            "capacity": cap,
            "bookings": nb,
            "hours": round(hrs, 2),
            "cancelled": nc,
            "cancel_rate": round(nc / float(nb + nc), 4) if (nb + nc) else 0.0,
            "utilisation": round(util, 4),
            "avg_hours": round(hrs / nb, 2) if nb else 0.0,
            "busiest_weekday": busiest_wd,
            "busiest_hour": busiest_hr,
            "share_of_hours": round(hrs / total_hours, 4) if total_hours else 0.0,
            "status": _status(util),
        })

    # ---- weekday / hour buckets
    by_weekday = [{"name": WEEKDAY_NAMES[i], "short": WEEKDAY_SHORT[i], "bookings": 0, "hours": 0.0}
                  for i in range(7)]
    by_hour = [{"hour": h, "label": "%02d:00" % h, "bookings": 0, "hours": 0.0} for h in HOURS]
    day_counts = {}
    day_hours = {}
    for b in active:
        bd = parse_date(b["date"])
        wd = bd.weekday()
        by_weekday[wd]["bookings"] += 1
        by_weekday[wd]["hours"] += _hours(b)
        day_counts[bd] = day_counts.get(bd, 0) + 1
        day_hours[bd] = day_hours.get(bd, 0.0) + _hours(b)
        for i, h in enumerate(HOURS):
            ov = _hour_overlap(b, h)
            if ov > 0:
                by_hour[i]["bookings"] += 1
                by_hour[i]["hours"] += ov
    for e in by_weekday:
        e["hours"] = round(e["hours"], 2)
    for e in by_hour:
        e["hours"] = round(e["hours"], 2)

    # ---- weekly trend (ISO weeks overlapping the range)
    by_week = []
    wk = start - timedelta(days=start.weekday())
    while wk <= end:
        by_week.append({"week_start": wk.isoformat(), "bookings": 0, "hours": 0.0})
        wk += timedelta(days=7)
    week_index = {w["week_start"]: w for w in by_week}
    for b in active:
        bd = parse_date(b["date"])
        key = (bd - timedelta(days=bd.weekday())).isoformat()
        if key in week_index:
            week_index[key]["bookings"] += 1
            week_index[key]["hours"] += _hours(b)
    for w in by_week:
        w["hours"] = round(w["hours"], 2)

    # ---- top days
    top_days = []
    for bd in sorted(day_counts, key=lambda x: (-day_counts[x], -day_hours[x], x))[:5]:
        top_days.append({"date": bd.isoformat(), "weekday": WEEKDAY_NAMES[bd.weekday()],
                         "bookings": day_counts[bd], "hours": round(day_hours[bd], 2)})

    # ---- headline figures
    all_created = len(active) + len(cancelled)
    cancel_rate = (len(cancelled) / float(all_created)) if all_created else 0.0
    busiest_day = "-"
    if active:
        counts = [e["bookings"] for e in by_weekday]
        busiest_day = WEEKDAY_NAMES[counts.index(max(counts))]
    busiest_hour = "-"
    if active:
        hcounts = [e["bookings"] for e in by_hour]
        busiest_hour = by_hour[hcounts.index(max(hcounts))]["label"]
    busiest_room = "-"
    quietest_room = "-"
    if active:
        ranked = sorted(per_room, key=lambda r: (-r["hours"], r["room"]))
        busiest_room = ranked[0]["room"]
        quietest_room = ranked[-1]["room"]

    # ---- recommendations
    recs = []
    if not active and not cancelled:
        recs.append("No bookings in this range yet - try a wider date range or load the demo data "
                    "(python3 app.py --demo).")
    else:
        if weekdays >= 5:
            for r in sorted(per_room, key=lambda x: -x["utilisation"]):
                if r["utilisation"] >= HEAVY:
                    small = min(per_room, key=lambda x: (x["utilisation"], x["capacity"]))
                    recs.append(
                        "%s is %d%% booked on %s - consider moving small meetings to %s "
                        "(%d seats, %d%% used)." % (
                            r["room"], _pct(r["utilisation"]), r["busiest_weekday"],
                            small["room"], small["capacity"], _pct(small["utilisation"])))
            for r in sorted(per_room, key=lambda x: x["utilisation"]):
                if r["utilisation"] <= LIGHT:
                    recs.append(
                        "%s is used only %d%% of available hours - consider reallocating it or "
                        "offering it to another team." % (r["room"], _pct(r["utilisation"])))
        if cancel_rate > 0.10:
            worst = max(per_room, key=lambda r: (r["cancelled"], r["room"]))
            recs.append(
                "Cancellation rate is %d%% (%d of %d) - mostly %s; check whether recurring "
                "bookings are still needed." % (
                    _pct(cancel_rate), len(cancelled), all_created, worst["room"]))
        if active and busiest_day != "-":
            recs.append("%s is the busiest weekday (%d bookings) - keep the most rooms free then." % (
                busiest_day, by_weekday[WEEKDAY_NAMES.index(busiest_day)]["bookings"]))
        if active and busiest_hour != "-":
            recs.append("Most meetings start around %s - avoid scheduling maintenance in that hour."
                        % busiest_hour)
        if not recs:
            recs.append("Usage looks balanced across rooms - no change to room allocation needed.")

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat(), "days": days,
                  "weekdays": weekdays, "error": None},
        "totals": {
            "bookings": len(active),
            "cancelled": len(cancelled),
            "all_created": all_created,
            "cancel_rate": round(cancel_rate, 4),
            "hours_reserved": round(total_hours, 2),
            "avg_hours": round(total_hours / len(active), 2) if active else 0.0,
            "unique_bookers": len(set(b.get("booker", "") for b in active)),
        },
        "per_room": per_room,
        "by_weekday": by_weekday,
        "by_hour": by_hour,
        "by_room_hour": [{"room": n, "cells": room_hour_matrix[n]} for n, _c in ROOMS],
        "by_week": by_week,
        "top_days": top_days,
        "busiest_day": busiest_day,
        "busiest_hour": busiest_hour,
        "quietest_room": quietest_room,
        "busiest_room": busiest_room,
        "recommendations": recs,
    }


def resolve_range(start_s=None, end_s=None, days=None, today=None):
    """Turn query parameters into (start_iso, end_iso). Defaults to the last 30 days."""
    today = today or date.today()
    if days:
        try:
            n = int(days)
        except (TypeError, ValueError):
            n = 30
        n = max(1, min(n, MAX_RANGE_DAYS))
        return (today - timedelta(days=n - 1)).isoformat(), today.isoformat()
    end = today
    if end_s:
        try:
            end = parse_date(end_s)
        except ValueError:
            end = today
    start = end - timedelta(days=29)
    if start_s:
        try:
            start = parse_date(start_s)
        except ValueError:
            start = end - timedelta(days=29)
    return start.isoformat(), end.isoformat()


def seed_demo(path=None, today=None, count=420):
    """Write realistic demo bookings over the last 90 days (demo helper, --demo only).

    ~420 bookings keeps the dashboard realistic: Cedar/Birch busy, Dune quiet.
    """
    import random
    rnd = random.Random(20240517)
    today = today or date.today()
    titles = ["Weekly sync", "1:1", "Design review", "Sprint planning", "Retro", "Interview",
              "Client call", "Budget review", "Roadmap", "Standup", "Workshop", "Training",
              "Board meeting", "Hiring panel", "Demo", "Post-mortem"]
    people = ["Ann", "Bob", "Chen", "Dana", "Eli", "Fatima", "Gus", "Hana", "Ivan", "Jo",
              "Kim", "Lena", "Mo", "Nina", "Omar", "Pia"]
    # room popularity: Cedar and Birch are busy, Dune is rarely used
    weights = {"Aspen": 0.20, "Birch": 0.28, "Cedar": 0.44, "Dune": 0.08}
    rooms = [r[0] for r in ROOMS]
    weekdays = [today - timedelta(days=i) for i in range(90)]
    weekdays = [d for d in weekdays if d.weekday() < 5]
    bookings = []
    used = set()
    attempts = 0
    while len(bookings) < count and attempts < count * 40:
        attempts += 1
        day = rnd.choice(weekdays)
        room = rnd.choices(rooms, weights=[weights[r] for r in rooms])[0]
        start_hour = rnd.choice([8, 9, 9, 10, 10, 11, 13, 14, 14, 15, 16])
        length = rnd.choice([30, 30, 60, 60, 60, 90, 120])
        start = start_hour * 60
        end = start + length
        if end > DAY_END:
            continue
        key = (room, day.isoformat(), start)
        if key in used:
            continue
        clash = False
        for (r2, d2, s2), b in zip(used, bookings):
            if r2 == room and d2 == day.isoformat() and s2 < end and start < s2 + (b["end"] - b["start"]):
                clash = True
                break
        if clash:
            continue
        used.add(key)
        created = datetime.combine(day - timedelta(days=rnd.randint(1, 10)),
                                   datetime.min.time()).replace(hour=rnd.randint(8, 17))
        b = {
            "id": uuid.uuid4().hex[:12],
            "room": room,
            "date": day.isoformat(),
            "start": start,
            "end": end,
            "title": rnd.choice(titles),
            "booker": rnd.choice(people),
            "created": created.isoformat(timespec="seconds"),
            "cancelled": False,
        }
        if rnd.random() < 0.15:
            b["cancelled"] = True
            b["cancelled_at"] = (created + timedelta(days=rnd.randint(0, 3))).isoformat(timespec="seconds")
        bookings.append(b)
    bookings.sort(key=lambda b: (b["date"], b["start"]))
    target = path or DATA_FILE
    with LOCK:
        save({"bookings": bookings})
    return len(bookings)


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
/* dashboard */
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:18px}
.kpi{background:#fff;border-radius:8px;padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.12);flex:1 1 150px;min-width:140px}
.kpi .k{font-size:12px;color:#667;text-transform:uppercase;letter-spacing:.04em}
.kpi .v{font-size:22px;font-weight:700;margin-top:4px;color:#1f3a5f}
.kpi .s{font-size:12px;color:#778;margin-top:2px}
.bars{display:flex;flex-direction:column;gap:6px}
.bar-row{display:flex;align-items:center;gap:8px;font-size:13px}
.bar-row .lbl{width:110px;flex:0 0 110px;color:#334}
.bar-track{flex:1;background:#eef2f7;border-radius:4px;height:18px;position:relative;overflow:hidden}
.bar-fill{height:100%;background:#1f6feb;border-radius:4px}
.bar-fill.alt{background:#2e9e6b}
.bar-fill.warnc{background:#c62828}
.bar-row .val{width:78px;flex:0 0 78px;text-align:right;color:#445;font-variant-numeric:tabular-nums}
.vbars{display:flex;align-items:flex-end;gap:6px;height:170px;padding-top:6px}
.vbar{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}
.vbar .col{width:100%;background:#1f6feb;border-radius:3px 3px 0 0;min-height:2px}
.vbar .cap{font-size:11px;color:#556;margin-top:4px;white-space:nowrap}
.vbar .num{font-size:11px;color:#334;margin-bottom:2px}
.heat td{text-align:center;font-variant-numeric:tabular-nums}
.heat th{text-align:center}
.heat td.rh{text-align:left;background:#eef2f7;font-weight:600}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600}
.badge.heavy{background:#fde7e7;color:#a01f1f}
.badge.balanced{background:#e6f6ea;color:#1b6b32}
.badge.light{background:#fff6e0;color:#7a5a00}
.quick a{display:inline-block;margin-right:8px;padding:6px 12px;border-radius:5px;background:#eef2f7;color:#1f3a5f;text-decoration:none;font-size:13px}
.quick a.on{background:#1f6feb;color:#fff}
.recs{margin:0;padding-left:20px;font-size:14px;line-height:1.55}
.recs li{margin-bottom:6px}
.two{display:flex;gap:18px;flex-wrap:wrap}
.two>div{flex:1 1 380px;min-width:300px}
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def page(title, body, msg=""):
    return """<!doctype html><html><head><meta charset="utf-8">
<title>%s - Room Booking</title><style>%s</style></head><body>
<header><h1>Meeting Room Booking</h1>
<nav><a href="/">Availability</a><a href="/book">Book a room</a>
<a href="/bookings">All bookings / cancel</a><a href="/my">My bookings</a>
<a href="/dashboard">Dashboard</a></nav></header>
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


def _hbar(rows, unit=""):
    """rows: list of (label, value, display). Pure HTML/CSS horizontal bars."""
    top = max([r[1] for r in rows] + [0]) or 1
    out = ['<div class="bars">']
    for label, value, display, cls in rows:
        width = (value / float(top)) * 100.0 if top else 0
        out.append('<div class="bar-row"><span class="lbl">%s</span>'
                   '<span class="bar-track"><span class="bar-fill %s" style="width:%.1f%%"></span></span>'
                   '<span class="val">%s</span></div>' % (esc(label), cls, width, esc(display)))
    out.append("</div>")
    return "".join(out)


def _vbars(entries, value_key, label_key, fmt):
    top = max([e[value_key] for e in entries] + [0]) or 1
    out = ['<div class="vbars">']
    for e in entries:
        h = (e[value_key] / float(top)) * 100.0
        out.append('<div class="vbar"><span class="num">%s</span>'
                   '<span class="col" style="height:%.1f%%"></span>'
                   '<span class="cap">%s</span></div>' % (esc(fmt(e[value_key])), h, esc(e[label_key])))
    out.append("</div>")
    return "".join(out)


def dashboard_html(start_s=None, end_s=None, days=None):
    start_iso, end_iso = resolve_range(start_s, end_s, days)
    st = dashboard_stats(start_iso, end_iso)
    rng = st["range"]
    tot = st["totals"]

    quick = []
    for n in (7, 30, 90):
        on = " on" if str(days or "") == str(n) else ""
        quick.append('<a class="%s" href="/dashboard?days=%d">%d days</a>' % (on.strip(), n, n))
    form = """<div class="card"><h2>Date range</h2>
<form method="get" action="/dashboard">
<label>From</label><input type="date" name="start" value="%s" required>
<label>To</label><input type="date" name="end" value="%s" required>
<button type="submit">Apply</button></form>
<p class="quick" style="margin:12px 0 0">Quick range: %s</p>
<p class="muted">Showing %s to %s (%d days, %d weekdays). Cancelled bookings are excluded from
usage (bookings and hours) but counted in the cancellation rate.</p></div>""" % (
        esc(rng["start"]), esc(rng["end"]), "".join(quick),
        esc(rng["start"]), esc(rng["end"]), rng["days"], rng["weekdays"])

    if rng.get("error"):
        return page("Dashboard", form + '<div class="card">%s</div>' % msg_html("err", rng["error"]))

    if tot["all_created"] == 0:
        empty = ('<div class="card"><h2>No bookings in this range</h2>%s</div>' % msg_html(
            "warn", "There are no bookings between %s and %s. Pick a wider range, or load demo data "
                    "with: python3 app.py --demo" % (rng["start"], rng["end"])))
        return page("Dashboard", form + empty)

    # ---- KPI cards
    kpis = [
        ("Total bookings", "%d" % tot["bookings"], "%d cancelled" % tot["cancelled"]),
        ("Hours reserved", "%.1f h" % tot["hours_reserved"], "avg %.1f h per booking" % tot["avg_hours"]),
        ("Cancellation rate", "%d%%" % _pct(tot["cancel_rate"]),
         "%d of %d created" % (tot["cancelled"], tot["all_created"])),
        ("Busiest day", st["busiest_day"], "by number of bookings"),
        ("Busiest time", st["busiest_hour"], "most bookings start here"),
        ("Most used room", st["busiest_room"], "least used: %s" % st["quietest_room"]),
        ("Unique bookers", "%d" % tot["unique_bookers"], "people who booked"),
    ]
    kpi_html = '<div class="kpis">' + "".join(
        '<div class="kpi"><div class="k">%s</div><div class="v">%s</div><div class="s">%s</div></div>'
        % (esc(k), esc(v), esc(s)) for k, v, s in kpis) + "</div>"

    # ---- per-room bars
    room_rows_b = [(r["room"], r["bookings"], "%d" % r["bookings"], "") for r in st["per_room"]]
    room_rows_h = [(r["room"], r["hours"], "%.1f h" % r["hours"], "alt") for r in st["per_room"]]
    room_charts = """<div class="card"><h2>Bookings per room</h2>%s</div>
<div class="card"><h2>Hours reserved per room</h2>%s</div>""" % (
        _hbar(room_rows_b), _hbar(room_rows_h))

    # ---- weekday / hour charts
    wd_chart = '<div class="card"><h2>Bookings by weekday</h2>%s</div>' % _vbars(
        st["by_weekday"], "bookings", "short", lambda v: "%d" % v)
    hr_chart = '<div class="card"><h2>Bookings by hour of day</h2>%s<p class="muted">A booking spanning 09:00-10:30 counts once in the 09:00 hour and once in the 10:00 hour.</p></div>' % _vbars(
        st["by_hour"], "bookings", "label", lambda v: "%d" % v)

    # ---- heatmap
    max_cell = max([max(r["cells"]) for r in st["by_room_hour"]] + [0]) or 1
    head = "".join("<th>%s</th>" % e["label"] for e in st["by_hour"])
    hrows = []
    for r in st["by_room_hour"]:
        cells = []
        for c in r["cells"]:
            alpha = (c / float(max_cell)) * 0.85 if c else 0
            style = "background:rgba(31,111,235,%.2f);color:%s" % (
                alpha, "#fff" if alpha > 0.55 else "#1d2733")
            cells.append('<td style="%s">%s</td>' % (style, c if c else ""))
        hrows.append("<tr><td class=\"rh\">%s</td>%s</tr>" % (esc(r["room"]), "".join(cells)))
    heat = """<div class="card"><h2>Room x hour heatmap (bookings)</h2><div class="grid-scroll">
<table class="heat"><tr><th>Room</th>%s</tr>%s</table></div>
<p class="muted">Darker blue = more bookings in that room and hour.</p></div>""" % (head, "".join(hrows))

    # ---- per-room table
    trows = []
    for r in st["per_room"]:
        cls = {"Heavily used": "heavy", "Underused": "light"}.get(r["status"], "balanced")
        trows.append("<tr><td>%s (%d)</td><td>%d</td><td>%.1f</td><td>%d%%</td><td>%d</td><td>%d%%</td>"
                     "<td>%s</td><td>%s</td><td><span class=\"badge %s\">%s</span></td></tr>" % (
                         esc(r["room"]), r["capacity"], r["bookings"], r["hours"],
                         _pct(r["utilisation"]), r["cancelled"], _pct(r["cancel_rate"]),
                         esc(r["busiest_weekday"]), esc(r["busiest_hour"]), cls, esc(r["status"])))
    room_table = """<div class="card"><h2>Room summary</h2><div class="grid-scroll"><table>
<tr><th>Room</th><th>Bookings</th><th>Hours</th><th>Utilisation</th><th>Cancelled</th>
<th>Cancel rate</th><th>Busiest day</th><th>Busiest time</th><th>Status</th></tr>%s</table></div>
<p class="muted">Utilisation = hours reserved / (weekdays in range x 10 available hours).
Heavily used = 75%% or more, Underused = 25%% or less.</p></div>""" % "".join(trows)

    # ---- recommendations
    recs = "<ul class=\"recs\">%s</ul>" % "".join("<li>%s</li>" % esc(r) for r in st["recommendations"])
    rec_card = '<div class="card"><h2>What to consider</h2>%s</div>' % recs

    # ---- weekly trend
    week_chart = '<div class="card"><h2>Weekly trend (bookings per week)</h2>%s</div>' % _vbars(
        [{"label": w["week_start"][5:], "bookings": w["bookings"]} for w in st["by_week"]],
        "bookings", "label", lambda v: "%d" % v)

    # ---- top days
    if st["top_days"]:
        td = "".join("<tr><td>%s</td><td>%s</td><td>%d</td><td>%.1f</td></tr>" % (
            esc(d["date"]), esc(d["weekday"]), d["bookings"], d["hours"]) for d in st["top_days"])
        top_days = ('<div class="card"><h2>Busiest days</h2><table><tr><th>Date</th><th>Weekday</th>'
                    '<th>Bookings</th><th>Hours</th></tr>%s</table></div>' % td)
    else:
        top_days = ""

    note = ('<div class="card">%s</div>' % msg_html(
        "warn", "Cancelled bookings are excluded from usage (bookings and hours) but counted in the "
                "cancellation rate."))

    body = (form + kpi_html + rec_card + room_charts +
            '<div class="two"><div>%s</div><div>%s</div></div>' % (wd_chart, hr_chart) +
            heat + room_table + week_chart + top_days + note)
    return page("Dashboard", body)


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
        elif u.path == "/dashboard":
            self._send(200, dashboard_html(q.get("start"), q.get("end"), q.get("days")))
        elif u.path == "/api/dashboard":
            s, e = resolve_range(q.get("start"), q.get("end"), q.get("days"))
            self._json(200, dashboard_stats(s, e))
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
    import sys
    if "--demo" in sys.argv[1:]:
        n = seed_demo()
        print("Wrote %d demo bookings to %s" % (n, DATA_FILE))
        print("Start the app with: python3 app.py  then open http://localhost:%d/dashboard" % PORT)
        return
    srv = make_server()
    print("Meeting room booking running at http://localhost:%d  (Ctrl+C to stop)" % srv.server_address[1])
    print("Data file: %s" % DATA_FILE)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
