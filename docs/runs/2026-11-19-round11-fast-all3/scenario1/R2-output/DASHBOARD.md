# Manager dashboard

A read-only analytics page for the person who manages the meeting rooms.
It is built from the same booking records the booking app already uses
(`bookings.json`) — no new data, no new dependencies, no external JS or CDN,
so it works fully offline.

## Open it

```bash
python3 app.py            # then open http://localhost:8000/dashboard
python3 app.py --demo     # optional: fill the data file with demo bookings first
```

`--demo` writes realistic demo bookings over the last 90 days (varied rooms,
weekdays and hours, ~15% cancelled) and exits — it never runs on the normal
start path. Delete `bookings.json` to start from an empty file again.

## What the page shows

* **Date range** — two date inputs + *Apply*, plus quick buttons for
  **7 / 30 / 90 days**. Default is the last 30 days ending today.
  `GET /dashboard?start=YYYY-MM-DD&end=YYYY-MM-DD` or `?days=7|30|90`.
* **KPI cards** — total bookings, hours reserved, cancellation rate,
  busiest day, busiest time, most/least used room, unique bookers.
* **Bookings per room** and **hours reserved per room** — horizontal bars
  (pure HTML/CSS divs, widths in %).
* **Bookings by weekday** (Mon–Sun) and **by hour of day** (08:00–17:00) —
  vertical bar charts. A booking spanning 09:00–10:30 counts once in the
  09:00 hour and once in the 10:00 hour.
* **Room × hour heatmap** — darker blue = more bookings in that room and hour.
* **Room summary table** — bookings, hours, utilisation %, cancelled,
  cancel rate, busiest day/time and a status label
  (**Heavily used** ≥ 75 %, **Balanced**, **Underused** ≤ 25 %).
* **What to consider** — automatic plain-English recommendations, e.g.
  *"Cedar is 92% booked on Tuesdays – consider moving small meetings to Aspen
  (4 seats, 21% used)."*, *"Dune is used only 8% of available hours – consider
  reallocating it or offering it to another team."*, *"Cancellation rate is
  18% (9 of 50) – mostly Aspen; check whether recurring bookings are still
  needed."*
* **Weekly trend** — bookings per ISO week overlapping the range.
* **Busiest days** — the top 5 dates in the range.

## How the numbers are defined

* A booking belongs to the range if its `date` is between start and end
  (inclusive).
* **Cancelled bookings are excluded from usage** (bookings and hours) but
  **counted in the cancellation rate** = cancelled / all bookings created in
  the range. The page states this in a note.
* **Utilisation** = hours reserved / (weekdays in range × 10 available hours,
  08:00–18:00 Mon–Fri).
* Recommendations only flag heavily used / underused rooms when the range has
  at least 5 weekdays; the cancellation rate is mentioned when it is above
  10 %; an empty range says so.

## JSON API

`GET /api/dashboard?start=&end=` (or `?days=`) returns the same dict the page
is rendered from: `range`, `totals`, `per_room`, `by_weekday`, `by_hour`,
`by_room_hour`, `by_week`, `top_days`, `busiest_day`, `busiest_hour`,
`busiest_room`, `quietest_room`, `recommendations`.

## Tests

```bash
python3 test_app.py
```

12 tests: the original 5 booking tests plus dashboard tests for counts, hours,
cancel rate, weekday/hour bucketing, utilisation, recommendations for a
heavily used and an underused room, empty range, invalid range, and an HTTP
test that `/dashboard` and `/api/dashboard` return 200.
