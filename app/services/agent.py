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
from app.services.prompt_loader import load_prompt

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
                "Call ONLY when user explicitly says 'pdf', 'download', 'document', or 'statement'. "
                "Always call query_database FIRST to get data, then call this. "
                "\n\nDOC_TYPE SELECTION — THIS IS CRITICAL:"
                "\n'report'    → Use for ANY list of multiple records: overdue invoices list, "
                "invoice summary, customer list, inventory report, order list. "
                "DEFAULT CHOICE when showing many rows."
                "\n'invoice'   → Use ONLY for a SINGLE specific formal Tax Invoice "
                "(e.g. user says 'send me INV-301 as pdf'). When using invoice type, "
                "ALWAYS JOIN customers table to include customer_name, city, gst_number in rows."
                "\n'statement' → Use for dues/outstanding account statements for one customer."
                "\n'orders'    → Use for production orders list."
                "\n'quotation' → Use for price quotations."
                "\n\nNEVER use 'invoice' type for 'all invoices', 'overdue invoices', "
                "'invoice summary' — those are ALWAYS 'report'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rows": {
                        "type": "array",
                        "description": "The data rows from query_database"
                    },
                    "title": {
                        "type": "string",
                        "description": "PDF title"
                    },
                    "subtitle": {
                        "type": "string",
                        "description": "Optional subtitle or date range"
                    },
                    "doc_type": {
                        "type": "string",
                        "enum": ["report", "invoice", "quotation", "statement", "orders"],
                        "description": "Document type. Default 'report' for any multi-record list."
                    },
                    "extra_context": {
                        "type": "object",
                        "description": "Additional metadata (customer details, totals) for invoice/statement types"
                    },
                    "send_via": {
                        "type": "string",
                        "enum": ["whatsapp", "email", "both"],
                        "description": "Delivery method. Default 'whatsapp'. Use 'email' or 'both' when user asks to email the PDF."
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

    # Load org record for industry/slug
    org_row = await fetch_one(
        "SELECT name, industry, slug FROM orgs WHERE id = $1",
        user["org_id"]
    )

    # Load layered domain prompt from files
    domain_prompt = load_prompt(dict(org_row) if org_row else {})

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

{domain_prompt}

ENTITY EXTRACTION — CRITICAL RULES (read before every query):

RULE 1 — EXTRACT THE FULL NAME THE USER TYPED:
Extract the LONGEST possible entity name from the user message.
Never truncate a multi-word name to just the first word.

EXAMPLES:
  "Mehta Enterprises 92000 invoice"  → customer = "Mehta Enterprises"
  "Singh Bullion Mart ka baaki"       → customer = "Singh Bullion Mart"
  "Sharma Fine Jewels credit limit"   → customer = "Sharma Fine Jewels"
  "Jain Gold Works statement"         → customer = "Jain Gold Works"
  "Mehta ka baaki"                    → customer = "Mehta"  (only 1 word given)
  "Sharma dues"                       → customer = "Sharma"  (only 1 word given)

RULE 2 — TWO-PASS CUSTOMER LOOKUP:
Pass 1: Search with the FULL extracted name:
  SELECT id, name, city FROM customers WHERE org_id = $1 AND name ILIKE '%{FULL_NAME}%'
  - If 1 result → proceed immediately. NO clarification needed.
  - If 2+ results → call clarify tool.
  - If 0 results → go to Pass 2.

Pass 2 (only if Pass 1 returned 0 results): Search with first significant word only:
  SELECT id, name, city FROM customers WHERE org_id = $1 AND name ILIKE '%{FIRST_WORD}%'
  - If 1 result → proceed.
  - If 2+ results → call clarify tool.
  - If 0 results → tell user customer not found.

RULE 3 — NEVER ASK WHICH MEHTA WHEN USER SAID "MEHTA ENTERPRISES":
"Mehta Enterprises" ILIKE '%Mehta Enterprises%' → returns ONLY "Mehta Enterprises (Pune)"
→ Proceed directly. Do NOT ask "which Mehta?"

RULE 4 — CONFIRM BEFORE CREATE:
"Mehta Enterprises 92000 invoice" → ACTION (create invoice)
  Steps: 1) Resolve customer (Pass 1: "Mehta Enterprises" → 1 match)
         2) call confirm_action → user confirms → check OTP threshold → create

