# Module map

Source: repository at HEAD of `dev` (commit e542a27 plus working tree), scanned by script on 2026-10-03. Line counts are physical lines. Fan-in and fan-out count imports between `app/` modules, including imports inside functions. **VERIFIED** by running the scan.

## Summary by class

| Class | Files | Lines |
|---|---|---|
| ENGINE | 32 | 10998 |
| REGISTRY | 2 | 1437 |
| CHANNEL | 8 | 2653 |
| BUILDER | 11 | 3546 |
| ADMIN | 13 | 3985 |
| CONFIG-IN-CODE | 13 | 828 |
| CLIENT-SPECIFIC | 13 | 3930 |
| DEAD/DUPLICATE | 2 | 3545 |

Files over 800 lines: `app/services/agent.py` (3786), `app/routers/admin.py` (3222), `app/services/step_interpreter.py` (2093), `app/routers/webhook.py` (1733), `app/services/workflow_builder_agent.py` (1556), `app/admin_panel/studio.py` (1027), `app/services/step_catalog.py` (990)

Import cycles (all hidden behind imports inside functions; there are 0 at module level): `app/admin_panel/studio.py` ↔ `app/admin_panel/workflows.py`; `app/scheduler/jobs.py` ↔ `app/services/agent.py`; `app/services/case_ops.py` ↔ `app/services/step_interpreter.py`; `app/services/workflow_builder_agent.py` ↔ `app/services/workflow_compiler.py`.

## Table

