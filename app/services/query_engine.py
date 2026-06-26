"""
Safe Read Query Engine — executes general_read requests.
LLM produces a query PLAN (not raw SQL). Engine maps plans to parameterized SQL.
"""
import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv
from app.db import fetch_all, fetch_one

load_dotenv()
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Allowlisted query templates — LLM picks template + fills params
QUERY_TEMPLATES = {
    "customer_outstanding": {
        "description": "Outstanding invoices for ONE customer by name",
        "sql": """
            SELECT c.name, c.city, i.invoice_number, i.amount, i.status, i.due_date
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.org_id = $1 AND c.org_id = $1
              AND i.status IN ('pending', 'overdue')
              AND c.name ILIKE $2
            ORDER BY i.due_date ASC
        """,
        "params": ["org_id", "customer_name"],
    },
    "top_customers_by_dues": {
        "description": "Aggregate pending+overdue by customer, sorted by total desc",
        "sql": """
            SELECT c.name, c.city,
                   SUM(i.amount) AS total_dues,
                   COUNT(i.id) AS invoice_count,
                   MIN(i.due_date) AS oldest_due
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.org_id = $1 AND i.status IN ('pending', 'overdue')
            GROUP BY c.id, c.name, c.city
            ORDER BY total_dues DESC
            LIMIT $2
        """,
        "params": ["org_id", "limit"],
    },
    "all_overdue_customers": {
        "description": "Customers with overdue invoices only",
        "sql": """
            SELECT c.name, c.city,
                   SUM(i.amount) AS total_overdue,
                   COUNT(i.id) AS invoice_count
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.org_id = $1 AND i.status = 'overdue'
            GROUP BY c.id, c.name, c.city
            ORDER BY total_overdue DESC
            LIMIT $2
        """,
        "params": ["org_id", "limit"],
    },
    "product_stock": {
        "description": "Stock for a product by fuzzy name",
        "sql": """
            SELECT name, qty, location, reorder_level, unit_price
            FROM inventory
            WHERE org_id = $1 AND (
                similarity(name, $2) > 0.3
                OR LOWER(name) LIKE $3
            )
            ORDER BY similarity(name, $2) DESC
            LIMIT 3
        """,
        "params": ["org_id", "product_name", "product_like"],
    },
    "low_stock_items": {
        "description": "Items at or below reorder level",
        "sql": """
            SELECT name, qty, reorder_level, location
            FROM inventory
            WHERE org_id = $1 AND qty <= reorder_level
            ORDER BY qty ASC
        """,
        "params": ["org_id"],
    },
    "metal_rates": {
        "description": "All current metal rates",
        "sql": """
            SELECT metal_type, rate_per_gram, making_charge_pct
            FROM metal_rates WHERE org_id = $1 ORDER BY metal_type
        """,
        "params": ["org_id"],
    },
    "customer_credit_limit": {
        "description": "Credit limit for one customer",
        "sql": """
            SELECT name, city, credit_limit
            FROM customers
            WHERE org_id = $1 AND name ILIKE $2
            ORDER BY similarity(name, $3) DESC LIMIT 3
        """,
        "params": ["org_id", "customer_name", "customer_name_exact"],
    },
    "active_orders": {
        "description": "Orders not yet delivered",
        "sql": """
            SELECT order_number, customer_name, description, status, estimated_amount
            FROM orders
            WHERE org_id = $1 AND status != 'delivered'
            ORDER BY created_at DESC
            LIMIT $2
        """,
        "params": ["org_id", "limit"],
    },
    "invoice_lookup": {
        "description": "Find invoice by number",
        "sql": """
            SELECT i.invoice_number, i.amount, i.status, i.due_date, c.name AS customer_name
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.org_id = $1 AND i.invoice_number ILIKE $2
        """,
        "params": ["org_id", "invoice_number"],
    },
}


async def _pick_template(intent: str, parameters: dict) -> dict:
    """LLM picks the best allowlisted template + fills params."""
    template_list = "\n".join(
        f"- {k}: {v['description']}" for k, v in QUERY_TEMPLATES.items()
    )
    prompt = f"""Pick the best query template for this intent.

INTENT: {intent}
PARAMETERS: {json.dumps(parameters)}

AVAILABLE TEMPLATES:
{template_list}

Return ONLY JSON:
{{"template": "template_key", "params": {{"limit": 3, "customer_name": "Mehta", ...}}}}

Rules:
- Default limit to 10 if not specified for list queries
- For "top N" queries set limit = N
- customer_name: partial match OK (e.g. "Mehta" matches "Mehta Jewellers")
- product_name: the product search term
"""

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=300,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.choices[0].message.content.strip()
    start, end = raw.find("{"), raw.rfind("}") + 1
    return json.loads(raw[start:end])


