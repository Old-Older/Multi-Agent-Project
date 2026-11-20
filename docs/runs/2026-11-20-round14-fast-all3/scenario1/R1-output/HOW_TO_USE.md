# Meeting Room Booking System — what it is and how to use it

This replaces the shared spreadsheet. It fixes the two problems you described:

- **No double bookings.** Every booking is checked against existing bookings for the
  same room and time. An overlapping request is rejected and the message names the
  booking that is in the way.
- **Cancellations take effect immediately.** Cancelling deletes the record, so the
  slot is free again at once — nothing stale is left behind.

## What was built

| File | What it does |
|---|---|
| `booking_system/app.py` | The whole system: a small web app (one page in the browser) plus a JSON API. Python 3 standard library only — nothing to install. |
| `booking_system/cli.py` | Same system from the terminal: `list`, `book`, `cancel`. |
| `booking_system/selftest.py` | Automated end-to-end test (53 checks, all passing). |
| `booking_system/README.md` | Technical reference: settings, API, tests. |
| `booking_system/data.json` | The bookings — created automatically on the first booking (it does not exist yet). This is the file you back up / share instead of the spreadsheet. A `data.json.lock` file appears next to it; that is normal, it stops two people booking at once. |

## Start it

```bash
cd booking_system               # the folder containing app.py
python3 app.py                  # open http://127.0.0.1:8000/
python3 app.py --host 0.0.0.0   # so teammates on the office network can open it too
python3 app.py --port 9000      # use a different port
python3 app.py --data ./data.json   # choose where the bookings file lives
```

With `--host 0.0.0.0` the server still prints `http://0.0.0.0:8000/`; teammates should
open `http://<the-host-machine's-IP>:8000/` instead.

One person runs it on a machine that stays on; everyone else just opens the URL.
The web page and the CLI read and write the same `data.json`, so they always agree.

## The three everyday jobs

**1. Check availability.** Open the page. Pick a date (today by default; the picker
allows today up to 60 days ahead) and optionally a room. You get a grid of 30-minute slots per room:
green = free, red = booked. Hover a red slot to see who booked it and the title.
The "Bookings for the day" table below lists the day's bookings.

**2. Book a room.** Click a green slot — the form opens pre-filled with that room,
date, start time and an end time one slot later (both can be changed). Add your name
(remembered for next time) and a short title, press **Book** or Enter.
If the slot is taken you get a clear message, e.g.
`Conflict: Aspen is already booked 09:00-10:00 on 2025-01-20 by Ann ('Standup').`

**3. Cancel a booking.** Find it in the "Bookings for the day" table — or in the
**Upcoming bookings** table, which lists everything from today onwards so you can
cancel a booking for next week without changing the date — and press **Cancel**. The slot turns green
immediately and can be booked again.

Past days can be viewed (read-only, marked as such) to see what happened, but not
booked — the date picker does not offer them, and the server rejects them anyway.
A title is optional; a name is required. Cancelling asks for confirmation first.

From the terminal:

```bash
python3 cli.py list --date 2025-01-20 --room aspen
python3 cli.py book --room aspen --date 2025-01-20 --start 09:00 --end 10:00 --booker "Ann" --title "Standup"
python3 cli.py cancel --id 3
```

## Rules currently in force (your defaults)

- Rooms: Aspen (4 people), Birch (6), Cedar (10), Dune (20)
- Working hours 08:00–18:00, 30-minute slots, max 4 hours per booking
- Book up to 60 days ahead, no past dates
- Booker is a free-text name — no login
- Anyone may cancel any booking

Rooms, hours, slot size, max length and horizon are constants at the top of `app.py`;
"anyone may cancel" and "no login" are how the app is built (there are no user
accounts). Tell me what to change and I will adjust them.

## Verified

`python3 selftest.py` passes all 53 checks (I ran it: 53 PASS, 0 failures), including:
overlap rejected with the conflicting booking named, adjacent and other-room bookings
allowed, cancel frees the slot with no stale record, double-cancel rejected, parallel
identical booking requests producing exactly one booking, user text escaped in the
page, and correct pre-filled end times.

An independent QA pass found 11 issues (script injection in the grid, wrong
pre-filled end time, UTC date bug, no upcoming-bookings view, and others); all 11
were fixed and the test suite was extended to cover them.

**Not verified:** the browser page has not been clicked through in a real browser —
its behaviour was checked by reading the code and by tests that mirror its logic.
Please try one booking and one cancellation when you first open it.
