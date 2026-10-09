# WhatsApp's 24-hour rule: what the system does and how to change it

**The rule (Meta's, not ours).** The chat bot may start a WhatsApp message to a person only if that person wrote to the
bot in the last 24 hours. Their message "opens the door"; every new message opens it again for 24 hours. Outside it
WhatsApp accepts the send and then never delivers it (error 131047 in the log: "Re-engagement message"). Telegram has no
such rule, so nothing here touches a Telegram person.

## What happens now (code: `app/services/reach.py`)

| Situation | What the system does |
|---|---|
| The person wrote in the last 24 hours (less a spare, see below) | The message goes as before, with a **👍 Got it** button under it. One tap opens the door for another 24 hours. |
| The door is closed (a flow's "tell this person" step, e.g. the stock alert) | The message is **not** sent on WhatsApp. It is kept (3 days), **emailed** to the person at once with the full text and a one-tap link that opens WhatsApp on the bot with a ready message, and the person who ran the flow is told: "…'s WhatsApp is closed … I emailed it to them…". |
| The door is closed (a scheduled report) | The report goes **by email** (PDF attached, whatever the AI asked for), with the same one-tap link. Only the newest text copy is kept for when they write. |
| The person writes anything (or taps Got it, or sends the ready message) | What was kept is sent on WhatsApp, and the senders are told it arrived (only if their own door is open). |
| WhatsApp refuses a send we thought was fine (our notes can be a little out) | Meta's "failed" report (131047) is acted on: kept, emailed, sender told. |

How we know the door is open: every message a person sends is noted in Redis (`door:<phone>`, 40 days); if Redis lost it,
the person's last logged chat turn (`audit_log`) counts. Nothing known = closed.

## Settings

Numbers (Settings screen, box **Messages WhatsApp cannot deliver**, `orgs.settings.limits`):

| Number | Built in | Meaning |
|---|---|---|
| `hold_days` | 3 | how long a kept message waits for the person to write |
| `hold_max` | 5 | most kept messages per person (the oldest go first) |
| `door_margin_minutes` | 60 | the 24 hours are counted with this much to spare |

Switches and the number (no screen yet; `orgs.settings.reach`, set with a small SQL update):

```sql
-- the number people write to, for the one-tap link (digits; otherwise the app asks Meta for it)
UPDATE orgs SET settings = jsonb_set(coalesce(settings,'{}'::jsonb), '{reach,whatsapp_number}', '"919876543210"');
-- switch the whole thing off (the bot just tries, as it always did)
UPDATE orgs SET settings = jsonb_set(coalesce(settings,'{}'::jsonb), '{reach,enabled}', 'false');
-- no Got it button
UPDATE orgs SET settings = jsonb_set(coalesce(settings,'{}'::jsonb), '{reach,got_it_button}', 'false');
```

Words: Messages screen, group **Messages WhatsApp could not deliver** (16 texts, standard wording in migration
`core-0016_hold_texts`; until that migration is applied the chat bot uses the same words from the code).

## Good to know

* Nothing is stored in a table. Kept messages are in Redis; if Redis is wiped they are lost, but the email already
  carried the full message.
* A person with no email on file gets nothing by email; the sender is told so, and the message waits for them to write.
* The cure that needs no person to do anything is an approved WhatsApp template (P1-5). When it exists it becomes the
  first try for a closed door; this stays as the backup.
* To test: run the stock alert for someone who has not written to the bot for a day. The flow's answer says the
  WhatsApp is closed, they get the email, and tapping the link then sending the ready message delivers the alert.

## The approved template (when one is chosen)

`orgs.settings -> reach.template = {"name": "session_active", "language": "en"}` (Godrej has it; `housing-0009`). When a
message has to wait because the person's WhatsApp is closed, the chat bot also sends that template (no blanks, one
**Proceed** button). The person taps it, their WhatsApp opens again and the waiting message arrives (the tap comes back
as a message of type `button`). At most once every `limits.template_hours` (24) per person. If Meta refuses the
template, nothing else changes: the message is still kept and emailed, and the next message tries again. To stop using
it, remove `reach.template` from the settings. The template's own words live in Meta's WhatsApp Manager, not here.
