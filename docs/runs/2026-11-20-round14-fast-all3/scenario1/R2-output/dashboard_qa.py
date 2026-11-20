#!/usr/bin/env python3
"""QA acceptance tests for the NEW manager dashboard in app.py.

Written against the dashboard specification (not against the implementation),
so it can be run as soon as the developer delivers the new app.py.

What it does
------------
* Starts ``app.py`` on a free port with a temporary ``--data`` file
  (subprocess + urllib, standard library only).
* Waits until the server answers, and always kills it in a ``finally`` block.
* Runs every check, prints ``PASS``/``FAIL`` per check plus a final count,
  and exits non-zero if anything failed.

Usage
-----
    python3 dashboard_qa.py                 # tests ./app.py
    python3 dashboard_qa.py path/to/app.py  # tests another copy
    python3 dashboard_qa.py --verbose       # also print details of passes

Exit codes: 0 = all checks passed, 1 = at least one check failed,
2 = the app could not be started at all.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
VERBOSE = False

# ---------------------------------------------------------------- results
RESULTS = []          # list of (ok, name, detail)


def check(name, cond, detail=""):
    """Record one check. ``detail`` is shown when it fails (or with --verbose)."""
    ok = bool(cond)
    RESULTS.append((ok, name, detail))
    line = ("PASS " if ok else "FAIL ") + name
    if not ok and detail != "":
        line += "  :: " + str(detail)[:600]
    elif VERBOSE and detail != "":
        line += "  :: " + str(detail)[:300]
    print(line, flush=True)
    return ok


def section(title):
    print("\n--- %s ---" % title, flush=True)


# ---------------------------------------------------------------- HTTP helpers
class Client:
    """Tiny JSON client that never raises on HTTP errors (returns the code)."""

    def __init__(self, base):
        self.base = base

    def raw(self, path, method="GET", body=None, timeout=15):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def json(self, path, method="GET", body=None, timeout=15):
        """Return (status, parsed_json_or_None, raw_text)."""
        status, text = self.raw(path, method, body, timeout)
        try:
            return status, json.loads(text), text
        except ValueError:
            return status, None, text


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def wait_ready(client, proc, timeout=20.0):
    """Poll /api/rooms until the server answers or the process dies."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            status, _ = client.raw("/api/rooms", timeout=2)
            if status == 200:
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


# ---------------------------------------------------------------- date helpers
TODAY = date.today()
# A weekday inside the booking horizon (<= 60 days ahead) so bookings are legal.
D1 = TODAY + timedelta(days=1)
while D1.weekday() >= 5:            # skip weekends: availability is weekday-based
    D1 += timedelta(days=1)
D2 = D1 + timedelta(days=1)
while D2.weekday() >= 5:
    D2 += timedelta(days=1)
D1S, D2S = D1.isoformat(), D2.isoformat()


def weekday_hours(start, end):
    """Available hours in [start, end] per the spec: weekdays x (18-8) hours."""
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n * 10


