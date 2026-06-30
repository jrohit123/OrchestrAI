"""
Tool-calling agent.
Replaces the entire classifier + intent_matcher + intent_analyzer pipeline.
Zero domain hardcoding. Works for any schema, any industry.
"""
import json
import os
import re
import datetime as _dt
from openai import AsyncOpenAI
from app.db import fetch_all, fetch_one
from app.services.query_engine import _safe, SENSITIVE_COLS
from app.services.prompt_loader import load_prompt

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── IST timezone for greetings ────────────────────────────────────────────────
try:
    import zoneinfo
    _IST = zoneinfo.ZoneInfo("Asia/Kolkata")
except ImportError:
    import pytz
    _IST = pytz.timezone("Asia/Kolkata")

# ── Schema cache (per org, reloaded on restart) ──────────────────────────────
_schema_cache: dict[str, str] = {}

# ── Greeting & help detection patterns ────────────────────────────────────────
_GREETING_PATTERNS = {
    # English
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    "good night", "howdy", "greetings", "what's up", "sup",
    # Hindi / Hinglish
    "namaste", "namaskar", "namasté", "pranam", "jai shri krishna",
    "ram ram", "jai jinendra", "sat sri akal", "salaam", "adaab",
    "kya haal", "kya hal", "kaise ho", "kya chal raha", "hello ji",
    "hi ji", "bhai", "sir", "boss",
}

_HELP_PATTERNS = {
    "help", "menu", "options", "what can i do", "what can i ask",
    "kya kar sakta hoon", "kya pooch sakta hoon", "kya help milegi",
    "kya karna hai", "guide", "guide me", "start", "get started",
    "capabilities", "features", "what do you do", "tell me what you can do",
    "commands", "list commands", "how to use",
}

# Permission → friendly capability label (domain-agnostic)
_PERM_LABELS = {
    "check_stock":            ("📦", "Check inventory & stock levels"),
    "check_outstanding":      ("💰", "View outstanding dues"),
    "create_invoice":         ("🧾", "Create sales invoices"),
    "view_report":            ("📊", "View business reports"),
    "approve_invoice":        ("✅", "Approve invoices"),
    "dues_report":            ("📋", "Outstanding dues report"),
    "check_metal_rates":      ("📈", "Check current metal rates"),
    "view_orders_by_status":  ("🔨", "Check production order status"),
    "check_low_stock":        ("⚠️", "Check low stock alerts"),
    "generate_price_quotation": ("💎", "Generate price quotations"),
    "create_sales_invoice":   ("🧾", "Create & send tax invoices"),
    "get_customer_dues_statement": ("📄", "Customer dues statement PDF"),
    "send_invoice_pdf":       ("📤", "Send invoice PDFs via WhatsApp"),
    "set_metal_rate":         ("⚙️",  "Update metal rates"),
    "clear_sessions":         ("🔒", "Manage user sessions"),
    "check_credit_limit":     ("💳", "Check customer credit limits"),
}


def _is_pure_greeting(message: str) -> bool:
    """Return True if the message is ONLY a greeting (≤4 words, no query body)."""
    clean = message.strip().lower().rstrip("!.?,")
    # Direct pattern match
    if clean in _GREETING_PATTERNS:
        return True
    # 1-4 word message where first word is a greeting
    words = clean.split()
    if len(words) <= 4 and words[0] in _GREETING_PATTERNS:
        return True
    return False


def _is_help_request(message: str) -> bool:
    """Return True if user is asking what the system can do."""
    clean = message.strip().lower()
    for pattern in _HELP_PATTERNS:
        if pattern in clean:
            return True
    return False


def _time_of_day_greeting(ist_hour: int) -> str:
    if 5 <= ist_hour < 12:
        return "Good morning"
    elif 12 <= ist_hour < 17:
        return "Good afternoon"
    elif 17 <= ist_hour < 21:
        return "Good evening"
    else:
        return "Namaskar"


