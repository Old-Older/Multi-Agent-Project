# QA Report — Meeting Room Booking App

**Verdict: PASS**

Tested independently, black-box, from a user's perspective. `app.py` was **not modified**.
All 65 of my own API/behaviour checks passed, the shipped `test_app.py` passes (8/8), and
every claim in `README.md` that I could verify matched the code's actual behaviour.

- App under test: `app.py` (run as `python3 app.py`, default port 8000, `PORT` / `BOOKING_DB` honoured)
- Shipped tests: `python3 test_app.py` → `Ran 8 tests ... OK`
- My probe scripts: `qa_probe.py` (65 checks), `qa_static.py` (UI/README static checks),
  `qa_readme.py` / `qa_readme2.py` (README claims, default port, persistence)

---

## Problems found

**No blocking or functional defects were found.** The numbered list below contains only
minor, non-blocking observations (cosmetic / hardening / documentation nits). None of them
affects the requirements REQ1–REQ4.

1. **No browser automation was available in the QA environment** (`playwright`, `selenium`,
   `pyppeteer` all missing), so the single-page UI was verified by static analysis plus the
   API it calls, not by clicking in a real browser. *Where:* test environment, not the app.
   *What to change:* nothing in the app; the lead should do one manual click-through
   (date picker → click a green cell → Book → Cancel) before showing the requester.
2. **Room names are not HTML-escaped in the grid** (`renderGrid()` uses `${room.room}` raw,
   while booker/title correctly go through `esc()`). *Where:* `app.py`, `PAGE` JS,
   `renderGrid()`. *What to change:* use `esc(room.room)` for consistency. Not exploitable
   today because room names are fixed server-side seeds, so this is hardening only.
3. **The "past" styling is client-clock based.** `renderGrid()` greys out slots with
   `slot.start < nowHHMM()` using the browser's clock, while the server rejects with its own
   clock. *Where:* `app.py`, `renderGrid()`. *What to change:* none required; if a user's
   clock is skewed they may see a slot as free that the server rejects — the server's 400
   message is shown in the banner, so the user is not misled about the outcome.
4. **`room_id` given as a string is silently accepted** (`"1"` → 201) because of `int(...)`
   coercion. *Where:* `app.py`, `validate_booking()`. *What to change:* optional strictness;
   the README documents `room_id` as an integer, and the UI always sends a number.
5. **README does not mention that the server binds `0.0.0.0`** (all interfaces), only that it
   serves `http://localhost:8000`. *Where:* `README.md` "Run it" section vs `main()`.
   *What to change:* one sentence, e.g. "listens on all interfaces; use a firewall on shared
   networks". Cosmetic.
6. **README's `curl` example uses a hard-coded past date** (`2025-01-20`), which the server
   correctly rejects with 400 "cannot book in the past". *Where:* `README.md`, API section.
   *What to change:* use `$(date -d tomorrow +%F)` in the example (the availability example
   already does this). Documentation only — I re-ran the example with tomorrow's date and it
   returned `201` with the documented body shape.

---

## What was verified (all PASS)

### Double booking prevention
- Exact duplicate → `409`; partial overlap at the start (`10:30–11:30` vs `10:00–11:00`) → `409`;
  partial overlap at the end (`09:30–10:30`) → `409`; contained (`10:00–10:30`) → `409`;
  superset (`09:00–12:00`) → `409`.
- Adjacent bookings (`09:00–10:00` and `11:00–12:00` around a `10:00–11:00` booking) → `201`.
- Same time in a different room → `201`.
- **Concurrency:** 20 simultaneous identical POSTs → exactly one `201`, nineteen `409`.
  8 simultaneous *overlapping but different* ranges → exactly one `201`, and the day's
  booking list contains no two overlapping active bookings. Overlap check runs inside
  `BEGIN IMMEDIATE` and a partial unique index `ux_active_slot` backs it up at storage level.
- `409` message names the clashing room, time range, date and booker.

### Cancellation
- `POST /api/bookings/{id}/cancel` → `200`, status becomes `cancelled`.
- Availability for that date shows the slot **free immediately** on the very next GET.
- The freed slot can be re-booked straight away (`201`).
- Cancelling twice → `409`; unknown id → `404`; non-numeric id → `404`.
- Cancelled bookings are kept and still listed (struck through in the UI), and never block.

### Availability accuracy
- 20 slots per room, `08:00` … `17:30`, 30-minute steps, 4 rooms.
- Busy slots exactly match the booked ranges (`09:00–12:00` → six busy slots), other rooms
  unaffected, `free_count` correct (14 of 20 after a 3-hour booking).
- Empty day → all free, `free_count` 20, empty booking list.

### Input validation (all rejected with `400` + a readable message)
Past date; a slot that has already started today (while a future slot today is accepted);
5-hour and 4h30 bookings (exactly 4h is accepted); end before start; zero length; before
08:00; after 18:00; off-grid `09:15`; `9am`; `25:00`; missing / empty / whitespace-only
booker; missing `booker` key; unknown room; `2025/01/01`; impossible date `2025-02-30`;
malformed JSON body; bad/missing `date` on both GET endpoints. Unknown path → `404`.

### Single-page UI vs README
- `GET /` serves the page; all elements the JS references exist (`date`, `grid`, `form`,
  `room`, `start`, `end`, `booker`, `title`, `today`, `next`, `list`, `msg`); JS braces and
  brackets balance; no external CDN.
- README claims confirmed in code: green/red/grey legend, capacity + free-slot count per room
  row, click-a-green-cell prefills room/start with end 1 hour later, Today / Next-day buttons,
  Cancel with a confirm dialog, cancelled rows struck through, 409 naming the clash,
  `BEGIN IMMEDIATE` + partial unique index, max 4h, no past bookings, booker required,
  `PORT` / `BOOKING_DB` env vars, `/health`.
- README API table matches the implemented routes (`/api/rooms`, `/api/availability`,
  `/api/bookings`, `/api/bookings/{id}/cancel`, `/health`).
- Default run with no env vars: reachable on port 8000, `bookings.db` created next to
  `app.py`, data persists across a restart (README: "delete the file to start from scratch").

---

## Requirements check (my part)

- **REQ1 usable system** — met: runs with `python3 app.py`, no dependencies, UI + API work.
- **REQ2 easy to check availability** — met: day grid, per-room free counts, date picker.
- **REQ3 easy to book** — met: click a free cell, form prefilled, clear success/error banner.
- **REQ4 easy to cancel** — met: Cancel button per booking, slot freed immediately.
- **REQ5 / REQ6 / REQ7** — outside my task (lead's responsibility); README covers usage (REQ6).

## Recommendation
Ship it. Do one manual browser click-through (item 1) and optionally fix items 2 and 6.
