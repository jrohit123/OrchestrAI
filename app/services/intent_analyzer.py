"""
Intent Analyzer — Tier 3 of the classifier.
Now delegates to intent_matcher.py for workflow matching.
Only falls back to unconstrained LLM for system-level routing
(identity, clarify, unknown) and truly open-ended queries.
"""
import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv
from app.services.intent_matcher import match_intent

load_dotenv()
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── Compact schema summary (used ONLY for fallback unconstrained queries) ────
# This is the ONLY schema reference remaining in the codebase.
# It has NO domain-specific terms, hints, or examples.
_FALLBACK_SCHEMA = """
Tables (always filter by org_id):
  customers: name, phone, email, city, credit_limit, gst_number
  inventory: name, qty, location, reorder_level, unit_price, sku
  invoices: invoice_number, customer_id, amount, status, due_date
    status: draft | pending | overdue | paid | approved
  orders: order_number, customer_name, description, metal_type, status
    status: confirmed | in_production | quality_check | ready | delivered
  pricing: metal_type, rate_per_gram, making_charge_pct (rates) or quotation_number, weight_grams, total_amount (quotations)
  users: name, phone, email, role_id, is_active
  roles: name, permissions[]
"""


async def analyze_intent(
    text: str,
    org_id: str,
    org_name: str,
    user_role: str,
) -> dict:
    """
    Tier 3 intent analysis.

    1. Try workflow matching via intent_matcher (zero/low LLM cost)
    2. If matched: return workflow route
    3. If not matched: LLM for identity/clarify/unknown + unconstrained reads
    """
    # ── Step 1: Try workflow matching ──────────────────────────────────────
    match = await match_intent(text, org_id, org_name, user_role)

    if match["matched"]:
        wf = match["workflow"]
        return {
            "route_type":   "workflow",
            "action":       "Read" if wf["workflow_type"] == "read" else "Execute",
            "intent":       wf.get("description", wf["name"]),
            "workflow_key": wf["intent_key"],
            "workflow":     wf,        # full workflow record for executor
            "parameters":   match["entities"],
            "confidence":   match["confidence"],
            "tier":         3,
            "match_method": match["method"],
        }

    # ── Step 2: Fallback LLM for system queries + open-ended reads ─────────
    prompt = f"""You are a message router for a WhatsApp ERP system.

USER MESSAGE: "{text}"
USER ROLE: {user_role}

DATABASE SCHEMA:
{_FALLBACK_SCHEMA}

ROUTING RULES:
1. "identity" — questions about the CURRENT user: who am I, my role, my permissions
2. "clarify"  — message is too vague to route safely (ask ONE clarifying question)
3. "general_read" — clear data question but no workflow matched (rare fallback)
4. "unknown"  — cannot determine intent

Return ONLY JSON:
{{
  "route_type": "identity|clarify|general_read|unknown",
  "action": "Read",
  "intent": "Clear English description of what to fetch",
  "workflow_key": null,
  "parameters": {{}},
  "clarification_question": null,
  "confidence": 0.0,
  "tier": 3
}}"""

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=300,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content.strip()
    if "```" in raw:
        start = raw.find("{"); end = raw.rfind("}") + 1
        raw = raw[start:end] if start >= 0 else raw

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"route_type": "unknown", "action": "Read", "intent": text,
                  "workflow_key": None, "parameters": {}, "confidence": 0.0}

    parsed["tier"] = 3
    return parsed