| Current path | Lines | In/Out | Class | Target path | Action | Effort | Reason |
|---|---|---|---|---|---|---|---|
| `app/__init__.py` | 1 | 0/0 | ENGINE | `app/__init__.py` | keep | S | package marker |
| `app/admin_panel/__init__.py` | 31 | 1/9 | ADMIN | `app/core/admin/__init__.py` | move | S | router assembly |
| `app/admin_panel/activity.py` | 137 | 1/2 | ADMIN | `app/core/admin/activity.py` | move | S | chats and change log |
| `app/admin_panel/cases.py` | 372 | 5/2 | CLIENT-SPECIFIC | `packs/case_management/admin/cases.py` | move | M | cases screen |
| `app/admin_panel/common.py` | 309 | 8/2 | ADMIN | `app/core/admin/common.py` | move | S | context, capabilities probe, audit helper |
| `app/admin_panel/meta.py` | 246 | 1/3 | ADMIN | `app/core/admin/meta.py` | move | S | sections by capability |
| `app/admin_panel/overview.py` | 127 | 1/3 | CLIENT-SPECIFIC | `packs/case_management/admin/overview.py` | move | M | case numbers on the overview |
| `app/admin_panel/pages.py` | 48 | 2/1 | ADMIN | `app/core/admin/pages.py` | move | S | page shell |
| `app/admin_panel/people.py` | 756 | 1/3 | CLIENT-SPECIFIC | `packs/case_management/admin/people.py` | move | L | committee seats, residents, special access: housing model |
| `app/admin_panel/routing.py` | 664 | 1/3 | CLIENT-SPECIFIC | `packs/case_management/admin/routing.py` | move | L | categories and rules for cases |
| `app/admin_panel/studio.py` **>800** | 1027 | 2/12 | ADMIN | `app/core/admin/studio.py + app/core/builder/chat.py` | split | M | editor API plus chat builder in one 1,027-line file |
| `app/admin_panel/ui/__init__.py` | 39 | 1/8 | ADMIN | `app/core/admin/ui/__init__.py` | move | S | assembles JS/CSS strings |
| `app/admin_panel/ui/css.py` | 250 | 1/0 | ADMIN | `app/core/admin/static/panel.css` | move | S | ship as real static files (the .html ignore rule is why they are strings) |
| `app/admin_panel/ui/js_core.py` | 322 | 1/0 | ADMIN | `app/core/admin/static/core.js` | move | S | shared helpers |
| `app/admin_panel/ui/js_overview_cases.py` | 207 | 1/0 | CLIENT-SPECIFIC | `packs/case_management/admin/static/cases.js` | move | M | case screens |
| `app/admin_panel/ui/js_people.py` | 278 | 1/0 | CLIENT-SPECIFIC | `packs/case_management/admin/static/people.js` | move | M | people screens |
| `app/admin_panel/ui/js_rest.py` | 267 | 1/0 | ADMIN | `app/core/admin/static/rest.js` | move | S | activity, settings, shell |
| `app/admin_panel/ui/js_routing.py` | 161 | 1/0 | CLIENT-SPECIFIC | `packs/case_management/admin/static/routing.js` | move | M | routing screens |
| `app/admin_panel/ui/js_studio.py` | 685 | 1/0 | ADMIN | `app/core/admin/static/studio.js` | move | M | workflow screens |
| `app/admin_panel/ui/js_studio_form.py` | 332 | 1/0 | ADMIN | `app/core/admin/static/studio_form.js` | move | S | step forms |
| `app/admin_panel/workflows.py` | 292 | 2/5 | ADMIN | `app/core/admin/workflows.py` | move | S | list, on/off, delete |
| `app/ai_models_config.json` | 7 | 0/0 | CONFIG-IN-CODE | `app/core/llm/models.json (default) + control DB platform_settings` | move | S | model roster is data |
| `app/config.py` | 10 | 9/0 | ENGINE | `app/core/config_store/env.py` | move | S | env loading; add typed settings |
| `app/db.py` | 140 | 33/2 | ENGINE | `app/core/tenancy/db.py` | split | M | pool + routing mixed; add per-tenant timezone, control-DB lookups, read-only pool |
| `app/executor/__init__.py` | 1 | 0/0 | ENGINE | `app/core/engine/__init__.py` | move | S | package marker |
| `app/executor/workflow_executor.py` | 307 | 1/6 | ENGINE | `app/core/engine/approvals.py` | merge | M | approval responses and OTP resume; 12 literal messages; belongs with the approval step |
| `app/logging_config.py` | 136 | 34/0 | ENGINE | `app/core/logging.py` | move | S | good PII redaction; keep |
| `app/main.py` | 194 | 0/10 | ENGINE | `app/main.py` | split | S | app wiring is fine; remove /debug endpoints, add auth dependency, move scheduler start out of web process |
| `app/prompts/_base.txt` | 432 | 0/0 | CONFIG-IN-CODE | `packs/_global/prompts/base.md -> prompts table` | split | M | generic rules mixed with jewellery/housing examples |
| `app/prompts/agent_system_wrapper.txt` | 20 | 0/0 | CONFIG-IN-CODE | `prompts table (global)` | move | S | wrapper with 11 variables |
| `app/prompts/confirm_intent.txt` | 21 | 0/0 | CONFIG-IN-CODE | `prompts table (global)` | move | S | generic |
| `app/prompts/critic_field_mapping.txt` | 30 | 0/0 | CONFIG-IN-CODE | `prompts table (global)` | move | S | builder critic |
| `app/prompts/critic_steps_logic.txt` | 29 | 0/0 | CONFIG-IN-CODE | `prompts table (global)` | move | S | builder critic |
| `app/prompts/critical_tables_block.txt` | 11 | 0/0 | CONFIG-IN-CODE | `prompts table (global)` | move | S | generic |
| `app/prompts/cross_check_mapping.txt` | 18 | 0/0 | CONFIG-IN-CODE | `prompts table (global)` | move | S | builder |
| `app/prompts/housing_society.txt` | 202 | 0/0 | CLIENT-SPECIFIC | `packs/housing_society/prompts/domain.md` | move | M | industry pack content |
| `app/prompts/jewellery.txt` | 527 | 0/0 | CLIENT-SPECIFIC | `packs/jewellery/prompts/domain.md` | move | M | industry pack content, 527 lines |
| `app/prompts/pdf_generation_instructions.txt` | 165 | 0/0 | CONFIG-IN-CODE | `prompts table (global)` | move | S | generic |
| `app/prompts/pdf_template_extraction.txt` | 11 | 0/0 | CONFIG-IN-CODE | `prompts table (global)` | move | S | generic |
| `app/prompts/price_interpret.txt` | 10 | 0/0 | CLIENT-SPECIFIC | `packs/jewellery/prompts/price.md` | move | S | jewellery |
| `app/prompts/response_formatting.txt` | 27 | 0/0 | CONFIG-IN-CODE | `prompts table (global)` | move | S | one jewellery example |
| `app/prompts/role_match.txt` | 12 | 0/0 | CONFIG-IN-CODE | `prompts table (global)` | move | S | generic |
| `app/prompts/workflow_builder_system.txt` | 138 | 0/0 | BUILDER | `prompts table (global builder)` | split | S | contains housing examples |
| `app/prompts/workflow_compiler.txt` | 359 | 0/0 | BUILDER | `prompts table (global builder)` | split | M | 359 lines with housing/invoice examples |
| `app/prompts/workflow_creator.txt` | 27 | 0/0 | BUILDER | `prompts table (global builder)` | move | S | studio creator |
| `app/prompts/workflow_dsl.txt` | 33 | 0/0 | BUILDER | `generated from the registry` | rewrite | S | should be produced from step specs, not hand-kept |
| `app/prompts/workflow_editor.txt` | 19 | 0/0 | BUILDER | `prompts table (global builder)` | move | S | studio editor |
| `app/redis_client.py` | 68 | 6/2 | ENGINE | `app/core/tenancy/redis.py` | move | S | sessions and locks |
| `app/routers/__init__.py` | 1 | 0/0 | ENGINE | `app/core/channels/__init__.py` | move | S | package marker |
| `app/routers/admin.py` **>800** | 3222 | 1/12 | DEAD/DUPLICATE | `(deleted after migration to admin_panel)` | delete | L | 3,222-line classic admin with inline HTML/JS, no auth, duplicates admin_panel and the studio |
| `app/routers/telegram_webhook.py` | 110 | 1/4 | CHANNEL | `app/core/channels/telegram_webhook.py` | move | S | thin; make secret mandatory |
| `app/routers/webhook.py` **>800** | 1733 | 2/17 | CHANNEL | `app/core/channels/whatsapp_webhook.py + app/core/engine/turn.py` | split | L | 1,733 lines: WhatsApp webhook, onboarding, OTP, identity and the whole turn loop in one file |
| `app/scheduler/__init__.py` | 1 | 0/0 | ENGINE | `app/core/engine/__init__.py` | move | S | package marker |
| `app/scheduler/jobs.py` | 571 | 2/5 | ENGINE | `app/core/engine/scheduler.py + sla.py` | split | M | scheduled reports + two-pass SLA reminders; move SLA to policy tables; run outside web replicas |
| `app/services/__init__.py` | 1 | 6/0 | ENGINE | `-` | delete | S | package marker |
| `app/services/action_executor.py` | 161 | 2/4 | ENGINE | `app/core/engine/run.py` | keep | M | loads latest definition by key; must load the pinned version |
| `app/services/agent.py` **>800** | 3786 | 3/25 | ENGINE | `app/core/engine/agent/{loop,tools,prompt,pdf_tool,schedule_tool}.py` | split | L | 3,786 lines: tool loop, 13 tools, SQL tool, PDF/invoice maths, schedules in one module; fan-out 25 |
| `app/services/calc_engine.py` | 196 | 3/0 | ENGINE | `app/core/engine/calc.py` | move | S | sandboxed expressions; keep |
| `app/services/case_ops.py` | 490 | 1/5 | CLIENT-SPECIFIC | `packs/case_management/steps.py` | move | M | six step types that assume cases, parties and routing |
| `app/services/draft_store.py` | 87 | 4/1 | ENGINE | `app/core/engine/runs.py` | rewrite | M | becomes workflow_runs with pinned version; add purge |
| `app/services/excel_engine.py` | 92 | 1/0 | ENGINE | `app/core/engine/documents/excel.py` | move | S | document helper |
| `app/services/field_reader.py` | 443 | 1/2 | ENGINE | `app/core/engine/readers.py` | move | M | code-first answer reading; good |
| `app/services/identity.py` | 168 | 2/2 | ENGINE | `app/core/tenancy/identity.py` | rewrite | M | scans every tenant DB per message; use a control-DB map |
| `app/services/json_utils.py` | 30 | 7/0 | ENGINE | `app/core/util/json.py` | move | S | helper |
| `app/services/llm_router.py` | 317 | 10/1 | ENGINE | `app/core/llm/router.py` | move | M | fallback ladder; add usage and cost logging, per-purpose model config |
| `app/services/menu.py` | 149 | 2/5 | ENGINE | `app/core/engine/menu.py` | move | S | fixed section labels move to config |
| `app/services/messaging.py` | 128 | 6/3 | CHANNEL | `app/core/channels/send.py` | move | S | dispatch by id prefix; make per-tenant |
| `app/services/onboarding_llm.py` | 95 | 1/3 | CHANNEL | `app/core/channels/onboarding.py` | merge | S | linking fallback |
| `app/services/onboarding_parsing.py` | 96 | 1/0 | CHANNEL | `app/core/channels/onboarding.py` | merge | S | linking parsing |
| `app/services/otp_service.py` | 306 | 3/3 | ENGINE | `app/core/engine/otp.py` | move | S | email OTP; settings already in orgs columns |
| `app/services/party_access.py` | 78 | 3/2 | CLIENT-SPECIFIC | `packs/case_management/access.py` | move | S | workflow access by role on a case |
| `app/services/pdf_engine.py` | 453 | 3/5 | ENGINE | `app/core/engine/documents/pdf.py` | move | M | LLM-generated PDF; templates should be tenant config |
| `app/services/pdf_preprocessor.py` | 132 | 2/0 | ENGINE | `app/core/engine/documents/preprocess.py` | move | S | document helper |
| `app/services/pdf_template_extractor.py` | 146 | 2/3 | BUILDER | `app/core/builder/pdf_template.py` | move | S | authoring-time tool |
| `app/services/price_interpreter.py` | 58 | 1/3 | CLIENT-SPECIFIC | `packs/jewellery/price.py` | move | S | jewellery price parsing; used by ai_price_interpret |
| `app/services/prompt_loader.py` | 45 | 8/0 | CONFIG-IN-CODE | `app/core/config_store/prompts.py` | rewrite | M | files by industry -> prompts table with tenant > pack > global precedence |
| `app/services/qa_verifier.py` | 176 | 2/3 | ENGINE | `app/core/engine/verify.py` | move | S | draft-data verification |
| `app/services/query_engine.py` | 193 | 1/2 | ENGINE | `app/core/engine/reports.py` | rewrite | M | stored-report SQL still uses regex guard; switch to named queries |
| `app/services/report_format.py` | 130 | 2/0 | ENGINE | `app/core/engine/report_format.py` | move | S | code-worded reports |
| `app/services/schema_utils.py` | 263 | 3/1 | ENGINE | `app/core/engine/schema_cache.py` | move | S | tenant schema introspection |
| `app/services/sheets_client.py` | 155 | 2/0 | CHANNEL | `app/core/channels/sheets.py` | move | S | Google Sheets target; make explicit step param instead of 'sheet:' prefix |
| `app/services/sql_guard.py` | 290 | 1/2 | ENGINE | `app/core/engine/sql_guard.py` | move | S | sqlglot guard; good |
| `app/services/step_catalog.py` **>800** | 990 | 2/0 | REGISTRY | `app/core/registry/catalog.py + schemas/steps/*.json` | split | M | the declared parameter specs; generate JSON Schema from it |
| `app/services/step_interpreter.py` **>800** | 2093 | 7/17 | ENGINE | `app/core/engine/interpreter.py + app/core/registry/steps/*.py` | split | L | 2,093 lines: runner, 19 step handlers, expression helpers |
| `app/services/step_sql.py` | 447 | 2/0 | REGISTRY | `app/core/registry/sql_preview.py` | move | S | generated read-only SQL view; good pattern |
| `app/services/telegram.py` | 205 | 4/2 | CHANNEL | `app/core/channels/telegram.py` | move | S | single global bot token; per tenant |
| `app/services/vocabulary.py` | 102 | 3/2 | ENGINE | `app/core/config_store/vocabulary.py` | move | S | zero words in code; the model to copy |
| `app/services/whatsapp.py` | 131 | 1/2 | CHANNEL | `app/core/channels/whatsapp.py` | move | S | single global token; take credentials per tenant |
| `app/services/workflow_builder_agent.py` **>800** | 1556 | 2/8 | BUILDER | `app/core/builder/classic_agent.py (retire)` | delete | L | 1,556-line classic builder with its own draft tables; replaced by studio chat |
| `app/services/workflow_compiler.py` | 367 | 2/8 | BUILDER | `app/core/builder/compile.py` | merge | M | 3-attempt compile loop; merge with studio chat pipeline |
| `app/services/workflow_critic.py` | 238 | 1/4 | BUILDER | `app/core/builder/critic.py` | move | S | LLM semantic critique; keep as optional layer |
| `app/services/workflow_previewer.py` | 146 | 1/4 | BUILDER | `app/core/builder/preview.py` | merge | S | PDF preview; fold into the dry run |
| `app/services/workflow_publisher.py` | 517 | 3/5 | BUILDER | `app/core/builder/publish.py` | rewrite | M | writes workflows + versions; must be the only write path (migrations too) |
| `app/services/workflow_validator.py` | 323 | 5/1 | DEAD/DUPLICATE | `merge into app/core/registry/validate.py` | merge | M | second validator beside step_catalog.validate_steps |

