# Meeting Room Booking System

Replaces the shared spreadsheet. One source of truth for bookings, **double
bookings are refused**, and a **cancelled booking frees its slot immediately**.

- `booking.py` — the whole system (Python 3, standard library only, no install)
- `dashboard.py` — manager dashboard: charts and summaries for a date range
- `USER_GUIDE.md` — step-by-step guide for the team
- `tests/test_booking.py` — automated tests (run `python tests/test_booking.py`)

## What it does

| Problem with the spreadsheet | What the system does |
|---|---|
| Two people book the same room/time | `book` checks every active booking for that room and day and **refuses** an overlap (back-to-back 09:00–10:00 / 10:00–11:00 is allowed). On macOS/Linux the check runs inside a file lock, so two people booking at the same second cannot both win; on Windows the lock is skipped (see Known limits). |
| Records not updated after a cancellation | `cancel` marks the booking cancelled; it disappears from availability and from the normal list, so the slot is bookable again at once. History stays visible with `list --all`. |
| "Is anything free?" means scrolling a sheet | `availability --date` prints free time spans per room, plus a one-line answer for a specific slot. |
| "Which rooms are over- or under-used?" | `dashboard.py` charts bookings, reserved hours, utilisation, busiest days/times and cancellations for any date range. |

## Quick start

Dates must be today or later. Run these in order in the folder that holds `booking.py`:

```bash
python booking.py demo                       # 3 sample bookings for tomorrow
python booking.py list                       # see them
python booking.py cancel --id 1 --by Ana     # free the first one again
```

## Manager dashboard

```bash
python dashboard.py                          # opens http://127.0.0.1:8765/ in your browser
python dashboard.py --port 9000 --no-browser # pick a port / don't open a browser
python dashboard.py --text --from 2025-01-01 --to 2025-01-31   # same numbers, plain text
```

The page reads the same `bookings.json` (or `BOOKING_FILE`) as `booking.py` and
never writes to it. Pick a date range (or use Last 7/30/90 days, All time),
optionally one room, and press **Show**; charts and the summary table update
without reloading the page. **Refresh data** re-reads the file after new
bookings. It shows:

- **Bookings per room** and **hours reserved per room**, plus **utilisation %**
  (reserved hours ÷ days in range × 10 bookable hours).
- **Busiest days**: bookings per weekday, the top 5 busiest dates, and the
  busiest weekday.
- **Busiest times**: bookings per start hour and a weekday × hour heatmap.
- **Cancellations**: cancelled bookings dated in the range, cancellation rate
  (cancelled ÷ active + cancelled), cancelled per room, top rooms by rate.
- **Summary table** (one row per room) and a **"What this suggests"** block that
  flags rooms at 70%+ utilisation as heavily used, below 25% as underused, and
  rooms with no bookings at all.

`--text` prints the same figures for a terminal or a report. `python check_dashboard.py`
re-runs the self-check (temporary data file, text output, HTTP page and JSON API).

## Example session (real output)

```
$ python booking.py book --room Aurora --date 2030-06-03 --start 09:00 --end 10:00 --by Ana --title "Sprint review"
Booked #4: #4   2030-06-03 09:00-10:00  Aurora    Sprint review  (booked by Ana)

$ python booking.py book --room Aurora --date 2030-06-03 --start 09:30 --end 10:30 --by Dana
ERROR: double booking. Aurora is already booked 09:00-10:00 by Ana (#4, Sprint review).
Run: python booking.py availability --date 2030-06-03 --room Aurora

$ python booking.py availability --date 2030-06-03 --start 09:00 --end 10:00
Availability on Monday 03 June 2030 (rooms open 08:00-18:00)

Aurora (4 seats): FREE 08:00-09:00, 10:00-18:00
    booked 09:00-10:00  Sprint review (#4, Ana)
Borealis (8 seats): FREE 08:00-18:00
Cascade (12 seats): FREE 08:00-18:00
Delta (20 seats): FREE 08:00-18:00

Rooms free for the whole 09:00-10:00 slot: Borealis, Cascade, Delta
```

## Commands

| Command | Purpose |
|---|---|
| `rooms` | list rooms, seats, floor, equipment |
| `availability --date D [--room R] [--min-capacity N] [--start HH:MM --end HH:MM]` | free slots per room; with `--start/--end` (both or neither), which rooms fit the whole slot (`... slot: none` if none do). `--min-capacity` must be ≥ 1 |
| `book --room R --date D --start HH:MM --end HH:MM --by NAME [--title T]` | book; prints the booking id. `--title` defaults to `Meeting`; a slot that has already started is refused |
| `cancel --id N --by NAME` | cancel (name must match the booker) |
| `list [--date D] [--by NAME] [--all]` | upcoming / by day / by person; cancelled bookings are hidden unless you add `--all` |
| `demo` | sample data on an empty data file |
| `dashboard.py [--port N] [--no-browser] [--file F]` | manager dashboard web page |
| `dashboard.py --text [--from D] [--to D] [--room R]` | same figures as plain text |

## Tests

```bash
python tests/test_booking.py
python check_dashboard.py
```

The tests run `booking.py` against a temporary `BOOKING_FILE`, so they never
touch your real `bookings.json`.

## Known limits

- Command line only for booking (no web UI) — deliberately, so it runs anywhere with Python 3. The dashboard is a local read-only web page.
- File locking uses `fcntl` (macOS/Linux). On Windows the code skips locking
  (untested there), so simultaneous bookings from two machines on a shared
  drive are not protected.
- No login: `--by` is a name, not authentication. Anyone can book under any name.
- The dashboard has no login either; it listens on 127.0.0.1 only, so it is for
  the manager's own machine.
