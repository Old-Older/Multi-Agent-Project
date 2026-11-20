# Manager dashboard — notes

The dashboard is a **tab inside the existing app** (`python3 app.py`, then click
**Dashboard** in the header). No new dependencies: still one file, standard library only,
no CDN or network access — the charts are plain HTML/CSS bars.

## Endpoint

`GET /api/dashboard?start=YYYY-MM-DD&end=YYYY-MM-DD`

Both parameters are required. The range is inclusive. Validation errors return
`400 {"error": "..."}`:

| case | message |
|---|---|
| `start` missing | `start is required (YYYY-MM-DD)` |
| `end` missing | `end is required (YYYY-MM-DD)` |
| bad format / impossible date | `date must be in YYYY-MM-DD format` / `date is not a valid calendar date` |
| `start > end` | `start must be on or before end` |
| more than 366 days | `date range is too long (max 366 days)` |

Response (every key is always present):

```json
{"start","end","days",
 "rooms":[{"room_id","room","capacity","bookings","cancelled","cancel_rate",
           "hours","utilisation","share","status"}],
 "totals":{"bookings","cancelled","cancel_rate","hours","capacity_hours","utilisation"},
 "by_weekday":[{"weekday":0..6,"label":"Mon","bookings","hours"}],
 "by_hour":[{"hour":8..17,"label":"08:00","bookings","hours"}],
 "by_date":[{"date","bookings","hours"}],
 "busiest":{"weekday","hour","date"},
 "suggestions":[{"room","kind","text"}]}
```

## Metric definitions

* **bookings** — active bookings (`status='active'`) whose booking date is in range.
* **cancelled** — cancelled bookings whose booking date is in range. Cancellations are
  counted by the date the booking was **for**, not when it was cancelled (there is no
  `cancelled_at` column and none was added).
* **cancel_rate** — `cancelled / (bookings + cancelled)`, `0.0` when there are none.
* **hours** — sum of `end - start` in hours over active bookings.
* **capacity_hours** — `days_in_range * 10` (08:00–18:00) per room; the `totals` figure is
  that times the number of rooms.
* **utilisation** — `hours / capacity_hours` (0.0 when capacity is 0).
* **share** — room hours / total hours across all rooms (0.0 when there are no hours).
* **status** — `underused` if utilisation < 0.10, `heavily used` if >= 0.50, else `moderate`.
* **by_weekday** — active bookings grouped by the weekday of the booking date (0 = Monday).
* **by_hour** — a booking counts in **every hour it overlaps**: 09:30–11:00 adds to 09 and 10.
  `hours` is the overlap with that hour.
* **by_date** — active bookings grouped by booking date; every date in the range is listed.
* **busiest** — weekday / hour / date with the most active bookings; ties go to the earliest.
  All three are `null` when the range has no active bookings.
* **suggestions** — `underused` rooms → "consider reallocating or sharing";
  `heavily used` rooms → "consider adding capacity"; rooms with `cancel_rate >= 0.25` and at
  least 4 bookings → "high cancellation rate". An empty range returns no suggestions.

An empty range returns all zeros, empty suggestions and never crashes.

## UI

* Header tab bar: **Book a room** (the original view, unchanged ids and behaviour) and
  **Dashboard**.
* Date-range controls: start, end, presets **Last 7 / 30 / 90 days** and **This month**, plus
  **Apply**. Default is the last 30 days.
* KPI cards: total bookings, total hours reserved, utilisation %, cancellation rate.
* Horizontal bar charts: bookings per room, hours per room (coloured by status), bookings by
  weekday, bookings by hour of day.
* Per-room table: bookings, cancelled, cancel rate, hours, utilisation %, share, status badge.
* "Busiest days and times" summary line and an allocation-suggestions list.
* Status colours: underused = amber, moderate = grey, heavily used = red.
* A clear empty state when the range has no bookings. All text is escaped with `esc()`.

## Seeding demo data

```bash
python3 app.py --seed-demo          # ~60 days of demo bookings into the configured DB
python3 app.py --seed-demo --days 90
```

`seed_demo_data(conn, days=60)` inserts a deterministic mix (fixed pseudo-random sequence, so
repeated runs on a fresh DB give the same data) of active and cancelled bookings over the past
N days, with a weekday/hour skew and uneven room popularity so underused and heavily used rooms
both appear. Slots already taken are skipped. It only runs with `--seed-demo`; a normal
`python3 app.py` start never seeds.