def _build_greeting_response(user: dict, message: str) -> str:
    """Build a personalised greeting. No LLM call, no DB query."""
    now_ist = _dt.datetime.now(_IST)
    tod = _time_of_day_greeting(now_ist.hour)
    first_name = user["user_name"].split()[0]
    role = user.get("role", "user").title()
    org = user.get("org_name", "")

    # Build capability list from this user's actual permissions
    perms = set(user.get("permissions", []))
    capability_lines = []
    seen_labels = set()
    for perm in _PERM_LABELS:
        if perm in perms:
            emoji, label = _PERM_LABELS[perm]
            if label not in seen_labels:
                capability_lines.append(f"  {emoji} {label}")
                seen_labels.add(label)

    caps_block = "\n".join(capability_lines) if capability_lines else "  • Query data and run reports"

    return (
        f"{tod}, *{first_name}!* 👋\n\n"
        f"I'm your ERP assistant for *{org}*.\n"
        f"You're logged in as *{role}*.\n\n"
        f"*Here's what I can help you with:*\n"
        f"{caps_block}\n\n"
        f"Just ask me in plain language — English, Hindi, or Hinglish, "
        f"whatever is comfortable. 😊\n\n"
        f"_Example: \"Mehta ka kitna baaki hai?\" or \"Show ready orders\"_"
    )


