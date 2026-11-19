# RoomBook — what was built

**Files:** `roombook.html` (the app, single file, no install) and `README.md` (how to use it).

## What it does
- **Day view**: rooms × 30-minute slots (08:00–19:00). Click a free slot to book; click a booking to cancel.
- **Booking from the grid uses two browser `prompt()` pop-ups** (title, then end time as HH:MM) — there is no inline booking form.
- **Check availability**: date + window + optional headcount → free rooms with a one-click Book button; busy rooms show the blocking booking and, where one exists, the next free window; rooms too small for the headcount are listed separately.
- **My bookings**: upcoming bookings with Cancel. Shows only your bookings when your name is filled in; with an empty name box it shows everyone's upcoming bookings.
- **Rooms & data**: add/remove rooms, export/import JSON backup, reset to demo data.
- **Double bookings are impossible**: every save is checked for overlap in the same room/date and refused with a message naming the blocking booking.
- **No stale records**: cancelling removes the booking from every view at once and frees the slot; cancelled bookings go to a hidden log.

## Verification status
- **Code inspection by QA (FAIL → fixes applied):** QA reviewed this file against SPEC.md and raised 11 items. All 11 were applied: the availability-view crash for capacity-filtered rooms, the wrong next-free-window calculation, strict HH:MM parsing with a retry message, cancel feedback when the confirmation is declined, and the README/BUILD_NOTES wording items.
- **Static checks only:** the JavaScript parses without syntax errors (`node --check`) and brackets balance. These do not prove behaviour.
- **Not verified in a real browser:** no one has clicked through the app in Chrome/Firefox/Safari. SPEC check 10 (no console errors when opened from `file://`) is therefore **unverified**, as is the availability/busy-room path after the fix. Please run through the README steps once before relying on it.

## Known limits
- Data is stored in one browser on one computer (localStorage); share via Export/Import.
- No logins; the name field is for clarity only.
