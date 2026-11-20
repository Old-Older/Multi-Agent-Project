# QA plan — manager dashboard (`/dashboard`, `/api/stats`)

Status: **written against app.py v1.1 (pre-dashboard)**. The dashboard is being built in
parallel, so every dashboard check below is a *specification to test against*, not a
result. Section 1 lists defects/risks in the **existing** code that the dashboard change
can make worse; section 2 is the API checklist with exact expected numbers; section 3 the
UI checklist; section 4 the regression checklist; section 5 the requirement trace.

Agreed defaults (human decision h3): `/dashboard` in the same app, no login; date-range
picker default **last 30 days** + quick **7 / 30 / 90**; cancellation rate = cancelled ÷
all bookings **created** in the range, per room and overall; reserved hours count
**non-cancelled** bookings only; busiest days = day of week **and** calendar date, busiest
times = hour of day; charts in plain HTML/CSS/SVG; one "allocation suggestion" line per
room from utilisation vs. available hours; cancelling sets `cancelled_at` instead of
deleting the row.

---

## 1. Existing defects / risks the dashboard change can make worse

Read from `app.py` (v1.1) and `test_app.py`. Severity: H = blocks the feature, M = wrong
numbers or broken flow, L = cosmetic/robustness.

| # | Sev | Where | Problem | What to change |
|---|-----|-------|---------|----------------|
| D1 | H | `cancel_booking()` — `conn.execute("DELETE FROM bookings WHERE id = ?")` | Cancellation **deletes** the row. The dashboard's cancellation rate, per-room cancellation table and "cancelled" counts have no data to read. | Replace with `UPDATE bookings SET cancelled_at = ? WHERE id = ? AND cancelled_at IS NULL`; keep the 200/403/404 contract. |
| D2 | H | `SCHEMA` (`CREATE TABLE IF NOT EXISTS bookings`) | No `cancelled_at` column and no migration. An existing `bookings.db` will not get the column, so every stats query fails with `no such column: cancelled_at` (500). | Add `cancelled_at TEXT` to the schema **and** an idempotent migration (`PRAGMA table_info(bookings)` → `ALTER TABLE bookings ADD COLUMN cancelled_at TEXT`) run from `init_db()`. |
| D3 | H | `availability()` → `list_bookings(day, room_id)` | Availability is built from *all* rows. Once rows are soft-deleted, cancelled bookings still show as `free: false` and the slot can never be re-booked. | Every availability/booking query must filter `cancelled_at IS NULL`. |
| D4 | H | `create_booking()` clash query `SELECT id FROM bookings WHERE room_id=? AND date=? AND start<? AND end>?` | Same: a cancelled row blocks re-booking the same slot. | Add `AND cancelled_at IS NULL` to the clash query. |
| D5 | H | `SCHEMA` — `UNIQUE (room_id, date, start)` | The unique index still covers cancelled rows, so re-booking a cancelled slot raises `IntegrityError` → 409 "that slot is already booked" even after D4 is fixed. | Replace with a partial index: `CREATE UNIQUE INDEX ... ON bookings(room_id, date, start) WHERE cancelled_at IS NULL` (drop the old table-level UNIQUE; needs a table rebuild or a new index name). |
| D6 | M | `list_bookings()` / `GET /api/bookings` / `GET /api/availability` | No way to ask for cancelled rows or to exclude them; the grid, "My bookings" and the API would show cancelled bookings as live. | Default to `cancelled_at IS NULL`; add `&include_cancelled=1` for the dashboard/audit. |
| D7 | M | `booking_dict()` / `SELECT_BOOKINGS` | Response has no `cancelled_at`/`cancelled` field, so the UI cannot grey out or label a cancelled booking. | Add `"cancelled_at": row["cancelled_at"]` (and keep `id`, `room`, … unchanged). |
| D8 | M | `test_app.py::test_cancellation_frees_slot` | Asserts `DELETE` twice → 404 and that the row is gone. With soft delete the second DELETE must still be 404 (only cancel rows where `cancelled_at IS NULL`) or the test must be updated deliberately. | Keep 404 on re-cancel; update the test to also assert the row still exists with `cancelled_at` set. |
| D9 | M | `test_app.py::setUp` — `DELETE FROM bookings` | Wipes rows between tests; fine, but any new stats test that relies on `created_at` must insert explicit `created_at` values, otherwise "bookings created in range" is untestable. | Stats tests insert rows directly with fixed `created_at`/`cancelled_at`. |
| D10 | M | `check_date_range()` — `[today, today+60]` | Bookings can only be made up to 60 days ahead, but the dashboard offers a **90-day** quick range and "last 30 days" reaches into the past. If `/api/stats` reuses `check_date_range` it will 400 on any past date; if it does not, it must still validate format and `from <= to`. | `/api/stats` must **not** call `check_date_range`; validate `YYYY-MM-DD`, `from <= to`, and cap the span (e.g. ≤ 366 days) with a 400. |
| D11 | M | `parse_date()` | Raises `ValueError` → 400 with a readable message; good. But `parse_qs` drops empty values, so `?from=&to=` arrives as missing → must be a 400 "from and to are required", not a 500. | Explicit required-parameter check in the stats handler. |
| D12 | M | `do_GET` route table | New routes must be added **before** the `return self.error(404, ...)` fallback and must be covered by the same `except ValueError → 400 / except Exception → 500` wrapper, otherwise a stats bug leaks a traceback or an HTML error page. | Add `/dashboard` (HTML) and `/api/stats` (JSON) inside the existing `try`. |
| D13 | L | `INDEX_HTML` header | No navigation link to `/dashboard`, so the manager cannot find the page. | Add a link in the header of both pages (`/` ↔ `/dashboard`). |
| D14 | L | `send_html()` | Sends no `Cache-Control`; a stale dashboard could be served after an update. | Send `Cache-Control: no-store` for `/dashboard` too. |
| D15 | L | `README.md` "Cancellation deletes the row" + "18 tests" | Documentation will be wrong after the change. | Update README (soft delete, new endpoints, test count). |
| D16 | L | `INDEX_HTML` JS `isoDate()` uses `toISOString()` | UTC-based; east of UTC the "today" default can be off by one day. The dashboard's "last 30 days" default will inherit the same bug. | Compute local dates (`new Date(y, m, d)`) in the dashboard JS. |
| D17 | L | `Handler.log_message` | Logs every request to stderr; a dashboard that polls will flood the log. | Acceptable, but do not auto-refresh more often than every 30 s. |

