# Documentation review — README.md, HOW_TO_USE.md, qa_report.md vs app.py / test_app.py

FAIL

Checked: README.md, HOW_TO_USE.md, qa_report.md against app.py (full read) and test_app.py (full read).
I re-ran `python3 test_app.py` myself: `Ran 8 tests ... OK` (8/8 pass) — that claim is confirmed.
I did NOT re-run the 65-check probe, the concurrency tests, or the browser UI checks, so those
qa_report.md claims are unverified by me (see items 9–12).

## Items that must be fixed

1. **qa_report.md, "Problems found" item 5 — already fixed, now wrong.** It says "README does not
   mention that the server binds `0.0.0.0`". README.md "Run it" now says: "The server listens on all
   interfaces (`0.0.0.0`), so colleagues on the same network can use `http://<your-machine>:8000` —
   put it behind a firewall on untrusted networks." That matches `main()`:
   `ThreadingHTTPServer(("0.0.0.0", PORT), Handler)`. Change: delete item 5 (or mark it resolved).

2. **qa_report.md, "Problems found" item 6 — already fixed, now wrong.** It says the README `curl`
   example uses a hard-coded past date `2025-01-20`. README.md's example now uses
   `$(date -d tomorrow +%F)` for both the availability and the POST call. Change: delete item 6
   (or mark it resolved).

3. **qa_report.md, "Recommendation" — stale.** "optionally fix items 2 and 6" refers to item 6,
   which no longer exists in the README. Change: drop the reference to item 6.

4. **qa_report.md, "Problems found" item 2 — wrong location/description.** It says
   `renderGrid()` uses `${room.room}` raw "while booker/title correctly go through `esc()`".
   In app.py the room name is interpolated in `renderGrid()` (`${room.room}`) **and** in
   `renderList()` (`<td>${b.room}</td>`), and `fillSelects()` also injects `${r.name}` raw.
   Change: say the room name is unescaped in `renderGrid()`, `renderList()` and `fillSelects()`
   (three places), not just `renderGrid()`.

5. **qa_report.md, "Single-page UI vs README" — claim not supported by the code.** It says
   "all elements the JS references exist (`date`, `grid`, `form`, `room`, `start`, `end`, `booker`,
   `title`, `today`, `next`, `list`, `msg`)". The JS also references `listdate`, `listempty`,
   `submit` and `formhint` (in `renderList()`, the submit handler and the form markup). They do
   exist in `PAGE`, but the list is incomplete. Change: add `listdate`, `listempty`, `submit`,
   `formhint` — or say "all elements the JS references exist" without an incomplete list.

6. **qa_report.md, "Input validation" — claim not supported by the code.** It lists "missing
   `booker` key" as rejected with `400`. In `validate_booking()` a missing `booker` key yields
   `booker = ""` and is rejected by the `if not booker` branch with `400 "booker name is required"`
   — same status, but it is not a separate check, and the report presents it as one of the
   enumerated validation cases. Change: fold it into "missing / empty / whitespace-only booker".

7. **qa_report.md, "Input validation" — claim not supported by the code.** It lists "bad/missing
   `date` on both GET endpoints" → `400`. That is true for `/api/availability` and
   `/api/bookings` (both call `parse_date`), but the report also lists "Unknown path → `404`"
   in the same bullet; `do_GET`/`do_POST` return `404 {"error":"not found"}` for unknown paths —
   correct, but note that a **non-numeric** cancel id (e.g. `/api/bookings/abc/cancel`) does not
   match the `^/api/bookings/(\d+)/cancel$` regex and returns `404 "not found"`, not a
   booking-specific error. The report's "non-numeric id → `404`" is right; keep it, but state it
   is the generic 404. Change: clarify, or drop the claim if it was not actually exercised.

8. **qa_report.md, "Availability accuracy" — "20 slots per room, `08:00` … `17:30`" is right, but
   the report never states the slot `end` of the last slot.** `api_availability()` returns
   `end = hhmm(minutes(s) + SLOT_MINUTES)`, so the last slot is `17:30–18:00`. Not an error, but
   the README/HOW_TO_USE say "08:00 to 18:00" while the grid columns are start times 08:00–17:30;
   add one clarifying sentence to README.md "How to use it" step 1 and HOW_TO_USE.md step 1:
   "columns are slot start times, 08:00–17:30, each 30 minutes (the last slot ends 18:00)".

