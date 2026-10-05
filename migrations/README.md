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

There is no `core-0004`: it was a file with two uniqueness rules, dropped on purpose before anything was applied. Numbers are never reused.

`features/housing` and `features/jewellery` hold no SQL yet. Their `feature.json` lists the tables only that client has, and is where future client-only changes go. Two Godrej-only platform tables, `access_grants` and `entity_records`, belong to neither group for now (the dashboard checks whether they exist).

Left different on purpose: two uniqueness rules (`users (org_id, email)` exists only in Godrej, `workflows (org_id, slash_command)` only in Baanganga), the default of every `id` column (`uuid_generate_v4()`, `gen_random_uuid()` or `uuid_generate_v7()`: all give valid UUIDs, and changing a default is not an addition), `orgs.default_making_charge_pct` and `orgs.gst_rate` (jewellery defaults), `users.channel` (telegram vs whatsapp). In new files use `gen_random_uuid()`: it works in both.
