#!/usr/bin/env python3
"""Tests for the meeting room booking app.

Runs the real HTTP server on a free port with a temporary database, so it
proves the behaviour end-to-end (server-side conflict check included).

Run:  python3 test_app.py
Exit code 0 = all tests passed.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from http.server import ThreadingHTTPServer

TMPDIR = tempfile.mkdtemp(prefix="roombooking-test-")
os.environ["DB_PATH"] = os.path.join(TMPDIR, "test.db")
os.environ["ADMIN_KEY"] = "test-admin-key"

import app  # noqa: E402  (import after env vars are set)

SERVER = None
BASE = None
ADMIN = "test-admin-key"


def setUpModule():
    global SERVER, BASE
    app.init_db()
    SERVER = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    BASE = "http://127.0.0.1:%d" % SERVER.server_address[1]
    threading.Thread(target=SERVER.serve_forever, daemon=True).start()


def tearDownModule():
    if SERVER:
        SERVER.shutdown()
        SERVER.server_close()


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body.strip().startswith(("{", "[")) else body)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
            try:
                return e.code, json.loads(body)
            except ValueError:
                return e.code, body
        finally:
            e.close()  # avoid ResourceWarning noise


def next_weekday(offset=0):
    d = date.today() + timedelta(days=offset)
    while d.weekday() > 4:
        d += timedelta(days=1)
    return d.isoformat()


class BookingTests(unittest.TestCase):
    def setUp(self):
        # fresh database for every test
        with app.connect() as conn:
            conn.execute("DELETE FROM bookings")
        self.day = next_weekday(7)

    def book(self, room="Aspen", start="09:00", end="10:00", email="ada@example.com", name="Ada"):
        return call("POST", "/api/bookings", {
            "room": room, "date": self.day, "start": start, "end": end,
            "booker": name, "email": email, "title": "Test meeting"})

    # ---- core requirements ------------------------------------------------
    def test_room_list(self):
        status, data = call("GET", "/api/rooms")
        self.assertEqual(status, 200)
        names = [r["name"] for r in data["rooms"]]
        self.assertEqual(names, ["Aspen", "Birch", "Cedar", "Dogwood", "Elm"])
        self.assertEqual(data["rooms"][4]["capacity"], 20)

    def test_availability_shows_free_and_booked(self):
        status, data = call("GET", "/api/availability?date=" + self.day)
        self.assertEqual(status, 200)
        self.assertTrue(data["open"])
        slots = data["rooms"]["Aspen"]["slots"]
        self.assertEqual(len(slots), 20)  # 08:00-18:00 in 30-min slots
        self.assertTrue(all(s["status"] == "free" for s in slots))

        self.assertEqual(self.book()[0], 201)
        status, data = call("GET", "/api/availability?date=" + self.day)
        aspen = {s["start"]: s for s in data["rooms"]["Aspen"]["slots"]}
        self.assertEqual(aspen["09:00"]["status"], "booked")
        self.assertEqual(aspen["09:30"]["status"], "booked")
        self.assertEqual(aspen["10:00"]["status"], "free")
        # other rooms unaffected
        birch = {s["start"]: s for s in data["rooms"]["Birch"]["slots"]}
        self.assertEqual(birch["09:00"]["status"], "free")

    def test_double_booking_rejected(self):
        status, data = self.book()
        self.assertEqual(status, 201, data)
        first_id = data["booking"]["id"]

        # exact same slot
        status, data = self.book(email="bob@example.com", name="Bob")
        self.assertEqual(status, 409, "double booking must be rejected")
        self.assertIn("already booked", data["error"])

        # partial overlap (09:30-10:30 overlaps 09:00-10:00)
        status, _ = self.book(start="09:30", end="10:30", email="bob@example.com")
        self.assertEqual(status, 409)

        # enclosing booking (08:30-10:30)
        status, _ = self.book(start="08:30", end="10:30", email="bob@example.com")
        self.assertEqual(status, 409)

        # only one booking exists
        status, data = call("GET", "/api/bookings?date=" + self.day + "&admin_key=" + ADMIN)
        self.assertEqual(status, 200, data)
        self.assertEqual(len(data["bookings"]), 1)
        self.assertEqual(data["bookings"][0]["id"], first_id)

        # adjacent (non-overlapping) booking is allowed
        status, _ = self.book(start="10:00", end="11:00", email="bob@example.com")
        self.assertEqual(status, 201)

        # same time in a different room is allowed
        status, _ = self.book(room="Birch", email="bob@example.com")
        self.assertEqual(status, 201)

    def test_cancellation_frees_slot(self):
        status, data = self.book()
        self.assertEqual(status, 201)
        bid = data["booking"]["id"]

        status, data = call("DELETE", "/api/bookings/%d" % bid, {"email": "ada@example.com"})
        self.assertEqual(status, 200, data)

        # slot is free again
        status, data = call("GET", "/api/availability?date=" + self.day)
        aspen = {s["start"]: s for s in data["rooms"]["Aspen"]["slots"]}
        self.assertEqual(aspen["09:00"]["status"], "free")

        # and it can be booked again by someone else
        status, data = self.book(email="bob@example.com", name="Bob")
        self.assertEqual(status, 201, data)

    def test_only_booker_or_admin_can_cancel(self):
        status, data = self.book()
        bid = data["booking"]["id"]

        status, data = call("DELETE", "/api/bookings/%d" % bid, {"email": "bob@example.com"})
        self.assertEqual(status, 403)
        status, data = call("DELETE", "/api/bookings/%d" % bid, {})
        self.assertEqual(status, 403)

        # still there
        status, data = call("GET", "/api/bookings?email=ada@example.com")
        self.assertEqual(len(data["bookings"]), 1)

        # admin override
        status, data = call("DELETE", "/api/bookings/%d" % bid, {"admin_key": "test-admin-key"})
        self.assertEqual(status, 200, data)
        status, data = call("GET", "/api/bookings?email=ada@example.com")
        self.assertEqual(len(data["bookings"]), 0)

    def test_my_bookings(self):
        self.book(start="09:00", end="10:00")
        self.book(start="11:00", end="12:00")
        self.book(room="Birch", email="bob@example.com", name="Bob")
        status, data = call("GET", "/api/bookings?email=ada@example.com")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["bookings"]), 2)
        self.assertTrue(all(b["email"] == "ada@example.com" for b in data["bookings"]))

    def test_csv_export(self):
        self.book()
        req = urllib.request.Request(BASE + "/api/bookings.csv?date=" + self.day)
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode()
            self.assertIn("text/csv", r.headers.get("Content-Type", ""))
        lines = text.strip().splitlines()
        self.assertEqual(lines[0].split(",")[0], "id")
        self.assertEqual(len(lines), 2)
        self.assertIn("Aspen", lines[1])

    def test_validation(self):
        # weekend rejected
        d = date.today() + timedelta(days=1)
        while d.weekday() != 5:
            d += timedelta(days=1)
        status, data = call("POST", "/api/bookings", {
            "room": "Aspen", "date": d.isoformat(), "start": "09:00", "end": "10:00",
            "booker": "Ada", "email": "ada@example.com"})
        self.assertEqual(status, 400)
        # outside hours
        status, _ = self.book(start="07:00", end="08:00")
        self.assertEqual(status, 400)
        # end before start
        status, _ = self.book(start="10:00", end="09:00")
        self.assertEqual(status, 400)
        # unknown room
        status, _ = self.book(room="Nope")
        self.assertEqual(status, 400)
        # bad email
        status, _ = self.book(email="not-an-email")
        self.assertEqual(status, 400)
        # off-grid time
        status, _ = self.book(start="09:15", end="09:45")
        self.assertEqual(status, 400)

    def test_past_date_rejected(self):
        status, data = call("POST", "/api/bookings", {
            "room": "Aspen", "date": "2020-01-06", "start": "09:00", "end": "10:00",
            "booker": "Ada", "email": "ada@example.com"})
        self.assertEqual(status, 400)
        self.assertIn("past", data["error"])

    def test_malformed_json_and_bad_types(self):
        req = urllib.request.Request(BASE + "/api/bookings", data=b"{not json", method="POST",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

        status, data = self.book()
        bid = data["booking"]["id"]
        # non-string email / admin_key must not crash the server
        status, _ = call("DELETE", "/api/bookings/%d" % bid, {"email": ["a"], "admin_key": {"x": 1}})
        self.assertEqual(status, 403)

    def test_email_and_date_filter_combined(self):
        self.book()
        other = next_weekday(14)
        call("POST", "/api/bookings", {"room": "Aspen", "date": other, "start": "09:00",
                                       "end": "10:00", "booker": "Ada", "email": "ada@example.com"})
        # someone else on the same day must not leak into the result
        call("POST", "/api/bookings", {"room": "Birch", "date": self.day, "start": "09:00",
                                       "end": "10:00", "booker": "Bob", "email": "bob@example.com"})
        status, data = call("GET", "/api/bookings?email=ada@example.com&date=" + self.day)
        self.assertEqual(status, 200)
        self.assertEqual(len(data["bookings"]), 1, data)
        self.assertEqual(data["bookings"][0]["date"], self.day)
        self.assertEqual(data["bookings"][0]["email"], "ada@example.com")
        # email only -> both of Ada's bookings
        status, data = call("GET", "/api/bookings?email=ada@example.com")
        self.assertEqual(len(data["bookings"]), 2)

    def test_all_bookings_requires_admin_key(self):
        self.book()
        # no key -> 403
        status, data = call("GET", "/api/bookings")
        self.assertEqual(status, 403, data)
        self.assertIn("admin", data["error"].lower())
        # wrong key -> 403
        status, data = call("GET", "/api/bookings?admin_key=wrong")
        self.assertEqual(status, 403)
        # date filter alone is not enough either
        status, data = call("GET", "/api/bookings?date=" + self.day)
        self.assertEqual(status, 403)
        # correct key -> 200 with the booking
        status, data = call("GET", "/api/bookings?admin_key=" + ADMIN)
        self.assertEqual(status, 200, data)
        self.assertEqual(len(data["bookings"]), 1)
        status, data = call("GET", "/api/bookings?admin_key=" + ADMIN + "&date=" + self.day)
        self.assertEqual(status, 200)
        self.assertEqual(len(data["bookings"]), 1)

    def test_long_title_rejected(self):
        status, data = call("POST", "/api/bookings", {
            "room": "Aspen", "date": self.day, "start": "09:00", "end": "10:00",
            "booker": "Ada", "email": "ada@example.com", "title": "x" * 201})
        self.assertEqual(status, 400, data)
        self.assertIn("too long", data["error"])
        self.assertIn("200", data["error"])
        # nothing was stored
        status, data = call("GET", "/api/bookings?email=ada@example.com")
        self.assertEqual(data["bookings"], [])
        # exactly 200 characters is still accepted and stored untruncated
        title = "y" * 200
        status, data = call("POST", "/api/bookings", {
            "room": "Aspen", "date": self.day, "start": "09:00", "end": "10:00",
            "booker": "Ada", "email": "ada@example.com", "title": title})
        self.assertEqual(status, 201, data)
        self.assertEqual(data["booking"]["title"], title)

    def test_concurrent_identical_bookings_only_one_wins(self):
        n = 12
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(n)

        def worker():
            barrier.wait()  # fire all requests at the same moment
            status, _ = self.book(email="ada@example.com", name="Ada")
            with lock:
                results.append(status)

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(results), n)
        self.assertEqual(results.count(201), 1, "exactly one booking must be created: %r" % results)
        self.assertEqual(results.count(409), n - 1, results)
        status, data = call("GET", "/api/bookings?email=ada@example.com")
        self.assertEqual(len(data["bookings"]), 1)

    def test_cancel_wrong_admin_key_message(self):
        status, data = self.book()
        bid = data["booking"]["id"]
        status, data = call("DELETE", "/api/bookings/%d" % bid, {"admin_key": "wrong-key"})
        self.assertEqual(status, 403)
        self.assertIn("admin key", data["error"].lower())
        # unknown booking -> 404
        status, data = call("DELETE", "/api/bookings/999999", {"admin_key": ADMIN})
        self.assertEqual(status, 404)

    def test_index_page_served(self):
        with urllib.request.urlopen(BASE + "/", timeout=10) as r:
            html = r.read().decode()
        self.assertEqual(r.status, 200)
        self.assertIn("Meeting Room Booking", html)
        self.assertIn("Aspen", html)
        # the UI must send the admin key for the full list and wrap loaders in try/catch
        self.assertIn("admin_key=", html)
        self.assertIn("async function loadAll(){\n  try {", html)
        self.assertIn("async function loadAvailability(){\n  try {", html)
        self.assertIn("async function loadMine(){\n  try {", html)
        # the dashboard section and its loader are part of the page
        self.assertIn("Dashboard (manager)", html)
        self.assertIn("async function loadDashboard(){\n  try {", html)
        self.assertIn("/api/dashboard?from=", html)


class DashboardTests(unittest.TestCase):
    """Manager dashboard: soft-delete cancellations + /api/dashboard."""

    def setUp(self):
        with app.connect() as conn:
            conn.execute("DELETE FROM bookings")
        # A fixed Mon-Fri week in the past: 2025-06-02 (Mon) .. 2025-06-06 (Fri)
        self.mon = "2025-06-02"
        self.tue = "2025-06-03"
        self.fri = "2025-06-06"

    def seed(self, room, day, start, end, email="ada@example.com", cancelled=False):
        with app.connect() as conn:
            cur = conn.execute(
                "INSERT INTO bookings (room, day, start_min, end_min, booker, email, title, "
                "created_at, cancelled_at, cancelled_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (room, day, start, end, "Ada", email, "seeded",
                 "2025-05-01T09:00:00", "2025-05-02T09:00:00" if cancelled else None,
                 email if cancelled else None))
            return cur.lastrowid

    def dash(self, frm, to, key=ADMIN, room=None):
        url = "/api/dashboard?from=%s&to=%s" % (frm, to)
        if key is not None:
            url += "&admin_key=" + key
        if room:
            url += "&room=" + room
        return call("GET", url)

    def test_dashboard_requires_admin_key(self):
        status, data = self.dash(self.mon, self.fri, key=None)
        self.assertEqual(status, 403, data)
        self.assertIn("admin", data["error"].lower())
        status, data = self.dash(self.mon, self.fri, key="wrong")
        self.assertEqual(status, 403)
        status, data = self.dash(self.mon, self.fri)
        self.assertEqual(status, 200, data)

    def test_dashboard_per_room_counts_and_hours(self):
        self.seed("Elm", self.mon, 9 * 60, 11 * 60)      # 2 h
        self.seed("Elm", self.tue, 14 * 60, 15 * 60)     # 1 h
        self.seed("Aspen", self.fri, 9 * 60, 10 * 60)    # 1 h
        status, data = self.dash(self.mon, self.fri)
        self.assertEqual(status, 200, data)
        rooms = {r["room"]: r for r in data["rooms"]}
        self.assertEqual(rooms["Elm"]["bookings"], 2)
        self.assertEqual(rooms["Elm"]["hours"], 3.0)
        self.assertEqual(rooms["Aspen"]["bookings"], 1)
        self.assertEqual(rooms["Aspen"]["hours"], 1.0)
        self.assertEqual(rooms["Birch"]["bookings"], 0)
        self.assertEqual(rooms["Elm"]["capacity"], 20)
        # 5 weekdays x 10 open hours = 50 available hours per room
        self.assertEqual(data["range"]["weekdays"], 5)
        self.assertEqual(data["range"]["available_hours_per_room"], 50.0)
        self.assertEqual(rooms["Elm"]["utilisation_pct"], 6.0)   # 3/50
        self.assertEqual(rooms["Aspen"]["utilisation_pct"], 2.0)  # 1/50
        self.assertEqual(data["totals"]["bookings"], 3)
        self.assertEqual(data["totals"]["hours"], 4.0)
        self.assertTrue(data["summary"])
        self.assertTrue(data["recommendation"])

    def test_cancelled_excluded_from_hours_but_counted_in_rate(self):
        self.seed("Elm", self.mon, 9 * 60, 11 * 60)                 # active, 2 h
        self.seed("Elm", self.tue, 9 * 60, 11 * 60, cancelled=True)  # cancelled, 2 h
        self.seed("Aspen", self.tue, 9 * 60, 10 * 60, cancelled=True)
        status, data = self.dash(self.mon, self.fri)
        self.assertEqual(status, 200, data)
        rooms = {r["room"]: r for r in data["rooms"]}
        self.assertEqual(rooms["Elm"]["bookings"], 1)
        self.assertEqual(rooms["Elm"]["hours"], 2.0)      # cancelled hour not counted
        self.assertEqual(rooms["Elm"]["cancelled"], 1)
        self.assertEqual(rooms["Aspen"]["cancelled"], 1)
        self.assertEqual(rooms["Aspen"]["hours"], 0.0)
        self.assertEqual(data["totals"]["bookings"], 1)
        self.assertEqual(data["totals"]["hours"], 2.0)
        self.assertEqual(data["totals"]["cancelled"], 2)
        # rate = cancelled / (cancelled + active) = 2/3
        self.assertEqual(data["totals"]["cancellation_rate_pct"], 66.7)
        self.assertEqual(sum(w["cancelled"] for w in data["cancelled_trend"]), 2)

    def test_weekday_and_hour_aggregation(self):
        self.seed("Elm", self.mon, 9 * 60, 10 * 60)
        self.seed("Birch", self.mon, 9 * 60, 10 * 60)
        self.seed("Cedar", self.tue, 15 * 60, 17 * 60)   # 15-16 and 16-17
        status, data = self.dash(self.mon, self.fri)
        self.assertEqual(status, 200, data)
        wd = {w["weekday"]: w["bookings"] for w in data["by_weekday"]}
        self.assertEqual(wd["Mon"], 2)
        self.assertEqual(wd["Tue"], 1)
        self.assertEqual(wd["Wed"], 0)
        self.assertEqual(len(data["by_weekday"]), 7)
        hrs = {h["hour"]: h["bookings"] for h in data["by_hour"]}
        self.assertEqual(hrs["09-10"], 2)
        self.assertEqual(hrs["15-16"], 1)
        self.assertEqual(hrs["16-17"], 1)
        self.assertEqual(hrs["08-09"], 0)
        self.assertEqual(len(data["by_hour"]), 10)
        self.assertEqual(data["top_dates"][0], {"date": self.mon, "bookings": 2})
        self.assertLessEqual(len(data["top_dates"]), 5)

    def test_dashboard_range_validation(self):
        # from after to
        status, data = self.dash(self.fri, self.mon)
        self.assertEqual(status, 400, data)
        # unparseable date
        status, data = self.dash("not-a-date", self.fri)
        self.assertEqual(status, 400)
        # missing dates
        status, data = call("GET", "/api/dashboard?admin_key=" + ADMIN)
        self.assertEqual(status, 400)
        # span longer than 366 days
        status, data = self.dash("2024-01-01", "2025-06-01")
        self.assertEqual(status, 400)
        self.assertIn("366", data["error"])
        # exactly 366 days is fine
        status, data = self.dash("2024-01-01", "2024-12-31")
        self.assertEqual(status, 200, data)

    def test_cancel_soft_deletes_and_frees_slot(self):
        day = next_weekday(7)
        status, data = call("POST", "/api/bookings", {
            "room": "Aspen", "date": day, "start": "09:00", "end": "10:00",
            "booker": "Ada", "email": "ada@example.com", "title": "soft delete"})
        self.assertEqual(status, 201, data)
        bid = data["booking"]["id"]
        status, data = call("DELETE", "/api/bookings/%d" % bid, {"email": "ada@example.com"})
        self.assertEqual(status, 200, data)
        self.assertIsNotNone(data["booking"]["cancelled_at"])
        self.assertEqual(data["booking"]["cancelled_by"], "ada@example.com")
        # the record is kept, marked cancelled
        with app.connect() as conn:
            row = conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNotNone(row["cancelled_at"])
        # the slot is free again and re-bookable
        status, data = call("GET", "/api/availability?date=" + day)
        aspen = {s["start"]: s for s in data["rooms"]["Aspen"]["slots"]}
        self.assertEqual(aspen["09:00"]["status"], "free")
        status, data = call("POST", "/api/bookings", {
            "room": "Aspen", "date": day, "start": "09:00", "end": "10:00",
            "booker": "Bob", "email": "bob@example.com", "title": "rebook"})
        self.assertEqual(status, 201, data)
        # cancelling twice is refused
        status, data = call("DELETE", "/api/bookings/%d" % bid, {"email": "ada@example.com"})
        self.assertEqual(status, 409, data)

    def test_migration_adds_columns_to_old_database(self):
        import sqlite3
        old = os.path.join(TMPDIR, "old.db")
        if os.path.exists(old):
            os.remove(old)
        conn = sqlite3.connect(old)
        conn.execute("CREATE TABLE bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT NOT NULL, "
                     "day TEXT NOT NULL, start_min INTEGER NOT NULL, end_min INTEGER NOT NULL, "
                     "booker TEXT NOT NULL, email TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', "
                     "created_at TEXT NOT NULL)")
        conn.execute("INSERT INTO bookings (room, day, start_min, end_min, booker, email, title, "
                     "created_at) VALUES ('Elm','2025-06-02',540,600,'A','a@x.com','t','x')")
        conn.commit()
        conn.close()
        saved = app.DB_PATH
        try:
            app.DB_PATH = old
            app.init_db()
            with app.connect() as c:
                cols = {r[1] for r in c.execute("PRAGMA table_info(bookings)").fetchall()}
                self.assertIn("cancelled_at", cols)
                self.assertIn("cancelled_by", cols)
                row = c.execute("SELECT * FROM bookings").fetchone()
                self.assertIsNone(row["cancelled_at"])  # old rows stay active
            app.init_db()  # idempotent: running again must not fail
        finally:
            app.DB_PATH = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
