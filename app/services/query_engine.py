"""
Dynamic SQL Query Engine.
Mode A: Template execution — uses workflow's sql_template directly (fast, deterministic)
Mode B: Unconstrained generation — LLM generates SQL for fallback queries
"""
import os
import re
import json
from openai import AsyncOpenAI
from dotenv import load_dotenv
from app.db import fetch_all

load_dotenv()
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

_DB_SCHEMA: str | None = None
_VALID_COLUMNS: dict | None = None


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
    lines = [f"- {t}: {', '.join(cs)}" for t, cs in sorted(table_cols.items())]
    _DB_SCHEMA = "TABLES:\n" + "\n".join(lines)


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


def _build_template_params(org_id: str, entities: dict, params_order: list,
                            entity_schema: dict, user_id: str = None) -> list:
    """
    Build positional params for sql_template execution.
    $1 = org_id (or user_id if session_context=true), $2..$N = entities in params_order sequence.
    """
    # Check if workflow uses session context (user_id instead of org_id)
    session_context = entity_schema.get("session_context", False)
    params = [user_id if session_context and user_id else org_id]

    for field in params_order:
        val = entities.get(field)
        if val is None:
            # Use default from entity_schema if present
            schema = entity_schema.get(field, {})
            val = schema.get("default")
            if val is None:
                val = 20 if schema.get("type") == "integer" else ""
        params.append(val)
    return params


async def _gen_sql_unconstrained(intent: str, parameters: dict) -> dict:
    """
    Fallback: LLM generates SQL for queries that didn't match any workflow.
    No domain examples — fully generic.
    """
    await _load_schema()

    prompt = f"""Generate a safe PostgreSQL SELECT query.

REQUEST: {intent}
PARAMETERS: {json.dumps(parameters)}

SCHEMA:
{_DB_SCHEMA}

RULES:
- SELECT only
- WHERE org_id = $1 always first
- Use $2, $3... for additional values
- ILIKE with wildcards for text
- LIMIT 20 default
- Return ONLY JSON: {{"sql": "...", "params_ordered": []}}
  params_ordered = values for $2, $3... in order (NOT $1)
  For ILIKE: include % in value: "%Mehta%"
  For LIMIT: integer value"""

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


async def execute_template(
    org_id: str,
    sql_template: str,
    entities: dict,
    params_order: list,
    entity_schema: dict,
    response_format: str = "generic",
    user_id: str = None
) -> str:
    """
    Mode A: Execute a workflow's stored sql_template.
    Fast and deterministic — no LLM call needed.
    """
    try:
        ok, reason = _safe(sql_template)
        if not ok:
            return f"🤔 Query configuration error. Contact admin. ({reason})"

        params = _build_template_params(org_id, entities, params_order, entity_schema, user_id)
        rows   = [dict(r) for r in await fetch_all(sql_template, *params)]
        return _fmt(rows, response_format)

    except Exception as e:
        print(f"[QUERY_ENGINE] Template execution error: {e}")
        return "🤔 Something went wrong running that query."


async def execute_read(
    org_id: str,
    intent: str,
    parameters: dict,
    response_format: str = "generic"
) -> str:
    """
    Mode B: Unconstrained LLM-generated SQL for fallback queries.
    Only reached when no workflow matches.
    """
    try:
        result        = await _gen_sql_unconstrained(intent, parameters)
        sql           = result["sql"]
        params_ordered = result.get("params_ordered", [])

        ok, reason = _safe(sql)
        if not ok:
            return "🤔 Couldn't process that query safely. Please rephrase."

        params = [org_id] + list(params_ordered)
        rows   = [dict(r) for r in await fetch_all(sql, *params)]
        return _fmt(rows, response_format)

    except Exception as e:
        print(f"[QUERY_ENGINE] Unconstrained error: {e}")
        return "🤔 Something went wrong. Try rephrasing your query."


def _fmt(rows: list, response_format: str = "generic") -> str:
    """Format rows for WhatsApp using the workflow's response_format hint."""
    if not rows:
        return "✅ No results found."

    def is_uuid(v):
        return isinstance(v, str) and len(v) > 30 and "-" in v

    clean = []
    for r in rows:
        row = {k: v for k, v in r.items()
               if k.lower() not in SENSITIVE_COLS and not is_uuid(v)}
        if row:
            clean.append(row)
    if not clean:
        return "✅ No displayable results."

    # Dispatch by response_format hint from workflow
    if response_format == "outstanding_summary" or "total_outstanding" in clean[0] or "total" in clean[0]:
        return _fmt_outstanding(clean)
    if response_format == "inventory" or ("qty" in clean[0] and "name" in clean[0]):
        return _fmt_inventory(clean)
    if response_format == "orders" or "order_number" in clean[0]:
        return _fmt_orders(clean)
    if response_format == "customers" or ("city" in clean[0] and "name" in clean[0] and "qty" not in clean[0]):
        return _fmt_customers(clean)
    if response_format == "roles" or ("role" in clean[0] and "permissions" in clean[0]):
        return _fmt_roles(clean)
    if response_format == "metal_rates" or ("metal_type" in clean[0] and "rate_per_gram" in clean[0]):
        return _fmt_metal_rates(clean)
    if response_format == "invoices" or "invoice_number" in clean[0]:
        return _fmt_invoices(clean)
    return _fmt_generic(clean)


