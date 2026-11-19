# Meeting Room Booking

A small, self-contained web app that replaces the shared spreadsheet for booking
meeting rooms. It prevents double bookings (checked on the server) and keeps
records correct when bookings are cancelled.

**No installation, no database server, no pip packages** — it uses only the
Python 3 standard library (`http.server` + `sqlite3`).

## Files

| File | Purpose |
|------|---------|
| `app.py` | The whole application: web server, API, HTML/CSS/JS UI, SQLite storage |
| `test_app.py` | Automated tests (double booking rejected, cancellation frees the slot, etc.) |
| `README.md` | This file |
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

The page has four sections, top to bottom.

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

## Rules built in

* 5 rooms: **Aspen** (4), **Birch** (6), **Cedar** (8), **Dogwood** (10), **Elm** (20)
* 30-minute slots, 08:00–18:00, Monday–Friday only; past dates are rejected
* Anyone can book any room; no approval step
* Only the booker (matching email) or an admin can cancel
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

Expected output ends with `Ran 16 tests ... OK`.

## HTTP API (optional, for scripting)

| Method & path | What it does |
|---|---|
| `GET /api/rooms` | Room list with capacities and slot times |
| `GET /api/availability?date=YYYY-MM-DD` | Every room's slots for that day |
| `GET /api/bookings?email=...` | That person's bookings ("my bookings"); add `&date=` to filter — both filters are applied together |
| `GET /api/bookings?admin_key=...` | All bookings (admin only); add `&date=` to filter. Without a valid `admin_key` → **403** |
| `POST /api/bookings` | Create: `{"room","date","start","end","booker","email","title"}` → 201, or 409 on conflict, 400 on invalid input (including a `title` longer than 200 characters) |
| `DELETE /api/bookings/<id>` | Cancel: `{"email": "..."}` or `{"admin_key": "..."}` → 200, 403 if not the booker and the admin key is missing/wrong, 404 if unknown |
| `GET /api/bookings.csv?date=...` | CSV export |

Example:

```bash
curl -X POST http://localhost:8000/api/bookings \
  -H 'Content-Type: application/json' \
  -d '{"room":"Cedar","date":"2025-06-02","start":"10:00","end":"11:00",
       "booker":"Ada","email":"ada@example.com","title":"Design review"}'
```

## Notes / limitations

* No login and no email reminders (as agreed). Identity is the typed email, so
  anyone who knows a booker's email could cancel their booking — acceptable for
  a trusted internal team; the admin key is the override.
* **The full booking list is admin-only.** `GET /api/bookings` without an
  `email` filter requires `?admin_key=...` and returns HTTP 403 otherwise; the
  UI's **Show all bookings** button sends the key from the Admin box. People
  can still see their own bookings (`?email=`) and the per-day availability
  grid (which shows who booked each slot), so the team calendar stays visible.
* A purpose/title longer than 200 characters is rejected with HTTP 400 and a
  clear message — it is never silently truncated.
* The page's loaders (availability, my bookings, all bookings) show a visible
  error message if the server cannot be reached or returns an error, instead of
  leaving a blank panel.
* There is no CSRF protection, so keep the app on the internal network rather
  than exposing it to the public internet.
* No recurring bookings yet.
* Back up `bookings.db` (a single file) to back up all bookings.