---

## 2. API-level checks — `/api/stats`

### 2.1 Hand-built dataset (fixed, deterministic)

Use a throw-away DB and a fixed "today" so the numbers never drift. The fixture below
writes rows **directly** into SQLite (bypassing the 60-day booking rule) so past dates can
be used; `created_at` is set explicitly because the cancellation rate is defined on
bookings *created* in the range.

```bash
# 0. fresh DB + server on port 8765
cd <dir with app.py>
export BOOKINGS_DB=/tmp/qa_stats.db PORT=8765
rm -f /tmp/qa_stats.db
python3 app.py &            # leave running; Ctrl-C / kill %1 when done
```

```bash
# 1. seed the fixture (run once, after the server has created the schema)
python3 - <<'PY'
import os, sqlite3
from datetime import date, timedelta
db = os.environ["BOOKINGS_DB"]
today = date.today()
d = lambda n: (today - timedelta(days=n)).isoformat()
rows = [
  # room, date,        start,  end,    booker, created_at,          cancelled_at
  (1, d(1),  "09:00", "10:00", "Alex",  d(1)+"T08:00:00", None),   # Cedar 1h, live
  (1, d(2),  "09:00", "11:00", "Sam",   d(2)+"T08:00:00", None),   # Cedar 2h, live
  (1, d(3),  "14:00", "15:00", "Alex",  d(3)+"T08:00:00", d(3)+"T09:00:00"),  # Cedar 1h, CANCELLED
  (2, d(1),  "10:00", "12:00", "Kim",   d(1)+"T08:00:00", None),   # Birch 2h, live
  (2, d(4),  "13:00", "13:30", "Kim",   d(4)+"T08:00:00", d(4)+"T09:00:00"),  # Birch 0.5h, CANCELLED
  (3, d(5),  "08:00", "12:00", "Lee",   d(5)+"T08:00:00", None),   # Maple 4h, live
  (4, d(40), "09:00", "10:00", "Lee",   d(40)+"T08:00:00", None),  # Oak, OUTSIDE last 30 days
]
conn = sqlite3.connect(db)
conn.executemany("INSERT INTO bookings (room_id,date,start,end,booker,created_at,cancelled_at) "
                 "VALUES (?,?,?,?,?,?,?)", rows)
conn.commit(); conn.close()
print("seeded", len(rows), "rows; today =", today)
PY
```