def _build_help_response(user: dict) -> str:
    """Build a detailed capability guide based on this user's permissions."""
    perms = set(user.get("permissions", []))
    role = user.get("role", "user").title()
    first_name = user["user_name"].split()[0]

    # Group by category
    query_caps, action_caps, report_caps = [], [], []

    perm_to_cat = {
        "check_stock":           ("query",   "📦 *Stock & Inventory*\n  Check stock levels, low stock, item locations"),
        "check_outstanding":     ("query",   "💰 *Outstanding Dues*\n  Check pending/overdue invoices for any customer"),
        "check_credit_limit":    ("query",   "💳 *Credit Limits*\n  View customer credit limits"),
        "check_metal_rates":     ("query",   "📈 *Metal Rates*\n  Current 22kt/18kt/silver rates"),
        "view_orders_by_status": ("query",   "🔨 *Production Orders*\n  In-production, ready, confirmed orders"),
        "create_invoice":        ("action",  "🧾 *Create Invoice*\n  Create & send tax invoice via WhatsApp"),
        "create_sales_invoice":  ("action",  "🧾 *Sales Invoice*\n  Generate GST tax invoice with PDF"),
        "generate_price_quotation": ("action","💎 *Price Quotation*\n  Generate quotation PDF for a customer"),
        "approve_invoice":       ("action",  "✅ *Approve Invoices*\n  Approve pending invoices"),
        "set_metal_rate":        ("action",  "⚙️ *Set Metal Rates*\n  Update 22kt/18kt/silver base rates"),
        "view_report":           ("report",  "📊 *Business Reports*\n  Revenue, outstanding, inventory reports"),
        "dues_report":           ("report",  "📋 *Dues Report*\n  Full outstanding report with aging analysis"),
        "get_customer_dues_statement": ("report", "📄 *Statement PDF*\n  Dues statement for specific customer"),
        "send_invoice_pdf":      ("report",  "📤 *Send Invoice PDF*\n  Resend any invoice as PDF via WhatsApp"),
    }

    seen = set()
    for perm, (cat, label) in perm_to_cat.items():
        if perm in perms and label not in seen:
            if cat == "query":   query_caps.append(label)
            elif cat == "action": action_caps.append(label)
            elif cat == "report": report_caps.append(label)
            seen.add(label)

    sections = []
    if query_caps:
        sections.append("*🔍 What you can check/query:*\n" + "\n\n".join(query_caps))
    if action_caps:
        sections.append("*⚡ What you can create/action:*\n" + "\n\n".join(action_caps))
    if report_caps:
        sections.append("*📁 Reports & Documents:*\n" + "\n\n".join(report_caps))

    body = "\n\n".join(sections) if sections else "Ask me anything about your business data."

    return (
        f"Hi *{first_name}!* Here's your full menu as *{role}*:\n\n"
        f"{body}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"*How to ask:*\n"
        f"• English: \"Show Mehta Enterprises dues\"\n"
        f"• Hinglish: \"Mehta ka kitna baaki hai?\"\n"
        f"• Hindi: \"Sharma ka outstanding dikhao\"\n"
        f"• Short: \"low stock\", \"ready orders\", \"22kt rate\"\n\n"
        f"Say *pdf* at the end to get any result as a document. 📄"
    )


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
            "name": "update_draft",
            "description": (
                "Update or read the pending action draft. Use this to accumulate "
                "information across multiple turns before confirmation. "
                "Call with intent_key to start a new draft. Call with fields to update "
                "an existing draft. The response shows what fields are still missing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent_key": {
                        "type": "string",
                        "description": "The workflow intent_key (e.g., 'create_sales_invoice', 'generate_price_quotation')"
                    },
                    "fields": {
                        "type": "object",
                        "description": "Fields to update in the draft (e.g., {customer_id: '...', amount: 92000})"
                    },
                    "stage": {
                        "type": "string",
                        "enum": ["collecting", "awaiting_confirmation"],
                        "description": "Stage of the draft. Default 'collecting'. Set to 'awaiting_confirmation' when all fields are collected."
                    }
                },
                "required": []
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
                    },
                    "candidates": {
                        "type": "array",
                        "description": "Optional list of candidate rows from database for disambiguation context",
                        "items": {"type": "object"}
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
                "Generate a professional PDF and send it via WhatsApp.\n\n"
                "STRICT TRIGGER RULE — only call this when the user's current message "
                "contains at least one of:\n"
                "  'pdf', 'download', 'document'\n"
                "  'statement pdf' (formal account statement requested as document)\n"
                "  'bhejo' after a data response (send as document)\n\n"
                "DO NOT CALL for: 'show', 'check', 'list', 'dikhao', 'batao', 'kitna', "
                "'baaki', 'outstanding', 'dues', 'orders' — UNLESS the word pdf/download/document "
                "is also present.\n\n"
                "CORRECT FLOW:\n"
                "  1. User asks question → query_database → return TEXT\n"
                "  2. Append to text: '_📥 Reply *pdf* to get this as a document._'\n"
                "  3. Only when user replies 'pdf' → THEN call generate_pdf\n\n"
                "DOC_TYPE:\n"
                "  'report'    → any multi-row result (DEFAULT)\n"
                "  'invoice'   → single Tax Invoice by INV-XXXX\n"
                "  'statement' → account statement for one customer\n"
                "  'orders'    → production orders list\n"
                "  'quotation' → price quotation\n"
                "NEVER use 'invoice' for lists of invoices — always 'report'."
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
                        "description": "Delivery method. Default 'whatsapp'. Use 'email' ONLY when user explicitly says 'email only', 'mail only', 'just email', or similar exclusive language. Use 'both' ONLY when user explicitly says 'email and whatsapp', 'send both', or similar inclusive language. Otherwise use 'whatsapp'."
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

    # Load workflows entity_schema for slot-filling guidance
    workflows = await fetch_all("""
        SELECT intent_key, entity_schema, business_glossary, llm_system_prompt
        FROM workflows
        WHERE org_id = $1 AND is_active = true
    """, user["org_id"])

    # Build workflow schema guidance
    workflow_schema_text = ""
    if workflows:
        workflow_schema_text = "\n\n=== WORKFLOW SCHEMAS — REQUIRED FIELDS FOR EACH ACTION ===\n"
        for wf in workflows:
            intent_key = wf.get("intent_key")
            entity_schema = wf.get("entity_schema", {})
            business_glossary = wf.get("business_glossary", {})
            llm_prompt = wf.get("llm_system_prompt", "")

            # Parse JSONB if it's a string
            if isinstance(entity_schema, str):
                try:
                    entity_schema = json.loads(entity_schema)
                except:
                    entity_schema = {}
            if isinstance(business_glossary, str):
                try:
                    business_glossary = json.loads(business_glossary)
                except:
                    business_glossary = {}

            if entity_schema:
                workflow_schema_text += f"\n{intent_key}:\n"
                workflow_schema_text += f"  Required fields:\n"
                for field_name, field_def in entity_schema.items():
                    required = "REQUIRED" if field_def.get("required") else "optional"
                    field_type = field_def.get("type", "string")
                    workflow_schema_text += f"    - {field_name} ({field_type}, {required})\n"

            if business_glossary:
                workflow_schema_text += f"  Business glossary:\n"
                for term, meaning in business_glossary.items():
                    workflow_schema_text += f"    - '{term}' means: {meaning}\n"

            if llm_prompt:
                workflow_schema_text += f"  Workflow-specific instructions: {llm_prompt}\n"

        workflow_schema_text += "\n=== END WORKFLOW SCHEMAS ===\n"

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

{workflow_schema_text}

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
  SELECT id, name, city FROM customers WHERE org_id = $1 AND name ILIKE '%{{FULL_NAME}}%'
  - If 1 result → proceed immediately. NO clarification needed.
  - If 2+ results → CRITICAL: CALL clarify tool FIRST. Do NOT show any results.
  - If 0 results → go to Pass 2.

Pass 2 (only if Pass 1 returned 0 results): Search with first significant word only:
  SELECT id, name, city FROM customers WHERE org_id = $1 AND name ILIKE '%{{FIRST_WORD}}%'
  - If 1 result → proceed.
  - If 2+ results → CRITICAL: CALL clarify tool FIRST. Do NOT show any results.
  - If 0 results → tell user customer not found.

RULE 3 — WILDCARD QUERIES ("all customers", "all Mehta", etc.):
If the user says "all", "all customers", "all [name fragment]", or "summary of all":
  - Do NOT try to resolve a specific customer
  - Query for ALL matching records: WHERE name ILIKE '%{{fragment}}%' OR no filter at all
  - Return a summary with totals
  - Example: "all Mehta customers" → WHERE name ILIKE '%Mehta%'
  - Example: "all customers" → no name filter, return all

RULE 4 — NEVER ASK WHICH MEHTA WHEN USER SAID "MEHTA ENTERPRISES":
If the user provided a FULL multi-word name that matches exactly 1 customer,
proceed immediately. Only clarify when the name is genuinely ambiguous.
"Mehta Enterprises" ILIKE '%Mehta Enterprises%' → returns ONLY "Mehta Enterprises (Pune)"
→ Proceed directly. Do NOT ask "which Mehta?"

RULE 5 — CONFIRM BEFORE CREATE (UPDATED with draft system):
"Mehta Enterprises 92000 invoice" → ACTION (create invoice)
  Steps: 1) Resolve customer (Pass 1: "Mehta Enterprises" → 1 match)
         2) Call update_draft with intent_key="create_sales_invoice" and fields={{"customer_id": "uuid", "customer_name": "Mehta Enterprises", "amount": 92000}}
         3) Call confirm_action with action_description and details
         4) User confirms → webhook executes → check OTP threshold → create