9. **qa_report.md, "Concurrency" — not established by my testing.** "20 simultaneous identical
   POSTs → exactly one `201`, nineteen `409`" and "8 simultaneous overlapping ranges → exactly one
   `201`" are plausible given `BEGIN IMMEDIATE` + `ux_active_slot`, and HOW_TO_USE.md repeats
   "(verified with 20 concurrent requests)", but I did not reproduce them. Change: either keep and
   label as "verified by qa_probe.py (not re-run in this review)", or re-run before shipping.

10. **qa_report.md, "Single-page UI vs README" — not established by my testing.** The UI was
    verified statically only (item 1 of the report admits no browser automation). Claims such as
    "click-a-green-cell prefills room/start with end 1 hour later", "Cancel with a confirm dialog",
    "cancelled rows struck through" are consistent with the code I read
    (`slots[Math.min(i + 2, slots.length - 1)]`, `confirm('Cancel this booking?')`,
    `tr.cancelled td { text-decoration:line-through; }`) but were not exercised in a browser.
    Change: keep the manual click-through recommendation and do not present these as tested.

11. **qa_report.md, "Default run with no env vars: reachable on port 8000, `bookings.db` created
    next to `app.py`, data persists across a restart" — not established by my testing.** The code
    supports it (`DB_PATH` default = `dirname(abspath(__file__))/bookings.db`, `PORT` default
    `"8000"`, `init_db()` uses `CREATE TABLE IF NOT EXISTS`), but I did not run it. Change: label
    as verified by qa_readme.py, or re-run.

12. **qa_report.md, "All 65 of my own API/behaviour checks passed" and "every claim in `README.md`
    that I could verify matched" — not established by my testing.** I did not run `qa_probe.py`
    (it is not in this workspace). Change: keep only if the probe scripts are shipped alongside,
    otherwise soften to "the checks listed below".

13. **qa_report.md, "Problems found" item 4 — wrong location.** It says `room_id` string coercion
    happens in `validate_booking()`. It does (`int(payload.get("room_id"))`), but the same
    coercion also accepts `true`/`1.0`-style values and floats like `1.9` → `1` (int() truncates),
    so `room_id: 1.9` books room 1. Change: mention the float truncation, or drop the item.

14. **HOW_TO_USE.md, "Files" table — `qa_report.md` described as "Independent QA report (PASS, 65
    black-box checks)".** The 65 checks are not reproducible from the shipped files (no
    `qa_probe.py` in the delivered set) and I did not re-run them. Change: "Independent QA report
    (PASS; see the report for the checks run)" or ship the probe scripts.

15. **HOW_TO_USE.md, "Rules the server enforces" — missing two rules the server actually enforces.**
    `validate_booking()` also rejects booker names longer than 80 characters and titles longer than
    120 characters (`400`). README.md "Rules enforced by the server" omits them too. Change: add
    "Booker name ≤ 80 characters, title ≤ 120 characters" to both files (the UI inputs already
    carry `maxlength="80"` / `maxlength="120"`).

16. **HOW_TO_USE.md, "Rules the server enforces" — "No bookings in the past" is imprecise.**
    `validate_booking()` rejects `day < today` **and** `day == today and start <= now`, i.e. a slot
    that has already started today. README.md states this correctly ("a slot that has already
    started today is rejected"); HOW_TO_USE.md does not. Change: add the same parenthetical.

17. **HOW_TO_USE.md, "How to use it" step 1 — "grey = past".** The page legend and README say
    "grey = past / closed" (`td.slot.past`, legend text "past / closed"). Change: "grey = past /
    closed" for consistency.

18. **HOW_TO_USE.md, "How to use it" step 2 — the quoted clash message is not the server's text.**
    It quotes `"Aurora is already booked 09:00–10:00 by Sam (Sync)"`. The server builds
    `"%s is already booked %s-%s on %s by %s%s. Please pick another slot."` — i.e. it includes the
    date and a trailing sentence, and uses a plain hyphen, not an en dash. Change: quote it as
    `Aurora is already booked 09:00-10:00 on 2025-01-21 by Sam (Sync). Please pick another slot.`
    or say "a message naming the room, time range, date and booker".

19. **HOW_TO_USE.md, "Start it" — "Colleagues on the same network can use
    `http://<your-machine>:8000`" without the firewall caveat.** README.md adds "put it behind a
    firewall on untrusted networks". Change: add the same caveat (the app has no login and anyone
    who can reach it can cancel any booking).

