"""Tests for the meeting room booking system.

Run from this directory with:  python3 -m unittest -v test_app
(or from anywhere with:        python3 -m unittest -v test_app  after `cd` here)
Uses a temporary SQLite file and a real HTTP server on a free port.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402

TMP = tempfile.mkdtemp()
app.DB_PATH = os.path.join(TMP, "test_bookings.db")


def tomorrow():
    return (date.today() + timedelta(days=1)).isoformat()


def days_ahead(n):
    return (date.today() + timedelta(days=n)).isoformat()


class BookingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.init_db()
        cls.server = app.make_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        conn = app.connect()
        conn.execute("DELETE FROM bookings")
        conn.close()

    # -- helpers
    def request(self, method, path, body=None, raw=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                text = res.read().decode()
                return res.status, (json.loads(text) if text else {})
        except urllib.error.HTTPError as err:
            text = err.read().decode()
            try:
                return err.code, json.loads(text or "{}")
            except ValueError:
                return err.code, {"raw": text}

    def book(self, start, end, booker="Alex", room_id=1, day=None):
        return self.request("POST", "/api/bookings", {
            "room_id": room_id, "date": day or tomorrow(),
            "start": start, "end": end, "booker": booker})

    def slot_free(self, start, room_id=1, day=None):
        status, body = self.request(
            "GET", "/api/availability?date=%s&room=%d" % (day or tomorrow(), room_id))
        self.assertEqual(status, 200)
        for slot in body["rooms"][0]["slots"]:
            if slot["start"] == start:
                return slot["free"]
        raise AssertionError("slot %s not found" % start)

    # -- tests
    def test_rooms_seeded(self):
        status, body = self.request("GET", "/api/rooms")
        self.assertEqual(status, 200)
        names = [r["name"] for r in body["rooms"]]
        self.assertEqual(names, ["Cedar", "Birch", "Maple", "Oak"])
        self.assertEqual([r["capacity"] for r in body["rooms"]], [4, 6, 10, 20])

    def test_booking_succeeds(self):
        status, body = self.book("10:00", "11:00")
        self.assertEqual(status, 201, body)
        self.assertEqual(body["booking"]["booker"], "Alex")
        self.assertEqual(body["booking"]["start"], "10:00")
        self.assertFalse(self.slot_free("10:00"))
        self.assertFalse(self.slot_free("10:30"))
        self.assertTrue(self.slot_free("11:00"))

    def test_overlapping_booking_rejected_409(self):
        self.assertEqual(self.book("10:00", "11:00")[0], 201)
        # exact same slot
        status, body = self.book("10:00", "11:00", booker="Sam")
        self.assertEqual(status, 409, body)
        # partial overlap
        self.assertEqual(self.book("10:30", "11:30", booker="Sam")[0], 409)
        self.assertEqual(self.book("09:30", "10:30", booker="Sam")[0], 409)
        self.assertEqual(self.book("09:00", "12:00", booker="Sam")[0], 409)
        # adjacent is fine
        self.assertEqual(self.book("11:00", "12:00", booker="Sam")[0], 201)
        # other room is fine
        self.assertEqual(self.book("10:00", "11:00", booker="Sam", room_id=2)[0], 201)

    def test_cancellation_frees_slot(self):
        status, body = self.book("14:00", "15:00")
        self.assertEqual(status, 201)
        bid = body["booking"]["id"]
        self.assertFalse(self.slot_free("14:00"))
        status, body = self.request("DELETE", "/api/bookings/%d" % bid, {"booker": "Alex"})
        self.assertEqual(status, 200, body)
        self.assertTrue(self.slot_free("14:00"))
        # slot can be re-booked immediately
        self.assertEqual(self.book("14:00", "15:00", booker="Sam")[0], 201)
        # cancelling again -> 404
        self.assertEqual(self.request("DELETE", "/api/bookings/%d" % bid, {"booker": "Alex"})[0], 404)

    def test_cancel_wrong_name_rejected(self):
        status, body = self.book("16:00", "17:00", booker="Alex")
        bid = body["booking"]["id"]
        status, body = self.request("DELETE", "/api/bookings/%d" % bid, {"booker": "Mallory"})
        self.assertEqual(status, 403, body)
        self.assertFalse(self.slot_free("16:00"))  # still booked
        # missing name -> 400
        self.assertEqual(self.request("DELETE", "/api/bookings/%d" % bid, {})[0], 400)
        # admin can cancel
        self.assertEqual(self.request("DELETE", "/api/bookings/%d" % bid, {"booker": "admin"})[0], 200)
        self.assertTrue(self.slot_free("16:00"))

    def test_validation_rules(self):
        self.assertEqual(self.book("07:00", "08:00")[0], 400)          # before hours
        self.assertEqual(self.book("17:00", "18:30")[0], 400)          # after hours
        self.assertEqual(self.book("10:00", "15:00")[0], 400)          # > 4 hours
        self.assertEqual(self.book("10:15", "10:45")[0], 400)          # off-grid
        self.assertEqual(self.book("11:00", "10:00")[0], 400)          # end before start
        self.assertEqual(self.book("10:00", "11:00", booker="")[0], 400)
        self.assertEqual(self.book("10:00", "11:00", room_id=99)[0], 400)
        past = (date.today() - timedelta(days=1)).isoformat()
        self.assertEqual(self.book("10:00", "11:00", day=past)[0], 400)
        far = (date.today() + timedelta(days=61)).isoformat()
        self.assertEqual(self.book("10:00", "11:00", day=far)[0], 400)
        self.assertEqual(self.book("10:00", "14:00")[0], 201)          # exactly 4h ok

    def test_bookings_list_and_ui(self):
        self.book("09:00", "09:30")
        status, body = self.request("GET", "/api/bookings?date=%s" % tomorrow())
        self.assertEqual(status, 200)
        self.assertEqual(len(body["bookings"]), 1)
        self.assertEqual(body["bookings"][0]["room"], "Cedar")
        with urllib.request.urlopen("http://127.0.0.1:%d/" % self.port) as res:
            html = res.read().decode()
        self.assertIn("Meeting Room Booking", html)
        self.assertIn("/api/availability", html)

    # -- new behaviour (QA defects 1-16)
    def test_ui_form_is_submittable(self):
        """Defect 1/2: no method="dialog" (it would swallow the submit event)."""
        with urllib.request.urlopen("http://127.0.0.1:%d/" % self.port) as res:
            html = res.read().decode()
        self.assertNotIn('method="dialog"', html)
        self.assertIn('<form id="bookForm">', html)
        self.assertIn("ev.preventDefault()", html)
        # every button is explicitly typed, so Enter in the name field cannot
        # trigger a non-submit button and Cancel never submits the form
        for tag in __import__("re").findall(r"<button[^>]*>", html):
            self.assertIn('type="', tag, tag)
        self.assertIn('id="mine"', html)          # "My bookings" panel
        self.assertIn("dlgEnd", html)

    def test_availability_rejects_out_of_range_dates(self):
        """Defect 5: availability uses the same [today, today+60] rule as booking."""
        past = (date.today() - timedelta(days=1)).isoformat()
        status, body = self.request("GET", "/api/availability?date=%s" % past)
        self.assertEqual(status, 400, body)
        self.assertIn("between today and 60 days ahead", body["error"])
        status, body = self.request("GET", "/api/availability?date=%s" % days_ahead(61))
        self.assertEqual(status, 400, body)
        self.assertIn("between today and 60 days ahead", body["error"])
        # boundaries are accepted
        self.assertEqual(self.request("GET", "/api/availability?date=%s" % date.today().isoformat())[0], 200)
        self.assertEqual(self.request("GET", "/api/availability?date=%s" % days_ahead(60))[0], 200)

    def test_availability_unknown_room_400(self):
        """Defect 7: unknown numeric room id is an error, not an empty list."""
        status, body = self.request("GET", "/api/availability?date=%s&room=99" % tomorrow())
        self.assertEqual(status, 400, body)
        self.assertEqual(body["error"], "unknown room")
        status, body = self.request("GET", "/api/availability?date=%s&room=bogus" % tomorrow())
        self.assertEqual(status, 400, body)
        # names still work
        status, body = self.request("GET", "/api/availability?date=%s&room=cedar" % tomorrow())
        self.assertEqual(status, 200, body)
        self.assertEqual(body["rooms"][0]["room"], "Cedar")

    def test_bookings_room_filter_validated(self):
        """Defect 8: a bogus room filter is a 400, not silently ignored."""
        status, body = self.request("GET", "/api/bookings?room=bogus")
        self.assertEqual(status, 400, body)
        status, body = self.request("GET", "/api/bookings?room=99")
        self.assertEqual(status, 400, body)
        self.book("09:00", "09:30", room_id=1)
        self.book("09:00", "09:30", room_id=2)
        status, body = self.request("GET", "/api/bookings?room=2")
        self.assertEqual(status, 200)
        self.assertEqual([b["room"] for b in body["bookings"]], ["Birch"])

    def test_booker_filter(self):
        """Defect 3: GET /api/bookings?booker=NAME powers the "My bookings" panel."""
        self.book("09:00", "09:30", booker="Alex")
        self.book("10:00", "10:30", booker="Sam")
        self.book("11:00", "11:30", booker="alex", day=days_ahead(5))
        status, body = self.request("GET", "/api/bookings?booker=Alex")
        self.assertEqual(status, 200, body)
        self.assertEqual(len(body["bookings"]), 2)
        self.assertTrue(all(b["booker"].lower() == "alex" for b in body["bookings"]))
        # upcoming filter drops past dates
        conn = app.connect()
        conn.execute("INSERT INTO bookings (room_id, date, start, end, booker, created_at) "
                     "VALUES (1, ?, '09:00', '09:30', 'Alex', 'x')",
                     ((date.today() - timedelta(days=3)).isoformat(),))
        conn.close()
        status, body = self.request("GET", "/api/bookings?booker=Alex&upcoming=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["bookings"]), 2)
        self.assertTrue(all(b["date"] >= date.today().isoformat() for b in body["bookings"]))
        # unknown name -> empty list, not an error
        status, body = self.request("GET", "/api/bookings?booker=Nobody")
        self.assertEqual(status, 200)
        self.assertEqual(body["bookings"], [])

    def test_bool_room_id_rejected(self):
        """Defect 9: true must not be treated as room 1."""
        status, body = self.request("POST", "/api/bookings", {
            "room_id": True, "date": tomorrow(), "start": "10:00", "end": "11:00", "booker": "Alex"})
        self.assertEqual(status, 400, body)
        self.assertEqual(self.request("GET", "/api/bookings")[1]["bookings"], [])

    def test_no_python_internals_in_errors(self):
        """Defect 10: invalid calendar dates get a generic message."""
        status, body = self.book("10:00", "11:00", day="2025-13-45")
        self.assertEqual(status, 400, body)
        self.assertNotIn("strptime", body["error"])
        self.assertNotIn("does not match format", body["error"])
        status, body = self.request("GET", "/api/availability?date=2025-02-30")
        self.assertEqual(status, 400, body)
        self.assertNotIn("out of range", body["error"])

    def test_head_and_unsupported_methods_return_json(self):
        """Defect 11: HEAD works, PUT/PATCH return JSON 405 (not the HTML 501 page)."""
        req = urllib.request.Request("http://127.0.0.1:%d/api/rooms" % self.port, method="HEAD")
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 200)
            self.assertEqual(res.read(), b"")
        for method in ("PUT", "PATCH"):
            status, body = self.request(method, "/api/bookings", {"x": 1})
            self.assertEqual(status, 405, body)
            self.assertIn("error", body)

    def test_delete_without_name_message(self):
        """Defect 12: a non-object DELETE body says so."""
        status, body = self.book("15:00", "15:30")
        bid = body["booking"]["id"]
        status, body = self.request("DELETE", "/api/bookings/%d" % bid, raw=b"[1,2]")
        self.assertEqual(status, 400, body)
        self.assertEqual(body["error"], "JSON object expected")
        status, body = self.request("DELETE", "/api/bookings/%d" % bid, {})
        self.assertEqual(status, 400, body)
        self.assertIn("booker name is required", body["error"])

    def test_past_start_time_today_rejected(self):
        """Defect 13: a start time already gone today cannot be booked."""
        now = datetime.now()
        if now.hour * 60 + now.minute <= app.OPEN_HOUR * 60 + app.SLOT_MINUTES:
            self.skipTest("too early in the day for a past slot")
        status, body = self.book("08:00", "08:30", day=date.today().isoformat())
        self.assertEqual(status, 400, body)
        self.assertIn("already passed", body["error"])

    def test_admin_names_configurable(self):
        """Defect 14: ADMIN_NAMES env var (comma-separated) is honoured."""
        old = app.ADMIN_NAMES
        os.environ["ADMIN_NAMES"] = "boss, Office Manager"
        try:
            app.ADMIN_NAMES = app._admin_names_from_env()
            self.assertEqual(app.ADMIN_NAMES, {"boss", "office manager"})
            status, body = self.book("13:00", "13:30", booker="Alex")
            bid = body["booking"]["id"]
            self.assertEqual(self.request("DELETE", "/api/bookings/%d" % bid, {"booker": "admin"})[0], 403)
            self.assertEqual(self.request("DELETE", "/api/bookings/%d" % bid, {"booker": "Office Manager"})[0], 200)
        finally:
            app.ADMIN_NAMES = old
            os.environ.pop("ADMIN_NAMES", None)


"""Dashboard tests, appended to test_app.py by the developer."""
import sqlite3


class DashboardTests(unittest.TestCase):
    """Manager dashboard: /dashboard page and /api/stats JSON endpoint."""

    @classmethod
    def setUpClass(cls):
        app.init_db()
        cls.server = app.make_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        conn = app.connect()
        conn.execute("DELETE FROM bookings")
        conn.close()

    def request(self, method, path, body=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                text = res.read().decode()
                return res.status, (json.loads(text) if text else {})
        except urllib.error.HTTPError as err:
            text = err.read().decode()
            try:
                return err.code, json.loads(text or "{}")
            except ValueError:
                return err.code, {"raw": text}

    def page(self, path):
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path)) as res:
            return res.status, res.read().decode()

    def book(self, start, end, booker="Alex", room_id=1, day=None):
        return self.request("POST", "/api/bookings", {
            "room_id": room_id, "date": day or tomorrow(),
            "start": start, "end": end, "booker": booker})

    def stats(self, start, end):
        status, body = self.request("GET", "/api/stats?start=%s&end=%s" % (start, end))
        self.assertEqual(status, 200, body)
        return body

    # -- tests
    def test_stats_shape_and_numbers(self):
        d = tomorrow()
        self.assertEqual(self.book("09:00", "10:00", room_id=1, day=d)[0], 201)   # Cedar 1h
        self.assertEqual(self.book("10:00", "12:00", room_id=1, day=d)[0], 201)   # Cedar 2h
        self.assertEqual(self.book("09:00", "09:30", room_id=2, day=d)[0], 201)   # Birch 0.5h
        body = self.stats(d, d)
        for key in ("range", "totals", "rooms", "by_day_of_week", "by_date",
                    "by_hour", "busiest", "summary"):
            self.assertIn(key, body)
        t = body["totals"]
        self.assertEqual(t["bookings"], 3)
        self.assertEqual(t["cancelled"], 0)
        self.assertEqual(t["hours_reserved"], 3.5)
        self.assertEqual(t["cancellation_rate"], 0.0)
        self.assertEqual(t["rooms_used"], 2)
        self.assertEqual(t["rooms_unused"], 2)
        self.assertEqual(body["range"]["start"], d)
        self.assertEqual(body["range"]["end"], d)
        self.assertEqual(body["range"]["days"], 1)
        rooms = {r["room"]: r for r in body["rooms"]}
        self.assertEqual(rooms["Cedar"]["bookings"], 2)
        self.assertEqual(rooms["Cedar"]["hours"], 3.0)
        self.assertEqual(rooms["Birch"]["hours"], 0.5)
        self.assertEqual(rooms["Oak"]["bookings"], 0)
        self.assertIn("suggestion", rooms["Oak"])
        self.assertEqual(len(body["by_day_of_week"]), 7)
        self.assertEqual(len(body["by_hour"]), 10)          # 08:00-18:00
        self.assertEqual(body["by_date"], [{"date": d, "bookings": 3}])
        hours = {h["hour"]: h["bookings"] for h in body["by_hour"]}
        self.assertEqual(hours[9], 2)
        self.assertEqual(hours[10], 1)
        self.assertEqual(body["busiest"]["hour"], 9)
        self.assertEqual(body["busiest"]["date"], d)
        self.assertIn("Cedar", body["summary"])

    def test_cancelled_excluded_from_hours_but_counted_in_rate(self):
        d = tomorrow()
        _, b1 = self.book("09:00", "10:00", room_id=1, day=d)
        self.book("11:00", "12:00", room_id=1, day=d)
        self.book("09:00", "10:00", room_id=2, day=d)
        status, _ = self.request("DELETE", "/api/bookings/%d" % b1["booking"]["id"], {"booker": "Alex"})
        self.assertEqual(status, 200)
        body = self.stats(d, d)
        t = body["totals"]
        self.assertEqual(t["bookings"], 3)          # cancelled still counted as created
        self.assertEqual(t["cancelled"], 1)
        self.assertEqual(t["hours_reserved"], 2.0)  # cancelled hour excluded
        self.assertAlmostEqual(t["cancellation_rate"], 33.3, places=1)
        rooms = {r["room"]: r for r in body["rooms"]}
        self.assertEqual(rooms["Cedar"]["cancelled"], 1)
        self.assertEqual(rooms["Cedar"]["bookings"], 2)
        self.assertEqual(rooms["Cedar"]["hours"], 1.0)
        self.assertAlmostEqual(rooms["Cedar"]["cancellation_rate"], 50.0, places=1)
        self.assertEqual(rooms["Birch"]["cancellation_rate"], 0.0)

    def test_cancelled_slot_bookable_again(self):
        d = tomorrow()
        _, b = self.book("14:00", "15:00", room_id=1, day=d)
        bid = b["booking"]["id"]
        self.assertEqual(self.request("DELETE", "/api/bookings/%d" % bid, {"booker": "Alex"})[0], 200)
        # availability shows the slot free again
        status, avail = self.request("GET", "/api/availability?date=%s&room=1" % d)
        self.assertEqual(status, 200)
        slot = [s for s in avail["rooms"][0]["slots"] if s["start"] == "14:00"][0]
        self.assertTrue(slot["free"])
        # and it can be booked again (no double booking)
        self.assertEqual(self.book("14:00", "15:00", booker="Sam", room_id=1, day=d)[0], 201)
        # the cancelled row is kept for statistics
        conn = app.connect()
        rows = conn.execute("SELECT cancelled_at FROM bookings WHERE id = ?", (bid,)).fetchone()
        conn.close()
        self.assertIsNotNone(rows["cancelled_at"])
        # active bookings list does not show the cancelled one
        status, body = self.request("GET", "/api/bookings?date=%s" % d)
        self.assertEqual([x["booker"] for x in body["bookings"]], ["Sam"])

    def test_migration_of_old_db_without_cancelled_at(self):
        old_path = os.path.join(TMP, "old_bookings.db")
        if os.path.exists(old_path):
            os.remove(old_path)
        conn = sqlite3.connect(old_path)
        conn.executescript("""
            CREATE TABLE rooms (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, capacity INTEGER NOT NULL);
            CREATE TABLE bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER NOT NULL,
                date TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, booker TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE (room_id, date, start));
            INSERT INTO rooms (name, capacity) VALUES ('Cedar', 4);
            INSERT INTO bookings (room_id, date, start, end, booker, created_at)
                VALUES (1, '2024-01-02', '09:00', '10:00', 'Old', '2024-01-01T10:00:00');
        """)
        conn.commit()
        conn.close()
        saved = app.DB_PATH
        app.DB_PATH = old_path
        try:
            app.init_db()          # must add cancelled_at without losing data
            app.init_db()          # idempotent
            conn = app.connect()
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(bookings)")}
            self.assertIn("cancelled_at", cols)
            row = conn.execute("SELECT booker, cancelled_at FROM bookings").fetchone()
            self.assertEqual(row["booker"], "Old")
            self.assertIsNone(row["cancelled_at"])
            conn.close()
            stats = app.compute_stats(date(2024, 1, 1), date(2024, 1, 31))
            self.assertEqual(stats["totals"]["bookings"], 1)
            self.assertEqual(stats["totals"]["hours_reserved"], 1.0)
        finally:
            app.DB_PATH = saved

    def test_invalid_date_ranges(self):
        cases = [
            "start=%s&end=%s" % (tomorrow(), date.today().isoformat()),   # start after end
            "start=%s&end=%s" % (date.today().isoformat(), days_ahead(400)),  # too long
            "start=not-a-date&end=%s" % tomorrow(),
            "start=%s&end=2025-02-30" % tomorrow(),
            "start=%s" % tomorrow(),                                       # end missing
        ]
        for qs in cases:
            status, body = self.request("GET", "/api/stats?" + qs)
            self.assertEqual(status, 400, (qs, body))
            self.assertIn("error", body)
            self.assertNotIn("Traceback", body["error"])
        status, body = self.request("GET", "/api/stats?start=%s&end=%s" % (tomorrow(), tomorrow()))
        self.assertEqual(status, 200, body)
        # exactly 366 days is allowed, 367 is not
        start = date.today() - timedelta(days=300)
        self.assertEqual(self.request("GET", "/api/stats?start=%s&end=%s"
                                      % (start.isoformat(), (start + timedelta(days=365)).isoformat()))[0], 200)
        self.assertEqual(self.request("GET", "/api/stats?start=%s&end=%s"
                                      % (start.isoformat(), (start + timedelta(days=366)).isoformat()))[0], 400)
        # the dashboard page shows the error instead of crashing
        status, html = self.page("/dashboard?start=%s&end=%s" % (tomorrow(), date.today().isoformat()))
        self.assertEqual(status, 200)
        self.assertIn("start date must be on or before the end date", html)

    def test_dashboard_page_and_empty_state(self):
        status, html = self.page("/dashboard")
        self.assertEqual(status, 200)
        self.assertIn("Room usage dashboard", html)
        self.assertIn("No bookings in this range", html)      # empty state, no fake data
        self.assertIn('href="/"', html)                       # link back to booking page
        self.assertIn("7 days", html)
        self.assertIn("30 days", html)
        self.assertIn("90 days", html)
        self.assertNotIn("<script", html)                     # no JS needed
        # booking page links to the dashboard
        status, index = self.page("/")
        self.assertIn('href="/dashboard"', index)
        # with data the page renders charts and the summary
        d = tomorrow()
        self.book("09:00", "10:00", room_id=1, day=d)
        status, html = self.page("/dashboard?start=%s&end=%s" % (d, d))
        self.assertEqual(status, 200)
        self.assertIn("<svg", html)
        self.assertIn("What this suggests", html)
        self.assertIn("Allocation suggestion", html)
        self.assertIn("Cedar", html)
        self.assertNotIn("No bookings in this range", html)

    def test_stats_default_range_is_last_30_days(self):
        status, body = self.request("GET", "/api/stats")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["range"]["end"], date.today().isoformat())
        self.assertEqual(body["range"]["start"], (date.today() - timedelta(days=29)).isoformat())
        self.assertEqual(body["range"]["days"], 30)


if __name__ == "__main__":
    unittest.main()
