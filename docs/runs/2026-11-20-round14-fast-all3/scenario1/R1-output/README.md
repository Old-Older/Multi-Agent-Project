# Meeting Room Booking System (v1)

A small, self-contained booking system that replaces the shared spreadsheet.
It prevents double bookings and frees a slot the moment a booking is cancelled.

- **Web app** (`app.py`): one HTML page served by Python — check availability, book, cancel.
- **CLI** (`cli.py`): `list`, `book`, `cancel` from the terminal.
- **Storage**: `data.json`, written atomically (temp file + `os.replace`) under a
  file lock, so concurrent requests cannot double-book.
- **No installs**: Python 3 standard library only.

## Run it

```bash
cd booking_system   # run from the folder that contains booking_system/
python3 app.py                 # then open http://127.0.0.1:8000/
python3 app.py --port 9000     # different port
python3 app.py --host 0.0.0.0  # let teammates on the LAN reach it
python3 app.py --data ./data.json          # explicit data file (any path you like)
python3 app.py --data ~/booking/data.json  # parent folder is created if missing
```

The data file defaults to `data.json` next to `app.py`; it is created on the first booking.
A `data.json.lock` file appears beside it — that is the lock, not a second copy of the data.

**Not verified:** the browser page has not been clicked through in a real browser; its
behaviour was checked by reading the code and by tests that mirror its logic.
The folder holding the data file is created automatically at startup; if it cannot be
created or written, the server refuses to start and prints a clear message (use `--data`
to pick another location). Use a path that exists on your OS — e.g. `./data.json` or
`~/booking/data.json` — rather than a Unix-only path such as `/tmp/...` on Windows.

## Rules (defaults)

| Setting | Value |
|---|---|
| Rooms | Aspen (4), Birch (6), Cedar (10), Dune (20) |
| Working hours | 08:00–18:00 |
| Slot size | 30 minutes |
| Max booking length | 4 hours |
| Booking horizon | 60 days ahead (no past dates) |
| Booker | free-text name, no login |
| Cancelling | anyone may cancel any booking |

## Usage walkthrough (browser)

1. Start the server and open <http://127.0.0.1:8000/>.
2. **Check availability** — pick a date (defaults to today) and optionally a room.
   The grid shows every 30-minute slot per room: **green = free**, **red = booked**
   (hover a red cell to see who booked it and the title).
3. **Book** — click any green slot. The form opens pre-filled with that room, date,
   start time **and end time** (one 30-minute slot later, e.g. 14:30 → 15:30); change
   either time if you need longer, add your name and a title, then press **Book**
   (or just press Enter). Your name is remembered for the next booking.
   (Or press **New booking** to fill the form from scratch.) The date picker offers
   today up to 60 days ahead; past dates cannot be booked.
   The date field only accepts today up to 60 days ahead.
4. **Cancel** — the "Bookings for the day" table lists the day's bookings with a
   **Cancel** button. After cancelling, the slot turns green immediately. The
   **Upcoming bookings** table below lists every booking from today onwards (all
   rooms), so you can always find and cancel a booking made for another day.
5. **Past dates** — you can pick a past date to see what was booked that day. The grid
   then shows the real bookings and a note says the day is read-only; past slots cannot
   be booked.
6. **Conflicts** — if the slot is taken, a red message names the clashing booking,
   e.g. `Conflict: Aspen is already booked 09:00-10:00 on 2025-01-20 by Ann ('Standup').`

## Usage walkthrough (CLI)

```bash
python3 cli.py list                                   # all bookings
python3 cli.py list --date 2025-01-20 --room aspen    # one day / one room
python3 cli.py book --room aspen --date 2025-01-20 --start 09:00 --end 10:00 \
                    --booker "Ann" --title "Standup"
python3 cli.py cancel --id 3
```

The CLI and the web app share the same `data.json` and the same lock, so they
always agree. Errors (conflicts, bad times, unknown ids) print to stderr and exit 1.

## HTTP API (used by the page)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | the UI |
| GET | `/api/rooms` | rooms + rules |
| GET | `/api/availability?date=YYYY-MM-DD[&room=aspen]` | 30-min slots, free/busy; `date` defaults to today, `room` optional. Past dates return the real bookings for that day plus `"past": true` / `"read_only": true` (nothing can be booked there) |
| GET | `/api/bookings[?date=YYYY-MM-DD][&room=aspen]` | bookings; both parameters are optional — with no `date` it returns **all** bookings (used by the "Upcoming bookings" table), with no `room` all rooms |
| POST | `/api/book` | `{room,date,start,end,booker,title}` → 201 or 400 with `error` |
| POST | `/api/cancel` | `{id}` → 200 or 400 with `error` |

Unknown paths return `404` with a JSON body `{"error": "Not found: <path>"}`;
`/favicon.ico` returns `204 No Content`.

## Tests

```bash
python3 selftest.py
```

Starts the server on a temporary data file and checks (53 checks, all passing): page served, availability,
booking, overlap rejection (with the conflicting booking named), adjacent and
other-room bookings allowed, all validation rules, cancel frees the slot with no
stale record, re-booking a freed slot, double-cancel rejected, 12 parallel
identical bookings yielding exactly one success, the CLI `list`/`book`/`cancel`,
HTML/JS escaping of booker and title (XSS), the pre-filled end-time logic, past-date
availability (real bookings, read-only flag) and the upcoming-bookings endpoint.

## Files

- `app.py` — web app, booking logic, storage
- `cli.py` — command-line interface
- `selftest.py` — end-to-end test script
- `README.md` — this file
- `data.json` — created at runtime (bookings)
