# Meeting Room Booking — User Guide

A small command-line tool that replaces the shared spreadsheet. It keeps one
list of bookings, refuses double bookings, and frees a slot again when a
booking is cancelled.

## 1. Quick start (5 lines)

```
1. Install Python 3 (python.org) — nothing else needed.
2. Put booking.py in a folder, e.g. ~/booking/
3. Open a terminal in that folder:  cd ~/booking
4. Try it:  python booking.py demo
5. See the result:  python booking.py list
```

On Windows use `python` (or `py`); on macOS/Linux `python3` also works.
Every command below is written as `python booking.py ...` — use whichever
works on your machine.

## 2. The rooms

| Room     | Seats | Location | Equipment                         |
|----------|-------|----------|-----------------------------------|
| Aurora   | 4     | Floor 1  | TV, whiteboard                    |
| Borealis | 8     | Floor 1  | projector, whiteboard             |
| Cascade  | 12    | Floor 2  | projector, video call             |
| Delta    | 20    | Floor 2  | projector, video call, whiteboard |

Rooms can be booked **08:00–18:00** only. Times are 24-hour `HH:MM`, dates are
`YYYY-MM-DD` (e.g. `2025-06-02`). Room names are not case-sensitive.

## 3. The six commands

### `rooms` — what rooms exist?
```
python booking.py rooms
```
Prints the table above (name, seats, floor, equipment).

### `availability` — what is free?
```
python booking.py availability --date 2025-06-02
```
Shows, for every room, the free time spans and any bookings already made:
```
Aurora (4 seats): FREE 08:00-09:00, 10:00-18:00
    booked 09:00-10:00  Sprint review (#1, Ana)
```
Narrow it down with optional filters:
```
python booking.py availability --date 2025-06-02 --room Aurora
python booking.py availability --date 2025-06-02 --min-capacity 10
python booking.py availability --date 2025-06-02 --min-capacity 10 --start 09:00 --end 10:00
```
The last form adds a line like
`Rooms free for the whole 09:00-10:00 slot: Cascade, Delta` — the fastest way
to find a room for a specific meeting. `--start` and `--end` must be given
together (both or neither) and are checked before anything is printed, so a
bad time gives an error and no table. `--min-capacity` must be 1 or more.

### `book` — reserve a room
```
python booking.py book --room Aurora --date 2025-06-02 --start 09:00 --end 10:00 --by Ana --title "Sprint review"
```
Output: `Booked #1: #1   2025-06-02 09:00-10:00  Aurora    Sprint review  (booked by Ana)`
The number after `#` is the **booking id** — note it down, you need it to cancel.
`--title` is optional (defaults to `Meeting`); `--by` (your name) is required.
Only future slots can be booked — past dates/times are refused.

### `cancel` — give a room back
```
python booking.py cancel --id 1 --by Ana
```
Output: `Cancelled #1: ...` plus a reminder to check availability.
`--by` is **required** and must match the person who booked (case does not
matter); anyone else is refused.

### `list` — see bookings
```
python booking.py list                 # upcoming bookings (today onwards)
python booking.py list --date 2025-06-02
python booking.py list --by Ana
python booking.py list --all           # everything, cancelled ones marked [CANCELLED]
```
`list` and `list --date` show **only active bookings** — cancelled ones are
hidden unless you add `--all`. `list` without `--date` shows today onwards, so
past dates need `--date` or `--all`.

### `demo` — sample data to try things out
```
python booking.py demo
```
Adds three sample bookings for tomorrow (only if the data file is still empty;
otherwise it prints `Data file already has bookings; demo not added.`).

## 4. How double bookings are prevented

Before saving, `book` checks every active booking for the same room and date.
If the new time overlaps an existing one, the booking is **refused** and
nothing is written:
```
ERROR: double booking. Aurora is already booked 09:00-10:00 by Ana (#1, Sprint review).
Run: python booking.py availability --date 2025-06-02 --room Aurora
```
Back-to-back meetings are fine: 09:00–10:00 and 10:00–11:00 do not overlap.
The check runs inside a file lock, so two people booking at the same moment
cannot both succeed.

## 5. How cancellations free the slot

`cancel` does not delete the record — it marks it `cancelled`. Cancelled
bookings disappear from `availability` and from `list` / `list --date`, so the
slot can be booked again immediately (see the history with `list --all`).
Cancelling the same booking twice is refused.

## 6. Where the data lives

All bookings are in **`bookings.json`**, next to `booking.py`. It is plain
text; back it up by copying it. To use a different file (e.g. a shared drive
or a test copy), set the `BOOKING_FILE` environment variable:
```
BOOKING_FILE=/path/to/team-bookings.json python booking.py list
```
(Windows PowerShell: `$env:BOOKING_FILE="C:\path\bookings.json"; python booking.py list`)

## 7. Troubleshooting

| Message | What it means / what to do |
|---|---|
| `ERROR: invalid date '02/06/2025'. Use YYYY-MM-DD, e.g. 2025-06-02.` | Date format is wrong. Write year-month-day with dashes. |
| `ERROR: invalid time '9am'. Use 24h HH:MM, e.g. 09:30.` | Times need two digits and a colon: `09:00`, not `9am`. |
| `ERROR: unknown room 'Zephyr'. Known rooms: Aurora, Borealis, Cascade, Delta.` | Room name typo. Run `python booking.py rooms`. Case does not matter. |
| `ERROR: 2025-06-02 09:00 is in the past; book a future slot.` | Pick a date/time that has not happened yet. |
| `ERROR: booking #1 is already cancelled.` | Someone already cancelled it — nothing to do. Check with `list --all`. |
| `ERROR: booking #2 belongs to Ben, not Ana.` | `--by` must match the person who booked. Ask them to cancel it. |
| `ERROR: --by is required so we know who cancelled (booking #2 belongs to Ben).` | Add `--by "Your Name"` to `cancel`. |
| `ERROR: double booking. ...` | That room is taken at that time. Run the suggested `availability` command. |
| `ERROR: rooms can only be booked between 08:00 and 18:00.` | Pick a time inside opening hours. |
| `ERROR: end time must be after start time.` | Swap `--start` and `--end`. |
| `ERROR: give both --start and --end, or neither.` | `availability` needs both times, or neither. |
| `ERROR: --min-capacity must be 1 or more.` | Use a seat count of at least 1. |
| `ERROR: no booking with id 99.` | Wrong id — find it with `python booking.py list --all`. |
| `ERROR: data file ... is not valid JSON.` | `bookings.json` was edited by hand and broken. Restore a backup or remove the file (this deletes all bookings). |

Need the full option list? `python booking.py --help` or
`python booking.py book --help`.