## Files outside `app/`

| Path | Class | Target | Action | Effort | Reason |
|---|---|---|---|---|---|
| `migrations/baanganga.sql` | CLIENT-SPECIFIC | `migrations/core/0001_baseline.sql + packs/jewellery/seed.sql` | split | L | per-client one-shot file; there is no baseline schema in the repo |
| `migrations/godrej.sql` | CLIENT-SPECIFIC | `migrations/core/0001_baseline.sql + packs/housing_society/seed.sql` | split | L | same |
| `migrations/godrej_002_case_model.sql` | CLIENT-SPECIFIC | `packs/case_management/migrations/0001.sql` | move | M | case model tables and SQL functions |
| `migrations/godrej_002_seed.sql … godrej_010_plumbing_rule.sql` | CLIENT-SPECIFIC | `packs/housing_society/migrations/ + seed` | move | M | hand-run SQL edits to live definitions; no version bump (see db-inventory N2) |
| `sheets_creds_b64.txt, scratch_defs.pkl` | DEAD/DUPLICATE | `(delete from git and history)` | delete | S | tracked secrets/scratch artefact; nothing loads them |
| `google-sheets-whatsapp-integration.md` | DEAD/DUPLICATE | `docs/` | move | S | documentation at repo root |
| `prototypes/workflow-studio-prototype.html` | DEAD/DUPLICATE | `docs/prototypes/` | move | S | design prototype |
| `.github/workflows/*.yml` | ENGINE | `keep + add test job` | keep | S | CI is lint only |
