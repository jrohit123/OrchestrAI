"""
sql_guard.py — checks and rewrites the SQL the assistant writes itself.

Almost everything the bot does is built by code from stored steps and stored reports. This
module covers the one place where the model writes SQL: a read question that no stored report
answers (the query_database tool). The query is parsed, not pattern-matched, so a comma join, a
subquery, a CTE or a renamed column cannot slip past a text check.

What prepare() guarantees about the SQL it returns:
  * one statement, and it is a plain SELECT (no INTO, no row locks, no data-changing CTE)
  * every table it reads is one the person's role may read (CTE names excluded)
  * no table function, no table from another schema
  * no dangerous function (pg_*, set_config, dblink, nextval, ...)
  * no hidden column (ids, phone, email, ...) in anything it returns
  * every table that has an org_id column is replaced by that table filtered to this
    organisation, so the filter no longer depends on the model writing it
  * at most MAX_ROWS rows

The caller still runs it in a read-only transaction with a time limit (db.fetch_all_readonly),
so even a mistake here cannot change data or run for long.
"""

import logging
import time

import sqlglot
from sqlglot import exp

from app.db import fetch_all, fetch_one
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

# sqlglot warns when it meets syntax it does not know, and such a query is refused anyway
logging.getLogger("sqlglot").setLevel(logging.ERROR)

MAX_ROWS = 100
QUERY_TIMEOUT_MS = 5000

# function names (lower case) that must never run, and prefixes that identify whole families
_DENY_NAMES = {
    "version",
    "set_config",
    "current_setting",
    "nextval",
    "setval",
    "currval",
    "lastval",
    "current_user",
    "current_role",
    "current_version",
    "session_user",
    "user",
    "current_database",
    "current_schema",
    "current_schemas",
    "current_catalog",
    "query_to_xml",
    "table_to_xml",
    "cursor_to_xml",
    "schema_to_xml",
    "database_to_xml",
    "xpath",
    "xmlparse",
}
_DENY_PREFIXES = ("pg_", "lo_", "dblink", "txid_", "has_", "inet_")

# anything that changes data or structure, wherever it hides (for example inside a CTE)
_CHANGING = tuple(
    getattr(exp, n)
    for n in (
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Create",
        "Drop",
        "Alter",
        "AlterTable",
        "Command",
        "Copy",
        "TruncateTable",
        "Grant",
        "Set",
        "Use",
        "Transaction",
        "Commit",
        "Rollback",
    )
    if hasattr(exp, n)
)


class GuardError(Exception):
    """The query is not allowed. The text is written for the assistant to read and fix it."""


def _func_name(node) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name or "").lower()
    try:
        return str(node.sql_name() or "").lower()
    except Exception:
        return type(node).__name__.lower()


def _own_columns(projection):
    """Columns in one select-list item, not descending into nested selects (those are checked
    on their own, with their own select list)."""
    stack = [projection]
    while stack:
        node = stack.pop()
        if isinstance(node, exp.Column):
            yield node
        for child in node.args.values():
            for c in child if isinstance(child, list) else [child]:
                if isinstance(c, exp.Expression) and not isinstance(
                    c, (exp.Select, exp.Subquery)
                ):
                    stack.append(c)


