"""Back up the control database and every client database before a real run.

Run from the project folder:

    python -m tools.backup                     local databases
    python -m tools.backup --allow-remote      live databases (pg_dump only reads)
    python -m tools.backup --to D:\\somewhere   default folder: ~/orchestrai-backups

For each database it runs pg_dump (custom format) into <folder>/<name>_<time>.dump, checks
the file can be read back with pg_restore --list, and prints the file name and size. It
reads the database list the same safe way as tools/migrate.py and never prints a
connection string: the address is handed to pg_dump through environment variables, not on
the command line.

A backup holds real data (names, phone numbers, chats). The folder must be outside the
project (the tool refuses a folder inside it) and should stay private.

Exit codes: 0 every database saved and checked, 1 refused or set up wrong (nothing was
touched), 2 a database failed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import sys
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from tools.migrate import (
    MigrationError,
    Options,
    Target,
    describe,
    discover_targets,
    dsn_is_local,
    redact,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FOLDER = Path.home() / "orchestrai-backups"
SCOOP_BIN = Path.home() / "scoop" / "apps" / "postgresql" / "current" / "bin"
DUMP_TIMEOUT_SECONDS = 900


def find_pg_tool(name: str) -> Path | None:
    """pg_dump / pg_restore from PATH, from $PG_BIN, or from the usual scoop folder."""
    found = shutil.which(name)
    if found:
        return Path(found)
    for folder in (os.environ.get("PG_BIN"), SCOOP_BIN):
        if not folder:
            continue
        for candidate in (Path(folder) / f"{name}.exe", Path(folder) / name):
            if candidate.is_file():
                return candidate
    return None


def dsn_to_pg_env(dsn: str) -> dict[str, str]:
    """Connection settings as PG* environment variables, so that no address or password
    ever appears on a command line."""
    parts = urlsplit(dsn.strip())
    if (
        parts.scheme not in ("postgres", "postgresql")
        or not parts.hostname
        or "," in parts.netloc
    ):
        raise MigrationError(
            "this database address is not in the usual "
            "postgresql://user:password@host:port/name form"
        )
    env = {"PGHOST": parts.hostname}
    if parts.port:
        env["PGPORT"] = str(parts.port)
    if parts.username:
        env["PGUSER"] = unquote(parts.username)
    if parts.password:
        env["PGPASSWORD"] = unquote(parts.password)
    name = unquote(parts.path.lstrip("/"))
    if name:
        env["PGDATABASE"] = name
    sslmode = parse_qs(parts.query).get("sslmode")
    if sslmode:
        env["PGSSLMODE"] = sslmode[0]
    return env


def clean_env(pg_env: dict[str, str]) -> dict[str, str]:
    """This computer's environment without any other PG* settings, plus ours."""
    base = {k: v for k, v in os.environ.items() if not k.upper().startswith("PG")}
    return {**base, **pg_env}


def safe_message(text: str) -> str:
    """The last line of a tool's message without addresses, hosts or passwords."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    last = lines[-1] if lines else "no message"
    last = re.sub(r'"[^"]*"', "[HOST]", last)
    last = re.sub(r"\([0-9a-fA-F:.]+\)", "", last)
    return " ".join(redact(last).split())[:200]


def _size(path: Path) -> str:
    size = path.stat().st_size
    return (
        f"{size / 1024:.0f} KB"
        if size < 1024 * 1024
        else f"{size / 1024 / 1024:.1f} MB"
    )


def back_up_one(
    target: Target, folder: Path, stamp: str, pg_dump: Path, pg_restore: Path
) -> str:
    """Save and check one database. Returns the line to print; raises on failure."""
    path = folder / f"{target.label}_{stamp}.dump"
    env = clean_env(dsn_to_pg_env(target.dsn))
    try:
        dump = subprocess.run(
            [str(pg_dump), "--format=custom", "--no-owner", "--file", str(path)],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DUMP_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise MigrationError("pg_dump took too long and was stopped") from None
    if dump.returncode != 0:
        with suppress(OSError):
            path.unlink()
        raise MigrationError(f"pg_dump failed ({safe_message(dump.stderr)})")
    check = subprocess.run(
        [str(pg_restore), "--list", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    items = [ln for ln in check.stdout.splitlines() if ln and not ln.startswith(";")]
    if check.returncode != 0:
        raise MigrationError("the file was written but pg_restore cannot read it back")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return (
        f"{path.name}  ({_size(path)}, {len(items)} items, readable, sha256 {digest})"
    )


def choose_folder(raw: str | None) -> Path:
    folder = Path(raw).expanduser() if raw else DEFAULT_FOLDER
    resolved = folder.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise MigrationError(
            "the backup folder is inside the project, where a backup (real data) could "
            "end up in git. Choose a folder outside it, for example ~/orchestrai-backups."
        )
    return resolved


async def run(opts: Options, raw_folder: str | None) -> int:
    folder = choose_folder(raw_folder)
    pg_dump, pg_restore = find_pg_tool("pg_dump"), find_pg_tool("pg_restore")
    if not pg_dump or not pg_restore:
        raise MigrationError(
            "pg_dump and pg_restore were not found. Put the PostgreSQL 'bin' folder on "
            "PATH or set PG_BIN to it (for example "
            "C:\\Users\\karti\\scoop\\apps\\postgresql\\current\\bin)."
        )
    targets = await discover_targets(opts)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    failed = 0
    saved: list[str] = []
    for target in targets:
        where = (
            "on this computer" if dsn_is_local(target.dsn) else "NOT on this computer"
        )
        kind = "control database" if target.kind == "control" else "client database"
        print(f"== {target.label}  ({kind}, {where})")
        try:
            line = back_up_one(target, folder, stamp, pg_dump, pg_restore)
            saved.append(line)
            print(f"   saved: {line}")
        except MigrationError as exc:
            failed += 1
            print(f"   PROBLEM: {redact(str(exc))}")
        except Exception as exc:
            failed += 1
            print(f"   PROBLEM: {describe(exc)}")
        sys.stdout.flush()
    if saved:
        manifest = folder / f"backup_{stamp}.txt"
        manifest.write_text("\n".join(saved) + "\n", encoding="utf-8")
    print()
    print(f"Backups are in {folder}")
    print("They hold real data: keep that folder private, outside the project.")
    if failed:
        print(f"{failed} database(s) were NOT backed up. Do not apply anything yet.")
    return 2 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.backup",
        description=(
            "Save a checked backup file of the control database and every client "
            "database. Reads only; changes nothing."
        ),
    )
    parser.add_argument(
        "--to",
        metavar="FOLDER",
        help="where to save the files (default: ~/orchestrai-backups; never inside the project)",
    )
    parser.add_argument(
        "--tenant",
        action="append",
        default=[],
        metavar="NAME",
        help="only this database (repeat or use commas); 'control' is the routing one",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="allow databases that are not on this computer (pg_dump only reads)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    opts = Options(
        tenants=[
            name.strip()
            for item in args.tenant
            for name in item.split(",")
            if name.strip()
        ],
        allow_remote=args.allow_remote,
    )
    with suppress(Exception):
        sys.stdout.reconfigure(errors="replace")
    try:
        return asyncio.run(run(opts, args.to))
    except MigrationError as exc:
        print(f"STOPPED - {redact(str(exc))}")
        return 1
    except Exception as exc:
        print(f"UNEXPECTED PROBLEM - {describe(exc)}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
