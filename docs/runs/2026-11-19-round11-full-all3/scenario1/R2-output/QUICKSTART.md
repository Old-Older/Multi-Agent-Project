# Meeting Room Booking — Quick Start

This replaces the shared spreadsheet. It runs on one shared computer and everyone
uses it in a web browser. There is no login: you are identified by the name and
email you type in.

## What changed vs the spreadsheet

* **No double bookings.** The app checks every booking on the server, so two
  people cannot end up with the same room at the same time — even if they click
  at the same moment. The second person is told who already has the room.
* **Cancellations free the slot immediately.** Once a booking is cancelled the
  slot shows as free and can be booked again right away. The cancelled booking
  is not thrown away: it is kept as a cancelled record (with who cancelled it and
  when) so the manager's dashboard can report cancellations.
* **One shared, always-current record.** Everyone sees the same availability for
  the day, each person can look up their own bookings, and the day's bookings can
  be exported to CSV.
* **A dashboard for the room manager** showing how the rooms are actually used
  (see below).

## Start it (once, on the shared machine)

1. On the shared machine, open a terminal in the folder that contains `app.py`.
2. Type `python3 app.py` and press Enter. Leave that window open — closing it
   stops the app.
3. Open a browser and go to **http://localhost:8000** (on the shared machine
   itself). To use it from your own computer, ask whoever runs the app for the
   address, e.g. `http://meeting-rooms.internal:8000`.
4. The first time it runs it creates a file called `bookings.db` — that file holds
   all bookings. Back it up to back up the bookings. If you already have a
   `bookings.db` from an older version, it is upgraded automatically when the app
   starts; nothing is lost.
5. If port 8000 is already taken, start it with `PORT=9000 python3 app.py` and use
   http://localhost:9000 instead.

## Check availability

1. In the top section, pick a date and press **Show availability** (or use
   **Prev day** / **Next day**).
2. You get one card per room (Aspen, Birch, Cedar, Dogwood, Elm) showing every
   30-minute slot from 08:00 to 18:00.
3. **Green** = free, **red** = booked (point at a red slot with the mouse to see
   who booked it), **grey** = closed. Weekends are closed — rooms can only be
   booked Monday to Friday.

## Book a room

1. Click a **green slot** — room, date and times are filled in for you. (Or choose
   room, date, start and end yourself.)
2. Enter **your name** and **your email**. Your email is your identity — it is what
   lets you cancel later.
3. Optionally add a **purpose** (e.g. "Sprint planning"), up to 200 characters. A
   longer purpose is refused with a clear message — it is never cut short.
4. Press **Book room**. If someone already has that room at an overlapping time,
   the booking is refused and you are told who already has it.
5. Anyone can book any room — there is no approval step. Past dates are refused.

## See my bookings

1. In the **My bookings** section, type your email and press **Show my bookings**.
2. You see everything you have booked. Your email is remembered in the browser, so
   next time it is already filled in.

## Cancel a booking

1. Find the booking in **My bookings** and press **Cancel** on that row.
2. The slot becomes free straight away and someone else can book it. The booking
   is kept as a cancelled record (it is not deleted), so the manager's dashboard
   can count cancellations.
3. You can only cancel your own bookings (the email must match). An admin can
   cancel anyone's booking (see Admin override below).

## Export to CSV

1. In the **My bookings** section, press **Export all to CSV**. It downloads
   `bookings.csv`, which opens in Excel or Google Sheets.
2. It exports the bookings for the date currently shown in the availability
   section (or all bookings for every date if no date is set).

## Admin override

1. In the **Admin** section, type the admin key (default `admin`, unless whoever
   runs the app changed it) and press **Show all bookings** to see every booking.
2. The **Cancel** button then works on anyone's booking — use it when someone
   leaves the team or forgets to cancel.
3. Without the admin key the full list is not shown (the page shows an error).
   The day's availability view stays visible to everyone.

## Dashboard for the room manager

The **Dashboard (manager)** section answers one question: *are our rooms used
well, and should we change how they are allocated?* It is for whoever manages
the rooms; it needs the admin key (default `admin`), because it shows figures
for all bookings.

**How to open it**

1. Scroll to **Dashboard (manager)** and type the admin key.
2. Pick a **From** and **To** date — or just press a preset: **Last 7 days**,
   **Last 30 days** (the default), **Last 90 days**, **This month**.
3. Optionally pick a **Room** (default *All rooms*) and press **Refresh**.

**What to look at**

* **Summary and recommendation** at the top: a plain-English sentence about the
  busiest and quietest room, total bookings and hours, cancellations and the
  cancellation rate, plus a recommendation naming rooms that are heavily used or
  underused.
* **Utilisation per room** bars: **red = heavily used (over 70 %)**, **amber =
  underused (under 25 %)**, blue = normal. Utilisation is the hours reserved
  divided by the hours the room was open in that period (weekdays in the range ×
  10 open hours), so 100 % would mean the room was booked every open hour.
* **Busiest days of the week** and **busiest times of day** (08–09, 09–10, …
  17–18): when the pressure happens.
* **Top 5 busiest dates**: the individual days with the most bookings.
* **Cancellations per week** and the cancelled count: how often rooms are held
  and then released.
* **Per-room detail table**: bookings, hours reserved, utilisation %, cancelled
  and a flag per room.

**How to decide about room allocation**

* Red rooms are the ones to relieve — move some bookings to a quieter room, or
  consider adding capacity.
* Amber rooms are the ones to fill — move bookings there, or reallocate the room
  to something else.
* If the busiest times are concentrated in a few hours or days, that is where
  extra capacity helps most.
* A high cancellation rate means rooms are being held and released — worth
  reminding people to cancel early.

Cancelled bookings are counted in the cancellation figures but **not** in hours
reserved or utilisation, so a cancelled slot does not make a room look busy.

## Good to know

* Rooms: Aspen (4 people), Birch (6), Cedar (8), Dogwood (10), Elm (20).
* 30-minute slots, 08:00–18:00, Monday–Friday only; past dates are refused.
* Anyone can book any room; no approval step.
* Keep the app on the internal network — it has no login and is meant for the
  team only. Because your email is your identity, someone who knows your email
  could cancel your booking; the admin key is the override.
* The dashboard reads the booking records already in the app — there is nothing
  extra to set up. It only counts bookings whose date falls inside the range you
  pick, so a range in the past shows the history for those dates.
* Updating to a newer version: stop the app, replace `app.py` (and
  `test_app.py`), back up `bookings.db`, then start it again — the database is
  upgraded automatically and existing bookings are kept.
