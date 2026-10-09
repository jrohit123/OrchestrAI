# Photos on WhatsApp: how they are kept and how to change the numbers

**Why.** WhatsApp keeps a photo for about 30 days only, and the chat bot gets just a reference to it. So the moment a
photo arrives the bot downloads it and saves its own copy in the client's own database. (Telegram keeps its photos itself,
so for Telegram only the reference is stored, as before.)

## What happens (code: `app/services/photos.py`)

| Step | What the system does |
|---|---|
| A person sends a photo on WhatsApp | The bot downloads it from Meta and saves it in `case_photos` (Godrej's database). It tells them "📎 Photo added" or "📎 Got the photo, now tell me what it is for", the same words as on Telegram. |
| The request is saved (`case.attach_photos` step) | The photos are put on the case (`case_photos.case_id`) and the case timeline gets an "evidence" entry that names the photo. Up to `photo_max` per request. |
| Someone opens the case in the dashboard | The timeline shows the picture. It is served only to a signed-in person who may see the case, and only as a real picture type (jpeg, png, webp). |
| The people on the case are told (`notify.parties` with "send the photos too") | Anyone whose WhatsApp is open gets the text and the photos. Anyone whose WhatsApp is closed (no message from them in 24 hours) gets the text by email, and whoever started it is told. |
| A photo that never reaches a case | The nightly cleanup removes it after `photos_days` and keeps a note of the row (without the picture) in `archived_rows`. |
| A voice note, video, document, location or contact is sent | The bot answers "I can only read text and photos here" instead of staying silent. A reaction (a thumbs up on a message) is ignored quietly. |

## The numbers (Settings screen, box **Photos**; `orgs.settings`)

| Number | Built in | Meaning |
|---|---|---|
| `limits.photo_max` | 5 | photos kept on one request |
| `limits.photo_max_mb` | 5 | the largest photo that is saved, in MB |
| `limits.photo_hold_minutes` | 15 | a photo sent first waits this long for its request |
| `retention.photos_days` | 7 | days before a photo nobody put on a case is cleared |

All the sentences are on the Messages screen, group **Photos** (`photo.failed`, `photo.too_big`, `photo.unsupported`
and the existing `photo.held`, `photo.added`).

## Good to know

* The table is Godrej-only (`housing-0008_case_photos`). A client without it just answers "I couldn't save that photo".
* The case reminders and the "tell everyone on the case" messages now go through the 24-hour rule, like flow messages.
* Photos kept on Telegram (before the move) stay on Telegram's servers; the dashboard shows "Added a photo (kept on
  Telegram)" for them. Telegram ties those references to the bot that received them.
