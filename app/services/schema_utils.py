"""
Schema utilities for database operations.
Provides shared functions for fetching schema information with proper filtering.
"""
import json
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


def format_schema_text(table_cols: dict, column_descriptions: dict | None = None) -> str:
    """
    Format schema dict into human-readable text for LLM prompts.

    Args:
        table_cols: Dict mapping table_name -> list of column names
        column_descriptions: Optional {table: {column: "meaning"}} from
            get_column_descriptions() — when a column has one, it's shown
            inline so the compiler doesn't have to guess semantics from the
            bare name alone.

    Returns:
        Formatted string representation of the schema
    """
    column_descriptions = column_descriptions or {}
    lines = []
    for t, cs in sorted(table_cols.items()):
        table_desc = column_descriptions.get(t) or {}
        col_strs = [
            f"{c} ({table_desc[c]})" if table_desc.get(c) else c
            for c in cs
        ]
        lines.append(f"  {t}: {', '.join(col_strs)}")
    return "\n".join(lines)