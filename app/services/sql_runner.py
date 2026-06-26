"""
Safe read-only SQL execution.
"""
import re
import json
from datetime import date, datetime
from decimal import Decimal
from app.db import fetch_all

_DANGEROUS = [
    r'\bDROP\b', r'\bDELETE\b', r'\bTRUNCATE\b', r'\bALTER\b',
    r'\bCREATE\b', r'\bINSERT\b', r'\bUPDATE\b', r'\bGRANT\b',
    r'\bEXEC(UTE)?\b', r';\s*--', r'\bpg_\w+',
    r'\binformation_schema\b', r'\bpg_catalog\b',
]

SENSITIVE_COLS = {
    'id', 'org_id', 'user_id', 'role_id', 'customer_id', 'invoice_id',
    'quotation_id', 'order_id', 'created_by', 'updated_by', 'scheduled_by',
    'decided_by', 'requester_id', 'approver_role', 'workflow_id',
    'otp_hash', 'config',
}


def _tables_in_sql(sql: str) -> set[str]:
    found = set()
    for m in re.finditer(r'\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)', sql, re.I):
        found.add(m.group(1).lower())
    return found


def validate_sql(sql: str, allowed_tables: set[str] | None = None) -> tuple[bool, str]:
    upper = sql.upper()
    for p in _DANGEROUS:
        if re.search(p, upper, re.IGNORECASE):
            return False, f"Blocked: {p}"
    if not upper.strip().startswith("SELECT"):
        return False, "Only SELECT allowed"
    if ";" in sql.rstrip(";"):
        return False, "Multiple statements blocked"
    if allowed_tables is not None:
        used = _tables_in_sql(sql)
        bad = used - {t.lower() for t in allowed_tables}
        if bad:
            return False, f"Table not permitted: {', '.join(sorted(bad))}"
    return True, "ok"


def _json_safe(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def clean_rows(rows: list) -> list:
    def is_uuid(v):
        return isinstance(v, str) and len(v) > 30 and "-" in v

    clean = []
    for r in rows:
        row = {
            k: _json_safe(v)
            for k, v in r.items()
            if k.lower() not in SENSITIVE_COLS and not is_uuid(v)
        }
        if row:
            clean.append(row)
    return clean


async def run_select(
    org_id: str,
    sql: str,
    params: list | None = None,
    allowed_tables: set[str] | None = None,
) -> dict:
    """Execute validated SELECT. Returns {ok, rows, error, row_count}."""
    ok, reason = validate_sql(sql, allowed_tables)
    if not ok:
        return {"ok": False, "rows": [], "error": reason, "row_count": 0}

    db_params = [org_id] + list(params or [])
    try:
        rows = [dict(r) for r in await fetch_all(sql, *db_params)]
        cleaned = clean_rows(rows)
        return {
            "ok": True,
            "rows": cleaned,
            "error": None,
            "row_count": len(cleaned),
            "preview": json.dumps(cleaned[:15], default=str),
        }
    except Exception as e:
        return {"ok": False, "rows": [], "error": str(e), "row_count": 0}
