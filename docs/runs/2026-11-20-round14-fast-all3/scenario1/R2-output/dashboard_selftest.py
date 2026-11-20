#!/usr/bin/env python3
"""Automated checks for the manager dashboard (v2 features of app.py).

Starts app.py on a free port with a temporary --data file, exercises the new
API (dashboard, cancellations, demo data, recorded cancellations) and the
dashboard UI markup, then prints PASS/FAIL per check and a final count.
Standard library only.  Run:  python3 dashboard_selftest.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
DATA = os.path.join(tempfile.mkdtemp(), "data.json")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
BASE = "http://127.0.0.1:%d" % PORT
TODAY = date.today()
D = (TODAY + timedelta(days=1)).isoformat()          # a bookable day
D2 = (TODAY + timedelta(days=2)).isoformat()
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(extra)) if not cond else ""))
    if not cond:
        fails.append(name)


def req(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data,
                               headers={"Content-Type": "application/json"},
                               method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def book(room, day, start, end, booker="Ann", title="T"):
    return req("/api/book", {"room": room, "date": day, "start": start, "end": end,
                             "booker": booker, "title": title})


srv = subprocess.Popen([sys.executable, APP, "--port", str(PORT), "--data", DATA],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    ready = False
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + "/api/rooms")
            ready = True
            break
        except Exception:
            time.sleep(0.1)
    check("server ready", ready)

    # ---- empty dashboard + defaults
    s, d0 = req("/api/dashboard")
    check("dashboard 200 with defaults", s == 200 and d0["range"]["end"] == TODAY.isoformat()
          and d0["range"]["days"] == 30, (s, d0.get("range")))
    check("empty dashboard flagged", d0["empty"] is True and d0["totals"]["bookings"] == 0)
    check("per_room has 4 rooms with all keys",
          len(d0["per_room"]) == 4 and all(
              set(["id", "name", "capacity", "bookings", "hours", "utilisation_pct",
                   "cancelled", "cancellation_rate_pct", "status"]) <= set(r)
              for r in d0["per_room"]), d0["per_room"])
    check("by_weekday 7 Mon..Sun", [w["name"] for w in d0["by_weekday"]] ==
          ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    check("by_hour 08..17", [h["hour"] for h in d0["by_hour"]] == list(range(8, 18)))
    check("heatmap 7x10", len(d0["heatmap"]) == 7 and all(len(r) == 10 for r in d0["heatmap"]))
    check("daily covers range", len(d0["daily"]) == 30 and d0["daily"][-1]["date"] == TODAY.isoformat())
    check("cancelled_by_room present", len(d0["cancelled_by_room"]) == 4)

    # ---- bad dates
    s, e = req("/api/dashboard?start=2024-05-10&end=2024-05-01")
    check("start>end -> 400 json error", s == 400 and "error" in e, (s, e))
    s, e = req("/api/dashboard?start=not-a-date&end=2024-05-01")
    check("malformed date -> 400", s == 400 and "error" in e, (s, e))
    s, e = req("/api/dashboard?start=2024-02-30&end=2024-03-01")
    check("impossible date -> 400", s == 400 and "error" in e, (s, e))

    # ---- bookings + recorded cancellation
    s, b1 = book("aspen", D, "09:00", "11:00", "Ann", "Standup")
    check("book aspen 2h", s == 201, (s, b1))
    s, b2 = book("dune", D, "09:00", "10:00", "Bob", "Big")
    check("book dune 1h", s == 201, (s, b2))
    s, b3 = book("birch", D2, "14:00", "15:00", "Cy", "Doomed")
    check("book birch (to cancel)", s == 201, (s, b3))
    s, c = req("/api/cancel", {"id": b3["id"]})
    check("cancel 200", s == 200 and c["cancelled"]["id"] == b3["id"], (s, c))

    # record kept in the data file
    with open(DATA, encoding="utf-8") as f:
        raw = json.load(f)
    kept = [b for b in raw["bookings"] if b["id"] == b3["id"]]
    check("cancelled record kept with flag", len(kept) == 1 and kept[0].get("cancelled") is True
          and "cancelled_at" in kept[0], kept)

    # hidden from bookings + availability, slot free again
    s, lst = req("/api/bookings?date=" + D2)
    check("cancelled hidden from /api/bookings", all(b["id"] != b3["id"] for b in lst["bookings"]), lst)
    s, av = req("/api/availability?date=%s&room=birch" % D2)
    slots = {x["start"]: x for x in av["rooms"][0]["slots"]}
    check("cancelled slot free again", slots["14:00"]["free"] and slots["14:30"]["free"])
    s, b4 = book("birch", D2, "14:00", "15:00", "Dee", "Rebook")
    check("rebook cancelled slot", s == 201, (s, b4))
    s, e = req("/api/cancel", {"id": b3["id"]})
    check("double cancel rejected", s == 400 and "error" in e, (s, e))

    # ---- cancellations endpoint
    s, cl = req("/api/cancellations?start=%s&end=%s" % (D, D2))
    check("cancellations endpoint lists record", s == 200 and cl["count"] == 1
          and cl["cancellations"][0]["id"] == b3["id"], (s, cl))
    s, cl = req("/api/cancellations?start=%s&end=%s" % (D, D))
    check("cancellations range filter", s == 200 and cl["count"] == 0, (s, cl))

    # ---- dashboard numbers
    s, d = req("/api/dashboard?start=%s&end=%s" % (D, D2))
    check("dashboard range echoed", s == 200 and d["range"]["start"] == D and d["range"]["end"] == D2
          and d["range"]["days"] == 2, d.get("range"))
    rooms = {r["id"]: r for r in d["per_room"]}
    check("aspen bookings/hours", rooms["aspen"]["bookings"] == 1 and rooms["aspen"]["hours"] == 2.0, rooms["aspen"])
    check("birch cancelled counted", rooms["birch"]["cancelled"] == 1 and rooms["birch"]["bookings"] == 1, rooms["birch"])
    check("birch cancellation rate 50%", rooms["birch"]["cancellation_rate_pct"] == 50.0, rooms["birch"])
    check("totals bookings/hours", d["totals"]["bookings"] == 3 and d["totals"]["hours"] == 4.0, d["totals"])
    check("totals cancelled + rate", d["totals"]["cancelled"] == 1
          and d["totals"]["cancellation_rate_pct"] == 25.0, d["totals"])
    check("busiest/quietest room", d["totals"]["busiest_room"] == "Aspen"
          and d["totals"]["quietest_room"] in ("Cedar", "Dune"), d["totals"])
    # utilisation: available hours = weekdays in range x 10
    wd = sum(1 for i in range(2) if (TODAY + timedelta(days=1 + i)).weekday() < 5)
    exp = round(100.0 * 2.0 / (wd * 10), 1) if wd else 0.0
    check("utilisation uses weekday hours", rooms["aspen"]["utilisation_pct"] == exp,
          (rooms["aspen"]["utilisation_pct"], exp, wd))
    check("status labels valid", all(r["status"] in ("heavily used", "balanced", "underused")
                                     for r in d["per_room"]))
    check("status matches thresholds", all(
        (r["status"] == "heavily used") == (r["utilisation_pct"] >= 60) and
        (r["status"] == "underused") == (r["utilisation_pct"] <= 20) for r in d["per_room"]))
    # by weekday / hour / heatmap
    wd1 = (TODAY + timedelta(days=1)).weekday()
    wd2 = (TODAY + timedelta(days=2)).weekday()
    check("by_weekday counts", d["by_weekday"][wd1]["bookings"] == 2
          and d["by_weekday"][wd2]["bookings"] == 1, d["by_weekday"])
    hours = {h["hour"]: h["bookings"] for h in d["by_hour"]}
    check("by_hour overlap counting", hours[9] == 2 and hours[10] == 1 and hours[14] == 1, hours)
    check("heatmap matches by_hour", sum(d["heatmap"][wd1]) == 3, d["heatmap"][wd1])
    check("top_slots <= 5 and sorted", len(d["top_slots"]) <= 5 and
          all(d["top_slots"][i]["count"] >= d["top_slots"][i + 1]["count"]
              for i in range(len(d["top_slots"]) - 1)), d["top_slots"])
    check("daily series counts", sum(x["bookings"] for x in d["daily"]) == 3, d["daily"])
    check("cancelled_by_room", {r["id"]: r["cancelled"] for r in d["cancelled_by_room"]}["birch"] == 1)

    # ---- demo data only when empty
    s, dm = req("/api/demo-data", {})
    check("demo-data skipped when data exists", s == 200 and dm["inserted"] == 0, (s, dm))

    # ---- UI markup
    with urllib.request.urlopen(BASE + "/") as r:
        html = r.read().decode()
    check("page has Dashboard tab", 'data-tab="dashboard"' in html and ">Dashboard<" in html)
    check("page has Bookings tab", 'data-tab="bookings"' in html)
    check("page has date range inputs", 'id="d_start"' in html and 'id="d_end"' in html)
    check("page has presets", all(p in html for p in ['data-preset="7"', 'data-preset="30"',
                                                      'data-preset="90"', 'data-preset="month"',
                                                      'data-preset="all"']))
    check("page has KPI cards", "kpis" in html and "Busiest room" in html and "Quietest room" in html)
    check("page has inline svg charts", "<svg" in html and "heatmapSvg" in html)
    check("page has empty state text", "No bookings in this range" in html)
    check("page has demo button", "Load demo data" in html and "/api/demo-data" in html)
    check("page states weekend rule", "weekends count as 0 available" in html)
    check("no external scripts/CDN", "http://" not in html and "https://" not in html
          and "<script src" not in html)
finally:
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except Exception:
        srv.kill()

# ---- demo data on a fresh, empty data file
DATA2 = os.path.join(tempfile.mkdtemp(), "data.json")
PORT2 = free_port()
BASE = "http://127.0.0.1:%d" % PORT2
srv = subprocess.Popen([sys.executable, APP, "--port", str(PORT2), "--data", DATA2],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + "/api/rooms")
            break
        except Exception:
            time.sleep(0.1)
    s, dm = req("/api/demo-data", {})
    check("demo-data inserts on empty file", s == 200 and dm["inserted"] > 20, (s, dm))
    s, d = req("/api/dashboard?start=%s&end=%s" % ((TODAY - timedelta(days=89)).isoformat(),
                                                   TODAY.isoformat()))
    check("demo dashboard has data", d["totals"]["bookings"] > 0 and d["totals"]["cancelled"] > 0, d["totals"])
    with open(DATA2, encoding="utf-8") as f:
        demo = json.load(f)["bookings"]
    active = [b for b in demo if not b.get("cancelled")]
    clash = False
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if a["room"] == b["room"] and a["date"] == b["date"] and a["start"] < b["end"] and b["start"] < a["end"]:
                clash = True
    check("demo data has no double bookings", not clash)
    check("demo data spread over 90 days", len(set(b["date"] for b in demo)) > 30)
    s, dm2 = req("/api/demo-data", {})
    check("demo-data not inserted twice", dm2["inserted"] == 0, dm2)
finally:
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except Exception:
        srv.kill()

print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
