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

# Compact schema summary passed to LLM (not full DDL)
DB_SCHEMA_SUMMARY = """
TABLES (all rows MUST filter by org_id):

customers(id, org_id, name, phone, email, gst_number, city, credit_limit)
inventory(id, org_id, sku, name, qty, location, reorder_level, unit_price)
invoices(id, org_id, invoice_number, customer_id, items jsonb, amount, status, due_date, paid_at)
  -- status values: draft, pending, overdue, paid, approved
orders(id, org_id, order_number, customer_id, customer_name, description, metal_type,
       estimated_amount, advance_paid, status, expected_delivery)
  -- status values: confirmed, in_production, quality_check, ready, delivered
metal_rates(id, org_id, metal_type, rate_per_gram, making_charge_pct)
quotations(id, org_id, quotation_number, customer_name, metal_type, weight_grams,
           design_code, total_amount, status)
"""

READ_EXAMPLES = """
GENERAL READ examples (route_type = general_read, action = Read):
- "top 3 customers by pending dues" → aggregate invoices (pending+overdue) by customer, sort desc, limit 3
- "Mehta ka kitna baaki hai" → single customer outstanding from invoices
- "stock of gold ring" → inventory lookup by product name
- "show all metal rates" → read metal_rates table
- "which items are low on stock" → inventory where qty <= reorder_level
- "list active orders" → orders where status NOT IN ('delivered')
- "Sharma credit limit" → customers.credit_limit for Sharma
- "what all roles do we have" → read roles table
- "show all users" → read users table

IDENTITY examples (route_type = identity, action = Read):
- "who am I" → get current user's role, parameters: {"identity_type": "role"}
- "my role" → get current user's role, parameters: {"identity_type": "role"}
- "what is my role" → get current user's role, parameters: {"identity_type": "role"}
- "my permissions" → get current user's permissions, parameters: {"identity_type": "permissions"}
- "what can I do" → get current user's permissions, parameters: {"identity_type": "permissions"}
- "my access" → get current user's permissions, parameters: {"identity_type": "permissions"}

WORKFLOW examples (route_type = workflow):
- "create invoice for Mehta 45000" → workflow_key: create_invoice
- "send dues statement for Mehta" → workflow_key: send_dues_statement
- "generate quote for Kapoor 22kt 15g" → workflow_key: create_quotation
- "update order ORD-1101 to delivered" → workflow_key: update_order_status
- "set gold rate to 6500" → workflow_key: set_metal_rate
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
    valid_workflow_keys = [w["intent_key"] for w in workflows]

    prompt = f"""Act as an Intent Analyzer for {org_name} (jewellery ERP on WhatsApp).

USER MESSAGE: "{text}"
USER ROLE: {user_role}

{DB_SCHEMA_SUMMARY}

REGISTERED WORKFLOWS (use ONLY for Create/Update/Delete/PDF/Execute — NOT for simple lookups):
{catalog}

{READ_EXAMPLES}

RULES:
1. Separate Intent (what user wants) from Action (what system does).
2. action must be one of: Read, Create, Update, Delete, Execute
3. If the query can be answered by reading database tables → route_type = "general_read"
4. If the query asks about the current user (who am I, my role, my permissions) → route_type = "identity"
5. If the query needs PDF generation, invoice creation, order mutation, rate update → route_type = "workflow"
6. NEVER route aggregate/report/top-N/dues-summary queries to a single-customer workflow
7. Hindi/Hinglish queries: understand meaning, respond with same routing logic
8. If critical info is missing AND query cannot proceed → route_type = "clarify" with clarification_question
9. workflow_key must be null for general_read/identity; must be one of {json.dumps(valid_workflow_keys)} for workflow
10. parameters: extract all entities (customer_name, product_name, invoice_number, amount, qty, order_number, status, metal_type, weight_grams, design_code, limit)

Return ONLY valid JSON:
{{
  "route_type": "general_read" | "workflow" | "identity" | "clarify" | "unknown",
  "action": "Read" | "Create" | "Update" | "Delete" | "Execute",
  "intent": "Plain English description of what to fetch or do",
  "workflow_key": null or "intent_key_string",
  "parameters": {{}},
  "clarification_question": null or "question to ask user",
  "confidence": 0.0
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
    if parsed.get("route_type") == "workflow" and wk not in valid_workflow_keys:
        # Fallback: treat as general_read if LLM picked invalid workflow
        if parsed.get("action") == "Read":
            parsed["route_type"] = "general_read"
            parsed["workflow_key"] = None
        else:
            parsed["route_type"] = "unknown"
            parsed["workflow_key"] = None

    parsed["tier"] = 3
    return parsed
