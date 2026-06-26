"""
Live schema introspection — tables derived from DB + user permissions.
"""
from app.db import fetch_all

_schema_cache: dict[str, str] = {}
_tables_cache: set[str] | None = None

# Internal tables never exposed to read agent (security, not business routing)
_INTERNAL_TABLES = frozenset({
    "audit_log", "otp_tokens", "credentials", "workflows",
    "pending_approvals", "users", "roles", "orgs",
})


async def _business_tables() -> set[str]:
    global _tables_cache
    if _tables_cache is not None:
        return _tables_cache
    rows = await fetch_all("""
        SELECT DISTINCT table_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
    """)
    _tables_cache = {r["table_name"] for r in rows} - _INTERNAL_TABLES
    return _tables_cache


def _permissions_allow_table(table: str, permissions: list[str]) -> bool:
    """Derive table access from permission strings stored in DB (roles.permissions)."""
    if not permissions:
        return False
    joined = " ".join(permissions).lower()
    if "owner" in joined or permissions == ["owner"]:
        return True

    # Table ↔ permission substring links (permission names come from DB, not user messages)
    signals = {
        "inventory": ("stock", "inventory"),
        "invoices": ("invoice", "outstanding", "dues"),
        "customers": ("customer", "outstanding", "dues", "credit"),
        "orders": ("order", "production"),
        "pricing": ("quotation", "metal", "price", "rate"),
    }
    if table in signals:
        return any(s in joined for s in signals[table])
    return "general_read" in permissions


async def get_allowed_tables(role: str, permissions: list[str] | None = None) -> set[str]:
    perms = permissions or []
    if role == "owner":
        return await _business_tables()
    if "general_read" in perms and role not in ("warehouse",):
        return await _business_tables()
    allowed = {t for t in await _business_tables() if _permissions_allow_table(t, perms)}
    return allowed


async def get_schema_text(role: str, permissions: list[str] | None = None) -> str:
    cache_key = f"{role}:{','.join(sorted(permissions or []))}"
    if cache_key in _schema_cache:
        return _schema_cache[cache_key]

    allowed = await get_allowed_tables(role, permissions)
    cols = await fetch_all("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)
    table_cols: dict[str, list] = {}
    for c in cols:
        t = c["table_name"]
        if t not in allowed:
            continue
        table_cols.setdefault(t, []).append(f"{c['column_name']} ({c['data_type']})")

    fk_hints = await fetch_all("""
        SELECT tc.table_name, kcu.column_name, ccu.table_name AS foreign_table
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage ccu
            ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
    """)
    fk_lines = [
        f"- {r['table_name']}.{r['column_name']} -> {r['foreign_table']}"
        for r in fk_hints if r["table_name"] in allowed
    ]

    lines = [f"- {t}: {', '.join(cs)}" for t, cs in sorted(table_cols.items())]
    text = "TABLES:\n" + "\n".join(lines)
    if fk_lines:
        text += "\n\nJOINS:\n" + "\n".join(fk_lines)
    text += "\n\nRULES: Always filter by org_id = $1 on every table. SELECT only."

    _schema_cache[cache_key] = text
    return text


async def get_sample_context(org_id: str, role: str, permissions: list[str] | None = None) -> str:
    allowed = await get_allowed_tables(role, permissions)
    parts = []

    if "customers" in allowed:
        rows = await fetch_all(
            "SELECT name, city FROM customers WHERE org_id = $1 ORDER BY name LIMIT 5",
            org_id,
        )
        if rows:
            parts.append("Sample customers: " + ", ".join(f"{r['name']} ({r['city']})" for r in rows))

    if "inventory" in allowed:
        rows = await fetch_all(
            "SELECT name, qty FROM inventory WHERE org_id = $1 ORDER BY name LIMIT 4",
            org_id,
        )
        if rows:
            parts.append("Sample inventory: " + ", ".join(f"{r['name']} ({r['qty']} pcs)" for r in rows))

    if "pricing" in allowed:
        rows = await fetch_all(
            """SELECT metal_type, rate_per_gram FROM pricing
               WHERE org_id = $1 AND quotation_number IS NULL LIMIT 5""",
            org_id,
        )
        if rows:
            parts.append("Metal rates: " + ", ".join(f"{r['metal_type']} ₹{r['rate_per_gram']}/g" for r in rows))

    return "\n".join(parts)


def invalidate_schema_cache():
    global _tables_cache
    _schema_cache.clear()
    _tables_cache = None
