# Meeting Room Booking

A small, self-contained web app for booking meeting rooms. It replaces the shared
spreadsheet and fixes its two problems:

* **No double bookings** — an overlapping booking in the same room is rejected
  (HTTP 409) with a message naming the clashing booking. The overlap check and the
  insert run under one database write lock (`BEGIN IMMEDIATE`), so two simultaneous
  requests cannot both succeed.
* **No stale records** — cancelling a booking marks it cancelled (`cancelled_at`)
  and the slot is free again immediately. History is kept, but nothing shows a
  cancelled booking as active.

Python 3 standard library only — no `pip install`, no build step.
A short user guide is in `HOW-TO-USE.md`.

## Start

```bash
python3 app.py            # serves http://localhost:8000
python3 app.py 9000       # optional: use another port
```

Open <http://localhost:8000> in a browser. Stop with `Ctrl+C`.
To let colleagues on the same network use it, they open `http://<your-machine-ip>:8000`.

**No logins:** the server listens on all interfaces and has no authentication — anyone
who can reach the port can book and cancel any booking. Use it on a trusted network only.

## Using the screens

The page has three sections, all for one chosen date (defaults to today):

1. **Availability** — pick a date (or press *Today*). Each room is shown as a card
   with its capacity, the bookings already on that date (time, title, booker) and
   the **free gaps** between them. The *Download CSV* link at the top of this section
   exports all active bookings for all dates, not just the chosen day.
2. **Book a room** — choose room, date (it starts as the availability date; change it
   here to book another day — the two can differ), start and end (15-minute steps,
   08:00–19:00 inclusive), your name, a title, optional notes, and optionally *Repeat weekly*
   (up to 52 extra weeks). Press **Book room**. A green banner at the top of the page confirms
   the booking; a red banner there explains any problem, e.g.
   `Room Birch is already booked 10:00-11:00 on 2026-01-05 (Standup)`.
   Recurring bookings are all-or-nothing: if any week clashes, nothing is created and
   the conflicting date is named.
3. **Bookings on <date>** — every active booking for the date with a **Cancel**
   button. A confirmation dialog names the room, date, time, title and booker; then you
   are asked for your name (optional, recorded as `cancelled_by` — dismissing that
   prompt aborts the cancellation). The booking disappears from the list and the slot
   shows as free again. Cancelling an already-cancelled booking or an unknown id is refused
   with a message.

The header of the main page also links to the manager dashboard (`Manager dashboard →`).

## Manager dashboard

`/dashboard` is a read-only analytics page for whoever manages the rooms. It is built
from the same `bookings` table (active and cancelled rows) and needs no login. The
dashboard links back to the booking page.

Pick a range with the preset buttons — *Last 7 days*, *Last 30 days*, *Last 90 days*,
*This month* — or type *From* / *To* dates and press **Apply**. With no parameters the
range is the **last 30 days ending today**; the maximum is 366 days.

* **Summary cards** — active bookings, hours reserved (sum of end − start of active
  bookings), rooms used / total, and cancellations with the cancellation rate.
* **Per-room usage** — a table plus a horizontal bar chart: bookings, hours reserved,
  cancelled, cancel rate, and utilisation = hours reserved ÷ (11 working hours × days in
  range). Each room is labelled **heavy** (≥ 60 % used), **normal**, or **underused**
  (< 20 % used); the thresholds are printed on the page.
* **Busiest weekdays** (Mon–Sun) and **busiest hours** (08:00–18:00) — bar charts of
  active bookings, so the manager can see when rooms are in demand.
* **Cancellations** — cancellation rate per room and bookings vs cancellations per month.
  Cancelled bookings are counted separately and never added to booking counts or hours.
* **Recommendations** — a short automatic list naming heavily used rooms, underused
  rooms and rooms with a high cancellation rate (≥ 25 %), each with the figure behind it,
  to help decide whether to change room allocation.

## API summary

