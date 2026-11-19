"""Quick self-check for dashboard.py: temp data, --text numbers, HTTP endpoints."""
import json, os, subprocess, sys, tempfile, time, urllib.error, urllib.request
from datetime import date, timedelta

here = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
data = os.path.join(tmp, "bookings.json")
today = date.today()
rows, nid = [], 1
plan = [("Aurora", 0, "09:00", "10:00", "active"), ("Aurora", 1, "09:00", "10:30", "active"),
        ("Aurora", 2, "09:00", "10:00", "cancelled"), ("Borealis", 0, "14:00", "16:00", "active"),
        ("Borealis", 3, "14:00", "15:00", "cancelled"), ("Cascade", 5, "11:00", "12:00", "active"),
        ("Delta", 40, "10:00", "11:00", "active")]
for room, off, s, e, st in plan:
    rows.append({"id": nid, "room": room, "date": (today - timedelta(days=off)).isoformat(),
                 "start": s, "end": e, "title": "T", "booked_by": "Ana", "status": st,
                 "created_at": "2025-01-01T00:00:00"})
    nid += 1
json.dump({"next_id": nid, "bookings": rows}, open(data, "w"))

env = dict(os.environ, BOOKING_FILE=data)
f, t = (today - timedelta(days=6)).isoformat(), today.isoformat()
out = subprocess.run([sys.executable, os.path.join(here, "dashboard.py"), "--text", "--from", f, "--to", t],
                     capture_output=True, text=True, env=env, cwd=here)
print(out.stdout or out.stderr)
assert out.returncode == 0, out.stderr
assert "2.5" in out.stdout and "33.3" in out.stdout, "Aurora numbers wrong"
assert "Delta" in out.stdout and "No bookings at all" in out.stdout, "Delta should be idle in range"

port = 8792
srv = subprocess.Popen([sys.executable, os.path.join(here, "dashboard.py"), "--no-browser", "--port", str(port)],
                       env=env, cwd=here, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    for _ in range(60):
        try:
            page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).read().decode()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise SystemExit("server did not start: " + srv.stderr.read().decode())
    assert "Meeting room dashboard" in page and "/api/stats" in page
    js = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/stats?from={f}&to={t}", timeout=2).read())
    aur = [r for r in js["table"] if r["room"] == "Aurora"][0]
    assert aur["bookings"] == 2 and aur["hours"] == 2.5 and aur["cancelled"] == 1, aur
    assert js["total_cancelled"] == 2 and js["busiest_hour"] == "09:00", js["busiest_hour"]
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stats?from={t}&to={f}", timeout=2)
        raise SystemExit("bad range should be 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400
    print("HTTP checks OK: page 200, /api/stats 200 with correct numbers, bad range -> 400")
finally:
    srv.terminate()
print("ALL CHECKS PASSED")
