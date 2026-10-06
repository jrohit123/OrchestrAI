# Database changes: how to run them safely

This is the guide for the real run on Railway. Every command below was tried on a practice
copy of your databases first. **Claude never runs these on Railway. You do.** Claude can run
the read-only steps (1 and 3) if you ask.

Prefer to paste the SQL yourself, one step at a time, instead of using the migration tool?
`docs/run-sql-by-hand.md` has every step, tried on practice copies. Either way gives the same result.

## What the run does

It applies the numbered SQL files in `migrations/` to the routing database and the two client
databases (Godrej, Baanganga). Files only add things, with a few small changes of data (listed
below). Nothing is dropped or renamed. **The files need no deploy**: the running app does not know
about what they add, except the last one, which changes how Godrej's four case flows are built
(they do the same as before). The new app version (the job lock, the settings foundation and the nightly cleanup) is a
separate deploy that comes **after** this run, so the tables it needs are already there
(see "7. After the new app version is live").

| File | What it does |
|---|---|
| `core-0001_align` | adds the columns, three `kind` rules and the `admin_events` table that one client was missing |
| `core-0002_align_indexes` | adds the missing indexes without blocking the app |
| `core-0003_baseline_check` | changes nothing; stops with a list if 0001 or 0002 left anything out |
| `core-0005_fix_draft_index` | Baanganga: a new draft no longer inherits the answers of a closed one |
| `core-0006`, `core-0007` | two chat-log indexes for the dashboard |
| `core-0008_cancel_orphan_drafts` | cancels open drafts of removed workflows (none today) |
| `core-0009_settings_foundation` | the base for settings, message texts and AI instructions kept in the database: two columns on `orgs` (`timezone`, `locale`, set to what the code assumes today) and two empty tables (`prompts`, `system_messages`). With no rows the app uses its built-in text, so nothing changes |
| `core-0010_archived_rows` | one empty table, `archived_rows`, where the nightly cleanup keeps a copy of every row it removes |
| `housing-0001_remove_unused_labels` | Godrej only: removes two permission labels nothing uses |
| `housing-0002_one_step_blocks` | Godrej only: every building block does one step. The 8 blocks that had several steps are cut into 25 one-step blocks, the 4 case flows that used them (File a complaint, Add an update, Close with a note, Pass on) run the small blocks in the same order with the same inputs, and the old blocks are switched off and marked "(replaced)". Nothing is deleted, and each changed flow keeps its old version in its History. It stops and changes nothing if a block was edited after the file was written. On a practice copy, 17 rehearsals (137 trace lines) gave the same result before and after |

**What people may notice afterwards:** Baanganga's dashboard gets an Activity log (its
`admin_events` table now exists). Baanganga drafts start clean. The AI is no longer told about
two unused Godrej labels. On Godrej, Flows > Building blocks lists 25 new small blocks, and the 8 big
ones say "(replaced)" and are switched off; the case flows work the same. Nothing else. The new
tables stay empty until the app is deployed.

## Before you start

- Pick a quiet time. A change that cannot get its table lock gives up after 5 seconds instead of
  waiting, so it never blocks the app, but quiet is still better.
- You are in `D:\Orchestrator AI` on the branch with these files (`git checkout db-safe-changes`).
- Railway CLI, in PowerShell:

```powershell
cd "D:\Orchestrator AI"
$railway = "$env:APPDATA\npm\railway.cmd"
```

`railway run <command>` runs the command on your PC with the app's settings, so the tool can find
the databases. You never paste a database address anywhere.

## 1. Look first (changes nothing)

```powershell
& $railway run python -m tools.migrate --status --allow-remote
& $railway run python -m tools.orphans --allow-remote
```

You should see all three databases, each "NOT on this computer", with files "waiting". The second
command lists leftover drafts and unused permission labels (numbers may differ from the practice
copy). `--allow-remote` is needed because these are live databases; both commands only read.

If a database says `could not connect`, stop and tell Claude: the tool read its address from the
routing database and could not reach it from your PC.

## 2. Back up (never skip)

```powershell
& $railway run python -m tools.backup --allow-remote
```

It saves one file per database into `C:\Users\karti\orchestrai-backups`, checks that each file can
be read back, and prints its name and size. You should see three `saved:` lines and no `PROBLEM`.
**If any database is not backed up, do not go on.**

The files hold real data (names, phone numbers, chats). Keep the folder private and never inside
the project (the tool refuses that). What it runs for each database, with the address passed
through environment variables so it never appears on a command line:

```text
pg_dump --format=custom --no-owner --file <name>_<time>.dump
```

## 3. Plan (changes nothing)

```powershell
& $railway run python -m tools.migrate --allow-remote
```

With no flag the tool only shows what it would do. Every database should list its files as
`waiting` and none should say `PROBLEM`.

## 4. Apply, one database at a time

