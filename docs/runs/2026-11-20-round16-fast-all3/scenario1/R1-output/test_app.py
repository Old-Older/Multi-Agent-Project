"""Smoke tests for app.py.

Run:  python3 -m unittest -v test_app

Starts the real HTTP server on a free port in a background thread, using a
temporary sqlite database, and exercises the API end to end.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import app


class BookingApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(cls.tmpdir.name, "test_bookings.db")
        app.init_db()
        cls.httpd = app.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.rooms = cls.get("/api/rooms")
        cls.room = {r["name"]: r["id"] for r in cls.rooms}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        cls.tmpdir.cleanup()

    # -- helpers -----------------------------------------------------------
    @classmethod
    def request(cls, method, path, payload=None):
        url = "http://127.0.0.1:%d%s" % (cls.port, path)
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                body = res.read().decode("utf-8")
                ctype = res.headers.get("Content-Type", "")
                return res.status, (json.loads(body) if "json" in ctype else body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            try:
                return exc.code, json.loads(body)
            except ValueError:
                return exc.code, body

    @classmethod
    def get(cls, path):
        return cls.request("GET", path)[1]

    def book(self, room="Aurora", date="2026-01-05", start="10:00", end="11:00",
             booker="Ada", title="Standup", notes="", repeat_weeks=0):
        return self.request("POST", "/api/bookings", {
            "room_id": self.room[room], "date": date, "start": start, "end": end,
            "booker": booker, "title": title, "notes": notes,
            "repeat_weeks": repeat_weeks,
        })

    # -- tests -------------------------------------------------------------
    def test_rooms_seeded(self):
        names = [r["name"] for r in self.rooms]
        self.assertEqual(names, ["Aurora", "Birch", "Cedar", "Dune"])
        caps = {r["name"]: r["capacity"] for r in self.rooms}
        self.assertEqual(caps, {"Aurora": 8, "Birch": 4, "Cedar": 12, "Dune": 6})

    def test_index_page_served(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Meeting Room Booking", body)

    def test_create_booking(self):
        status, body = self.book(room="Birch", date="2026-02-02", start="09:00", end="10:00")
        self.assertEqual(status, 201, body)
        self.assertEqual(body["count"], 1)
        created = body["created"][0]
        self.assertEqual(created["room"], "Birch")
        self.assertEqual(created["start"], "09:00")
        self.assertIsNone(created["cancelled_at"])

    def test_overlap_rejected_409(self):
        self.assertEqual(self.book(room="Cedar", date="2026-02-03", start="10:00", end="11:00")[0], 201)
        status, body = self.book(room="Cedar", date="2026-02-03", start="10:30", end="11:30")
        self.assertEqual(status, 409)
        self.assertIn("already booked", body["error"])
        # fully contained overlap
        self.assertEqual(self.book(room="Cedar", date="2026-02-03", start="10:15", end="10:30")[0], 409)
        # same room, different date is fine
        self.assertEqual(self.book(room="Cedar", date="2026-02-04", start="10:30", end="11:30")[0], 201)
        # different room, same time is fine
        self.assertEqual(self.book(room="Dune", date="2026-02-03", start="10:30", end="11:30")[0], 201)

    def test_adjacent_booking_accepted(self):
        self.assertEqual(self.book(room="Dune", date="2026-02-05", start="10:00", end="11:00")[0], 201)
        self.assertEqual(self.book(room="Dune", date="2026-02-05", start="11:00", end="12:00")[0], 201)
        self.assertEqual(self.book(room="Dune", date="2026-02-05", start="09:00", end="10:00")[0], 201)

    def test_cancel_frees_slot(self):
        status, body = self.book(room="Aurora", date="2026-02-06", start="14:00", end="15:00")
        self.assertEqual(status, 201)
        bid = body["created"][0]["id"]
        status, cancelled = self.request("POST", "/api/bookings/%d/cancel" % bid, {"cancelled_by": "Ada"})
        self.assertEqual(status, 200)
        self.assertIsNotNone(cancelled["cancelled_at"])
        self.assertEqual(cancelled["cancelled_by"], "Ada")
        # slot is free again
        self.assertEqual(self.book(room="Aurora", date="2026-02-06", start="14:00", end="15:00")[0], 201)
        # cancelling twice is a conflict
        self.assertEqual(self.request("POST", "/api/bookings/%d/cancel" % bid, {})[0], 409)
        # unknown booking
        self.assertEqual(self.request("POST", "/api/bookings/999999/cancel", {})[0], 404)

    def test_cancelled_booking_not_listed_but_kept(self):
        status, body = self.book(room="Birch", date="2026-02-09", start="08:00", end="09:00")
        bid = body["created"][0]["id"]
        self.request("POST", "/api/bookings/%d/cancel" % bid, {})
        active = self.get("/api/bookings?date=2026-02-09")
        self.assertEqual(active, [])
        all_rows = self.get("/api/bookings?date=2026-02-09&include_cancelled=1")
        self.assertEqual(len(all_rows), 1)
        self.assertIsNotNone(all_rows[0]["cancelled_at"])

    def test_cancelled_booking_no_longer_blocks(self):
        status, body = self.book(room="Cedar", date="2026-02-10", start="13:00", end="14:00")
        bid = body["created"][0]["id"]
        self.assertEqual(self.book(room="Cedar", date="2026-02-10", start="13:00", end="14:00")[0], 409)
        self.request("POST", "/api/bookings/%d/cancel" % bid, {})
        self.assertEqual(self.book(room="Cedar", date="2026-02-10", start="13:00", end="14:00")[0], 201)

    def test_availability_gaps(self):
        self.book(room="Aurora", date="2026-02-11", start="10:00", end="11:00")
        self.book(room="Aurora", date="2026-02-11", start="13:00", end="14:00")
        data = self.get("/api/availability?date=2026-02-11")
        aurora = [r for r in data["rooms"] if r["room"] == "Aurora"][0]
        self.assertEqual(len(aurora["bookings"]), 2)
        self.assertEqual(aurora["free"], [
            {"start": "08:00", "end": "10:00"},
            {"start": "11:00", "end": "13:00"},
            {"start": "14:00", "end": "19:00"},
        ])

    def test_validation_errors(self):
        cases = [
            dict(start="11:00", end="10:00"),          # end before start
            dict(start="10:00", end="10:00"),          # zero length
            dict(date="2026-13-01"),                   # bad date
            dict(date="not-a-date"),
            dict(start="07:00", end="08:00"),          # before opening
            dict(start="18:00", end="19:30"),          # after closing
            dict(start="10:07", end="11:00"),          # not 15-min granularity
            dict(booker=""),                           # missing name
            dict(title="   "),                         # blank title
            dict(repeat_weeks=99),                     # out of range
        ]
        for case in cases:
            with self.subTest(case=case):
                kwargs = {"room": "Dune", "date": "2026-03-01"}
                kwargs.update(case)
                status, body = self.book(**kwargs)
                self.assertEqual(status, 400, body)
                self.assertIn("error", body)
        # unknown room
        status, body = self.request("POST", "/api/bookings", {
            "room_id": 9999, "date": "2026-03-01", "start": "10:00", "end": "11:00",
            "booker": "Ada", "title": "X"})
        self.assertEqual(status, 400)

    def test_recurring_creates_all_weeks(self):
        status, body = self.book(room="Birch", date="2026-04-06", start="15:00", end="16:00",
                                 repeat_weeks=3)
        self.assertEqual(status, 201, body)
        self.assertEqual(body["count"], 4)
        dates = sorted(b["date"] for b in body["created"])
        self.assertEqual(dates, ["2026-04-06", "2026-04-13", "2026-04-20", "2026-04-27"])

    def test_recurring_conflict_is_all_or_nothing(self):
        # occupy the third week only
        self.assertEqual(self.book(room="Cedar", date="2026-05-20", start="09:00", end="10:00")[0], 201)
        status, body = self.book(room="Cedar", date="2026-05-06", start="09:00", end="10:00",
                                 repeat_weeks=3)
        self.assertEqual(status, 409, body)
        self.assertIn("2026-05-20", body["error"])
        # nothing from the series was created
        rows = self.get("/api/bookings?date=2026-05-06")
        self.assertEqual(rows, [])
        rows = self.get("/api/bookings?date=2026-05-13")
        self.assertEqual(rows, [])

    def test_export_csv(self):
        self.book(room="Dune", date="2026-06-01", start="08:00", end="09:00", title="CSV, test")
        status, body = self.request("GET", "/api/export.csv")
        self.assertEqual(status, 200)
        self.assertIn("room,date,start,end,booker,title", body)
        self.assertIn('"CSV, test"', body)

    def test_html_escaping_in_api_roundtrip(self):
        status, body = self.book(room="Dune", date="2026-06-02", start="10:00", end="11:00",
                                 title="<script>alert(1)</script>")
        self.assertEqual(status, 201)
        rows = self.get("/api/bookings?date=2026-06-02")
        self.assertEqual(rows[0]["title"], "<script>alert(1)</script>")
        # the page escapes on render (esc() helper present in the served HTML)
        _, html = self.request("GET", "/")
        self.assertIn("const esc =", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