"Mehta Enterprises invoices" → READ (query existing invoices, no creation)
  Steps: 1) Resolve customer → 2) query_database for their invoices

Distinguish CREATE from VIEW by context:
- CREATE signals: "invoice [customer] [amount]", "bill [customer]", "make invoice"
- VIEW signals: "show", "list", "check", "what", question words, no amount given
- AMBIGUOUS: "Mehta Enterprises 92000 invoice" → treat as CREATE if amount given

PDF DOC TYPE RULES — ALWAYS pass doc_type explicitly:
- "report"    → ANY list of multiple records (overdue invoices, invoice summary,
                 customer list, inventory, ready orders). THIS IS THE DEFAULT.
- "invoice"   → ONLY a single specific Tax Invoice (user says "send INV-301 as pdf").
                 When using "invoice" type, JOIN customers in your query to get
                 customer_name, city, gst_number.
- "statement" → Dues/account statement for ONE specific customer.
- "orders"    → Production orders list.
- "quotation" → Price quotation.
NEVER use "invoice" doc_type for "all invoices", "overdue invoices list", "invoice summary".
Those are ALWAYS "report".

PDF QUERY RULE: When generating a PDF that involves invoices and customers,
always JOIN the customers table to include customer name in results:
SELECT i.invoice_number, c.name as customer_name, c.city, i.amount, i.status, i.due_date
FROM invoices i JOIN customers c ON c.id = i.customer_id
WHERE i.org_id = $1 AND ...
This ensures customer names appear in the PDF instead of blank columns.

