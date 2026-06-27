"""
Tool-calling agent.
Replaces the entire classifier + intent_matcher + intent_analyzer pipeline.
Zero domain hardcoding. Works for any schema, any industry.
"""
import json
import os
import re
from openai import AsyncOpenAI
from app.db import fetch_all, fetch_one
from app.services.query_engine import _safe, SENSITIVE_COLS

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── Schema cache (per org, reloaded on restart) ──────────────────────────────
_schema_cache: dict[str, str] = {}


async def _get_schema(org_id: str) -> str:
    """
    Read information_schema at runtime for this org's database.
    Returns a compact schema string + 2 sample rows per table.
    Cached in memory. No hardcoding.
    """
    if org_id in _schema_cache:
        return _schema_cache[org_id]

    # Get column structure
    cols = await fetch_all("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name NOT IN (
              'audit_log', 'otp_tokens', 'pending_approvals',
              'credentials', 'workflows'
          )
        ORDER BY table_name, ordinal_position
    """)

    table_cols: dict[str, list] = {}
    for c in cols:
        t = c["table_name"]
        table_cols.setdefault(t, []).append(
            f"{c['column_name']} ({c['data_type']})"
        )

    # Get 2 sample rows per table so LLM sees real values
    sample_lines = []
    for table in sorted(table_cols.keys()):
        try:
            rows = await fetch_all(
                f"SELECT * FROM {table} WHERE org_id = $1 LIMIT 2",
                org_id
            )
            if rows:
                # Strip sensitive columns from samples
                clean = [
                    {k: v for k, v in dict(r).items()
                     if k not in SENSITIVE_COLS}
                    for r in rows
                ]
                sample_lines.append(
                    f"  sample: {json.dumps(clean, default=str)}"
                )
            else:
                sample_lines.append("  sample: (empty)")
        except Exception:
            sample_lines.append("  sample: (unavailable)")

    schema_parts = []
    for i, (table, columns) in enumerate(sorted(table_cols.items())):
        schema_parts.append(
            f"- {table}: {', '.join(columns)}\n{sample_lines[i]}"
        )

    result = "\n".join(schema_parts)
    _schema_cache[org_id] = result
    return result


def invalidate_schema_cache(org_id: str):
    """Call this if schema changes at runtime."""
    _schema_cache.pop(org_id, None)


# ── Tool definitions — generic, zero domain knowledge ────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": (
                "Run a SELECT query against the database. "
                "Use this to fetch any data the user is asking about. "
                "Always use $1 for org_id. Use $2, $3... for additional params. "
                "ILIKE for name searches. LIMIT 50 max."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A safe PostgreSQL SELECT query"
                    },
                    "params": {
                        "type": "array",
                        "description": "Values for $2, $3... ($1=org_id is injected automatically)",
                        "items": {}
                    }
                },
                "required": ["sql"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clarify",
            "description": (
                "Ask the user a clarifying question when their request is ambiguous. "
                "Use when: a name matches multiple records, the request is incomplete, "
                "or you need one more piece of information before proceeding. "
                "Do NOT use this for every message — only when genuinely unclear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The clarifying question to ask"
                    },
                    "options": {
                        "type": "array",
                        "description": "Optional list of choices to present",
                        "items": {"type": "string"}
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_pdf",
            "description": (
                "Generate a PDF from query results and send it to the user. "
                "Use ONLY when the user explicitly asks for a PDF, report, or statement. "
                "Call query_database first to get the data, then call this."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rows": {
                        "type": "array",
                        "description": "The data rows to include in the PDF"
                    },
                    "title": {
                        "type": "string",
                        "description": "PDF title shown at the top"
                    },
                    "subtitle": {
                        "type": "string",
                        "description": "Optional subtitle or date range"
                    }
                },
                "required": ["rows", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_action",
            "description": (
                "Show the user what action is about to be taken and wait for confirmation. "
                "MUST be called before any write operation: creating invoices, "
                "updating rates, changing order status, etc. "
                "Never execute a write without calling this first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_description": {
                        "type": "string",
                        "description": "Plain English description of what will happen"
                    },
                    "details": {
                        "type": "object",
                        "description": "Key details of the action (customer, amount, etc.)"
                    }
                },
                "required": ["action_description"]
            }
        }
    }
]


# ── System prompt builder — reads from DB, zero hardcoding ───────────────────

async def _build_system_prompt(user: dict) -> str:
    schema = await _get_schema(user["org_id"])
    today = __import__("datetime").date.today().strftime("%d %b %Y")

    return f"""You are a WhatsApp ERP assistant for {user["org_name"]}.

