# Meeting Room Booking — what was built and how to use it

A small web app that replaces the shared spreadsheet. It prevents double bookings
and keeps cancellations up to date, so the room grid is always the truth.

## Files

| File | What it is |
| --- | --- |
| `app.py` | The whole system: server, database, JSON API and the single-page UI (Python 3 standard library only — nothing to install). |
| `test_app.py` | Automated API tests (`python3 test_app.py` → 8 tests, all pass). |
| `README.md` | Reference: run instructions, rules, API table. |
| `HOW_TO_USE.md` | This guide. |
| `qa_report.md` | Independent QA report (PASS). Its check counts and concurrency runs came from probe scripts that are not shipped, so those figures are unverified; `test_app.py` is the reproducible evidence. |
| `doc_review.md`, `doc_review_confirmation.md` | Documentation review of these files against the code, and its confirmation round. |

## Start it

```bash
python3 app.py
```

Open **http://localhost:8000**. The database `bookings.db` is created next to
`app.py` on first start and seeded with four rooms: Aurora (8), Birch (4),
Cedar (12), Dune (20). Colleagues on the same network can use
`http://<your-machine>:8000` — put it behind a firewall on untrusted networks, and
note there is no login: anyone who can reach the page can book or cancel. Optional:
`PORT=9000 python3 app.py`, `BOOKING_DB=/path/rooms.db python3 app.py`.

## How to use it (three things you asked for)

1. **Check availability** — pick a date at the top (defaults to today; "Today" /
   "Next day" buttons). The grid shows one row per room and one column per
   30-minute slot; the column headers are slot *start* times 08:00–17:30 and the last
   slot ends at 18:00: **green = free, red = booked, grey = past / closed** (a past
   slot that was booked stays red). Each room row also shows its capacity and how many
   slots are still free.
2. **Book a room** — click any green cell. The form is prefilled with that room and
   start time (end defaults to one hour later). Type your name (required) and an
   optional title, press **Book room**. The grid and the day's list refresh at once.
   If someone else already has that slot you get a clear message naming the clashing
   booking, e.g. "Aurora is already booked 09:00-10:00 on 2026-11-21 by Sam (Sync).
   Please pick another slot." — no double booking.
3. **Cancel a booking** — in the "Bookings on <date>" list press **Cancel** (the
   button only appears on active bookings) and confirm. The booking is kept as history
   (struck through, marked *cancelled*) and its slot turns green again immediately, so
   it can be rebooked.

## Rules the server enforces

- Booking hours 08:00–18:00, 30-minute slots, one-off bookings only (no recurring bookings).
- Booker name required (free text, no login), at most 80 characters; title at most 120 characters.
- No bookings in the past (a slot that has already started today is rejected); maximum 4 hours per booking.
- **No double bookings**: overlap detection runs inside a `BEGIN IMMEDIATE`
  transaction and a partial unique index on `(room_id, date, start) WHERE
  status='active'` makes a duplicate active slot impossible even when two people
  click at the same moment (the unique index guarantees this; the 20-request concurrency run was done by QA with a probe script that is not shipped, so that figure is unverified here).
- Cancelled bookings never block a slot.

## API (for scripts or a future integration)

`GET /api/rooms`, `GET /api/availability?date=YYYY-MM-DD`,
`GET /api/bookings?date=YYYY-MM-DD`, `POST /api/bookings`,
`POST /api/bookings/{id}/cancel` — see `README.md` for bodies and status codes.

## Known limits

- The page was checked through its API and by reading the code, not clicked in a real
  browser; do one click-through (pick a date → click a green cell → Book → Cancel) first.

- No login: anyone who can reach the page can book or cancel. Fine for a trusted
  team network; say the word if you want per-person accounts.
- Single bookings only (no weekly recurring bookings yet).
- Rooms are fixed in `app.py` (`DEFAULT_ROOMS`); edit that list and delete
  `bookings.db` to change them (rooms are only seeded when the table is empty).
