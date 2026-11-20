import json, os, subprocess, sys, time, urllib.request, urllib.error, tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(tempfile.mkdtemp(), "data.json")
PORT = 8765
BASE = "http://127.0.0.1:%d" % PORT
D = (date.today() + timedelta(days=1)).isoformat()

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

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(extra)) if not cond else ""))
    if not cond: fails.append(name)

srv = subprocess.Popen([sys.executable, os.path.join(HERE, "app.py"), "--port", str(PORT), "--data", DATA],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/api/rooms"); break
        except Exception: time.sleep(0.1)

    # page
    with urllib.request.urlopen(BASE + "/") as r:
        html = r.read().decode()
    check("index page served", r.status == 200 and "Meeting Room Booking" in html and "aspen" in html)

    # availability
    s, av = req("/api/availability?date=" + D)
    check("availability 200", s == 200 and len(av["rooms"]) == 4, av)
    check("20 slots per room", len(av["rooms"][0]["slots"]) == 20, len(av["rooms"][0]["slots"]))
    check("all free initially", all(x["free"] for r in av["rooms"] for x in r["slots"]))

    # book
    s, b1 = req("/api/book", {"room": "aspen", "date": D, "start": "09:00", "end": "10:00",
                              "booker": "Ann", "title": "Standup"})
    check("book 201", s == 201 and b1["id"] == 1, (s, b1))

    # conflict (overlap)
    s, e = req("/api/book", {"room": "aspen", "date": D, "start": "09:30", "end": "10:30",
                             "booker": "Bob", "title": "Clash"})
    check("overlap rejected 400", s == 400, (s, e))
    check("conflict names booking", "Ann" in e.get("error", "") and "09:00" in e.get("error", ""), e)

    # adjacent is fine
    s, b2 = req("/api/book", {"room": "aspen", "date": D, "start": "10:00", "end": "11:00",
                              "booker": "Bob", "title": "Adjacent"})
    check("adjacent booking ok", s == 201, (s, b2))

    # other room same time fine
    s, b3 = req("/api/book", {"room": "birch", "date": D, "start": "09:00", "end": "10:00",
                              "booker": "Cy", "title": "Other room"})
    check("other room same time ok", s == 201, (s, b3))

    # validation
    for name, body, frag in [
        ("too long", {"room": "cedar", "date": D, "start": "08:00", "end": "13:00", "booker": "X"}, "Maximum"),
        ("outside hours", {"room": "cedar", "date": D, "start": "07:00", "end": "08:00", "booker": "X"}, "working hours"),
        ("bad room", {"room": "zzz", "date": D, "start": "08:00", "end": "09:00", "booker": "X"}, "Unknown room"),
        ("no booker", {"room": "cedar", "date": D, "start": "08:00", "end": "09:00", "booker": " "}, "Booker"),
        ("past date", {"room": "cedar", "date": "2000-01-01", "start": "08:00", "end": "09:00", "booker": "X"}, "past"),
        ("beyond horizon", {"room": "cedar", "date": (date.today()+timedelta(days=90)).isoformat(),
                            "start": "08:00", "end": "09:00", "booker": "X"}, "60 days"),
        ("end before start", {"room": "cedar", "date": D, "start": "10:00", "end": "09:00", "booker": "X"}, "after start"),
    ]:
        s, e = req("/api/book", body)
        check("reject " + name, s == 400 and frag in e.get("error", ""), (s, e))

    # availability reflects bookings
    s, av = req("/api/availability?date=%s&room=aspen" % D)
    slots = {x["start"]: x for x in av["rooms"][0]["slots"]}
    check("09:00 busy", not slots["09:00"]["free"] and slots["09:00"]["booking"]["booker"] == "Ann")
    check("10:00 busy", not slots["10:00"]["free"])
    check("11:00 free", slots["11:00"]["free"])

    # list
    s, lst = req("/api/bookings?date=" + D)
    check("list has 3", s == 200 and len(lst["bookings"]) == 3, lst)

    # cancel frees slot
    s, c = req("/api/cancel", {"id": 1})
    check("cancel 200", s == 200 and c["cancelled"]["booker"] == "Ann", (s, c))
    s, av = req("/api/availability?date=%s&room=aspen" % D)
    slots = {x["start"]: x for x in av["rooms"][0]["slots"]}
    check("slot freed after cancel", slots["09:00"]["free"] and slots["09:30"]["free"])
    s, lst = req("/api/bookings?date=" + D)
    check("no stale record", all(b["id"] != 1 for b in lst["bookings"]) and len(lst["bookings"]) == 2)

    # rebook freed slot
    s, b4 = req("/api/book", {"room": "aspen", "date": D, "start": "09:00", "end": "10:00",
                              "booker": "Dee", "title": "Rebook"})
    check("rebook freed slot", s == 201, (s, b4))

    # cancel twice
    s, e = req("/api/cancel", {"id": 1})
    check("double cancel rejected", s == 400 and "No booking" in e.get("error", ""), (s, e))

    # concurrency: 12 parallel identical bookings -> exactly 1 wins
    import threading
    results = []
    def go():
        results.append(req("/api/book", {"room": "dune", "date": D, "start": "14:00", "end": "15:00",
                                         "booker": "Racer", "title": "Race"})[0])
    ts = [threading.Thread(target=go) for _ in range(12)]
    [t.start() for t in ts]; [t.join() for t in ts]
    check("concurrent: exactly one 201", results.count(201) == 1, results)

    # ---- XSS: booker/title are stored raw but must be escaped by the page JS
    s, bx = req("/api/book", {"room": "cedar", "date": D, "start": "11:00", "end": "12:00",
                              "booker": "<script>alert(1)</script>", "title": "\"><img src=x onerror=alert(2)>"})
    check("xss booking accepted", s == 201, (s, bx))
    check("page escapes grid cell", 'title="${esc(b.booker)}: ${esc(b.title)}' in html
          and '>${esc(b.booker)}</button>' in html, "grid cell not escaped")
    check("page escapes success message", "for ${b.booker}." in html and "esc(b.booker)" in html)
    check("page has esc() helper", "function esc(s)" in html)
    s, lst = req("/api/bookings?date=" + D)
    xb = [b for b in lst["bookings"] if b["booker"].startswith("<script>")]
    check("xss booking listed raw in JSON", len(xb) == 1, lst)
    req("/api/cancel", {"id": bx["id"]})

    # ---- pre-filled end time logic (mirrors the page JS)
    def js_end(start):
        h, mi = [int(x) for x in start.split(":")]
        return min(h * 60 + mi + 60, 18 * 60)
    check("prefill end 09:00 -> 10:00", js_end("09:00") == 600)
    check("prefill end 14:30 -> 15:30", js_end("14:30") == 930)
    check("prefill end 17:30 -> 18:00", js_end("17:30") == 1080)
    check("page uses split(':') for prefill", "start.split(':').map(Number)" in html
          and "parseInt(start)*60" not in html)
    check("page uses local date formatter", "toISOString" not in html and "getFullYear()" in html)
    check("form date min/max set", "$('#f_date').min=$('#date').min" in html)
    check("booker remembered", "localStorage.setItem('lastBooker'" in html)
    check("enter submits form", "ev.key==='Enter'" in html)
    check("upcoming table present", 'id="upcoming"' in html and "loadUpcoming" in html)

    # ---- past-date availability: real bookings, read-only flag
    past = (date.today() - timedelta(days=7)).isoformat()
    s, pav = req("/api/availability?date=" + past)
    check("past availability 200", s == 200, (s, pav))
    check("past flagged read-only", pav.get("past") is True and pav.get("read_only") is True, pav)
    s, fav = req("/api/availability?date=" + D)
    check("future not read-only", fav.get("past") is False, fav.get("past"))
    s, e = req("/api/book", {"room": "aspen", "date": past, "start": "09:00", "end": "10:00", "booker": "X"})
    check("past booking still rejected", s == 400 and "past" in e.get("error", ""), (s, e))

    # ---- upcoming bookings endpoint (no date -> all bookings)
    s, allb = req("/api/bookings")
    check("upcoming endpoint 200", s == 200 and isinstance(allb.get("bookings"), list), (s, allb))
    s, dayb = req("/api/bookings?date=" + D)
    check("upcoming has >= day bookings", len(allb["bookings"]) >= len(dayb["bookings"]), (allb, dayb))
    check("upcoming rows decorated", all("room_name" in b and "date" in b for b in allb["bookings"]))
    s, rb = req("/api/bookings?room=aspen")
    check("upcoming room filter", s == 200 and all(b["room"] == "aspen" for b in rb["bookings"]), rb)

    # ---- favicon 204
    try:
        with urllib.request.urlopen(BASE + "/favicon.ico") as r:
            check("favicon 204", r.status == 204, r.status)
    except urllib.error.HTTPError as e:
        check("favicon 204", e.code == 204, e.code)

    # CLI against same data file
    env = dict(os.environ)
    def cli(*args):
        return subprocess.run([sys.executable, os.path.join(HERE, "cli.py")] + list(args),
                              capture_output=True, text=True, env=env, cwd=HERE)
    # point CLI at test data via a tiny wrapper
    wrapper = os.path.join(HERE, "_cli_test.py")
    with open(wrapper, "w") as f:
        f.write("import sys, app\napp.DATA_PATH=%r\napp._LOCK_PATH=%r\nimport cli\nsys.exit(cli.main(sys.argv[1:]))\n"
                % (DATA, DATA + ".lock"))
    def cli2(*args):
        return subprocess.run([sys.executable, wrapper] + list(args), capture_output=True, text=True)
    r = cli2("list", "--date", D)
    check("cli list", r.returncode == 0 and "Dee" in r.stdout, r.stdout + r.stderr)
    r = cli2("book", "--room", "cedar", "--date", D, "--start", "16:00", "--end", "17:00",
             "--booker", "Eve", "--title", "CLI")
    check("cli book", r.returncode == 0 and "Booked" in r.stdout, r.stdout + r.stderr)
    r = cli2("book", "--room", "cedar", "--date", D, "--start", "16:30", "--end", "17:30", "--booker", "Zed")
    check("cli conflict exit 1", r.returncode == 1 and "Conflict" in r.stderr, r.stdout + r.stderr)
    bid = [b for b in req("/api/bookings?date=" + D)[1]["bookings"] if b["booker"] == "Eve"][0]["id"]
    r = cli2("cancel", "--id", str(bid))
    check("cli cancel", r.returncode == 0 and "Cancelled" in r.stdout, r.stdout + r.stderr)
    os.unlink(wrapper)
finally:
    srv.terminate(); srv.wait()

print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
