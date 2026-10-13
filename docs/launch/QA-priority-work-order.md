# OrchestrAI launch: QA priority work order

> **For Claude Code.** This is a work order, not a report. Do the items **top to bottom**. Each item has a reason, the place in the code, the fix, and the test that must turn green.
> **For the owner.** Section 5 lists the decisions only you can make. Everything else can be done without you.

| | |
|---|---|
| Prepared | 2026-10-08 |
| Code | branch `dashboard-redesign`, commit `16a1637` (live on Railway) |
| Based on | `docs/qa/OrchestrAI-QA-Findings.md` (31 findings), `docs/ux/OrchestrAI-UX-Audit.md`, the test suite in `tests/qa/`, and the two live database copies you supplied (Godrej, Baanganga) |
| Rule of the launch | Fix what the **live setup can hit today**. Leave the rest for later. Small changes only. |

---

## 0. Rules for Claude Code (read first)

1. **One item = one commit.** The commit must include the code change and the test flip (remove `xfail` from the named test; it must pass).
2. **Never touch production.** Tests run on a local Postgres only:
   ```bash
   MIGRATE_TEST_PG=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest tests/qa -q
   ```
   The routing dump you were given contains **live database addresses with passwords**. Never load it, never copy it, never use it. The harness builds its own routing database.
3. **No refactors.** Change only what the item says. If the fix needs a database migration, **stop and ask** (none of the P0 items needs one).
4. **After every item** run the new tests and the whole existing suite (`python -m pytest -q`). Nothing that passed before may fail.
5. **Do not deploy** until the owner says so. When asked, use the clean-worktree deploy recipe from memory, then run the smoke checklist in section 6.
6. **Test-first for the new tests** named "write": add the test (expected to fail), then fix, then remove the `xfail`.
7. Update the status line of the finding in `docs/qa/OrchestrAI-QA-Findings.md` (VERIFIED → FIXED, with the commit).

**Where the tests are.** `tests/qa/test_10_pure.py`, `test_20_confirm_and_approval.py`, `test_30_identity_otp_telegram.py`, `test_40_webhooks.py` have been run: 55 pass, 56 are known bugs kept as expected failures (`xfail(strict=True)`, tagged with the bug ID). `test_50_scheduler_and_reports.py` is written but **has not been run yet**. **Step 0:** run it, fix mistakes in the test only, and note the result.

---

## 1. What your live data says (why this order)

Counts and settings only. No personal data was read or copied.

| Fact (from the live copies) | Why it matters |
|---|---|
| **Godrej** is on Telegram: 17 people, **only 6 linked** to Telegram, 6 roles (admin, committee, member, owner, staff, tenant), 32 cases of which **16 are open and unassigned**, 44 flows (37 are small building blocks), 651 chat turns in 8 weeks | Small, real, and busy enough that bugs will be met in the first week |
| Godrej **case reminders are ON**: 30 of 32 cases already reminded and 26 already marked late | The reminder job is a live feature. Its failure mode (QA-011) is live too |
| **Baanganga** is on WhatsApp: 5 people, 27 invoices, 13 orders; 2 active **WhatsApp** scheduled reports (daily 20:58, Monday 09:00) | WhatsApp drops bot-started messages after 24 h of silence (QA-012) |
| Baanganga's invoice and quotation flows already contain **approval and OTP steps**, but **no gates and no limits are set**. **No approval has ever been requested** in either database | Money flows have no protection switched on today. The approval code crashes (QA-032), so the day a limit is set it fails |
| Live yes/no words, same in both: `yes, y, haan, ha, ok, confirm, go ahead, proceed, 👍` and `no, n, na, nahi, cancel, stop, reset…` | "yes but make it 5000" confirms the old values, "no problem, go ahead" cancels (QA-007) |
| At Godrej the role **owner** (flat owners) can read the `residents` table. Columns `first_owner_mobile` and `brokers_name` are **not** in the hidden-column list. The guard accepts `SELECT first_owner_mobile FROM residents` | A resident can ask the bot for other residents' mobile numbers (**QA-033, new**) |
| Godrej `admin` and Baanganga `owner` can read `users` | Phone and e-mail can leave inside one JSON value (QA-008) |
| `case_pass_on` failed 2 of 9 times on 7 Oct, both with a **list** of case numbers: "No cases record found matching 'CS-…, CS-…'" | People will try to assign many cases at once; the chat flow cannot |
| No phone number is in both organisations; no schedule on day 29 to 31 or at midnight; no stale drafts; no duplicate cases | These bugs are real but **not live today** (QA-020, QA-010, QA-016, QA-003 not yet seen) |
| 64% of Godrej and 70% of Baanganga chat-log rows have no session id | We cannot trace failures (QA-022) |
| `sheets_creds_b64.txt` is **tracked in git** and the GitHub repo is public. Both live database passwords were shown in this conversation through the routing dump | Rotate them (P0-1, owner) |

