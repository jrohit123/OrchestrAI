"""
Dynamic SQL Query Engine.
LLM generates SQL from intent + schema. Validates safety. Executes read-only.
"""
import os
import re
import json
from openai import AsyncOpenAI
from dotenv import load_dotenv
from app.db import fetch_all

load_dotenv()
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_DB_SCHEMA: str | None = None
_VALID_COLUMNS: dict | None = None

# Patterns that must never appear in generated SQL
_DANGEROUS = [
    r'\bDROP\b', r'\bDELETE\b', r'\bTRUNCATE\b', r'\bALTER\b',
    r'\bCREATE\b', r'\bINSERT\b', r'\bUPDATE\b', r'\bGRANT\b',
    r'\bEXEC(UTE)?\b', r';\s*--', r'\bpg_\w+',
    r'\binformation_schema\b', r'\bpg_catalog\b'
]

SENSITIVE_COLS = {
    'id', 'org_id', 'user_id', 'role_id', 'customer_id', 'invoice_id',
    'quotation_id', 'order_id', 'created_by', 'updated_by', 'scheduled_by',
    'decided_by', 'requester_id', 'approver_role', 'workflow_id',
    'otp_hash', 'config',
}


async def _load_schema():
    global _DB_SCHEMA, _VALID_COLUMNS
    if _DB_SCHEMA:
        return

    cols = await fetch_all("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)

    _VALID_COLUMNS = {}
    table_cols: dict[str, list] = {}

    for c in cols:
        t = c['table_name']
        _VALID_COLUMNS.setdefault(t, set()).add(c['column_name'])
        table_cols.setdefault(t, []).append(f"{c['column_name']} ({c['data_type']})")

    lines = []
    for t, cs in sorted(table_cols.items()):
        lines.append(f"- {t}: {', '.join(cs)}")

    _DB_SCHEMA = "TABLES:\n" + "\n".join(lines)
    print(f"[QUERY_ENGINE] Schema loaded: {len(_VALID_COLUMNS)} tables")


def _safe(sql: str) -> tuple[bool, str]:
    upper = sql.upper()
    for p in _DANGEROUS:
        if re.search(p, upper, re.IGNORECASE):
            return False, f"Blocked: {p}"
    if not upper.strip().startswith('SELECT'):
        return False, "Only SELECT allowed"
    if ';' in sql.rstrip(';'):
        return False, "Multiple statements blocked"
    return True, "ok"


async def _gen_sql(intent: str, parameters: dict) -> dict:
    await _load_schema()

    prompt = f"""You are a PostgreSQL expert. Generate a safe SELECT query.

REQUEST: {intent}
EXTRACTED PARAMETERS: {json.dumps(parameters)}

SCHEMA:
{_DB_SCHEMA}

RULES:
- SELECT only — no INSERT/UPDATE/DELETE
- Always WHERE org_id = $1 (parameterized, never literal)
- Use $1, $2... placeholders — NEVER embed values in SQL
- ILIKE with %wildcards% for text search
- LIMIT 20 unless user specified a different limit
- JOIN tables as needed
- Return ONLY JSON: {{"sql": "...", "params": {{}}}}

PARAM MAPPING:
- customer_name → use ILIKE: '%name%'
- product_name  → use ILIKE on inventory.name
- limit         → LIMIT clause
- status        → exact match
- invoice_number, order_number → exact match

Examples:
{{"sql": "SELECT c.name, SUM(i.amount) as total FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE i.org_id=$1 AND i.status IN ('pending','overdue') GROUP BY c.id,c.name ORDER BY total DESC LIMIT 3", "params": {{"limit":3}}}}
{{"sql": "SELECT name, qty, location FROM inventory WHERE org_id=$1 AND name ILIKE $2 LIMIT 5", "params": {{"product_name":"gold ring"}}}}"""

    resp = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=500,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    content = resp.choices[0].message.content.strip()
    if "```" in content:
        content = content.replace("```json", "").replace("```", "").strip()
    return json.loads(content)


def _build_params(sql: str, llm_params: dict, org_id: str) -> list:
    """Build positional params list matching $1..$N in SQL."""
    holes = re.findall(r'\$(\d+)', sql)
    n = max(int(h) for h in holes) if holes else 0

    out = [org_id]  # $1 always org_id
    ordered = []

    for k, v in llm_params.items():
        if k == 'limit':
            ordered.append(int(v))
        elif k in ('customer_name', 'product_name'):
            s = str(v)
            ordered.append(s if s.startswith('%') else f'%{s}%')
        else:
            ordered.append(v)

    for i in range(min(len(ordered), n - 1)):
        out.append(ordered[i])

    return out


def _fmt(rows: list) -> str:
    """Format rows for WhatsApp — filters sensitive columns."""
    if not rows:
        return "✅ No results found."

    def is_uuid(v):
        return isinstance(v, str) and '-' in v and len(v) > 30

    clean = []
    for r in rows:
        row = {k: v for k, v in r.items()
               if k.lower() not in SENSITIVE_COLS and not is_uuid(v)}
        if row:
            clean.append(row)

    if not clean:
        return "✅ No displayable results."

    cols = list(clean[0].keys())

    # Roles/permissions
    if 'name' in cols and 'permissions' in cols:
        lines = ["👥 *Roles & Permissions*"]
        for r in clean:
            p = r.get('permissions', [])
            s = ', '.join(p[:5]) + (f' +{len(p)-5} more' if len(p) > 5 else '')
            lines.append(f"\n• *{r['name']}*\n  {s}")
        return "\n".join(lines)

    # Customers
    if 'name' in cols and 'city' in cols and 'credit_limit' not in cols:
        lines = ["👤 *Customers*"]
        for r in clean[:15]:
            lines.append(f"• {r.get('name')} ({r.get('city','-')})")
        return "\n".join(lines)

    # Inventory
    if 'name' in cols and 'qty' in cols:
        lines = ["📦 *Inventory*"]
        for r in clean[:15]:
            warn = " ⚠️" if r.get('qty', 999) <= r.get('reorder_level', 0) else ""
            lines.append(f"• *{r['name']}*: {r.get('qty')} pcs @ {r.get('location','-')}{warn}")
        return "\n".join(lines)

    # Invoice/dues summary
    if 'total' in cols or 'total_outstanding' in cols or 'total_overdue' in cols:
        lines = ["� *Outstanding Summary*"]
        for r in clean[:10]:
            name = r.get('name') or r.get('customer_name', '?')
            total = r.get('total') or r.get('total_outstanding') or r.get('total_overdue', 0)
            lines.append(f"• *{name}*: ₹{float(total):,.0f}")
        return "\n".join(lines)

    # Metal rates
    if 'metal_type' in cols and 'rate_per_gram' in cols:
        lines = ["💎 *Metal Rates*"]
        for r in clean:
            lines.append(f"• *{r['metal_type']}*: ₹{float(r['rate_per_gram']):,.0f}/g — Making: {r.get('making_charge_pct')}%")
        return "\n".join(lines)

    # Orders
    if 'order_number' in cols or 'status' in cols:
        from app.adapters.orders import STATUS_LABELS
        lines = ["� *Orders*"]
        for r in clean[:10]:
            label = STATUS_LABELS.get(r.get('status', ''), r.get('status', ''))
            cust  = r.get('customer_name', r.get('name', '?'))
            desc  = r.get('description', '')[:35]
            lines.append(f"• *{r.get('order_number','?')}* — {cust}\n  {desc} | {label}")
        return "\n".join(lines)

    # Generic table
    show = cols[:4]
    lines = [f"📊 *Results* ({len(clean)} rows)"]
    for r in clean[:10]:
        parts = [f"{k}: {str(r.get(k,''))[:25]}" for k in show]
        lines.append("• " + " | ".join(parts))
    if len(clean) > 10:
        lines.append(f"_...and {len(clean)-10} more_")
    return "\n".join(lines)


async def execute_read(org_id: str, intent: str, parameters: dict) -> str:
    """Execute a read request — LLM generates SQL, we validate and run."""
    try:
        result   = await _gen_sql(intent, parameters)
        sql      = result["sql"]
        lp       = result.get("params", {})

        ok, reason = _safe(sql)
        if not ok:
            print(f"[QUERY_ENGINE] Blocked: {reason}\nSQL: {sql}")
            return "🤔 Couldn't process that query. Please rephrase."

        params = _build_params(sql, lp, org_id)
        rows   = [dict(r) for r in await fetch_all(sql, *params)]
        return _fmt(rows)

    except Exception as e:
        print(f"[QUERY_ENGINE] Error: {e}")
        return "🤔 Something went wrong. Try rephrasing your query."
