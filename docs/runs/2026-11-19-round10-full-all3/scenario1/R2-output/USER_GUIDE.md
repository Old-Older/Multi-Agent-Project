# Meeting Room Booking — User Guide

A small command-line tool that replaces the shared spreadsheet: one list of
bookings, no double bookings, and a cancelled booking frees its slot at once.
A separate dashboard (`dashboard.py`) shows the manager how the rooms are used.

## 1. Quick start (5 lines)

```
1. Install Python 3 (python.org) — nothing else needed.
2. Put booking.py and dashboard.py in a folder, e.g. ~/booking.
3. Open a terminal in that folder:  cd ~/booking
4. Try it:  python booking.py demo
5. See the result:  python booking.py list
```

On Windows use `python` (or `py`); on macOS/Linux `python3` also works.

## 2. Rooms and times

Four rooms: **Aurora** (4 seats, Floor 1), **Borealis** (8, Floor 1),
**Cascade** (12, Floor 2), **Delta** (20, Floor 2); `python booking.py rooms`
shows equipment. Bookable **08:00-18:00** only. Times are 24-hour `HH:MM`,
dates `YYYY-MM-DD` (e.g. `2030-06-03`). Room names are not case-sensitive.

## 3. The six commands

### `rooms` — what rooms exist?
`python booking.py rooms` prints the room table (name, seats, floor, equipment).

### `availability` — what is free?
`python booking.py availability --date 2030-06-03` shows each room's free time
spans and existing bookings. Example output when Aurora already has a
09:00-10:00 booking:
```
Aurora (4 seats): FREE 08:00-09:00, 10:00-18:00
    booked 09:00-10:00  Sprint review (#4, Ana)
```
Optional filters:
```
python booking.py availability --date 2030-06-03 --room Aurora
python booking.py availability --date 2030-06-03 --min-capacity 10
python booking.py availability --date 2030-06-03 --min-capacity 10 --start 09:00 --end 10:00
```
The last form adds a line like
`Rooms free for the whole 09:00-10:00 slot: Cascade, Delta` (or `... slot: none`)
— the fastest way to find a room for a meeting. `--start` and `--end` must be
given together and are checked before anything is printed; `--min-capacity`
must be 1 or more.

### `book` — reserve a room
```
python booking.py book --room Aurora --date 2030-06-03 --start 09:00 --end 10:00 --by Ana --title "Sprint review"
```
Output: `Booked #4: #4   2030-06-03 09:00-10:00  Aurora    Sprint review  (booked by Ana)`
The number after `#` is the **booking id** — note it down, you need it to cancel.
`--title` is optional (defaults to `Meeting`); `--by` (your name) is required.
A slot that has already started is refused; later slots today are fine.

### `cancel` — give a room back
`python booking.py cancel --id 1 --by Ana` prints:
```
Cancelled #1: #1   2026-11-20 09:00-10:00  Aurora    Daily stand-up  (booked by Ana)
The slot is free again - check with: python booking.py availability --date 2026-11-20
```
`--by` is **required** and must match the person who booked (case does not
matter); anyone else is refused.

### `list` — see bookings
```
python booking.py list                 # upcoming (today onwards)
python booking.py list --date 2030-06-03
python booking.py list --by Ana
python booking.py list --all           # includes cancelled, marked [CANCELLED]
```
`list` and `list --date` show **only active bookings** — cancelled ones are
hidden unless you add `--all`. `list` without `--date` shows today onwards;
an empty day prints `Bookings on <date>: none.`

### `demo` — sample data to try things out
`python booking.py demo` prints `Added 3 sample bookings for <tomorrow>.` (only
on an empty data file; otherwise `Data file already has bookings; demo not added.`).

## 4. How double bookings are prevented

Before saving, `book` checks every active booking for the same room and date.
If the new time overlaps an existing one, the booking is **refused** and
nothing is written:
```
ERROR: double booking. Aurora is already booked 09:00-10:00 by Ana (#4, Sprint review).
Run: python booking.py availability --date 2030-06-03 --room Aurora
```
Back-to-back meetings are fine: 09:00-10:00 and 10:00-11:00 do not overlap.
On macOS/Linux the check runs inside a file lock, so two people booking at the
same moment cannot both succeed; on Windows the lock is skipped (see README,
Known limits).

## 5. How cancellations free the slot

`cancel` does not delete the record — it marks it `cancelled`. Cancelled
bookings disappear from `availability` and from `list` / `list --date`, so the
slot can be booked again immediately (history stays in `list --all`).
Cancelling the same booking twice is refused.

## 6. Manager dashboard

```
python dashboard.py            # opens http://127.0.0.1:8765/ in your browser
python dashboard.py --text --from 2025-01-01 --to 2025-01-31
```
Pick a date range (or Last 7/30/90 days, All time) and optionally a room, then
press **Show**. The page shows bookings per room, hours reserved and
utilisation % per room, busiest weekdays and dates, busiest start hours with a
weekday × hour heatmap, cancellations and cancellation rate per room, a summary
table, and a "What this suggests" block that flags heavily used (70%+) and
underused (below 25%) rooms. **Refresh data** re-reads `bookings.json` after new
bookings. The dashboard only reads the data; it never changes bookings.

## 7. Where the data lives

All bookings are in **`bookings.json`**, next to `booking.py`; back it up by
copying it. While a command runs, a small `bookings.json.lock` file sits next
to it — leave it alone, it is not data. To use a different file (e.g. a shared
drive), set `BOOKING_FILE`:
`BOOKING_FILE=/path/to/team-bookings.json python booking.py list`
(the dashboard reads the same variable, or use `--file`).

## 8. Troubleshooting

| Message | What it means / what to do |
|---|---|
| `ERROR: invalid date ...` / `ERROR: invalid time ...` | Wrong format. Dates are `YYYY-MM-DD`; times are `09:00`, not `9am`. |
| `ERROR: unknown room 'Zephyr'. Known rooms: ...` | Room name typo. Run `python booking.py rooms`. Case does not matter. |
| `ERROR: <date> <time> is in the past; book a future slot.` | That slot has already started. Pick a later time. |
| `ERROR: double booking. ...` | That room is taken at that time. Run the suggested `availability` command. |
| `ERROR: rooms can only be booked between 08:00 and 18:00.` / `ERROR: end time must be after start time.` | Pick a time inside opening hours, with the end after the start. |
| `ERROR: give both --start and --end, or neither.` / `ERROR: --min-capacity must be 1 or more.` | `availability` needs both times or neither; seat count must be at least 1. |
| `No room seats 50 or more.` | No room is that big — lower `--min-capacity`. |
| `ERROR: booking #1 is already cancelled.` | Someone already cancelled it — nothing to do. Check with `list --all`. |
| `ERROR: booking #2 belongs to Ben, not Ana.` | `--by` must match the person who booked. Ask them to cancel it. |
| `booking.py cancel: error: the following arguments are required: --by` | You left out `--by`. Add `--by "Your Name"`. |
| `ERROR: no booking with id 99.` | Wrong id — find it with `python booking.py list --all`. |
| `ERROR: data file ... is not valid JSON.` | `bookings.json` was edited by hand and broken. Restore a backup or remove the file (this deletes all bookings). |
| Dashboard: `The start date must be on or before the end date.` | Swap the two dates. |
| Dashboard: `Address already in use` | Another dashboard is running; use `--port 9000`. |

Full option list: `python booking.py --help`, `python dashboard.py --help`.
