"""
Intent Analyzer — replaces tier3 intent_key + entity extraction.
Returns route_type, action, intent description, workflow_key, parameters.
"""
import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv
from app.db import fetch_all

load_dotenv()
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Compact schema passed to LLM (not full DDL)
DB_SCHEMA_SUMMARY = """
TABLES (all rows MUST filter by org_id):

customers(id, org_id, name, phone, email, gst_number, city, credit_limit)
inventory(id, org_id, sku, name, qty, location, reorder_level, unit_price)
invoices(id, org_id, invoice_number, customer_id, items jsonb, amount, status, due_date, paid_at)
  -- status values: draft, pending, overdue, paid, approved
orders(id, org_id, order_number, customer_id, customer_name, description, metal_type,
       estimated_amount, advance_paid, expected_delivery)
  -- status values: confirmed, in_production, quality_check, ready, delivered
metal_rates(id, org_id, metal_type, rate_per_gram, making_charge_pct)
quotations(id, org_id, quotation_number, customer_name, metal_type, weight_grams,
           design_code, total_amount, status)
roles(id, org_id, name, permissions text[])
users(id, org_id, name, phone, email, role_id, is_active)
"""

READ_EXAMPLES = """
GENERAL READ examples (route_type = general_read, action = Read):
- "top 3 customers by pending dues"
- "Mehta ka kitna baaki hai" / "dues Mehta" → customer outstanding from invoices
- "stock of gold ring" / "gold ring ka stock" → inventory lookup
- "show all metal rates" / "current gold rate" → read metal_rates
- "which items are low on stock" → inventory where qty <= reorder_level
- "list active orders" → orders where status != 'delivered'
- "Sharma credit limit" → customers.credit_limit
- "all overdue customers" / "top 3 dues customer wise" → aggregate invoices
- "pending invoices for Mehta" → invoices for specific customer
- "show all customers" / "list all products"

IDENTITY examples (route_type = identity, action = Read):
- "who am I" / "mera role kya hai" → parameters: {"identity_type": "role"}
- "my role" / "what is my role"   → parameters: {"identity_type": "role"}
- "my permissions" / "what can I do" / "mujhe kya karna hai"
                                   → parameters: {"identity_type": "permissions"}
- "my access" / "what do I have access to"
                                   → parameters: {"identity_type": "permissions"}
- "who are all the users"          → route_type: general_read (about all users, not current user)

WORKFLOW examples (route_type = workflow — only for Create/Update/PDF actions):
- "create invoice for Mehta 45000"      → workflow_key: create_invoice
- "invoice Mehta 25000"                 → workflow_key: create_invoice
- "send dues statement for Mehta"       → workflow_key: send_dues_statement
- "generate quote for Kapoor 22kt 15g"  → workflow_key: create_quotation
- "quote Mehta 22kt 15.5g"             → workflow_key: create_quotation
- "update order ORD-1001 to delivered"  → workflow_key: update_order_status
- "set gold rate to 6500"               → workflow_key: set_metal_rate
- "new order Mehta 22kt gold ring"      → workflow_key: create_order
"""


async def _load_workflow_catalog(org_id: str) -> list[dict]:
    rows = await fetch_all("""
        SELECT intent_key, name, description, adapter_method, steps
        FROM workflows
        WHERE org_id = $1 AND is_active = true
          AND intent_key != 'weekly_dues_report'
        ORDER BY name
    """, org_id)
    return [dict(r) for r in rows]


def _format_workflow_catalog(workflows: list[dict]) -> str:
    if not workflows:
        return "(No registered workflows — only general_read available for data queries)"
    lines = []
    for w in workflows:
        steps = w.get("steps") or []
        step_text = ""
        if steps:
            step_text = "\n  Steps: " + "; ".join(
                s if isinstance(s, str) else str(s) for s in steps
            )
        lines.append(
            f"- {w['intent_key']}: {w['name']}\n"
            f"  {w.get('description') or ''}\n"
            f"  adapter: {w.get('adapter_method')}{step_text}"
        )
    return "\n".join(lines)


async def analyze_intent(
    text: str,
    org_id: str,
    org_name: str,
    user_role: str,
) -> dict:
    """
    Main Intent Analyzer. Returns normalized routing decision.
    """
    workflows = await _load_workflow_catalog(org_id)
    catalog = _format_workflow_catalog(workflows)
    valid_wf = [w["intent_key"] for w in workflows]

    prompt = f"""You are an Intent Analyzer for {org_name} (a jewellery business using WhatsApp ERP).

USER MESSAGE: "{text}"
USER ROLE: {user_role}

DATABASE SCHEMA:
{DB_SCHEMA_SUMMARY}

REGISTERED WORKFLOWS (use ONLY for actions that modify data, generate PDFs, or execute business logic):
{catalog}

{READ_EXAMPLES}

ROUTING RULES:
1. route_type must be one of: "general_read" | "workflow" | "identity" | "clarify" | "unknown"
2. action must be one of: "Read" | "Create" | "Update" | "Delete" | "Execute"
3. general_read = any SELECT query that reads existing data (no PDF, no creation)
4. workflow = PDF generation, invoice creation, quotation, order create/update, rate change
5. identity = questions about the CURRENT user's role or permissions (not all users)
6. clarify = query is too ambiguous to proceed — ask ONE specific clarifying question
7. NEVER route "top N", "all", "summary", "report" queries to a single-customer workflow
8. Hindi/Hinglish: understand meaning correctly before routing
9. workflow_key must be null for general_read/identity
10. workflow_key must be one of: {json.dumps(valid_wf)} for workflow route

PARAMETER EXTRACTION:
Extract all relevant params from the message:
- customer_name: customer name from message
- product_name: product/item name
- amount: numeric amount (₹ values)
- invoice_number: INV-xxx format
- order_number: ORD-xxx format
- quotation_number: QUO-xxx format
- limit: top N limit
- status: order/invoice status
- metal_type: 22kt, 18kt, silver etc.
- weight_grams: weight in grams
- rate: price value
- identity_type: "role" or "permissions" (for identity route only)

Return ONLY valid JSON:
{{
  "route_type": "general_read|workflow|identity|clarify|unknown",
  "action": "Read|Create|Update|Delete|Execute",
  "intent": "Clear English description of what to fetch or do",
  "workflow_key": null or "intent_key",
  "parameters": {{}},
  "clarification_question": null or "question string",
  "confidence": 0.0,
  "tier": 3
}}"""

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=600,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content.strip()
    if "```" in raw:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        raw = raw[start:end] if start >= 0 else raw

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "route_type": "unknown",
            "action": "Read",
            "intent": text,
            "workflow_key": None,
            "parameters": {},
            "clarification_question": None,
            "confidence": 0.0,
            "tier": 3,
        }

    # Validate workflow_key
    wk = parsed.get("workflow_key")
    if parsed.get("route_type") == "workflow":
        if wk not in valid_wf:
            if parsed.get("action") == "Read":
                parsed["route_type"] = "general_read"
                parsed["workflow_key"] = None
            else:
                parsed["route_type"] = "unknown"
                parsed["workflow_key"] = None

    parsed["tier"] = 3
    return parsed