AMOUNT DISPLAY: Always display monetary values in Indian format with Rs. prefix.
Rs.1,45,000 not Rs.145000. Use commas at Indian positions.

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
        # customer_name IS a valid column in orders table — do NOT block it
        # metal IS a substring of metal_type — blocking it breaks every orders/pricing query
        # These two were causing ORD-1006 to fail. Only block truly non-existent names.
        forbidden_columns = [
            "quantity", "stock_quantity", "stock_level", "amount_on_hand",
            "threshold", "min_stock", "reorder_point",
            "invoice_status", "payment_status",
            "client_name", "gold_type"
        ]

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
        from app.services.pdf_engine import generate_pdf as _gen_pdf
        from app.services.whatsapp import send_document
        from app.services.pdf_preprocessor import preprocess_rows

        rows          = tool_input.get("rows", [])
        title         = tool_input.get("title", "Report")
        subtitle      = tool_input.get("subtitle", "")
        extra_context = tool_input.get("extra_context", {})
        send_via      = tool_input.get("send_via", "whatsapp")

        if not rows:
            return "ERROR: No data to generate PDF from"

        # Use explicit doc_type if agent passed it; otherwise infer carefully.
        # NEVER infer "invoice" just because the word appears in the title —
        # "Overdue Invoices" is a report, not a single Tax Invoice.
        if "doc_type" in tool_input:
            doc_type = tool_input["doc_type"]
        else:
            title_lower = title.lower()
            # Single specific tax invoice: must mention exact INV-number or "Tax Invoice"
            if re.search(r'\btax invoice\b|inv-\d+', title_lower):
                doc_type = "invoice"
            elif "quotation" in title_lower or re.search(r'\bquote\b', title_lower):
                doc_type = "quotation"
            elif "dues statement" in title_lower or "account statement" in title_lower:
                doc_type = "statement"
            elif re.search(r'\borders? report\b|\borders? list\b|\bproduction orders?\b', title_lower):
                doc_type = "orders"
            else:
                # Everything else — invoice lists, customer lists, inventory, etc. — is "report"
                doc_type = "report"

        # ── Pre-process rows for aging analysis, risk buckets, etc. ──────
        enriched_rows, analysis_summary = preprocess_rows(rows, doc_type)
        # Merge pre-computed analysis into extra_context (analysis wins on collision)
        merged_context = {**extra_context, **analysis_summary}
        # ──────────────────────────────────────────────────────────────────────

        try:
            org_row  = await fetch_one("SELECT name FROM orgs WHERE id = $1", user["org_id"])
            org_name = org_row["name"] if org_row else user["org_name"]

            pdf_bytes = await _gen_pdf(
                rows=enriched_rows,            # ← use enriched rows
                title=title,
                org_name=org_name,
                subtitle=subtitle,
                doc_type=doc_type,
                extra_context=merged_context,  # ← use merged context with analysis
            )
            safe_filename = re.sub(r'[^\w\-]', '_', title)[:50] + ".pdf"

            results = []

            # WhatsApp delivery
            if send_via in ("whatsapp", "both"):
                await send_document(
                    to=phone,
                    pdf_bytes=pdf_bytes,
                    filename=safe_filename,
                    caption=f"📄 {title}"
                )
                results.append("WhatsApp")

            # Email delivery
            if send_via in ("email", "both"):
                user_email = user.get("email")
                if user_email:
                    from app.services.otp_service import send_email_with_pdf
                    email_sent = await send_email_with_pdf(
                        to_email=user_email,
                        to_name=user.get("user_name", "User"),
                        subject=f"📄 {title} — {org_name}",
                        body=f"Please find attached: <b>{title}</b>",
                        pdf_bytes=pdf_bytes,
                        filename=safe_filename,
                        org_name=org_name
                    )
                    if email_sent:
                        results.append(f"Email ({user_email})")
                    else:
                        results.append("Email (failed to send)")
                else:
                    results.append("Email (no email on file)")

            delivery_str = " + ".join(results) if results else "no delivery"
            return f"PDF_SENT: {title} ({len(rows)} rows) via {delivery_str}"

        except Exception as e:
            print(f"[PDF_ENGINE] Error: {e}")
            import traceback; traceback.print_exc()
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
                max_tokens=4096,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                parallel_tool_calls=False
            )
            print(f"[AGENT] OpenAI response received, stop_reason: {response.choices[0].finish_reason}")

            if response.choices[0].finish_reason == "length":
                print(f"[AGENT] Response truncated (stop_reason=length) — aborting tool call")
                history_to_save = _serialize_history(messages)
                return (
                    "⚠️ That request returned too much data to process in one go. "
                    "Try narrowing it down — e.g. ask for a specific customer or date range.",
                    history_to_save
                )
        except Exception as e:
            print(f"[AGENT] OpenAI API error: {e}")
            import traceback
            traceback.print_exc()
            return f"OpenAI API error: {str(e)}", []

        assistant_message = response.choices[0].message

        # LLM finished — return the text response
        if not assistant_message.tool_calls:
            print(f"[AGENT] No tool calls, returning text response")
            history_to_save = _serialize_history(messages)
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
                    history_to_save = _serialize_history(messages)
                    return f"🤔 {clarify_question}\n\n{opts}", history_to_save
                history_to_save = _serialize_history(messages)
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
                history_to_save = _serialize_history(messages)
                return "\n".join(lines), history_to_save

        # Add tool results back into message history
        messages.extend(tool_results)

    history_to_save = _serialize_history(messages)
    return "🤔 Something went wrong. Please try again.", history_to_save


def _serialize_history(messages: list) -> list:
    """Convert OpenAI message objects to JSON-serializable dicts.
    Only saves user and assistant messages - tool messages are intermediate results
    and don't need to persist across conversations."""
    serialized = []
    for m in messages:
        if m.get("role") == "system":
            continue
        if m.get("role") == "tool":
            # Skip tool messages - they're intermediate results
            continue
        if m.get("role") == "assistant" and m.get("tool_calls"):
            # Skip tool-call assistant messages too — saving one side
            # of a tool_call/tool_result pair without the other causes
            # OpenAI to reject the history on the next request
            continue
        msg_copy = {"role": m["role"], "content": m.get("content", "")}
        serialized.append(msg_copy)
    return serialized
