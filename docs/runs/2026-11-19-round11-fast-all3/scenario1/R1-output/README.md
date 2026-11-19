# Meeting Room Booking

A small web app that replaces the shared spreadsheet. It fixes the two problems you described:

- **No double bookings** – every booking is validated on the server against existing bookings for the same room; overlapping requests are rejected with a clear message. A lock around the read-modify-write of the data file means two people clicking "Book" at the same moment cannot both win.
- **No stale records** – cancelling a booking marks it cancelled and it disappears from availability immediately.

Standard library only (Python 3.8+), no installation, no external packages.

## Files

| File | Purpose |
|---|---|
| `app.py` | The whole app: web server, validation, storage, browser UI |
| `test_app.py` | Self-tests: overlap rejection, cancellation freeing the slot, recurring conflict skipping, validation rules, concurrency |
| `bookings.json` | Data file, created automatically on first booking |
| `README.md` | This file |

## Start it

```bash
python3 app.py
```

Then open **http://localhost:8000** in a browser. To let colleagues on the same network use it, they open `http://<your-machine-ip>:8000`. Stop with `Ctrl+C`.

Optional: `PORT=9000 python3 app.py` to use another port, `BOOKINGS_FILE=/path/to/file.json python3 app.py` to store data elsewhere.

## Run the tests

```bash
python3 test_app.py
```

Expected: `Ran 5 tests ... OK`.

## How to use it

1. **Check availability** – open *Availability* (the start page). Pick a date and press *Check*. You get a grid: one row per room (Aspen 4, Birch 6, Cedar 10, Dune 20) and one column per 30-minute slot from 08:00 to 18:00. Green = free, red = booked (with the meeting title and who booked it). Weekends are shown greyed out.
2. **Find a free room for a time** – on the same page fill in *Find a free room for* (e.g. 10:00 to 11:30) and press *Check*. A green banner lists every room that is free for that whole period.
3. **Book** – open *Book a room*, choose room, date, start, end, title and your name, press *Book*. Rules enforced by the server:
   - name and title required
   - Monday–Friday only, 08:00–18:00, 30-minute boundaries
   - end after start, at most 4 hours
   - up to 60 days ahead, no past dates
   - no overlap with an existing booking in the same room (error message names the clashing booking)
4. **Recurring weekly bookings** – in the booking form set *Repeat weekly for N weeks* (e.g. 8). The same slot is booked for N consecutive weeks; weeks that clash are skipped and listed with the reason, e.g. `Skipped 1 week(s): 2025-06-12 (Double booking: Dune is already booked 14:00-15:00 ...)`.
5. **Cancel** – open *All bookings / cancel*. Every upcoming booking shows date, time, room, title and **who booked it**, with a *Cancel* button. Anyone can cancel; the slot is free again immediately.
6. **My bookings** – open *My bookings*, type your name, press *Show* to see only your bookings (with cancel buttons).

## JSON API (optional)

- `GET /api/availability?date=YYYY-MM-DD[&room=Aspen][&start=09:00&end=10:00]`
- `GET /api/bookings[?booker=Ann]`

## Defaults used

4 rooms (Aspen 4, Birch 6, Cedar 10, Dune 20); 30-minute slots 08:00–18:00 Mon–Fri; name required, no login; anyone can cancel; max 4 hours per booking; up to 60 days ahead; no buffer between meetings. These are constants at the top of `app.py` (`ROOMS`, `DAY_START`, `DAY_END`, `MAX_HOURS`, `MAX_DAYS_AHEAD`) if you want to change them.
