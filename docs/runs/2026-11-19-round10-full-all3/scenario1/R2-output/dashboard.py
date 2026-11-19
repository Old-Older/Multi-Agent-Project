#!/usr/bin/env python3
"""Manager dashboard for the meeting room booking system.

Reads the same booking records as booking.py (bookings.json, or the file in
BOOKING_FILE) and shows, for a selected date range:

  * how often each room is booked (bar chart + table)
  * total time reserved per room and utilisation % (bar chart + table)
  * busiest days (weekday bars, busiest dates) and busiest times
    (start-hour bars, weekday x hour heatmap)
  * cancellations: count, rate, per room, top rooms by cancellation rate
  * a short "What this suggests" summary (heavily used / underused rooms)

Usage:
  python dashboard.py                       # local web page on 127.0.0.1:8765
  python dashboard.py --port 9000 --no-browser
  python dashboard.py --text --from 2025-01-01 --to 2025-01-31 [--room Aurora]

Python 3 standard library only, no network assets, works offline.
The dashboard is read-only: it never writes to the booking data file.
"""
import argparse
import json
import os
import sys
import threading
import webbrowser
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import booking  # reuse storage, room list and opening hours

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
BOOKABLE_HOURS_PER_DAY = booking.CLOSE_HOUR - booking.OPEN_HOUR  # 10


# ------------------------------------------------------------------ helpers
def parse_day(text):
    return datetime.strptime(text, "%Y-%m-%d").date()


def _minutes(hhmm):
    """'09:30' -> 570; returns None for malformed values."""
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def booking_hours(b):
    """Duration of one booking in hours, clipped to opening hours; 0 if invalid."""
    s, e = _minutes(b.get("start")), _minutes(b.get("end"))
    if s is None or e is None or e <= s:
        return 0.0
    lo, hi = booking.OPEN_HOUR * 60, booking.CLOSE_HOUR * 60
    s, e = max(s, lo), min(e, hi)
    return max(0.0, (e - s) / 60.0)


def default_range():
    today = date.today()
    return today - timedelta(days=29), today


# ------------------------------------------------------------------ stats
def compute_stats(db, date_from, date_to, room=None):
    """All dashboard numbers for one date range. Used by web and --text."""
    rooms = [r["name"] for r in booking.ROOMS]
    if room:
        rooms = [r for r in rooms if r.lower() == room.strip().lower()] or rooms
    days = (date_to - date_from).days + 1
    per_room = {r: {"bookings": 0, "hours": 0.0, "cancelled": 0,
                    "weekday": Counter()} for r in rooms}
    by_weekday = Counter()
    by_date = Counter()
    by_hour = Counter()
    heat = {w: Counter() for w in WEEKDAYS}
    total_active = total_cancelled = 0
    skipped = 0

    for b in db.get("bookings", []):
        try:
            d = parse_day(b["date"])
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if d < date_from or d > date_to:
            continue
        name = str(b.get("room", ""))
        match = next((r for r in rooms if r.lower() == name.lower()), None)
        if match is None:
            skipped += 1
            continue
        status = b.get("status", "active")
        if status == "cancelled":
            per_room[match]["cancelled"] += 1
            total_cancelled += 1
            continue
        if status != "active":
            skipped += 1
            continue
        hours = booking_hours(b)
        per_room[match]["bookings"] += 1
        per_room[match]["hours"] += hours
        per_room[match]["weekday"][WEEKDAYS[d.weekday()]] += 1
        by_weekday[WEEKDAYS[d.weekday()]] += 1
        by_date[d.isoformat()] += 1
        start = _minutes(b.get("start"))
        if start is not None:
            hour = start // 60
            by_hour[hour] += 1
            heat[WEEKDAYS[d.weekday()]][hour] += 1
        total_active += 1

    capacity = days * BOOKABLE_HOURS_PER_DAY
    table = []
    for r in rooms:
        row = per_room[r]
        total = row["bookings"] + row["cancelled"]
        busiest = row["weekday"].most_common(1)
        table.append({
            "room": r,
            "bookings": row["bookings"],
            "hours": round(row["hours"], 1),
            "utilisation": round(100.0 * row["hours"] / capacity, 1) if capacity else 0.0,
            "cancelled": row["cancelled"],
            "cancel_rate": round(100.0 * row["cancelled"] / total, 1) if total else 0.0,
            "busiest_weekday": busiest[0][0] if busiest else "-",
        })

    busiest_weekday = by_weekday.most_common(1)
    busiest_hour = by_hour.most_common(1)
    top_dates = by_date.most_common(5)
    top_cancel = sorted([t for t in table if t["cancelled"]],
                        key=lambda t: (-t["cancel_rate"], -t["cancelled"]))[:3]

    heavy = [t["room"] for t in table if t["utilisation"] >= 70]
    light = [t["room"] for t in table if t["utilisation"] < 25]
    idle = [t["room"] for t in table if t["bookings"] == 0]
    notes = []
    if total_active == 0 and total_cancelled == 0:
        notes.append("No bookings in this range, so there is nothing to compare yet.")
    else:
        if heavy:
            notes.append("Heavily used (70%+ of bookable hours): " + ", ".join(heavy) +
                         " - keep these rooms as they are; consider adding capacity if they stay this full.")
        if light:
            notes.append("Underused (below 25% of bookable hours): " + ", ".join(light) +
                         " - candidates to repurpose or to move meetings into.")
        if idle:
            notes.append("No bookings at all in this range: " + ", ".join(idle) + ".")
        if busiest_weekday:
            notes.append(f"Busiest day is {busiest_weekday[0][0]} "
                         f"({busiest_weekday[0][1]} bookings); busiest start time is "
                         f"{busiest_hour[0][0]:02d}:00 ({busiest_hour[0][1]} bookings).")
        rate = 100.0 * total_cancelled / (total_active + total_cancelled)
        notes.append(f"{total_cancelled} of {total_active + total_cancelled} bookings were cancelled "
                     f"({rate:.1f}%).")
        if top_cancel:
            notes.append("Highest cancellation rate: " + ", ".join(
                f"{t['room']} {t['cancel_rate']:.1f}%" for t in top_cancel) + ".")

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "days": days,
        "room_filter": room or "",
        "rooms": rooms,
        "table": table,
        "by_weekday": {w: by_weekday.get(w, 0) for w in WEEKDAYS},
        "by_date": dict(sorted(by_date.items())),
        "top_dates": [{"date": d, "count": c} for d, c in top_dates],
        "by_hour": {h: by_hour.get(h, 0) for h in range(booking.OPEN_HOUR, booking.CLOSE_HOUR)},
        "heatmap": {w: {h: heat[w].get(h, 0) for h in range(booking.OPEN_HOUR, booking.CLOSE_HOUR)}
                    for w in WEEKDAYS},
        "total_active": total_active,
        "total_cancelled": total_cancelled,
        "cancel_rate": round(100.0 * total_cancelled / (total_active + total_cancelled), 1)
        if (total_active + total_cancelled) else 0.0,
        "busiest_weekday": busiest_weekday[0][0] if busiest_weekday else "-",
        "busiest_hour": f"{busiest_hour[0][0]:02d}:00" if busiest_hour else "-",
        "notes": notes,
        "skipped_records": skipped,
    }


