# Meeting Room Booking — how to use it

Replaces the shared spreadsheet. Two problems it fixes:

* **No double bookings** — an overlapping booking in the same room is refused with a
  message naming the clash (e.g. `Room Birch is already booked 10:00-11:00 on 2026-01-05 (Standup)`).
* **No stale records** — cancelling frees the slot immediately and the booking disappears
  from the availability view and the list. History is kept in the database.

## Start it

```bash
python3 app.py            # http://localhost:8000
python3 app.py 9000       # another port
```

Python 3 standard library only — nothing to install. Colleagues on the same network open
`http://<your-machine-ip>:8000`.

**No logins:** the server listens on all network interfaces and has no authentication, so
anyone who can reach the port can book and cancel any booking. Run it only on a trusted
network.

Data lives in `bookings.db` next to `app.py` (the path is printed at startup); set
`BOOKINGS_DB=/path/to/file.db` to use another file. The database runs in WAL mode, so to back
it up stop the app first (or run `sqlite3 bookings.db "PRAGMA wal_checkpoint(TRUNCATE);"`)
and copy `bookings.db` together with `bookings.db-wal` / `bookings.db-shm` if they exist.

## The three screens (all for one chosen date, default today)

1. **Availability** — pick a date or press *Today*. Each room is a card with its capacity,
   the bookings already on that date (time, title, booker) and the **free gaps** between them.
   The *Download CSV* link at the top of this section exports all active bookings for all
   dates, not just the chosen day.
2. **Book a room** — room, date (it starts as the availability date you are viewing; change
   it here to book another day — the two can differ), start and end (15-minute steps,
   08:00–19:00 inclusive), your name, a title, optional notes, and optionally *Repeat weekly*
   (up to 52 extra weeks, i.e. 53 bookings). Press **Book room**. A green banner appears at the
   top of the page confirming the booking; a red banner there explains what went wrong.
   Recurring bookings are all-or-nothing: if any week clashes, nothing is created and the
   clashing date is named.
3. **Bookings on <date>** — every active booking with a **Cancel** button. Two steps: a
   confirmation dialog names the room, date, time, title and booker; then a prompt asks for
   your name (optional, recorded as who cancelled — dismissing the prompt aborts the
   cancellation). Afterwards the availability grid and the list refresh, so the freed slot is
   visible at once. Cancelling an already-cancelled booking or an unknown id is refused with a
   message.

## Rules built in

* Overlaps in the same room are rejected (identical, overlapping, contained intervals).
  Back-to-back bookings (10:00–11:00 then 11:00–12:00) are fine, and different rooms at the
  same time are fine.
* The overlap check and the insert run under one database write lock (`BEGIN IMMEDIATE`),
  so two people clicking *Book* at the same moment cannot both succeed. (An external probe
  with 20 simultaneous requests produced exactly one success; this is not part of
  `test_app.py`.)
* A cancelled booking cannot be cancelled twice and no longer blocks its slot.
* Validation: real date, end after start, 15-minute grid, 08:00–19:00, non-empty name and
  title, existing room, whole-number room id and repeat count. Text fields must be JSON
  strings and `room_id` / `repeat_weeks` real integers — booleans and floats such as `1.5`
  are rejected with `400`.

## Rooms

Seeded with **Aurora** (8 seats), **Birch** (4), **Cedar** (12), **Dune** (6). They are rows
in the `rooms` table, so no code change is needed:

```bash
sqlite3 bookings.db "INSERT INTO rooms(name, capacity) VALUES ('Elm', 10);"
sqlite3 bookings.db "UPDATE rooms SET capacity = 6 WHERE name = 'Birch';"
```

Room names are UNIQUE, so adding a duplicate name fails. Deleting a room that still has
bookings fails on the foreign key — cancel or move those bookings first.

## API (for scripts or a future front end)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/rooms` | rooms |
| GET | `/api/availability?date=YYYY-MM-DD` | per room: active bookings and free gaps |
| GET | `/api/bookings?date=&room=&include_cancelled=` | list bookings (`room` is a numeric room id; `include_cancelled` accepts 1/true/yes) |
| POST | `/api/bookings` | create (`room_id`, `date`, `start`, `end`, `booker`, `title`, `notes`, `repeat_weeks`) |
| POST | `/api/bookings/<id>/cancel` | cancel (optional `{"cancelled_by": "Name"}`) |
| GET | `/api/export.csv` | all active bookings as CSV |

`201` created, `200` ok, `400` validation error, `404` unknown booking, `409` overlap,
already cancelled, or a recurring series with conflicting weeks (nothing is booked).

## Tests

```bash
python3 -m unittest -v test_app
```

14 tests, all passing: rooms seeded, index page served, create, overlap rejected, adjacent
accepted, cancel frees the slot, cancelled booking no longer blocks, cancelled booking kept
but not listed, validation, recurring all-or-nothing, recurring creates all weeks,
availability gaps, CSV export, and a check that the served page contains the escaping helper
(it does not prove user text is escaped end to end). There are **no automated tests for the
strict type checks or for concurrency** — those were checked by hand with an external probe
and are not covered by `test_app.py`.
