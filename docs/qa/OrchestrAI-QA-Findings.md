# OrchestrAI: QA review, findings so far

Prepared 2026-10-08. Code reviewed: branch `dashboard-redesign`, commit `16a1637` (the version live on Railway at that time).
Updated the same day: the use-case catalogue (section 7) and finding QA-031 were added.
Nothing in the application was changed. Nothing ran against production. Everything below was found by reading the code
and by running small checks on this computer only.

---

## 1. How to read this document

**Status of the work (honest version)**

| Phase | State |
|---|---|
| 0. Map the system | Done for the chat side (webhooks, identity, drafts, confirm/cancel, codes, approvals, workflow engine, SQL guards, scheduler, cleanup). Not yet mapped in depth: the chat workflow builder (`workflow_builder_agent`, `workflow_publisher`, `workflow_compiler`), PDF/Excel, Google Sheets. |
| 1. Risk matrix | Done (section 4). |
| 2. Test harness | Built and working: throwaway Postgres databases from schema-only dumps, fake Redis, fake WhatsApp / Telegram / email / LLM, network blocked. 2 smoke tests pass. |
| 3. Test catalogue | Written out in section 7 as 170 numbered cases in 14 groups (A to N). 38 were run (30 showed a bug, 8 behaved); the rest are judged from the code, not examined yet, or need a live model or an answer from the owner. 11 findings are VERIFIED (run or seen live) and the other 20 are reasoned from the code; each of those has a planned test in section 8. |
| 4. Report | This file. It will be refreshed as tests are added. |
| 5. Fixes (2026-10-08) | The eight launch blockers (P0-1 to P0-8) are fixed, tested (full suite green) and LIVE as Railway deployment 5e0c2809: QA-001, 002, 003, 007, 008, 011, 015, 021, 024, 032 and 033 are FIXED, QA-004 and QA-012 are PARTLY fixed. The five small database changes (core-0012 to core-0015 on both clients, housing-0005 on Godrej) were applied after a backup. What is left is in docs/launch/QA-priority-work-order.md (P1 and P2). |

**Labels**

* **VERIFIED**: the behaviour was reproduced by running the application's own code. The quick-check script and its output are in section 10.
* **SUSPECTED**: reasoned from reading the code, with file and line. Not yet reproduced by a test.
* Where a bug is VERIFIED only at function level, the line says so; the end-to-end effect is then SUSPECTED.

**Severity**

* **S1**: data loss, wrong money or a message to the wrong person, tenant leak, someone gets access they should not have.
* **S2**: a core flow is broken or a person is stuck.
* **S3**: wrong behaviour that has a workaround.
* **S4**: cosmetic or wording.

**Scope notes from the owner**: admin authentication and database passwords were "known and deferred". Dashboard sign-in has since been built (7 Oct 2026) and is not reviewed here. Database passwords are out of scope.

**Rules followed**: tests use only a Postgres on this computer (the harness refuses any other host), fake Redis, and fakes for WhatsApp, Telegram, email and the model. Only synthetic data. No application file was edited; proposed fixes are given as diffs in section 6 and are **not applied**.

---

## 2. Summary

### 2.1 Counts

| Severity | Count | Of which VERIFIED |
|---|---|---|
| S1 | 7 | 2 (QA-002 is conditional on a setting, QA-007) |
| S2 | 15 | 5 |
| S3 | 7 | 4 |
| S4 | 2 | 0 |

(31 findings in all, 11 of them VERIFIED, section 5. Where a finding says "S2/S3", the first one is counted. Several S1/S2 items share one root cause, listed in 2.3.)

### 2.2 Top 10 to look at first

1. **QA-001 (S1)**: on Telegram, a stranger can register themselves and choose **any role, including admin or owner**, with no approval step.
2. **QA-002 (S1 if the setting is missing)**: the Telegram webhook accepts forged messages when `TELEGRAM_WEBHOOK_SECRET` is not set. Someone who knows a person's Telegram chat number could act as them.
3. **QA-003 (S1)**: nothing stops a confirmation from running twice (two quick "yes" messages, or an edited message). Every step runs twice.
4. **QA-004 (S1)**: the same for approvals: two taps on Approve, or two approvers, run the approved action twice.
5. **QA-005 (S1)**: workflow steps are not in one transaction. When step 2 of 3 fails, step 1's rows stay, the person is told "I couldn't save that", and a retry creates the record again.
6. **QA-007 (S1)**: "yes, but make it 5000" counts as a plain yes. The old amount is saved.
7. **QA-017 (S1)**: after an approval, the workflow is re-read from the database and resumed at a stored step number. If the workflow was edited meanwhile, the approved action can be skipped while the person is told it succeeded.
8. **QA-010 (S2)**: a monthly schedule on day 29, 30 or 31 crashes the "next run" calculation. The report is then due again every minute.
9. **QA-008 (S2)**: the SQL guard for AI-written queries lets whole-row functions through, so hidden columns (phone, email) can come back inside one JSON value.
10. **QA-012 (S2, seen live)**: WhatsApp messages the bot starts itself are silently lost after 24 hours of silence from the person, and the bot reports success.

### 2.3 Top 5 systemic risks

1. **No idempotency and no locking around "do the thing"** (QA-003, QA-004, QA-021, QA-027). Chat apps retry, people double-tap, and every handler reads state, works for seconds (the AI call), and writes state back.
2. **Failures are invisible**: WhatsApp delivery reports are discarded, correlation IDs are blank, agent turns are always logged as success (QA-012, QA-022).
3. **Several safety checks fail open**: unknown `when` operators run the step, unparseable numbers skip gates, the Telegram secret is optional (QA-002, QA-018, QA-019).
4. **Free-text understanding drives control flow**: "yes ..." and "no ..." match by first word, "cancel ..." clears everything (QA-007, QA-024).
5. **Stored configuration is executed live without versioning** (QA-017, QA-016, QA-023): a workflow edit changes what already-confirmed or already-approved work does.

### 2.4 What could not be tested, and why

* **Live configuration** (cannot be read, production is off limits): whether `TELEGRAM_WEBHOOK_SECRET` is set on Railway; the real yes/no vocabulary of each organisation; which roles have `users` in `readable_tables`. Findings that depend on these say so.
* **LLM behaviour** (catalogue K, most of E): needs a live model. Only the code around the model (loop limit, fallback ladder, guards) can be tested with a scripted fake. Prompt-injection and language-quality tests need a model and a judge.
* **PDF / Excel / Sheets** (F): not yet reached. WeasyPrint and Google libraries not exercised.
* **Performance** (M) and a long soak: planned, not run.

---

## 3. System map

### 3.1 Components and entry points

| Entry point | Code | What it does |
|---|---|---|
| `POST /webhook/whatsapp` | `app/routers/webhook.py:99` | Checks the Meta signature, drops status updates, de-duplicates by message id (Redis, 300 s), then `handle_message`. |
| `GET /webhook/whatsapp` | `webhook.py:86` | Meta's one-time verification (token compare in constant time). |
| `POST /webhook/telegram` | `app/routers/telegram_webhook.py:25` | Optional secret header, de-duplicates by `update_id` (Redis, 300 s), builds `tg:<chat id>`, then `handle_message`. |
| `handle_message` | `webhook.py:424` | The whole chat state machine (3.2). |
| Scheduler (in the web process) | `app/scheduler/jobs.py` | Every minute: scheduled reports, case reminders, panel key tidy; nightly: cleanup. One advisory lock per job on the routing database (`app/scheduler/locks.py`). |
| Dashboard | `app/admin_panel/*` | JSON API under `/admin/{org}/api/v2`, sign-in under `/admin/_auth`. |
| Debug and health | `app/main.py:58, 81, 90` | `/debug/schema/{source_key}`, `/debug/clear-schema-cache`, `/health` (all unauthenticated). |

### 3.2 One chat message, in order

`handle_message` (`webhook.py:441-1733`):

1. **Identity.** `resolve_identity(phone)` scans every tenant database for `users.phone = $1` (`identity.py:14`). Not found: on Telegram, the self-registration flow (3.4); on WhatsApp, "not registered".
2. **Active check.** User or organisation switched off: message and stop.
3. **Slash commands.** `/cancel`, `/start`, `/help`, `/status`, others resolved to a workflow (`webhook.py:929-999`).
4. **Security code.** If there is no `auth:<org>:<phone>` key in Redis, an emailed code is required (default 4 digits, 3 tries, 3 minutes), then the original text is replayed (`webhook.py:1013-1151`). The window is `orgs.session_ttl_minutes` (default 480).
5. **Cancel gate.** `webhook.py:1157-1188`: the exact cancel tokens, or any message of 3 words or fewer that contains the word `cancel`, clears the draft and the conversation history.
6. **History clean-up and draft rehydrate.** If Redis has no `pending_action` but `user_drafts` has an active row, the draft is rebuilt and the person is told about it (`webhook.py:1229-1266`).
7. **Approval buttons** (`action:approve:<id>` / `action:reject:<id>`, only for interactive messages) go to `handle_approval_response`.
8. **Awaiting a code** for a pending action: `verify_otp`, then `execute_pending_action(otp_verified=True)`.
9. **Awaiting confirmation** (`webhook.py:1355-1480`): a message that starts with a confirm word executes **at once**. A cancel word cancels. Anything else: if the draft is older than the confirmation window (10 min default) it is dropped; otherwise it is treated as a correction and falls through to the agent.
10. **Agent turn.** `run_agent` (up to 6 tool iterations), then the reply is sent and one `audit_log` row is written with outcome `success` (`webhook.py:1580-1676`).