Expected values for `from = today-30`, `to = today` (7 rows seeded, 6 inside the range):

| Metric | Expected | Why |
|---|---|---|
| `total_bookings` | **6** | 6 rows created in the last 30 days (Oak row is 40 days old) |
| `cancelled_bookings` | **2** | Cedar d(3), Birch d(4) |
| `cancellation_rate` | **0.3333** (33.3 %) | 2 / 6 |
| `total_hours` (reserved) | **9.0** | 1 + 2 + 2 + 4 (cancelled 1 h and 0.5 h excluded) |
| Cedar | 3 bookings, **1** cancelled, 3.0 h reserved (the cancelled 1 h is excluded) | |
| Birch | 2 bookings, 1 cancelled, 2.0 h reserved | |
| Maple | 1 booking, 0 cancelled, 4.0 h reserved | |
| Oak | 0 bookings, 0 h, **listed** with "unused" | room exists but has no bookings in range |
| `rooms_used` / `rooms_unused` | **3** / **1** (Oak) | |
| by day of week | Mon 1, Tue 1, Wed 1, Thu 2, Fri 0, Sat 0, Sun 1 (sums to 6) | |
| by calendar date | 5 distinct dates: d(1)=2, d(2)=1, d(3)=1, d(4)=1, d(5)=1 | d(1) has Cedar+Birch |
| by hour of day | 08:00→1, 09:00→2, 10:00→1, 13:00→1, 14:00→1 | hour of the **start** time; state the rule in the UI |
| per-room cancellations | Cedar 1/3, Birch 1/2, Maple 0/1, Oak 0/0 | |

These numbers were recomputed independently by `qa_verify_fixture.py` (plain Python over
the same rows, no dashboard code) and match the table above.

Utilisation: available hours per room = 10 h/day × 30 days = **300 h** (08:00–18:00).
Cedar 3.0/300 = **1.0 %**, Birch 2.0/300 = **0.67 %**, Maple 4.0/300 = **1.33 %**,
Oak 0/300 = **0 %**. All four are far below any sensible threshold, so every room must
carry an "underused" suggestion — that is the expected output for this fixture, not a bug.

### 2.2 Checks

Run each command and compare with the expected value. `jq` is optional; the `python3 -c`
forms work with the standard library only.

1. **Endpoint exists and is JSON.**
   `curl -s -o /dev/null -w '%{http_code} %{content_type}\n' 'http://127.0.0.1:8765/api/stats?from=2025-01-01&to=2025-01-02'`
   → `200 application/json; charset=utf-8`.
2. **Default range = last 30 days** when no parameters are given.
   `curl -s 'http://127.0.0.1:8765/api/stats' | python3 -m json.tool | head -20`
   → `from` = today−29 (or today−30, whichever the UI shows — must match the picker) and
   `to` = today; `total_bookings` = 6 on the fixture.
3. **Exact totals for the fixture.**
   `curl -s 'http://127.0.0.1:8765/api/stats?from=<today-30>&to=<today>' | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["total_bookings"], d["cancelled_bookings"], round(d["cancellation_rate"],4), d["total_hours"])'`
   → `6 2 0.3333 9.0`.
4. **Per-room rows.** Same URL, print `room, bookings, cancelled, hours, utilisation_pct`:
   → `Cedar 3 1 3.0 1.0`, `Birch 2 1 2.0 0.67`, `Maple 1 0 4.0 1.33`, `Oak 0 0 0.0 0.0`
   (columns: bookings, cancelled, hours, utilisation %).
   Every room in `/api/rooms` must appear, including Oak.
5. **Cancelled hours excluded, cancelled bookings counted.** Cancel a live booking through
   the API and re-read stats:
   `curl -s -X DELETE http://127.0.0.1:8765/api/bookings/<id of Maple 4h> -H 'Content-Type: application/json' -d '{"booker":"Lee"}'`
   then re-run check 3 → `total_bookings` still **6**, `cancelled_bookings` **3**,
   `cancellation_rate` **0.5**, `total_hours` **5.0** (9.0 − 4.0).
