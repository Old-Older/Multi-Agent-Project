# Changelog

All notable changes to the meeting room booking system. Versions are numbered
`vMAJOR.MINOR`; the date is the release date.

## v1.0 — first release (release date: 2025-06-02)

First release of the meeting room booking system, replacing the shared
spreadsheet. Its two headline fixes: **no double bookings** (the overlap check
runs on the server, so two people cannot get the same room at the same time) and
**cancellations free the slot immediately** (the record is deleted, so the slot
shows free and can be re-booked at once).

### Features

- **Availability** — pick a date (or use Prev/Next day) and see one card per room
  with every 30-minute slot from 08:00 to 18:00: green = free, red = booked
  (hover shows who), grey = closed. Weekends are closed.
- **Booking** — click a free slot to prefill the form, or choose room, date,
  start and end manually; enter name, email and an optional purpose (at most 200
  characters — a longer one is rejected with HTTP 400, never truncated). An
  overlapping request is rejected with HTTP 409 and names who already has the
  room. Evidence: 12 simultaneous identical requests produce exactly one 201 and
  eleven 409s.
- **Cancellation** — cancel from "My bookings"; the slot is free immediately and
  re-bookable by someone else. Only the booker (matching email, case-insensitive)
  or an admin can cancel; anyone else gets HTTP 403.
- **My bookings** — look up your own bookings by email; the email is remembered
  in the browser. The email is the identity — there is no name-based lookup.
- **CSV export** — downloads `bookings.csv` for the date currently shown in the
  availability section, or all bookings if no date is set.
- **Admin override** — with the admin key (default `admin`, or `ADMIN_KEY`) you
  can see all bookings and cancel anyone's. The unfiltered booking list requires
  the admin key and returns HTTP 403 without it.
- **Visible errors** — the availability, my-bookings and all-bookings loaders
  show an error message instead of a blank panel when the server fails.
- **HTTP API** — `/api/rooms`, `/api/availability`, `/api/bookings` (GET, POST,
  DELETE), `/api/bookings.csv`; see `README.md` for the full table.

### Rules built in

- 5 rooms: Aspen (4), Birch (6), Cedar (8), Dogwood (10), Elm (20).
- 30-minute slots, 08:00–18:00, Monday–Friday only; past dates are rejected.
- Anyone can book any room; no approval step.
- Only the booker or an admin can cancel.

### Running and configuration

- `python3 app.py`, then open http://localhost:8000.
- Environment variables: `PORT` (default 8000), `ADMIN_KEY` (default `admin`),
  `DB_PATH` (default `bookings.db`, created automatically), `HOST`
  (default `0.0.0.0`).

### Tests

- 16 automated tests: `python3 test_app.py` → expected output ends with
  `Ran 16 tests ... OK`. The suite starts the real server on a free port with a
  temporary database and covers availability, double-booking rejection
  (including concurrency), cancellation freeing the slot, booker/admin-only
  cancel, the email+date filter, admin-key-only full list, the 200-character
  purpose limit, CSV export, validation and the HTML page.

### Files

- `app.py` — the application (server, API, UI, SQLite storage).
- `test_app.py` — the automated tests.
- `README.md` — full reference (run options, walkthrough, rules, HTTP API).
- `QUICKSTART.md` — one-page plain-language guide for the team.
- `bookings.db` — created on first run; holds all bookings.

### Known limitations

- No login and no CSRF protection: identity is the typed email, so anyone who
  knows a booker's email could cancel their booking. Keep the app on the
  internal network.
- No recurring bookings and no email reminders.
- Back up `bookings.db` (a single file) to back up all bookings.

### Updating to a later version

Stop the app, replace `app.py` (and `test_app.py`) with the new version, keep
`bookings.db` in place, run `python3 test_app.py`, then start the app again.
