"""Put a backup back, as one all-or-nothing step.

Run from the project folder:

    python -m tools.restore --tenant godrej --allow-remote                        shows what would happen, changes nothing
    python -m tools.restore --tenant godrej --allow-remote --yes-restore godrej   really puts the newest backup back
    python -m tools.restore --tenant godrej --file C:\\path\\godrej_2026-10-06_1200.dump ...

Why not plain pg_restore --clean? A change can add tables that point at old ones (for
example Baanganga's admin_events points at users and orgs). pg_restore then cannot drop the
old tables, stops half-way and leaves a mixed state. This tool first lists the tables the
backup does not contain, then removes them and restores everything else inside ONE
transaction: if anything fails, the database stays exactly as it was.

It restores the database to the moment of the backup: rows written after it are lost, and
the plan lists tables whose row counts differ so you can see what that means. It reads the
address from the routing database like the other tools, hands it to psql and pg_restore
through environment variables, never prints it, and by default changes nothing.

Exit codes: 0 fine, 1 refused or set up wrong (nothing was touched), 2 the restore failed
(the database was left as it was).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess
import sys
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from tools.backup import (
    DEFAULT_FOLDER,
    clean_env,
    dsn_to_pg_env,
    find_pg_tool,
    safe_message,
)
from tools.migrate import (
    MigrationError,
    Options,
    Target,
    describe,
    discover_targets,
    dsn_is_local,
    open_connection,
    redact,
)

TABLE_ENTRY = re.compile(r"^\d+; \d+ \d+ TABLE public (\S+) ")
COPY_START = re.compile(r'^COPY public\.("?\w+"?) \(.*\) FROM stdin;\s*$')
LIVE_TABLES_SQL = """
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') ORDER BY 1
"""
LOCK_WAIT_MS = 30000
RESTORE_TIMEOUT_SECONDS = 1800


class RestoreFailed(MigrationError):
    """The restore was tried and failed; being one transaction, the database is as it was."""


# ----------------------------------------------------------------------- pure logic


def archive_tables(toc_text: str) -> set[str]:
    """The tables listed by `pg_restore --list`."""
    found = set()
    for line in toc_text.splitlines():
        match = TABLE_ENTRY.match(line)
        if match:
            found.add(match.group(1).strip('"'))
    return found


def count_copy_rows(sql_text: str) -> dict[str, int]:
    """Rows per table in a restore script's COPY blocks."""
    counts: dict[str, int] = {}
    current = None
    for line in sql_text.splitlines():
        if current is None:
            match = COPY_START.match(line)
            if match:
                current = match.group(1).strip('"')
                counts[current] = 0
        elif line == "\\.":
            current = None
        else:
            counts[current] += 1
    return counts


