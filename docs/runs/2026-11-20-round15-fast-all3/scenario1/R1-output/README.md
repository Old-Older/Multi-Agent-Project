# Meeting Room Booking System (v1.1)

A small, dependency-free web app for booking meeting rooms. It replaces the shared
spreadsheet: one source of truth, no double bookings, and cancellations free the slot
immediately.

* **Browser UI** at `/` — date picker, room filter, slot grid, click-to-book dialog,
  one-click cancel, and a **My bookings** panel.
* **JSON REST API** under `/api/...` — for scripts or other tools.
* **Storage** — a local SQLite file (`bookings.db`), created automatically on first run.
* **No installs** — Python 3 standard library only (`http.server`, `sqlite3`).

## Files

| File | Purpose |
|------|---------|
| `app.py` | The whole application: DB schema + auto-seed, booking logic, REST API, HTML UI. |
| `test_app.py` | `unittest` suite (**18 tests**) covering booking, overlap rejection, cancellation, wrong-name cancel, validation, availability date range, booker filter, unknown room, bool room id, JSON errors for unsupported methods, configurable admins. |
| `README.md` | This file. |

## Run it

```bash
python3 app.py
```

Then open <http://127.0.0.1:8000/>.

Optional environment variables:

```bash
PORT=9000 HOST=0.0.0.0 BOOKINGS_DB=/path/to/bookings.db ADMIN_NAMES="admin,office" python3 app.py
```

| Variable | Default | Meaning |
|----------|---------|---------|
| `PORT` | `8000` | TCP port to listen on. |
| `HOST` | `127.0.0.1` | Bind address. Use `0.0.0.0` to let colleagues on the same network reach it (`http://<your-machine-ip>:8000/`). |
| `BOOKINGS_DB` | `bookings.db` next to `app.py` | SQLite database file. |
| `ADMIN_NAMES` | `admin` | Comma-separated names that may cancel **any** booking (case-insensitive). Example: `ADMIN_NAMES="admin,office manager"`. |

The database file is created next to `app.py` and the four rooms are seeded
automatically on startup (idempotent — safe to restart any time).

## Run the tests

```bash
cd <the directory containing app.py>
python3 -m unittest -v test_app
```

The tests start a real server on a free port and use a temporary database, so they
never touch your real `bookings.db`. (`test_app.py` also adds its own directory to
`sys.path`, so `python3 -m unittest -v test_app` works from the repo root too.)

## How to use the UI

1. **Enter your name** in the "Your name" box (top bar). It is used to book, to cancel,
   and to fill the "My bookings" panel.
2. **Pick a date** (defaults to today; the picker is limited to today … today + 60 days)
   and optionally **filter by room**. **Prev / Today / Next** move one day at a time and
   stop at those limits.
3. The grid shows every 30-minute slot from 08:00 to 18:00 for each room:
   * **green "Free"** — click it to open the booking dialog;
   * **red** — booked, showing the booker's name and the booked time range.
4. In the dialog, the **start** time is the slot you clicked and the **end** time list only
   offers valid choices: from start + 30 minutes up to `min(start + 4 h, 18:00)`. Options
   that would overlap an existing booking in that room are disabled and marked
   `(booked)`, and an inline message appears in the dialog if the range is not usable —
   no server round trip needed. Press **Book** to save. If someone else grabbed the slot
   in the meantime you get a clear "already booked" message.
5. **Cancel**: your own bookings are outlined in blue in the grid and have a **Cancel**
   button. Click it, confirm, and the slot turns green again immediately.
   Only the booker (name match, case-insensitive) or an admin can cancel.
6. **My bookings** (panel below the grid) lists all of *your* upcoming bookings across
   every date and room, each with a **Cancel** button — so a booking made for another day
   can always be found and cancelled. It refreshes when you change your name, book,
   cancel, or press **Refresh**.

## Rules enforced