"Mehta Enterprises invoices" → READ (query existing invoices, no creation)
  Steps: 1) Resolve customer → 2) query_database for their invoices

Distinguish CREATE from VIEW by context:
- CREATE signals: "invoice [customer] [amount]", "bill [customer]", "make invoice"
- VIEW signals: "show", "list", "check", "what", question words, no amount given
- AMBIGUOUS: "Mehta Enterprises 92000 invoice" → treat as CREATE if amount given

RULE 6 — USE update_draft FOR MULTI-TURN SLOT ACCUMULATION:
When the user provides incomplete information for an action (e.g., "create invoice" without amount):
  1) Call update_draft with intent_key and the fields you have
  2) Tell the user what you have and what's missing (refer to WORKFLOW SCHEMAS for required fields)
  3) On the next message, call update_draft again with the new fields merged
  4) When all required fields are collected, call update_draft with stage="awaiting_confirmation"
  5) Then call confirm_action

Example:
  User: "create invoice"
  → update_draft(intent_key="create_sales_invoice", fields={{}})
  → "I'll create an invoice for you. I need: customer name, amount. Please provide customer name."
  User: "Jain Gold Works"
  → update_draft(intent_key="create_sales_invoice", fields={{"customer_id": "uuid", "customer_name": "Jain Gold Works"}})
  → "I have: customer Jain Gold Works. I need: amount. Please provide amount."
  User: "92000"
  → update_draft(intent_key="create_sales_invoice", fields={{"customer_id": "uuid", "customer_name": "Jain Gold Works", "amount": 92000}}, stage="awaiting_confirmation")
  → confirm_action(action_description="Create invoice for Jain Gold Works, Rs.92,000", details={{...}})