# ------------------------------------------------------------------ text mode
def print_text(stats):
    print(f"Meeting room dashboard {stats['from']} .. {stats['to']} "
          f"({stats['days']} days)" + (f"  room={stats['room_filter']}" if stats["room_filter"] else ""))
    print(f"{'Room':<10}{'Bookings':>9}{'Hours':>8}{'Util%':>8}{'Cancelled':>11}{'Cancel%':>9}  Busiest day")
    for t in stats["table"]:
        print(f"{t['room']:<10}{t['bookings']:>9}{t['hours']:>8.1f}{t['utilisation']:>8.1f}"
              f"{t['cancelled']:>11}{t['cancel_rate']:>9.1f}  {t['busiest_weekday']}")
    print(f"\nTotal bookings: {stats['total_active']}   cancelled: {stats['total_cancelled']} "
          f"({stats['cancel_rate']:.1f}%)")
    print(f"Busiest weekday: {stats['busiest_weekday']}   busiest start hour: {stats['busiest_hour']}")
    print("Bookings per weekday: " + ", ".join(f"{w} {c}" for w, c in stats["by_weekday"].items()))
    print("Bookings per start hour: " + ", ".join(f"{h:02d}:00 {c}" for h, c in stats["by_hour"].items()))
    if stats["top_dates"]:
        print("Busiest dates: " + ", ".join(f"{d['date']} ({d['count']})" for d in stats["top_dates"]))
    print("\nWhat this suggests:")
    for n in stats["notes"]:
        print("  - " + n)


