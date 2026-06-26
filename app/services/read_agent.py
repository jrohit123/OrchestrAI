"""
Unified read agent — one LLM loop with DB tools (search_customers + run_query).
No hardcoded domain keywords; schema and samples from live database.
"""
import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

from app.services.schema_service import get_schema_text, get_sample_context, get_allowed_tables
from app.services.sql_runner import run_select
from app.services.customer_resolver import search_customers, format_disambiguation_prompt

load_dotenv()
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_customers",
            "description": "Search customers by partial name before filtering invoices/dues/credit queries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_term": {"type": "string"},
                },
                "required": ["search_term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_query",
            "description": (
                "Execute read-only PostgreSQL SELECT. $1 = org_id (auto-injected). "
                "Use $2,$3,... for other bind values. Always filter org_id = $1."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "params": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Values for $2 onward only",
                    },
                },
                "required": ["sql", "params"],
            },
        },
    },
]


def _system_prompt(user: dict, schema: str, sample_ctx: str) -> str:
    perms = user.get("permissions") or []
    return f"""You are OrchestrAI — WhatsApp data assistant for {user.get('org_name', 'the business')}.

USER: {user.get('user_name')} | ROLE: {user.get('role')}
PERMISSIONS: {', '.join(perms[:15])}

{schema}

LIVE DATA SAMPLES:
{sample_ctx or '(none)'}

INSTRUCTIONS:
1. Answer data questions with run_query — infer joins and filters from schema.
2. Use search_customers when a person/company name may match multiple customers.
3. If search returns multiple customers and the user did not specify one exactly, ask which they mean (numbered list). Accept number, full name, or all matches on follow-up.
4. Greetings / help: suggest 4-5 example questions from schema + samples (reads only).
5. Identity questions: use user info above.
6. WhatsApp format: *bold*, bullets, ₹ amounts. Match English/Hinglish tone.
7. Never invent numbers — always query first.
8. pricing rows: quotation_number IS NULL = metal rates; NOT NULL = quotations."""


def _message_names_exact_match(message: str, matches: list[dict]) -> bool:
    ml = message.lower()
    return any(c["name"].lower() in ml for c in matches)


async def _execute_tool(org_id: str, name: str, args: dict, allowed_tables: set[str]) -> str:
    if name == "search_customers":
        term = args.get("search_term", "").strip()
        matches = await search_customers(org_id, term)
        return json.dumps({
            "search_term": term,
            "count": len(matches),
            "customers": [
                {"name": m["name"], "city": m.get("city"), "credit_limit": str(m.get("credit_limit", ""))}
                for m in matches
            ],
        }, default=str)

    if name == "run_query":
        result = await run_select(org_id, args["sql"], args.get("params") or [], allowed_tables)
        return json.dumps(result, default=str)

    return json.dumps({"error": f"Unknown tool {name}"})


async def run_read_agent(
    user: dict,
    message: str,
    extra_context: str = "",
    max_turns: int = 10,
) -> str:
    org_id = user["org_id"]
    role = user.get("role", "owner")
    perms = user.get("permissions") or []
    allowed = await get_allowed_tables(role, perms)
    schema = await get_schema_text(role, perms)
    samples = await get_sample_context(org_id, role, perms)

    system = _system_prompt(user, schema, samples)
    if extra_context:
        system += f"\n\nCONTEXT:\n{extra_context}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": message},
    ]

    for _ in range(max_turns):
        resp = await _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=1200,
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            messages.append(msg)
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                tool_result = await _execute_tool(org_id, tc.function.name, args, allowed)

                if tc.function.name == "search_customers":
                    parsed = json.loads(tool_result)
                    if parsed["count"] > 1 and not _message_names_exact_match(message, parsed.get("customers", [])):
                        matches = await search_customers(org_id, args.get("search_term", ""))
                        return json.dumps({
                            "_disambiguation": True,
                            "hint": args.get("search_term", ""),
                            "matches": matches,
                            "message": format_disambiguation_prompt(
                                args.get("search_term", ""), matches
                            ),
                        })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })
            continue

        if msg.content:
            return msg.content.strip()

    return "🤔 I couldn't complete that query. Please try rephrasing."


async def handle_read(
    user: dict,
    raw_text: str,
    intent: str = "",
    parameters: dict | None = None,
) -> dict:
    query = raw_text.strip()
    if intent and intent != query:
        query = f"{raw_text}\n(Intent: {intent})"

    extra = ""
    if parameters:
        if parameters.get("customer_name"):
            extra += f"Customer filter: {parameters['customer_name']}\n"
        if parameters.get("customer_id"):
            extra += f"Customer ID: {parameters['customer_id']}\n"
        if parameters.get("customer_names"):
            extra += f"Customers: {', '.join(parameters['customer_names'])}\n"

    result = await run_read_agent(user, query, extra_context=extra)

    if result.startswith("{") and "_disambiguation" in result:
        try:
            payload = json.loads(result)
            if payload.get("_disambiguation"):
                return {
                    "status": "disambiguation",
                    "message": payload["message"],
                    "pending": {
                        "raw_text": raw_text,
                        "intent": intent or raw_text,
                        "parameters": parameters or {},
                        "customer_hint": payload["hint"],
                        "matches": payload["matches"],
                    },
                }
        except json.JSONDecodeError:
            pass

    return {"status": "reply", "message": result}


async def handle_read_disambiguation_reply(user: dict, text: str, pending: dict) -> dict:
    """LLM interprets user's pick — no keyword lists."""
    matches = pending.get("matches", [])
    match_lines = "\n".join(
        f"  {i + 1}. {m['name']} ({m.get('city', '')})" for i, m in enumerate(matches)
    )
    ctx = f"""DISAMBIGUATION — answer the original question for the customer's choice.

Original question: {pending.get('raw_text', '')}
Search matches:
{match_lines}

User's reply (interpret as: a number, a full customer name, or all matching customers): "{text}"

Resolve their choice, then use run_query to answer the original question."""

    message = await run_read_agent(user, pending.get("raw_text", text), extra_context=ctx)
    return {"status": "reply", "message": message}


async def handle_greet_or_capabilities(user: dict, ttl_str: str = "") -> str:
    suffix = f" Session note: active for {ttl_str}." if ttl_str else ""
    return await run_read_agent(
        user,
        f"The user wants a greeting and to know what data questions they can ask.{suffix}",
    )


async def handle_identity(user: dict, ask_permissions: bool = False) -> str:
    q = "What are my permissions and what data can I query?" if ask_permissions else "Who am I?"
    return await run_read_agent(user, q)
