"""
SQL safety validator and schema loader.
Used by the tool-calling agent in agent.py.
"""

import re

from app.db import fetch_all
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

_DANGEROUS = [
    r"\bDROP\b",
    r"\bDELETE\b",
    r"\bTRUNCATE\b",
    r"\bALTER\b",
    r"\bCREATE\b",
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bGRANT\b",
    r"\bEXEC(UTE)?\b",
    r";\s*--",
    r"\bpg_\w+",
    r"\binformation_schema\b",
    r"\bpg_catalog\b",
]

SENSITIVE_COLS = {
    "org_id",
    "user_id",
    "role_id",
    "customer_id",
    "invoice_id",
    "quotation_id",
    "order_id",
    "created_by",
    "updated_by",
    "scheduled_by",
    "decided_by",
    "requester_id",
    "approver_role",
    "workflow_id",
    "otp_hash",
    "config",
    "phone",
    "email",
}


def _safe(sql: str) -> tuple[bool, str]:
    upper = sql.upper()
    for p in _DANGEROUS:
        if re.search(p, upper, re.IGNORECASE):
            return False, f"Blocked: {p}"
    if not upper.strip().startswith("SELECT"):
        return False, "Only SELECT allowed"
    if ";" in sql.rstrip(";"):
        return False, "Multiple statements blocked"
    return True, "ok"


_ENTITY_TYPE_EQ = re.compile(r"entity_type\s*=\s*'([^']+)'", re.IGNORECASE)
_ENTITY_TYPE_IN = re.compile(r"entity_type\s+IN\s*\(([^)]+)\)", re.IGNORECASE)


def check_entity_records_access(sql: str, readable_entity_types) -> tuple[bool, str]:
    """
    entity_records is one physical table standing in for what used to be
    several separate tables — some sensitive (e.g. invoices). Once they
    share a table, readable_tables' table-level check can no longer tell
    them apart, so a role granted one entity_type's workflow could
    otherwise read every other entity_type through the same table name.

    Every query touching entity_records must name the entity_type(s) it
    wants as a literal in the SQL text — no filter at all is rejected
    (that would return every entity_type's rows at once) — and every
    literal named must be in the caller's readable_entity_types.

    Same regex-based safety-net philosophy as _safe()/the readable_tables
    check above: not a full SQL parser, but it closes the actual leak
    this table design introduces, which a bare table-name allowlist can't.
    """
    if not re.search(r"\bentity_records\b", sql, re.IGNORECASE):
        return True, "ok"

    literals = set(_ENTITY_TYPE_EQ.findall(sql))
    for group in _ENTITY_TYPE_IN.findall(sql):
        literals.update(v.strip().strip("'") for v in group.split(","))

    if not literals:
        return False, "entity_records queries must filter on a specific entity_type"

    not_allowed = literals - set(readable_entity_types or [])
    if not_allowed:
        return False, f"not permitted to read entity_type(s): {', '.join(sorted(not_allowed))}"

    return True, "ok"


async def execute_query(
    sql: str,
    params: list,
    user: dict,
    response_format: str = "generic",
    business_glossary: dict = None,
) -> str:
    """
    Execute a validated SELECT query and return formatted results.
    Used by read workflows with empty entity_schema.
    """
    # NOTE: sql_template here is authored once by workflow_compiler and reused
    # unchanged, so it still uses the old $1=org_id / $2+=params convention
    # (see workflow_compiler.txt). Do NOT port the :org_id-marker redesign from
    # agent.py's query_database here without also migrating already-compiled
    # workflows in the DB — this path isn't where the per-turn LLM offset bug
    # showed up, since these templates are reviewed once, not regenerated live.
    if business_glossary is None:
        business_glossary = {}

    # Validate SQL
    ok, reason = _safe(sql)
    if not ok:
        return f"ERROR: Query blocked — {reason}"

    # Check readable_tables permission
    readable_tables = set(user.get("readable_tables", []))
    referenced_tables = set(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.IGNORECASE))
    not_allowed = referenced_tables - readable_tables
    if not_allowed:
        return f"ERROR: not permitted to read tables: {', '.join(sorted(not_allowed))}"

    ok, reason = check_entity_records_access(sql, user.get("readable_entity_types"))
    if not ok:
        return f"ERROR: {reason}"

    # Add LIMIT if not present (prevent runaway queries)
    if "LIMIT" not in sql.upper():
        sql = sql.rstrip(";") + " LIMIT 100"

    try:
        full_params = [user["org_id"]] + list(params)
        logger.info(f"execute_query running: {sql[:200]}")
        rows = await fetch_all(sql, *full_params, source_key=user["source_key"])

        # Strip sensitive columns
        clean = []
        for r in rows:
            row = {
                k: v
                for k, v in dict(r).items()
                if k not in SENSITIVE_COLS
                and not (
                    isinstance(v, str)
                    and len(v) > 30
                    and "-" in v
                    and k.endswith("_id")
                )
            }
            clean.append(row)

        if not clean:
            return "No results found."

        # Format based on response_format
        if response_format == "table":
            # Simple table format
            if clean:
                headers = list(clean[0].keys())
                lines = [" | ".join(headers)]
                for row in clean:
                    lines.append(" | ".join(str(row.get(h, "")) for h in headers))
                return "\n".join(lines)
            return "No results."
        else:
            # Generic JSON format (default)
            import json

            return json.dumps(clean, default=str, indent=2)

    except Exception as e:
        logger.error(f"execute_query failed: {e}", exc_info=True)
        return f"ERROR: {e!s}"