def _build_sql_args(template_key: str, org_id: str, params: dict) -> tuple[str, list]:
    tpl = QUERY_TEMPLATES[template_key]
    args = []
    for p in tpl["params"]:
        if p == "org_id":
            args.append(org_id)
        elif p == "limit":
            args.append(int(params.get("limit") or 10))
        elif p == "customer_name" or p == "customer_name_exact":
            name = params.get("customer_name") or params.get("customer") or ""
            args.append(f"%{name}%")
            if p == "customer_name_exact":
                args.append(name)
        elif p == "product_name":
            args.append(params.get("product_name") or params.get("product") or "")
        elif p == "product_like":
            name = params.get("product_name") or params.get("product") or ""
            args.append(f"%{name.lower()}%")
        elif p == "invoice_number":
            inv = params.get("invoice_number") or ""
            if not inv.upper().startswith("INV-"):
                inv = f"INV-{inv}" if inv.isdigit() else inv
            args.append(inv)
        else:
            args.append(params.get(p))
    return tpl["sql"], args


def _format_whatsapp(template_key: str, rows: list, params: dict) -> str:
    if not rows:
        return "✅ No matching records found."

    if template_key == "customer_outstanding":
        lines = []
        total = 0
        customer_name = rows[0]["name"]
        for r in rows:
            total += float(r["amount"])
            icon = "🔴" if r["status"] == "overdue" else "🟡"
            lines.append(f"{icon} {r['invoice_number']} — ₹{r['amount']:,.0f} ({r['status']})")
        return (
            f"💰 *{customer_name}* — Outstanding\n\n"
            + "\n".join(lines)
            + f"\n\n*Total: ₹{total:,.0f}*"
        )

    if template_key == "top_customers_by_dues":
        limit = params.get("limit")
        title = f"Top {limit} Customers by Dues" if limit else "Customers by Dues"
        lines = [
            f"{i+1}. *{r['name']}* ({r['city']}) — ₹{r['total_dues']:,.0f} ({r['invoice_count']} inv.)"
            for i, r in enumerate(rows)
        ]
        grand = sum(float(r["total_dues"]) for r in rows)
        return f"📊 *{title}*\n\n" + "\n".join(lines) + f"\n\n*Total shown: ₹{grand:,.0f}*"

    if template_key == "all_overdue_customers":
        lines = [
            f"• *{r['name']}* ({r['city']}) — ₹{r['total_overdue']:,.0f}"
            for r in rows
        ]
        return "📊 *Overdue Customers*\n\n" + "\n".join(lines)

    if template_key == "product_stock":
        r = rows[0]
        low = r["qty"] <= r["reorder_level"]
        warn = "\n⚠️ _Below reorder level!_" if low else ""
        return (
            f"📦 *{r['name']}*\n"
            f"Available: *{r['qty']} pcs*\n"
            f"Location: {r['location']}\n"
            f"Unit price: ₹{r['unit_price']:,.0f}{warn}"
        )

    if template_key == "low_stock_items":
        lines = [f"• *{r['name']}* — {r['qty']} pcs (reorder: {r['reorder_level']})" for r in rows]
        return "⚠️ *Low Stock Items*\n\n" + "\n".join(lines)

    if template_key == "metal_rates":
        lines = [f"• *{r['metal_type']}* — ₹{r['rate_per_gram']:,.0f}/g (making: {r['making_charge_pct']}%)" for r in rows]
        return "💰 *Metal Rates*\n\n" + "\n".join(lines)

    if template_key == "customer_credit_limit":
        if len(rows) > 1:
            opts = "\n".join(f"{i+1}. {r['name']} ({r['city']})" for i, r in enumerate(rows))
            return f"🔍 Multiple matches:\n{opts}\n\nReply with customer name."
        r = rows[0]
        cl = r["credit_limit"]
        return f"💳 *{r['name']}* — Credit Limit: ₹{cl:,.0f}" if cl else f"ℹ️ *{r['name']}* — no credit limit set"

    if template_key == "active_orders":
        lines = [
            f"• *{r['order_number']}* — {r['customer_name']}: {r['description']} [{r['status']}]"
            for r in rows
        ]
        return f"📋 *Active Orders* ({len(rows)})\n\n" + "\n".join(lines)

    if template_key == "invoice_lookup":
        r = rows[0]
        return (
            f"🧾 *{r['invoice_number']}*\n"
            f"Customer: {r['customer_name']}\n"
            f"Amount: ₹{r['amount']:,.0f}\n"
            f"Status: {r['status']}"
        )

    # Generic fallback
    return f"Found {len(rows)} record(s)."


async def execute_read(org_id: str, intent: str, parameters: dict) -> str:
    """Execute a general_read request. Returns WhatsApp-formatted message."""
    try:
        picked = await _pick_template(intent, parameters)
        template_key = picked["template"]
        if template_key not in QUERY_TEMPLATES:
            return "🤔 Could not determine how to fetch that data. Try rephrasing."

        sql, args = _build_sql_args(template_key, org_id, picked.get("params", parameters))
        rows = await fetch_all(sql, *args)
        rows = [dict(r) for r in rows]
        return _format_whatsapp(template_key, rows, picked.get("params", parameters))
    except Exception as e:
        print(f"[QUERY_ENGINE] Error: {e}")
        return f"⚠️ Could not run query: {str(e)}"
