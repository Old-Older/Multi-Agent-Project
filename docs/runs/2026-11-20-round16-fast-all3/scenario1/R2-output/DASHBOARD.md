# Manager dashboard (added to app.py)

New in this version: a manager analytics dashboard computed from the existing
`bookings` table (active + cancelled rows). No new dependencies, no internet.

## Pages / endpoints

* `GET /dashboard` - the dashboard page (inline HTML/CSS/SVG, vanilla JS).
  Linked from the main page header ("Manager dashboard ->"); the dashboard
  links back to `/`.
* `GET /api/dashboard?from=YYYY-MM-DD&to=YYYY-MM-DD` - JSON for the range.
  * Both params missing (or empty) -> default = last 30 days ending today.
  * Only one of them -> 400.
  * Invalid / non-existent date -> 400.
  * `from > to` -> 400.
  * More than 366 days -> 400.
  * Errors are `{"error": "..."}` with status 400.

## What the page shows

1. KPI cards: active bookings, hours reserved (sum of end-start of active
   bookings), rooms used / total, cancellations + cancellation rate
   (cancelled / (active + cancelled)).
2. Per-room table + horizontal bar chart: bookings, hours, cancelled,
   cancellation rate, utilisation % = hours / (11 h x days in range), and a
   label. Thresholds (documented on the page): heavy >= 60 %, underused < 20 %,
   normal in between.
3. Busiest weekdays: Mon..Sun bar chart of active bookings (hours in tooltip).
4. Busiest hours: bar chart of active bookings per start hour, 08..18.
5. Cancellations: per-room cancellation-rate bar chart + monthly
   bookings-vs-cancellations grouped bar chart.
6. Recommendations: automatic list (heavy rooms, underused rooms, high
   cancellation-rate rooms, overall cancellation rate), each with the figure
   that triggered it.
7. Range controls: preset buttons (last 7 / 30 / 90 days, this month) plus
   custom from/to date inputs.

Cancelled bookings are counted separately and never included in booking
counts or reserved hours.

## JSON keys of /api/dashboard

```
range            {from, to, days, working_hours_per_day, capacity_hours, default_days, max_days}
thresholds       {heavy_pct, underused_pct, high_cancellation_pct, day_start, day_end}
kpis             {active_bookings, hours_reserved, rooms_used, rooms_total,
                  cancellations, cancellation_rate, total_bookings}
rooms[]          {room_id, room, capacity, bookings, hours, cancelled,
                  cancellation_rate, utilisation, label}
weekdays[]       {weekday, bookings, hours}          # Mon..Sun
hours[]          {hour, bookings}                    # 8..18
trend[]          {month, bookings, cancelled, cancellation_rate}
recommendations[]{kind, room, text}                  # kind: heavy|underused|cancellations|info
```

## Tests

`python3 -m unittest -v test_app` -> `Ran 20 tests ... OK`
(5 new dashboard tests: page + links, empty range, seeded numbers incl. a
cancelled booking, heavy-room recommendation, invalid ranges, default range).
