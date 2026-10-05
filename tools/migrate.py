"""Safe, numbered SQL changes for every OrchestrAI database.

Run from the project folder:

    python -m tools.migrate --status            what each database has and what is waiting
    python -m tools.migrate                     show the plan, change nothing
    python -m tools.migrate --apply             really apply the waiting files
    python -m tools.migrate --apply --tenant godrej

The tool reads the list of client databases from the control (routing) database,
using the ROUTING_DATABASE_URL environment variable. It never reads .env and never
prints a connection string.

Rules the tool enforces by itself:
  * No flag means plan only. The session is opened read-only, so a plan cannot write.
  * A database that is not on this computer is refused unless --allow-remote is given,
    and --apply on such a database also needs --backup-taken.
  * One run at a time per database (Postgres advisory lock).
  * All waiting files of one database run in ONE transaction. If one fails, that
    database is rolled back and the other databases carry on. A file whose first comment
    line says "-- no-transaction" (needed for CREATE INDEX CONCURRENTLY) runs on its own,
    still in order.
  * A file that was applied must never change (checksum). Add a new numbered file.
  * DROP TABLE / DROP COLUMN / RENAME / TRUNCATE are refused unless the file's first
    comment lines include "-- allow-destructive". This looks inside DO blocks too. It is
    a guard against mistakes, not a security boundary: SQL built inside a string
    (EXECUTE '...') is not inspected.

Where the files live (older loose files in migrations/ are not read):
  migrations/core/                 every client database       core-0001_short_name.sql
  migrations/control/              the routing database        control-0001_short_name.sql
  migrations/features/<name>/      only the clients listed in that folder's feature.json,
                                   for example {"tenants": ["godrej"]}
                                                               <name>-0001_short_name.sql

Exit codes: 0 fine, 1 refused or set up wrong (nothing was touched), 2 a database failed.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
ROUTING_ENV = "ROUTING_DATABASE_URL"

# One fixed number meaning "a migration run is using this database". It comes from a
# name so nobody has to remember it; other jobs must use a different name.
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"orchestrai:schema_migrations").digest()[:8], "big", signed=True
)

FILE_RE = re.compile(
    r"^(?P<prefix>[a-z][a-z0-9_]*)-(?P<num>\d{4})_(?P<name>[a-z0-9_]+)\.sql$"
)
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_PREFIXES = {"core", "control"}
TRANSACTION_WORDS = {"BEGIN", "START", "COMMIT", "END", "ROLLBACK", "ABORT"}
DESTRUCTIVE = [
    (
        "DROP TABLE / COLUMN / SCHEMA / DATABASE / EXTENSION",
        re.compile(r"\bDROP (TABLE|COLUMN|SCHEMA|DATABASE|EXTENSION)\b"),
    ),
    (
        "ALTER TABLE ... DROP <column>",
        re.compile(
            r"\bALTER TABLE\b[^;]*\bDROP "
            r"(?!CONSTRAINT\b|DEFAULT\b|NOT NULL\b|IDENTITY\b|EXPRESSION\b)"
        ),
    ),
    ("RENAME", re.compile(r"\bRENAME\b")),
    ("TRUNCATE", re.compile(r"\bTRUNCATE\b")),
]

TABLE_EXISTS_SQL = "SELECT to_regclass('public.schema_migrations') IS NOT NULL"
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version    text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now(),
    checksum   text NOT NULL,
    applied_by text NOT NULL
)
"""
APPLIED_SQL = "SELECT version, checksum, applied_at FROM public.schema_migrations"
INSERT_SQL = (
    "INSERT INTO public.schema_migrations (version, checksum, applied_by) "
    "VALUES ($1, $2, $3)"
)
INVALID_INDEXES_SQL = """
SELECT n.nspname || '.' || c.relname AS name
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE NOT i.indisvalid AND n.nspname = 'public'
ORDER BY 1
"""


class MigrationError(Exception):
    """A problem with the files, the settings or the request. Nothing was touched."""


class ApplyFailed(Exception):
    """A database refused one of the files."""


# --------------------------------------------------------------------------- safety


