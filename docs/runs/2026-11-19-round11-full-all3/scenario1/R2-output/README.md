# Meeting Room Booking

A small, self-contained web app that replaces the shared spreadsheet for booking
meeting rooms. It prevents double bookings (checked on the server), keeps
records correct when bookings are cancelled, and gives the room manager a
dashboard of how the rooms are actually used.

**No installation, no database server, no pip packages** — it uses only the
Python 3 standard library (`http.server` + `sqlite3`).

## Files

| File | Purpose |
|------|---------|
| `app.py` | The whole application: web server, API, HTML/CSS/JS UI, SQLite storage |
| `test_app.py` | Automated tests (double booking rejected, cancellation frees the slot, dashboard figures, etc.) |
| `README.md` | This file |
| `QUICKSTART.md` | One-page plain-language guide for the team |
| `CHANGELOG.md` | What changed in each version |
| `bookings.db` | Created automatically on first run — all bookings live here |

## Run it

```bash
python3 app.py
```

Then open **http://localhost:8000** in a browser.

Options (environment variables):

```bash
PORT=9000 python3 app.py                 # use a different port
ADMIN_KEY=my-secret python3 app.py       # change the admin key (default: admin)
DB_PATH=/data/bookings.db python3 app.py # store the database elsewhere
```

To share it with the team, run it on one always-on machine/server and give
everyone the URL (e.g. `http://meeting-rooms.internal:8000`). The server listens
on all interfaces (`HOST=0.0.0.0` by default). There is no login: people are
identified by the name and email they type in.

## How to use it

The page has five sections, top to bottom.

### 1. Check availability
Pick a date and press **Show availability** (or use **Prev/Next day**).
You get one card per room showing every 30-minute slot from 08:00 to 18:00:

* **green** = free, **red** = booked (hover to see who booked it), **grey** = closed
* Weekends show "closed" — rooms can only be booked Monday–Friday.

### 2. Book a room
Either click a **green slot** (this fills in room, date and times for you), or
choose room / date / start / end manually. Then enter:

* **Your name**
* **Your email** — this is your identity; it is what lets you cancel later
* **Purpose** (optional, e.g. "Sprint planning") — at most 200 characters; a
  longer purpose is rejected with a clear message (nothing is truncated silently)

Press **Book room**. If someone already has that room at an overlapping time,
the server rejects the booking and tells you who has it — the slot is never
double-booked, even if two people click at the same moment.

### 3. My bookings
Type your email and press **Show my bookings** to see everything you have
booked, with a **Cancel** button on each row. Your email is remembered in the
browser, so next time it is pre-filled.

**Export all to CSV** downloads the bookings for the date currently shown in
section 1 (or all bookings if no date is set) as `bookings.csv`, which opens in
Excel / Google Sheets.

### 4. Admin
Enter the admin key (default `admin`, or whatever `ADMIN_KEY` was set to) and
press **Show all bookings** to see every booking; the **Cancel** button then
works on anyone's booking. This is the override for when someone leaves the
team or forgets to cancel.

The admin key is required for the full list: without it the server answers
HTTP 403 and the page shows an error message, so the team calendar is not
readable by anyone who merely knows the URL.

### 5. Dashboard (manager)
The dashboard answers "how are our rooms actually used, and should we change
the allocation?". It is **admin-key only** — the same key as the Admin section
(default `admin`, or whatever `ADMIN_KEY` was set to). Without a valid key the
server answers HTTP 403 and the page shows the error message.

**Opening it.** In the **Dashboard (manager)** section type the admin key, pick
a **From** and **To** date, optionally choose a **Room** (default *All rooms*)
and press **Refresh**. The range defaults to the **last 30 days**; the preset
buttons **Last 7 days**, **Last 30 days**, **Last 90 days** and **This month**
fill the dates in and reload. A range may span at most 366 days.

**What it shows** (all figures come from the booking records for the selected
dates only):

* **Summary and recommendation** at the top, in plain English — e.g. which room
  is busiest and which is quietest, total bookings and hours, cancellations and
  the cancellation rate, plus a recommendation naming heavily used and
  underused rooms.
* **KPI cards**: bookings, hours reserved, cancelled, cancellation rate.
* **Utilisation per room** — a bar per room (red = heavily used, amber =
  underused, blue = normal).
* **Busiest days of the week** — bookings per Mon–Sun.
* **Busiest times of day** — bookings per hour band 08–09, 09–10, … 17–18 (a
  09:00–11:00 booking counts in both 09–10 and 10–11).