**Priority words**

| | Meaning |
|---|---|
| **P0** | The live setup can hit it **today**. Fix before launch. |
| **P1** | Latent: it needs a feature switched on, or more people. Fix in the first two weeks. |
| **P2** | Later. Design work or very low chance. |

---

## 2. P0: fix before launch

Order of work: **P0-1 → P0-8 → P0-4 → P0-6 → P0-5 → P0-3 → P0-2 → P0-7.** Cheap and certain first; the changes that touch the chat handler (P0-5, P0-6) after the small ones are safe.

### P0-1 · Close the open doors &nbsp; `QA-015` `QA-002` + secrets &nbsp; · effort S (half a day)

**Why.** Anyone on the internet can call `GET /debug/schema/{key}` (lists every table and column of a client) and `GET /health` (makes paid OpenAI and Cerebras calls on every request, so it can be used to burn money). The Telegram webhook accepts forged updates when `TELEGRAM_WEBHOOK_SECRET` is empty, and identity is just the chat number.

**Code (Claude Code).**
- `app/main.py:58-87`: remove `/debug/schema/{source_key}` and `/debug/clear-schema-cache`, or require the admin sign-in.
- `app/main.py:123-150`: make `/health` cheap (process, database, Redis only; no model calls). Put the model checks behind a protected `/health/deep`.
- `app/routers/telegram_webhook.py:22,31-34`: if the secret is empty, **refuse** every update (fail closed) and log one clear error at start-up.

**Owner (not code).**
- Rotate the two Railway database passwords, then update `data_sources.database_url` and the service variables. They were shown in this conversation.
- Rotate the Google service key, then remove `sheets_creds_b64.txt` from the repo (public) and from history.
- Delete the unused `ADMIN_TOKEN` variable.
- Check that `TELEGRAM_WEBHOOK_SECRET` is set on Railway (say yes or no; never paste the value).

**Done when.** `test_A16_telegram_updates_are_refused_when_no_secret_is_configured` passes without `xfail`. Write: `test_I02_debug_routes_need_a_sign_in`, `test_I03_health_makes_no_paid_calls` (patch the OpenAI client, assert zero calls).

### P0-8 · Approval gate crash &nbsp; `QA-032` (new) &nbsp; · effort S (two lines)

**Why.** `db.execute` returns asyncpg's status text (`"INSERT 0 1"`). The approval code then reads `approval_row[0]["id"]` and raises `TypeError`. The approval row is saved, the approver is **never asked**, the draft is cancelled and the requester is told "I couldn't save that". It is not hit today (no gate is set anywhere), but Baanganga's invoice flows were built for it. Fix it **before** any limit is set, and it unlocks the tests for QA-004, QA-017, QA-019 and QA-028.

**Code.** `app/services/step_interpreter.py:923-939` and `app/executor/workflow_executor.py:185-201`: use `fetch_one(... RETURNING id ...)` instead of `execute`.

**Done when.** `test_D27_the_approval_gate_asks_the_approver_and_tells_the_requester_it_was_sent` passes. Then remove the `w.use_returning_fix()` work-around from `start_big_request` in `test_20_...` and from `test_D17_...`; all approval tests must still behave.

### P0-4 · Reminder storm &nbsp; `QA-011` &nbsp; · effort S