def dsn_hosts(dsn: str) -> list[str]:
    """The machines a connection string would connect to (empty if it names none)."""
    dsn = dsn.strip()
    hosts: list[str] = []
    if "://" in dsn:
        parts = urlsplit(dsn)
        for item in parts.netloc.rsplit("@", 1)[-1].split(","):
            item = item.strip()
            if not item:
                continue
            if item.startswith("["):
                host = item[1 : item.find("]")] if "]" in item else item[1:]
            else:
                host = item.rsplit(":", 1)[0] if ":" in item else item
            hosts.append(unquote(host))
        query = parse_qs(parts.query)
        for key in ("host", "hostaddr"):
            for value in query.get(key, []):
                hosts.extend(x.strip() for x in value.split(",") if x.strip())
    else:
        pattern = r"(?:^|\s)(?:host|hostaddr)\s*=\s*('(?:[^'\\]|\\.)*'|\S+)"
        for match in re.finditer(pattern, dsn):
            value = match.group(1).strip("'")
            hosts.extend(x.strip() for x in value.split(",") if x.strip())
    return hosts


def is_local_host(host: str) -> bool:
    host = host.strip().strip("[]").lower()
    if not host:
        return False
    if host.startswith("/"):  # a folder holding a unix socket
        return True
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def dsn_is_local(dsn: str) -> bool:
    """True only when the string names at least one machine and all are this computer."""
    hosts = dsn_hosts(dsn)
    return bool(hosts) and all(is_local_host(h) for h in hosts)


_SECRET_PATTERNS = [
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+"),
    re.compile(r"(?i)\bpassword\s*=\s*\S+"),
]


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def describe(exc: BaseException) -> str:
    """A short, safe description of an error (no addresses, no passwords, no row data)."""
    if isinstance(exc, OSError | TimeoutError):
        return f"could not connect ({type(exc).__name__})"
    text = " ".join(redact(str(exc)).split())
    return f"{type(exc).__name__}: {text[:300]}"


def who_am_i() -> str:
    override = os.environ.get("MIGRATE_APPLIED_BY", "").strip()
    if override:
        return override[:120]
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    return f"{user}@{socket.gethostname()}"[:120]


# ------------------------------------------------------------------- reading the files


def _ident_char(c: str) -> bool:
    return bool(c) and (c.isalnum() or c in "_$")


_DOLLAR = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def _inner_code(body: str) -> str:
    """The words inside a $$ body (a DO block, a function) with comments and quoted
    text blanked, so a DROP hidden in a DO block is still seen by the safety check.
    A $$ text that is not SQL at all is simply ignored."""
    try:
        return "; ".join(code for _, code in split_statements(body))
    except MigrationError:
        return " "


def split_statements(sql: str) -> list[tuple[str, str]]:
    """Split SQL text into statements.

    Returns (statement, code_only) pairs. code_only is the same statement with comments
    and the inside of quoted text blanked out, so keyword checks cannot be fooled by
    words that sit in a comment or in a string."""
    out: list[tuple[str, str]] = []
    raw: list[str] = []
    code: list[str] = []
    n = len(sql)
    i = 0

    def take(end: int, shown: str | None = None) -> None:
        nonlocal i
        chunk = sql[i:end]
        raw.append(chunk)
        code.append(shown if shown is not None else " " * len(chunk))
        i = end

    def flush() -> None:
        if "".join(code).strip():
            out.append(("".join(raw).strip(), "".join(code)))
        raw.clear()
        code.clear()

    while i < n:
        ch = sql[i]
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            take(n if end == -1 else end)
        elif sql.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif sql.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            if depth:
                raise MigrationError("a /* comment is never closed")
            take(j)
        elif ch == "'":
            prev = sql[i - 1] if i else ""
            before = sql[i - 2] if i > 1 else ""
            backslash_escapes = prev in ("e", "E") and not _ident_char(before)
            j = i + 1
            while True:
                if j >= n:
                    raise MigrationError("a quoted text is never closed")
                if backslash_escapes and sql[j] == "\\":
                    j += 2
                elif sql[j] == "'":
                    if sql[j + 1 : j + 2] == "'":
                        j += 2
                    else:
                        j += 1
                        break
                else:
                    j += 1
            take(j, "'" + " " * (j - i - 2) + "'")
        elif ch == '"':
            j = i + 1
            while True:
                if j >= n:
                    raise MigrationError("a quoted name is never closed")
                if sql[j] == '"':
                    if sql[j + 1 : j + 2] == '"':
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            take(j, '"' + " " * (j - i - 2) + '"')
        elif ch == "$" and not _ident_char(sql[i - 1] if i else ""):
            match = _DOLLAR.match(sql, i)
            if match is None:
                take(i + 1, ch)
            else:
                tag = match.group(0)
                end = sql.find(tag, match.end())
                if end == -1:
                    raise MigrationError("a $$ quoted text is never closed")
                j = end + len(tag)
                take(j, f"{tag} {_inner_code(sql[match.end() : end])} {tag}")
        elif ch == ";":
            flush()
            i += 1
        elif ch == "\\":
            raise MigrationError(
                "a backslash outside quotes - psql commands such as \\i are not supported"
            )
        else:
            take(i + 1, ch)
    flush()
    return out