* **Top 5 busiest dates** — the individual dates with the most bookings.
* **Cancellations per week** — cancelled bookings grouped by week.
* **Per-room detail table** — room, capacity, bookings, hours reserved,
  utilisation %, cancelled, and a flag (heavily used / underused / normal).

All charts are inline SVG drawn by the page itself — no CDN, no JavaScript
libraries, nothing to download.

**How the figures are computed**

* Only bookings whose date falls inside the selected range are used.
* **Cancelled bookings are counted in the cancellation figures but NOT in hours
  reserved or utilisation** (the section says so on screen).
* Hours reserved = sum of (end − start) over the active bookings of that room.
* **Utilisation % = hours reserved ÷ (weekdays in the range × 10 open hours) ×
  100**, rounded to one decimal. The denominator (available hours per room) is
  printed above the charts.
* **Heavily used = over 70 %**, **underused = under 25 %**, anything in between
  is normal. Both thresholds are printed in the section.
* Cancellation rate = cancelled ÷ (cancelled + active bookings) × 100.

**Deciding about room allocation.** Look at the utilisation bars and the
per-room table: red rooms (over 70 %) are the ones to relieve — move some
bookings to a quieter room or add capacity; amber rooms (under 25 %) are the
ones to fill or reallocate. The busiest-days and busiest-times charts show when
the pressure happens, and the cancellations chart shows whether rooms are being
held and released.

## Rules built in

* 5 rooms: **Aspen** (4), **Birch** (6), **Cedar** (8), **Dogwood** (10), **Elm** (20)
* 30-minute slots, 08:00–18:00, Monday–Friday only; past dates are rejected
* Anyone can book any room; no approval step
* Only the booker (matching email) or an admin can cancel
* **Cancelling does not delete the booking.** The record is kept and marked
  cancelled (with who cancelled it and when), so the dashboard can report
  cancellations; the slot becomes free immediately and can be booked again.
  Cancelling an already-cancelled booking returns HTTP 409.
* Overlap check is server-side and transactional, so concurrent requests cannot
  create a double booking (verified: 12 simultaneous identical requests → exactly
  one booking created, the rest rejected with HTTP 409)

## Run the tests

```bash
python3 test_app.py
```

The tests start the real server on a free port with a temporary database and
check, among other things:

* `test_double_booking_rejected` — the same slot, a partial overlap and an
  enclosing booking are all rejected with HTTP 409; adjacent slots and other
  rooms still work
* `test_cancellation_frees_slot` — after cancelling, the slot shows as free and
  someone else can book it
* `test_only_booker_or_admin_can_cancel` — a different email gets 403, the admin
  key succeeds; a wrong admin key gets a 403 that says the admin key is wrong
