# Meeting Room Booking

A small, self-contained meeting room booking web app: one Python file (`app.py`,
standard library only — `http.server` + `sqlite3`) serving one HTML/CSS/JS page.
No logins, no external CDNs, no network dependencies.

## Run it

```bash
python3 app.py
```

Then open **http://localhost:8000** in a browser.

Optional environment variables:

```bash
PORT=9000 python3 app.py                       # different port
BOOKING_DB=/tmp/rooms.db python3 app.py        # different database file
```

The SQLite database `bookings.db` is created next to `app.py` on first start and
seeded with the four default rooms. Delete the file to start from scratch.

## Run the tests

```bash
python3 test_app.py
```

The test script starts its own server on a free port with a temporary database,
exercises the API with `urllib`, and shuts it down. It does not touch your
`bookings.db`.

## How to use it

1. **Check availability** — pick a date at the top (defaults to today; "Today" and
   "Next day" buttons are provided). The grid shows every room as a row and every
   30-minute slot from 08:00 to 18:00 as a column:
   - green = free, red = booked, grey = past/closed.
   - Each room row shows its capacity and how many slots are still free that day.
2. **Book a room** — click any green cell. The booking form is prefilled with that
   room and start time (end defaults to 1 hour later). Enter your name (required)
   and an optional title, then press **Book room**. You can also fill the form
   manually. The grid and the day's booking list refresh immediately.
3. **Cancel a booking** — in the "Bookings on <date>" list, press **Cancel** next to
   a booking and confirm. The booking is marked *cancelled* (kept as history,
   struck through) and its slot becomes free again right away.

## Rules enforced by the server

- Rooms: Aurora (8), Birch (4), Cedar (12), Dune (20).
- Booking hours 08:00–18:00, 30-minute slots, single bookings only.
- Booker name required (free text, no login).
- No bookings in the past (a slot that has already started today is rejected).
- Maximum 4 hours per booking.
- **No double bookings**: overlap detection runs inside a `BEGIN IMMEDIATE`
  transaction, and a partial unique index on `(room_id, date, start) WHERE
  status='active'` makes a duplicate active slot impossible even under concurrent
  requests. Conflicts return HTTP 409 with a message naming the clashing booking.
- Cancelled bookings are kept with `status='cancelled'` and never block a slot.

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/rooms` | `{"rooms":[{"id","name","capacity"}]}` |
| GET | `/api/availability?date=YYYY-MM-DD` | Per room: `slots` list of `{start,end,status:"free"\|"busy"}` plus `free_count` |
| GET | `/api/bookings?date=YYYY-MM-DD` | All bookings for the day incl. cancelled: `id, room, room_id, date, start, end, booker, title, status` |
| POST | `/api/bookings` | Body `{room_id,date,start,end,booker,title}` → `201 {"booking":…}`, `409` on conflict, `400` on invalid input |
| POST | `/api/bookings/{id}/cancel` | `200 {"booking":…}`, `404` unknown id, `409` already cancelled |
| GET | `/health` | `{"ok":true}` (used by the tests) |

Example:

```bash
curl -s "http://localhost:8000/api/availability?date=$(date -d tomorrow +%F)"
curl -s -X POST http://localhost:8000/api/bookings \
  -H 'Content-Type: application/json' \
  -d '{"room_id":1,"date":"2025-01-20","start":"09:00","end":"10:00","booker":"Sam","title":"Sync"}'
curl -s -X POST http://localhost:8000/api/bookings/1/cancel
```

## Files

- `app.py` — server, database, API and the single-page UI.
- `test_app.py` — API test suite (`python3 test_app.py`).
- `README.md` — this file.