**Why.** Reminders are live. `telegram.send_text` raises on any non-200 answer (`app/services/telegram.py:64`), for example when a person has blocked the bot. In `_run_case_notification_pass` that exception ends the whole pass **before** the case is marked as sent. The same person is messaged again every minute, and every later case never gets its reminder. A bad template (`{unknown}`) does the same with `KeyError`.

**Code.** `app/scheduler/jobs.py:288-420`: wrap each case in its own `try/except`; mark the case as sent after the first successful send (or after 3 failures, with an error log); send the complainant message in its own `try`; use a safe formatter (`format_map` with a default) and log the bad template once.

**Done when.** `test_H05_one_reminder_that_cannot_be_sent_does_not_block_or_repeat_the_others` and `test_H05b_a_bad_message_template_does_not_stop_the_pass` pass (in `test_50`, run step 0 first).

### P0-6 · "Yes, but…" and "cancel invoice" &nbsp; `QA-007` `QA-024` &nbsp; · effort S–M

**Why.** `matches_vocab` accepts a message that **starts with** a confirm word, so "yes but make it 5000" saves the old values and "no problem, go ahead" cancels. Any message of 3 words or fewer containing "cancel" wipes the draft and the chat history ("cancel invoice INV-1"). On Baanganga that is wrong money; on Godrej a wrong case.

**Code.** `app/services/vocabulary.py:37-53`, `app/routers/webhook.py:1162-1188, 1357, 1421`.
- A message **confirms** only if it is a confirm word or phrase, optionally followed by punctuation or a short polite filler from a new setting `vocabulary.filler_words` (for example `please`, `thanks`, `ji`, `save it`). Anything else goes to the agent as a correction.
- A message **cancels** only if it is exactly a cancel word or token (plus punctuation). "cancel <thing>" goes to the agent. Wipe history only on a real cancel.
- **Keep** "yes save it" working: the old docstring explains it broke live once.

**Done when.** `test_C03`, `test_C04`, `test_C05`, `test_C06` (pure) and `test_C07` pass; `test_C_plain_confirmations_confirm`, `test_C08`, `test_C09` still pass. Add `yes save it` and `ok thanks` to the confirm tests.

### P0-5 · One message at a time per person &nbsp; `QA-003` `QA-021` &nbsp; · effort M

**Why.** Two "yes" at once both read the draft and both run every step (two cases, two invoices). Two quick messages each read the session, wait for the model, and write back, so the second erases the first. Chat apps retry and people double-tap.

**Code.** In `handle_message` / `_handle_message` (`app/routers/webhook.py`: the session is read at line 1155 and written at 1553 and 1627; the Telegram route calls the same function), hold a **per-person Redis lock** (`SET key NX PX 60000`) for the whole turn. A second message waits up to about 10 seconds, then answers "one moment, I'm still on your last message". Release in `finally`. On confirm, also claim the draft atomically (`UPDATE user_drafts SET stage='executing' WHERE … AND stage='awaiting_confirmation' RETURNING …`) so a retry cannot run it twice. One lock fixes both findings.

**Done when.** `test_C01_two_yes_at_once_run_the_action_once` and `test_C11_two_quick_messages_both_stay_in_the_conversation` pass. Controls stay green. Add a Telegram version of C01.

### P0-3 · The bot must not leak personal data &nbsp; `QA-033` (new) `QA-008` &nbsp; · effort M

**Why.** The guard hides columns **by name** (`phone`, `email`, …) and the caller strips them **by name** from results. So: `to_jsonb(u)` and `row_to_json(users)` return phone and e-mail in one value; `WHERE phone = '+91…'` finds a person by number; and at Godrej `first_owner_mobile` and `brokers_name` are not hidden at all, while the role `owner` can read `residents`.