### 3.3 State tables

**Draft** (`user_drafts.stage`, check constraint) and the chat's copy (`session:<org>:<phone>` → `pending_action.stage`)

| From | Event | To | Notes |
|---|---|---|---|
| none | agent opens a request | `collecting` | `upsert_draft`; one active draft per user (unique index). |
| `collecting` | all fields present | `awaiting_confirmation` | |
| `awaiting_confirmation` | reply starts with a confirm word | runs steps; `done` (draft closed after the steps) or error (`cancelled`) | **No staleness check on this path.** Draft is closed only after the steps ran (`action_executor.py:88-95`). |
| `awaiting_confirmation` | reply starts with a cancel word | `cancelled` | |
| `awaiting_confirmation` | anything else | back to `collecting` (correction) | `reprompt_count` is capped (default 3), then the draft is cleared. |
| `awaiting_confirmation` | OTP gate hit | `awaiting_otp` (session only) | `resume_step` stored in the session. |
| `awaiting_confirmation` | approval gate hit | `awaiting_approval` (session only) | `resume_step` stored in `pending_approvals.context`. |
| any open | no activity | rows have `expires_at` (session TTL); stale collecting drafts (30 min) are dropped by the agent | Finished rows are removed by the nightly cleanup. |

**Security code** (`otp_tokens`): `generate_and_send_otp` (cool-down 60 s, old unused codes marked used) → `verify_otp` (latest unused code, attempt counter, expiry, hash compare) → used.

**Approval** (`pending_approvals.status`): `pending` → `approved` / `rejected`. Multi-level: approving level N inserts level N+1 and notifies that approver; the workflow resumes only when the last level clears (`workflow_executor.py:174-296`). Rejection informs the requester only (`161-172`).

**Telegram sign-up** (`session:tglink:<phone>`): email → (match: code to the email on file) or (no match: `awaiting_new_user_name` → `awaiting_new_user_role` → `awaiting_new_user_confirm` → INSERT user → code to the typed email → `awaiting_link_otp` → bound).

**Workflow run** (`run_workflow_steps`): permission gates, then each step in order; a step is skipped when its `when` guard is false; a gate step halts with a `resume_step`; a failure raises and the run stops with no rollback. Blocks (`run_workflow`) are limited to depth 5 and cannot contain gates; a call cycle is refused (`step_interpreter.py:1569-1655`).

### 3.4 Shared mutable state

| Where | What | Scope |
|---|---|---|
| Redis `msg_processed:<wamid>`, `tg_processed:<update_id>` | duplicate guard, 300 s | global |
| Redis `session:<org>:<phone>` | conversation history, `pending_action`, state | per tenant and phone |
| Redis `session:sec:<org>:<phone>` | waiting for the security code (180 s) | per tenant and phone |
| Redis `session:tglink:<phone>` | Telegram sign-up | per phone (before identity is known) |
| Redis `auth:<org>:<phone>` | signed-in window | per tenant and phone |
| Redis `photos_held:<org>:<phone>` | photos sent before a request | per tenant and phone |
| Process memory caches | schema allow-list (`step_interpreter`), schema text (`agent._schema_cache`), SQL guard policy and scoped tables (10 min / 30 s), vocabulary (per org, process lifetime), config store, case categories, party access, column types | per source key or org |
| Postgres per tenant | users, roles, workflows, drafts, cases, approvals, codes, audit | one database per tenant; routing database lists them |

### 3.5 External dependencies

Meta WhatsApp Cloud API, Telegram Bot API, Brevo (email), OpenAI-compatible providers through `llm_router` (ordered ladder with cool-downs: quota 15 min, server 60 s, timeout 30 s, auth 1 h; 12 s per attempt), Google Sheets, WeasyPrint, Postgres, Redis.

---

## 4. Risk matrix

Likelihood (L) and impact (I): H high, M medium, L low.

| Area | L | I | Why | First tests |
|---|---|---|---|---|
| Duplicate execution (double yes, double approve) | H | H | no idempotency; chat apps retry and people double-tap | QA-003, QA-004 |
| Telegram identity and sign-up | M | H | public bot; optional secret; role choice | QA-001, QA-002 |
| Confirmation wording | H | H | first-word matching on yes/no | QA-007, QA-024 |
| Multi-step writes | M | H | no transaction | QA-005, QA-027 |
| Approvals and gates | M | H | fail-open guards, resume by index | QA-017, QA-018, QA-019 |
| Scheduler and reminders | M | M | date maths, one bad row stops the pass | QA-010, QA-011 |
| WhatsApp delivery | H | M | 24-hour rule, reports discarded | QA-012 |
| AI and report SQL | M | M | guard gaps | QA-008, QA-009 |
| Webhook hygiene | M | M | batches, media, Redis down | QA-013 |
| Codes (OTP) | L | M | concurrency, weak generator | QA-014 |
| Tenant isolation | L | H | caches keyed by source key; phone found in first tenant that matches | QA-020 |
| Observability | H | L | blank correlation id, untruthful audit | QA-022 |
| Chat workflow builder | M | M | not yet mapped | planned |
| Documents, PDFs | M | M | not yet reached | planned |

---

## 5. Findings

Each finding: severity, status, what happens, evidence, how to reproduce or the planned test.

### S1

**QA-001 [S1] FIXED (commit b394b8a, only the roles in orgs.settings.self_registration.roles are offered; closed when none are listed; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was SUSPECTED). A stranger on Telegram can register as any role, including admin.**
* Area: B identity and onboarding.
* What happens: a Telegram user who is not in `users` sends any email address. If no unlinked user has it, the bot starts self-registration: name, then a role chosen from **every role of the organisation** (`SELECT id, name FROM roles WHERE org_id = ...`, no filter), then a confirmation. It then inserts an **active** user with that role (`webhook.py:721-731`), emails a code to the address the stranger typed, and when the stranger types the code it binds the Telegram chat to the new user and marks the session authenticated (`webhook.py:785-877`). The code only proves the stranger owns the email they typed. There is no approval by an admin. For Godrej the roles include admin, committee and owner.
* Evidence: `webhook.py:452-496` (flow start and role list at `491-495`), `721-731` (insert), `785-877` (bind).
* Reproduce (planned test `test_b_telegram_self_registration_role`): `tg:555` sends an email, a name, picks "admin", says yes, reads the captured code, sends it. Expect: user created with role admin and able to run admin workflows.
* Question for the owner: is self-registration meant to offer every role? If it is meant for residents, restrict the offered roles (diff in section 6).

**QA-002 [S1 if the setting is missing] FIXED (commit 5cad6c3, the Telegram webhook refuses every update when the secret is empty; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was VERIFIED (code)). The Telegram webhook secret is optional.**
* What happens: `TELEGRAM_WEBHOOK_SECRET` defaults to an empty string and the check only runs when it is non-empty (`telegram_webhook.py:22, 31-34`). With it unset, anyone can POST a forged update with any `chat.id`. Identity is the chat id, so the sender is treated as that person, and an existing signed-in window (`auth:` key, up to 8 hours) skips the code step.
* Evidence: `telegram_webhook.py:22,31`; the quick check printed "Telegram secret check only when configured: True".
* Question for the owner: is the variable `TELEGRAM_WEBHOOK_SECRET` set in Railway (name only, not the value)?
* Fix: refuse to handle Telegram updates when it is empty (diff in section 6).

**QA-003 [S1] FIXED (commit 6a57f33, one message at a time per person (Redis turn lock) and a claim on each confirm card; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was SUSPECTED). Nothing stops a confirmation from running twice.**
* What happens: "yes" is handled by reading `pending_action` from Redis (`webhook.py:1155`), running every step, and only then closing the draft (`action_executor.py:88-95`) and removing `pending_action` (`webhook.py:1370`). Two "yes" messages close together (a double tap, a slow reply, an edited Telegram message processed as new, a Meta retry after the 5-minute duplicate window) both read the pending draft and both run all the steps. The duplicate guard only stops the *same message id*.
* Evidence: `webhook.py:1155, 1357-1388`, `action_executor.py:78-95`, `webhook.py:145-153`, `telegram_webhook.py:52` (edited messages).
* Reproduce (planned): a workflow that inserts into a table without a unique rule (for example `audit_log`); `asyncio.gather` two `handle_message("yes")`. Expect two rows.
* Fix: claim the draft atomically before running (diff in section 6).

**QA-004 [S1] PARTLY FIXED (commit 6a57f33 serialises a double tap; deciding an approval once is still P1-1; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was SUSPECTED). The same race in approvals.**
* What happens: `handle_approval_response` selects the row with `status = 'pending'` (`workflow_executor.py:61-70`), checks permissions, then updates it unconditionally (`120-130`). Two taps, or two people holding the approval permission, both pass, both mark it decided, both run the approved action, or both create the next level's row.
* Fix: `UPDATE ... WHERE id = $3 AND status = 'pending' RETURNING id` and stop if nothing was updated (diff in section 6).

