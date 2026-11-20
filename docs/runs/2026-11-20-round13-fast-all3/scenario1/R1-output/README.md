# Meeting Room Booking

A small, self-contained meeting room booking system: one Python file, standard library only,
no installs, no internet needed. Everyone who opens the page sees the same bookings because
they are stored in one JSON file on the machine running the server.

## Run it

```bash
python3 booking_app.py
```

Then open <http://localhost:8000> in a browser.

- Requires Python 3.7+ (no `pip install` needed).
- The server listens on port 8000 on all network interfaces (`HOST = "0.0.0.0"`), so anyone who can
  reach the machine can use it. If the port is busy the server stops with an `OSError`; change `PORT`
  at the top of `booking_app.py` and use that port in the URL instead.
- To let teammates use it, run it on a shared machine and give them `http://<that-machine>:8000`.
- Stop it with `Ctrl+C`. Bookings survive a restart because they are read from `bookings.json`.

## How to use it

The page has four sections, top to bottom.

**1. Availability** – pick a date (or press *Today* / *Tomorrow*) and see a grid of all rooms
against every 30-minute slot from 08:00 to 18:00. Green cells are free; red cells are booked and
show who booked them and the meeting title (in the first 30-minute cell of the booking). Click any
green cell to fill the booking form with that room, date and start time (the duration is not
pre-filled — choose it yourself).

**2. Find a free room** – enter a date, start time, duration and (optionally) a minimum capacity,
then press *Find rooms*. It lists which rooms are free for that whole window and which are taken.
Rooms smaller than the minimum capacity are left out of the result entirely.

**3. Book a room** – choose room, date, start, duration, type your name and a title, press *Book*.
The server checks everything and shows a clear message if something is wrong: unknown room, empty
name or title, outside 08:00–18:00, start or duration not a multiple of 30 minutes, duration zero or
longer than 4 hours, a time that has already passed, or a slot already booked by someone else.
A successful booking appears immediately in the grid and the bookings list.

**4. Bookings** – shows the bookings for a chosen date (today by default), or *All upcoming*, which
hides meetings that have already ended. Each booking has a **Cancel** button; you are asked to
confirm, and once cancelled the slot is free again right away for everyone.

Rules: 4 rooms — Aurora (8), Birch (4), Cedar (12), Den (20); 08:00–18:00 in 30-minute slots;
no logins (just your name); no bookings in the past; max 4 hours per booking; no recurring meetings.

**No authentication:** anyone who can open the page can book and can cancel *anyone's* booking.
The booker name is shown so the team can see who owns a booking, but it is not enforced.

## API summary

All responses are JSON. Errors return `{"error": "message"}` with status 400 (bad input),
404 (unknown booking id) or 409 (slot taken); an unexpected server fault returns 500.

| Method | Path | Description |
|---|---|---|
| GET | `/api/rooms` | Rooms with capacities, opening hours, slot length, max duration |
| GET | `/api/bookings?date=YYYY-MM-DD` | Bookings on one date |
| GET | `/api/bookings?upcoming=1` | Upcoming bookings (default when no `date`); `upcoming=0` returns every booking, including past ones |
| GET | `/api/availability?date=&start=&duration=&capacity=` | For each room: `free: true/false` for that window. Defaults: `date`=today, `start`=09:00, `duration`=60 minutes, `capacity`=0 (no filter). Rooms below `capacity` are omitted. Invalid date/time/duration → 400 |
| POST | `/api/bookings` | Create a booking. Body: `{"room":"aurora","date":"2026-05-04","start":"09:00","duration":60,"name":"Alex","title":"Sync"}` → 201 with the booking. `room` is case-insensitive; `duration` is minutes or `"HH:MM"` and defaults to 60 |
| DELETE | `/api/bookings/<id>` | Cancel a booking → 200, or 404 if it does not exist |

Room ids: `aurora`, `birch`, `cedar`, `den`.

Example (use a future date — a past date is rejected):

```bash
curl -s http://localhost:8000/api/rooms
curl -s "http://localhost:8000/api/availability?date=2030-05-04&start=09:00&duration=60&capacity=8"
curl -s -X POST http://localhost:8000/api/bookings -H 'Content-Type: application/json' \
  -d '{"room":"aurora","date":"2030-05-04","start":"09:00","duration":60,"name":"Alex","title":"Sync"}'
curl -s -X DELETE http://localhost:8000/api/bookings/1
```

## Where data is stored

`bookings.json`, in the same folder as `booking_app.py`. It is created automatically on first run
with a few example bookings for today and tomorrow — these are real bookings and block those slots
until you cancel them. All reads and writes go through a threading lock, so two people booking the
same slot at the same moment cannot both succeed. (This is by design in the code; it has not been
re-tested under load in the final delivery.)

## How to reset

Stop the server first, then delete `bookings.json` and start it again — a fresh file with the
example bookings is created. To start completely empty, delete the file and create a new one
containing valid JSON with both keys:

```json
{"next_id": 1, "bookings": []}
```

Do not edit `bookings.json` by hand while the server is running.

## Tests

The developer's test scripts `test_api.py` and `test_concurrency.py` (booking, double-booking
rejected with 409, validation errors, cancel, re-book the freed slot, 20 parallel requests for one
slot producing exactly one booking) are not part of this delivery and were not re-run on the final
files. Treat the concurrency guarantee as unverified until you run them yourself.