def header_flags(sql: str) -> set[str]:
    """Markers written as comment lines at the very top of a file."""
    flags: set[str] = set()
    for line in sql.splitlines():
        text = line.strip()
        if not text:
            continue
        if not text.startswith("--"):
            break
        word = text[2:].strip().lower()
        if word in ("no-transaction", "allow-destructive"):
            flags.add(word)
    return flags


def read_sql(path: Path) -> tuple[str, str]:
    """The file text and its checksum. Line endings do not change the checksum."""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    raw = raw.replace(b"\r\n", b"\n")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise MigrationError(f"{path.name}: the file is not UTF-8 text") from None
    return text, hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Migration:
    version: str
    group: str
    name: str
    path: Path
    checksum: str
    sql: str
    statements: tuple[str, ...]
    no_transaction: bool = False
    allow_destructive: bool = False


def check_file(
    name: str,
    statements: list[tuple[str, str]],
    *,
    no_transaction: bool,
    allow_destructive: bool,
) -> None:
    for _, code in statements:
        text = " ".join(code.upper().split())
        first = text.split(" ", 1)[0]
        if first in TRANSACTION_WORDS:
            raise MigrationError(
                f"{name}: do not use {first} - the tool opens and closes the transaction"
            )
        if "CONCURRENTLY" in text and not no_transaction:
            raise MigrationError(
                f"{name}: CONCURRENTLY cannot run inside a transaction - put "
                "'-- no-transaction' as the first comment line of the file"
            )
        if allow_destructive:
            continue
        for label, pattern in DESTRUCTIVE:
            if pattern.search(text):
                raise MigrationError(
                    f"{name}: contains {label}, which this tool refuses. If you really "
                    "mean it, put '-- allow-destructive' as a comment line at the top"
                )


def load_group(folder: Path, prefix: str) -> list[Migration]:
    if not folder.is_dir():
        return []
    found: dict[str, Migration] = {}
    for path in sorted(folder.glob("*.sql")):
        match = FILE_RE.match(path.name)
        if not match or match["prefix"] != prefix:
            raise MigrationError(
                f"{folder.name}/{path.name}: the name must look like "
                f"{prefix}-0001_short_name.sql"
            )
        version = f"{prefix}-{match['num']}"
        if version in found:
            raise MigrationError(f"{path.name}: the number {version} is used twice")
        sql, checksum = read_sql(path)
        flags = header_flags(sql)
        try:
            statements = split_statements(sql)
        except MigrationError as exc:
            raise MigrationError(f"{path.name}: {exc}") from None
        no_transaction = "no-transaction" in flags
        allow_destructive = "allow-destructive" in flags
        check_file(
            path.name,
            statements,
            no_transaction=no_transaction,
            allow_destructive=allow_destructive,
        )
        found[version] = Migration(
            version=version,
            group=prefix,
            name=match["name"],
            path=path,
            checksum=checksum,
            sql=sql,
            statements=tuple(s for s, _ in statements),
            no_transaction=no_transaction,
            allow_destructive=allow_destructive,
        )
    return [found[v] for v in sorted(found)]


def read_feature_tenants(folder: Path) -> list[str]:
    path = folder / "feature.json"
    hint = 'like {"tenants": ["godrej"]}'
    if not path.is_file():
        raise MigrationError(
            f"features/{folder.name}/feature.json is missing - list the client "
            f"databases this feature is for, {hint}"
        )
    try:
        tenants = json.loads(path.read_text(encoding="utf-8"))["tenants"]
    except (ValueError, KeyError, TypeError):
        raise MigrationError(
            f"features/{folder.name}/feature.json must look {hint}"
        ) from None
    if not isinstance(tenants, list) or not all(isinstance(t, str) for t in tenants):
        raise MigrationError(f"features/{folder.name}/feature.json must look {hint}")
    return tenants


