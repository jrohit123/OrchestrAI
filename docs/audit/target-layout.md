# Proposed layout

Every current module is mapped (see `module-map.md` for the reason and effort). Nothing here has been moved. The order of work is in `architecture-audit.md` (migration phases).

```
app/
  core/
    tenancy/      db.py  identity.py  redis.py        # control DB lookups, per-tenant pools, timezone, channel map
    config_store/ env.py  prompts.py  messages.py  vocabulary.py  settings.py   # tenant config with global < pack < tenant precedence
    engine/       interpreter.py  run.py  runs.py  approvals.py  sla.py  scheduler.py  menu.py  readers.py  agent/
    registry/     catalog.py  validate.py  sql_preview.py  steps/      # one file per step type with a parameter schema
    builder/      chat.py  compile.py  critic.py  preview.py  publish.py  evals/
    llm/          router.py  models.json
    channels/     whatsapp.py  telegram.py  send.py  onboarding.py  *_webhook.py
    admin/        common.py  meta.py  studio.py  workflows.py  activity.py  static/
  main.py
packs/
  _global/                   # prompts and messages every tenant gets
  housing_society/           # roles, starter workflows, prompts, messages, vocabulary, seed
  jewellery/
  case_management/           # optional capability: case steps, case admin screens, case migrations
migrations/
  control/                   # routing DB
  core/                      # identical for every tenant, with schema_migrations table in each DB
schemas/                     # JSON Schema generated from the step registry and the definition format
tools/
  new_tenant.py  migrate.py  load_pack.py
docs/
```

## Where every current module goes