6. **Range boundaries are inclusive.** `from=<today-1>&to=<today-1>` → `total_bookings` 2, `total_hours` 3.0
   (Cedar 09:00 + Birch 10:00 on d(1)); `from=<today-40>&to=<today-40>` → 1, 1.0 h (the Oak row).
7. **Range excludes by `created_at`, not by booking date.** Move the window to
   `from=<today-3>&to=<today-1>` → 4 bookings (d(1) ×2, d(2), d(3)), 1 cancelled, 5.0 h
   (1 + 2 + 2 live hours; the cancelled Cedar 1 h is excluded).
8. **Empty range.** `from=<today-200>&to=<today-190>` → `200`, `total_bookings` 0,
   `total_hours` 0, `cancellation_rate` 0 (not `null`, not a division error), all four rooms
   present with zeros, `rooms_used` 0, `rooms_unused` 4, and a non-empty summary sentence
   such as "No bookings in this period."
9. **Invalid input → 400 with a JSON `error`, never 500.**
   `curl -s -w ' %{http_code}\n' 'http://127.0.0.1:8765/api/stats?from=2025-13-45&to=2025-01-01'`
   `curl -s -w ' %{http_code}\n' 'http://127.0.0.1:8765/api/stats?from=2025-02-01&to=2025-01-01'` (from > to)
   `curl -s -w ' %{http_code}\n' 'http://127.0.0.1:8765/api/stats?from=&to='` (missing)
   `curl -s -w ' %{http_code}\n' 'http://127.0.0.1:8765/api/stats?from=2025-01-01&to=2027-01-01'` (span > 366 d)
   → all `400` with `{"error": "..."}` and no Python text.
10. **Past dates are allowed** (unlike `/api/availability`): `from=<today-90>&to=<today>` →
    `200`, not `400 "date must be between today and 60 days ahead"`.
11. **Consistency with `/api/bookings`.** For the same range,
    `curl -s 'http://127.0.0.1:8765/api/bookings?include_cancelled=1'` must contain exactly
    the rows the stats counted; `total_bookings` = number of rows with `created_at` in range.
12. **No double counting of multi-slot bookings.** A 4 h booking is **one** booking and
    **4.0 h**, not 8 half-hour slots.
13. **`HEAD /api/stats`** → 200 with an empty body (the existing `do_HEAD` path).
14. **`PUT /api/stats`** → 405 JSON (existing `method_not_allowed`).
15. **Concurrency smoke test.** 20 parallel `curl` calls to `/api/stats` while 5 bookings
    are created → no 500, no `database is locked` in the server log.
16. **Performance.** With 5 000 rows seeded, `/api/stats` answers in < 1 s
    (`curl -s -o /dev/null -w '%{time_total}\n' ...`); the `idx_bookings_date` index is used
    or a `created_at` index is added.

---

## 3. UI checks — `/dashboard`

17. **Page loads.** `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/dashboard`
    → `200`; body contains `<title>` mentioning the dashboard and no `Traceback`.
18. **No JavaScript errors.** Open `/dashboard` in a browser with the console open, reload,
    change the range, click each quick button → console stays empty (no `Uncaught`,
    no 404 for a missing asset). Also check the Network tab: no request to an external
    host (charts must be local HTML/CSS/SVG).
19. **Default range.** On first load the picker shows the last 30 days and the KPIs match
    check 3 of section 2.
20. **Quick buttons 7 / 30 / 90.** Each sets the picker and reloads; 7 → only the last 7
    days of the fixture (5 bookings), 90 → includes the Oak row (7 bookings).
21. **Invalid range in the UI.** Set `from` after `to` → an inline error message, no
    request with a bad range, no blank page, no console error.
22. **Empty state.** Range with no bookings (check 8) → "No bookings in this period"
    message, KPI cards show 0 (not `NaN`, not `undefined`, not `Infinity`), charts show an
    empty-state placeholder instead of a broken axis, summary paragraph is still readable.
23. **Charts render.** Every chart (per-room bars, day-of-week, calendar date, hour of day,
    cancellation table) is visible, has axis labels/units, and the bar lengths are
    proportional to the numbers in the tables (spot-check Cedar 3.0 h vs Maple 4.0 h).
24. **Numbers agree across views.** KPI total = sum of per-room bookings = sum of the
    day-of-week buckets = sum of the calendar-date buckets. Cancellation rate shown as a
    percentage equals cancelled ÷ total.
