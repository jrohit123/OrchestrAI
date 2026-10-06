# Database changes

Numbered SQL files, applied with `python -m tools.migrate` (usage and safety rules are at the top of `tools/migrate.py`).

| Folder | Goes to | File name |
|---|---|---|
| `core/` | every client database | `core-0001_short_name.sql` |
| `control/` | the routing database | `control-0001_short_name.sql` |
| `features/<name>/` | only the clients listed in that folder's `feature.json`, like `{"tenants": ["godrej"]}` | `<name>-0001_short_name.sql` |

Rules for every file:

- It must be safe to run twice (`IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, ...).
- Never edit a file after it was applied anywhere. Add a new number instead.
- No `BEGIN` / `COMMIT`: the tool opens and closes the transaction.
- Only the first comment lines of a file may carry a marker: `-- no-transaction` (needed for `CREATE INDEX CONCURRENTLY`) or `-- allow-destructive` (drop / rename / truncate, refused otherwise).

The loose files in this folder (`godrej_00x_*.sql`, `baanganga.sql`, ...) are older, were run by hand, and are not read by the tool.

## Files so far

| File | What it does | Risk |
|---|---|---|
| `core-0001_align` | adds the columns, the `kind` rules and the `admin_events` table that one client was missing | additions only |
| `core-0002_align_indexes` | adds missing indexes (`CONCURRENTLY`, no blocking) | additions only |
| `core-0003_baseline_check` | changes nothing; stops with a list if 0001 or 0002 left anything missing. Its row is the baseline | none |
| `core-0005_fix_draft_index` | makes Baanganga's one-open-draft rule the same as Godrej's | replaces one index |
| `core-0006_audit_log_session_index` | index for opening one chat on the dashboard (`CONCURRENTLY`) | additions only |
| `core-0007_audit_log_intent_index` | index for the Workflows screen's "Last used" column (`CONCURRENTLY`) | additions only |
| `core-0008_cancel_orphan_drafts` | cancels open drafts whose workflow was removed, and marks builder drafts that lost their workflow as abandoned; nothing is deleted. It matched no row on the practice copies | changes data, only such drafts |
| `core-0009_settings_foundation` | the base for settings, message texts and AI instructions kept in the database: two columns on `orgs` (`timezone`, `locale`, defaulting to what the code assumes today) and two empty tables (`prompts`, `system_messages`, with versions). Nothing reads them until the code is deployed, and with no rows the code uses its built-in text, so nothing changes | additions only |
| `core-0010_archived_rows` | one empty table, `archived_rows`, where the nightly cleanup (app/services/cleanup.py) keeps a copy of every row it removes before removing it. Nothing writes to it until the app is deployed | additions only |
| `housing-0001_remove_unused_labels` | Godrej only: removes two permission labels that nothing uses (`get_resident_cases_status`, `view_my_cases`) so the AI is no longer told about them; `general_read` stays | changes role data |
| `housing-0002_one_step_blocks` | Godrej only: every building block does one step. Cuts the 8 blocks that had several steps into 25 one-step blocks, makes the 4 case flows that used them run the small blocks in the same order with the same inputs, and switches the old blocks off (title ends "(replaced)"; nothing is deleted, and each changed flow keeps its old version in its History). It only touches a block that still has exactly the steps it had when the file was written, and stops and changes nothing if one has several other steps. Safe to run twice | changes workflow data |

Read-only report (names and counts only, changes nothing): `python -m tools.orphans` lists drafts that point at removed workflows and permission labels that no workflow, workflow step or built-in rule uses.

To paste the SQL by hand instead of using the tool, `docs/run-sql-by-hand.md` lists every step. Before a real run, `python -m tools.backup` saves a checked backup of every database, and `python -m tools.restore --tenant <name>` puts one back as one all-or-nothing step. The whole procedure, with the exact commands, is in `docs/runbook-migrations.md`.

No partial indexes for the every-minute jobs on purpose: measured on a practice copy, the due-reports query runs in under 1 ms and the case-reminder query in under 0.1 ms (it already uses `idx_cases_org_status`), with 2 to 3 schedules and 29 cases. Revisit if `cases` passes about 50,000 rows.

There is no `core-0004`: it was a file with two uniqueness rules, dropped on purpose before anything was applied. Numbers are never reused.

`features/housing` holds two files and `features/jewellery` none yet. Each `feature.json` lists the client it applies to and the tables only that client has; it is where client-only changes go. Two Godrej-only platform tables, `access_grants` and `entity_records`, belong to neither group for now (the dashboard checks whether they exist).

Left different on purpose: two uniqueness rules (`users (org_id, email)` exists only in Godrej, `workflows (org_id, slash_command)` only in Baanganga), the default of every `id` column (`uuid_generate_v4()`, `gen_random_uuid()` or `uuid_generate_v7()`: all give valid UUIDs, and changing a default is not an addition), `orgs.default_making_charge_pct` and `orgs.gst_rate` (jewellery defaults), `users.channel` (telegram vs whatsapp). In new files use `gen_random_uuid()`: it works in both.
