# Architecture audit

**Scope and sources.** Repository at `D:\Orchestrator AI` (branch `dev`, commit e542a27, plus this audit's `docs/audit/` files). Databases: the dumps `godrej (11).sql` (2026-10-03), `baanganga (3).sql` and `routing_db (3).sql` (both 2026-09-23), **plus a read-only live scan of all three Railway databases on 2026-10-03**. The Godrej dump matched live exactly. Claims are labelled **VERIFIED** (read or run) or **INFERRED**. Secrets in the routing dump are **[REDACTED]** everywhere. Only `docs/audit/` files were written.

---

## PASTE-BACK SUMMARY

### Scores (1 far, 5 there)

| Area | Score | One line |
|---|---|---|
| Structure | **2** | Two god modules (`agent.py` 3,786 lines, classic `admin.py` 3,222), 4 cycles hidden in function imports, `webhook.py` mixes channel, onboarding, OTP and the turn loop. |
| Hardcoding | **3** | Steps, fields, vocabulary, reminders and statuses are data. Prompts, 77 user messages, IST, the channel binding and jewellery/housing words are code: 61 register rows, 12 block the target. |
| Step registry | **4** | 25 step keys; 22 have declared parameter specs that match the code except 3 undeclared reads. A JSON Schema per step is generatable today. |
| Definition format | **3** | Clean `{op, params, when}` JSON, but no `schema_version`, per-tenant alias conventions, a `sheet:` magic prefix, references by name. |
| Database design | **2** | 20 tables exist in only one tenant, no baseline schema or migration history, real drift, no purge, CHECK lists that are data. |
| Versioning | **2** | 4 snapshots for 19 workflows, snapshots omit 18 columns, runs are not pinned, SQL migrations bypass history. |
| Prompts | **2** | 19 files in the deploy, the shared base prompt contains client content, no tenant precedence. A stale prompt broke production (327a9a3). |
| Chat builder | **3** | Validate, repair, diff, dry run, 409 on stale save are real. No clarification contract, output not API-constrained, no evals, two pipelines. |
| Multi-client readiness | **1** | One tenant per channel, one global WhatsApp number and Telegram bot, identity scans every tenant DB, IST hard-coded, no base schema in the repo. |

### Top 10 strengths

1. **The registry is nearly self-describing.** `STEP_TYPES` (`services/step_catalog.py:22`) declares parameters for 22 of 25 keys in `PRIMITIVES` (`step_interpreter.py:1820-1841`); my script found only 3 undeclared reads (`only_mine`, `where`, `button_roles`). VERIFIED.
2. **Definitions are plain JSON the engine interprets.** 52 steps in 19 Godrej workflows are all `{op, params, when?}`; blocks nest to depth 5. VERIFIED.
3. **Builder safety loop.** `studio_chat` validates every proposal with `validate_steps`, retries once with the errors fed back, returns a diff, and nothing is saved until Apply and Save; saves use optimistic locking (409). `admin_panel/studio.py`. VERIFIED.
4. **Dry run exists.** `run_workflow_steps(dry_run=True)` records a trace and powers Try it and the 'What happens next' confirmation. VERIFIED.
5. **Vocabulary is fully data.** `services/vocabulary.py` holds zero words; every list comes from `orgs.settings.vocabulary`. VERIFIED.
6. **Code first, AI second.** `field_reader.py` reads answers with rules and SQL and hands over to the model only when unsure; reports are worded by code (`report_format.py`). VERIFIED.
7. **AI-written SQL is guarded.** sqlglot parse, table allow-list, row cap, 5 s timeout, read-only transaction (`sql_guard.py`, `db.py:125-131`). VERIFIED.
8. **Physical tenant isolation.** One database per tenant behind a routing DB (`db.py:67-80`). VERIFIED.
9. **Operational config is JSON.** SLA reminders and statuses come from `orgs.settings` (`scheduler/jobs.py:230-305`). VERIFIED.
10. **Ingress hygiene.** WhatsApp HMAC, Telegram de-duplication, PII-redacting logger (`webhook.py:79-101`, `telegram_webhook.py:38-43`). 62 real foreign keys in Godrej, 0 orphans in the checks I ran. VERIFIED.

### Top 10 weaknesses, ranked

1. **No admin authentication.** `_check_token` is defined but applied to no route (`routers/admin.py:20-27`); two unauthenticated debug routes list any tenant's tables (`main.py:60,83`). VERIFIED.
2. **Secrets and privilege.** Control-DB connection strings, with passwords, are plain text and use the superuser `postgres` (live: the only role); 'read-only' is a session flag on that login; `sheets_creds_b64.txt` and `scratch_defs.pkl` are tracked in git. VERIFIED (dump, `git ls-files`).
3. **Cannot onboard a second client on the same channel.** `get_source_key_for_channel` raises unless exactly one tenant owns a channel (`db.py:92-110`); the WhatsApp number and Telegram bot are single env values; identity is found by scanning every tenant DB (`identity.py:25`); IST is hard-coded in 3 files. VERIFIED.
4. **No version pinning, thin history.** `action_executor.py:48` loads the latest definition; 18 of 19 workflows are still version 1 after hand-run SQL edits; snapshots omit 18 columns. VERIFIED.
5. **Unsafe execution.** Each step commits on its own connection; an unrecognised `when` runs the step anyway (`step_interpreter.py:405`). VERIFIED.
6. **Prompts and messages are code.** 19 prompt files, 77 literal user messages; `_base.txt` names jewellery tables and a retired housing workflow. VERIFIED.
7. **No base schema, no migration runner.** `migrations/` has per-client alter-only files; the table list differs by tenant and so do 15 indexes. VERIFIED.
8. **No tests; lint-only CI.** The suite was removed; `.github/workflows` runs ruff. Two builders and two validators coexist. VERIFIED.
9. **Observability is blind to failure.** All 595 Godrej audit rows say 'success'; `steps_taken` is always empty; `workflows.last_run` is NULL on all 27 workflows; no LLM cost accounting. VERIFIED live.
10. **Debris and soft references.** 84/84 drafts and 69/69 OTP rows expired and never purged; 64 drafts point at deleted workflows; 3 dead permission strings. VERIFIED.

### Result of the two change tests

1. **New manufacturing client:** about **8 config items** (fine), **1–3 registry steps** (acceptable once) and **6 defects needing code or a deploy, touching 8 files**: no baseline schema to create the DB from; an industry prompt file plus deploy; the one-tenant-per-channel rule; a single global WhatsApp/Telegram credential set (3 files); IST in 3 places if the client is elsewhere; the vocabulary seed file the docs mention does not exist.
2. **Extra field on people + a new optional capability:** `users` has no attribute column (core migration needed); `residents.custom_fields` exists but the People screens read fixed columns (code). The capability can be config only if it is built from existing steps. There are no feature flags, packs or tenant-level capability switches, so 'optional' means 'registered for everyone'.

### The 10 most important database changes (details and SQL in `proposed-schema.sql`)

1. `schema_migrations` in every tenant DB and the control DB, with a baseline (P1-01).
2. Control DB: `status`, `industry_pack`, `pack_version`, `schema_version`, `timezone`, `flags`, `secret_ref`; `tenant_channels` and `identity_map` (C-01 to C-03).
3. `workflow_definitions`: immutable JSONB versions with `schema_version`, backfilled from live rows (P2-01).
4. `workflow_runs` pinned to a version with an idempotency key; version columns on `user_drafts` and `pending_approvals` now (P2-01, P2-02).
5. Real audit fields (`workflow_key`, `workflow_version`, `run_id`, `error_step`) and an index on `audit_log(session_id)` (P2-03, P1-03).
6. `prompts` and `system_messages` with global < pack < tenant precedence (P1-05).
7. `orgs.timezone`, `orgs.locale`; move jewellery columns into `orgs.settings` (P1-04, P1-06).
8. Purge expired drafts, OTPs and abandoned builder drafts; clean dead permission strings; add the missing foreign keys (P1-02, P2-04).
9. `sla_policies` and `escalation_steps`; ordering guard on `priority_tat_rules` (P2-05).
10. `named_queries` for reports and three DB roles `app_rw`, `app_ro`, `migrator` (P3-01).

### Unresolved questions

1. Should **Special access** (`access_grants`, empty, never read by the bot) be finished or removed? It decides a core table and the capability model.
2. Does each client need **its own WhatsApp number or Telegram bot**? It decides whether channels move to the control DB (assumed yes).
3. Should a request in flight **finish on the version it started on**? I assume yes.
4. May **business tables** (`cases`, `customers`, `invoices`) stay per client, or must they become generic entity records? The brief says no per-client tables; today every client has them.
5. Where is **Redis** hosted (it is not in the Railway project and I did not inspect it), and is anything important kept only there, such as sessions in progress or duplicate-message keys?

---

## Part A: Repository structure

### A.1 Tree, sizes, files over 800 lines

`app/` has 94 files (74 Python) and 30,922 lines. VERIFIED by script.

| directory (depth ≤3) | files | lines |
|---|---|---|
| `app/` | 7 | 556 |
| `app/admin_panel/` | 11 | 4009 |
| `app/admin_panel/ui/` | 9 | 2541 |
| `app/executor/` | 2 | 308 |
| `app/prompts/` | 19 | 2091 |
| `app/routers/` | 4 | 5066 |
| `app/scheduler/` | 2 | 572 |
| `app/services/` | 40 | 15779 |

Files over 800 lines (all Python): `app/services/agent.py` 3,786, `app/routers/admin.py` 3,222, `app/services/step_interpreter.py` 2,093, `app/routers/webhook.py` 1,733, `app/services/workflow_builder_agent.py` 1,556, `app/admin_panel/studio.py` 1,027, `app/services/step_catalog.py` 990.

### A.2 Classification

Every module is classified in `module-map.md`. Summary: ENGINE 32 files / 10,998 lines; BUILDER 11 / 3,546; ADMIN 13 / 3,985; CLIENT-SPECIFIC 13 / 3,930 (case steps, housing/jewellery prompts, case dashboard screens, jewellery price parser); CONFIG-IN-CODE 13 / 828 (generic prompts and the model roster); CHANNEL 8 / 2,653; REGISTRY 2 / 1,437; DEAD or DUPLICATE 2 / 3,545 (classic `routers/admin.py`, second validator `workflow_validator.py`).

### A.3 Import graph

- **No module-level import cycles** (0). **Four cycles exist only through imports inside functions**: `admin_panel/studio.py` ↔ `workflows.py`; `scheduler/jobs.py` ↔ `services/agent.py`; `services/case_ops.py` ↔ `step_interpreter.py`; `workflow_builder_agent.py` ↔ `workflow_compiler.py`. There are 88 function-level `app.*` imports across 19 modules. VERIFIED (AST scan).
- **Direction:** routers → services → `db`/`logging_config` is respected; no service imports a router or the admin panel. Fan-in leaders: `logging_config` 34, `db` 33, `llm_router` 10.
- **God modules (fan-out):** `agent.py` 25, `webhook.py` 17, `step_interpreter.py` 17, `studio.py` 12, `admin.py` 12.
- **Layers that reach across:** `step_interpreter.py` imports `case_ops` (client-specific steps) into the shared registry; `webhook.py` holds WhatsApp ingress, Telegram linking, OTP, onboarding and the whole turn loop (62 user messages); `agent.py` holds the tool loop, SQL tool, PDF/invoice maths and schedule tool; `scheduler/jobs.py` imports the agent.

### A.4 Entry points, jobs, config, logging, errors, tests

- **Entry:** `uvicorn app.main:app` (`Procfile`, `nixpacks.toml`, `Dockerfile`). Routers: WhatsApp webhook, Telegram webhook, classic admin, admin panel v2 (`main.py:48-51`). VERIFIED.
- **Background jobs:** APScheduler inside the web process (`jobs.py:22,550-565`): `run_scheduled_reports` and `run_case_reminders`, every minute, `max_instances=1`. **With N replicas every replica runs both jobs** (no lock or leader): duplicate reminders and report deliveries (INFERRED from absence of any lock; no `SETNX` or advisory lock found). Also in-process: LLM provider cooldowns and the studio chat rate limit.
- **Config:** env via `config.required()`; 11 variables are required at import, so the app cannot start without e.g. `SENDER_EMAIL`. Model roster in `ai_models_config.json`. Tenant config in `orgs` columns and `orgs.settings`.
- **Logging:** structured, correlation id, PII redaction (`logging_config.py`). No LLM usage or cost metric.
- **Error handling:** step failures return a generic message; delivery failures after a successful insert are treated as partial success (`step_interpreter.py:1976-1996`); the webhook wrapper logs an error row. No retries, no dead-letter.
- **Tests/CI:** no tests (`tests/` removed, commit ee7b50f). CI is `ruff check` and `ruff format --check` only (`.github/workflows`). VERIFIED.

### A.5 Current to target

Full table with 94 rows (path, target, action, effort, reason): `module-map.md`. Proposed tree with every module mapped: `target-layout.md`. The shape of the plan:

| Current | Target | Action | Effort | Reason |
|---|---|---|---|---|
| `services/agent.py` | `core/engine/agent/*` | split | L | 3,786 lines, 13 tools, fan-out 25 |
| `routers/webhook.py` | `core/channels/*` + `core/engine/turn.py` | split | L | channel, onboarding, OTP and turn loop mixed |
| `routers/admin.py` | (deleted) | delete | L | 3,222-line classic admin, no auth, duplicates v2 |
| `services/step_interpreter.py` | `core/engine/interpreter.py` + `core/registry/steps/*` | split | L | handlers and runner together |
| `services/case_ops.py`, `admin_panel/{people,routing,cases,overview}.py` | `packs/case_management/` | move | M–L | housing case model is a pack, not core |
| `prompts/*.txt` | `prompts` table + `packs/*/prompts` | move | M | tenant config |
| `services/identity.py`, `db.py`, `messaging.py` | `core/tenancy/*`, `core/channels/*` | rewrite | M | multi-client |
| `services/workflow_builder_agent.py`, `workflow_validator.py` | merged into one builder pipeline | delete/merge | L/M | two builders, two validators |
| `migrations/*.sql` | `migrations/{control,core}`, `packs/*/migrations` | split | L | no baseline, per-client names |

---

## Part B: Hardcoding and client-specific scan

The register is `hardcoding-register.csv` (61 rows, each with `file:line` found by search, so the line numbers are real). Severity: **12 block the target**, 19 hurt, 30 minor. Method: regex sweeps over `app/**/*.py` (excluding the dashboard's JS/CSS strings) for model names, timezones, URLs, client and industry words, role and status literals, numeric limits, user-facing strings (AST), table names in SQL, then reading each hit class. Counts of raw hits before curation: timezone 19, client words 103, URLs 11, timeouts/limits 98, table literals 147 (mostly the housing admin screens), status literals 26. Model names: none in `.py` (they are in the JSON file).

**What blocks the target (all VERIFIED):** industry prompt as a deployed file (H01); client content in the shared base prompt (H02); client prompts as code (H04-H05); 62+12 hard-coded messages are *hurts*, not blockers; IST in `db.py:38`, `jobs.py:22`, `agent.py:1923` (H28-H30); one tenant per channel (H39); identity scan (H40); global channel credentials (H41); open debug routes (H43) and unused admin token (H44).

**Words searched** (brief): godrej, baanganga, jewel*, gold, gst, making charge, flat, society, lift, committee, plus karat, resident, tenant, wing, tower, shikayat, baaki, khula, housing, invoice, quotation. They appear in code mainly in `agent.py` (invoice maths, org defaults, tool descriptions), the four housing admin modules, and the prompts. Hinglish business words (`baaki`, `khula`, `band`) also sit in Godrej's `workflows.business_glossary`, copied from Baanganga's template (VERIFIED, dump).

---

## Part C: Step registry audit

`PRIMITIVES` (`step_interpreter.py:1820-1841`) plus `CASE_PRIMITIVES` (`case_ops.py:482`) = **25 keys, 22 distinct handlers** (`sheets.insert/update/delete_row` are aliases of the `db.*` handlers). 'Declared' means a parameter spec exists in `STEP_TYPES` (`step_catalog.py`) and is what the editor, `validate_steps` and the chat builder use. 'Read, not declared' came from a regex over each handler's body (INFERRED where the handler builds keys dynamically).

| Step | Defined | Declared | Read but not declared | Side effects | Transaction | Idempotency | Definition-driven |
|---|---|---|---|---|---|---|---|
| `ai_price_interpret` | `step_interpreter.py:1329` | yes | — | none | none | n/a | yes |
| `approval_gate` | `step_interpreter.py:824` | yes | — | DB write, message out | own connection | none | yes |
| `case.add_parties` | `case_ops.py:299` | yes | — | DB write | own connection | ON CONFLICT | yes |
| `case.attach_photos` | `case_ops.py:332` | yes | — | DB write | own connection | none | yes |
| `case.authorize` | `case_ops.py:257` | yes | — | none | own connection | n/a | yes |
| `case.categorize` | `case_ops.py:130` | yes | — | none | none | n/a | partly (rules in SQL function / keyword tables) |
| `case.route` | `case_ops.py:171` | yes | — | none | own connection | n/a | partly (rules in SQL function / keyword tables) |
| `compute` | `step_interpreter.py:755` | yes | — | none | none | n/a | yes |
| `conflict_check` | `step_interpreter.py:1498` | yes | — | none | own connection | n/a | yes |
| `db.delete_row` | `step_interpreter.py:1294` | yes | — | DB write, external call | own connection | none | yes |
| `db.insert_row` | `step_interpreter.py:963` | yes | — | DB write, external call | own connection | none | yes |
| `db.update_row` | `step_interpreter.py:1205` | yes | — | DB write, external call | own connection | none | yes |
| `db.upsert_row` | `step_interpreter.py:1361` | yes | — | DB write | own connection | ON CONFLICT | yes |
| `derive_field` | `step_interpreter.py:1411` | yes | — | none | none | n/a | yes |
| `notify.parties` | `case_ops.py:362` | yes | button_roles | message out | own connection | n/a | yes |
| `notify.user` | `step_interpreter.py:1435` | yes | — | message out | none | n/a | yes |
| `notify.whatsapp` | `step_interpreter.py:1463` | yes | — | message out | none | n/a | yes |
| `otp_gate` | `step_interpreter.py:769` | yes | — | email OTP | none | n/a | yes |
| `pdf.generate` | `step_interpreter.py:1114` | yes | — | none | none | n/a | yes |
| `require_permission` | `step_interpreter.py:468` | yes | — | none | none | n/a | yes |
| `resolve_entity` | `step_interpreter.py:510` | yes | only_mine, where | external call | own connection | n/a | yes |
| `run_workflow` | `step_interpreter.py:1558` | yes | — | none | own connection | n/a | yes |
| `sheets.delete_row` | `step_interpreter.py:1294` | NO (alias) | table, where | DB write, external call | own connection | none | yes |
| `sheets.insert_row` | `step_interpreter.py:963` | NO (alias) | sequence, table, values | DB write, external call | own connection | none | yes |
| `sheets.update_row` | `step_interpreter.py:1205` | NO (alias) | set, table, where | DB write, external call | own connection | none | yes |

*Caution: the Side effects, Transaction and Idempotency columns come from pattern-matching each handler's own source, so they are INFERRED and miss calls made through helpers. Known misses: `pdf.generate` calls the LLM and WeasyPrint through `pdf_engine`; `ai_price_interpret` calls the LLM through `price_interpreter`; `otp_gate` writes an `otp_tokens` row and sends email through `otp_service`; `db.*` shows "external call" only because the handlers mention the Sheets client.*

**Findings (VERIFIED unless marked):**

- **Transactions:** none across steps. Each DB step uses its own pooled connection (`step_interpreter.py:1937` loop); the only transaction in the engine is the read-only one in `db.py:131`. A failure in step 5 of 7 leaves steps 1-4 committed. The code treats pdf/notify failures after an insert as success on purpose (`:1976-1996`).
- **Idempotency:** only `db.upsert_row` and `case.add_parties` use `ON CONFLICT`. `db.insert_row` takes a sequence for numbers but there is no run-level key, so a repeated confirm can create two rows (INFERRED; the Redis dedupe on webhook ids lasts 300 s). `notify.*` has none: a resumed run re-sends.
- **Failure behaviour:** `StepError`/`VerificationError` produce a user message; any other exception becomes a generic failure; conditions fail open (`:405`).
- **JSON Schema per step type from code today?** **Mostly yes.** Each spec has `key`, `kind` (table, column, alias, value, text, number, bool, choice, list, map, sequence, workflow), `required`, `required_unless`, `default`, `options`, `table_key`. A generator can emit the `params` schema and the `op` enum from it. **Missing:** (a) the 3 undeclared reads; (b) the three `sheets.*` aliases; (c) value grammar: `kind: value` accepts a literal or a `$path`, but the path roots (`$fields`, `$case`, `$user`, `$inserted`, `$route`, `$computed`, `$org_id`…) and alias scoping are enforced only in `validate_steps`, not described; (d) the `when` grammar (`exists, equals, not_equals, in, gte, lte, gt, lt, and`) is not declared; (e) outputs: what each step adds to the context is known only through `aliases_made_by` heuristics; (f) side-effect, retry and idempotency metadata do not exist.

**Against the step types you need:**

| Needed | Today | Gap |
|---|---|---|
| Collect info | `entity_schema` + `field_reader` + the agent; not a step | fine as a concept; field types are string, float, array only in live data (31 string fields in Godrej; string/float/array in Baanganga) |
| Approve | `approval_gate`: sequential levels by **role** and amount (`_required_levels_for_gate`), first level created in the step, rest walked by `handle_approval_response` | no any/all approvers, no named users, no timeout or escalation, **on-reject = tell the requester** (`workflow_executor.py:160-165`), no alternate path. **Zero live definitions** use it |
| Act / assign | `db.update_row`, `case.route`, `case.add_parties` | good; case ones are client-specific |
| Notify | `notify.user`, `notify.whatsapp`, `notify.parties` | no de-duplication, no WhatsApp template path for the 24-hour window (VERIFIED absent in `whatsapp.py`) |
| Generate document | `pdf.generate` (LLM writes HTML, WeasyPrint renders) | output not deterministic; no Excel step (Excel is an agent tool) |
| Run another workflow | `run_workflow` | synchronous, depth 5, no wait/parallel, no child run record |
| Calculate | `compute`, `derive_field`, `calc_engine` sandbox | good |
| Collect payment | none (grep for payment/razorpay/upi/stripe finds nothing) | missing |

---

## Part D: Workflow definition format

Sampled from the dumps: Godrej `file_a_complaint`, `case_find`, `case_close_with_note`; Baanganga `create_sales_invoice`, `check_stock`, `cancel_purchase_order`. Strings are replaced by `<text>`; only structure, step names and `$paths` remain.

### Samples: godrej

`file_a_complaint`
```json
{
 "intent_key": "file_a_complaint",
 "workflow_type": "action",
 "version": "1",
 "steps": [
  {
   "op": "case.categorize",
   "params": {
    "text_from": [
     "$fields.title",
     "$fields.description"
    ]
   }
  },
  {
   "op": "case.route",
   "params": {}
  },
  {
   "op": "run_workflow",
   "params": {
    "workflow": "case_create"
   }
  },
  "…"
 ],
 "entity_schema": {
  "title": {
   "type": "string",
   "label": "<text>",
   "read_by": "<text>",
   "question": "<text>",
   "required": true,
   "description": "<text>"
  },
  "location": {
   "type": "string",
   "label": "<text>",
   "read_by": "<text>",
   "question": "<text>",
   "required": true,
   "description": "<text>"
  },
  "priority": {
   "enum": [
    "<text>",
    "<text>",
    "<text>",
    "…"
   ],
   "type": "string",
   "label": "<text>",
   "question": "<text>",
   "required": true,
   "description": "<text>"
  },
  "description": {
   "type": "string",
   "label": "<text>",
   "required": false,
   "description": "<text>"
  }
 },
 "gates": [],
 "settings": {
  "photos": true
 },
 "has_sql_template": false,
 "has_response_template": true,
 "has_llm_system_prompt": false,
 "has_pdf_config": false,
 "sql_params_order": [],
 "calc_rules_keys": []
}
```

`case_find`
```json
{
 "intent_key": "case_find",
 "workflow_type": "action",
 "version": "1",
 "steps": [
  {
   "op": "resolve_entity",
   "params": {
    "into": "case",
    "table": "cases",
    "expose": {
     "resolved_case_number": "<text>"
    },
    "name_from": "$fields.case_number",
    "normalize": "identifier",
    "match_column": "case_number"
   }
  },
  {
   "op": "case.authorize",
   "params": {
    "case": "$case"
   }
  }
 ],
 "entity_schema": {
  "case_number": {
   "type": "string",
   "required": true,
   "description": "<text>"
  }
 },
 "gates": [],
 "settings": {},
 "has_sql_template": false,
 "has_response_template": false,
 "has_llm_system_prompt": false,
 "has_pdf_config": false,
 "sql_params_order": [],
 "calc_rules_keys": []
}
```

`case_close_with_note`
```json
{
 "intent_key": "case_close_with_note",
 "workflow_type": "action",
 "version": "1",
 "steps": [
  {
   "op": "run_workflow",
   "params": {
    "workflow": "case_find"
   }
  },
  {
   "op": "run_workflow",
   "params": {
    "inputs": {
     "note": "$fields.comment_text"
    },
    "workflow": "case_close"
   }
  },
  {
   "op": "case.attach_photos",
   "params": {
    "case_id": "$case.id"
   }
  },
  "…"
 ],
 "entity_schema": {
  "case_number": {
   "type": "string",
   "label": "<text>",
   "read_by": {
    "lookup": {
     "show": [
      "<text>",
      "<text>"
     ],
     "table": "cases",
     "normalize": "identifier",
     "match_column": "case_number"
    }
   },
   "question": "<text>",
   "required": true,
   "description": "<text>"
  },
  "comment_text": {
   "type": "string",
   "label": "<text>",
   "read_by": "<text>",
   "question": "<text>",
   "required": true,
   "description": "<text>"
  }
 },
 "gates": [],
 "settings": {
  "photos": true,
  "who_can_use": [
   "<text>",
   "<text>"
  ]
 },
 "has_sql_template": false,
 "has_response_template": true,
 "has_llm_system_prompt": false,
 "has_pdf_config": false,
 "sql_params_order": [],
 "calc_rules_keys": []
}
```

### Samples: baanganga

`create_sales_invoice`
```json
{
 "intent_key": "create_sales_invoice",
 "workflow_type": "action",
 "version": "1",
 "steps": [
  {
   "op": "resolve_entity",
   "params": {
    "into": "customer",
    "table": "customers",
    "expose": {
     "customer_city": "<text>",
     "customer_gstin": "<text>"
    },
    "name_from": "$fields.customer_name",
    "match_column": "name"
   }
  },
  {
   "op": "ai_price_interpret",
   "params": {}
  },
  {
   "op": "compute",
   "params": {}
  },
  "…"
 ],
 "entity_schema": {
  "items": {
   "type": "array",
   "required": true,
   "item_schema": {
    "gst": {
     "type": "float",
     "computed": true,
     "required": false
    },
    "qty": {
     "type": "integer",
     "default": 1,
     "required": false
    },
    "total": {
     "type": "float",
     "computed": true,
     "required": false
    },
    "weight": {
     "type": "float",
     "required": false
    },
    "rate_text": {
     "type": "string",
     "required": false
    },
    "unit_price": {
     "type": "float",
     "computed": true,
     "required": false
    },
    "description": {
     "type": "string",
     "required": true
    },
    "line_subtotal": {
     "type": "float",
     "computed": true,
     "required": false
    },
    "making_charges": {
     "type": "float",
     "computed": true,
     "required": false
    },
    "making_charge_pct": {
     "type": "float",
     "required": false
    }
   }
  },
  "subtotal": {
   "type": "float",
   "computed": true,
   "required": false
  },
  "gst_amount": {
   "type": "float",
   "computed": true,
   "required": false
  },
  "total_amount": {
   "type": "float",
   "computed": true,
   "required": false
  },
  "customer_name": {
   "type": "string",
   "match": "<text>",
   "table": "customers",
   "column": "name",
   "format": "<text>",
   "required": true
  },
  "making_charges_total": {
   "type": "float",
   "computed": true,
   "required": false
  }
 },
 "gates": [],
 "settings": null,
 "has_sql_template": false,
 "has_response_template": true,
 "has_llm_system_prompt": true,
 "has_pdf_config": true,
 "sql_params_order": [],
 "calc_rules_keys": [
  "item_rules",
  "aggregate_rules"
 ]
}
```

`check_stock`
```json
{
 "intent_key": "check_stock",
 "workflow_type": "read",
 "version": "1",
 "steps": [],
 "entity_schema": {
  "item_name": {
   "type": "string",
   "match": "<text>",
   "table": "inventory",
   "column": "name",
   "format": "<text>",
   "required": false
  }
 },
 "gates": [],
 "settings": null,
 "has_sql_template": true,
 "has_response_template": false,
 "has_llm_system_prompt": true,
 "has_pdf_config": true,
 "sql_params_order": [
  "item_name"
 ],
 "calc_rules_keys": []
}
```

`cancel_purchase_order`
```json
{
 "intent_key": "cancel_purchase_order",
 "workflow_type": "action",
 "version": "1",
 "steps": [
  {
   "op": "sheets.delete_row",
   "params": {
    "table": "sheet:PurchaseOrders",
    "where": {
     "po_id": "$fields.po_id"
    }
   }
  },
  {
   "op": "notify.whatsapp",
   "params": {
    "attach_pdf": false
   }
  }
 ],
 "entity_schema": {
  "po_id": {
   "type": "string",
   "required": true
  }
 },
 "gates": [],
 "settings": null,
 "has_sql_template": false,
 "has_response_template": true,
 "has_llm_system_prompt": true,
 "has_pdf_config": false,
 "sql_params_order": [],
 "calc_rules_keys": []
}
```

### Inventory

| | Godrej (19 workflows) | Baanganga (8 workflows) |
|---|---|---|
| Step keys | db.insert_row 8, resolve_entity 6, db.update_row 8, case.authorize 1, notify.user 3, derive_field 3, run_workflow 12, case.attach_photos 3, notify.parties 3, case.add_parties 2, case.categorize 1, case.route 1, notify.whatsapp 1 | sheets.update_row 1, notify.whatsapp 5, resolve_entity 3, ai_price_interpret 2, compute 3, otp_gate 2, approval_gate 2, db.insert_row 2, pdf.generate 2, sheets.delete_row 1, sheets.insert_row 1 |
| Step-level keys | {'op': 52, 'params': 52, 'when': 15} | {'op': 24, 'params': 24} |
| `when` shapes | {"('exists', 'field')": 9, "('and',)": 2, "('equals', 'field')": 2, "('field', 'not_equals')": 2} | none |
| Field keys in `entity_schema` | type 31, required 31, description 31, enum 4, label 12, read_by 10, question 11 | type 25, required 25, item_schema 2, computed 12, match 5, table 5, column 5, format 5 |
| `$path` roots | {'$case': 23, '$fields': 32, '$user': 10, '$assignee': 4, '$requester': 4, '$handler': 4, '$route': 7, '$inserted': 7} | {'$fields': 12, '$computed': 7, '$org_id': 2, '$user': 2, '$customer': 2} |
| Non-empty definition columns | {'steps': 16, 'entity_schema': 15, 'response_template': 4, 'settings': 6, 'training_phrases': 7, 'slash_command': 7, 'pdf_config': 2, 'llm_system_prompt': 2, 'sql_template': 3, 'business_glossary': 2} | {'steps': 5, 'entity_schema': 7, 'response_template': 5, 'llm_system_prompt': 8, 'business_glossary': 7, 'training_phrases': 8, 'slash_command': 8, 'calc_rules': 3, 'pdf_config': 3, 'sql_template': 3} |
| `gates` | empty in all 19 | empty in all 8 |
| `kind` / `settings` | `kind` set (12 blocks, 7 workflows), `settings` in 6 | column does not exist |
| Version | 18 at v1, one at v3 | not recorded (0 snapshots) |

### Inconsistencies

1. **Old versus new engine style.** Baanganga uses `$computed.*`, `$org_id`, `$customer`, `sheets.*` steps, `compute`/`ai_price_interpret`, `computed`/`match`/`table`/`column`/`format` field keys. Godrej uses `$case`, `$route`, `$inserted`, `run_workflow`, `case.*`, and field keys `label`, `question`, `read_by`, `enum`. They are two dialects of one language; a validator that accepts both is the only thing joining them.
2. **Magic prefix.** A Google Sheets target is `table: "sheet:…"` inside a `db.*` step or the `sheets.*` alias (`step_interpreter.py:610`), not an explicit target.
3. **References by name.** `run_workflow.workflow` = intent_key string; `roles.permissions` = text[] of intent_keys; `workflow_versions.granted_roles` = role names; `user_drafts.intent_key`; `audit_log.intent_key`. By id: routing rules, parties, seats. 64 drafts and 3 permission strings already point at nothing.
4. **No `schema_version`** on `workflows`, `workflow_versions` or `workflow_drafts`. VERIFIED (column lists).
5. **Duplicated rules.** OTP/approval thresholds exist as columns and as `gates`; response format as column, `response_template` and `pdf_config`; per-workflow `llm_system_prompt`, `business_glossary`, `training_phrases` mix runtime prompt data into the definition.
6. **Logic outside the definition:** case routing in SQL (`route_case`); access in `case_relations` and `party_access.py`; the confirmation text in `_build_confirm_summary_lines`; intent routing in the agent prompt; seat→role effects in a trigger; what a step *produces* in `aliases_made_by` heuristics; photo handling in `webhook.py`.
7. **Nesting and reuse** are expressed only as `run_workflow` by key with `inputs` mapping; no declared inputs/outputs for a block (the checker uses `aliases_needed_by` heuristics).

### Proposed canonical definition (schema_version 1)

```json
{
 "schema_version": 1,
 "key": "file_a_complaint",
 "kind": "workflow",
 "name": "File a complaint",
 "description": "\u2026",
 "triggers": {
  "slash": "complaint",
  "phrases": [
   "\u2026"
  ],
  "menu": {
   "section": "create",
   "label": "\u2026"
  }
 },
 "access": {
  "roles": [
   "owner",
   "tenant"
  ],
  "on_case": [
   "requester"
  ]
 },
 "inputs": {
  "title": {
   "type": "text",
   "required": true,
   "question": "\u2026",
   "label": "\u2026",
   "read_by": "typed"
  }
 },
 "outputs": {
  "case_id": "uuid"
 },
 "steps": [
  {
   "id": "s1",
   "op": "case.categorize",
   "params": {},
   "when": null,
   "on_error": "stop"
  }
 ],
 "gates": [
  {
   "type": "approval",
   "when": {},
   "levels": [
    {
     "approvers": {
      "any_of": [
       "role:owner"
      ]
     },
     "timeout_minutes": 1440,
     "on_reject": "stop"
    }
   ]
  }
 ],
 "messages": {
  "confirm": "key:complaint.confirm",
  "done": "key:complaint.done"
 },
 "documents": {
  "template": null
 },
 "settings": {
  "photos": {
   "max": 5
  }
 },
 "limits": {
  "draft_stale_minutes": 30
 }
}
```

Rules: steps have stable `id`s (so patches and audit can point at them); roles are referenced as `role:<name>` and resolved to ids on save; message text lives in `system_messages`, referenced by key; every block declares `inputs` and `outputs`; one dialect (the Godrej style) with `sheets` as an explicit `target`.

**Migration path (no downtime):** (1) add `schema_version` and `workflow_definitions` (see `proposed-schema.sql` P2-01) and backfill current rows as version N with `schema_version = 0` (today's format); (2) write `normalize_definition()` that maps both dialects to v1 and run it on read; (3) make the studio save v1 only; (4) a one-off tool rewrites the 27 live definitions to v1 and records a new version each; (5) remove the dialect branches once nothing reads v0.

---

## Part E: Databases

Full inventory (columns, constraints, indexes, triggers, functions, JSONB key frequency, classification, drift, integrity, versioning, unused objects, control DB, data quality) is in `db-inventory.md`; the changes are in `proposed-schema.sql` (proposals only, never run). Method: dumps parsed by script, then a read-only scan of the three live Railway databases (equivalents of the six catalog queries plus counts and key names only; no personal data selected).

**Highlights (all VERIFIED from the dumps):**

- Godrej 25 tables, 62 FKs, 10 SQL functions, 8 triggers. Baanganga 17 tables, 31 FKs, 1 function, 0 triggers. Control DB 1 table (`data_sources`, 2 rows).
- **No migration history table anywhere.** Drift: 20 tables exist in only one DB; `scheduled_reports.source_key` only in Baanganga; `users(org_id,email)` unique and `user_drafts.created_at` only in Godrej; 15 indexes on shared tables exist in Godrej but not Baanganga, including `users(phone)`; Baanganga has `pgcrypto`, Godrej does not. Part is simply the 10-day age of the Baanganga dump.
- **Debris:** `user_drafts` 84/84 expired; `otp_tokens` 69/69 expired; `workflow_drafts` 5/8 abandoned; nothing purges them (confirmed live).
- **Live scan (2026-10-03, read-only):** the Godrej dump equals live. All three databases have exactly one role, the superuser `postgres`. No migration table anywhere. `workflows.last_run` is NULL on all 27 workflows because no code writes it. Only 1 of the 19 live Godrej workflows has a version snapshot. 420 of 595 Godrej audit rows have no `session_id`, so the Chats screen cannot group them. The every-minute jobs show as 45,583 sequential scans on `cases` and about 20,580 on `scheduled_reports`: fine at 29 rows, the first thing to break at scale. The 2 Oct confirm-logging fix is visible live (12 workflow-keyed audit rows). Full list: `db-inventory.md` section 10.
- **Integrity:** every table has a primary key; soft name references (64 drafts, 3 permission strings, 2 orphan snapshots); `workflow_versions` has no FK to `workflows`; `audit_log(session_id)` unindexed; 34 of 62 FKs cascade on delete.
- **Versioning:** 4 snapshots for 19 workflows (Godrej), 0 for 8 (Baanganga); all SQL migrations 006-010 edited live definitions with no version bump and no `admin_events` row (5 rows exist, none from SQL).
- **JSON:** `cases/residents/staff.custom_fields`, `routing_rules.match`, `workflows.calc_rules` have zero keys in every row, yet 5 GIN indexes exist; `audit_log.steps_taken` is empty in all 595 rows; no JSON is validated; `workflows.entity_schema` has 13 distinct key-sets in 19 rows.
- **Unused:** only `godrej.staff_attendance` meets 'zero rows and zero code references' (and was cleared since the 1 Oct dump, which had 71 rows): a decision for the client, not a drop.
- **Control DB:** needs status, pack, pack/schema version, timezone, locale, flags, secret reference, channel config and an identity map; raw passworded URLs for the `postgres` superuser are stored.
- **Data quality:** 22 open cases, all past due, 19 unassigned; 24 of 29 cases have no category; Low priority is 10 minutes against 120 for Urgent; 1 of 29 categories has its own target.

---

## Part F: Prompts and messages

### F.1 Prompt files

| File | Lines | Variables | Workflow keys it names | Tables it names | Client words |
|---|---|---|---|---|---|
| `_base.txt` | 432 | first_word, full_name | register_complaint | customers, invoices, orders, users | complaint:3, wing:2 |
| `agent_system_wrapper.txt` | 20 | critical_tables_block, domain_prompt, org_defaults_line, org_name, permissions, role, sheets_block, today | — | — | — |
| `confirm_intent.txt` | 21 | email, name, role, text | — | — | — |
| `critic_field_mapping.txt` | 30 | description_block, entity_schema_json, schema_text | — | — | flat:2, wing:1 |
| `critic_steps_logic.txt` | 29 | description_block, entity_schema_json, steps_json | — | — | — |
| `critical_tables_block.txt` | 11 | schema | — | — | — |
| `cross_check_mapping.txt` | 18 | description_block, field_names_json, schema_text | — | — | — |
| `housing_society.txt` | 202 | assigned_name, case_number, comment_count, complainant_name, created_at, due_date, high_count, location | add_case_comment, assign_case, case_number, close_case | cases, users | complaint:17, wing:5, committee:2, flat:2 |
| `jewellery.txt` | 527 | Customer, FIRST_WORD, FULL_NAME, amount, customer, date, desc, fragment | create_sales_invoice, generate_price_quotation | customers, inventory, invoices, orders | gold:14, gst:10, making charges:7, jewels:4 |
| `pdf_generation_instructions.txt` | 165 | canonical_block, ctx_json, data_json, doc_type, layout_section, light_bg, muted_col, org_name | — | orders | gst:1 |
| `pdf_template_extraction.txt` | 11 | — | — | orders | — |
| `price_interpret.txt` | 10 | qty, rate_text, weight | — | — | gst:1, flat:1 |
| `response_formatting.txt` | 27 | glossary_json, raw_data, workflow_name | — | — | gold:1 |
| `role_match.txt` | 12 | role_names, text | — | — | flat:1 |
| `workflow_builder_system.txt` | 138 | — | assign_case | cases, residents, roles, staff | lift:3, gst:1 |
| `workflow_compiler.txt` | 359 | description_block, pdf_context, schema_text, slot_name, variable | case_number | cases, customers, entity_records, invoices | flat:4, gst:2, wing:1 |
| `workflow_creator.txt` | 27 | dsl | case_action | — | — |
| `workflow_dsl.txt` | 33 | step_types | — | — | — |
| `workflow_editor.txt` | 19 | dsl | — | — | — |

`prompt_loader.load_prompt` concatenates `_base.txt` + `{industry}.txt` + `clients/{slug}.txt` (the `clients/` directory does not exist). Inline system prompts: 4 (`studio.py:852`, `agent.py:2824`, `workflow_builder_agent.py:878,1428`). Problems (VERIFIED): `_base.txt` (shared by every industry) names `customers/invoices/orders` and the retired `register_complaint`; `housing_society.txt` named `assign_case` until commit 327a9a3, which is exactly what broke a tester's `close` on 2 Oct; `workflow_builder_system.txt` and `workflow_compiler.txt` embed housing and invoice examples; `jewellery.txt` is 527 lines of one client's rules.

### F.2 User-facing strings

77 string-bearing send calls (AST): `webhook.py` 62, `workflow_executor.py` 12, `step_interpreter.py` 2, `telegram_webhook.py` 1. Only 5 contain industry words; the rest are platform wording (onboarding, OTP, security, errors, photo notes). Each should become a `system_messages` row. Messages that are already data (good): workflow step templates, `case_reminders` templates, vocabulary.

### F.3 Proposed keys and loader

- `prompts(key, scope[global|pack|tenant], scope_ref, version, body, variables)`. Keys: `agent.system`, `agent.wrapper`, `agent.domain`, `builder.creator`, `builder.editor`, `builder.compiler`, `builder.critic.*`, `pdf.instructions`, `format.response`, `price.interpret`, `role.match`, `confirm.intent`.
- `system_messages(key, locale, scope, scope_ref, body, variables)`. Keys by area: `onboarding.*`, `otp.*`, `security.*`, `draft.*` (stale, cancelled, photo held, photo added), `approval.*`, `error.*`.
- **Precedence:** tenant over pack over global; highest active version wins; file in repo is only the seed and the last-resort fallback.
- **Variables filled from tenant data at call time:** org name, roles and permitted workflows (names and descriptions, so no key is ever hardcoded again), today in the tenant's timezone, org defaults (`prompt_vars`: GST rate, making charge), vocabulary, category list. The first of these would have prevented the `assign_case` failure.

---

## Part G: LLM paths

| Question | Runtime agent (`services/agent.py`) | Studio chat builder (`admin_panel/studio.py`) | Classic builder (`workflow_builder_agent.py`) |
|---|---|---|---|
| Where prompts load | `prompt_loader` files + `agent_system_wrapper.txt`; workflow list is built from DB per user (`_build_system_prompt`) | `prompts/workflow_creator.txt`, `workflow_editor.txt` (`_prompt(...)`) | `workflow_builder_system.txt` and inline (`:878`,`:1428`) |
| Output constrained? | Function calling with 13 tools (`update_draft`, `clarify`, `confirm_action`, `query_database`, `generate_pdf`…); arguments validated afterwards by `qa_verifier` and the schema | **No.** JSON requested in text, parsed by `_json_object`, then `validate_steps` | Function calling with 9 tools (`set_gates`, `update_builder_draft`, `compile_and_summarize`…) |
| Bad output | forced tool retry when it narrates a confirm (`agent.py` intercept); fallback ladder of up to 8 models, 12 s each (`llm_router.py:60,246-312`); worst case about 96 s (INFERRED) | 2 attempts, errors fed back; then 'could not draft cleanly' | 3-attempt compile loop + LLM critic (`workflow_compiler.py:136`, `workflow_critic.py`) |
| Ambiguity | `clarify` tool exists; code-first reader asks fixed questions | **No instruction to ask**; silent assumptions (no 'clarif' text in the prompts) | asks through chat tools; recap before publish |
| Multi-turn refinement | session history in Redis, trimmed | last 6 messages from the browser | `workflow_drafts.chat_history` with compaction (`:667`) |
| Edits as patches? | n/a | **Full rewrite**, diff computed after the fact (`diff_steps`) | full spec rewrite (`revise_draft`) |
| Dry run before save | 'What happens next' preview from the engine dry run | Try it (engine dry run with trace) | PDF preview only (`workflow_previewer.py`) |
| Tests / evals | none | none | none |
| Cost / latency | no token or cost logging anywhere (`grep usage` empty); cooldowns in process memory | per-tenant rate limit in process memory (`studio.py:738`) | none |

**Gap list against the target pipeline** (understand → ground → constrained draft → layered validation with repair → deterministic compile → preview/diff/simulate → apply; edits as patches; evals):

1. *Understand:* add a clarification contract (return `questions[]` when roles, users, thresholds or fields are unknown) in the studio prompts.
2. *Ground:* the studio already passes tables and blocks; add roles, seats, categories and existing field names so unknown roles are flagged, not invented.
3. *Constrained draft:* use JSON-schema structured output (generated from the registry) or a single tool call per edit; drop free-text JSON parsing.
4. *Layered validation:* keep `validate_steps`; add the definition-format schema; delete `workflow_validator.py`.
5. *Compile:* normalise to the canonical format deterministically.
6. *Preview/diff/simulate:* have it (diff, Try it); add simulation against sample tenant data and show message text.
7. *Apply as patches:* ids on steps, edits returned as `add/replace/remove step <id>`; apply through the single publish function that snapshots.
8. *Evals:* 50-100 requests with expected structure, run on every prompt change (prompts will be in the DB, so changes must be gated).
9. *Cost:* log tokens and model per call into an `llm_calls` table.
10. *Prompt injection:* builder input is admin-only, output is structurally validated, and nothing executes before Apply; the exposure is a malicious building-block description reaching the prompt (INFERRED, low). The runtime agent takes end-user text and can call `query_database`; mitigated by the sqlglot guard and permissions.

---

## Part H: Two change tests, traced through the code and DB

### H.1 Add a manufacturing client

| # | What you must do | Where (evidence) | Tier |
|---|---|---|---|
| 1 | Insert a `data_sources` row (key, URL, channel) | routing DB; URL stored raw | config |
| 2 | Create the tenant database and its schema | **no baseline schema in the repo**; `migrations/baanganga.sql` and `godrej.sql` are alter-only and per client | **defect** |
| 3 | Insert `orgs`, `roles`, `users` | tenant DB | config |
| 4 | Seed `orgs.settings.vocabulary` (confirm/cancel words) | `vocabulary.py` returns an empty set otherwise, so 'yes' never matches by code; the referenced `migrations/seed_vocabulary.sql` **does not exist** in the repo (git log empty) | config + **defect** (missing seed) |
| 5 | Industry prompt `manufacturing.txt` | `prompt_loader.py:27`; without it the tenant gets only `_base.txt`, which contains jewellery and housing content | **defect** (new file + deploy) |
| 6 | Pick a messaging channel | `db.py:92-110` raises when two tenants claim one channel; WhatsApp and Telegram are each already claimed | **defect** |
| 7 | Give the client its own WhatsApp number or bot | credentials are global env values read in `whatsapp.py`, `telegram.py`; routing by `tg:` prefix in `messaging.py` | **defect** (3 files + env) |
| 8 | Users' phones must not exist in another tenant | `identity.py:25` returns the first tenant that matches | design **defect** |
| 9 | Timezone other than IST | `db.py:38`, `jobs.py:22`, `agent.py:1923,1946` | **defect** (3 files) if not IST |
| 10 | Business tables (work orders, BOMs) | create by SQL; the engine reads the live schema (`schema_utils.py`) so it can write to them | config (but per-client tables) |
| 11 | Workflows | studio chat / blank / copy; dashboard sections appear by capability probe, so Cases/People/Routing are hidden | config |
| 12 | SLA reminders | `orgs.settings.case_reminders` is generic; scheduler iterates all tenants automatically | config |
| 13 | Documents and logo | `pdf_config` per workflow, logo upload | config |
| 14 | New behaviour, e.g. stock deduction, BOM explosion | new step types | registry (acceptable once; 1-3 steps) |

**Count:** 8 config touches (rows 1, 3, 4, 10, 11, 12, 13 and settings), 1-3 registry additions, **6 defects touching 8 files**: `db.py`, `messaging.py`, `whatsapp.py`, `telegram.py`, `jobs.py`, `agent.py`, new `app/prompts/manufacturing.txt`, and a new baseline migration. Verdict: not repeatable without a developer.

### H.2 Extra field on people, and a new optional capability

**Extra field on people.**
- *JSON config tier:* a workflow can capture and write it today through `json_key: custom_fields.<name>` in `entity_schema` and a nested `custom_fields` in `db.insert_row` (documented in `step_interpreter.py` header). Works for `residents`, `staff`, `cases` (they have `custom_fields`).
- *Blocks today:* (1) `users`, the core people table, has **no attributes column** (only id, org, role, name, phone, email, channel, is_active, created_at), and Baanganga's `customers` has none either, so a core migration is needed; (2) the dashboard's People screens read fixed columns (`admin_panel/people.py`), so the new field does not appear without code and a JS change; (3) there is no UI to define a person field (`case_categories.extra_fields` exists for cases only); (4) 5 GIN indexes already exist on JSON that holds no keys, which shows the pattern was built and never used.
- *Correct tier:* JSON attribute (`users.attributes jsonb`, field definitions in tenant config) with a core migration **once**.

**New optional capability** (example: photos on close, which I added today).
- It needed a **code change** (the photo-ordering logic in `webhook.py`) and a **data change** (SQL 009: one workflow's steps and `settings.photos`, and one block's `with_photos`). The data part was pure config; the code part was a registry-level behaviour.
- *Blocks today:* no tenant feature flags (control DB has no `flags`); the registry is global, so every tenant gets the case steps and they fail at run time on databases without case tables; no pack mechanism, so 'optional' means a hand-run SQL file; the SQL edit bypassed versioning.
- *Correct tier:* if built from existing steps → JSON workflow config + a flag in `workflows.settings`; if it needs new behaviour → one new registry step with a parameter schema and, if it needs tables, a core or pack migration, switched on per tenant by a feature flag.

---

## Appendix: what I could not determine

- Whether Railway runs more than one replica (affects duplicate scheduled jobs).
- Contents of `sheets_creds_b64.txt` (deliberately not opened).
- Whether any approval or OTP gate has ever fired in production (the dumps show `pending_approvals` empty).
- Behaviour under load, and LLM latency and cost (not measured anywhere).
- Redis (not part of the Railway project; not inspected).
- When Postgres statistics were last reset (so 'index never scanned' is not turned into a drop recommendation).