RULE 7 — WORKFLOW SCHEMAS GUIDE REQUIRED FIELDS:
Before asking for information, check the WORKFLOW SCHEMAS section above.
Each workflow lists its required fields with types and whether they're required.
Use this to give accurate guidance on what's missing.
Example: For create_sales_invoice, required fields are: customer_name (string, REQUIRED), items (array, REQUIRED).

RULE 8 — INVOICE & QUOTATION ITEMS STRUCTURE:
When creating an invoice OR quotation, you MUST collect items with the following structure:
items = [
  {{
    "description": "22kt Gold Necklace with Ruby, 60g",
    "qty": 1,
    "unit_price": 330097.09,
    "gst": 9902.91,
    "total": 340000
  }}
]

Each item needs:
- description: string (what the item is - e.g., "22kt Gold Necklace with Ruby, 60g")
- qty: integer (quantity - default 1 if not specified)
- unit_price: float (price per unit, ex-GST)
- gst: float (GST amount for this item)
- total: float (line total = qty × unit_price + gst, or just the final total)

If the user provides a simple description like "gold chain 60g", you can:
1. Ask for quantity (default 1)
2. Ask for unit price (or calculate from inventory if available)
3. Calculate GST (typically 3% for jewellery)
4. Calculate total

Example flow for invoice:
  User: "invoice for Jain Gold Works, 22kt gold chain 60g"
  → update_draft(intent_key="create_sales_invoice", fields={{"customer_id": "uuid", "customer_name": "Jain Gold Works"}})
  → "I have: customer Jain Gold Works. I need: items. What items should be on this invoice?"
  User: "22kt gold chain 60g, 1 piece"
  → query_database to get unit_price from inventory if available
  → update_draft(intent_key="create_sales_invoice", fields={{"customer_id": "uuid", "customer_name": "Jain Gold Works", "items": [{{"description": "22kt gold chain 60g", "qty": 1, "unit_price": 330000, "gst": 9900, "total": 339900}}]}})
  → confirm_action(...)

Example flow for quotation:
  User: "quote for Sharma, 22kt gold chain 60g"
  → update_draft(intent_key="generate_price_quotation", fields={{"customer_id": "uuid", "customer_name": "Sharma"}})
  → "I have: customer Sharma. I need: items. What items should be on this quotation?"
  User: "22kt gold chain 60g, 1 piece at 330000"
  → update_draft(intent_key="generate_price_quotation", fields={{"customer_id": "uuid", "customer_name": "Sharma", "items": [{{"description": "22kt gold chain 60g", "qty": 1, "unit_price": 330000, "gst": 9900, "total": 339900}}]}})
  → confirm_action(...)

PDF DOC TYPE RULES — ALWAYS pass doc_type explicitly:
- "report"    → ANY list of multiple records (overdue invoices, invoice summary,
                 customer list, inventory, ready orders). THIS IS THE DEFAULT.
