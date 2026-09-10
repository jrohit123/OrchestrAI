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


def format_schema_text(
    table_cols: dict,
    column_descriptions: dict | None = None,
    enum_constraints: dict | None = None,
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

    Returns:
        Formatted string representation of the schema
    """
    column_descriptions = column_descriptions or {}
    enum_constraints = enum_constraints or {}
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
            col_strs.append(f"{c} ({'; '.join(parts)})" if parts else c)
        lines.append(f"  {t}: {', '.join(col_strs)}")
    return "\n".join(lines)