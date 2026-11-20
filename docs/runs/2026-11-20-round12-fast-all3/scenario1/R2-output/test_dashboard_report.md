# test_dashboard.py — independent test suite for GET /api/dashboard

**Verdict: FAIL (endpoint not implemented yet — expected at this stage)**

- File written: `test_dashboard.py` (workspace root; loads `app.py` from the same
  directory or from `inbox/app.py`). `app.py` was **not** modified.
- Framework: `unittest`, standard library only, `tempfile` DB per test
  (`app.DB_PATH` is pointed at a fresh temp DB and restored in `tearDown`).
- Tests: **26** — 23 call `app.api_dashboard(query)` directly, 3 go over HTTP
  (`ThreadingHTTPServer` on port 0 in a daemon thread, `urllib` client).
- Result against the current `inbox/app.py`: **0 passed, 26 failed**.

## Why everything fails

`app.py` has no `api_dashboard` function and `Handler.do_GET` has no
`/api/dashboard` route. Every direct-call test fails with
`AssertionError: app.api_dashboard does not exist yet (endpoint not implemented)`;
every HTTP test gets `404` instead of `200`/`400`
(`GET /api/dashboard?... -> 404`, body `{"error": "not found"}`).
The suite is written so that it starts passing as soon as the endpoint lands —
no test needs editing.

## Coverage (SPEC item -> test)

| SPEC item | Test(s) |
|---|---|
| (1) empty DB -> zeros, no crash | `TestEmptyDatabase.test_empty_db_returns_zeros_and_does_not_crash`, `test_single_day_range` |
| (2) known fixture exact values | `TestKnownFixture.test_room_totals_exact`, `test_totals_exact`, `test_share_sums_to_one` |
| (3) range filtering | `TestRangeFiltering.test_only_in_range_bookings_counted`, `test_cancelled_counted_by_booking_date` |
| (4) by_hour overlap (09:30-11:00 -> hours 9 and 10) | `TestByHourOverlap.test_booking_spanning_two_hours_counts_in_both`, `test_hourly_hours_sum_to_total_hours` |
| (5) by_weekday / by_date sums == totals | `TestWeekdayAndDateSums.test_weekday_sums_equal_totals`, `test_by_date_sums_equal_totals` |
| (6) busiest weekday/hour/date + tie -> earliest | `TestBusiest.test_busiest_weekday_and_hour`, `test_busiest_tie_breaks_to_earliest` |
| (7) suggestions underused / heavily used / high_cancellations | `TestSuggestions.test_underused_and_heavily_used_suggestions`, `test_high_cancellations_suggestion`, `test_no_suggestions_when_all_rooms_moderate` |
| (8) validation 400s | `TestValidation` (missing start, missing end, missing both, bad format, impossible date, reversed, span > 366, span == 366 allowed) |
| (9) HTTP 200 + JSON keys | `TestHttpEndpoint.test_http_dashboard_200_and_keys`, `test_http_dashboard_400_on_bad_range`, `test_http_dashboard_400_on_missing_params` |

## Exact expected values used (so failures are unambiguous)

Fixture A (`TestKnownFixture`, range 2024-03-04..2024-03-10, 7 days, 4 rooms,
capacity_hours = 7*10*4 = 280):

| room | bookings | cancelled | hours | cancel_rate | utilisation | share | status |
|---|---|---|---|---|---|---|---|
| Aurora | 3 | 1 | 4 | 0.25 | 4/70 ≈ 0.057143 | 4/6 ≈ 0.666667 | moderate |
| Birch | 1 | 0 | 2 | 0 | 2/70 ≈ 0.028571 | 2/6 ≈ 0.333333 | underused |
| Cedar | 0 | 0 | 0 | 0 | 0 | 0 | underused |
| Dune | 0 | 0 | 0 | 0 | 0 | 0 | underused |
| **totals** | 4 | 1 | 6 | 0.2 | 6/280 ≈ 0.021429 | — | — |

Other fixed expectations: `days` = 30 for 2024-03-01..2024-03-30; `by_hour`
has 10 entries with `hour` 8..17 and first `label` "08:00"; `by_weekday` has 7
entries with `weekday` 0..6 and labels Mon..Sun; `by_date` has one entry per day
in range; busiest for the fixture above = weekday 0, hour 9, date 2024-03-04;
tie case (Tue 2024-03-05 and Thu 2024-03-07 both 1 booking at 14:00) -> weekday 1,
date 2024-03-05.

## Notes / assumptions the developer should confirm

1. `api_dashboard(query)` is assumed to take a `parse_qs`-style dict
   (`{"start": ["2024-03-01"], "end": [...]}`) and return `(status, body)` like
   the other `api_*` functions. If the signature differs, only the `dashboard()`
   helper in the suite needs changing.
2. `by_date` is assumed to contain **every** day of the range (zeros included);
   `test_by_date_sums_equal_totals` asserts `len(by_date) == days`.
3. `by_hour[i].hours` is assumed to be the overlap hours of the bookings counted
   in that hour (09:30-11:00 -> 0.5 in hour 9, 1.0 in hour 10), and the hourly
   hours are asserted to sum to `totals.hours`.
4. `status` strings are asserted exactly as `'underused'`, `'moderate'`,
   `'heavily used'`; suggestion `kind` values exactly as `'underused'`,
   `'heavily used'`, `'high_cancellations'`.
5. `capacity_hours` is asserted as `days * 10 * number_of_rooms` (all rooms,
   including rooms with no bookings).
6. Span limit: 2024-01-01..2024-12-31 (366 days, leap year) must be accepted;
   2024-01-01..2025-01-02 must be rejected with `ApiError(400)`.

## Requirements check (my part)

- REQ10 (use the system's booking records): tests read the real `bookings` table
  through the app's own DB layer. Met.
- REQ2/REQ3/REQ4/REQ5/REQ6/REQ8: each has explicit assertions above. Met at the
  test level; the implementation is still missing.
- REQ1/REQ7/REQ9 (interactive UI, charts, allocation decision): **not covered by
  this suite** — it tests the JSON endpoint only; the Dashboard tab UI needs a
  separate browser/static check.
- REQ11: the SPEC was already agreed with the human; the open assumptions are
  listed above rather than guessed silently.