**Code.** `app/services/sql_guard.py:123-224` (`prepare`) and the caller block in `app/services/agent.py:1307-1400`.
1. Hidden columns become a setting, `orgs.settings.ai_sql.hidden_columns`, merged with the built-in list, and extended by pattern (`*phone*`, `*mobile*`, `*email*`, `password*`, `*otp*`).
2. Refuse whole-row functions (`to_json`, `to_jsonb`, `row_to_json`, and a bare table alias as a function argument).
3. Refuse a hidden column anywhere in the query, not only in the SELECT list (WHERE, JOIN, ORDER BY, GROUP BY).
4. Add the new hidden names to the Godrej and Baanganga settings by **data change after approval**, not by migration in code.

**Done when.** `test_G03`, `test_G04`, `test_G05`, `test_G10b` (pure) and the three end-to-end versions in `test_50` pass. Write `test_G_owner_cannot_read_resident_mobile_numbers` (it must fail first, then pass). Keep every `refused` test and `test_G_control_...` green.

### P0-2 · A stranger on Telegram must not become admin &nbsp; `QA-001` &nbsp; · effort S–M

**Why.** Telegram bots are public. Anyone who finds the bot can send any e-mail address they own, pick a role from **every** role of the organisation (at Godrej: including `admin`, which can run all case flows and read `users`), type "yes", read the code from their own mailbox, and become an active user. Nobody approves. Proven end to end by `test_B03`.

**Code.** `app/routers/webhook.py:491-495` (role list) and `721-731` (insert). Offer only the roles in a new setting `orgs.settings.self_registration.roles`. **If the setting is missing, self-registration is off** and the person is told to ask their admin. See decision 1 in section 5.

**Done when.** `test_B03_a_stranger_on_telegram_cannot_register_themselves_as_admin` passes; `test_B_control_a_stranger_can_register_as_a_member` still passes (it picks the role by number; update the number or the setting in the test).

### P0-7 · Make WhatsApp failures visible &nbsp; `QA-012` (visibility only) &nbsp; · effort S

**Why.** After 24 hours without a message **from the person**, WhatsApp accepts a bot-started message and never delivers it. Baanganga has two WhatsApp scheduled reports. The webhook throws the delivery report away (`webhook.py:112-114`), `send_text` only checks the HTTP status (`app/services/whatsapp.py:24-37`), and the flow says "completed successfully". Seen live on 7 Oct.

**Code (this item).** Handle `statuses` in the webhook. For `status == "failed"` log an **ERROR** with Meta's error code, the message id and the last 4 digits of the recipient. Nothing else changes. The real cure (an approved template, and holding the message until the person writes) is **P1** and needs the owner to create the template in Meta.

**Done when.** Write `test_L_a_failed_delivery_report_is_logged_as_an_error` (post a signed `statuses` payload with `status: failed`, assert an ERROR record).

---

## 3. P1: first two weeks