- "invoice"   → ONLY a single specific Tax Invoice (user says "send INV-301 as pdf"
                 or "Mehta Enterprises 92000 invoice pdf" referencing one invoice).
                 Title MUST be exactly: "Tax Invoice — INV-XXX"
                 Query MUST JOIN customers for customer_name, city, gst_number, AND include i.items.
                 ALWAYS populate extra_context with values from the query result:
                 {{
                   "invoice_number": "<from row>",
                   "customer_name":  "<from row>",
                   "customer_city":  "<from row.city>",
                   "customer_gstin": "<from row.gst_number>",
                   "amount":         <from row>,
                   "gst_rate":       3.0,
                   "due_date":       "<from row>"
                 }}
- "statement" → Dues/account statement for ONE specific customer.
- "orders"    → Production orders list.
- "quotation" → Price quotation.
NEVER use "invoice" doc_type for "all invoices", "overdue invoices list", "invoice summary".
Those are ALWAYS "report".

PDF QUERY RULE: When generating a PDF that involves invoices and customers,
always JOIN the customers table to include customer name in results:
SELECT i.invoice_number, c.name as customer_name, c.city, c.gst_number,
       i.amount, i.status, i.due_date, i.items
FROM invoices i JOIN customers c ON c.id = i.customer_id
WHERE i.org_id = $1 AND ...
Include i.items so the Tax Invoice can show line-item breakdown.

AMOUNT DISPLAY: Always display monetary values in Indian format with Rs. prefix.
Rs.1,45,000 not Rs.145000. Use commas at Indian positions.

SQL SELF-CORRECTION PROTOCOL:
When query_database returns an ERROR:
1. Do NOT show the user raw errors or SQL
2. Identify the issue: wrong column name? wrong table? syntax error?
3. Write a corrected SELECT and call query_database again
4. If the second attempt also fails: "I couldn't retrieve that data.
   Please verify [specific thing] and try again."
Example: tried `inventory.quantity` → error → retry with `inventory.qty`

