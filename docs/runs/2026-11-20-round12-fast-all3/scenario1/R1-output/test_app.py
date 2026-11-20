#!/usr/bin/env python3
"""API tests for app.py. Run: python3 test_app.py

Starts the server on a free port with a temporary database, exercises the API
with urllib, then shuts it down.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.port = free_port()
        env = dict(os.environ, PORT=str(cls.port), BOOKING_DB=os.path.join(cls.tmp, "test.db"))
        cls.proc = subprocess.Popen([sys.executable, APP], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = "http://127.0.0.1:%d" % cls.port
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/health", timeout=1).read()
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)

    # helpers
    def call(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def day(self, offset=1):
        return (date.today() + timedelta(days=offset)).isoformat()

    def book(self, room_id, start, end, booker="Sam", title="Sync", day=None):
        return self.call("POST", "/api/bookings", {
            "room_id": room_id, "date": day or self.day(),
            "start": start, "end": end, "booker": booker, "title": title})

    # tests
    def test_rooms(self):
        status, body = self.call("GET", "/api/rooms")
        self.assertEqual(status, 200)
        names = [(r["name"], r["capacity"]) for r in body["rooms"]]
        self.assertEqual(names, [("Aurora", 8), ("Birch", 4), ("Cedar", 12), ("Dune", 20)])

    def test_availability_shape(self):
        status, body = self.call("GET", "/api/availability?date=" + self.day())
        self.assertEqual(status, 200)
        self.assertEqual(len(body["rooms"]), 4)
        self.assertEqual(len(body["rooms"][0]["slots"]), 20)  # 08:00-18:00 in 30 min
        self.assertEqual(body["rooms"][0]["slots"][0]["start"], "08:00")
        self.assertEqual(body["rooms"][0]["slots"][-1]["start"], "17:30")

    def test_book_and_availability_reflects_it(self):
        d = self.day(2)
        status, body = self.book(1, "09:00", "10:00", day=d)
        self.assertEqual(status, 201, body)
        bid = body["booking"]["id"]
        self.assertEqual(body["booking"]["status"], "active")
        _, avail = self.call("GET", "/api/availability?date=" + d)
        aurora = [r for r in avail["rooms"] if r["room_id"] == 1][0]
        busy = [s["start"] for s in aurora["slots"] if s["status"] == "busy"]
        self.assertEqual(busy, ["09:00", "09:30"])
        # other room unaffected
        birch = [r for r in avail["rooms"] if r["room_id"] == 2][0]
        self.assertTrue(all(s["status"] == "free" for s in birch["slots"]))
        # cancel -> immediately free again
        status, body = self.call("POST", "/api/bookings/%d/cancel" % bid)
        self.assertEqual(status, 200)
        self.assertEqual(body["booking"]["status"], "cancelled")
        _, avail = self.call("GET", "/api/availability?date=" + d)
        aurora = [r for r in avail["rooms"] if r["room_id"] == 1][0]
        self.assertTrue(all(s["status"] == "free" for s in aurora["slots"]))
        # cancelled booking still listed
        _, listing = self.call("GET", "/api/bookings?date=" + d)
        self.assertEqual([b["status"] for b in listing["bookings"]], ["cancelled"])
        # cancelling twice -> 409
        self.assertEqual(self.call("POST", "/api/bookings/%d/cancel" % bid)[0], 409)
        # unknown id -> 404
        self.assertEqual(self.call("POST", "/api/bookings/999999/cancel")[0], 404)

    def test_double_booking_rejected(self):
        d = self.day(3)
        self.assertEqual(self.book(3, "10:00", "11:00", day=d)[0], 201)
        # exact overlap
        status, body = self.book(3, "10:00", "11:00", booker="Alex", day=d)
        self.assertEqual(status, 409)
        self.assertIn("already booked", body["error"])
        # partial overlap
        self.assertEqual(self.book(3, "10:30", "11:30", day=d)[0], 409)
        self.assertEqual(self.book(3, "09:30", "10:30", day=d)[0], 409)
        # contained
        self.assertEqual(self.book(3, "10:00", "10:30", day=d)[0], 409)
        # adjacent is fine
        self.assertEqual(self.book(3, "11:00", "12:00", day=d)[0], 201)
        self.assertEqual(self.book(3, "09:00", "10:00", day=d)[0], 201)
        # different room same time is fine
        self.assertEqual(self.book(4, "10:00", "11:00", day=d)[0], 201)

    def test_cancelled_does_not_block(self):
        d = self.day(4)
        _, body = self.book(2, "14:00", "15:00", day=d)
        self.call("POST", "/api/bookings/%d/cancel" % body["booking"]["id"])
        self.assertEqual(self.book(2, "14:00", "15:00", booker="Other", day=d)[0], 201)

    def test_validation(self):
        d = self.day(5)
        self.assertEqual(self.book(1, "09:00", "09:00", day=d)[0], 400)          # zero length
        self.assertEqual(self.book(1, "09:00", "13:30", day=d)[0], 400)          # > 4 hours
        self.assertEqual(self.book(1, "07:00", "08:00", day=d)[0], 400)          # before open
        self.assertEqual(self.book(1, "17:30", "18:30", day=d)[0], 400)          # after close
        self.assertEqual(self.book(1, "09:15", "10:00", day=d)[0], 400)          # off grid
        self.assertEqual(self.book(1, "09:00", "10:00", booker="  ", day=d)[0], 400)  # no booker
        self.assertEqual(self.book(99, "09:00", "10:00", day=d)[0], 400)         # unknown room
        self.assertEqual(self.book(1, "09:00", "10:00", day=self.day(-1))[0], 400)  # past
        self.assertEqual(self.call("GET", "/api/availability?date=nope")[0], 400)
        # exactly 4 hours is allowed
        self.assertEqual(self.book(1, "09:00", "13:00", day=d)[0], 201)

    def test_bookings_list_fields(self):
        d = self.day(6)
        self.book(4, "08:00", "08:30", booker="Kim", title="Standup", day=d)
        status, body = self.call("GET", "/api/bookings?date=" + d)
        self.assertEqual(status, 200)
        b = body["bookings"][0]
        for key in ("id", "room", "date", "start", "end", "booker", "title", "status"):
            self.assertIn(key, b)
        self.assertEqual((b["room"], b["booker"], b["title"]), ("Dune", "Kim", "Standup"))

    def test_index_page_served(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            html = r.read().decode()
        self.assertIn("Meeting Room Booking", html)
        self.assertNotIn("http://cdn", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
