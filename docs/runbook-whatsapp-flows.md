# WhatsApp Flows: the menu and the complaint form as panels

What it does: on WhatsApp, "menu" sends a message with an **Open menu** button; tapping it opens a panel inside WhatsApp with
the person's sections (Create, Reports, More) and, under each, only the workflows their role may use. Starting a complaint
sends a **Raise a complaint** button that opens one form: tower and flat, the problem, a kind (optional), how urgent, and
up to 3 photos. The form's answers go to the chat bot as one message, which shows the usual summary, and the person says yes.

Nothing about the lists is typed into Meta. A Flow is only a layout; the lists are sent with each message from the database
(`app/services/flows.py`). Add, remove or regroup a workflow, a kind of complaint or an urgency on the dashboard and the panels
change by themselves.

## What is kept where

| Thing | Where |
|---|---|
| The two layouts | Meta, WhatsApp Manager > Flows. Source files: `docs/design/whatsapp-menu-flow.json`, `docs/design/whatsapp-complaint-form-flow.json` |
| Which Flow to use, on or off | `orgs.settings -> whatsapp_flows` (below) |
| The words on the buttons and above the form | Messages screen, group Menu: `flow.menu_button`, `flow.complaint_intro`, `flow.complaint_button` |
| Urgency choices, field names | the complaint workflow's own `entity_schema` |
| Kinds of complaint offered | the top-level kinds on the Case rules screen |

## Setting it up

1. In WhatsApp Manager > Account tools > Flows > Create flow: **Without Endpoint**, **Default**, category **Other**. Name them `menu` and
   `complaint_form`. Paste the two JSON files. The error counter must be 0.
2. Try them first as drafts: set `"mode": "draft"` in the setting below and the bot sends the unpublished version.
3. Publish both (a published Flow cannot be edited; a change means a new Flow and a new id).
4. Copy each Flow's id and put it in the setting:

```sql
UPDATE orgs SET settings = jsonb_set(COALESCE(settings, '{}'::jsonb), '{whatsapp_flows}',
  '{"menu": {"enabled": true, "flow_id": "MENU_ID"},
    "complaint": {"enabled": true, "flow_id": "FORM_ID", "workflow": "file_a_complaint"}}'::jsonb);
```

(Add `"mode": "draft"` inside either to send the unpublished version.) The setting is read within about 30 seconds.

## Switching it off

Set `"enabled": false` for one of them, or remove `whatsapp_flows`. The bot goes back to the list menu and the chat questions. It
does the same by itself when a Flow cannot be sent.

## Good to know

- It works only for WhatsApp numbers; Telegram keeps its own menu.
- A list holds at most 20 items; titles are cut to 30 letters and descriptions to 20.
- A person's tap comes back as an `nfm_reply` message. A chosen workflow is handled like a tap on a menu row (their role is still
  checked); a filled form becomes `/<the workflow's slash command> Problem: ... Where: ... Priority: ... Category: ...`.
- Photos from the form are saved like photos sent in chat (`case_photos`). How Meta hands them over was not yet proven on a real
  phone when this was written: the log line `WhatsApp Flow answer photos` shows what came back.
- A bare tap on the complaint workflow opens the form. A command with words after it (`/complaint water leak`) skips the form.
