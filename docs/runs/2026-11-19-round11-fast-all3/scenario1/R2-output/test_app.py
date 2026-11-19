#!/usr/bin/env python3
"""Self-tests for app.py. Run:  python3 test_app.py"""
import os
import tempfile
import threading
import unittest
from datetime import date, timedelta

import app


def next_weekday(offset_days=1):
    d = date.today() + timedelta(days=offset_days)
    while d.weekday() > 4:
        d += timedelta(days=1)
    return d


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self._old = app.DATA_FILE
        app.DATA_FILE = self.tmp.name
        self.day = next_weekday().isoformat()

    def tearDown(self):
        app.DATA_FILE = self._old
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_overlap_rejected(self):
        b, err = app.add_booking("Aspen", self.day, "09:00", "10:00", "Standup", "Ann")
        self.assertIsNone(err)
        self.assertIsNotNone(b)
        # exact same slot
        b2, err2 = app.add_booking("Aspen", self.day, "09:00", "10:00", "Other", "Bob")
        self.assertIsNone(b2)
        self.assertIn("Double booking", err2)
        # partial overlap
        b3, err3 = app.add_booking("Aspen", self.day, "09:30", "10:30", "Other", "Bob")
        self.assertIsNone(b3)
        self.assertIn("Double booking", err3)
        # different room is fine
        b4, err4 = app.add_booking("Birch", self.day, "09:00", "10:00", "Other", "Bob")
        self.assertIsNone(err4)
        # adjacent slot is fine (no buffer)
        b5, err5 = app.add_booking("Aspen", self.day, "10:00", "11:00", "Next", "Bob")
        self.assertIsNone(err5)

    def test_cancel_frees_slot(self):
        b, err = app.add_booking("Cedar", self.day, "11:00", "12:00", "Review", "Ann")
        self.assertIsNone(err)
        av = app.availability(self.day)
        cedar = [r for r in av["rooms"] if r["name"] == "Cedar"][0]
        cell = [c for c in cedar["cells"] if c["start"] == "11:00"][0]
        self.assertFalse(cell["free"])
        ok, err = app.cancel_booking(b["id"])
        self.assertTrue(ok, err)
        av = app.availability(self.day)
        cedar = [r for r in av["rooms"] if r["name"] == "Cedar"][0]
        cell = [c for c in cedar["cells"] if c["start"] == "11:00"][0]
        self.assertTrue(cell["free"])
        # slot can be booked again
        b2, err2 = app.add_booking("Cedar", self.day, "11:00", "12:00", "Review 2", "Bob")
        self.assertIsNone(err2)

    def test_recurring_skips_conflicts(self):
        first = next_weekday()
        week2 = (first + timedelta(weeks=1)).isoformat()
        week3 = (first + timedelta(weeks=2)).isoformat()
        # block week 2
        b, err = app.add_booking("Dune", week2, "14:00", "15:00", "Blocker", "Zed")
        self.assertIsNone(err)
        res, err = app.add_recurring("Dune", first.isoformat(), "14:00", "15:00", "Weekly", "Ann", 3)
        self.assertIsNone(err)
        self.assertEqual(len(res["created"]), 2)
        self.assertEqual(len(res["skipped"]), 1)
        self.assertEqual(res["skipped"][0]["date"], week2)
        self.assertIn("Double booking", res["skipped"][0]["reason"])
        dates = [b["date"] for b in res["created"]]
        self.assertIn(first.isoformat(), dates)
        self.assertIn(week3, dates)

    def test_validation_rules(self):
        _, err = app.add_booking("Aspen", self.day, "09:00", "10:00", "T", "")
        self.assertIn("name", err)
        _, err = app.add_booking("Aspen", self.day, "09:00", "14:00", "T", "Ann")
        self.assertIn("4 hours", err)
        _, err = app.add_booking("Aspen", self.day, "07:00", "08:00", "T", "Ann")
        self.assertIn("08:00", err)
        far = (date.today() + timedelta(days=90)).isoformat()
        _, err = app.add_booking("Aspen", far, "09:00", "10:00", "T", "Ann")
        self.assertIn("60 days", err)
        _, err = app.add_booking("Aspen", self.day, "10:00", "09:00", "T", "Ann")
        self.assertIn("after start", err)

    def test_concurrent_requests_cannot_double_book(self):
        results = []

        def worker(name):
            results.append(app.add_booking("Birch", self.day, "15:00", "16:00", "Race", name))

        threads = [threading.Thread(target=worker, args=("U%d" % i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        winners = [r for r in results if r[0] is not None]
        self.assertEqual(len(winners), 1, "exactly one booking must win the race")


class DashboardTests(unittest.TestCase):
    """Hand-built dataset: 2024-03-04 (Mon) .. 2024-03-08 (Fri)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self._old = app.DATA_FILE
        app.DATA_FILE = self.tmp.name
        self.start, self.end = "2024-03-04", "2024-03-08"
        rows = [
            # Cedar heavily used: 5 bookings on Tue, 08:00-18:00 = 10h
            ("Cedar", "2024-03-05", 480, 720, "Ann", False),
            ("Cedar", "2024-03-05", 720, 960, "Ann", False),
            ("Cedar", "2024-03-05", 960, 1080, "Bob", False),
            ("Cedar", "2024-03-05", 480, 600, "Bob", False),
            ("Cedar", "2024-03-05", 600, 720, "Chen", False),
            # Aspen: 09:00-10:30 on Monday -> hour 9 +1, hour 10 +0.5
            ("Aspen", "2024-03-04", 540, 630, "Dana", False),
            # Dune: one cancelled booking only
            ("Dune", "2024-03-06", 600, 660, "Eli", True),
        ]
        bookings = []
        for i, (room, day, s, e, who, cancelled) in enumerate(rows):
            b = {"id": "b%d" % i, "room": room, "date": day, "start": s, "end": e,
                 "title": "T%d" % i, "booker": who, "created": "2024-03-01T09:00:00",
                 "cancelled": cancelled}
            if cancelled:
                b["cancelled_at"] = "2024-03-02T09:00:00"
            bookings.append(b)
        app.save({"bookings": bookings})

    def tearDown(self):
        app.DATA_FILE = self._old
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_counts_hours_and_cancel_rate(self):
        st = app.dashboard_stats(self.start, self.end)
        self.assertIsNone(st["range"]["error"])
        self.assertEqual(st["range"]["days"], 5)
        self.assertEqual(st["range"]["weekdays"], 5)
        self.assertEqual(st["totals"]["bookings"], 6)
        self.assertEqual(st["totals"]["cancelled"], 1)
        self.assertEqual(st["totals"]["all_created"], 7)
        self.assertAlmostEqual(st["totals"]["cancel_rate"], 1 / 7.0, places=3)
        # 4h + 4h + 2h + 2h + 2h + 1.5h = 15.5h
        self.assertAlmostEqual(st["totals"]["hours_reserved"], 15.5, places=2)
        self.assertAlmostEqual(st["totals"]["avg_hours"], 15.5 / 6, places=2)
        self.assertEqual(st["totals"]["unique_bookers"], 4)

    def test_weekday_and_hour_buckets(self):
        st = app.dashboard_stats(self.start, self.end)
        self.assertEqual(len(st["by_weekday"]), 7)
        self.assertEqual(st["by_weekday"][1]["name"], "Tuesday")
        self.assertEqual(st["by_weekday"][1]["bookings"], 5)
        self.assertEqual(st["by_weekday"][0]["bookings"], 1)
        self.assertEqual(st["by_weekday"][5]["bookings"], 0)
        self.assertEqual(st["busiest_day"], "Tuesday")
        hours = {e["hour"]: e for e in st["by_hour"]}
        self.assertEqual(len(st["by_hour"]), 10)
        self.assertEqual(st["by_hour"][0]["label"], "08:00")
        # Aspen 09:00-10:30 -> hour 9 gets 1 booking / 1.0h, hour 10 gets 1 booking / 0.5h
        aspen = [r for r in st["by_room_hour"] if r["room"] == "Aspen"][0]["cells"]
        self.assertEqual(aspen[1], 1)   # 09:00
        self.assertEqual(aspen[2], 1)   # 10:00
        self.assertEqual(aspen[0], 0)   # 08:00
        self.assertEqual(hours[9]["bookings"], 3)   # Aspen + 2 Cedar bookings
        self.assertAlmostEqual(hours[9]["hours"], 3.0, places=2)
        self.assertEqual(hours[10]["bookings"], 3)
        self.assertAlmostEqual(hours[10]["hours"], 2.5, places=2)
        self.assertEqual(hours[8]["bookings"], 2)
        self.assertEqual(len(st["by_room_hour"]), 4)
        self.assertEqual(len(st["by_room_hour"][0]["cells"]), 10)
        self.assertEqual(len(st["by_week"]), 1)
        self.assertEqual(st["by_week"][0]["week_start"], "2024-03-04")
        self.assertEqual(st["by_week"][0]["bookings"], 6)
        self.assertEqual(st["top_days"][0]["date"], "2024-03-05")
        self.assertEqual(st["top_days"][0]["bookings"], 5)

    def test_utilisation_and_recommendations(self):
        st = app.dashboard_stats(self.start, self.end)
        rooms = {r["room"]: r for r in st["per_room"]}
        # Cedar: 4h+4h+2h+2h+2h = 14h of 50 available hours (raw records may overlap)
        self.assertAlmostEqual(rooms["Cedar"]["hours"], 14.0, places=2)
        self.assertAlmostEqual(rooms["Cedar"]["utilisation"], 14.0 / 50.0, places=3)
        self.assertEqual(rooms["Cedar"]["cancelled"], 0)
        self.assertEqual(rooms["Dune"]["bookings"], 0)
        self.assertEqual(rooms["Dune"]["cancelled"], 1)
        self.assertAlmostEqual(rooms["Dune"]["utilisation"], 0.0, places=3)
        self.assertEqual(rooms["Dune"]["cancel_rate"], 1.0)
        self.assertEqual(st["busiest_room"], "Cedar")
        self.assertEqual(st["quietest_room"], "Dune")
        recs = " ".join(st["recommendations"])
        self.assertIn("Dune", recs)
        self.assertIn("underused", recs.lower() + " underused")
        self.assertIn("Cancellation rate", recs)

    def test_heavily_used_room_flagged(self):
        # 5 weekdays x 10h = 50h available; add 30h in Cedar -> 40h = 80% -> heavily used
        data = app.load()
        for i in range(15):
            data["bookings"].append({"id": "x%d" % i, "room": "Cedar", "date": "2024-03-06",
                                     "start": 480 + (i % 5) * 120, "end": 480 + (i % 5) * 120 + 120,
                                     "title": "T", "booker": "Zed", "created": "2024-03-01T09:00:00",
                                     "cancelled": False})
        app.save(data)
        st = app.dashboard_stats(self.start, self.end)
        cedar = [r for r in st["per_room"] if r["room"] == "Cedar"][0]
        self.assertGreaterEqual(cedar["utilisation"], 0.75)
        self.assertEqual(cedar["status"], "Heavily used")
        recs = " ".join(st["recommendations"])
        self.assertIn("Cedar is", recs)
        self.assertIn("consider moving small meetings", recs)

    def test_empty_range(self):
        st = app.dashboard_stats("2024-04-01", "2024-04-05")
        self.assertIsNone(st["range"]["error"])
        self.assertEqual(st["totals"]["bookings"], 0)
        self.assertEqual(st["totals"]["cancel_rate"], 0)
        self.assertEqual(st["totals"]["hours_reserved"], 0)
        self.assertTrue(st["recommendations"])
        self.assertIn("No bookings", st["recommendations"][0])

    def test_invalid_range(self):
        st = app.dashboard_stats("2024-03-08", "2024-03-04")
        self.assertIsNotNone(st["range"]["error"])
        self.assertEqual(st["totals"]["bookings"], 0)
        st2 = app.dashboard_stats("2023-01-01", "2024-12-31")
        self.assertIsNotNone(st2["range"]["error"])
        st3 = app.dashboard_stats("not-a-date", "2024-03-04")
        self.assertIsNotNone(st3["range"]["error"])

    def test_dashboard_http_routes(self):
        import json as _json
        import threading
        import urllib.request
        srv = app.make_server("127.0.0.1", 0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            base = "http://127.0.0.1:%d" % port
            for path in ("/dashboard", "/dashboard?days=7",
                         "/dashboard?start=%s&end=%s" % (self.start, self.end)):
                with urllib.request.urlopen(base + path, timeout=10) as r:
                    self.assertEqual(r.status, 200)
                    html = r.read().decode("utf-8")
                    self.assertIn("Dashboard", html)
            with urllib.request.urlopen(base + "/api/dashboard?start=%s&end=%s" % (self.start, self.end),
                                        timeout=10) as r:
                self.assertEqual(r.status, 200)
                payload = _json.loads(r.read().decode("utf-8"))
            self.assertEqual(payload["totals"]["bookings"], 6)
            self.assertIn("per_room", payload)
            self.assertIn("recommendations", payload)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