20. **README.md, "API" table — `POST /api/bookings` status codes incomplete.** The server also
    returns `409` from the `sqlite3.IntegrityError` path ("That slot was just booked by someone
    else…") and `500` on unexpected errors; `400` covers unknown `room_id`, bad JSON, bad date/time,
    missing booker, >4h, past. Change: add "`409` also on a lost race; `500` on internal error".

21. **README.md, "API" table — `GET /api/availability` response shape incomplete.** The actual body
    is `{"date":…, "slots":[start times…], "rooms":[{room_id, room, capacity, slots:[{start,end,status}], free_count}]}`.
    The table only mentions `slots` and `free_count` per room. Change: document `date`, the
    top-level `slots` list, `room_id`, `room` and `capacity`.

22. **README.md, "API" table — `GET /api/bookings` field list omits nothing but the wrapper.**
    The body is `{"date":…, "bookings":[…]}`; the table lists only the per-booking fields. Change:
    mention the `{"date","bookings"}` wrapper.

23. **README.md, "Run the tests" — "starts its own server on a free port with a temporary
    database … It does not touch your `bookings.db`."** Correct (`free_port()`, `tempfile.mkdtemp()`,
    `BOOKING_DB`), confirmed by my run. No change needed — listed only to record that it was checked.

24. **README.md, "How to use it" step 3 — "press **Cancel** next to a booking and confirm".**
    Correct (`confirm('Cancel this booking?')`), but the button only appears on **active** rows;
    cancelled rows show a `cancelled` pill and no button. Change: add "the Cancel button only
    appears on active bookings".

25. **README.md, "How to use it" step 1 — "green = free, red = booked, grey = past/closed".**
    Correct, but a slot that is both busy and in the past renders as **red** (`cls` prefers
    `busy`), so "grey = past" is only true for free past slots. Change: "grey = past/closed (free
    slots only; a past slot that was booked stays red)".

26. **README.md, "Rules enforced by the server" — "single bookings only".** True (no recurrence
    field in the schema), but the phrase is ambiguous next to "Maximum 4 hours per booking".
    Change: "one-off bookings only (no recurring bookings)".

27. **README.md, "Run it" — "The SQLite database `bookings.db` is created next to `app.py` on first
    start and seeded with the four default rooms."** Correct (`DB_PATH` default, `init_db()` seeds
    only when `rooms` is empty). Note the seed only happens when the `rooms` table is empty, so
    deleting rows without deleting the file does not re-seed. Change: optional clarification.

28. **README.md, "Files" section — lists only `app.py`, `test_app.py`, `README.md`.** The delivered
    set also includes `HOW_TO_USE.md` and `qa_report.md`. Change: add both.

29. **README.md, "Run it" — `PORT=9000 python3 app.py` / `BOOKING_DB=/tmp/rooms.db python3 app.py`.**
    Correct (`PORT = int(os.environ.get("PORT", "8000"))`, `BOOKING_DB` honoured). No change.

30. **Cross-file: room names/capacities, hours, slot length, max length, port, run command, API
    paths and cancel status codes all agree** between README.md, HOW_TO_USE.md, app.py and
    test_app.py: Aurora (8), Birch (4), Cedar (12), Dune (20); 08:00–18:00; 30-minute slots;
    max 4 hours; port 8000; `python3 app.py`; `GET /api/rooms`, `GET /api/availability`,
    `GET /api/bookings`, `POST /api/bookings` (201/409/400), `POST /api/bookings/{id}/cancel`
    (200/404/409), `GET /health`. No change needed — recorded as checked.

## Requirements (my part)

- REQ1–REQ4: supported by the code and by the 8 shipped tests I re-ran; the docs describe them
  accurately apart from the items above.
- REQ5 (show the system) and REQ7 (consult the requester): not mine — the lead's; the human
  answered the questions with "Use all your defaults", which matches the seeded rooms/hours/rules.
- REQ6 (explain how to use it): met by README.md + HOW_TO_USE.md once items 8, 15–19 are fixed.