```powershell
& $railway run python -m tools.migrate --apply --tenant control --allow-remote --backup-taken
& $railway run python -m tools.migrate --apply --tenant baanganga --allow-remote --backup-taken
& $railway run python -m tools.migrate --apply --tenant godrej --allow-remote --backup-taken
```

`--backup-taken` is you promising that step 2 finished. Each database runs all its waiting files in
one go; if one file fails, that database is undone completely and the message names the file. The
other databases are never affected. If a database says `PROBLEM`, stop, send Claude the message,
and do not run the next command until Claude says so.

## 5. Check

```powershell
& $railway run python -m tools.migrate --status --allow-remote
& $railway run python -m tools.orphans --allow-remote
```

- Status: every file `done`, "0 with a problem".
- Orphans: the only unused label left in each database is `general_read` (kept on purpose).
- By hand: open the dashboard (Chats and Workflows screens), then send one normal message on the
  Godrej bot (Telegram) and one on Baanganga (WhatsApp).

## 6. Go back (only if something is wrong)

The safest way back is to put the backup in place, one database at a time. It returns that
database to **exactly** how it was when step 2 ran, so anything written after step 2 is lost. The
plan lists which tables would lose rows, so you can see what that means. Use it right after a bad
run, and restart the app on Railway afterwards.

It is one all-or-nothing step: if anything fails, the database stays as it was. Look first (this
changes nothing), then do it by typing the database's name again:

```powershell
& $railway run python -m tools.restore --tenant godrej --allow-remote
& $railway run python -m tools.restore --tenant godrej --allow-remote --yes-restore godrej
```

Use `baanganga` or `control` in the same way. It picks the newest backup of that database in
`C:\Users\karti\orchestrai-backups`; add `--file <path>` for another one. A file that belongs to
another database is refused by its name. Afterwards `--status` shows that database as `waiting`
again (the tracking table is part of what the restore undoes).

**Do not use a plain `pg_restore --clean`.** On a practice copy it failed half-way on Baanganga:
the new `admin_events` table points at `users` and `orgs`, so those could not be dropped, and the
database was left in a mixed state. The tool removes the tables the backup does not contain and
restores the rest in one transaction.

Smaller undo for the two chat-log indexes only (nothing else is touched):

```sql
DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_session;
DROP INDEX CONCURRENTLY IF EXISTS idx_audit_log_intent;
```

## 7. After the new app version is live: the nightly cleanup

Do this only after step 5 is fine **and** the new version of the app is deployed (you deploy it;
Claude never does). From then on, every night at 03:30 the app clears out three kinds of leftovers
that nothing ever removed, in every client database:

| What | Goes when | Built-in days | Setting (`orgs.settings.retention.`) |
|---|---|---|---|
| finished drafts (`user_drafts`, stage done or cancelled) | closed more than this long ago | 7 | `drafts_days` |
| expired one-time codes (`otp_tokens`) | expired more than this long ago | 1 | `otp_days` |
| abandoned workflow drafts (`workflow_drafts`, status abandoned) | not touched for this long | 30 | `workflow_drafts_days` |
| the copies themselves (`archived_rows`) | archived more than this long ago | 180 | `archive_days` |

A row is **copied to `archived_rows` and removed by one statement**, so it is never gone without
its copy. Only counts are logged (for example `cleanup 'godrej': removed user_drafts 66, otp_tokens
69`), never what was inside a row. A database without the `archived_rows` table (not migrated yet)
is left alone. Two copies of the app never run it at the same time. Set
`{"retention": {"enabled": false}}` in an organisation's settings to switch it off for that
organisation. A zero, a negative number or a typo is ignored and the built-in number is used.

**Preview what the first night will do** (changes nothing; run it before the deploy if you like):

```powershell
& $railway run python -m tools.cleanup
```

