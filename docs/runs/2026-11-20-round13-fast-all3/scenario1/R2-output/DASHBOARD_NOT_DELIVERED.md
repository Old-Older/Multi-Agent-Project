# Manager dashboard — NOT delivered (honest status)

The interactive manager dashboard for the meeting room booking system was **not built** in this
round. The time budget ran out while I was reading the existing code (`booking_app.py`, ~25k
characters) and my tool calls to run the app kept timing out, so no code was written.

## What was agreed with you (your answer: "Use all your defaults")

1. New page `/dashboard` in the same app, no login (same as the booking page).
2. Date range: two date pickers + quick buttons (last 7 / 30 / 90 days, this month, all time);
   default = last 30 days.
3. Cancellations are recorded (who, when, room, slot) instead of deleted, so the cancellation
   rate = cancelled / (active + cancelled) per room and per day. Existing bookings unchanged.
4. Charts in plain HTML/CSS/SVG (no internet needed): bookings per room, reserved hours per room,
   day-of-week × hour heatmap, bookings per day, plus a table with utilisation %
   (reserved hours ÷ available hours in the range) and an auto-written "heavily used / underused"
   summary.
5. A script to generate demo bookings so the dashboard is not empty on first look.

## What exists today

- `booking_app.py` — the booking system from the previous round (availability grid, booking,
  cancel, JSON API). Unchanged.
- `README.md` — its instructions. Unchanged.

## What is missing

- The `/dashboard` page and its `/api/stats` endpoint.
- Recording of cancellations (today `DELETE /api/bookings/<id>` removes the record, so
  cancellation counts cannot be computed from the current data).
- The demo-data generator and the README section for the dashboard.

## Suggested next step

Re-run this request with a fresh time budget; the design above is ready to implement in
`booking_app.py` (one new route, one stats function, one HTML page, one seed script).