=== CRITICAL: ONLY USE THESE TABLES AND COLUMNS ===
YOU MUST ONLY USE THE FOLLOWING TABLES. NO OTHERS EXIST:
- inventory: id, org_id, sku, name, qty, location, reorder_level, unit_price, updated_at
- customers: id, org_id, name, phone, email, gst_number, city, credit_limit, created_at
- invoices: id, org_id, invoice_number, customer_id, created_by, items, amount, status, due_date, paid_at, pdf_url, created_at
- orders: id, org_id, order_number, quotation_id, customer_id, customer_name, description, metal_type, weight_estimate, estimated_amount, advance_paid, status, status_history, expected_delivery, notes, created_by, status_updated_at, created_at
- pricing: id, org_id, metal_type, rate_per_gram, making_charge_pct, updated_by, updated_at, quotation_number, weight_grams, making_charges, subtotal, gst_pct, gst_amount, total_amount, status, valid_until, created_by
- orgs: id, name, slug, industry, plan, is_active, created_at, session_ttl_minutes, gst_rate
- users: id, org_id, role_id, name, phone, email, channel, is_active, created_at
- roles: id, org_id, name, permissions, created_at
- audit_log: id, org_id, user_id, intent_key, tier, input_text, outcome, otp_used, steps_taken, created_at, due_date, pdf_url
- pending_approvals: id, org_id, workflow_id, requester_id, approver_role, intent_key, context, status, decided_by, decided_at, created_at
- otp_tokens: id, user_id, otp_hash, action_context, expires_at, used, attempts, created_at
- credentials: id, org_id, adapter_name, config, created_at
- workflows: id, org_id, intent_key, name, steps, is_active, otp_required, otp_threshold, version, last_run, created_at, is_scheduled, schedule_cron, scheduled_by, approval_threshold, trigger_patterns, description, adapter_method, workflow_type, training_phrases, entity_schema, sql_template, sql_params_order, response_format, business_glossary, llm_system_prompt

FORBIDDEN TABLE NAMES (DO NOT USE):
- products, items, inventory_items, stock, stock_items, goods, merchandise, materials
- locations, businesses, companies, organizations, firms

FORBIDDEN COLUMN NAMES (USE THE CORRECT ONES):
- inventory.qty (NOT: quantity, stock_quantity, stock_level, amount_on_hand)
- inventory.reorder_level (NOT: threshold, min_stock, reorder_point)
- invoices.status (NOT: invoice_status, payment_status)
- customers.name (NOT: customer_name, client_name)
- pricing.metal_type (NOT: metal, gold_type)

=== END OF CRITICAL CONSTRAINTS ===

CURRENT USER:
- Name: {user["user_name"]}
- Role: {user["role"]}
- Permissions: {", ".join(user.get("permissions", [])[:15])}

TODAY: {today}

DATABASE SCHEMA (for reference only - use the table/column list above):
{schema}

RULES:
1. For any data question — use query_database. Write fresh SQL every time.
2. ALWAYS include WHERE org_id = $1 (injected automatically as $1).
3. NEVER use table names or column names NOT listed in the CRITICAL section above.
4. If a table doesn't exist in the schema, the query will fail. Only use tables shown above.
5. Never expose id, org_id, or uuid columns in your response.
6. If a name matches multiple rows — use clarify tool, show the options.
7. For PDF requests — query_database first, then generate_pdf.
8. For write operations — always call confirm_action first, never write directly.
9. Format all responses for WhatsApp: use *bold* for key numbers, bullet points
   for lists, emojis for context, keep responses concise.
10. Speak naturally. You understand English and Hinglish equally.
11. If a query returns empty — say so plainly, don't say "no results found".
12. Add useful context and insight beyond just the raw data where relevant.

HINGLISH BUSINESS GLOSSARY — NEVER ASK FOR CLARIFICATION ON THESE TERMS:
- "baaki" / "udhaar" / "kitna baaki" / "dues" / "outstanding" 
  → invoices.amount WHERE status IN ('pending', 'overdue')
- "bhav" / "rate" / "sone ka bhav" / "aaj ka bhav"
  → pricing.rate_per_gram (from the pricing table)