* `test_email_and_date_filter_combined` — `?email=` together with `?date=`
  applies both filters (only that person's bookings on that day)
* `test_all_bookings_requires_admin_key` — the unfiltered list returns 403
  without the admin key and 200 with it
* `test_long_title_rejected` — a purpose longer than 200 characters is rejected
  with 400 and a clear message; exactly 200 characters is stored untruncated
* `test_concurrent_identical_bookings_only_one_wins` — 12 simultaneous identical
  POSTs produce exactly one 201 and eleven 409s
* availability, "my bookings", CSV export, validation (weekend, past date,
  out-of-hours, off-grid, bad email), malformed JSON, and the HTML page

The 7 dashboard tests in `DashboardTests`:

* `test_dashboard_requires_admin_key` — `GET /api/dashboard` without a valid
  admin key returns 403
* `test_dashboard_per_room_figures` — per-room bookings, hours and utilisation
  for a seeded date range
* `test_dashboard_cancelled_excluded_from_hours` — cancelled bookings are
  counted in the cancellation figures but not in hours reserved or utilisation
* `test_dashboard_weekday_hour_top_date_aggregation` — bookings per weekday,
  per hour band and the top dates
* `test_dashboard_range_validation` — 400 for missing/bad dates, `from` after
  `to`, and a span longer than 366 days
* `test_cancel_soft_deletes_and_frees_slot` — cancelling keeps the record and
  marks it cancelled, the slot is free immediately and can be re-booked, and a
  second cancel returns 409
* `test_migration_adds_cancellation_columns` — an old database without
  `cancelled_at` / `cancelled_by` is upgraded on start-up

Expected output ends with `Ran 23 tests ... OK`.

## HTTP API (optional, for scripting)

| Method & path | What it does |
|---|---|
| `GET /api/rooms` | Room list with capacities and slot times |
| `GET /api/availability?date=YYYY-MM-DD` | Every room's slots for that day |
| `GET /api/bookings?email=...` | That person's bookings ("my bookings"); add `&date=` to filter — both filters are applied together |
| `GET /api/bookings?admin_key=...` | All bookings (admin only); add `&date=` to filter. Without a valid `admin_key` → **403** |
| `POST /api/bookings` | Create: `{"room","date","start","end","booker","email","title"}` → 201, or 409 on conflict, 400 on invalid input (including a `title` longer than 200 characters) |
| `DELETE /api/bookings/<id>` | Cancel: `{"email": "..."}` or `{"admin_key": "..."}` → 200, 403 if not the booker and the admin key is missing/wrong, 404 if unknown, 409 if already cancelled. The record is kept and marked cancelled; the slot is free immediately |
| `GET /api/bookings.csv?date=...` | CSV export |
| `GET /api/dashboard?from=YYYY-MM-DD&to=YYYY-MM-DD&admin_key=...&room=...` | Manager dashboard figures for a date range (admin only) — see below |

### `GET /api/dashboard`

Parameters:

* `admin_key` — **required**; must equal `ADMIN_KEY` (default `admin`), otherwise
  **403**.
* `from`, `to` — **required**, `YYYY-MM-DD`, `from` on or before `to`, at most
  **366 days** inclusive. Missing/bad dates, `from` after `to`, or a longer span
  → **400** with a clear message.
* `room` — optional; one of Aspen, Birch, Cedar, Dogwood, Elm (case-insensitive).
  Filters every figure to that room. An unknown room → **400**.

Response (abridged):

```json
{
  "range": {"from": "2025-06-01", "to": "2025-06-30", "days": 30, "weekdays": 21,
            "available_hours_per_room": 210.0},
  "room_filter": null,
  "rooms": [{"room": "Elm", "capacity": 20, "bookings": 12, "hours": 18.5,
             "cancelled": 2, "utilisation_pct": 8.8, "flag": "underused"}],
  "by_weekday": [{"weekday": "Mon", "bookings": 9}],
  "by_hour": [{"hour": "08-09", "bookings": 1}],
  "top_dates": [{"date": "2025-06-03", "bookings": 4}],
  "totals": {"bookings": 40, "hours": 61.0, "cancelled": 5,
             "cancellation_rate_pct": 11.1},
  "cancelled_trend": [{"week_start": "2025-06-02", "cancelled": 2}],
  "thresholds": {"heavy_pct": 70.0, "under_pct": 25.0},
  "summary": "...", "recommendation": "..."
}
```

`by_weekday` always has 7 entries (Mon–Sun), `by_hour` 10 entries (08–09 …
17–18), `top_dates` up to 5. `flag` is `heavy` (utilisation over 70 %),
`underused` (under 25 %) or `normal`. Cancelled bookings are counted in
`cancelled` / `cancellation_rate_pct` / `cancelled_trend` but not in `bookings`,
`hours` or `utilisation_pct`.

Example:

```bash
curl -X POST http://localhost:8000/api/bookings \
  -H 'Content-Type: application/json' \
  -d '{"room":"Cedar","date":"2025-06-02","start":"10:00","end":"11:00",
       "booker":"Ada","email":"ada@example.com","title":"Design review"}'

curl 'http://localhost:8000/api/dashboard?from=2025-06-01&to=2025-06-30&admin_key=admin'
```

## Notes / limitations

* No login and no email reminders (as agreed). Identity is the typed email, so
  anyone who knows a booker's email could cancel their booking — acceptable for
  a trusted internal team; the admin key is the override.
* **The full booking list and the dashboard are admin-only.** `GET /api/bookings`
  without an `email` filter requires `?admin_key=...` and returns HTTP 403
  otherwise; `GET /api/dashboard` always requires it. The UI's **Show all
  bookings** button sends the key from the Admin box and the dashboard sends the
  key from its own box. People can still see their own bookings (`?email=`) and
  the per-day availability grid (which shows who booked each slot), so the team
  calendar stays visible.
* A purpose/title longer than 200 characters is rejected with HTTP 400 and a
  clear message — it is never silently truncated.
* The page's loaders (availability, my bookings, all bookings, dashboard) show a
  visible error message if the server cannot be reached or returns an error,
  instead of leaving a blank panel.
* There is no CSRF protection, so keep the app on the internal network rather
  than exposing it to the public internet.
* No recurring bookings yet.
* Back up `bookings.db` (a single file) to back up all bookings. An existing
  database from an older version is upgraded automatically on start-up (the
  cancellation columns are added; old bookings stay active).
