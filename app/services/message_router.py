"""
LLM message router — no keyword lists or regex routing.
Loads action workflows from DB; everything else defaults to read agent.
"""
import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv
from app.db import fetch_all

load_dotenv()
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_workflow_cache: dict[str, list[dict]] = {}


async def _load_action_workflows(org_id: str) -> list[dict]:
    if org_id in _workflow_cache:
        return _workflow_cache[org_id]
    rows = await fetch_all("""
        SELECT intent_key, name, description, adapter_method, entity_schema,
               workflow_type, sql_template, sql_params_order, response_format,
               otp_required, otp_threshold, approval_threshold
        FROM workflows
        WHERE org_id = $1 AND is_active = true AND workflow_type = 'action'
        ORDER BY name
    """, org_id)
    _workflow_cache[org_id] = [dict(r) for r in rows]
    return _workflow_cache[org_id]


def invalidate_router_cache(org_id: str = None):
    if org_id:
        _workflow_cache.pop(org_id, None)
    else:
        _workflow_cache.clear()


def _workflow_catalog(workflows: list[dict]) -> str:
    if not workflows:
        return "(No action workflows registered — all messages are data reads.)"
    lines = []
    for w in workflows:
        desc = w.get("description") or w.get("name") or ""
        lines.append(f"- {w['intent_key']}: {w['name']} — {desc}")
    return "\n".join(lines)


async def route_message(
    text: str,
    org_id: str,
    org_name: str,
    user_role: str,
) -> dict:
    """
    Single LLM call to classify message.
    Returns standard analysis dict for webhook / executor.
    """
    workflows = await _load_action_workflows(org_id)
    catalog = _workflow_catalog(workflows)

    prompt = f"""You route WhatsApp messages for a business ERP assistant.

ORGANISATION: {org_name}
USER ROLE: {user_role}
USER MESSAGE: "{text}"

REGISTERED ACTION WORKFLOWS (mutations / side-effects only):
{catalog}

Return ONLY JSON:
{{
  "route_type": "general_read|workflow|identity|capabilities|system|clarify|unknown",
  "intent": "short English description of what the user wants",
  "workflow_key": null or one intent_key from ACTION WORKFLOWS above,
  "parameters": {{}},
  "system_intent": null or "clear_sessions|manage_schedule",
  "clarification_question": null or a question if route_type is clarify,
  "confidence": 0.0 to 1.0
}}

ROUTING RULES:
- DEFAULT: Any question about data, reports, lists, totals, sorting, comparisons → general_read
- Greetings (hi, hello), help, what can I ask, menu → capabilities
- Who am I, my role, my name → identity
- User wants to CREATE/SEND/UPDATE something matching an action workflow → workflow + workflow_key
- Owner admin: emergency lockdown / clear all sessions → system, system_intent clear_sessions
- Owner admin: schedule/stop/reschedule automated reports → system, system_intent manage_schedule
- Truly ambiguous → clarify with one question
- Random chitchat unrelated to business → unknown
- NEVER use workflow for data lookups (dues, stock, top N, invoices list, credit limit, etc.)"""

    resp = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=400,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.choices[0].message.content.strip()
    if "```" in raw:
        start, end = raw.find("{"), raw.rfind("}") + 1
        raw = raw[start:end] if start >= 0 else raw

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {
            "route_type": "general_read",
            "intent": text,
            "workflow_key": None,
            "parameters": {},
            "confidence": 0.5,
        }

    route = parsed.get("route_type", "general_read")
    wk = parsed.get("workflow_key")

    # Attach full workflow record when action matched
    workflow = None
    if route == "workflow" and wk:
        workflow = next((w for w in workflows if w["intent_key"] == wk), None)
        if not workflow:
            parsed["route_type"] = "general_read"
            parsed["workflow_key"] = None
        else:
            parsed["workflow"] = workflow
            parsed["action"] = "Execute"

    if route == "system":
        parsed["intent"] = parsed.get("system_intent") or parsed.get("intent", "")
        parsed["route_type"] = "system"
    elif route in ("general_read", "identity", "capabilities"):
        parsed["action"] = "Read"
    elif route == "workflow" and workflow:
        parsed["action"] = "Execute"
    else:
        parsed.setdefault("action", "Read")

    parsed["tier"] = 3
    parsed.setdefault("parameters", {})
    parsed.setdefault("confidence", 0.8)
    return parsed