| # | What | Why now | Fix idea | Tests |
|---|---|---|---|---|
| P1-1 | **Approval family** `QA-004` `QA-017` `QA-019` `QA-028` | Latent until a limit is set. After P0-8 they can finally be tested | Update the approval row with `WHERE status='pending'`; resume from the version that was approved; tell the requester when nobody can approve; close the draft on reject | `test_D20`, `test_D26`, `test_D17`, `test_D19` |
| P1-2 | **One transaction per workflow run** `QA-005` | Live flows have 9 to 14 steps; a failure at step 7 leaves 6 steps written and "please try again" repeats them | Put the connection in a `ContextVar` inside `db.py` so every helper in a run uses one transaction; send messages after commit | `test_D14` |
| P1-3 | **Old "yes"** `QA-006` | A "yes" two hours later runs an old draft | Apply the staleness check to confirm words too | `test_C02` |
| P1-4 | **Schedules** `QA-010` | Day 29 to 31 and midnight break; a monthly report would repeat every minute | Clamp the day to the month length; treat hour 0 as a real hour | `test_H07`, `test_H08`, `test_H09`, `test_H10`, the property test |
| P1-5 | **WhatsApp template** `QA-012` | Cures the loss for Baanganga's reports | Approved Utility template; park the real message; send on the person's next reply | new |
| P1-6 | **Webhook edges** `QA-013` | More users means more batches and photos | Handle every message in a delivery; answer images, voice and stickers; set the "seen" mark only after success | `test_A08`, `test_A12`, `test_A20` |
| P1-7 | **Guards fail closed** `QA-018` | The dashboard now lets people edit conditions (`and` already appears in two switched-off blocks) | Refuse unknown operators when saving; unknown means "do not run"; support `and` and `or`; read "1,00,000" | `test_D01` to `test_D08` and the property tests |
| P1-8 | **Codes** `QA-014` | Cheap | `secrets` instead of `random`; atomic attempt counter | `test_B13`, `test_B14` |
| P1-9 | **Trace and truth** `QA-022` | Two thirds of chat-log rows cannot be traced | Set the correlation id on the WhatsApp path; log the real outcome of agent turns | write |
| P1-10 | **Dates in India** `QA-025` | Case numbers use `{YY}-{MM}` from the server clock (UTC) | Owner sets `TZ=Asia/Kolkata`; use the IST date in `step_interpreter` | write |
| P1-11 | **Assign many cases** (product) | 2 of 9 `case_pass_on` runs failed on a list of numbers | Accept several numbers, or say plainly "send one case number at a time" | write |
| P1-12 | **Stored report SQL** `QA-009` | The old regex guard can be bypassed by a comma join; authors are the team only | Run stored SQL through `sql_guard` | `test_G12`, `test_G12b` |
| P1-13 | **Finish the suite** | Many catalogue cases are still not run (see the findings file, section 7); groups E, F, K, L, M are open | Run `test_50`, then add tests for K03/K04/K05/K08 (scripted model), L02/L03/L06, M01 to M03 | see the findings file, section 7 |

---

## 4. P2: later

`QA-016` dead draft returns · `QA-020` one phone in two organisations (none today) · `QA-023` SQL text in `sequence.field` · `QA-026` Telegram edited message and callback without a message · `QA-027` document-number race (a unique rule already stops duplicates) · `QA-029` two pools on first call · `QA-030` HTML in the code e-mail · `QA-031` anyone can learn which organisation keys exist.

---

## 5. Decisions only the owner can make

| # | Decision | Needed for | Suggested answer |
|---|---|---|---|
| 1 | Which roles may self-register on Telegram, and does an admin approve them? | P0-2 | `tenant`, `owner`, `member` only; every other role is added by an admin in the dashboard |
| 2 | Should the role `owner` read `residents` through the bot at all? | P0-3 | No. Remove it from the role |
| 3 | Is `TELEGRAM_WEBHOOK_SECRET` set on Railway? | P0-1 | Yes or no; never paste the value |
| 4 | Rotate the two database passwords and the Google key now? | P0-1 | Yes, today |
| 5 | Baanganga: should invoices and quotations above some amount need approval or an OTP? | P0-8 context | Decide a limit, then set the gate **after** P0-8 is live |
| 6 | Create a WhatsApp **Utility** template for scheduled reports in Meta | P1-5 | Yes; Claude Code will give the exact text |
| 7 | Set `TZ=Asia/Kolkata` on Railway | P1-10 | Yes |

---

## 6. Launch gate and smoke check

**Launch gate.** All P0 tests pass with the `xfail` removed. The whole existing suite passes. The owner has answered decisions 1 to 4.

**After deploy, read-only smoke check (10 minutes, live).**
1. Telegram: send `/status` as a known person. Expect an answer.
2. Send the same message from a number that is not registered. Expect the onboarding text, and **no admin role offered** (P0-2).
3. Open `/debug/schema/godrej` and `/health`. Expect "not found" or a sign-in request, and a fast `/health` (P0-1).
4. Godrej: confirm a draft with "yes but …". Expect a question, not a save (P0-6).
5. Baanganga: look in the logs for a **failed delivery** line the next time a report is sent after 24 h of silence (P0-7).
6. Watch the log for one reminder pass. Expect no repeated message to the same person (P0-4).

---

## 7. Not in this order, and why

Model behaviour (groups E and K), PDFs (F) and performance (M) need a live model, real documents or a stated budget. They are listed as **blocked or not reached** in `docs/qa/OrchestrAI-QA-Findings.md`, section 7. They do not block launch.
