# Manager dashboard — handover and verification status

Deliverables: `app.py` (dashboard + soft-delete cancellations), `test_app.py`
(23 tests), `README.md`, `QUICKSTART.md`, `CHANGELOG.md` (v1.1 entry).

## What was built (requester's decisions, all three defaults accepted)

1. **Dashboard is admin-key only** (same `ADMIN_KEY`, default `admin`); without a
   valid key `GET /api/dashboard` returns 403 and the page shows the error.
2. **Cancellations are kept as records** (`cancelled_at`, `cancelled_by`) instead
   of being deleted, so cancellations can be counted. The slot is still free
   immediately and re-bookable; a second cancel returns 409. An existing
   `bookings.db` is migrated automatically on start-up (columns added only if
   missing).
3. **Default range = last 30 days**; presets Last 7 / 30 / 90 days and This
   month; room filter; busiest days = weekday (Mon–Sun) + top 5 dates; busiest
   times = hour bands 08–09 … 17–18; utilisation = hours ÷ (weekdays in range ×
   10 open hours); heavily used > 70 %, underused < 25 % (both printed on screen).

Charts are inline SVG drawn by the page itself — no CDN, no JS libraries, still
Python 3 standard library only.

## Verification status (be precise when presenting this)

* **Tests:** `python3 test_app.py` → `Ran 23 tests ... OK` (16 original + 7
  `DashboardTests`). QA re-ran the suite on the final code and got 23 tests, all
  ok; the 7 method names in README.md were checked against `test_app.py`.
* **Dashboard figures:** QA recomputed per-room bookings, hours, cancelled,
  cancellation rate, utilisation, weekday/hour aggregation and the range
  validation independently on the pre-fix code and they matched the API. The
  multi-day aggregation fix was then checked by hand only (QA-reported: 40 active
  bookings over 20 weekdays → 40 bookings / 40.0 h, Mon–Fri 8 each, hour bands
  09–10 and 14–15 = 20 each, top 5 dates × 2); that figure set is not
  reproducible from the delivered files because no seed script is shipped.
* **UI:** checked by fetching the page and reading the dashboard JavaScript
  (section present, date pickers, presets, room filter, inline SVG charts,
  per-room table, summary/recommendation, thresholds and denominator stated, no
  external script/link, every referenced element id exists). **No real browser
  was driven** — clicking through the charts in a browser is the one thing not
  verified.
* **Migration:** covered by the automated test
  `test_migration_adds_columns_to_old_database`; QA did not repeat it by hand.
* **Test names in README.md:** the 7 `DashboardTests` names were checked against
  `test_app.py` by QA and corrected; the top-dates list has no automated test.
* **Test suite after the last code change:** the dev's final edits (range query
  hardened to `day BETWEEN ? AND ?`, capped recommendation) were not re-run by
  the dev; QA ran the suite on that code and got `Ran 23 tests ... OK`, but the
  suite has no test for the multi-day range or the capped recommendation, so
  those two are covered by QA's manual checks only.
* **Seeding history:** `POST /api/bookings` rejects past dates, so to try the
  dashboard on historical data, insert rows directly into `bookings.db` (columns
  as in the `bookings` table: `day` as `YYYY-MM-DD`, `start`/`end` as `HH:MM`,
  plus room, booker, email, title) and restart the app, or simply use the
  dashboard as real bookings accumulate.
* **Release date:** `CHANGELOG.md` v1.1 says `(release date: TBD)` — fill it in
  when you release (v1.0's date is also TBD in the changelog).
* **Not done:** no test was added for the capped recommendation text ("… and N
  more" / "No room is heavily used"); that behaviour was verified by QA by hand
  only. The underused rooms in that sentence are listed by room name, not by
  utilisation.
* **Not done:** no automated test for multi-day aggregation across several weeks
  (QA verified it by hand after the fix).