**QA-005 [S1] SUSPECTED (mechanism read in code). Workflow steps are not in a transaction.**
* What happens: every database call acquires its own connection (`db.py:120-146`), so each step commits by itself. If step N of M fails, the earlier steps' rows stay, the draft is closed as `cancelled` (`action_executor.py:132-143`) and the person is told "I couldn't save that, please send your request again". Sending it again repeats the earlier steps (a second case, a second comment, a second message).
* Evidence: `db.py:120-146`, `step_interpreter.py:2039-2138`, `action_executor.py:132-160`.
* Reproduce (planned): the seeded workflow `qa_partial_fail` inserts a case then violates its own unique rule. Expect the first row to remain.

**QA-007 [S1] FIXED (commits a110d5d and 87a30cc, a yes or no must be the whole message; polite words come from orgs.settings.vocabulary.filler_words; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was VERIFIED (function level)). "yes, but ..." is a yes.**
* What happens: `matches_vocab` matches when the message *starts with* a confirm word as a whole token (`vocabulary.py:37-53`). So "yes but make it 5000", "yes, but not today", "ok no wait" confirm the **old** values; "no problem, go ahead" and "no, wait" **cancel**. The confirm branch runs before any correction handling (`webhook.py:1357`).
* Evidence: the quick check printed `matches_vocab(['yes'], 'yes but make it 5000') = True` and `matches_vocab(['no'], 'no problem, go ahead') = True`.
* Note: the actual words are per organisation (`orgs.settings.vocabulary`); the live list could not be read. The behaviour above holds for any list that contains plain "yes" and "no".

**QA-017 [S1] SUSPECTED. Resuming after approval uses the latest workflow and an old step number.**
* What happens: when an approval gate halts, the step number to resume from is stored (`step_interpreter.py:903-917`) together with a copy of the workflow in the approval row, but `execute_pending_action` ignores the copy and loads the **current** workflow by `intent_key` (`action_executor.py:48-53`), then runs it from the stored number (`78-86`). If the workflow was edited while the approval waited (a step removed, inserted or reordered) the number points at the wrong step. For example, if the gate was removed, `resume_step` is past the end, nothing runs, and the result is still "completed successfully" (`step_interpreter.py:2149-2179`).
* Reproduce (planned): create an approval for a 2-step workflow, edit it to 1 step, approve. Expect success message and no row.

### S2

**QA-006 [S2] SUSPECTED. "yes" after the confirmation window still executes.** The 10-minute staleness test (`agent._is_draft_stale`) is applied only to *unrecognised* replies (`webhook.py:1431-1449`). A confirm word runs the draft however old it is (it lives as long as the session, 8 hours by default). Prices, rates, stock and people may have changed since the preview.