RESPONSE QUALITY CHECK (before sending any reply):
Ask yourself: Does my response contain any of these? If yes, rewrite it.
  ✗ SQL queries or WHERE clauses
  ✗ Column names (org_id, customer_id, invoice_number as raw text)
  ✗ UUID strings
  ✗ Table names mentioned to the user
  ✗ Raw error strings from the database
  ✗ Technical system details

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
            # Match as standalone word only — not as substring of valid column names
            if re.search(r'\b' + re.escape(forbidden) + r'\b', sql_lower):
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
        doc_type      = tool_input.get("doc_type", "report")
        extra_context = tool_input.get("extra_context", {})
        send_via      = tool_input.get("send_via", "whatsapp")

        # For quotations: rows are always empty — all data is in extra_context. Allow it.
        # For invoices: if items array is empty, construct a synthetic line item from amount.
        # For reports: empty rows is a genuine error.
        if not rows:
            if doc_type in ("quotation",):
                pass  # Quotation data lives entirely in extra_context — fine to proceed.
            elif doc_type == "invoice":
                # Synthetic fallback: seeded/legacy invoices may have empty items array.
                # Build one line item treating `amount` as the GST-inclusive total.
                raw_amount = float(extra_context.get("amount", 0))
                gst_rate   = float(extra_context.get("gst_rate", 3.0))
                subtotal   = round(raw_amount / (1 + gst_rate / 100), 2)
                gst_val    = round(raw_amount - subtotal, 2)
                rows = [{
                    "description": "Jewellery — As Per Order",
                    "qty": 1,
                    "unit_price": subtotal,    # ex-GST unit price
                    "gst": gst_val,
                    "total": raw_amount        # GST-inclusive line total
                }]
                # Also inject pre-computed amounts so LLM doesn't recalculate
                extra_context["subtotal"]   = subtotal
                extra_context["gst_amount"] = gst_val
                extra_context["total_amount"] = raw_amount
            else:
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

        # ── QUOTATION: generate number and persist to pricing table ──────────
        if doc_type == "quotation" and extra_context.get("metal_type"):
            try:
                from app.db import execute as _execute, fetch_one as _fetch_one
                from datetime import timedelta

                count_row = await _fetch_one(
                    "SELECT COUNT(*) as cnt FROM pricing "
                    "WHERE org_id = $1 AND quotation_number IS NOT NULL",
                    user["org_id"]
                )
                q_number = f"QUO-{1001 + int(count_row['cnt'])}"
                valid_until = (__import__("datetime").date.today()
                               + timedelta(days=3)).strftime("%Y-%m-%d")

                ctx = extra_context
                await _execute("""
                    INSERT INTO pricing (
                        org_id, quotation_number, metal_type, weight_grams,
                        rate_per_gram, making_charge_pct, making_charges, subtotal,
                        gst_pct, gst_amount, total_amount, status, valid_until, created_by
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'sent',$12,$13)
                """,
                    user["org_id"],
                    q_number,
                    str(ctx.get("metal_type", "")).lower(),
                    float(ctx.get("weight_grams", 0)),
                    float(ctx.get("rate_per_gram", 0)),
                    float(ctx.get("making_charge_pct", 0)),
                    float(ctx.get("making_charges", 0)),
                    float(ctx.get("subtotal", 0)),
                    float(ctx.get("gst_pct", 3.0)),
                    float(ctx.get("gst_amount", 0)),
                    float(ctx.get("total_amount", 0)),
                    valid_until,
                    user["user_id"]
                )
                extra_context["quotation_number"] = q_number
                extra_context["valid_until"] = valid_until
                print(f"[AGENT] Quotation saved to DB: {q_number}")
            except Exception as e:
                print(f"[AGENT] Quotation DB save failed (non-fatal): {e}")
                # Non-fatal — still generate the PDF even if save fails
        # ─────────────────────────────────────────────────────────────────────

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

    elif tool_name == "update_draft":
        intent_key = tool_input.get("intent_key")
        fields = tool_input.get("fields", {})
        stage = tool_input.get("stage", "collecting")

        # Return session patch for webhook to persist
        return {
            "type": "draft_update",
            "intent_key": intent_key,
            "fields": fields,
            "stage": stage,
            "raw_text": message
        }

    elif tool_name == "confirm_action":
        action_desc = tool_input.get("action_description", "")
        details = tool_input.get("details", {})
        details_str = "\n".join(
            f"  • {k}: {v}" for k, v in details.items()
        ) if details else ""

        # Return session patch for webhook to persist
        return {
            "type": "confirm_pending",
            "action_description": action_desc,
            "details": details
        }

    return f"ERROR: Unknown tool {tool_name}"


# ── Main agent loop ───────────────────────────────────────────────────────────

