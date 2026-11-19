# Changelog

All notable changes to the Meeting Room Booking app are recorded here.

**Version convention:** versions are `vMAJOR.MINOR`; the date next to a version
is its release date (`TBD` = not released yet). Newest version first. To update
to a later version, replace `app.py` (and `test_app.py`) and start the app — an
existing `bookings.db` is upgraded automatically on start-up; back it up first.

## v1.1 — (release date: TBD)

Manager dashboard, and cancellations kept as records instead of being deleted.
Still Python 3 standard library only: no pip packages, no CDN, no JavaScript
libraries.

### Added — manager dashboard (REQ1–REQ9)

* New **Dashboard (manager)** section on the same page, for the person managing
  the rooms. **Admin-key only** — the same key as the Admin section (default
  `admin`, or whatever `ADMIN_KEY` is set to); without a valid key the server
  answers HTTP 403 and the page shows the error message.
* **Date range** with **From** / **To** pickers, a **Room** filter (default
  *All rooms*) and **Refresh**; presets **Last 7 days**, **Last 30 days**,
  **Last 90 days** and **This month**. The default range is the **last 30
  days**; a range may span at most 366 days.
* **Per-room figures**: bookings, hours reserved, cancelled, utilisation % and a
  flag (heavily used / underused / normal), plus a per-room detail table with
  capacity.
* **Busiest days and times**: bookings per weekday (Mon–Sun), bookings per hour
  band 08–09, 09–10, … 17–18 (a 09:00–11:00 booking counts in both 09–10 and
  10–11), and the **top 5 busiest individual dates**.
* **Cancellations**: cancellation count, cancellation rate and a
  cancellations-per-week chart.
* **Clear charts and summaries**: KPI cards (bookings, hours, cancelled,
  cancellation rate), utilisation bars per room (red = heavily used, amber =
  underused, blue = normal), inline **SVG** bar charts drawn by the page itself,
  and a plain-English **summary + recommendation** naming heavily used and
  underused rooms so the manager can decide whether to change room allocation.
* **Thresholds 70 % / 25 %**: heavily used = utilisation over **70 %**,
  underused = under **25 %**, anything in between is normal. Both thresholds are
  printed in the section.
* **Utilisation = hours reserved ÷ (weekdays in the range × 10 open hours) ×
  100**, rounded to one decimal; the denominator (available hours per room) is
  printed above the charts.
* All figures come from the system's own booking records, restricted to the
  selected date range.

### Added — `GET /api/dashboard`

```
GET /api/dashboard?from=YYYY-MM-DD&to=YYYY-MM-DD&admin_key=...&room=Elm
```

* `admin_key` required and must equal `ADMIN_KEY` (default `admin`) → otherwise
  **403**.
* `from` / `to` required, `YYYY-MM-DD`, `from` on or before `to`, at most 366
  days inclusive; missing or bad dates, `from` after `to`, or a longer span →
  **400** with a clear message. An unknown `room` → **400**.
* `room` optional (case-insensitive) and filters every figure to one room.
* Response: `range` (days, weekdays, available hours per room), `room_filter`,
  `rooms[]` (capacity, bookings, hours, cancelled, utilisation %, flag),
  `by_weekday` (7 entries), `by_hour` (10 entries), `top_dates` (up to 5),
  `totals` (bookings, hours, cancelled, cancellation rate), `cancelled_trend`,
  `thresholds` and the generated `summary` / `recommendation`.

### Changed — cancellations are soft deletes

* Cancelling no longer deletes the booking. The record is kept and marked
  cancelled with `cancelled_at` (when) and `cancelled_by` (who: `admin` or the
  booker's email), so cancellations can be counted and reported.
* The **slot is free immediately** and can be booked again, exactly as before;
  availability, conflict checks and booking lists ignore cancelled records.
* Cancelling an already-cancelled booking returns **409**.
* Cancelled bookings are counted in the cancellation figures but **not** in
  hours reserved or utilisation (the dashboard says so on screen).
* **Automatic migration**: on start-up an existing `bookings.db` from an older
  version is upgraded in place — the `cancelled_at` and `cancelled_by` columns
  are added only if missing (idempotent, safe to run repeatedly); old bookings
  stay active. Back up `bookings.db` before upgrading.

### Tests

* **23 tests** (`python3 test_app.py` → `Ran 23 tests ... OK`): the 16 original
  tests plus 7 new ones in `DashboardTests` — dashboard requires the admin key
  (403), per-room counts/hours/utilisation for a seeded range, cancelled
  bookings excluded from hours but counted in the cancellation rate,
  weekday/hour/top-date aggregation, range validation (400), cancel
  soft-deletes and still frees the slot (re-booking works, double cancel 409),
  and the migration on an old database without the new columns.

## v1.0 — (release date: TBD)

First release: a small, self-contained web app that replaces the shared
spreadsheet for booking meeting rooms. Python 3 standard library only
(`http.server` + `sqlite3`); no installation, no database server, no pip
packages.

* **Availability**: one card per room showing every 30-minute slot from 08:00
  to 18:00 (green = free, red = booked, grey = closed); rooms can only be booked
  Monday–Friday and past dates are rejected.
* **Booking**: click a free slot or choose room / date / start / end, then enter
  name, email (the identity used to cancel later) and an optional purpose of at
  most 200 characters (longer is rejected with HTTP 400, never truncated).
* **No double bookings**: the overlap check is server-side and transactional, so
  concurrent requests cannot create a double booking (verified: 12 simultaneous
  identical requests → exactly one booking, the rest rejected with HTTP 409).
* **My bookings**: look up your bookings by email and cancel them; your email is
  remembered in the browser.
* **CSV export**: download the bookings for the date currently shown (or all
  bookings if no date is set) as `bookings.csv`.
* **Admin**: with the admin key (default `admin`, or `ADMIN_KEY`) see every
  booking and cancel anyone's; the unfiltered list returns HTTP 403 without it.
* **Rules**: 5 rooms — Aspen (4), Birch (6), Cedar (8), Dogwood (10), Elm (20);
  anyone can book any room, no approval step; only the booker (matching email)
  or an admin can cancel.
* **HTTP API**: `GET /api/rooms`, `GET /api/availability`, `GET /api/bookings`
  (by email, or all with `admin_key`), `POST /api/bookings`,
  `DELETE /api/bookings/<id>`, `GET /api/bookings.csv`.
* **Configuration**: `PORT`, `ADMIN_KEY` and `DB_PATH` environment variables;
  the server listens on all interfaces by default.
* **Tests**: 16 automated tests (`python3 test_app.py` → `Ran 16 tests ... OK`).
* **Known limitations**: no login and no email reminders (identity is the typed
  email), no CSRF protection (keep it on the internal network), no recurring
  bookings.
