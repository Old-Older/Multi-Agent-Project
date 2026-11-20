# Manager dashboard — how to use it

Open the booking system (`python3 app.py`, then http://127.0.0.1:8000/; options
`--port`, `--host`, `--data <file>` as before — the bookings live in `data.json`, and a
`data.json.lock` file next to it is normal) and click the **Dashboard** tab at the top.
The **Bookings** tab is the normal booking screen, unchanged. The dashboard is
**read-only**: to cancel a booking use the Bookings tab or `cli.py cancel`.

## Date range
Pick a **start** and **end** date (inclusive), or use a preset: Last 7 days, Last 30 days,
Last 90 days, This month, All time. Everything on the page recalculates for that range.
If only one of the two dates is given to the API, the other defaults independently
(start = 30 days before today, end = today); with no dates at all the range is the last
30 days ending today.

## What you see
- **Summary cards**: total bookings, total hours reserved, cancellation rate, busiest room,
  quietest room.
- **Plain-language summary** paragraph at the top: which rooms are heavily used, which are
  underused, and a suggestion (e.g. move some meetings from a heavily used room to an
  underused one).
- **Bookings per room** and **hours reserved per room** — horizontal bar charts.
- **Utilisation per room** — bar plus a status label and a recommendation line.
- **Busiest days** — bookings per weekday (Mon–Sun).
- **Busiest times** — bookings per hour of day (08:00–17:00), plus a weekday × hour
  **heatmap** and the **top 5 busiest weekday/hour slots**.
- **Cancellations** — count, rate, and a per-room cancellation bar chart.
- A **daily series** (bookings and hours per day) is also returned by the API for the range.

## How the numbers are defined
- **Bookings**: active bookings whose date falls in the range. Cancelled bookings are
  **recorded, not deleted**, and are **excluded** from booking counts and reserved hours,
  so usage reflects real occupancy.
- **Hours reserved**: sum of (end − start) over those active bookings.
- **Utilisation %** = reserved hours ÷ available hours, where available hours =
  weekdays in the range × 10 h (08:00–18:00). **Weekends count as 0 available hours**, so a
  range of weekends only has 0 available hours and utilisation is reported as 0.
- **Status**: **heavily used** ≥ 60 %, **underused** ≤ 20 %, otherwise **balanced**.
- **Cancellation rate** = cancelled ÷ (active + cancelled) × 100, per room and overall;
  with no bookings at all it is 0.
- **Busiest / quietest room**: ranked by number of bookings (ties broken by room order);
  with no bookings in the range both are reported as none.
- **Busiest times**: a booking counts in **every hour it overlaps** (09:00–11:00 counts in
  both 09 and 10).

## Demo data
If the range has no bookings, the dashboard shows "No bookings in this range" and a
**Load demo data** button. It inserts a realistic set of bookings over the last 90 days
(weekdays only, varied rooms and hours, roughly one in eight cancelled) **only when the
data file has no bookings at all**; on a file that already has bookings it inserts nothing
and returns `{"inserted": 0}`. Reload the dashboard afterwards (e.g. preset "Last 90 days")
to see the charts.

## API (for scripts)
- `GET /api/dashboard?start=YYYY-MM-DD&end=YYYY-MM-DD` — all dashboard figures as JSON:
  `range{start,end,days,weekdays,available_hours_per_room}`, `per_room[]`
  (id, name, capacity, bookings, hours, utilisation_pct, available_hours, cancelled,
  cancellation_rate_pct, status), `totals` (bookings, hours, cancelled,
  cancellation_rate_pct, busiest_room, quietest_room), `by_weekday[7]`, `by_hour[10]`,
  `heatmap` (7×10), `top_slots` (≤5), `daily[]`, `cancelled_by_room`, `cancellations`,
  `empty`. Bad or reversed dates return HTTP 400 with `{"error": ...}`.
- `GET /api/cancellations?start=YYYY-MM-DD&end=YYYY-MM-DD` — the cancelled records in that
  range (same record fields as a booking, plus `cancelled` and `cancelled_at`).
- `POST /api/demo-data` — insert demo bookings into a data file with no bookings; returns
  `{"inserted": n}`.

## Tests and limitations
- `python3 selftest.py` — 53 checks of the original booking behaviour, all passing.
- `python3 dashboard_selftest.py` — the dashboard checks, all passing (the exact count is
  printed by the script; it was not re-counted for this document).
- `dashboard_qa.py` — an independent QA script; it was run against this app.py with 67 of
  68 checks passing. The one failure is cosmetic: a request with a present-but-empty
  `start`/`end` parameter returns the default range instead of HTTP 400 (the web page never
  sends empty dates).
- **Unverified:** the dashboard has not been clicked through in a real browser; the chart
  checks are based on the API and the served page markup only.