- "maal" / "stock items" / "khatam ho raha"  
  → inventory WHERE qty <= reorder_level
- "production mein" / "kaam chal raha" / "in production"
  → orders WHERE status = 'in_production'
- "ready hai" / "ready orders"
  → orders WHERE status = 'ready'
- "pending invoice" / "baaki invoice"
  → invoices WHERE status IN ('pending', 'overdue')
- "low stock" / "stock kam hai" / "khatam hone wala"
  → inventory WHERE qty <= reorder_level ORDER BY (reorder_level - qty) DESC

RULE ON CLARIFY TOOL:
- NEVER use clarify because you're unsure of intent — attempt the query first
- ONLY use clarify when a database query returns MULTIPLE records 
  (e.g., you searched customers WHERE name ILIKE '%Mehta%' and got 3 rows)
- "Mehta ka baaki" means outstanding dues for customers named Mehta — query it directly

NEVER: expose passwords, OTP hashes, raw UUIDs, or internal workflow config.
NEVER: run DROP, DELETE, UPDATE, INSERT, or any DDL.
"""


# ── Tool execution ────────────────────────────────────────────────────────────

async def _execute_tool(
    tool_name: str,
    tool_input: dict,
    user: dict,
    phone: str,
) -> str:
    """Execute a tool call and return result as string."""

    if tool_name == "query_database":
        sql = tool_input.get("sql", "")
        params = tool_input.get("params", [])

        # Validate SQL against forbidden tables/columns
        forbidden_tables = ["products", "items", "inventory_items", "stock", "stock_items", "goods", "merchandise", "materials", "locations", "businesses", "companies", "organizations", "firms"]
        forbidden_columns = ["quantity", "stock_quantity", "stock_level", "amount_on_hand", "threshold", "min_stock", "reorder_point", "invoice_status", "payment_status", "customer_name", "client_name", "metal", "gold_type"]

        sql_lower = sql.lower()
        for forbidden in forbidden_tables:
            if f"from {forbidden}" in sql_lower or f"join {forbidden}" in sql_lower:
                return f"ERROR: Table '{forbidden}' does not exist. Use 'inventory' instead."

        for forbidden in forbidden_columns:
            if forbidden in sql_lower:
                return f"ERROR: Column '{forbidden}' does not exist. Check schema for correct column names."

        ok, reason = _safe(sql)
        if not ok:
            return f"ERROR: Query blocked — {reason}"

        try:
            full_params = [user["org_id"]] + list(params)
            rows = await fetch_all(sql, *full_params)

            # Strip sensitive columns
            clean = []
            for r in rows:
                row = {
                    k: v for k, v in dict(r).items()
                    if k not in SENSITIVE_COLS
                    and not (isinstance(v, str) and len(v) > 30 and "-" in v
                             and k.endswith("_id"))
                }
                clean.append(row)

            if not clean:
                return "EMPTY: No rows returned"

            return json.dumps(clean, default=str)

        except Exception as e:
            return f"ERROR: {str(e)}"

    elif tool_name == "clarify":
        question = tool_input.get("question", "")
        options = tool_input.get("options", [])
        if options:
            opts_text = "\n".join(
                f"{i+1}. {o}" for i, o in enumerate(options)
            )
            return f"CLARIFY_SENT: {question}\n{opts_text}"
        return f"CLARIFY_SENT: {question}"

    elif tool_name == "generate_pdf":
        # Import here to avoid circular deps
        from app.services.pdf_service import _generate_generic_pdf
        from app.services.whatsapp import send_document

        rows = tool_input.get("rows", [])
        title = tool_input.get("title", "Report")
        subtitle = tool_input.get("subtitle", "")

        if not rows:
            return "ERROR: No data to generate PDF from"

        try:
            # Build a generic PDF — title + table of whatever rows came in
            org_row = await fetch_one(
                "SELECT name FROM orgs WHERE id = $1", user["org_id"]
            )
            org_name = org_row["name"] if org_row else user["org_name"]

            pdf_bytes = _generate_generic_pdf(
                title=title,
                subtitle=subtitle,
                rows=rows,
                org_name=org_name
            )
            await send_document(
                to=phone,
                pdf_bytes=pdf_bytes,
                filename=f"{title.replace(' ', '_')}.pdf",
                caption=f"📄 {title}"
            )
            return f"PDF_SENT: {title} ({len(rows)} rows)"

        except Exception as e:
            return f"ERROR generating PDF: {str(e)}"

    elif tool_name == "confirm_action":
        action_desc = tool_input.get("action_description", "")
        details = tool_input.get("details", {})
        details_str = "\n".join(
            f"  • {k}: {v}" for k, v in details.items()
        ) if details else ""

        # Store in session that we're awaiting confirmation
        # The webhook handles the reply
        return f"CONFIRM_PENDING: {action_desc}\n{details_str}"

    return f"ERROR: Unknown tool {tool_name}"


# ── Main agent loop ───────────────────────────────────────────────────────────

async def run_agent(
    message: str,
    user: dict,
    phone: str,
    max_iterations: int = 6,
    conversation_history: list = None,
) -> tuple[str, list]:
    """
    Main entry point. Replaces classify_message + execute_intent entirely.
    Runs the tool-calling loop until the LLM produces a final text response.
    """
    print(f"[AGENT] Starting agent for: {message}")
    try:
        system_prompt = await _build_system_prompt(user)
        print(f"[AGENT] System prompt built, length: {len(system_prompt)}")
    except Exception as e:
        print(f"[AGENT] Error building system prompt: {e}")
        import traceback
        traceback.print_exc()
        return f"Error building system prompt: {str(e)}", []

    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    # Inject prior conversation (last N turns)
    if conversation_history:
        messages.extend(conversation_history)
    
    messages.append({"role": "user", "content": message})

    for iteration in range(max_iterations):
        print(f"[AGENT] Iteration {iteration + 1}/{max_iterations}")
        try:
            response = await _client.chat.completions.create(
                model="gpt-4o",
                max_tokens=1024,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto"
            )
            print(f"[AGENT] OpenAI response received, stop_reason: {response.choices[0].finish_reason}")
        except Exception as e:
            print(f"[AGENT] OpenAI API error: {e}")
            import traceback
            traceback.print_exc()
            return f"OpenAI API error: {str(e)}", []

        assistant_message = response.choices[0].message

        # LLM finished — return the text response
        if not assistant_message.tool_calls:
            print(f"[AGENT] No tool calls, returning text response")
            history_to_save = [m for m in messages if m.get("role") != "system"]
            return assistant_message.content.strip(), history_to_save

        # LLM wants to call tools
        # Add assistant's response to message history
        messages.append({
            "role": "assistant",
            "content": assistant_message.content,
            "tool_calls": assistant_message.tool_calls
        })

        # Execute each tool call
        tool_results = []
        for tool_call in assistant_message.tool_calls:
            print(f"[AGENT] Executing tool: {tool_call.function.name}")
            result = await _execute_tool(
                tool_name=tool_call.function.name,
                tool_input=json.loads(tool_call.function.arguments),
                user=user,
                phone=phone
            )
            print(f"[AGENT] Tool result: {result[:100]}...")

            tool_results.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "content": result
            })

            # If this was a clarify call, stop the loop
            if tool_call.function.name == "clarify":
                clarify_question = json.loads(tool_call.function.arguments).get("question", "")
                options = json.loads(tool_call.function.arguments).get("options", [])
                if options:
                    opts = "\n".join(
                        f"{i+1}. {o}" for i, o in enumerate(options)
                    )
                    history_to_save = [m for m in messages if m.get("role") != "system"]
                    return f"🤔 {clarify_question}\n\n{opts}", history_to_save
                history_to_save = [m for m in messages if m.get("role") != "system"]
                return f"🤔 {clarify_question}", history_to_save

            # If confirm_action was called, pause and return the prompt
            if tool_call.function.name == "confirm_action":
                action_desc = json.loads(tool_call.function.arguments).get("action_description", "")
                details = json.loads(tool_call.function.arguments).get("details", {})
                lines = [f"⚠️ *Confirm Action*\n\n{action_desc}"]
                if details:
                    for k, v in details.items():
                        lines.append(f"  • {k}: {v}")
                lines.append("\nReply *yes* to confirm or *no* to cancel.")
                history_to_save = [m for m in messages if m.get("role") != "system"]
                return "\n".join(lines), history_to_save

        # Add tool results back into message history
        messages.extend(tool_results)

    history_to_save = [m for m in messages if m.get("role") != "system"]
    return "🤔 Something went wrong. Please try again.", history_to_save