def find_backup(folder: Path, label: str, explicit: str | None = None) -> Path:
    """The backup file to use: the one named, or the newest <label>_*.dump in the folder.
    A file whose name does not start with the database's name is refused: it is
    probably another database's backup."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise MigrationError(f"the backup file was not found: {path.name}")
        if not path.name.startswith(f"{label}_"):
            raise MigrationError(
                f"{path.name} does not look like a backup of '{label}' (its name should "
                f"start with '{label}_'). Restoring another database's backup would mix "
                "up your data, so this is refused."
            )
        return path
    candidates = sorted(folder.glob(f"{label}_*.dump"))
    if not candidates:
        raise MigrationError(
            f"no backup of '{label}' was found in {folder}. Run python -m tools.backup first."
        )
    return candidates[-1]


def differences(backup: dict[str, int], live: dict[str, int]) -> list[str]:
    """Plain-words lines about tables whose row counts differ."""
    lines = []
    for table in sorted(set(backup) | set(live)):
        if table in backup and table in live and backup[table] != live[table]:
            lost = max(live[table] - backup[table], 0)
            note = f"{lost} newer row(s) will be lost" if lost else "rows come back"
            lines.append(
                f"{table}: backup has {backup[table]} rows, now {live[table]} ({note})"
            )
    return lines


# -------------------------------------------------------------------------- the work


def _run(tool: Path, args: list[str], env: dict[str, str], timeout: int):
    return subprocess.run(
        [str(tool), *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


async def live_counts(target: Target, opts: Options) -> dict[str, int]:
    conn = await open_connection(target.dsn, opts)
    try:
        counts = {}
        for row in await conn.fetch(LIVE_TABLES_SQL):
            name = row["relname"]
            quoted = '"' + name.replace('"', '""') + '"'
            counts[name] = await conn.fetchval(f"SELECT count(*) FROM public.{quoted}")
        return counts
    finally:
        await conn.close()


def read_backup(pg_restore: Path, dump: Path) -> tuple[set[str], dict[str, int]]:
    env = clean_env({})
    toc = _run(pg_restore, ["--list", str(dump)], env, 120)
    if toc.returncode != 0:
        raise MigrationError("pg_restore cannot read this backup file")
    data = _run(
        pg_restore, ["--data-only", "--no-owner", "--file", "-", str(dump)], env, 600
    )
    if data.returncode != 0:
        raise MigrationError("pg_restore cannot read the data in this backup file")
    return archive_tables(toc.stdout), count_copy_rows(data.stdout)


def restore_in_one_step(
    target: Target, dump: Path, remove: list[str], pg_restore: Path, psql: Path
) -> None:
    """Remove the tables the backup does not hold and restore the rest: one transaction."""
    env = clean_env(dsn_to_pg_env(target.dsn))
    env["PGOPTIONS"] = f"-c lock_timeout={LOCK_WAIT_MS} -c statement_timeout=600000"
    env["PGCLIENTENCODING"] = "UTF8"
    fd, name = tempfile.mkstemp(prefix="restore_", suffix=".sql")
    os.close(fd)
    script = Path(name)
    try:
        made = _run(
            pg_restore,
            ["--clean", "--if-exists", "--no-owner", "--file", str(script), str(dump)],
            clean_env({}),
            600,
        )
        if made.returncode != 0:
            raise RestoreFailed("pg_restore could not prepare the restore script")
        args = ["-X", "-q", "-v", "ON_ERROR_STOP=1", "--single-transaction"]
        for table in remove:
            quoted = '"' + table.replace('"', '""') + '"'
            args += ["-c", f"DROP TABLE IF EXISTS public.{quoted} CASCADE"]
        args += ["-f", str(script)]
        done = _run(psql, args, env, RESTORE_TIMEOUT_SECONDS)
        if done.returncode != 0:
            raise RestoreFailed(
                f"the restore failed and was undone, so the database is as it was "
                f"({safe_message(done.stderr)})"
            )
    except subprocess.TimeoutExpired:
        raise RestoreFailed("the restore took too long and was stopped") from None
    finally:
        with suppress(OSError):
            script.unlink()  # the script holds real data


def _when(path: Path) -> str:
    when = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return when.astimezone().strftime("%Y-%m-%d %H:%M")


def _size(path: Path) -> str:
    size = path.stat().st_size
    return (
        f"{size / 1024:.0f} KB"
        if size < 1024 * 1024
        else f"{size / 1024 / 1024:.1f} MB"
    )


async def run(
    opts: Options, folder: str | None, explicit: str | None, confirm: str | None
) -> int:
    if len(opts.tenants) != 1:
        raise MigrationError(
            "name exactly one database with --tenant (control, or a client such as godrej)"
        )
    label = opts.tenants[0]
    pg_restore, psql = find_pg_tool("pg_restore"), find_pg_tool("psql")
    if not pg_restore or not psql:
        raise MigrationError(
            "pg_restore and psql were not found. Put the PostgreSQL 'bin' folder on PATH "
            "or set PG_BIN to it."
        )
    dump = find_backup(
        Path(folder).expanduser() if folder else DEFAULT_FOLDER, label, explicit
    )
    [target] = await discover_targets(opts)

    in_backup, backup_counts = read_backup(pg_restore, dump)
    now_counts = await live_counts(target, opts)
    remove = sorted(set(now_counts) - in_backup)

    where = "on this computer" if dsn_is_local(target.dsn) else "NOT on this computer"
    kind = "control database" if target.kind == "control" else "client database"
    print(f"== {label}  ({kind}, {where})")
    print(f"   backup file: {dump.name}  ({_size(dump)}, saved {_when(dump)})")
    print(
        f"   tables in the backup: {len(in_backup)}; in the database now: {len(now_counts)}"
    )
    print(
        f"   tables that will be REMOVED (the backup does not have them): {', '.join(remove) or 'none'}"
    )
    lines = differences(backup_counts, now_counts)
    print("   tables with a different number of rows now: " + ("" if lines else "none"))
    for line in lines:
        print(f"      {line}")
    print()
    if confirm != label:
        print(
            "Plan only - nothing was changed. This puts the database back to the moment of "
            "the backup: every table exactly as it was then, including changes that do not "
            "change a row count. To do it, add:  --yes-restore " + label
        )
        return 0

    restore_in_one_step(target, dump, remove, pg_restore, psql)
    after = await live_counts(target, opts)
    wrong = [
        t
        for t in sorted(set(backup_counts) | set(after))
        if backup_counts.get(t) != after.get(t)
    ]
    if wrong or set(after) != in_backup:
        print(
            f"PROBLEM: restored, but these tables do not match the backup: {', '.join(wrong) or 'table list'}"
        )
        return 2
    rows = sum(after.values())
    print(
        f"Restored and checked: {len(after)} tables, {rows} rows, all matching the backup."
    )
    print("Restart the app on Railway so it starts from a clean connection.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.restore",
        description=(
            "Put a backup back as one all-or-nothing step. With no --yes-restore it only "
            "shows what would happen."
        ),
    )
    parser.add_argument(
        "--tenant",
        action="append",
        default=[],
        metavar="NAME",
        help="the one database to restore ('control' is the routing one)",
    )
    parser.add_argument(
        "--from",
        dest="folder",
        metavar="FOLDER",
        help="folder holding the backups (default: ~/orchestrai-backups)",
    )
    parser.add_argument(
        "--file",
        metavar="FILE",
        help="a specific backup file (default: the newest one for that database)",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="allow a database that is not on this computer",
    )
    parser.add_argument(
        "--yes-restore",
        metavar="NAME",
        help="type the database's name again to really restore it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    opts = Options(
        tenants=[
            n.strip() for item in args.tenant for n in item.split(",") if n.strip()
        ],
        allow_remote=args.allow_remote,
    )
    with suppress(Exception):
        sys.stdout.reconfigure(errors="replace")
    try:
        return asyncio.run(run(opts, args.folder, args.file, args.yes_restore))
    except RestoreFailed as exc:
        print(f"PROBLEM - {redact(str(exc))}")
        return 2
    except MigrationError as exc:
        print(f"STOPPED - {redact(str(exc))}")
        return 1
    except Exception as exc:
        print(f"UNEXPECTED PROBLEM - {describe(exc)}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
