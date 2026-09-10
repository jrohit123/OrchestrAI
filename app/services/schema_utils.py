"""
Schema utilities for database operations.
Provides shared functions for fetching schema information with proper filtering.
"""
import json
import re
from app.db import fetch_all, fetch_one


# System/internal tables that should be excluded from business schema
# These are workflow engine tables, not business domain tables
SYSTEM_TABLE_BLOCKLIST = {
    'audit_log', 'otp_tokens', 'pending_approvals',
    'credentials', 'workflows', 'workflow_drafts', 'scheduled_reports'
}


async def get_business_schema(source_key: str) -> dict:
    """
    Get all business table schemas (excluding system/workflow tables).
    
    This uses a blocklist approach rather than an allowlist, making it
    domain-agnostic and future-proof for new business tables.
    
    Args:
        source_key: Database source key for multi-tenancy
        
    Returns:
        Dict mapping table_name -> list of column names
    """
    cols = await fetch_all("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name NOT IN (SELECT unnest($1::text[]))
        ORDER BY table_name, ordinal_position
    """, list(SYSTEM_TABLE_BLOCKLIST), source_key=source_key)

    table_cols: dict = {}
    for r in cols:
        table_cols.setdefault(r["table_name"], []).append(r["column_name"])

    return table_cols


async def get_column_descriptions(org_id: str, source_key: str) -> dict:
    """
    Per-org column meanings, stored at orgs.settings->'column_descriptions'
    as {table: {column: "what this column actually means"}} — no schema
    change, reuses the same jsonb column already used for vocabulary and
    case_reminders config. Grounds the compiler's table/column mapping
    decisions instead of leaving it to guess from bare column names alone,
    which is how "resident_name" ended up mapped to "first_owner_name" (a
    real column, wrong meaning) — bare names carry no signal that
    first_owner_name is specific to the flat's recorded first owner, not
    a generic "this row's own name" field.

    Returns {} if the org has none configured yet — callers must treat
    missing descriptions as normal, not an error; this is opt-in enrichment.
    """
    row = await fetch_one("SELECT settings FROM orgs WHERE id = $1", org_id, source_key=source_key)
    if not row or not row.get("settings"):
        return {}
    settings = row["settings"]
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except (json.JSONDecodeError, TypeError):
            return {}
    return (settings or {}).get("column_descriptions") or {}


_COLUMN_TYPE_CACHE: dict = {}


async def get_column_types(source_key: str) -> dict:
    """
    {(table, column): postgres_data_type} — e.g. ('meetings','meeting_date')
    -> 'date'. entity_schema's type vocabulary is only string/integer/float
    (see workflow_compiler.txt RULE 3), so a date-typed column has no way to
    signal that at compile time without this — the runtime chat agent then
    has no idea a free-text date needs normalizing to ISO before it becomes
    a SQL value, and whatever the user actually typed ("15 Sep 2026") goes
    straight into an insert/update and crashes against asyncpg's date codec.
    Used by workflow_compiler.txt (to mark entity_schema fields with
    "format":"date") and step_interpreter.py (as the deterministic
    normalization safety net, same role get_enum_constraints plays for
    CHECK-constraint columns).
    """
    if source_key in _COLUMN_TYPE_CACHE:
        return _COLUMN_TYPE_CACHE[source_key]
    rows = await fetch_all("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
    """, source_key=source_key)
    types = {(r["table_name"], r["column_name"]): r["data_type"] for r in rows}
    _COLUMN_TYPE_CACHE[source_key] = types
    return types


_ENUM_CONSTRAINT_CACHE: dict = {}


async def get_enum_constraints(source_key: str) -> dict:
    """
    Introspect simple `column IN (...)` / `column = ANY(ARRAY[...])` CHECK
    constraints straight from Postgres — e.g. residents.residential_status
    only accepting 'first_owner'/'second_owner'/'tenant'. Grounds the
    compiler's entity_schema so a field backed by such a column carries its
    real allowed values, which the runtime chat agent then uses to capture
    the CORRECT canonical value from free text (an LLM handles "he's the
    first owner" / typos / Hinglish far better than any string-normalization
    heuristic could) — this data is also step_interpreter.py's deterministic
    last-line-of-defense before an insert/update actually hits the DB.

    Returns {(table, column): [values, ...]}. Best-effort: a constraint this
    regex can't parse (ranges, multi-column expressions, etc.) is silently
    skipped, never raises.
    """
    if source_key in _ENUM_CONSTRAINT_CACHE:
        return _ENUM_CONSTRAINT_CACHE[source_key]

    rows = await fetch_all("""
        SELECT rel.relname AS table_name, pg_get_constraintdef(con.oid) AS def
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE con.contype = 'c' AND nsp.nspname = 'public'
    """, source_key=source_key)

    parsed: dict = {}
    pattern = re.compile(
        r'\(?"?(\w+)"?\)?(?:::[\w\s]+)?\s*=\s*ANY\s*\(*ARRAY\[(.*?)\]', re.IGNORECASE
    )
    literal_pattern = re.compile(r"'((?:[^'\\]|\\.)*)'")
    for row in rows:
        m = pattern.search(row["def"] or "")
        if not m:
            continue
        column, array_body = m.group(1), m.group(2)
        values = literal_pattern.findall(array_body)
        if values:
            parsed[(row["table_name"], column)] = values

    _ENUM_CONSTRAINT_CACHE[source_key] = parsed
    return parsed


_DATE_TYPES = {"date", "timestamp without time zone", "timestamp with time zone"}


def format_schema_text(
    table_cols: dict,
    column_descriptions: dict | None = None,
    enum_constraints: dict | None = None,
    column_types: dict | None = None,
) -> str:
    """
    Format schema dict into human-readable text for LLM prompts.

    Args:
        table_cols: Dict mapping table_name -> list of column names
        column_descriptions: Optional {table: {column: "meaning"}} from
            get_column_descriptions() — when a column has one, it's shown
            inline so the compiler doesn't have to guess semantics from the
            bare name alone.
        enum_constraints: Optional {(table, column): [values]} from
            get_enum_constraints() — shown inline as "(options: a, b, c)" so
            the compiler knows to carry these into entity_schema's "enum".
        column_types: Optional {(table, column): postgres_data_type} from
            get_column_types() — a date/timestamp column is shown inline as
            "(date field)" so the compiler knows to carry a "format":"date"
            hint into entity_schema for it.

    Returns:
        Formatted string representation of the schema
    """
    column_descriptions = column_descriptions or {}
    enum_constraints = enum_constraints or {}
    column_types = column_types or {}
    lines = []
    for t, cs in sorted(table_cols.items()):
        table_desc = column_descriptions.get(t) or {}
        col_strs = []
        for c in cs:
            parts = []
            if table_desc.get(c):
                parts.append(table_desc[c])
            options = enum_constraints.get((t, c))
            if options:
                parts.append(f"options: {', '.join(options)}")
            if column_types.get((t, c)) in _DATE_TYPES:
                parts.append("date field")
            col_strs.append(f"{c} ({'; '.join(parts)})" if parts else c)
        lines.append(f"  {t}: {', '.join(col_strs)}")
    return "\n".join(lines)