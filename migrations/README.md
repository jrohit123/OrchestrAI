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
