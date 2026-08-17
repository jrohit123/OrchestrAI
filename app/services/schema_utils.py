"""
Schema utilities for database operations.
Provides shared functions for fetching schema information with proper filtering.
"""
from app.db import fetch_all


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
          AND table_name NOT IN (
              'audit_log', 'otp_tokens', 'pending_approvals',
              'credentials', 'workflows', 'workflow_drafts', 'scheduled_reports'
          )
        ORDER BY table_name, ordinal_position
    """, source_key=source_key)

    table_cols: dict = {}
    for r in cols:
        table_cols.setdefault(r["table_name"], []).append(r["column_name"])
    
    return table_cols


async def get_business_schema_with_types(source_key: str) -> dict:
    """
    Get all business table schemas with data types (excluding system/workflow tables).
    
    Args:
        source_key: Database source key for multi-tenancy
        
    Returns:
        Dict mapping table_name -> list of (column_name, data_type) tuples
    """
    cols = await fetch_all("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name NOT IN (
              'audit_log', 'otp_tokens', 'pending_approvals',
              'credentials', 'workflows', 'workflow_drafts', 'scheduled_reports'
          )
        ORDER BY table_name, ordinal_position
    """, source_key=source_key)

    table_cols: dict = {}
    for r in cols:
        table_cols.setdefault(r["table_name"], []).append(
            (r["column_name"], r["data_type"])
        )
    
    return table_cols


def format_schema_text(table_cols: dict, include_types: bool = False) -> str:
    """
    Format schema dict into human-readable text for LLM prompts.
    
    Args:
        table_cols: Dict mapping table_name -> list of column names or (name, type) tuples
        include_types: Whether to include data types in the output
        
    Returns:
        Formatted string representation of the schema
    """
    if include_types:
        return "\n".join(
            f"  {t}: {', '.join(f'{name} ({dtype})' for name, dtype in cs)}"
            for t, cs in sorted(table_cols.items())
        )
    else:
        return "\n".join(
            f"  {t}: {', '.join(cs if isinstance(cs[0], str) else [c[0] for c in cs])}"
            for t, cs in sorted(table_cols.items())
        )