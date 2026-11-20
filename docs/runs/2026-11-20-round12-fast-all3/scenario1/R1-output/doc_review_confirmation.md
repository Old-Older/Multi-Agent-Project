# Confirmation of my own doc_review.md items against the revised files

FAIL

Scope: only my own numbered items from doc_review.md (1–30), checked against the revised
README.md, HOW_TO_USE.md, qa_report.md and the unchanged app.py / test_app.py.
I re-ran `python3 test_app.py`: `Ran 8 tests ... OK` (8/8). No new items raised.

## Item-by-item

1. **confirmed** — qa_report.md now has a status note saying items 5 and 6 were fixed in README.md and are kept only as history.
2. **confirmed** — qa_report.md item 2 now names `renderGrid()`, `renderList()` and `fillSelects()` (three places).
3. **not fixed** — qa_report.md "Recommendation" still says "optionally fix items 2 and 6"; item 6 is now marked as already fixed, so the reference is still stale.
4. **confirmed** — qa_report.md item 2 now names all three functions.
5. **not fixed** — qa_report.md "Single-page UI vs README" still lists only `date, grid, form, room, start, end, booker, title, today, next, list, msg`; `listdate`, `listempty`, `submit`, `formhint` are still missing.
6. **not fixed** — qa_report.md "Input validation" still lists "missing `booker` key" as a separate case instead of folding it into "missing / empty / whitespace-only booker".
7. **not fixed** — qa_report.md still lists "bad/missing `date` on both GET endpoints. Unknown path → `404`" without saying the non-numeric cancel id gets the generic `404 {"error":"not found"}`.
8. **not fixed** — neither README.md "How to use it" step 1 nor HOW_TO_USE.md step 1 says the columns are slot *start* times 08:00–17:30 with the last slot ending 18:00 (both still say "08:00 to 18:00").
9. **confirmed** — qa_report.md's status note labels the check counts and concurrency runs unverified; HOW_TO_USE.md no longer cites "verified with 20 concurrent requests" (it now says the 20-request run was done with an unshipped probe script and is unverified).
10. **confirmed** — qa_report.md's status note states the UI was checked by reading the code and calling its API, not by clicking in a browser; HOW_TO_USE.md "Known limits" says the page was not clicked in a real browser and asks for a click-through first.
11. **not fixed** — qa_report.md still asserts "Default run with no env vars: reachable on port 8000, `bookings.db` created next to `app.py`, data persists across a restart" as verified, with no label that it came from the unshipped `qa_readme.py`.
12. **confirmed** — the status note says the 65-check figure came from probe scripts not shipped with the app and is unverified, and that the shipped `test_app.py` (8 tests) is the reproducible evidence; HOW_TO_USE.md's Files table now says the same.
13. **not fixed** — qa_report.md item 4 still says only that `room_id` as a string is accepted; the float truncation (`room_id: 1.9` → room 1) is still not mentioned.
14. **confirmed** — HOW_TO_USE.md Files table now reads "Independent QA report (PASS). Its detailed check counts and concurrency runs came from probe scripts that are not shipped, so those figures are unverified here; the shipped `test_app.py` (8 tests) is the reproducible evidence."
15. **not fixed** — the booker ≤ 80 / title ≤ 120 character limits are still absent from both HOW_TO_USE.md "Rules the server enforces" and README.md "Rules enforced by the server".
16. **not fixed** — HOW_TO_USE.md still says only "No bookings in the past"; the "(a slot that has already started today is rejected)" parenthetical is still missing.
17. **not fixed** — HOW_TO_USE.md step 1 still says "grey = past"; it does not say "past / closed".
18. **not fixed** — HOW_TO_USE.md step 2 still quotes `"Aurora is already booked 09:00–10:00 by Sam (Sync)"` (en dash, no date, no trailing sentence) instead of the server's actual message.
19. **not fixed** — HOW_TO_USE.md "Start it" still gives `http://<your-machine>:8000` with no firewall / no-login caveat.
20. **not fixed** — README.md `POST /api/bookings` row still lists only `201` / `409` / `400`; the lost-race `409` and `500` are still not mentioned.
21. **not fixed** — README.md `GET /api/availability` row still documents only `slots` and `free_count`; `date`, the top-level `slots` list, `room_id`, `room` and `capacity` are still missing.
22. **not fixed** — README.md `GET /api/bookings` row still lists only the per-booking fields, not the `{"date","bookings"}` wrapper.
23. **confirmed** — README.md "Run the tests" still correctly describes the free port / temporary database, and my re-run (8/8 OK) confirms it.
24. **not fixed** — README.md step 3 still does not say the Cancel button only appears on active bookings.
25. **not fixed** — README.md step 1 still says "grey = past/closed" without the note that a past slot that was booked stays red.
26. **not fixed** — README.md "Rules enforced by the server" still says "single bookings only" rather than "one-off bookings only (no recurring bookings)".
27. **not fixed** — README.md "Run it" still does not say the seed only happens when the `rooms` table is empty (deleting rows without deleting the file does not re-seed). HOW_TO_USE.md does now say "rooms are only seeded when the table is empty" and "delete `bookings.db` to change them", so the reseed point is covered there but not in README.md.
28. **not fixed** — README.md "Files" still lists only `app.py`, `test_app.py`, `README.md`; `HOW_TO_USE.md` and `qa_report.md` are still missing.
29. **confirmed** — README.md still documents `PORT=9000` / `BOOKING_DB=/tmp/rooms.db` correctly (matches `app.py`).
30. **confirmed** — cross-file agreement still holds: Aurora (8), Birch (4), Cedar (12), Dune (20); 08:00–18:00; 30-minute slots; max 4 hours; port 8000; `python3 app.py`; the API paths and cancel status codes match app.py and test_app.py.

## Requirements (my part)

- REQ6 (explain how to use it): still not fully met — items 8, 15–19, 24–28 remain open in the docs.
- REQ1–REQ4: supported by the code and by the 8 shipped tests I re-ran.
- REQ5 (show the system) and REQ7 (consult the requester): not my part — the lead's.