**Put a row back** (run in the database console of that client; replace `123` with the copy's id):

```sql
SELECT id, source_table, reason, archived_at FROM archived_rows ORDER BY id DESC LIMIT 20;
INSERT INTO user_drafts
SELECT (jsonb_populate_record(NULL::user_drafts, row_data)).* FROM archived_rows WHERE id = 123;
```

For an abandoned workflow draft use `NULL::workflow_drafts`. The one-time code itself is never
copied (it is useless after it expires), so those rows cannot be put back; the copy keeps who it
was for, what it was for and when.

**Change the number of days** for an organisation (here: keep finished drafts 14 days). Later this
will be on the Settings screen:

```sql
UPDATE orgs SET settings = coalesce(settings, '{}'::jsonb) || jsonb_build_object(
  'retention', coalesce(settings->'retention', '{}'::jsonb) || '{"drafts_days": 14}'::jsonb);
```

### The same screens, on the dashboard (after the deploy)

Both ways of changing these numbers are also on the dashboard, so the SQL above is only for you:

- **Settings** now has cards for chat sessions, photos and "keeping old records". Every box shows
  the built-in number next to it and a "Use built-in" button, and a number outside its allowed range
  is refused. Each save is written to the change log.
- **Assistant → Messages** lists the 73 sentences the assistant sends by itself (codes, approvals,
  cancelling, errors and so on), with a phone preview. Saving a wording makes a new version; "Use
  built-in wording" switches the saved versions off (nothing is deleted). The assistant uses a new
  wording at once on the copy of the app that saved it, and within a minute on any other.
- **Assistant → AI instructions** shows the written rules the AI follows, in three layers (shared
  rules, rules for the kind of business, notes for this organisation) put one after the other. Each
  layer starts as the text in the prompt files. A save is a new version; "Compare" shows what
  changed against an earlier version, "Use built-in text" goes back, and "What the assistant reads"
  shows the layers put together. These words steer the AI for everyone in the organisation, so
  change them with care.
- Until someone saves something, every number, every sentence and every instruction is exactly what
  it was before the deploy. The Assistant menu item only appears in a database that has migration
  `core-0009`.

**Try this right after the deploy** (five minutes; the chat code was changed in about 70 places, and
it was tested with stand-ins for Telegram, WhatsApp and the database, not with the real ones):

1. On the Godrej bot send `hi`, then `/status`, then `/cancel`. You should get the same words as
   yesterday.
2. Start a complaint, send a photo, finish it. The photo should attach.
3. Open the dashboard: Settings and Assistant should open without an error.
4. In Assistant → Messages change one harmless sentence (for example "Draft cancelled."), trigger
   it in the chat (start something, then `/cancel`), see your wording, then press "Use built-in
   wording".

If anything looks wrong, roll the deploy back on Railway (open the service, Deployments, pick the
previous one, Redeploy) or tell Claude. The database files are safe to leave in place: the old app
ignores what they add.

## What the messages mean

| You see | It means |
|---|---|
| `waiting` | the file has not been applied to this database yet |
| `done` / `ran now` | applied earlier / applied in this run |
| `CHANGED` | a file was edited after it was applied. Never edit an applied file; add a new number |
| `PROBLEM: ... everything in this transaction was undone` | that database is exactly as before this run; the file named failed |
| `PROBLEM: ... lock busy` | another run is using that database right now; wait and run again |
| `PROBLEM: ... lock timeout` | the app was holding a table; nothing was changed; run again a little later |
| `PROBLEM: an invalid index was left behind` | an index build failed half-way; send the message to Claude |
| `STOPPED - not on this computer` | you forgot `--allow-remote` (or `--backup-taken` with `--apply`) |
| `Plan only - nothing was changed` | you did not add `--apply` (or `--yes-restore <name>`), so nothing happened |
| `PROBLEM - the restore failed and was undone` | the restore was one transaction: the database is as it was before you ran it |
| `could not connect` | the database could not be reached from your PC |

Exit code 0 means fine, 1 means refused or set up wrong (nothing touched), 2 means a database failed.

## Practice on your PC first (Claude does this when you ask)

After step 2, ask Claude: "practise with the new backups". Claude restores the three backup files
into a private Postgres on your PC, points the restored routing database at those copies
(**this rewrite is the safety step: the backup of the routing database holds the real addresses**),
runs steps 3 to 5 there, and reports. Nothing leaves your PC. Claude deletes the copy afterwards.

For the record, this is what Claude runs once the private Postgres is up (it was tried exactly
like this). `$pg` is the PostgreSQL `bin` folder, `$h` the local connection options, `$sim` the
backup folder:

```powershell
$h = @("-h","127.0.0.1","-p","55432","-U","postgres")
& "$pg\createdb.exe" @h -T template0 -E UTF8 practice_baanganga      # same for godrej and routing
& "$pg\pg_restore.exe" @h --no-owner --dbname=practice_baanganga "$sim\baanganga_<time>.dump"
# the safety step: no address may point at a real database any more
& "$pg\psql.exe" @h -d practice_routing -c "UPDATE data_sources SET database_url = 'postgresql://postgres@127.0.0.1:55432/practice_' || source_key"
$env:ROUTING_DATABASE_URL = "postgresql://postgres@127.0.0.1:55432/practice_routing"
python -m tools.migrate --apply
```

The tools refuse any database that is not on this computer unless you pass `--allow-remote`, so a
forgotten rewrite is caught before anything runs. Use a different server name than the real ones.

## Adding a change later

Create `migrations/core/core-0011_short_name.sql` (the next number; client-only changes go in
`migrations/features/<name>/`). It must be safe to run twice, must not contain `BEGIN`/`COMMIT`,
and an index built with `CONCURRENTLY` needs `-- no-transaction` as its first line. Never edit a
file after it has been applied anywhere. Run `python -m pytest tests -q` and practise before a real
run. The rules are at the top of `tools/migrate.py` and in `migrations/README.md`.
