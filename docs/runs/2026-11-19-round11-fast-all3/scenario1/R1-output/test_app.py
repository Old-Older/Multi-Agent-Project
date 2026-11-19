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


if __name__ == "__main__":
    unittest.main(verbosity=2)