def prepare(
    sql: str,
    *,
    allowed_tables,
    org_id: str,
    org_scoped_tables,
    hidden_columns,
    max_rows: int = MAX_ROWS,
):
    """Return (safe_sql, tables_read) or raise GuardError."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.SqlglotError as e:
        raise GuardError(
            "the query could not be understood. Write one plain PostgreSQL SELECT."
        ) from e
    if len(statements) != 1:
        raise GuardError("only one SELECT statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise GuardError("only SELECT queries are allowed.")
    if tree.find(*_CHANGING):
        raise GuardError("only reading is allowed, nothing may change data.")
    if tree.find(exp.Into):
        raise GuardError("SELECT ... INTO is not allowed.")
    if tree.find(exp.Lock):
        raise GuardError("locking rows is not allowed.")

    allowed = {t.lower() for t in allowed_tables}
    scoped = {t.lower() for t in org_scoped_tables}
    hidden = {c.lower() for c in hidden_columns} | {
        "user"
    }  # a bare USER returns the database login
    cte_names = {str(c.alias_or_name).lower() for c in tree.find_all(exp.CTE)}

    # every table it reads
    used: set[str] = set()
    tables = list(tree.find_all(exp.Table))
    for t in tables:
        name = (t.name or "").lower()
        if not name:
            raise GuardError("functions cannot be used as a table. Use real tables.")
        schema = (t.db or "").lower()
        if schema and schema != "public":
            raise GuardError(f"tables from the schema '{schema}' are not allowed.")
        if not schema and name in cte_names:
            continue
        if name not in allowed:
            raise GuardError(f"not permitted to read table '{name}'.")
        used.add(name)

    # dangerous functions
    for node in tree.find_all(exp.Func):
        name = _func_name(node)
        if name in _DENY_NAMES or name.startswith(_DENY_PREFIXES):
            raise GuardError(f"the function '{name}' is not allowed.")

    # hidden columns may be filtered on but never returned (also not renamed on the way out)
    for sel in tree.find_all(exp.Select):
        for proj in sel.expressions:
            for col in _own_columns(proj):
                if col.name.lower() in hidden:
                    raise GuardError(
                        f"the column '{col.name}' cannot be returned. Leave it out of the select list."
                    )

    # org filter, built in instead of trusting the model to write it
    scope_ok = _uuid_ok(org_id)
    if not scope_ok:
        raise GuardError("internal error resolving the organisation.")
    for t in tables:
        name = (t.name or "").lower()
        if (t.db or "").lower() not in ("", "public") or name not in scoped:
            continue
        if not t.db and name in cte_names:
            continue
        alias = t.alias or t.name
        inner = (
            sqlglot.select("*")
            .from_(exp.Table(this=exp.to_identifier(t.name)))
            .where(f"org_id = '{org_id}'")
        )
        t.replace(
            exp.Subquery(
                this=inner, alias=exp.TableAlias(this=exp.to_identifier(alias))
            )
        )

    # row limit
    limit = tree.args.get("limit")
    n = None
    if limit is not None:
        try:
            n = int(limit.expression.name)
        except (TypeError, ValueError, AttributeError):
            n = None
    if n is None or n > max_rows:
        tree = tree.limit(max_rows)
    return tree.sql(dialect="postgres"), used


def _uuid_ok(value) -> bool:
    import re

    return bool(re.fullmatch(r"[0-9a-fA-F-]{36}", str(value)))


# ── what the guard needs to know about an organisation's database ─────────────

_scoped_cache: dict[str, tuple[float, set[str]]] = {}
_policy_cache: dict[str, tuple[float, dict]] = {}


async def org_scoped_tables(source_key: str) -> set[str]:
    """Tables that have an org_id column in this organisation's database (cached 10 minutes)."""
    hit = _scoped_cache.get(source_key)
    if hit and time.monotonic() - hit[0] < 600:
        return hit[1]
    rows = await fetch_all(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'org_id'",
        source_key=source_key,
    )
    found = {r["table_name"] for r in rows}
    _scoped_cache[source_key] = (time.monotonic(), found)
    return found


async def ai_sql_allowed(user: dict) -> tuple[bool, str]:
    """The per-organisation switch for AI-written SQL.

    orgs.settings -> 'ai_sql' = {"enabled": false}             switches it off for everyone
                                {"roles": ["admin", "committee"]}  only those roles may use it
    Nothing configured means it stays on, as before.
    """
    key = f"{user['source_key']}:{user['org_id']}"
    hit = _policy_cache.get(key)
    if hit and time.monotonic() - hit[0] < 30:
        cfg = hit[1]
    else:
        row = await fetch_one(
            "SELECT settings FROM orgs WHERE id = $1",
            user["org_id"],
            source_key=user["source_key"],
        )
        settings = row["settings"] if row else None
        if isinstance(settings, str):
            import json

            try:
                settings = json.loads(settings)
            except ValueError:
                settings = {}
        cfg = (settings or {}).get("ai_sql") or {}
        _policy_cache[key] = (time.monotonic(), cfg)
    if cfg.get("enabled") is False:
        return False, (
            "free-form questions are switched off for this organisation. "
            "Only the stored reports can answer. Tell the person you cannot answer that here."
        )
    roles = cfg.get("roles")
    if roles and user.get("role") not in roles:
        return False, (
            "free-form questions are not available for this person's role. "
            "Tell the person you cannot answer that for them."
        )
    return True, ""