@dataclass
class Catalog:
    core: list[Migration] = field(default_factory=list)
    control: list[Migration] = field(default_factory=list)
    features: dict[str, tuple[list[str], list[Migration]]] = field(default_factory=dict)

    def for_control(self) -> list[Migration]:
        return list(self.control)

    def for_tenant(self, source_key: str) -> list[Migration]:
        out = list(self.core)
        for name in sorted(self.features):
            tenants, migrations = self.features[name]
            if source_key in tenants:
                out.extend(migrations)
        return out

    def all_versions(self) -> set[str]:
        versions = {m.version for m in self.core + self.control}
        for _, migrations in self.features.values():
            versions.update(m.version for m in migrations)
        return versions


def load_catalog(root: Path) -> Catalog:
    if not root.is_dir():
        raise MigrationError(f"the migrations folder was not found: {root}")
    catalog = Catalog(
        core=load_group(root / "core", "core"),
        control=load_group(root / "control", "control"),
    )
    features_dir = root / "features"
    if features_dir.is_dir():
        for folder in sorted(p for p in features_dir.iterdir() if p.is_dir()):
            if not NAME_RE.match(folder.name) or folder.name in RESERVED_PREFIXES:
                raise MigrationError(
                    f"features/{folder.name}: use a lower-case name that is not "
                    "'core' or 'control'"
                )
            catalog.features[folder.name] = (
                read_feature_tenants(folder),
                load_group(folder, folder.name),
            )
    return catalog


# --------------------------------------------------------------------- talking to a DB


@dataclass
class Options:
    apply: bool = False
    status: bool = False
    tenants: list[str] = field(default_factory=list)
    root: Path = MIGRATIONS_DIR
    allow_remote: bool = False
    backup_taken: bool = False
    lock_timeout: float = 5.0
    statement_timeout: float = 300.0


@dataclass(frozen=True)
class Target:
    label: str
    kind: str  # "control" or "tenant"
    dsn: str = field(repr=False)


@dataclass
class Report:
    label: str
    kind: str
    local: bool
    plan: list[Migration] = field(default_factory=list)
    table: bool = False
    table_created: bool = False
    applied: dict[str, tuple[str, datetime]] = field(default_factory=dict)
    pending: list[Migration] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    invalid_indexes: list[str] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)
    error: str | None = None


async def open_connection(dsn: str, opts: Options) -> asyncpg.Connection:
    conn = await asyncpg.connect(dsn, timeout=15, statement_cache_size=0)
    try:
        await conn.execute("SET application_name = 'orchestrai-migrate'")
        await conn.execute("SET search_path = public")
        # Read-only until --apply says otherwise: the database itself refuses writes.
        await conn.execute("SET default_transaction_read_only = on")
        await conn.execute(f"SET lock_timeout = {int(opts.lock_timeout * 1000)}")
        await conn.execute(
            f"SET statement_timeout = {int(opts.statement_timeout * 1000)}"
        )
    except BaseException:
        await conn.close()
        raise
    return conn


async def inspect(
    conn: asyncpg.Connection,
    plan: list[Migration],
    all_versions: set[str],
    report: Report,
) -> None:
    report.plan = plan
    report.table = bool(await conn.fetchval(TABLE_EXISTS_SQL))
    report.applied = {}
    if report.table:
        for row in await conn.fetch(APPLIED_SQL):
            report.applied[row["version"]] = (row["checksum"], row["applied_at"])
    report.pending = [m for m in plan if m.version not in report.applied]
    report.changed = [
        m.version
        for m in plan
        if m.version in report.applied and report.applied[m.version][0] != m.checksum
    ]
    report.unknown = sorted(v for v in report.applied if v not in all_versions)
    report.invalid_indexes = [r["name"] for r in await conn.fetch(INVALID_INDEXES_SQL)]


async def run_together(
    conn: asyncpg.Connection, group: list[Migration], applied_by: str
) -> None:
    """Run several files as one transaction; any failure undoes all of them."""
    current = group[0].version
    try:
        async with conn.transaction():
            for migration in group:
                current = migration.version
                await conn.execute(migration.sql)
                await conn.execute(
                    INSERT_SQL, migration.version, migration.checksum, applied_by
                )
    except Exception as exc:
        raise ApplyFailed(
            f"{current}: {describe(exc)} - everything in this transaction was undone"
        ) from None