# ---------------------------------------------------------------- the checks
def run_checks(c, data_path):
    # ============================================================ 1. page / UI
    section("HTML page (GET /)")
    status, html = c.raw("/")
    check("GET / returns 200 HTML", status == 200 and "<html" in html.lower(), status)
    low = html.lower()
    check("page has a Dashboard tab", "dashboard" in low and
          ("tab" in low or "role=\"tab\"" in low or "data-tab" in low),
          "no 'Dashboard' tab found in the page")
    check("page has date range inputs (start & end)",
          low.count('type="date"') >= 2 or ("start" in low and "end" in low and 'type="date"' in low),
          "expected two <input type=date> for the range")
    presets = ["last 7", "last 30", "last 90", "this month", "all time"]
    missing = [p for p in presets if p not in low]
    check("page has preset buttons (7/30/90 days, this month, all time)",
          not missing, "missing presets: %s" % missing)
    # No external scripts / CDN: look at every script src and link href.
    import re
    srcs = re.findall(r'<script[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', html, re.I)
    bad_srcs = [s for s in srcs if s.lower().startswith(("http://", "https://", "//"))]
    check("no external <script src> (works offline)", not bad_srcs, bad_srcs)
    links = re.findall(r'<link[^>]*\bhref\s*=\s*["\']([^"\']+)["\']', html, re.I)
    bad_links = [s for s in links if s.lower().startswith(("http://", "https://", "//"))]
    check("no external stylesheet/CDN <link>", not bad_links, bad_links)
    check("page renders charts with inline SVG or CSS bars",
          "<svg" in low or "bar" in low or "chart" in low,
          "no SVG/CSS chart markup found")
    check("page mentions the demo-data button", "demo" in low,
          "no 'Load demo data' button found")
    check("page states weekends count as 0 available hours",
          "weekend" in low, "weekend/available-hours note missing")

    # ============================================================ 2. demo data
    section("POST /api/demo-data")
    status, body, raw = c.json("/api/demo-data", method="POST", body={})
    check("demo-data returns 200 with {\"inserted\": n}",
          status == 200 and isinstance(body, dict) and isinstance(body.get("inserted"), int),
          (status, raw[:300]))
    inserted = body.get("inserted") if isinstance(body, dict) else None
    check("demo-data inserted at least one booking", isinstance(inserted, int) and inserted > 0,
          inserted)
    status, body2, raw2 = c.json("/api/demo-data", method="POST", body={})
    check("demo-data is a no-op when data is not empty (inserted == 0)",
          status == 200 and isinstance(body2, dict) and body2.get("inserted") == 0,
          (status, raw2[:300]))

    # ============================================================ 3. dashboard shape
    section("GET /api/dashboard - shape")
    start = (TODAY - timedelta(days=90)).isoformat()
    end = TODAY.isoformat()
    status, dash, raw = c.json("/api/dashboard?start=%s&end=%s" % (start, end))
    check("dashboard returns 200 JSON", status == 200 and isinstance(dash, dict),
          (status, raw[:300]))
    if not isinstance(dash, dict):
        return  # nothing else can be checked
    top_keys = ["range", "per_room", "totals", "by_weekday", "by_hour",
                "heatmap", "top_slots", "daily", "cancelled_by_room"]
    missing = [k for k in top_keys if k not in dash]
    check("dashboard has all top-level keys", not missing, "missing: %s" % missing)

    rng = dash.get("range") or {}
    check("range has start/end/days",
          all(k in rng for k in ("start", "end", "days")), rng)
    check("range echoes the requested dates",
          rng.get("start") == start and rng.get("end") == end, rng)
    check("range.days == 91 for a 90-day-back range", rng.get("days") == 91, rng.get("days"))

    per_room = dash.get("per_room") or []
    check("per_room lists all 4 rooms", len(per_room) == 4,
          [r.get("id") for r in per_room if isinstance(r, dict)])
    room_keys = ["id", "name", "capacity", "bookings", "hours", "utilisation_pct",
                 "cancelled", "cancellation_rate_pct", "status"]
    bad = [r.get("id") for r in per_room
           if not isinstance(r, dict) or any(k not in r for k in room_keys)]
    check("per_room entries have every required field", not bad, bad)
    check("per_room ids are aspen/birch/cedar/dune",
          sorted(r.get("id") for r in per_room if isinstance(r, dict)) ==
          ["aspen", "birch", "cedar", "dune"],
          [r.get("id") for r in per_room if isinstance(r, dict)])
    check("per_room status values are from the allowed set",
          all(r.get("status") in ("heavily used", "balanced", "underused")
              for r in per_room if isinstance(r, dict)),
          [r.get("status") for r in per_room if isinstance(r, dict)])

    totals = dash.get("totals") or {}
    tkeys = ["bookings", "hours", "cancelled", "cancellation_rate_pct",
             "busiest_room", "quietest_room"]
    check("totals has every required field",
          all(k in totals for k in tkeys), "missing: %s" % [k for k in tkeys if k not in totals])

    bw = dash.get("by_weekday") or []
    check("by_weekday has 7 entries", len(bw) == 7, len(bw))
    check("by_weekday entries have bookings and hours",
          all(isinstance(x, dict) and "bookings" in x and "hours" in x for x in bw), bw[:2])

    bh = dash.get("by_hour") or []
    check("by_hour has 10 entries (08..17)", len(bh) == 10, len(bh))
    hours_seen = [x.get("hour") for x in bh if isinstance(x, dict)]
    check("by_hour covers hours 08..17", hours_seen == list(range(8, 18)), hours_seen)
    check("by_hour entries have a bookings count",
          all(isinstance(x, dict) and "bookings" in x for x in bh), bh[:2])

    hm = dash.get("heatmap")
    check("heatmap is a 7 x 10 matrix",
          isinstance(hm, list) and len(hm) == 7 and all(isinstance(row, list) and len(row) == 10
                                                        for row in hm),
          "heatmap shape: %s" % (len(hm) if isinstance(hm, list) else type(hm)))

    ts = dash.get("top_slots")
    check("top_slots is a list of at most 5 entries",
          isinstance(ts, list) and len(ts) <= 5, ts)

    daily = dash.get("daily")
    check("daily is a per-day series covering the range",
          isinstance(daily, list) and len(daily) == rng.get("days"),
          "len(daily)=%s, days=%s" % (len(daily) if isinstance(daily, list) else None,
                                      rng.get("days")))
    check("daily entries have date/bookings/hours",
          isinstance(daily, list) and all(isinstance(x, dict) and
                                          {"date", "bookings", "hours"} <= set(x) for x in daily),
          (daily or [])[:2])

    cbr = dash.get("cancelled_by_room")
    check("cancelled_by_room is present (list or dict)", isinstance(cbr, (list, dict)), type(cbr))

    # ============================================================ 4. dashboard maths
    section("GET /api/dashboard - numbers")
    # Book a known set of bookings inside a controlled 1-day range.
    day = D1S
    made = []
    for room, s, e in [("aspen", "09:00", "11:00"), ("aspen", "13:00", "14:00"),
                       ("birch", "10:00", "11:00")]:
        st, b, raw = c.json("/api/book", method="POST",
                            body={"room": room, "date": day, "start": s, "end": e,
                                  "booker": "QA", "title": "QA %s %s" % (room, s)})
        if st == 201:
            made.append(b)
    check("setup: 3 bookings created for the maths checks", len(made) == 3,
          [m.get("id") for m in made])

    status, d1, raw = c.json("/api/dashboard?start=%s&end=%s" % (day, day))
    check("single-day dashboard returns 200", status == 200 and isinstance(d1, dict),
          (status, raw[:300]))
    if isinstance(d1, dict):
        pr = {r["id"]: r for r in d1.get("per_room", []) if isinstance(r, dict)}
        aspen = pr.get("aspen", {})
        check("aspen bookings counted (>=2)", aspen.get("bookings", 0) >= 2, aspen.get("bookings"))
        check("aspen hours = 3.0 (2h + 1h)",
              aspen.get("hours") is not None and abs(float(aspen["hours"]) - 3.0) < 1e-6,
              aspen.get("hours"))
        avail = weekday_hours(D1, D1)
        want_util = round(3.0 / avail * 100, 1) if avail else 0.0
        got_util = aspen.get("utilisation_pct")
        check("aspen utilisation_pct = hours / available hours",
              got_util is not None and abs(float(got_util) - want_util) <= 0.2,
              "got %s, expected ~%s (available=%sh)" % (got_util, want_util, avail))
        check("aspen status matches utilisation thresholds",
              (float(aspen.get("utilisation_pct") or 0) >= 60 and aspen.get("status") == "heavily used") or
              (float(aspen.get("utilisation_pct") or 0) <= 20 and aspen.get("status") == "underused") or
              (20 < float(aspen.get("utilisation_pct") or 0) < 60 and aspen.get("status") == "balanced"),
              (aspen.get("utilisation_pct"), aspen.get("status")))
        tot = d1.get("totals", {})
        check("totals.bookings >= 3", tot.get("bookings", 0) >= 3, tot.get("bookings"))
        check("totals.hours >= 4.0", float(tot.get("hours") or 0) >= 4.0, tot.get("hours"))
        check("totals.busiest_room is aspen", tot.get("busiest_room") in ("aspen", "Aspen"),
              tot.get("busiest_room"))
        check("totals.quietest_room is a room with no bookings",
              tot.get("quietest_room") in ("cedar", "Cedar", "dune", "Dune"),
              tot.get("quietest_room"))
        bh = {x.get("hour"): x.get("bookings") for x in d1.get("by_hour", [])}
        check("by_hour counts overlapping hours (09:00-11:00 counts in 9 and 10)",
              bh.get(9, 0) >= 1 and bh.get(10, 0) >= 2, bh)
        check("by_hour has no bookings outside 08..17",
              all(bh.get(h, 0) == 0 for h in (0, 7, 18, 23)), bh)
        bw = d1.get("by_weekday", [])
        check("by_weekday puts the bookings on the right weekday",
              len(bw) == 7 and bw[D1.weekday()].get("bookings", 0) >= 3,
              (D1.weekday(), bw[D1.weekday()] if len(bw) == 7 else bw))
        check("daily[0] matches the day's totals",
              d1.get("daily") and d1["daily"][0].get("bookings") == tot.get("bookings"),
              (d1.get("daily") or [{}])[0])

    # ============================================================ 5. cancellation is recorded
    section("Cancelling records the booking (not delete)")
    st, b, raw = c.json("/api/book", method="POST",
                        body={"room": "cedar", "date": D2S, "start": "15:00", "end": "16:00",
                              "booker": "QA Cancel", "title": "To be cancelled"})
    check("setup: booking to cancel created", st == 201, (st, raw[:200]))
    bid = b.get("id") if isinstance(b, dict) else None
    st, cbody, raw = c.json("/api/cancel", method="POST", body={"id": bid})
    check("cancel returns 200", st == 200, (st, raw[:200]))

    st, lst, raw = c.json("/api/bookings?date=%s" % D2S)
    ids = [x.get("id") for x in (lst or {}).get("bookings", [])]
    check("cancelled booking gone from /api/bookings", bid not in ids, ids)

    st, av, raw = c.json("/api/availability?date=%s&room=cedar" % D2S)
    slots = {}
    if isinstance(av, dict) and av.get("rooms"):
        slots = {s["start"]: s for s in av["rooms"][0].get("slots", [])}
    check("cancelled slot is free again in availability",
          slots.get("15:00", {}).get("free") is True and slots.get("15:30", {}).get("free") is True,
          {k: v.get("free") for k, v in slots.items() if k in ("15:00", "15:30")})

    st, rb, raw = c.json("/api/book", method="POST",
                         body={"room": "cedar", "date": D2S, "start": "15:00", "end": "16:00",
                               "booker": "QA Rebook", "title": "Rebooked"})
    check("cancelled slot can be re-booked", st == 201, (st, raw[:200]))

    st, canc, raw = c.json("/api/cancellations?start=%s&end=%s" % (D2S, D2S))
    check("GET /api/cancellations lists the cancelled record",
          st == 200 and isinstance(canc, dict) and
          any(x.get("id") == bid for x in canc.get("cancellations", canc.get("bookings", []))),
          (st, raw[:300]))

    st, d2, raw = c.json("/api/dashboard?start=%s&end=%s" % (D2S, D2S))
    check("dashboard for the cancel day returns 200", st == 200 and isinstance(d2, dict),
          (st, raw[:200]))
    if isinstance(d2, dict):
        tot = d2.get("totals", {})
        check("dashboard totals.cancelled counts the cancellation",
              tot.get("cancelled", 0) >= 1, tot.get("cancelled"))
        pr = {r["id"]: r for r in d2.get("per_room", []) if isinstance(r, dict)}
        cedar = pr.get("cedar", {})
        check("per_room cedar.cancelled >= 1", cedar.get("cancelled", 0) >= 1,
              cedar.get("cancelled"))
        denom = cedar.get("bookings", 0) + cedar.get("cancelled", 0)
        want_rate = round(1.0 / denom * 100, 1) if denom else 0.0
        got_rate = cedar.get("cancellation_rate_pct")
        check("cedar cancellation_rate_pct = cancelled/(bookings+cancelled)*100",
              got_rate is not None and abs(float(got_rate) - want_rate) <= 0.2,
              "got %s, expected ~%s" % (got_rate, want_rate))
        check("totals.cancellation_rate_pct is > 0",
              float(tot.get("cancellation_rate_pct") or 0) > 0,
              tot.get("cancellation_rate_pct"))
        cbr = d2.get("cancelled_by_room")
        if isinstance(cbr, dict):
            cval = cbr.get("cedar", 0)
        else:
            cval = sum(x.get("cancelled", x.get("count", 0)) for x in (cbr or [])
                       if isinstance(x, dict) and x.get("id", x.get("room")) == "cedar")
        check("cancelled_by_room counts cedar", cval >= 1, cbr)

    # ============================================================ 6. bad dates
    section("Bad date ranges -> HTTP 400 {\"error\": ...}")
    bad_ranges = [
        ("start > end", "start=%s&end=%s" % (D2S, D1S)),
        ("malformed start", "start=not-a-date&end=%s" % D2S),
        ("malformed end", "start=%s&end=2024-13-45" % D1S),
        ("empty start", "start=&end=%s" % D2S),
    ]
    for label, qs in bad_ranges:
        st, body, raw = c.json("/api/dashboard?" + qs)
        check("dashboard rejects %s with 400 + error" % label,
              st == 400 and isinstance(body, dict) and "error" in body,
              (st, raw[:200]))

    # ============================================================ 7. empty state
    section("Empty range")
    far_start = (TODAY - timedelta(days=400)).isoformat()
    far_end = (TODAY - timedelta(days=390)).isoformat()
    st, de, raw = c.json("/api/dashboard?start=%s&end=%s" % (far_start, far_end))
    check("empty range returns 200 with zero totals",
          st == 200 and isinstance(de, dict) and
          (de.get("totals") or {}).get("bookings") == 0,
          (st, raw[:300]))
    if isinstance(de, dict):
        check("empty range still lists all 4 rooms",
              len(de.get("per_room") or []) == 4, len(de.get("per_room") or []))
        check("empty range has no NaN/inf in JSON",
              "NaN" not in raw and "Infinity" not in raw, raw[:200])

    # ============================================================ 8. old data files
    section("Backward compatibility with old data.json (no cancelled flag)")
    # Write an old-style record straight into the data file, then read it back.
    try:
        data = None
        for _ in range(20):          # the server may be mid-write; retry briefly
            try:
                with open(data_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                break
            except (ValueError, OSError):
                time.sleep(0.1)
        if not isinstance(data, dict):
            raise RuntimeError("could not read the data file %r" % data_path)
        old_day = D2S
        data["bookings"].append({"id": 9001, "room": "dune", "date": old_day,
                                 "start": "08:00", "end": "09:00", "booker": "Legacy",
                                 "title": "Old record",
                                 "created": "2024-01-01T00:00:00"})
        data["next_id"] = max(data.get("next_id", 1), 9002)
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        st, lst, raw = c.json("/api/bookings?date=%s" % old_day)
        check("old record without 'cancelled' flag is still listed",
              st == 200 and any(x.get("id") == 9001 for x in (lst or {}).get("bookings", [])),
              (st, raw[:200]))
        st, dd, raw = c.json("/api/dashboard?start=%s&end=%s" % (old_day, old_day))
        check("dashboard handles old records without crashing",
              st == 200 and isinstance(dd, dict), (st, raw[:200]))
    except Exception as e:  # pragma: no cover - only if the data file is unreadable
        check("old record without 'cancelled' flag is still listed", False, repr(e))


def main(argv):
    global APP, VERBOSE
    args = [a for a in argv[1:] if not a.startswith("-")]
    VERBOSE = "--verbose" in argv or "-v" in argv
    if args:
        APP = os.path.abspath(args[0])
    if not os.path.exists(APP):
        print("FAIL app.py not found at %s" % APP)
        print("\n1 failure(s)")
        return 2

    tmpdir = tempfile.mkdtemp(prefix="dashboard-qa-")
    data_path = os.path.join(tmpdir, "data.json")
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    client = Client(base)
    print("Testing %s on port %d with data file %s" % (APP, port, data_path), flush=True)

    proc = subprocess.Popen(
        [sys.executable, APP, "--port", str(port), "--data", data_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=os.path.dirname(APP) or HERE)
    try:
        if not wait_ready(client, proc):
            out, err = b"", b""
            try:
                proc.kill()
                out, err = proc.communicate(timeout=5)
            except Exception:
                pass
            print("FAIL server did not start on %s" % base)
            print("  stdout: %s" % out.decode("utf-8", "replace")[-800:])
            print("  stderr: %s" % err.decode("utf-8", "replace")[-800:])
            RESULTS.append((False, "server starts", "did not become ready"))
            return 2
        check("server starts and answers /api/rooms", True)
        try:
            run_checks(client, data_path)
        except Exception:
            check("test run completed without an unexpected exception", False,
                  traceback.format_exc()[-800:])
    finally:
        # Always stop the server, whatever happened above.
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception:
            pass
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:
                pass

    # Keep a full log next to the script so a truncated console still has the detail.
    try:
        with open(os.path.join(HERE, "dashboard_qa.log"), "w", encoding="utf-8") as f:
            for ok, name, detail in RESULTS:
                f.write(("PASS " if ok else "FAIL ") + name + "  :: " + str(detail) + "\n")
    except OSError:
        pass

    passed = sum(1 for ok, _, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print("\n%d checks: %d passed, %d failed" % (len(RESULTS), passed, failed))
    if failed:
        print("\nFailed checks:")
        for ok, name, detail in RESULTS:
            if not ok:
                print("  - %s :: %s" % (name, str(detail)[:300]))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