| Target | Comes from |
|---|---|
| `(deleted after migration to admin_panel)` | `app/routers/admin.py` |
| `-` | `app/services/__init__.py` |
| `app/__init__.py` | `app/__init__.py` |
| `app/core/admin/__init__.py` | `app/admin_panel/__init__.py` |
| `app/core/admin/activity.py` | `app/admin_panel/activity.py` |
| `app/core/admin/common.py` | `app/admin_panel/common.py` |
| `app/core/admin/meta.py` | `app/admin_panel/meta.py` |
| `app/core/admin/pages.py` | `app/admin_panel/pages.py` |
| `app/core/admin/static/core.js` | `app/admin_panel/ui/js_core.py` |
| `app/core/admin/static/panel.css` | `app/admin_panel/ui/css.py` |
| `app/core/admin/static/rest.js` | `app/admin_panel/ui/js_rest.py` |
| `app/core/admin/static/studio.js` | `app/admin_panel/ui/js_studio.py` |
| `app/core/admin/static/studio_form.js` | `app/admin_panel/ui/js_studio_form.py` |
| `app/core/admin/studio.py + app/core/builder/chat.py` | `app/admin_panel/studio.py` |
| `app/core/admin/ui/__init__.py` | `app/admin_panel/ui/__init__.py` |
| `app/core/admin/workflows.py` | `app/admin_panel/workflows.py` |
| `app/core/builder/classic_agent.py (retire)` | `app/services/workflow_builder_agent.py` |
| `app/core/builder/compile.py` | `app/services/workflow_compiler.py` |
| `app/core/builder/critic.py` | `app/services/workflow_critic.py` |
| `app/core/builder/pdf_template.py` | `app/services/pdf_template_extractor.py` |
| `app/core/builder/preview.py` | `app/services/workflow_previewer.py` |
| `app/core/builder/publish.py` | `app/services/workflow_publisher.py` |
| `app/core/channels/__init__.py` | `app/routers/__init__.py` |
| `app/core/channels/onboarding.py` | `app/services/onboarding_llm.py`, `app/services/onboarding_parsing.py` |
| `app/core/channels/send.py` | `app/services/messaging.py` |
| `app/core/channels/sheets.py` | `app/services/sheets_client.py` |
| `app/core/channels/telegram.py` | `app/services/telegram.py` |
| `app/core/channels/telegram_webhook.py` | `app/routers/telegram_webhook.py` |
| `app/core/channels/whatsapp.py` | `app/services/whatsapp.py` |
| `app/core/channels/whatsapp_webhook.py + app/core/engine/turn.py` | `app/routers/webhook.py` |
| `app/core/config_store/env.py` | `app/config.py` |
| `app/core/config_store/prompts.py` | `app/services/prompt_loader.py` |
| `app/core/config_store/vocabulary.py` | `app/services/vocabulary.py` |
| `app/core/engine/__init__.py` | `app/executor/__init__.py`, `app/scheduler/__init__.py` |
| `app/core/engine/agent/{loop,tools,prompt,pdf_tool,schedule_tool}.py` | `app/services/agent.py` |
| `app/core/engine/approvals.py` | `app/executor/workflow_executor.py` |
| `app/core/engine/calc.py` | `app/services/calc_engine.py` |
| `app/core/engine/documents/excel.py` | `app/services/excel_engine.py` |
| `app/core/engine/documents/pdf.py` | `app/services/pdf_engine.py` |
| `app/core/engine/documents/preprocess.py` | `app/services/pdf_preprocessor.py` |
| `app/core/engine/interpreter.py + app/core/registry/steps/*.py` | `app/services/step_interpreter.py` |
| `app/core/engine/menu.py` | `app/services/menu.py` |
| `app/core/engine/otp.py` | `app/services/otp_service.py` |
| `app/core/engine/readers.py` | `app/services/field_reader.py` |
| `app/core/engine/report_format.py` | `app/services/report_format.py` |
| `app/core/engine/reports.py` | `app/services/query_engine.py` |
| `app/core/engine/run.py` | `app/services/action_executor.py` |
| `app/core/engine/runs.py` | `app/services/draft_store.py` |
| `app/core/engine/scheduler.py + sla.py` | `app/scheduler/jobs.py` |
| `app/core/engine/schema_cache.py` | `app/services/schema_utils.py` |
| `app/core/engine/sql_guard.py` | `app/services/sql_guard.py` |
| `app/core/engine/verify.py` | `app/services/qa_verifier.py` |
| `app/core/llm/models.json (default) + control DB platform_settings` | `app/ai_models_config.json` |
| `app/core/llm/router.py` | `app/services/llm_router.py` |
| `app/core/logging.py` | `app/logging_config.py` |
| `app/core/registry/catalog.py + schemas/steps/*.json` | `app/services/step_catalog.py` |
| `app/core/registry/sql_preview.py` | `app/services/step_sql.py` |
| `app/core/tenancy/db.py` | `app/db.py` |
| `app/core/tenancy/identity.py` | `app/services/identity.py` |
| `app/core/tenancy/redis.py` | `app/redis_client.py` |
| `app/core/util/json.py` | `app/services/json_utils.py` |
| `app/main.py` | `app/main.py` |
| `generated from the registry` | `app/prompts/workflow_dsl.txt` |
| `merge into app/core/registry/validate.py` | `app/services/workflow_validator.py` |
| `packs/_global/prompts/base.md -> prompts table` | `app/prompts/_base.txt` |
| `packs/case_management/access.py` | `app/services/party_access.py` |
| `packs/case_management/admin/cases.py` | `app/admin_panel/cases.py` |
| `packs/case_management/admin/overview.py` | `app/admin_panel/overview.py` |
| `packs/case_management/admin/people.py` | `app/admin_panel/people.py` |
| `packs/case_management/admin/routing.py` | `app/admin_panel/routing.py` |
| `packs/case_management/admin/static/cases.js` | `app/admin_panel/ui/js_overview_cases.py` |
| `packs/case_management/admin/static/people.js` | `app/admin_panel/ui/js_people.py` |
| `packs/case_management/admin/static/routing.js` | `app/admin_panel/ui/js_routing.py` |
| `packs/case_management/steps.py` | `app/services/case_ops.py` |
| `packs/housing_society/prompts/domain.md` | `app/prompts/housing_society.txt` |
| `packs/jewellery/price.py` | `app/services/price_interpreter.py` |
| `packs/jewellery/prompts/domain.md` | `app/prompts/jewellery.txt` |
| `packs/jewellery/prompts/price.md` | `app/prompts/price_interpret.txt` |
| `prompts table (global builder)` | `app/prompts/workflow_builder_system.txt`, `app/prompts/workflow_compiler.txt`, `app/prompts/workflow_creator.txt`, `app/prompts/workflow_editor.txt` |
| `prompts table (global)` | `app/prompts/agent_system_wrapper.txt`, `app/prompts/confirm_intent.txt`, `app/prompts/critic_field_mapping.txt`, `app/prompts/critic_steps_logic.txt`, `app/prompts/critical_tables_block.txt`, `app/prompts/cross_check_mapping.txt`, `app/prompts/pdf_generation_instructions.txt`, `app/prompts/pdf_template_extraction.txt`, `app/prompts/response_formatting.txt`, `app/prompts/role_match.txt` |