* Rooms: **Cedar** (4), **Birch** (6), **Maple** (10), **Oak** (20).
* Working hours **08:00–18:00**, **30-minute** slots.
* Anyone can book with a name — no login.
* Single bookings only (no recurrence).
* Max booking length **4 hours**; bookings from **today** up to **60 days** ahead; no past
  dates and no start time that has already passed today.
* **No double bookings**: the check and insert happen inside one `BEGIN IMMEDIATE`
  transaction, backed by a `UNIQUE (room_id, date, start)` constraint and an overlap
  query (`start < new_end AND end > new_start`). Concurrent requests cannot both win.
* Cancellation deletes the row, so the slot is free on the very next availability query.

## REST API

All responses are JSON, including errors (`{"error": "message"}`) and unsupported
methods (`405`). `HEAD` is supported on every `GET` route. Internal errors return a
generic `{"error": "internal server error"}` — no Python tracebacks or exception text.

### `GET /api/rooms`
```json
{"rooms": [{"id": 1, "name": "Cedar", "capacity": 4}, ...]}
```

### `GET /api/availability?date=YYYY-MM-DD[&room=<id|name>]`
`date` is required and must be between today and 60 days ahead, otherwise `400`
`{"error": "date must be between today and 60 days ahead"}`. An unknown room id or name
returns `400 {"error": "unknown room"}`.
```json
{"date": "2025-06-02", "slot_minutes": 30,
 "rooms": [{"room_id": 1, "room": "Cedar", "capacity": 4,
            "slots": [{"start": "08:00", "end": "08:30", "free": true, "booking": null},
                      {"start": "08:30", "end": "09:00", "free": false,
                       "booking": {"id": 7, "room_id": 1, "room": "Cedar",
                                   "date": "2025-06-02", "start": "08:30",
                                   "end": "09:30", "booker": "Alex"}}]}]}
```

### `POST /api/bookings`
```bash
curl -X POST http://127.0.0.1:8000/api/bookings \
  -H 'Content-Type: application/json' \
  -d '{"room_id": 1, "date": "2025-06-02", "start": "10:00", "end": "11:30", "booker": "Alex"}'
```
* `201` → `{"booking": {...}}`
* `409` → slot overlaps an existing booking
* `400` → invalid input (bad date/time, outside hours, > 4 h, past date or past start
  time today, > 60 days, unknown room, `room_id` not an integer — booleans are rejected,
  no name)

### `DELETE /api/bookings/{id}`
```bash
curl -X DELETE http://127.0.0.1:8000/api/bookings/7 \
  -H 'Content-Type: application/json' -d '{"booker": "Alex"}'
```
* `200` → `{"cancelled": 7}`
* `403` → name does not match the booker (and is not an admin)
* `404` → no such booking
* `400` → no name supplied (`"booker name is required to cancel"`), or the body is not a
  JSON object (`"JSON object expected"`)

### `GET /api/bookings[?date=YYYY-MM-DD][&room=<id|name>][&booker=NAME][&upcoming=1]`
All filters are optional and combine. `booker` matches case-insensitively; `upcoming=1`
keeps only today and later. A non-numeric/unknown `room` returns `400`.
```json
{"bookings": [{"id": 7, "room_id": 1, "room": "Cedar", "date": "2025-06-02",
               "start": "08:30", "end": "09:30", "booker": "Alex"}]}
```
Example — everything Alex has booked from today on:
```bash
curl 'http://127.0.0.1:8000/api/bookings?booker=Alex&upcoming=1'
```

## Admin

There is no login. Names listed in the **`ADMIN_NAMES`** environment variable
(comma-separated, case-insensitive, default `admin`) may cancel any booking:

```bash
ADMIN_NAMES="admin,office manager" python3 app.py
```

The active list is printed at startup. Anyone who types an admin name as their own name
can cancel any booking — see the limitations below.

## Notes / limitations (v1.1)

* No authentication — anyone who knows a booker's name (or an admin name) can cancel that
  booking. Fine for a trusted team; add real accounts if that becomes a problem.
* No recurring bookings, no email notifications, no room equipment/notes fields.
* Single process, single SQLite file — plenty for a team; not designed for multi-server use.
