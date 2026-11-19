import os, tempfile, threading, urllib.request, json
tmp = tempfile.mkdtemp()
os.environ["BOOKINGS_FILE"] = os.path.join(tmp, "bookings.json")
import app
app.DATA_FILE = os.environ["BOOKINGS_FILE"]
n = app.seed_demo()
print("seeded", n)
st = app.dashboard_stats(*app.resolve_range(days="90"))
print("totals", st["totals"])
print("range", st["range"])
print("recs:")
for r in st["recommendations"]:
    print("  -", r)
print("per_room:", [(r["room"], r["bookings"], r["hours"], r["utilisation"], r["status"]) for r in st["per_room"]])
print("weeks", len(st["by_week"]), "top_days", st["top_days"][:2])
srv = app.make_server("127.0.0.1", 0)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % port
for p in ["/", "/book", "/bookings", "/my", "/dashboard", "/dashboard?days=7", "/dashboard?days=90",
          "/dashboard?start=2020-01-01&end=2020-01-05", "/dashboard?start=2024-05-01&end=2024-01-01"]:
    with urllib.request.urlopen(base + p, timeout=10) as r:
        html = r.read().decode()
        print(p, r.status, len(html), "Dashboard" in html, "What to consider" in html, "heatmap" in html)
with urllib.request.urlopen(base + "/api/dashboard?days=30", timeout=10) as r:
    d = json.loads(r.read().decode())
    print("api keys", sorted(d.keys()))
srv.shutdown()