async def run_agent(
    message: str,
    user: dict,
    phone: str,
    max_iterations: int = 6,
    conversation_history: list = None,
    pending_action: dict = None,
) -> tuple[str, list, dict]:
    """
    Main entry point. Replaces classify_message + execute_intent entirely.
    Runs the tool-calling loop until the LLM produces a final text response.

    Returns: (reply_text, history_to_save, session_patch)
    session_patch is a dict of session updates (e.g., pending_action) for webhook to persist.
    """
    print(f"[AGENT] Starting agent for: {message}")

    session_patch = {}

    # ── Fast-path: greetings and help (no LLM call needed) ──────────────────
    msg_stripped = message.strip()

    if _is_pure_greeting(msg_stripped):
        greeting_text = _build_greeting_response(user, msg_stripped)
        history_to_save = [{"role": "user", "content": message},
                           {"role": "assistant", "content": greeting_text}]
        return greeting_text, history_to_save, {}

    if _is_help_request(msg_stripped):
        help_text = _build_help_response(user)
        history_to_save = [{"role": "user", "content": message},
                           {"role": "assistant", "content": help_text}]
        return help_text, history_to_save, {}
    
    # ── Fast-path: clarify selection handling ────────────────────────────────
    # If user sent a number and previous message was a clarify, extract the selection
    if conversation_history and len(conversation_history) >= 2:
        last_assistant = conversation_history[-1].get("content", "")
        if "🤔" in last_assistant:
            # User is responding to a clarify menu
            if msg_stripped.lower() in ("all", "all of them", "summary", "all customers", "sab"):
                # User wants all options - append this context
                message = f"Show results for all options (summary)"
            elif msg_stripped.isdigit():
                # User is selecting a specific option
                lines = last_assistant.split("\n")
                for line in lines:
                    if line.strip().startswith(msg_stripped + "."):
                        selected_option = line.strip()[len(msg_stripped)+1:].strip()
                        # Append the selection to the message for context
                        message = f"{selected_option} (selected from menu)"
                        break
    # ─────────────────────────────────────────────────────────────────────────
    
    try:
        system_prompt = await _build_system_prompt(user)
        print(f"[AGENT] System prompt built, length: {len(system_prompt)}")
    except Exception as e:
        print(f"[AGENT] Error building system prompt: {e}")
        import traceback
        traceback.print_exc()
        return f"Error building system prompt: {str(e)}", [], {}

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
                    history_to_save,
                    {}
                )
        except Exception as e:
            print(f"[AGENT] OpenAI API error: {e}")
            import traceback
            traceback.print_exc()
            return f"OpenAI API error: {str(e)}", [], {}

        assistant_message = response.choices[0].message

        # LLM finished — return the text response
        if not assistant_message.tool_calls:
            print(f"[AGENT] No tool calls, returning text response")
            history_to_save = _serialize_history(messages)
            return assistant_message.content.strip(), history_to_save, session_patch

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
                    return f"🤔 {clarify_question}\n\n{opts}", history_to_save, {}
                history_to_save = _serialize_history(messages)
                return f"🤔 {clarify_question}", history_to_save, {}

            # If update_draft was called, capture session patch
            if tool_call.function.name == "update_draft":
                if isinstance(result, dict) and result.get("type") == "draft_update":
                    # Build pending_action from result
                    current_draft = pending_action or {}
                    updated_draft = {
                        "intent_key": result.get("intent_key") or current_draft.get("intent_key"),
                        "stage": result.get("stage") or current_draft.get("stage", "collecting"),
                        "fields": {**current_draft.get("fields", {}), **result.get("fields", {})},
                        "raw_text": result.get("raw_text", message),
                        "created_at": current_draft.get("created_at") or __import__("datetime").datetime.now().isoformat()
                    }
                    session_patch["pending_action"] = updated_draft
                # Continue loop to let LLM respond with confirmation or next question

            # If confirm_action was called, pause and return the prompt
            if tool_call.function.name == "confirm_action":
                if isinstance(result, dict) and result.get("type") == "confirm_pending":
                    # Set stage to awaiting_confirmation
                    if pending_action:
                        pending_action["stage"] = "awaiting_confirmation"
                        session_patch["pending_action"] = pending_action
                action_desc = json.loads(tool_call.function.arguments).get("action_description", "")
                details = json.loads(tool_call.function.arguments).get("details", {})
                lines = [f"⚠️ *Confirm Action*\n\n{action_desc}"]
                if details:
                    for k, v in details.items():
                        lines.append(f"  • {k}: {v}")
                lines.append("\nReply *yes* to confirm or *no* to cancel.")
                history_to_save = _serialize_history(messages)
                return "\n".join(lines), history_to_save, session_patch

        # Add tool results back into message history
        messages.extend(tool_results)

    history_to_save = _serialize_history(messages)
    return "🤔 Something went wrong. Please try again.", history_to_save, session_patch


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