# ------------------------------------------------------------------ web page
PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Meeting room dashboard</title>
<style>
 body{font-family:system-ui,Arial,sans-serif;margin:0;background:#f6f7f9;color:#1b1f24}
 header{background:#1f3a5f;color:#fff;padding:14px 20px}
 header h1{margin:0;font-size:20px}
 main{padding:16px 20px;max-width:1100px}
 .controls{display:flex;flex-wrap:wrap;gap:10px;align-items:end;background:#fff;padding:12px;border-radius:8px;box-shadow:0 1px 3px #0002}
 label{font-size:12px;display:block;color:#444}
 input,select,button{font-size:14px;padding:5px 8px;border:1px solid #b9c0c8;border-radius:5px;background:#fff}
 button{cursor:pointer;background:#1f3a5f;color:#fff;border:none}
 button.alt{background:#e6ebf1;color:#1f3a5f}
 #err{color:#a1121b;font-weight:600;margin:8px 0}
 .card{background:#fff;border-radius:8px;box-shadow:0 1px 3px #0002;padding:14px;margin-top:14px}
 .card h2{font-size:15px;margin:0 0 10px}
 .bar{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:13px}
 .bar .lbl{width:90px;text-align:right;color:#333}
 .bar .track{flex:1;background:#eef1f4;border-radius:4px;height:18px;position:relative}
 .bar .fill{height:18px;border-radius:4px;background:#2b6cb0}
 .bar .val{width:70px;font-variant-numeric:tabular-nums}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{padding:5px 8px;border-bottom:1px solid #e3e7eb;text-align:right}
 th:first-child,td:first-child{text-align:left}
 .heat td{text-align:center;font-size:12px;border:1px solid #fff;padding:4px}
 .muted{color:#666;font-size:12px}
 ul.notes{margin:0;padding-left:18px;font-size:13px}
</style></head><body>
<header><h1>Meeting room dashboard</h1></header>
<main>
 <div class="controls">
  <div><label for="from">From</label><input type="date" id="from"></div>
  <div><label for="to">To</label><input type="date" id="to"></div>
  <div><label for="room">Room</label><select id="room"><option value="">All rooms</option></select></div>
  <button id="show">Show</button>
  <button class="alt" data-days="7">Last 7 days</button>
  <button class="alt" data-days="30">Last 30 days</button>
  <button class="alt" data-days="90">Last 90 days</button>
  <button class="alt" data-days="0">All time</button>
  <button class="alt" id="refresh">Refresh data</button>
 </div>
 <div id="err"></div>
 <div id="out"></div>
</main>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const iso = d => d.toISOString().slice(0,10);

function bars(title, items, unit, colour){
  const max = Math.max(1, ...items.map(i => i.value));
  const rows = items.map(i => `<div class="bar"><span class="lbl">${esc(i.label)}</span>
    <span class="track"><span class="fill" style="width:${(100*i.value/max).toFixed(1)}%;background:${colour}"></span></span>
    <span class="val">${i.value}${unit}</span></div>`).join('');
  return `<div class="card"><h2>${esc(title)}</h2>${rows || '<p class="muted">No data</p>'}</div>`;
}

function render(s){
  $('room').innerHTML = '<option value="">All rooms</option>' +
    s.rooms.map(r => `<option ${r===s.room_filter?'selected':''}>${esc(r)}</option>`).join('');
  if (s.total_active === 0 && s.total_cancelled === 0){
    $('out').innerHTML = `<div class="card"><h2>No bookings in this range</h2>
      <p class="muted">${esc(s.from)} to ${esc(s.to)} (${s.days} days). Pick another range or add bookings with booking.py.</p></div>`;
    return;
  }
  const t = s.table;
  const table = `<div class="card"><h2>Summary per room (${esc(s.from)} to ${esc(s.to)}, ${s.days} days)</h2>
   <table><tr><th>Room</th><th>Bookings</th><th>Hours reserved</th><th>Utilisation %</th>
   <th>Cancelled</th><th>Cancellation %</th><th>Busiest day</th></tr>
   ${t.map(r => `<tr><td>${esc(r.room)}</td><td>${r.bookings}</td><td>${r.hours.toFixed(1)}</td>
   <td>${r.utilisation.toFixed(1)}</td><td>${r.cancelled}</td><td>${r.cancel_rate.toFixed(1)}</td>
   <td>${esc(r.busiest_weekday)}</td></tr>`).join('')}</table>
   <p class="muted">Utilisation = reserved hours / (${s.days} days x ${10} bookable hours). Cancellation % = cancelled / (active + cancelled) for bookings dated in the range.</p></div>`;

  const heatMax = Math.max(1, ...Object.values(s.heatmap).flatMap(o => Object.values(o)));
  const hours = Object.keys(s.by_hour);
  const heat = `<div class="card"><h2>Busiest times: weekday x start hour (bookings)</h2>
   <table class="heat"><tr><th></th>${hours.map(h => `<th>${h}:00</th>`).join('')}</tr>
   ${Object.entries(s.heatmap).map(([w,row]) => `<tr><th>${w}</th>${hours.map(h => {
     const v = row[h]; const a = v ? (0.15 + 0.85*v/heatMax) : 0;
     return `<td style="background:rgba(43,108,176,${a.toFixed(2)});color:${a>0.55?'#fff':'#1b1f24'}">${v}</td>`;
   }).join('')}</tr>`).join('')}</table></div>`;

  $('out').innerHTML = `
   <div class="card"><h2>Overview</h2>
    <p>${s.total_active} active bookings, ${s.total_cancelled} cancelled (${s.cancel_rate.toFixed(1)}%).
    Busiest weekday: <b>${esc(s.busiest_weekday)}</b>; busiest start hour: <b>${esc(s.busiest_hour)}</b>.</p></div>
   ${table}
   ${bars('Bookings per room', t.map(r => ({label:r.room, value:r.bookings})), '', '#2b6cb0')}
   ${bars('Hours reserved per room', t.map(r => ({label:r.room, value:r.hours.toFixed(1)})), ' h', '#2f855a')}
   ${bars('Utilisation per room (% of bookable hours)', t.map(r => ({label:r.room, value:r.utilisation.toFixed(1)})), '%', '#805ad5')}
   ${bars('Bookings per weekday', Object.entries(s.by_weekday).map(([k,v]) => ({label:k, value:v})), '', '#2b6cb0')}
   ${bars('Bookings per start hour', Object.entries(s.by_hour).map(([k,v]) => ({label:k+':00', value:v})), '', '#dd6b20')}
   ${heat}
   ${bars('Cancelled bookings per room', t.map(r => ({label:r.room, value:r.cancelled})), '', '#c53030')}
   <div class="card"><h2>Busiest dates</h2>${s.top_dates.length ?
     '<ul class="notes">' + s.top_dates.map(d => `<li>${esc(d.date)}: ${d.count} bookings</li>`).join('') + '</ul>'
     : '<p class="muted">No data</p>'}</div>
   <div class="card"><h2>What this suggests</h2><ul class="notes">${s.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul></div>`;
}

async function load(){
  $('err').textContent = '';
  const f = $('from').value, to = $('to').value;
  if (!f || !to){ $('err').textContent = 'Please choose both a start and an end date.'; return; }
  if (f > to){ $('err').textContent = 'The start date must be on or before the end date.'; return; }
  const q = new URLSearchParams({from:f, to:to, room:$('room').value});
  try {
    const r = await fetch('/api/stats?' + q);
    const data = await r.json();
    if (!r.ok){ $('err').textContent = data.error || 'Could not load data.'; return; }
    render(data);
  } catch(e){ $('err').textContent = 'Could not reach the dashboard server: ' + e; }
}

function setDays(n){
  const to = new Date(); const from = new Date();
  if (n > 0) from.setDate(to.getDate() - (n - 1)); else from.setFullYear(2000, 0, 1);
  $('from').value = iso(from); $('to').value = iso(to); load();
}

document.addEventListener('DOMContentLoaded', () => {
  const to = new Date(), from = new Date(); from.setDate(to.getDate() - 29);
  $('from').value = iso(from); $('to').value = iso(to);
  $('show').onclick = load; $('room').onchange = load; $('refresh').onclick = load;
  document.querySelectorAll('button[data-days]').forEach(b => b.onclick = () => setDays(+b.dataset.days));
  load();
});
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if url.path == "/api/stats":
            q = parse_qs(url.query)
            try:
                d_from = parse_day(q.get("from", [""])[0])
                d_to = parse_day(q.get("to", [""])[0])
                if d_from > d_to:
                    raise ValueError("start date is after end date")
            except ValueError as exc:
                return self._send(400, json.dumps({"error": f"Invalid date range: {exc}"}),
                                  "application/json")
            try:
                db = booking.load_db()
            except SystemExit as exc:
                return self._send(500, json.dumps({"error": str(exc)}), "application/json")
            stats = compute_stats(db, d_from, d_to, q.get("room", [""])[0] or None)
            return self._send(200, json.dumps(stats), "application/json")
        return self._send(404, "Not found", "text/plain; charset=utf-8")

    def log_message(self, *args):
        pass


def main(argv=None):
    p = argparse.ArgumentParser(description="Manager dashboard for the meeting room booking system.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--file", help="booking data file (default: bookings.json / BOOKING_FILE)")
    p.add_argument("--text", action="store_true", help="print the numbers instead of serving a page")
    p.add_argument("--from", dest="date_from", help="YYYY-MM-DD (default: 30 days ago)")
    p.add_argument("--to", dest="date_to", help="YYYY-MM-DD (default: today)")
    p.add_argument("--room", help="limit to one room")
    args = p.parse_args(argv)

    if args.file:
        booking.DATA_FILE = os.path.abspath(args.file)

    if args.text:
        d_from, d_to = default_range()
        try:
            if args.date_from:
                d_from = parse_day(args.date_from)
            if args.date_to:
                d_to = parse_day(args.date_to)
        except ValueError:
            raise SystemExit("ERROR: dates must be YYYY-MM-DD.")
        if d_from > d_to:
            raise SystemExit("ERROR: --from must be on or before --to.")
        print_text(compute_stats(booking.load_db(), d_from, d_to, args.room))
        return

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Dashboard running at {url}  (data: {booking.DATA_FILE})")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