All responses are JSON except the CSV export. Errors look like `{"error": "..."}`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/rooms` | List rooms (`id`, `name`, `capacity`) |
| GET | `/api/availability?date=YYYY-MM-DD` | Per room: active `bookings` and `free` gaps |
| GET | `/api/bookings?date=&room=&include_cancelled=` | List bookings (`room` is a numeric room id; `include_cancelled` accepts 1/true/yes) |
| POST | `/api/bookings` | Create booking(s). Body: `room_id`, `date`, `start`, `end`, `booker`, `title`, `notes`, `repeat_weeks` |
| POST | `/api/bookings/<id>/cancel` | Cancel. Body (optional): `{"cancelled_by": "Name"}` |
| GET | `/api/export.csv` | All active bookings as CSV |
| GET | `/api/dashboard?from=YYYY-MM-DD&to=YYYY-MM-DD` | Dashboard data for the range (see below) |

Text fields must be JSON strings and `room_id` / `repeat_weeks` real integers — booleans
and floats such as `1.5` are rejected with `400`.

Status codes: `201` created, `200` ok, `400` validation error, `404` unknown booking,
`409` overlap, already cancelled, or a recurring series with conflicting weeks (nothing
is booked).

`/api/dashboard` returns `range`, `thresholds`, `kpis`, `rooms[]`, `weekdays[]`,
`hours[]`, `trend[]` and `recommendations[]`. Both `from` and `to` may be omitted (last
30 days); giving only one, an invalid or non-existent date, `from` after `to`, or a range
over 366 days returns `400` with `{"error": "..."}`.

Example:

```bash
curl -X POST http://localhost:8000/api/bookings \
  -H 'Content-Type: application/json' \
  -d '{"room_id":1,"date":"2026-01-05","start":"10:00","end":"11:00",
       "booker":"Ada","title":"Standup","notes":"","repeat_weeks":0}'
```

## Where the data lives

`bookings.db` (SQLite) in the same folder as `app.py` (the path is printed at startup).
It is created on first start with the four rooms **Aurora** (8 seats), **Birch** (4),
**Cedar** (12), **Dune** (6). Set `BOOKINGS_DB=/path/to/file.db` to use a different file.

Tables: `rooms(id, name, capacity)` (name is UNIQUE) and
`bookings(id, room_id, date, start_time, end_time, booker, title, notes, created_at, cancelled_at, cancelled_by)`
with index `idx_bookings_slot`. Deleting a room that still has bookings fails on the
foreign key.

## Back up

Stop the app first (or run `sqlite3 bookings.db "PRAGMA wal_checkpoint(TRUNCATE);"`), then
copy the file. The app runs in WAL mode, so also copy `bookings.db-wal` / `bookings.db-shm`
if they exist.

```bash
cp bookings.db bookings-backup-$(date +%F).db
```

Restore by copying the backup back to `bookings.db` while the app is stopped.

## Change the room list

Rooms are rows in the `rooms` table, so no code change is needed:

```bash
sqlite3 bookings.db "INSERT INTO rooms(name, capacity) VALUES ('Elm', 10);"
sqlite3 bookings.db "UPDATE rooms SET capacity = 6 WHERE name = 'Birch';"
sqlite3 bookings.db "DELETE FROM rooms WHERE name = 'Dune';"   # only if it has no bookings
```

Room names are UNIQUE, so adding a duplicate name fails. The UI and API pick up changes
on the next page load. To change the *default* rooms for a fresh database, edit
`DEFAULT_ROOMS` at the top of `app.py`.

## Tests

```bash
python3 -m unittest -v test_app
```

`test_app.py` starts the real server on a free port with a temporary database and
checks: rooms seeded, index page served, create booking, overlap rejected with 409,
adjacent booking accepted, cancel frees the slot, cancelled booking no longer blocks,
cancelled booking kept but not listed, validation errors, recurring all-or-nothing,
recurring creates all weeks, availability gaps, CSV export, and that the served page
contains the escaping helper (it does not prove user text is escaped end to end).
Five dashboard tests cover the page and its links, an empty range, seeded numbers
including a cancelled booking, the heavy-room recommendation, invalid ranges and the
default range.
There are **no automated tests for the strict type checks or for concurrency** — those were
checked by hand with an external probe and are not covered by `test_app.py`.
