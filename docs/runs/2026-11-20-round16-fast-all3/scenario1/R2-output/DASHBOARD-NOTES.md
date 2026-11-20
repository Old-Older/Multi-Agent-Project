# Manager dashboard — status and known issues

The dashboard is implemented in `app.py` (page `GET /dashboard`, data `GET /api/dashboard?from=&to=`).
See `DASHBOARD.md` for the JSON keys and `README.md` / `HOW-TO-USE.md` for usage.

## Verified
- `python3 -m unittest -v test_app` — all tests pass. The final `test_app.py` contains 20 test
  functions (14 existing + 6 dashboard); the lead re-ran the whole suite and QA re-ran it in two
  batches, all OK.
- `/dashboard` and `/` return 200; invalid ranges (one of from/to missing, bad date, from > to,
  more than 366 days) return 400 JSON. Covered by `test_dashboard_invalid_ranges`.
- `from=&to=` (both empty) returns the default range (last 30 days) — intended behaviour, asserted by
  `test_dashboard_default_range_is_last_30_days`.
- The main page header links to `/dashboard` — asserted by `test_dashboard_page_served_and_linked`.

## Earlier QA findings — re-checked against the final app.py, all resolved
1. Utilisation is now computed and printed as a percentage.
2. The heavy/underused label compares the percentage with the 60 % / 20 % thresholds.
3. Busiest weekday/hour are stated in words and empty ranges show a "no bookings" message.
4. Numeric summaries are shown next to the weekday/hour charts.
5. The header link to `/dashboard` is present.
6. `from=&to=` returning the default range is documented behaviour, not a defect.
7. Small hours/rates are rounded to 1 decimal — a display nit only, no wrong figure.

## Not verified
- The page's JavaScript was inspected as text, not executed in a real browser: chart rendering and
  the preset buttons have not been seen working in a browser.
- No server log is committed, so "no 500s" rests on the test runs above, not on a log.
- `DASHBOARD.md` says "20 tests" (correct) but "5 new dashboard tests" (the suite has 6 dashboard tests).