**QA-008 [S2] FIXED (commit d6a4e94, no whole rows and no personal-data column anywhere in a question; the columns come from orgs.settings.ai_sql; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was VERIFIED (guard level)). The AI-SQL guard lets whole-row functions through.** `sql_guard.prepare` only checks columns that appear as `exp.Column` in the select list (`sql_guard.py:181-187`). `SELECT to_jsonb(u) FROM users u` and `SELECT row_to_json(users) FROM users` are accepted. The caller then strips sensitive columns *by result key* (`agent.py` "Strip sensitive columns" block), but the whole row arrives under one key, so phone and email inside it are returned to the model and the person. (`SELECT *` is also accepted; the caller's key stripping saves that case.) Depends on `users` (or another table with hidden columns) being in the role's `readable_tables`. A boolean count query such as `WHERE phone LIKE '+9190%'` is allowed by design and can extract a phone number one digit at a time.

**QA-009 [S2] VERIFIED (function level). The older regex guard for stored report SQL is bypassable.** `execute_query` finds tables with `\b(?:FROM|JOIN)\s+(\w+)` (`query_engine.py:135`), so `FROM cases c, users u` is seen as `{cases}` only; `_safe` passes it; result columns are removed by *name* (`155-169`), so `SELECT u.phone AS contact` comes back; a `LIMIT` anywhere in the text (even inside a column name) suppresses the automatic limit (`145`). Reachable through a stored report authored by an admin or by the workflow builder.

**QA-010 [S2] VERIFIED (function level). Monthly schedules on day 29, 30 or 31 crash and can resend every minute.** `compute_next_run` does `next_dt.replace(month=now.month + 1)` keeping the day, so day 31 into a 30-day month, or day 29 to 31 into February, raises `ValueError` (`jobs.py:84-87`). Reproduced for 31 Jan, 31 Mar and 30 Jan. In `run_scheduled_reports` the report is already delivered when the next-run calculation fails; the handler then tries again, fails again, and logs "Failed to reschedule" (`jobs.py:194-229`), leaving `next_run_at` in the past. The report is due again on every minute tick. Also: `hour` 0 (midnight) is treated as missing, so a "daily at 00:00" runs at 08:00 and weekly/monthly at 09:00 (`jobs.py:52, 60, 74`, quick check: `daily at hour 0 -> 08:00`).

**QA-011 [S2] FIXED (commit 5291cc3, a reminder that cannot be sent no longer stops the others or repeats; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was SUSPECTED). One bad reminder blocks all the others and repeats messages.** In `_run_case_notification_pass` the "sent" column is written *after* both messages (`jobs.py:366-411`), with no try/except per row. If the second send fails, or `assignee_tmpl.format(**vals)` raises on an unknown placeholder, the exception ends the whole pass: the first person is messaged again every minute and every later case in the queue never gets its reminder.

**QA-012 [S2] VISIBILITY FIXED (commit f8548d0 logs a failed delivery as an error; the cure (an approved template) is still P1-5; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was VERIFIED live (owner's test, 7 Oct 2026)). WhatsApp messages started by the bot are lost after 24 hours of silence.** The send call is accepted, the flow reports success, and the person receives nothing. Meta reports the failure later as a status update, which the webhook discards (`webhook.py:112-114`); `send_text` only looks at the HTTP status of the send (`app/services/whatsapp.py:24-37`). Affects scheduled reports, "tell this person" steps and case messages on WhatsApp (Baanganga). Telegram is not affected. Fix plan is in section 6 (log failures; then use an approved template and queue the real message).

**QA-013 [S2/S3] SUSPECTED. Webhook edge cases.** (a) Only `entry[0]`, `changes[0]`, `messages[0]` are processed, so extra messages in one delivery are lost (`webhook.py:109-120`). (b) Images, voice, stickers, WhatsApp "button" replies and captions get no reply at all (`134-143`). (c) `json.loads(raw)` is outside the `try`, and the `try` only catches `KeyError` and `IndexError` (`106, 168`), so a signed non-JSON body or a JSON list returns 500 and Meta retries. (d) The duplicate key is written *before* the message is handled (`149-153`): if the process dies mid-handling, Meta's retry within 5 minutes is dropped and the message is lost. (e) A Redis outage makes every webhook call fail with 500 (`150`), after which Meta retries. (f) The duplicate window is 300 s; a delivery retried later than that is processed again.

**QA-014 [S2/S3] SUSPECTED. Code attempts can be exceeded under concurrency; codes are short and made with `random`.** `verify_otp` reads the attempt count, then increments it in a separate statement (`otp_service.py:132-171`). Many guesses sent at once all read `attempts < max` and are all checked. Default code length is 4 and 3 tries (`orgs` defaults); the code comes from `random.randint` (`otp_service.py:80`), not `secrets` (VERIFIED by reading). The code is not tied to a purpose: any unused code verifies any gate.

**QA-016 [S2] SUSPECTED. A dead draft keeps coming back.** `execute_pending_action` returns without closing the draft when the person lacks permission or the workflow is switched off or removed (`action_executor.py:55-76`). The chat handler then drops the Redis copy (`webhook.py:1413-1418`), but the `user_drafts` row stays active, and the next message rebuilds it and shows "you have an unfinished request" (`webhook.py:1229-1266`) until `expires_at` (8 hours) or `/cancel`.

**QA-018 [S2] VERIFIED (function level). `when` guards fail open and some forms crash.** An unknown operator (a typo, or `startswith`) logs a warning and **returns True** (`step_interpreter.py:408-409`): the guarded step runs. `or` groups, nested `and`, and a condition without `field` raise `KeyError` (`368-375`). Numeric `gte/lte/gt/lt` return False when the value cannot be read as a number, for example `"1,00,000"` or `"Rs 5 lakh"` (`360-406`): a gate whose `when` is an amount test is skipped. A large negative amount (a refund) is also below any `gte` threshold, so it needs no approval. `equals 1000` does not match the number `1000.0` (strings compare as `"1000.0"` vs `"1000"`), and `equals "None"` matches a missing value. Quick-check output is in section 10.

**QA-019 [S2/S3] SUSPECTED. Approval gate edge cases.** (a) No approver found: the request row is created, the person is told it was sent, nobody is notified (`step_interpreter.py:941-967`). (b) Any user with the `approve` permission can decide an approval of any role or level (`workflow_executor.py:93-95`). (c) `f"{amount:,.0f}"` raises when the amount is a string (`step_interpreter.py:948`, `workflow_executor.py:214`), after the next level's row was already inserted. (d) A requester who has since been switched off still has the approved action executed; `is_active` is not checked (`workflow_executor.py:241-262`, `action_executor.py`). (e) The approver is picked with `LIMIT 1` and no order.

**QA-020 [S2] SUSPECTED. Identity: first tenant wins, errors are swallowed.** `resolve_identity` returns the first tenant whose `users.phone` matches; the tenant order is `SELECT source_key FROM data_sources` with no `ORDER BY` (`db.py:85-87`). The same phone in two tenants gets whichever the database lists first. A query error in a tenant (schema drift) is logged at debug level and treated as "not here" (`identity.py:87-92`), so it can show as "not registered".

**QA-021 [S2] FIXED (commit 6a57f33, the turn lock stops two quick messages erasing each other; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was SUSPECTED). Session lost-update.** The session is read before the agent call (`webhook.py:1155`, refreshed at `1553`) and written back after it, which can take many seconds (`1627-1628`). Two messages close together: the second write replaces the first one's history and `pending_action`.

**QA-027 [S2] SUSPECTED (mechanism read in code). The document-number lock does nothing.** `_op_insert_row` takes `pg_advisory_xact_lock` in its own statement on its own pooled connection (`step_interpreter.py:1057-1068`); the lock ends when that statement's transaction ends, before the number is computed (`1078-1099`) and inserted (`1110`). Concurrent inserts compute the same next number. With a unique rule (`cases (org_id, case_number)`, `invoices (org_id, invoice_number)`) one of them fails and the person sees an error; without one, numbers repeat.

### S3 and S4

**QA-015 [S3] FIXED (commit 5cad6c3, debug routes removed, /health free, /health/deep for super admins only; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was VERIFIED (route list)). Unauthenticated debug endpoints and an expensive health check.** `/debug/schema/{source_key}` lists every table and column of any tenant; `/debug/clear-schema-cache` clears a cache for anyone (`main.py:58-87`). `/health` calls OpenAI `models.list()` and the Cerebras API on every request (`main.py:123-150`), so anyone can trigger paid calls, and it is slow when a provider is slow.

**QA-022 [S3] VERIFIED (production log lines). Observability gaps.** The WhatsApp path never sets a correlation id: the live logs show `correlation_id= |` (empty) on webhook lines, and the response header `X-Request-ID` is empty (`main.py:33-44`). Agent and menu turns are always written as outcome `success` (`webhook.py:1651-1676`); only exceptions and confirm-path failures are written as `error`.

**QA-023 [S2/S3] SUSPECTED. SQL text from a workflow's `sequence.field`.** `_op_insert_row` validates table and column names from `values` (`step_interpreter.py:984`) but then uses `seq["field"]` unvalidated in a SELECT and in the INSERT column list (`1079, 1098, 1107`). It is written by whoever authors a workflow (admin or the builder), so it is a privilege boundary rather than an open door.

**QA-024 [S3] FIXED (commit a110d5d, a cancel must be the whole message; live as Railway 5e0c2809 on 2026-10-08 19:16 IST; was VERIFIED (expression)). The cancel gate catches "cancel something".** Any message of 3 words or fewer that contains `cancel` (for example "cancel invoice INV-1") clears the draft and wipes the conversation history instead of reaching a cancel workflow (`webhook.py:1162-1188`).

**QA-025 [S3] SUSPECTED. Dates use the server's clock.** `TODAY`, `TODAY+7` and the `{YY}{MM}` case-number prefix use `datetime.date.today()` (`step_interpreter.py:1002-1008, 1046`) in the server's time zone (UTC on Railway), while reports and the database use IST. Between 00:00 and 05:30 IST the date is yesterday's, and on the 1st of a month the prefix keeps the old month.

**QA-026 [S3/S4] SUSPECTED. Telegram edge cases.** An edited message is processed as a new one (`telegram_webhook.py:52`), which can run a second "yes". A `callback_query` without a `message` (inline mode) raises `KeyError` and returns 500 (`55`).

**QA-028 [S3] SUSPECTED. Approval rejection leaves the requester's draft.** On reject the requester is told, but the draft and session stay at `awaiting_approval` (`workflow_executor.py:161-172`) until they expire.

**QA-029 [S4] SUSPECTED.** `get_pool` can create two pools when two first calls overlap (`db.py:56-75`); `clear_all_sessions` uses `KEYS` (`redis_client.py:60-67`), which blocks Redis on a big keyspace.

**QA-030 [S4] SUSPECTED.** The security-code email puts the person's name and the action text into HTML without escaping (`otp_service.py:216-230`).

**QA-031 [S3] VERIFIED (route behaviour, found while auditing the dashboard on this computer). Anyone can find out which organisations exist.** `GET /admin/{org_slug}` returns the sign-in page when the key exists and a JSON `404 {"detail": "Unknown org 'x'"}` when it does not (`app/admin_panel/pages.py:50-51`). `GET /admin/_auth/org/{org_slug}` returns the organisation's **name** with no sign-in (`auth_routes.py:117-122`; answer seen: `{"key":"sunrise","name":"Sunrise Heights CHS"}`). So keys such as `godrej` or `baanganga` can be tried one by one and the client names read. No data is shown, so this is information about who the clients are, not a data leak. Fix: give the same answer for every key until the person has signed in, and show the name only after sign-in. Test case I11.

**QA-032 [S1 when a limit is set] FIXED (commit 5cf051c; live as Railway 5e0c2809 on 2026-10-08 19:16 IST). The approval gate crashed after saving the approval.** `db.execute` returns the status text (`"INSERT 0 1"`), and the code then read `approval_row[0]["id"]` and raised, so the approver was never asked, the draft was cancelled and the requester was told "I couldn't save that". Now `fetch_one(... RETURNING id ...)` is used in `step_interpreter.py` and `workflow_executor.py`. No approval had ever been requested on the live databases.

**QA-033 [S2] FIXED (commit d6a4e94 and migrations core-0014 and housing-0005; live as Railway 5e0c2809 on 2026-10-08 19:16 IST). At Godrej a flat owner could ask the chat bot for other residents' mobile numbers.** The role `owner` can read the `residents` table and `first_owner_mobile` and `brokers_name` were not hidden. The columns that are personal data are now listed by the organisation (`orgs.settings.ai_sql.hidden_columns` and `hidden_column_patterns`) and refused anywhere in a question, on top of a small built-in minimum.


---

## 6. Proposed fixes (diffs, NOT applied, NOT tested)

Shown as unified diffs against `16a1637`. Each is small and meant to be applied one at a time with its test.

**QA-002: fail closed when the Telegram secret is missing**
```diff
--- a/app/routers/telegram_webhook.py
+++ b/app/routers/telegram_webhook.py
@@ async def telegram_webhook(
-    # Verify secret token if configured
-    if TELEGRAM_WEBHOOK_SECRET and not hmac.compare_digest(
-        x_telegram_bot_api_secret_token or "", TELEGRAM_WEBHOOK_SECRET
-    ):
-        return Response(status_code=403)
+    # The secret is required: without it anyone could post a forged update.
+    if not TELEGRAM_WEBHOOK_SECRET or not hmac.compare_digest(
+        x_telegram_bot_api_secret_token or "", TELEGRAM_WEBHOOK_SECRET
+    ):
+        return Response(status_code=403)
```
(Set the variable in Railway and re-register the webhook with `secret_token` first.)

**QA-003: claim the draft before running it**
```diff
--- a/app/services/draft_store.py
+++ b/app/services/draft_store.py
+async def claim_draft(org_id, user_id, source_key: str) -> bool:
+    """Take the active draft for execution. True for exactly one caller."""
+    row = await fetch_one(
+        "UPDATE user_drafts SET stage = 'done', updated_at = now(), expires_at = now() "
+        "WHERE org_id = $1 AND user_id = $2 AND stage = 'awaiting_confirmation' "
+        "AND expires_at > now() RETURNING id",
+        org_id, user_id, source_key=source_key,
+    )
+    return row is not None
--- a/app/routers/webhook.py
+++ b/app/routers/webhook.py
@@ confirm branch (before execute_pending_action)
+            from app.services.draft_store import claim_draft
+            if not await claim_draft(user["org_id"], user["user_id"], user["source_key"]):
+                await send_text(phone, await say(user["source_key"], "draft.none"))
+                return
```
(If the steps then fail, reopen the draft with `upsert_draft(stage="awaiting_confirmation")` so the person can retry; this needs a small follow-up.)

**QA-004: decide an approval once**
```diff
--- a/app/executor/workflow_executor.py
+++ b/app/executor/workflow_executor.py
@@
-    await execute(
-        """
-        UPDATE pending_approvals
-        SET status = $1, decided_by = $2, decided_at = NOW()
-        WHERE id = $3
-    """,
-        new_status, user["user_id"], approval["id"],
-        source_key=user["source_key"],
-    )
+    done = await fetch_one(
+        """
+        UPDATE pending_approvals
+        SET status = $1, decided_by = $2, decided_at = NOW()
+        WHERE id = $3 AND status = 'pending'
+        RETURNING id
+    """,
+        new_status, user["user_id"], approval["id"],
+        source_key=user["source_key"],
+    )
+    if not done:  # someone else decided it a moment ago
+        await send_text(phone, await say(user["source_key"], "approval.already_handled"))
+        return
```

**QA-007: a confirmation must be only a confirmation**
```diff
--- a/app/services/vocabulary.py
+++ b/app/services/vocabulary.py
+def matches_exactly(text: str, words: frozenset) -> bool:
+    """True when the whole message (ignoring case, spaces and ending punctuation) is one of the words."""
+    t = re.sub(r"[\s.!?,]+$", "", text.strip().lower())
+    return bool(words) and t in {w.lower() for w in words}
--- a/app/routers/webhook.py
+++ b/app/routers/webhook.py
-        if matches_vocab(text, vocab["confirm_words"]):
+        if matches_exactly(text, vocab["confirm_words"]):
```
A message that only *starts* with a yes word then goes to the correction path, which is what the person meant. Keep the prefix rule for the cancel words only if the owner wants "no, cancel it" to cancel.

**QA-010: month arithmetic and midnight**
```diff
--- a/app/scheduler/jobs.py
+++ b/app/scheduler/jobs.py
-        hour = int(row.get("hour") or 8)
+        hour = 8 if row.get("hour") is None else int(row["hour"])
@@ monthly
-        if next_dt <= now_ist:
-            if now_ist.month == 12:
-                next_dt = next_dt.replace(year=now_ist.year + 1, month=1)
-            else:
-                next_dt = next_dt.replace(month=now_ist.month + 1)
+        if next_dt <= now_ist:
+            year, month = (now_ist.year + 1, 1) if now_ist.month == 12 else (now_ist.year, now_ist.month + 1)
+            day = min(int(row.get("day_of_month") or 1), calendar.monthrange(year, month)[1])
+            next_dt = next_dt.replace(year=year, month=month, day=day)
```
(Apply the same `is None` rule to the weekly and monthly `hour` lines at 60 and 74.) Also compute and save the next run **before** sending, so a failure in the calculation cannot cause a repeat.

**QA-018: unknown `when` operators must fail closed**
```diff
--- a/app/services/step_interpreter.py
+++ b/app/services/step_interpreter.py
-    logger.warning(f"Unrecognised 'when' guard, running step anyway: {cond}")
-    return True
+    logger.error(f"Unrecognised 'when' guard, refusing to run the step: {cond}")
+    raise StepError(f"A step has a condition this engine does not understand: {sorted(cond)}")
```
and support `or`, nested groups and a missing `field` explicitly in `_step_enabled`.

**QA-014: atomic attempts and a proper random source**
```diff
--- a/app/services/otp_service.py
+++ b/app/services/otp_service.py
-import random
+import secrets
@@
-    otp = str(random.randint(10 ** (otp_length - 1), 10**otp_length - 1))
+    otp = str(10 ** (otp_length - 1) + secrets.randbelow(9 * 10 ** (otp_length - 1)))
```
and count the attempt first in one statement, `UPDATE otp_tokens SET attempts = attempts + 1 WHERE id = $1 AND used = false AND attempts < $2 RETURNING attempts`, refusing when it returns no row. Consider a default length of 6.

**QA-001: only some roles may self-register**
```diff
--- a/app/routers/webhook.py
+++ b/app/routers/webhook.py
-                    "SELECT id, name FROM roles WHERE org_id = ("
-                    "SELECT id FROM orgs WHERE is_active = true LIMIT 1) ORDER BY name",
+                    "SELECT id, name FROM roles WHERE org_id = ("
+                    "SELECT id FROM orgs WHERE is_active = true LIMIT 1) "
+                    "AND COALESCE((SELECT settings -> 'self_register_roles' FROM orgs WHERE is_active = true LIMIT 1) ? name, false) "
+                    "ORDER BY name",
```
(Needs a setting such as `orgs.settings.self_register_roles = ["tenant", "member"]`; with none set, self-registration offers nothing and the person is told to ask an admin. The wording of the SQL is illustrative; an equivalent Python filter is fine.)

**QA-012: see delivery failures, then queue**
1. In the webhook, instead of ignoring `statuses`, log every entry whose `status` is `failed` with Meta's `errors[0].code` and the masked recipient.
2. Remember each person's last inbound time (a Redis key with a 24-hour TTL is enough). When it is missing, send one approved template ("You have a new update from {{1}}. Reply to read it."), keep the real message, and send it when the person next writes.

**QA-015: remove or protect the debug routes**: delete `/debug/schema/{source_key}` and `/debug/clear-schema-cache`, or put them behind the dashboard's super admin sign-in; make `/health` report local checks only (database, Redis, scheduler), and move the provider checks to a separate protected route.

---

## 7. Use-case catalogue (A to N) with test cases

This is the catalogue from the brief, written out as numbered test cases. Every case says what to do, what should happen, and what is known today. Cases are **designed to be run on the local harness** (`tests/qa/`); the status column says how far each one got.

**Status words**

| Status | Meaning |
|---|---|
| `RUN-FAIL` | Run on this computer against the application's own code (or seen live). The behaviour is wrong. This is VERIFIED. |
| `RUN-PASS` | Run. The behaviour is right. |
| `READ-FAIL` | Judged wrong from reading the code, with file and line in section 5. Not run yet (SUSPECTED). |
| `READ-OK` | Judged fine from reading the code. Not run. |
| `NOT RUN` | Designed, not examined yet. |
| `BLOCKED` | Cannot be done without something we do not have (a live model, production access, an answer from the owner). |

"Run" below means `RUN-FAIL` plus `RUN-PASS`. Only two harness tests exist so far (they pass); the other runs are the quick-check script (section 10) and the one live test the owner did.

**Coverage by group** (cases designed, and what is known today)

| Group | Cases | Run | RUN-PASS | RUN-FAIL | READ-FAIL | READ-OK | NOT RUN | BLOCKED |
|---|---|---|---|---|---|---|---|---|
| A. Webhook ingestion | 21 | 1 | 0 | 1 | 12 | 3 | 5 | 0 |
| B. Identity and onboarding | 17 | 1 | 0 | 1 | 7 | 4 | 5 | 0 |
| C. Draft, confirm and cancel | 15 | 5 | 0 | 5 | 6 | 0 | 4 | 0 |
| D. Workflow engine | 26 | 10 | 2 | 8 | 10 | 3 | 3 | 0 |
| E. Chat workflow builder | 11 | 0 | 0 | 0 | 0 | 2 | 7 | 2 |
| F. Documents and PDFs | 7 | 0 | 0 | 0 | 0 | 0 | 7 | 0 |
| G. Data layer | 19 | 9 | 5 | 4 | 2 | 4 | 4 | 0 |
| H. Scheduler | 12 | 4 | 0 | 4 | 3 | 2 | 3 | 0 |
| I. Admin API | 11 | 4 | 1 | 3 | 0 | 2 | 4 | 1 |
| J. Multi-tenant isolation | 6 | 1 | 0 | 1 | 1 | 0 | 4 | 0 |
| K. LLM behaviour and regression | 9 | 0 | 0 | 0 | 0 | 0 | 4 | 5 |
| L. Failure injection | 7 | 0 | 0 | 0 | 3 | 0 | 4 | 0 |
| M. Performance | 4 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |
| N. Observability | 5 | 3 | 0 | 3 | 1 | 1 | 0 | 0 |
| **All** | **170** | **38** | **8** | **30** | **45** | **21** | **58** | **8** |

Reading the table: of 170 cases, 38 were run (30 showed a bug, 8 behaved), 66 are judged from the code only, 58 are designed but not examined, and 8 cannot be done without a live model or an answer from the owner. The cases that need a model (E, K) are the largest blocked group; PDFs (F) and performance (M) are simply not reached yet.


### A. Webhook ingestion
*Why it matters: webhooks are retried, and the Telegram secret check is optional.*

| ID | Case (what to do) | Expected | Status | Evidence |
|---|---|---|---|---|
| A01 | WhatsApp POST with no signature header | Rejected, nothing processed | NOT RUN | harness `w.wa_post(signature=None)` |
| A02 | WhatsApp POST with a wrong signature | Rejected | NOT RUN | |
| A03 | Replay of an old valid signed body after more than 5 minutes | Ignored or limited | NOT RUN | duplicate window is 300 s (QA-013f) |
| A04 | The same message id delivered twice within 5 minutes | Handled once | READ-OK | `webhook.py:149-153` (but see A05, A21) |
| A05 | The same message id delivered again after 5 minutes | Handled once | READ-FAIL | QA-013 (f) |
| A06 | Two messages arrive out of order | Conversation stays consistent | NOT RUN | |
| A07 | A WhatsApp status callback (`statuses`) arrives | Not treated as a message | READ-OK | `webhook.py:112-114` discards it (and that is also QA-012) |
| A08 | One delivery holds three messages | All three handled | READ-FAIL | QA-013 (a): only the first is processed |
| A09 | Signed body that is not JSON | 4xx, no retry storm | READ-FAIL | QA-013 (c): returns 500 |
| A10 | Signed body that is a JSON list | 4xx | READ-FAIL | QA-013 (c) |
| A11 | Very large body (several MB) | Refused early | NOT RUN | |
| A12 | Unknown message type (sticker, location) | A short reply or a clean ignore | READ-FAIL | QA-013 (b): no reply at all |
| A13 | Image or voice note with no text; a photo with only a caption | Asked for text, or caption used | READ-FAIL | QA-013 (b) |
| A14 | WhatsApp "button" reply | Handled like a choice | READ-FAIL | QA-013 (b) |
| A15 | Telegram update without the secret header, secret configured | 401 | READ-OK | `telegram_webhook.py:31-34` |
| A16 | Telegram update with no secret configured | The app refuses to serve Telegram | RUN-FAIL | QA-002: the check is skipped when the variable is empty |
| A17 | Telegram edited message | Not run as a new message | READ-FAIL | QA-026, QA-003 |
| A18 | Telegram `callback_query` without a `message` | Ignored, 200 | READ-FAIL | QA-026: KeyError, 500 |
| A19 | Redis is down while a webhook arrives | Clear degrade, no data loss | READ-FAIL | QA-013 (e): 500 for everything |
| A20 | Process dies after the duplicate key is written, before the message is handled; Meta retries | The retry is handled | READ-FAIL | QA-013 (d): the retry is dropped |
| A21 | Delivery retried after 6 minutes | Not run twice | READ-FAIL | same as A05 |

### B. Identity and onboarding
*Why it matters: identity is found by scanning tenant databases, and trigger functions change roles when seats change.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| B01 | The same person writes from `+91 98765 43210`, `098765 43210`, `+919876543210` | One identity | NOT RUN | |
| B02 | Unknown WhatsApp sender | "Not registered, contact your admin" and nothing else | READ-OK | standard text `onboarding.not_registered` |
| B03 | Unknown Telegram sender sends an email, then a name, then picks a role | Only low-risk roles offered, or an admin must approve | READ-FAIL | QA-001: every role is offered, including admin |
| B04 | One phone number registered in two tenants | A clear choice or a safe rule | READ-FAIL | QA-020: first tenant in database order wins |
| B05 | A tenant database errors during the identity scan (schema drift) | Logged as an error, not "not registered" | READ-FAIL | QA-020: logged at debug |
| B06 | A person added by an admin (no chat linked) writes their email to the bot | Linked at once | NOT RUN | the dashboard says it does |
| B07 | A switched-off person writes | "Account switched off", nothing runs | READ-OK | standard text `onboarding.inactive` |
| B08 | A switched-off requester whose approval is granted | The action does not run | READ-FAIL | QA-019 (d) |
| B09 | A person gives up a committee seat | Role goes back to member (database trigger) | READ-OK | `sync_committee_role_to_user()` in the schema |
| B10 | A person's role changes in the middle of a draft | Permission is checked again at execute time | READ-OK | `action_executor.py:55-76` |
| B11 | A code is used after it expired | Refused | NOT RUN | |
| B12 | A code is used a second time | Refused | NOT RUN | `used` flag exists |
| B13 | Ten wrong codes sent at the same moment | At most the allowed number are checked | READ-FAIL | QA-014: read-then-increment race |
| B14 | How the code is made | A secure random source | RUN-FAIL | QA-014: `random.randint` (quick check) |
| B15 | A code made for one gate is used on another | Refused | READ-FAIL | QA-014: not tied to a purpose |
| B16 | Resend spam (ten "resend" in a minute) | Cooldown holds | NOT RUN | `otp_resend_cooldown_seconds` exists |
| B17 | A person's name contains HTML | Escaped in the code email | READ-FAIL | QA-030 |

### C. Draft, confirm and cancel
*Why it matters: no version pinning, no idempotency key, and the session is read, changed and written back in Redis.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| C01 | "yes" sent twice at once | The action runs once | READ-FAIL | QA-003 |
| C02 | "yes" after the draft is 2 hours old | Asked again, or refused | READ-FAIL | QA-006 |
| C03 | "yes but make it 5000" | Not treated as a plain yes | RUN-FAIL | QA-007 (function level) |
| C04 | "no problem, go ahead" | Not treated as "no" | RUN-FAIL | QA-007 |
| C05 | "no, wait" | Asks what to change, does not silently cancel | RUN-FAIL | QA-007: cancels |
| C06 | "ok no wait" | Not a confirmation | RUN-FAIL | QA-007: confirms |
| C07 | "cancel invoice INV-1" (three words) | Reaches a cancel workflow | RUN-FAIL | QA-024: wipes the draft and the chat history |
| C08 | Plain "cancel" in the middle of a draft | Draft cancelled | NOT RUN | |
| C09 | "haan", "thik hai", "ok" | Confirm (organisation's words) | NOT RUN | needs the live word list |
| C10 | The person starts a different request while a draft is open | Asked, or switched cleanly | NOT RUN | |
| C11 | The same person on two devices, two quick messages | Both kept | READ-FAIL | QA-021: the second write replaces the first |
| C12 | Unrecognised replies many times in a row | Stops asking after the cap | NOT RUN | |
| C13 | The draft points at a workflow that was switched off | Draft closed with a message | READ-FAIL | QA-016: it comes back |
| C14 | The workflow is edited between "yes" and execution | The version the person saw runs | READ-FAIL | QA-017 |
| C15 | After an approval, the workflow was edited | The approved version runs | READ-FAIL | QA-017 |

### D. Workflow engine
*Why it matters: this is where silent data corruption happens.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| D01 | A `when` with an unknown operator (a typo) | The step does not run, or the flow is refused | RUN-FAIL | QA-018: returns True (fails open) |
| D02 | A `when` that is an `or` group | Evaluated | RUN-FAIL | QA-018: KeyError |
| D03 | A condition without a `field` | Refused at save | RUN-FAIL | QA-018: KeyError |
| D04 | `equals 1000` against the number `1000.0` | Match | RUN-FAIL | QA-018 |
| D05 | `equals "None"` against a missing value | No match | RUN-FAIL | QA-018: matches |
| D06 | `gte 100000` against `"1,00,000"` | Read as 100000 | RUN-FAIL | QA-018: False, the gate is skipped |
| D07 | `gte 100000` against `"Rs 5 lakh"` | Read, or refused | RUN-FAIL | QA-018 |
| D08 | A large refund (`-500000`) against a `gte` gate | Still needs approval by size | RUN-FAIL | QA-018 |
| D09 | Approval levels at exactly the ceiling (100000) and just over | `[1]` then `[1, 2]` | RUN-PASS | quick check |
| D10 | Approval levels at amount 0 | Lowest level (the `when` decides if the gate applies) | RUN-PASS | quick check printed `[1]` |
| D11 | Nesting of `run_workflow` to depth 5 and beyond | Stopped at 5 with a message | READ-OK | depth cap in the interpreter |
| D12 | A cycle in `run_workflow` | Refused | READ-OK | cycle check |
| D13 | Parallel branches | Not offered (steps run in order) | READ-OK | `_execute_steps` runs steps one after another |
| D14 | Step 2 of 3 fails | Step 1's rows are rolled back | READ-FAIL | QA-005: they stay |
| D15 | The person retries after D14 | No duplicate record | READ-FAIL | QA-005 |
| D16 | Approver and requester are the same person | A clear policy | NOT RUN | |
| D17 | No approver exists for the level | The requester is told, someone is notified | READ-FAIL | QA-019 (a) |
| D18 | The approver has left or is switched off | Next approver or a clear message | NOT RUN | |
| D19 | A request is rejected | Requester told, draft closed | READ-FAIL | QA-028 |
| D20 | Two approvers tap Approve together | Runs once | READ-FAIL | QA-004 |
| D21 | An amount that is a string at the next approval level | No crash | READ-FAIL | QA-019 (c) |
| D22 | Response-time (SLA) edges at 59, 60 and 61 minutes | Reminder exactly at the threshold | NOT RUN | |
| D23 | Ten inserts at once into a table that numbers its rows | Ten different numbers | READ-FAIL | QA-027 |
| D24 | A workflow author puts SQL in `sequence.field` | Refused | READ-FAIL | QA-023 |
| D25 | "TODAY" between 00:00 and 05:30 IST | Today in IST | READ-FAIL | QA-025 |
| D26 | Resume after an approval with the gate removed | Not "completed successfully" | READ-FAIL | QA-017 |

### E. Chat workflow builder
*Why it matters: the model writes configuration that then runs for real. Most of this needs a model; a scripted fake model can drive the code around it.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| E01 | Prompt injection inside the request | Ignored | BLOCKED | needs a live model and a judge |
| E02 | Contradictory or impossible requests | Asks, or refuses | BLOCKED | needs a live model |
| E03 | A request that names a role or workflow that does not exist | A plain-language problem list | NOT RUN | `validate_steps` explains problems |
| E04 | A very long request | Limited with a message | NOT RUN | |
| E05 | The model returns invalid JSON, markdown fences, extra keys, unknown step types | Repaired or refused, never saved | NOT RUN | scripted fake model |
| E06 | Truncated output, timeout, rate limit, fallback model, repair loop used up | A clear message, nothing saved | NOT RUN | scripted fake model |
| E07 | "Apply" pressed twice | One workflow, not two | NOT RUN | |
| E08 | Saving on a stale version | 409 and a "someone else saved this" screen | READ-OK | `js_studio.py:143` handles 409 |
| E09 | Restore from a partial snapshot | Refused or complete | NOT RUN | |
| E10 | Delete or switch off a step or block used elsewhere | Refused with the names | READ-OK | `workflows.py` returns 409 listing users |
| E11 | Two editors at once | One wins, the other is told | NOT RUN | |

### F. Documents and PDFs
*Why it matters: money, tax and numbers on paper. Not reached yet.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| F01 | A template with a missing placeholder | A clear error | NOT RUN | |
| F02 | Unicode and Devanagari text in a PDF | Renders | NOT RUN | |
| F03 | A long table across page breaks | Headers repeat, nothing cut | NOT RUN | |
| F04 | Rounding of GST and making charges | Paise-exact | NOT RUN | |
| F05 | Negative values | Shown or refused | NOT RUN | |
| F06 | Gold rate typed as "22k", "916", grams vs tola | Parsed or asked | NOT RUN | |
| F07 | A PDF that is scanned, password-protected, many pages, or the wrong type | A clear message | NOT RUN | |

### G. Data layer
*Why it matters: the AI writes SQL, and old stored reports use an older text check.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| G01 | `SELECT phone FROM users` (a hidden column) | Refused | RUN-PASS | quick check |
| G02 | `SELECT *` from a table with hidden columns | Hidden columns removed | READ-OK | guard allows it; the caller removes them by key |
| G03 | `SELECT to_jsonb(u) FROM users u` | Refused | RUN-FAIL | QA-008 |
| G04 | `SELECT row_to_json(users) FROM users` | Refused | RUN-FAIL | QA-008 |
| G05 | `... WHERE phone LIKE '+9190%'` (guess a number digit by digit) | Predicates on hidden columns refused | RUN-FAIL | QA-008: allowed by design |
| G06 | Comma join into `pg_catalog.pg_user` | Refused | RUN-PASS | quick check |
| G07 | Two statements: `SELECT 1; DROP TABLE users` | Refused | RUN-PASS | quick check |
| G08 | A CTE that selects a hidden column | Refused | RUN-PASS | quick check |
| G09 | A table function (`generate_series`) as a table | Refused | RUN-PASS | quick check |
| G10 | Comments and Unicode tricks inside the SQL | Refused or harmless | NOT RUN | |
| G11 | A write hidden inside a CTE | Refused | READ-OK | guard allows SELECT only |
| G12 | Stored report: `FROM cases c, users u`, an alias, `LIMIT` inside a column name | Permission check sees both tables; aliases cannot leak | RUN-FAIL | QA-009 |
| G13 | Delete a user who has cases | A clear rule (no orphans) | NOT RUN | |
| G14 | A status that breaks a CHECK rule | Refused by the database | READ-OK | CHECK constraints in the schema |
| G15 | JSON columns with the wrong shape (a string where a list is expected) | A clear error | NOT RUN | |
| G16 | Two approvals on one case | One wins | READ-FAIL | QA-004 |
| G17 | Old drafts and codes | Removed by the nightly job | READ-OK | `app/services/cleanup.py` |
| G18 | 10,000+ rows, N+1 queries, pool exhaustion, database down mid-request | Stays usable, clear errors | NOT RUN | |
| G19 | Two first calls create two pools | One pool | READ-FAIL | QA-029 |

### H. Scheduler
*Why it matters: one process may run in several copies, and times are in IST.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| H01 | Two copies of the scheduler run the same job | Only one runs | READ-OK | advisory lock in `app/scheduler/locks.py` |
| H02 | A run lasts longer than the interval | The next tick waits | READ-OK | same lock |
| H03 | The app restarts and misses runs | A defined catch-up rule | NOT RUN | |
| H04 | A case closes before its reminder is due | No reminder | NOT RUN | |
| H05 | One reminder fails to send, or has a bad template | Others still go out; no repeats | READ-FAIL | QA-011 |
| H06 | A scheduled report with no rows, or a huge result | Handled | NOT RUN | |
| H07 | "Daily at 00:00" | Runs at 00:00 IST | RUN-FAIL | QA-010: runs at 08:00 |
| H08 | "Weekly Monday at 00:00" | Monday 00:00 | RUN-FAIL | QA-010: Monday 09:00 |
| H09 | Monthly on the 31st (asked on 31 Jan and 31 Mar) and on the 30th (asked on 30 Jan) | A next run is found | RUN-FAIL | QA-010: ValueError, three times |
| H10 | The monthly crash inside the live loop | One send per period | READ-FAIL | QA-010: due again every minute |
| H11 | The date at 01:00 IST on the 1st of a month | Today's date and prefix | READ-FAIL | QA-025 |
| H12 | A WhatsApp message started by the bot, 25 hours after the person last wrote | Delivered, or a failure is logged | RUN-FAIL | QA-012, seen live by the owner |

### I. Admin API
*Why it matters: the dashboard talks to these endpoints, and each one is a door.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| I01 | Panel calls without signing in | 401 | BLOCKED | the sign-in (built 7 Oct) is not reviewed in this file |
| I02 | `GET /debug/schema/{key}` with no sign-in | 401 | RUN-FAIL | QA-015 |
| I03 | `GET /health` called by anyone, many times | Cheap, no paid calls | RUN-FAIL | QA-015: calls OpenAI and Cerebras |
| I04 | Each POST and PUT with wrong types, too long, Unicode | A clear 4xx | NOT RUN | many endpoints use limited fields (for example `PersonNew`) |
| I05 | A name with `<script>` shown in the dashboard | Shown as text | READ-OK | the dashboard script builds elements and has no `innerHTML` |
| I06 | The same POST or DELETE twice | Same result, no duplicate | NOT RUN | |
| I07 | Two saves of one workflow | Second gets 409 | READ-OK | 409 exists |
| I08 | Pagination with a very long list | Pages, fast | NOT RUN | |
| I09 | A server error | No stack trace in the answer | NOT RUN | |
| I10 | An admin of organisation A opens organisation B | Refused with a clear page | RUN-PASS | seen in the UX audit run (page level); API level NOT RUN |
| I11 | `GET /admin/<guess>` for a key that does not exist | Same answer as for an existing key | RUN-FAIL | QA-031: an unknown key gives a JSON 404, a real key gives the sign-in page |

### J. Multi-tenant isolation
*Why it matters: one process serves every client.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| J01 | The same phone in two tenants | No mix-up of drafts or history | READ-FAIL | QA-020 |
| J02 | Redis keys of two tenants for one person | Separate | NOT RUN | |
| J03 | Prompt, schema and pool caches | Per tenant | NOT RUN | `_reset_caches()` in the harness lists them |
| J04 | Tenant A's rows in tenant B's model context | Never | NOT RUN | |
| J05 | Routing by channel | Right tenant | NOT RUN | `data_sources.messaging_channel` |
| J06 | A stranger lists any tenant's tables | Refused | RUN-FAIL | QA-015 |

### K. LLM behaviour and regression
*Why it matters: the model decides which workflow runs. Needs a live model; the code around it can be driven by a scripted fake.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| K01 | A scenario set per client (housing: file a complaint, close with a note, assign; jewellery: quote, invoice, rate) | Right workflow every time | BLOCKED | live model |
| K02 | Wrong workflow chosen | Asks, does not guess | BLOCKED | live model |
| K03 | A model that keeps calling tools | Stops at the loop limit | NOT RUN | scripted fake model |
| K04 | A model that invents a tool name | Error handled, no crash | NOT RUN | scripted fake model |
| K05 | A very long session | History trimmed, no overflow | NOT RUN | `context_message_limit` |
| K06 | Hindi, Marathi, Hinglish | Understood | BLOCKED | live model |
| K07 | "Show all customers" | Refused or limited by role | BLOCKED | live model (the SQL guard is G) |
| K08 | A sensitive action | Never runs without a confirmation | NOT RUN | scripted fake model |
| K09 | Five paraphrases of one request | One intent | BLOCKED | live model, metamorphic test |

### L. Failure injection
*Why it matters: things fail in production in the middle of work.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| L01 | Redis down | A clear degrade | READ-FAIL | QA-013 (e) |
| L02 | Database down in the middle of a request | A clear message, no half-done work | NOT RUN | |
| L03 | Model returns 500 or times out | Fallback, then a plain message | NOT RUN | |
| L04 | WhatsApp answers 429 or 5xx | Retried or logged | READ-FAIL | QA-012: only the HTTP status is looked at, the result is ignored |
| L05 | The process is killed between step 1 and step 2 | A defined recovery | READ-FAIL | QA-005, QA-013 (d) |
| L06 | Restart while a person has a draft waiting | The draft is still there | NOT RUN | |
| L07 | Clock skew between the app and the database | No wrong "late" or "due" | NOT RUN | |

### M. Performance
*Why it matters: stated budgets are needed, and none were given. Planned, not run.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| M01 | A burst of 100 webhooks | p50 and p95 against a budget | NOT RUN | no budget stated |
| M02 | 50 sessions at once | No lost updates | NOT RUN | |
| M03 | A slow model (20 s) | Others are not blocked | NOT RUN | |
| M04 | A soak (hours) | Memory flat | NOT RUN | |

### N. Observability
*Why it matters: you cannot fix what you cannot see.*

| ID | Case | Expected | Status | Evidence |
|---|---|---|---|---|
| N01 | Every failure has a correlation id in the log | Yes | RUN-FAIL | QA-022: blank on the WhatsApp path (live logs) |
| N02 | The audit outcome tells the truth | Failures show as errors | READ-FAIL | QA-022: agent turns always "success" |
| N03 | A health endpoint exists | Yes, cheap | RUN-FAIL | it exists but calls paid APIs (QA-015) |
| N04 | A WhatsApp delivery failure is visible | Logged | RUN-FAIL | QA-012 |
| N05 | A failed reschedule is logged | Yes | READ-OK | "Failed to reschedule" line |

---

## 8. Test plan (what each finding needs next)

All run on the local harness (`tests/qa/`). **Done**: harness smoke tests. **Next, in this order**:

| Test | Findings | Needs |
|---|---|---|
| `double_yes_runs_steps_twice` | QA-003 | `asyncio.gather` of two confirmations, a workflow into `audit_log` |
| `double_approval_runs_twice` | QA-004 | approval row from the gate, two concurrent taps |
| `partial_write_after_failed_step` | QA-005 | seeded `qa_partial_fail` |
| `yes_but_executes_old_values`, `no_problem_cancels` | QA-007 | pending draft, scripted reply |
| `resume_after_workflow_edit` | QA-017 | approval, edit steps, approve |
| `stale_yes_executes` | QA-006 | draft aged 2 hours |
| `telegram_self_registration_role` | QA-001 | Telegram messages, captured code |
| `telegram_forged_update_without_secret` | QA-002 | webhook post with no header |
| `monthly_31st_storm` | QA-010 | scheduled report row, fake clock, count sends over 3 ticks |
| `reminder_storm_on_failed_send`, `bad_template_blocks_pass` | QA-011 | cases + priority rules + org settings |
| `ai_sql_to_jsonb_leak`, `report_alias_leak` | QA-008, QA-009 | end to end on the throwaway database |
| `otp_attempts_under_concurrency` | QA-014 | known code, 10 parallel guesses |
| `dead_draft_rehydrates` | QA-016 | switched-off workflow |
| `webhook_batch_media_nonjson_redis_down` | QA-013 | signed posts, failing fake Redis |
| `two_tenants_one_phone` | QA-020 | both client databases |
| `session_lost_update` | QA-021 | slow scripted model, two messages |
| `doc_number_race` | QA-027 | 10 concurrent inserts, with and without a unique rule |
| `scheduler_lock_one_runner` | hypothesis 5 | two `run_if_free` at once |
| property tests on `when` guards, gate levels, phone and amount parsing | QA-018, D | `hypothesis` |
| metamorphic LLM tests | K | needs a live model |

Techniques applied so far: code reading by state machine, boundary values on gates and dates, decision-table checks on the guard operators, fault-injection design (fake Redis and transports). Planned: concurrency stress, property tests, mutation testing on `step_interpreter` and `validate_steps`.

---

## 9. Hypotheses from the earlier audit

| Hypothesis | Verdict | Evidence |
|---|---|---|
| Conditions fail open (`step_interpreter` ~line 405) | **Confirmed**, and some forms crash | `408-409`; section 10 |
| No transaction across steps | **Confirmed by code** (end-to-end test planned) | `db.py:120-146`, `step_interpreter.py:2039-2138` |
| Resume uses the latest workflow, not the pinned one (`action_executor` ~48) | **Confirmed**, with a worse effect: stored step number | `action_executor.py:48-86`, `step_interpreter.py:903` |
| `audit_log` marks every turn "success" | **Partly**: agent and menu turns always; confirm failures and exceptions are `error` | `webhook.py:1364, 1418, 1651-1676, 1719-1731` |
| Scheduler runs in every replica | **Mitigated**: one advisory lock per job on the routing database (test planned) | `app/scheduler/locks.py` |
| Stored report SQL uses a regex guard a comma join can bypass | **Confirmed** | `query_engine.py:135`; section 10 |
| Drafts and OTPs are never purged | **Refuted**: a nightly cleanup archives and removes them by retention | `app/services/cleanup.py` |
| Drafts reference retired workflows by key | **Confirmed**, and the dead draft keeps coming back (QA-016) | `action_executor.py:48-76`, `webhook.py:1229` |
| Redis session race on two quick messages | **Confirmed by code** (QA-021) | `webhook.py:1155, 1553, 1627` |
| A rejected approval only informs the requester | **Confirmed** (QA-028) | `workflow_executor.py:161-172` |
| Fixed IST time zone | **Confirmed**; and dates from the server clock differ (QA-025) | `jobs.py` (`_IST`), `db.py:37`, `step_interpreter.py:1002-1046` |
| Special access table never read | **Not checked yet** | |

New, not in the earlier list: QA-001, QA-002, QA-003, QA-004, QA-007, QA-010, QA-012, QA-014, QA-015, QA-017 and the others in section 5.

---

## 10. Evidence: the quick check

Run on this computer, no database, no network. Source: a short script that imports the application's own functions. Output (trimmed):

```
== D1 'when' guards
unknown operator (typo 'equal'): True               <- fails open
unknown operator 'startswith': True                 <- fails open
'or' group: raised KeyError: 'field'
condition without a field: raised KeyError: 'field'
equals 1000 on the number 1000.0: False
equals 'None' on a missing value: True
gte 100000 on '1,00,000': False                     <- gate would be skipped
gte 100000 on 'Rs 5 lakh': False
gte 100000 on -500000 (a big refund): False
levels needed at exactly the ceiling 100000: [1]
levels needed at 100000.01: [1, 2]
== C yes / no wording
matches_vocab(['yes'], 'yes but make it 5000') = True
matches_vocab(['yes'], 'yes, but not today') = True
matches_vocab(['no'], 'no problem, go ahead') = True
matches_vocab(['no'], 'no, wait') = True
matches_vocab(['ok'], 'ok no wait') = True
cancel gate for 'cancel invoice INV-1' -> treated as cancel: True
== H schedules
daily at hour 0 (midnight): next run (IST): '2026-10-08 08:00'
weekly mon at hour 0: 'Mon 09:00'
monthly day 31, asked on Jan 31 after the time: raised ValueError: day is out of range for month
monthly day 31, asked on Mar 31 after the time: raised ValueError: day is out of range for month
monthly day 30 on Jan 30 after the time: raised ValueError: day is out of range for month
== G AI-written SQL guard
ALLOWED  SELECT * FROM users
ALLOWED  SELECT to_jsonb(u) FROM users u
ALLOWED  SELECT row_to_json(users) FROM users
ALLOWED  SELECT name FROM users WHERE phone LIKE '+9190%'
refused  SELECT phone FROM users
refused  SELECT name FROM users, pg_catalog.pg_user
refused  SELECT 1; DROP TABLE users
refused  WITH x AS (SELECT phone FROM users) SELECT * FROM x
== G stored-report SQL, older text check
tables the permission check sees: {'cases'}      (the query also read users)
_safe says: (True, 'ok')
== misc
OTP made with random.randint: True | secrets module used: False
Telegram secret check only when configured: True
unauthenticated debug routes: ['/debug/schema/{source_key}', '/debug/clear-schema-cache']
health calls OpenAI models.list(): True
```

Things the SQL guard does well (worth keeping): one statement only, SELECT only, no data-changing CTEs, no other schemas, no `pg_*` or other dangerous functions, no table functions, an organisation filter built in, a row limit, and the caller also runs it in a read-only transaction with a time limit.

---

## 11. The harness (for whoever continues)

* These files are new and are not committed to git. Files: `tests/qa/harness.py` (worlds, fakes, helpers), `tests/qa/seed.py` (synthetic organisation, roles, people, four workflows), `tests/qa/fixtures/schema_*.sql` (schema-only dumps, no data), `tests/qa/test_00_harness.py`.
* Run: start any Postgres on this computer, then
  `MIGRATE_TEST_PG=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest tests/qa -q`.
  Without that variable the database tests are skipped. The harness builds three template databases from the dumps once per run and a fresh copy for every test, and drops them afterwards.
* Needs: `fakeredis`, `hypothesis`, `freezegun` (installed for this review), `psql` on the PATH or in `PG_BIN`.
* A test: `from tests.qa.harness import needs_qa, qa_run` then
  `@needs_qa def test_x(): async def scenario(w): ...; qa_run(scenario)`.
  `w.say(phone, text)` runs one chat turn, `w.make_pending(...)` puts a person mid-draft, `w.wa_post(...)` / `w.tg_post(...)` send signed webhooks, `w.sent` lists every outbound message, `w.otps` the captured codes, `w.llm.queue(...)` scripts the model (any unscripted call fails the test).

## 12. Recommended CI plan

* **Every push (about 1 minute)**: lint, import check, the no-database tests (the quick-check items turned into tests), the sign-in tests.
* **Nightly (about 15 minutes)**: the whole suite on a fresh Postgres, including the concurrency and failure-injection tests, with the random seed printed on failure.
* **Quarantine**: a test that fails once and passes on retry is moved to a `flaky` marker and reported separately; it must be fixed within a week or deleted. Concurrency tests use fixed barriers instead of sleeps to stay stable.
* **Weekly**: mutation testing on `step_interpreter` and `workflow_validator`, a soak run, and the model scenarios against a live model with a recorded transcript for review.

## 13. Questions that would change a severity

1. Is `TELEGRAM_WEBHOOK_SECRET` set in Railway? (QA-002)
2. Should self-registration on Telegram offer every role? (QA-001)
3. What are the live confirm and cancel words? (QA-007, QA-024)
4. Which roles have `users` (or other tables with phone, email) in `readable_tables`? (QA-008)
5. Are any monthly schedules on day 29 to 31 or at hour 0 today? (QA-010)
6. Is it intended that anyone can read an organisation's name from its key before signing in? (QA-031)
