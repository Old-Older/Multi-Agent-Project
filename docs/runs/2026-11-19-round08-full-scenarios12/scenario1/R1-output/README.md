# RoomBook — meeting room booking

RoomBook replaces the shared spreadsheet for booking meeting rooms. It stops double bookings, and a cancelled booking disappears from every view immediately, so the records never go stale.

## How to open it

1. Find the file `roombook.html`.
2. Double-click it. It opens in your web browser (Chrome, Edge, Firefox or Safari).
3. That's it — no installation, no internet connection, no account.

You can keep the file anywhere (desktop, shared drive) and open it whenever you need it.

## First thing: type your name

In the top bar there is a **Your name** box. Type your name once — the app remembers it on this computer. A name is required to book, and it is shown on every booking so the team can see who booked what.

## The four tabs

**Day view** (the default) — a grid of rooms (rows) against 30-minute slots from 08:00 to 19:00 (columns). Use the date picker and the ‹ Previous / Next › buttons to move between days. Booked slots are shaded and show the meeting title and who booked it.

**Check availability** — pick a date, a From and To time, and optionally how many people you need. The app lists every room that is free for that whole window, each with a **Book this room** button. For rooms that are busy it shows which booking is in the way and, where one exists, offers the next free window that day. Rooms that are too small for the headcount you entered are listed separately as "too small".

**My bookings** — upcoming bookings with a **Cancel** button. It shows *your* bookings when your name is filled in; if the name box is empty it shows everyone's upcoming bookings.

**Rooms & data** — add or remove rooms, export/import a backup, reset to demo data.

## How to book a room

1. Go to **Day view** and choose the date.
2. Click an empty slot in the room you want.
3. **Two browser pop-up boxes appear** (the small prompt dialogs your browser shows at the top of the window):
   - first, type a meeting title;
   - then, type the end time as `HH:MM`, e.g. `11:00` (times must be in 30-minute steps).
4. The booking is saved and the slot turns blue with your title and name.

Pressing **Cancel** in either pop-up aborts the booking and nothing is saved. If the end time is not in `HH:MM` form, a red message asks you to click the slot again and retry.

If someone already has that room at that time, the booking is **refused** and a red message names the blocking booking (title, time, who booked it). Nothing is saved, so a double booking cannot happen. Back-to-back meetings (10:00–10:30 then 10:30–11:00) are fine, and the same time in a different room is fine.

You can also book from **Check availability** with one click; those bookings get the title "Meeting" — cancel and re-book if you want a different title.

## How to cancel a booking

Click the booking in the day grid, or use **My bookings → Cancel**, and confirm. The booking is removed from every view straight away, the slot is free again and can be re-booked by anyone. A confirmation message appears at the bottom right; if you decline the confirmation, a message says the booking is unchanged. Cancelled bookings are kept in a hidden log for reference but never block a room.

## Rooms

In **Rooms & data** you can add a room (name and number of seats) or remove one. Removing a room also removes its bookings; if it has upcoming bookings you are asked to confirm first.

## Backing up and sharing your data

Bookings are stored inside this browser on this computer.

- **Export JSON** downloads a file with all rooms and bookings. Keep it somewhere safe.
- **Import JSON** loads such a file back in — use it to restore a backup or move the data to another computer.
- **Reset to demo data** clears everything and puts back the sample rooms and bookings. It deletes your real bookings, so export first.

## Limits to be aware of

- **The data lives in one browser on one computer.** If a colleague opens the same file on their own computer, they see their own separate copy. To share, one person exports and the other imports.
- Clearing the browser's site data (or using a private/incognito window) can wipe the bookings. Export regularly if the data matters.
- There are no logins: anyone who can open the file can book and cancel. The name field is for clarity, not security.
- If the team needs everyone to see the same live bookings at the same time, the next step is a small shared server (or a shared database) behind the same screens — the booking rules are already in place and would carry over.