def _fmt_outstanding(clean):
    tkey = next((k for k in ("total_outstanding","total_overdue","total") if k in clean[0]), None)
    lines = ["💰 *Outstanding Summary*"]
    for r in clean[:15]:
        name  = r.get("name") or r.get("customer_name","?")
        total = float(r.get(tkey, 0) or 0) if tkey else 0
        city  = f" ({r['city']})" if r.get("city") else ""
        oldest = f" | Due: {r['oldest_due_date']}" if r.get("oldest_due_date") else ""
        count  = f" [{r['invoice_count']} inv]" if r.get("invoice_count") else ""
        lines.append(f"• *{name}*{city}: ₹{total:,.0f}{count}{oldest}")
    if len(clean) > 15:
        lines.append(f"_...and {len(clean)-15} more_")
    return "\n".join(lines)

def _fmt_inventory(clean):
    lines = ["📦 *Stock / Inventory*"]
    for r in clean[:15]:
        qty      = r.get("qty", 0)
        reorder  = r.get("reorder_level", 0)
        warn     = " ⚠️ LOW" if reorder and qty <= reorder else ""
        loc      = f" @ {r['location']}" if r.get("location") else ""
        price    = f" ₹{float(r['unit_price']):,.0f}" if r.get("unit_price") else ""
        lines.append(f"• *{r.get('name','?')}*: {qty} pcs{loc}{price}{warn}")
    if len(clean) > 15:
        lines.append(f"_...and {len(clean)-15} more_")
    return "\n".join(lines)

def _fmt_orders(clean):
    STATUS_EMOJI = {"confirmed":"🟡","in_production":"🔨","quality_check":"🔍","ready":"✅","delivered":"📦"}
    lines = ["📋 *Orders*"]
    for r in clean[:10]:
        emoji = STATUS_EMOJI.get(r.get("status",""), "❓")
        cust  = r.get("customer_name") or r.get("name","?")
        desc  = str(r.get("description",""))[:35]
        dlv   = f" | {r['expected_delivery']}" if r.get("expected_delivery") else ""
        lines.append(f"• {emoji} *{r.get('order_number','?')}* — {cust}\n  {desc}{dlv}")
    if len(clean) > 10:
        lines.append(f"_...and {len(clean)-10} more_")
    return "\n".join(lines)

def _fmt_customers(clean):
    lines = ["� *Customers*"]
    for r in clean[:15]:
        city   = f" ({r['city']})" if r.get("city") else ""
        credit = f" | Limit: ₹{float(r['credit_limit']):,.0f}" if r.get("credit_limit") else ""
        lines.append(f"• *{r.get('name','?')}*{city}{credit}")
    if len(clean) > 15:
        lines.append(f"_...and {len(clean)-15} more_")
    return "\n".join(lines)

def _fmt_metal_rates(clean):
    lines = ["💎 *Metal Rates*"]
    for r in clean:
        rate   = float(r.get("rate_per_gram",0))
        making = r.get("making_charge_pct","—")
        upd    = str(r.get("updated_at",""))[:10]
        lines.append(f"• *{r['metal_type']}*: ₹{rate:,.0f}/g | Making: {making}% | {upd}")
    return "\n".join(lines)

def _fmt_roles(clean):
    lines = ["👤 *Your Role & Permissions*"]
    for r in clean:
        role = r.get("role", "?")
        perms = r.get("permissions", [])
        if isinstance(perms, list):
            # Show first 8 permissions, then count
            shown = perms[:8]
            remaining = len(perms) - 8
            perm_lines = "\n".join(f"  • {p}" for p in shown)
            if remaining > 0:
                perm_lines += f"\n  _...and {remaining} more_"
        else:
            perm_lines = f"  {str(perms)[:100]}"
        lines.append(f"• *Role*: {role}\n{perm_lines}")
    return "\n".join(lines)

def _fmt_invoices(clean):
    lines = ["🧾 *Invoices*"]
    for r in clean[:10]:
        amt  = float(r.get("amount",0))
        due  = f" | Due: {r['due_date']}" if r.get("due_date") else ""
        lines.append(f"• *{r.get('invoice_number','?')}*: ₹{amt:,.0f} | {r.get('status','—').upper()}{due}")
    if len(clean) > 10:
        lines.append(f"_...and {len(clean)-10} more_")
    return "\n".join(lines)

def _fmt_generic(clean):
    cols  = list(clean[0].keys())[:4]
    lines = [f"📊 *Results* ({len(clean)} rows)"]
    for r in clean[:10]:
        parts = [f"{k}: {str(r.get(k,''))[:30]}" for k in cols if r.get(k) is not None]
        lines.append("• " + " | ".join(parts))
    if len(clean) > 10:
        lines.append(f"_...and {len(clean)-10} more_")
    return "\n".join(lines)