async def run_alone(
    conn: asyncpg.Connection, migration: Migration, applied_by: str
) -> None:
    """Run a '-- no-transaction' file one statement at a time, outside a transaction."""
    try:
        for statement in migration.statements:
            await conn.execute(statement)
        bad = await conn.fetch(INVALID_INDEXES_SQL)
        if bad:
            names = ", ".join(r["name"] for r in bad)
            raise ApplyFailed(
                f"{migration.version}: an invalid index was left behind ({names}). "
                "Drop it (DROP INDEX CONCURRENTLY) and run again"
            )
        await conn.execute(
            INSERT_SQL, migration.version, migration.checksum, applied_by
        )
    except ApplyFailed:
        raise
    except Exception as exc:
        raise ApplyFailed(
            f"{migration.version}: {describe(exc)} - this file runs outside a "
            "transaction, so statements before the failure may have taken effect; "
            "fix the file (it must be safe to run twice) and run again"
        ) from None


async def apply_to(
    conn: asyncpg.Connection,
    plan: list[Migration],
    all_versions: set[str],
    report: Report,
) -> None:
    got = await conn.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY)
    if not got:
        report.error = (
            "another run is using this database right now (lock busy) - "
            "nothing was changed here"
        )
        return
    try:
        await conn.execute("SET default_transaction_read_only = off")
        existed = bool(await conn.fetchval(TABLE_EXISTS_SQL))
        await conn.execute(CREATE_TABLE_SQL)
        report.table_created = not existed
        # Look again now that we hold the lock: another run may have just finished.
        await inspect(conn, plan, all_versions, report)
        if report.changed:
            report.error = (
                "refusing to apply here: these files changed after they were "
                f"applied: {', '.join(report.changed)}"
            )
            return
        applied_by = who_am_i()
        todo = list(report.pending)
        i = 0
        while i < len(todo):
            if todo[i].no_transaction:
                batch = [todo[i]]
                await run_alone(conn, todo[i], applied_by)
            else:
                j = i
                while j < len(todo) and not todo[j].no_transaction:
                    j += 1
                batch = todo[i:j]
                await run_together(conn, batch, applied_by)
            report.ran.extend(m.version for m in batch)
            i += len(batch)
    except ApplyFailed as exc:
        report.error = str(exc)
    finally:
        with suppress(Exception):
            await conn.fetchval("SELECT pg_advisory_unlock($1)", LOCK_KEY)
        with suppress(Exception):
            await inspect(conn, plan, all_versions, report)


async def process_target(
    target: Target, plan: list[Migration], all_versions: set[str], opts: Options
) -> Report:
    report = Report(
        label=target.label,
        kind=target.kind,
        local=dsn_is_local(target.dsn),
        plan=plan,
    )
    conn = None
    try:
        conn = await open_connection(target.dsn, opts)
        if opts.apply:
            await apply_to(conn, plan, all_versions, report)
        else:
            await inspect(conn, plan, all_versions, report)
    except Exception as exc:
        report.error = describe(exc)
    finally:
        if conn is not None:
            with suppress(Exception):
                await conn.close()
    return report


# -------------------------------------------------------------------------- the report


def print_report(report: Report) -> None:
    kind = "control database" if report.kind == "control" else "client database"
    where = "on this computer" if report.local else "NOT on this computer"
    print(f"== {report.label}  ({kind}, {where})")
    if report.table_created:
        print("   tracking table (schema_migrations): created now")
    elif report.table:
        print("   tracking table (schema_migrations): present")
    else:
        print("   tracking table (schema_migrations): not created yet")
    if not report.plan:
        print("   no files apply to this database")
    for migration in report.plan:
        if migration.version in report.ran:
            state = "ran now"
        elif migration.version in report.changed:
            state = "CHANGED"
        elif migration.version in report.applied:
            state = "done"
        else:
            state = "waiting"
        notes = []
        if migration.no_transaction:
            notes.append("no-transaction")
        if migration.allow_destructive:
            notes.append("ALLOW-DESTRUCTIVE")
        if state == "CHANGED":
            notes.append("edited after it was applied")
        suffix = f"  [{', '.join(notes)}]" if notes else ""
        print(f"   {state:<9} {migration.version}  {migration.name}{suffix}")
    for version in report.unknown:
        print(f"   note: {version} is recorded as applied but has no file here")
    if report.invalid_indexes:
        print(f"   warning: invalid indexes: {', '.join(report.invalid_indexes)}")
    if report.error:
        print(f"   PROBLEM: {report.error}")