25. **Utilisation + allocation suggestion.** Each room row shows bookings, hours,
    utilisation % and one suggestion line; Oak (0 bookings) says "unused/underused —
    consider merging or downsizing"; the suggestion is derived from the numbers, not
    hard-coded.
26. **Summary paragraph.** Auto-generated text names the busiest day/time and the most and
    least used room, and matches the tables.
27. **Links work.** A link from `/` to `/dashboard` and back; the room names in the
    dashboard link to `/` (or `/api/bookings?room=…`) and land on a working page.
28. **Accessibility / clarity.** Charts have text alternatives (table or `aria-label`),
    colour is not the only signal, page is usable at 1280 px and 800 px wide.
29. **No login required** (agreed default) and the page does not leak booker names beyond
    what the booking page already shows.

---

## 4. Regression checks — booking and cancelling still work

30. **Existing suite passes.** `cd <dir with app.py> && python3 -m unittest -v test_app`
    → all tests pass (18 before the change; the count may grow, none may be deleted).
31. **Book via API.** `curl -s -X POST http://127.0.0.1:8765/api/bookings -H 'Content-Type: application/json' -d '{"room_id":1,"date":"<tomorrow>","start":"10:00","end":"11:00","booker":"Alex"}'`
    → `201` with `{"booking": {...}}`.
32. **Overlap still rejected.** Same request again → `409 {"error": "that slot is already booked"}`.
33. **Cancel frees the slot.** `curl -s -X DELETE http://127.0.0.1:8765/api/bookings/<id> -H 'Content-Type: application/json' -d '{"booker":"Alex"}'`
    → `200 {"cancelled": <id>}`; then
    `curl -s 'http://127.0.0.1:8765/api/availability?date=<tomorrow>&room=1'` shows
    `"start":"10:00"` with `"free": true`.
34. **Cancelled slot is bookable again** (the D3/D4/D5 trap):
    re-POST the same slot with `"booker":"Sam"` → **201**, not 409.
35. **Cancelled booking is not listed as live.** `curl -s 'http://127.0.0.1:8765/api/bookings?date=<tomorrow>'`
    → only the new Sam booking; the cancelled one appears only with `&include_cancelled=1`
    and then carries a non-null `cancelled_at`.
36. **Cancel twice → 404**, cancel with the wrong name → 403, cancel with no name → 400
    (unchanged contract).
37. **Booking page still works in the browser.** `/` loads, grid renders 20 slots × 4 rooms,
    click a free slot → dialog → Book → success message, the slot turns red, "My bookings"
    lists it, Cancel → confirm → slot turns green again.
38. **Stats reflect the new booking immediately.** After check 31, `/api/stats` for today's
    range shows `total_bookings` +1 and `total_hours` +1.0; after check 33 it shows
    `cancelled_bookings` +1 and `total_hours` back to the previous value.
39. **Old database still opens.** Start the server against a copy of a pre-change
    `bookings.db` → no error, the migration adds `cancelled_at`, existing bookings are
    treated as live, `/dashboard` works.
40. **Restart is idempotent.** Start/stop twice on the same DB → no duplicate rooms, no
    schema error, stats unchanged.

---

## 5. Requirement trace

| REQ | Covered by |
|---|---|
| REQ1 interactive dashboard | 17–29 |
| REQ2 selected date range | 2, 6, 7, 19, 20, 21 |
| REQ3 how often each room is booked | 4, 24 |
| REQ4 total time reserved per room | 3, 4, 5, 12 |
| REQ5 busiest days and times | 3 (day-of-week / date / hour buckets), 26 |
| REQ6 how often cancelled | 3, 5, 24 |
| REQ7 clear charts and summaries | 23, 26, 28 |
| REQ8 heavily used vs underused rooms | 4, 25 |
| REQ9 decide on room allocation | 25, 26 |
| REQ10 uses the system's booking records | 11, 38, 39 |
| REQ11 consult the requester | defaults confirmed in h3; open questions below |

Open questions for the requester (REQ11): (a) is "last 30 days" today−29…today or
today−30…today? (b) is the hour-of-day bucket the booking **start** hour or every hour the
booking covers? (c) what utilisation threshold separates "heavily used" from "underused"?
(d) should the dashboard count bookings by booking date or by creation date for the
per-room tables (the cancellation rate is defined on creation date)?