def print_summary(reports: list[Report], opts: Options) -> None:
    waiting = sum(1 for r in reports if r.pending and not r.error)
    problems = sum(1 for r in reports if r.error or r.changed)
    ran = sum(len(r.ran) for r in reports)
    print()
    print(
        f"Summary: {len(reports)} database(s) looked at, "
        f"{waiting} with files waiting, {problems} with a problem."
    )
    if opts.apply:
        print(f"Applied {ran} file(s) in this run.")
    else:
        print("Plan only - nothing was changed. Add --apply to change the databases.")


# -------------------------------------------------------------------------- the runner


def refuse_unless_allowed(targets: list[Target], opts: Options) -> None:
    remote = [t.label for t in targets if not dsn_is_local(t.dsn)]
    if not remote:
        return
    names = ", ".join(remote)
    if not opts.allow_remote:
        raise MigrationError(
            f"not on this computer: {names}. Nothing was touched. Use --allow-remote "
            "only if you mean to look at (or change) a live database."
        )
    if opts.apply and not opts.backup_taken:
        raise MigrationError(
            f"--apply on a database that is not on this computer ({names}) also needs "
            "--backup-taken, to confirm you made a backup first. Nothing was touched."
        )


async def run(opts: Options) -> int:
    catalog = load_catalog(opts.root)
    routing = os.environ.get(ROUTING_ENV, "").strip()
    if not routing:
        raise MigrationError(
            f"{ROUTING_ENV} is not set. Set it in this terminal to the routing "
            "database address (do not write it into a file that is committed)."
        )
    refuse_unless_allowed([Target("control", "control", routing)], opts)
    try:
        conn = await open_connection(routing, opts)
        try:
            rows = await conn.fetch(
                "SELECT source_key, database_url FROM public.data_sources "
                "ORDER BY source_key"
            )
        finally:
            await conn.close()
    except Exception as exc:
        raise MigrationError(
            f"could not read the client list from the control database "
            f"({describe(exc)})"
        ) from None

    targets = [Target("control", "control", routing)]
    for row in rows:
        if row["source_key"] == "control":
            raise MigrationError("a client database may not be called 'control'")
        targets.append(Target(row["source_key"], "tenant", row["database_url"]))
    if opts.tenants:
        known = {t.label for t in targets}
        unknown = [t for t in opts.tenants if t not in known]
        if unknown:
            raise MigrationError(
                f"unknown database name(s): {', '.join(unknown)}. "
                f"Known: {', '.join(sorted(known))}"
            )
        targets = [t for t in targets if t.label in opts.tenants]
    refuse_unless_allowed(targets, opts)

    all_versions = catalog.all_versions()
    reports: list[Report] = []
    for target in targets:
        plan = (
            catalog.for_control()
            if target.kind == "control"
            else catalog.for_tenant(target.label)
        )
        report = await process_target(target, plan, all_versions, opts)
        print_report(report)
        sys.stdout.flush()
        reports.append(report)
    print_summary(reports, opts)
    return 2 if any(r.error or r.changed for r in reports) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.migrate",
        description=(
            "Numbered, tracked SQL changes for the control database and every client "
            "database. With no flag it only shows a plan."
        ),
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="show what each database has applied and what is waiting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the plan and change nothing (this is also what no flag does)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="really apply the waiting files"
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
        help="allow databases that are not on this computer",
    )
    parser.add_argument(
        "--backup-taken",
        action="store_true",
        help="with --apply on a remote database: confirms backups were taken first",
    )
    parser.add_argument(
        "--dir",
        default=str(MIGRATIONS_DIR),
        help="folder holding core/, control/ and features/ (default: migrations/)",
    )
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=5.0,
        help="seconds to wait for a table lock before giving up (default 5)",
    )
    parser.add_argument(
        "--statement-timeout",
        type=float,
        default=300.0,
        help="seconds one statement may run (default 300)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    opts = Options(
        apply=args.apply and not args.dry_run,
        status=args.status,
        tenants=[
            name.strip()
            for item in args.tenant
            for name in item.split(",")
            if name.strip()
        ],
        root=Path(args.dir),
        allow_remote=args.allow_remote,
        backup_taken=args.backup_taken,
        lock_timeout=args.lock_timeout,
        statement_timeout=args.statement_timeout,
    )
    with suppress(Exception):
        sys.stdout.reconfigure(errors="replace")
    try:
        return asyncio.run(run(opts))
    except MigrationError as exc:
        print(f"STOPPED - {redact(str(exc))}")
        return 1
    except Exception as exc:
        print(f"UNEXPECTED PROBLEM - {describe(exc)}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
