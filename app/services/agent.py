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
from app.config import required
from app.services.prompt_loader import load_prompt
from app.services.query_engine import _safe

_client = AsyncOpenAI(api_key=required("OPENAI_API_KEY"))

def _parse_jsonb(val, default=None):
    """Parse JSONB values from Postgres (may be string or already parsed)."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default
    return val if val is not None else default

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
    "help", "what can i do", "what can i ask",
    "kya kar sakta hoon", "kya pooch sakta hoon", "kya help milegi",
    "kya karna hai", "guide", "guide me", "start", "get started",
    "capabilities", "features", "what do you do", "tell me what you can do",
    "commands", "list commands", "how to use",
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


async def _build_greeting_response(user: dict, message: str) -> str:
    """Build a personalised greeting. Reads workflow names from DB — no hardcoded labels."""
    from app.db import fetch_all as _fetch_all
    now_ist   = _dt.datetime.now(_IST)
    tod       = _time_of_day_greeting(now_ist.hour)
    first_name = user["user_name"].split()[0]
    role      = user.get("role", "user").title()
    org       = user.get("org_name", "")

    # Build capability list from workflows the user has permission for
    perms = set(user.get("permissions", []))
    workflows = await _fetch_all(
        "SELECT intent_key, name, workflow_type FROM workflows WHERE org_id = $1 AND is_active = true",
        user["org_id"], source_key=user["source_key"]
    )
    capability_lines = []
    seen = set()
    for wf in workflows:
        if wf["intent_key"] in perms or not perms:
            if wf["name"] not in seen:
                emoji = "⚡" if wf["workflow_type"] == "action" else "🔍"
                capability_lines.append(f"  {emoji} {wf['name']}")
                seen.add(wf["name"])

    # Fallback for non-workflow permissions
    if not capability_lines:
        capability_lines = ["  • Query data and run reports"]

    caps_block = "\n".join(capability_lines)

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


async def _build_greeting_response_with_menu(user: dict, message: str) -> dict:
    """Build greeting with interactive menu instead of text."""
    from app.services.menu import build_menu_sections
    
    now_ist   = _dt.datetime.now(_IST)
    tod       = _time_of_day_greeting(now_ist.hour)
    first_name = user["user_name"].split()[0]
    org       = user.get("org_name", "")
    
    greeting_text = (
        f"{tod}, *{first_name}!* 👋\n\n"
        f"I'm your ERP assistant for *{org}*.\n"
        f"Here's what I can help you with:"
    )
    
    sections = await build_menu_sections(user["org_id"], user)
    
    return {
        "text": greeting_text,
        "menu_sections": sections,
        "button_label": "📋 Menu"
    }


async def _build_help_response(user: dict) -> str:
    """Build a detailed capability guide from DB workflows — no hardcoded labels."""
    from app.db import fetch_all as _fetch_all
    role       = user.get("role", "user").title()
    first_name = user["user_name"].split()[0]
    perms      = set(user.get("permissions", []))

    workflows = await _fetch_all(
        "SELECT intent_key, name, description, workflow_type FROM workflows WHERE org_id = $1 AND is_active = true",
        user["org_id"], source_key=user["source_key"]
    )

    read_caps, action_caps = [], []
    for wf in workflows:
        if wf["intent_key"] in perms or not perms:
            label = f"🔍 *{wf['name']}*"
            if wf.get("description"):
                label += f"\n  {wf['description']}"
            if wf["workflow_type"] == "action":
                action_caps.append(label.replace("🔍", "⚡"))
            else:
                read_caps.append(label)

    sections = []
    if read_caps:
        sections.append("*🔍 What you can check/query:*\n" + "\n\n".join(read_caps))
    if action_caps:
        sections.append("*⚡ What you can create/action:*\n" + "\n\n".join(action_caps))

    body = "\n\n".join(sections) if sections else "Ask me anything about your business data."

    return (
        f"Hi *{first_name}!* Here's your full menu as *{role}*:\n\n"
        f"{body}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"*How to ask:*\n"
        f"• English: \"Show Mehta Enterprises dues\"\n"
        f"• Hinglish: \"Mehta ka kitna baaki hai?\"\n"
        f"• Hindi: \"Sharma ka outstanding dikhao\"\n"
        f"• Short: \"low stock\", \"ready orders\"\n\n"
        f"Say *pdf* at the end to get any result as a document. 📄"
    )


async def _get_schema(org_id: str, source_key: str = "platform") -> str:
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
              'credentials', 'workflows', 'workflow_drafts', 'scheduled_reports'
          )
        ORDER BY table_name, ordinal_position
    """, source_key=source_key)

    table_cols: dict[str, list] = {}
    for c in cols:
        t = c["table_name"]
        table_cols.setdefault(t, []).append(
            f"{c['column_name']} ({c['data_type']})"
        )

    # NOTE: Sample rows removed to prevent hallucination
    # Schema samples were causing LLM to use example data (Jain Gold Works, etc.)
    parts = [f"- {t}: {', '.join(cols)}" for t, cols in table_cols.items()]
    _schema_cache[org_id] = "\n".join(parts)
    return _schema_cache[org_id]


_sheets_schema_cache: str | None = None

async def _get_sheets_schema() -> str:
    """Cached tab/column listing for the Sheets side — same idea as
    _get_schema() but for Google Sheets instead of Postgres."""
    global _sheets_schema_cache
    if _sheets_schema_cache is not None:
        return _sheets_schema_cache
    if not os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID"):
        _sheets_schema_cache = ""
        return ""
    from app.services.sheets_client import get_all_tab_headers
    try:
        tabs = await get_all_tab_headers()
    except Exception as e:
        print(f"[AGENT] Could not load Sheets schema: {e}")
        return ""
    parts = [f"- {tab} (Google Sheets tab): {', '.join(cols)}" for tab, cols in tabs.items()]
    _sheets_schema_cache = "\n".join(parts)
    return _sheets_schema_cache


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
            "name": "query_sheet",
            "description": (
                "Read rows from a Google Sheets tab. Use this ONLY for tabs listed under "
                "'GOOGLE SHEETS DATA' in the system prompt — this is a SEPARATE data source "
                "from Postgres (query_database). Never use query_database for these tabs, "
                "and never use query_sheet for customers/invoices/orders/inventory (those "
                "are Postgres — use query_database).\n\n"
                "filters does a case-insensitive PARTIAL match on each column given — "
                "similar to ILIKE '%value%'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tab": {
                        "type": "string",
                        "description": "Exact tab name, e.g. 'Suppliers', 'RawMaterialStock', 'PurchaseOrders'"
                    },
                    "filters": {
                        "type": "object",
                        "description": "Column:value pairs to filter rows by (partial match). Omit to fetch all rows."
                    }
                },
                "required": ["tab"]
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
            "name": "show_menu",
            "description": (
                "Show the interactive WhatsApp menu of available workflows/options. "
                "Call this whenever the user asks to see the menu, options, or what they can select — "
                "in ANY phrasing or language (English, Hindi, Hinglish, mixed), at ANY point in the "
                "conversation, not just as a first message. Examples: 'can I get the menu', 'menu chahiye', "
                "'show me options', 'menu dikhao', 'kya options hain', 'go back to menu', 'main menu bhejo'. "
                "Always prefer this over describing options as plain text when the user wants to SEE/SELECT "
                "from a menu (as opposed to a general 'what can you do' capability question, which can be text)."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_pdf",
            "description": (
                "Generate a professional PDF and send it via WhatsApp.\n\n"
                "IMPORTANT: This tool is ONLY for generating PDFs from EXISTING database records.\n"
                "Do NOT use this to create new invoices or quotations.\n\n"
                "For CREATING new invoices/quotations, you MUST use:\n"
                "  1. update_draft → accumulate fields\n"
                "  2. confirm_action → trigger execution\n"
                "The system will automatically generate the PDF after database insert.\n\n"
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
                    },
                    "forward_to": {
                        "type": "string",
                        "description": "Phone number of another user to send this PDF to instead of the current user. Use when asked to 'send to [name]', 'forward to [name]', 'share with [name]'. Look up their phone from the users table first."
                    },
                    "forward_to_name": {
                        "type": "string",
                        "description": "Name of the recipient for the forward caption (e.g. 'Rajeswari')"
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
    },
    {
        "type": "function",
        "function": {
            "name": "manage_schedule",
            "description": (
                "Create, list, pause, resume, or delete a scheduled report.\n\n"
                "Use 'create' when the user asks to automatically send any report/query "
                "on a recurring basis — e.g. 'send me outstanding report every day at 8am', "
                "'low stock alert every hour', 'inventory summary every Monday at 9am'.\n\n"
                "Use 'list' when user asks 'what reports am I getting?' or 'show my schedules'.\n"
                "Use 'pause'/'resume'/'delete' when user wants to stop or manage a schedule.\n\n"
                "schedule_type values:\n"
                "  'minutely' — every N minutes (set interval_minutes)\n"
                "  'hourly'   — every hour\n"
                "  'daily'    — every day at specified hour:minute IST\n"
                "  'weekly'   — every week on day_of_week at hour:minute IST\n"
                "  'monthly'  — every month on day_of_month at hour:minute IST\n\n"
                "delivery: 'whatsapp' (default), 'email', or 'both'\n"
                "For 'email' or 'both': only use when user explicitly says 'mail me' or 'email me'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "pause", "resume", "delete"],
                        "description": "What to do"
                    },
                    "query_text": {
                        "type": "string",
                        "description": "The exact query to run on schedule (e.g. 'outstanding report', 'low stock items', 'pending orders'). Required for create."
                    },
                    "report_label": {
                        "type": "string",
                        "description": "Short human-readable name (e.g. 'Daily Outstanding Report'). Required for create."
                    },
                    "schedule_type": {
                        "type": "string",
                        "enum": ["minutely", "hourly", "daily", "weekly", "monthly"],
                        "description": "Frequency type. Required for create."
                    },
                    "interval_minutes": {
                        "type": "integer",
                        "description": "For minutely: how often in minutes (e.g. 30 = every 30 min). Min 1."
                    },
                    "hour": {
                        "type": "integer",
                        "description": "Hour in IST 24h format (0-23). Required for daily/weekly/monthly."
                    },
                    "minute": {
                        "type": "integer",
                        "description": "Minute (0-59). Default 0."
                    },
                    "day_of_week": {
                        "type": "string",
                        "enum": ["mon","tue","wed","thu","fri","sat","sun"],
                        "description": "Day of week for weekly schedules."
                    },
                    "day_of_month": {
                        "type": "integer",
                        "description": "Day of month (1-31) for monthly schedules."
                    },
                    "delivery": {
                        "type": "string",
                        "enum": ["whatsapp", "email", "both"],
                        "description": "Where to send. Default 'whatsapp'."
                    },
                    "report_id": {
                        "type": "string",
                        "description": "UUID of the schedule to pause/resume/delete."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_to_user",
            "description": (
                "Send a report, summary, or any data to another user in the same org via WhatsApp.\n\n"
                "Use this when the current user asks to forward, share, or send something to a colleague.\n\n"
                "Examples:\n"
                "  'send inventory summary to Rohit'\n"
                "  'forward this outstanding report to Ravi'\n"
                "  'share low stock alert with Priya'\n"
                "  'send pdf of pending orders to Rajeswari'\n\n"
                "Steps:\n"
                "  1. Look up the recipient in the users table by name\n"
                "  2. Run the requested query (query_database or generate_pdf)\n"
                "  3. Call this tool with the result and recipient phone\n\n"
                "If recipient name is ambiguous (multiple matches), call clarify first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_phone": {
                        "type": "string",
                        "description": "WhatsApp phone number of the recipient (from users table)"
                    },
                    "recipient_name": {
                        "type": "string",
                        "description": "Name of the recipient user"
                    },
                    "message": {
                        "type": "string",
                        "description": "The text message or report summary to send"
                    },
                    "sender_name": {
                        "type": "string",
                        "description": "Name of the person sending (current user)"
                    }
                },
                "required": ["recipient_phone", "message"]
            }
        }
    }
]


# ── System prompt builder — reads from DB, zero hardcoding ───────────────────

async def _build_system_prompt(user: dict) -> str:
    schema = await _get_schema(user["org_id"], user["source_key"])
    sheets_schema = await _get_sheets_schema()
    today = __import__("datetime").date.today().strftime("%d %b %Y")

    # Load org record for industry/slug
    org_row = await fetch_one(
        "SELECT name, industry, slug, gst_rate, default_making_charge_pct FROM orgs WHERE id = $1",
        user["org_id"], source_key=user["source_key"]
    )

    # Load workflows entity_schema for slot-filling guidance
    workflows = await fetch_all("""
        SELECT intent_key, entity_schema, business_glossary, llm_system_prompt
        FROM workflows
        WHERE org_id = $1 AND is_active = true
    """, user["org_id"], source_key=user["source_key"])

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
                except (json.JSONDecodeError, TypeError):
                    entity_schema = {}
            if isinstance(business_glossary, str):
                try:
                    business_glossary = json.loads(business_glossary)
                except (json.JSONDecodeError, TypeError):
                    business_glossary = {}

            if entity_schema:
                workflow_schema_text += f"\n{intent_key}:\n"
                workflow_schema_text += f"  Required fields:\n"
                for field_name, field_def in entity_schema.items():
                    required   = "REQUIRED" if field_def.get("required") else "optional"
                    field_type = field_def.get("type", "string")
                    computed   = " [COMPUTED — do not fill, system calculates this]" if field_def.get("computed") else ""
                    description = f" — {field_def.get('description', '')}" if field_def.get("description") else ""
                    workflow_schema_text += f"    - {field_name} ({field_type}, {required}){computed}{description}\n"

                # Add note about computed fields if any exist
                has_computed = any(v.get("computed") for v in entity_schema.values())
                if has_computed:
                    workflow_schema_text += (
                        "  CRITICAL: Never pass values for [COMPUTED] fields to update_draft.\n"
                        "  The system recalculates them deterministically. Filling them yourself\n"
                        "  will be silently overwritten and may show wrong numbers to the user.\n"
                    )

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
- quotations: id, org_id, quotation_number, customer_id, items, total_amount, status, valid_until, created_at, created_by
- scheduled_reports: id, org_id, user_id, phone, query_text, report_label, schedule_type, interval_minutes, hour, minute, day_of_week, day_of_month, delivery, is_active, next_run_at, last_run_at, run_count, created_at
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

=== END OF CRITICAL CONSTRAINTS ===

CURRENT USER:
- Name: {user["user_name"]}
- Role: {user["role"]}
- Permissions: {", ".join(user.get("permissions", [])[:15])}

TODAY: {today}

ORG DEFAULTS: GST rate {org_row['gst_rate']}% | Standard making charges {org_row.get('default_making_charge_pct', 12)}%
(Use the making-charge default ONLY when the customer/admin does not explicitly state a making charge themselves.
If they say "making charges 5000" or "8% making", use their number instead — never override an explicit value.)

DATABASE SCHEMA (for reference only - use the table/column list above):
{schema}

GOOGLE SHEETS DATA (separate source — use query_sheet tool, NEVER query_database, for these):
{sheets_schema if sheets_schema else "(none configured)"}

RULE S1 — Sheets vs Postgres: PurchaseOrders/Suppliers/RawMaterialStock live in Google
Sheets. Everything else (customers, invoices, orders, inventory) lives in Postgres.
Pick the right tool by which schema block the tab/table name appears under.

RULE S2 — Sheet reads use query_sheet(tab, filters). filters values do partial,
case-insensitive matching automatically — do not add wildcard characters yourself.

{workflow_schema_text}

{domain_prompt}

MENU REQUESTS:
If the user asks to see the menu/options in ANY phrasing or language, at ANY point —
call the show_menu tool. Do not describe the options as plain text in that case.

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

RULE 6B — NEVER INVENT DATA:
If the user says only "create invoice" or "invoice banao" with NO customer, item, or amount:
  → Call update_draft with empty fields
  → Ask ONLY for missing required fields
  → Do NOT use example names (Jain Gold Works, Mehta Enterprises) from this prompt
  → Do NOT use schema sample rows as invoice data
  → Do NOT pull items from orders/inventory unless user asked

RULE 6C — CONFIRMATION MUST USE THE confirm_action TOOL — NEVER PLAIN TEXT:
When all required fields are collected:
  → Call update_draft with stage="awaiting_confirmation"
  → Immediately call confirm_action TOOL
  → FORBIDDEN: Do NOT write "⚠️ Confirm Action" as plain text in your response
  → FORBIDDEN: Do NOT format a confirmation block yourself and return it as a message
  → FORBIDDEN: Do NOT ask "yes or no?" or "shall I proceed?" in plain text
  The confirm_action TOOL is the ONLY way a confirmation block ever reaches the user.
  If you write the ⚠️ block as text, the system cannot detect it and "yes" from the user
  will be treated as a new message with no pending action — the quotation/invoice will NOT be created.

RULE 7 — WORKFLOW SCHEMAS GUIDE REQUIRED FIELDS:
Before asking for information, check the WORKFLOW SCHEMAS section above.
Each workflow lists its required fields with types and whether they're required.
Use this to give accurate guidance on what's missing.
Example: For create_sales_invoice, required fields are: customer_name (string, REQUIRED), items (array, REQUIRED).

RULE 8 — WORKFLOW-SPECIFIC FIELD STRUCTURE:
Every field a workflow needs — including nested item fields and which ones are
computed automatically — is defined in WORKFLOW SCHEMAS above, plus that
workflow's own llm_system_prompt. Follow that schema exactly.
Never invent a field structure not declared in the workflow's entity_schema.
Fields marked [COMPUTED] are calculated by the system — do NOT ask the user
for them and do NOT fill them in update_draft.

RULE 9 — NEVER CALL generate_pdf WHEN CREATING OR CHANGING A RECORD:
If a workflow writes to the database, always follow:
  1. update_draft → accumulate fields per that workflow's entity_schema
  2. confirm_action → trigger execution
The system generates any PDF automatically after the write.
generate_pdf is ONLY for re-sending a document from an EXISTING record
(e.g. "resend INV-301 as pdf", "send QUO-1001 pdf again").

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


# ── Draft validation helper ────────────────────────────────────────────────────

# Fields that are resolved by the executor, not supplied by the LLM
_EXECUTOR_RESOLVED_FIELDS = {"customer_id", "org_id", "created_by"}

# Stale draft thresholds in minutes
_DRAFT_STALE_MINUTES   = 30   # collecting stage — abandon after 30 min of inactivity
_CONFIRM_STALE_MINUTES = 10   # awaiting_confirmation — shorter: stale unconfirmed writes are riskier

# Max reprompt attempts before forcing a clean restart
_MAX_REPROMPT_COUNT = 3


def _is_draft_stale(pending_action: dict | None) -> bool:
    """
    Return True if this draft is too old to still be relevant.
    Covers both 'collecting' (30 min) and 'awaiting_confirmation' (10 min) stages.
    """
    if not pending_action:
        return False
    stage = pending_action.get("stage")
    if stage not in ("collecting", "awaiting_confirmation"):
        return False
    # Use a shorter threshold for confirmation-stage drafts
    threshold = _CONFIRM_STALE_MINUTES if stage == "awaiting_confirmation" else _DRAFT_STALE_MINUTES
    created = pending_action.get("created_at")
    if not created:
        return False
    try:
        import datetime as _datetime_mod
        if isinstance(created, str):
            created_dt = _datetime_mod.datetime.fromisoformat(created)
        else:
            created_dt = created
        # Make both timezone-aware or both naive for comparison
        now = _datetime_mod.datetime.now(_datetime_mod.timezone.utc)
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=_datetime_mod.timezone.utc)
        age_minutes = (now - created_dt).total_seconds() / 60
        return age_minutes > threshold
    except Exception:
        return False

async def _validate_draft(intent_key: str, fields: dict, org_id: str, source_key: str) -> dict:
    """Validate draft fields. Thin wrapper over qa_verifier for backward compatibility."""
    from app.services.qa_verifier import verify_draft, VerificationError
    wf = await fetch_one(
        "SELECT * FROM workflows WHERE intent_key=$1 AND org_id=$2 AND is_active=true",
        intent_key, org_id, source_key=source_key
    )
    if not wf:
        return {"missing_fields": [], "complete": True}
    try:
        await verify_draft(dict(wf), fields, org_id, source_key)
        return {"missing_fields": [], "complete": True}
    except VerificationError as e:
        return {"missing_fields": e.missing_fields + e.invalid_fields, "complete": False}


# ── Tool execution ────────────────────────────────────────────────────────────

async def _execute_tool(
    tool_name: str,
    tool_input: dict,
    user: dict,
    phone: str,
    message: str = "",
) -> str:
    """Execute a tool call and return result as string."""

    if tool_name == "query_database":
        sql = tool_input.get("sql", "")
        params = tool_input.get("params", [])

        # Validate SQL against live schema — check referenced tables actually exist.
        # This replaces a hardcoded denylist with an always-correct schema check.
        schema_text = await _get_schema(user["org_id"])
        known_tables = set(re.findall(r'^- (\w+):', schema_text, re.MULTILINE))
        referenced_tables = set(re.findall(
            r'\b(?:FROM|JOIN)\s+(\w+)', sql, re.IGNORECASE
        ))
        unknown_tables = referenced_tables - known_tables
        if unknown_tables:
            return (
                f"ERROR: Table(s) {', '.join(sorted(unknown_tables))} not found in schema. "
                f"Available tables: {', '.join(sorted(known_tables))}. "
                f"Correct the query and retry."
            )

        ok, reason = _safe(sql)
        if not ok:
            return f"ERROR: Query blocked — {reason}"

        try:
            full_params = [user["org_id"]] + list(params)
            print(f"[AGENT] Executing SQL: {sql}")
            print(f"[AGENT] SQL params: {full_params}")
            rows = await fetch_all(sql, *full_params, source_key=user["source_key"])

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

    elif tool_name == "query_sheet":
        from app.services.sheets_client import sheet_fetch_filtered
        tab     = tool_input.get("tab", "")
        filters = tool_input.get("filters", {}) or {}
        try:
            rows = await sheet_fetch_filtered(tab, filters)
            if not rows:
                return "EMPTY: No rows returned"
            return json.dumps(rows[:50], default=str)
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

    elif tool_name == "show_menu":
        return {"type": "show_menu"}

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
        forward_to    = tool_input.get("forward_to")       # phone of another user to send to
        forward_name  = tool_input.get("forward_to_name")  # their name for caption

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

        # NOTE: Quotation records are created exclusively by action_executor._create_quotation
        # via the update_draft → confirm_action → execute_pending_action flow.
        # generate_pdf here is only called for EXISTING quotations being re-sent as PDFs.

        # ── Pre-process rows for aging analysis, risk buckets, etc. ──────
        enriched_rows, analysis_summary = preprocess_rows(rows, doc_type)
        # Merge pre-computed analysis into extra_context (analysis wins on collision)
        merged_context = {**extra_context, **analysis_summary}
        # ──────────────────────────────────────────────────────────────────────

        try:
            org_row  = await fetch_one("SELECT name FROM orgs WHERE id = $1", user["org_id"], source_key=user["source_key"])
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

            # WhatsApp delivery to current user
            if send_via in ("whatsapp", "both") and not forward_to:
                await send_document(
                    to=phone,
                    pdf_bytes=pdf_bytes,
                    filename=safe_filename,
                    caption=f"📄 {title}"
                )
                results.append("WhatsApp")

            # Forward to another user (instead of or in addition to current user)
            if forward_to:
                sender_name = user.get("user_name", "A colleague")
                await send_document(
                    to=forward_to,
                    pdf_bytes=pdf_bytes,
                    filename=safe_filename,
                    caption=f"📨 *From {sender_name}:* 📄 {title}"
                )
                results.append(f"WhatsApp → {forward_name or forward_to}")

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

        # Guard: the LLM must always pass an object. A malformed call (e.g.
        # passing an items array directly as `fields`) corrupts the stored
        # draft via Postgres jsonb's `||` operator, which crashes every
        # subsequent turn with "'list' object is not a mapping". Reject
        # instead of storing it.
        if not isinstance(fields, dict):
            print(f"[AGENT] update_draft called with non-dict fields ({type(fields).__name__}) — rejecting: {fields}")
            return (
                "ERROR: fields must be a JSON object mapping field names to values "
                "(e.g. {\"items\": [...]}), not a bare list. Re-call update_draft "
                "with the correct shape."
            )

        # Log draft fields for debugging
        print(f"[AGENT] update_draft: intent_key={intent_key}, fields={fields}, stage={stage}")

        # Server-side guardrail: auto-correct misclassified making charges
        # If making_charge_pct > 100, it's almost certainly a flat Rupee amount misclassified as percentage
        for item in (fields.get("items") or []):
            pct = item.get("making_charge_pct")
            if pct is not None and pct > 100:
                item["making_charges_flat"] = pct
                item.pop("making_charge_pct", None)
                print(f"[AGENT] Auto-corrected making_charge_pct={pct} → making_charges_flat (flat) — value was implausible as a percentage")

        # Validate draft against workflow schema
        validation = await _validate_draft(intent_key, fields, user["org_id"], user["source_key"])

        # Persist to database (write-through cache)
        from app.services.draft_store import upsert_draft
        await upsert_draft(
            org_id=user["org_id"],
            user_id=user["user_id"],
            intent_key=intent_key,
            fields=fields,
            stage=stage,
            source_key=user["source_key"],
        )

        # Return session patch for webhook to persist
        return {
            "type": "draft_update",
            "intent_key": intent_key,
            "fields": fields,
            "stage": stage,
            "raw_text": message,
            "missing_fields": validation.get("missing_fields", []),
            "complete": validation.get("complete", False)
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
            "details": details,
            "stage": "awaiting_confirmation"
        }

    elif tool_name == "manage_schedule":
        from app.scheduler.jobs import (
            create_scheduled_report, list_scheduled_reports,
            pause_scheduled_report, resume_scheduled_report,
            delete_scheduled_report, compute_next_run
        )
        import datetime as _dt

        action = tool_input.get("action")

        if action == "create":
            query_text    = tool_input.get("query_text", "")
            report_label  = tool_input.get("report_label", query_text[:50])
            schedule_type = tool_input.get("schedule_type", "daily")
            delivery      = tool_input.get("delivery", "whatsapp")
            hour          = tool_input.get("hour")
            minute        = tool_input.get("minute", 0)
            day_of_week   = tool_input.get("day_of_week")
            day_of_month  = tool_input.get("day_of_month")
            interval_mins = tool_input.get("interval_minutes")

            if not query_text:
                return "ERROR: query_text is required to create a schedule"

            result = await create_scheduled_report(
                org_id=user["org_id"],
                user_id=user["user_id"],
                phone=phone,
                email=user.get("email", ""),
                query_text=query_text,
                report_label=report_label,
                schedule_type=schedule_type,
                delivery=delivery,
                interval_minutes=interval_mins,
                hour=hour,
                minute=minute,
                day_of_week=day_of_week,
                day_of_month=day_of_month,
                source_key=user["source_key"],
            )
            next_run_ist = result["next_run_at"].astimezone(
                _dt.timezone(  # type: ignore
                    _dt.timedelta(hours=5, minutes=30)
                )
            )
            return {
                "type": "schedule_created",
                "id": result["id"],
                "report_label": report_label,
                "schedule_type": schedule_type,
                "next_run": next_run_ist.strftime("%d %b %Y at %I:%M %p IST")
            }

        elif action == "list":
            rows = await list_scheduled_reports(user["user_id"])
            if not rows:
                return {"type": "schedule_list", "schedules": [], "count": 0}
            schedules = []
            for r in rows:
                next_run = r["next_run_at"]
                if next_run:
                    try:
                        next_run_ist = next_run.astimezone(
                            _dt.timezone(_dt.timedelta(hours=5, minutes=30))
                        )
                        next_str = next_run_ist.strftime("%d %b at %I:%M %p")
                    except Exception:
                        next_str = str(next_run)
                else:
                    next_str = "—"
                schedules.append({
                    "id": str(r["id"]),
                    "label": r["report_label"],
                    "schedule_type": r["schedule_type"],
                    "active": r["is_active"],
                    "next_run": next_str,
                    "run_count": r["run_count"]
                })
            return {"type": "schedule_list", "schedules": schedules, "count": len(schedules)}

        elif action in ("pause", "resume", "delete"):
            report_id = tool_input.get("report_id")
            if not report_id:
                # No ID given — try to match by label from the list
                rows = await list_scheduled_reports(user["user_id"])
                if not rows:
                    return f"ERROR: No schedules found for this user"
                # Return the list so the LLM can pick the right one
                schedules = [{"id": str(r["id"]), "label": r["report_label"],
                              "schedule_type": r["schedule_type"],
                              "hour": r["hour"], "minute": r["minute"],
                              "active": r["is_active"]} for r in rows]
                return {
                    "type": "schedule_list_for_action",
                    "action": action,
                    "schedules": schedules,
                    "message": f"Multiple schedules found. Use the id field to {action} the correct one."
                }
            if action == "pause":
                ok = await pause_scheduled_report(report_id, user["user_id"])
            elif action == "resume":
                ok = await resume_scheduled_report(report_id, user["user_id"])
            else:
                ok = await delete_scheduled_report(report_id, user["user_id"])
            if not ok:
                # ID might be correct but user_id check failed — try without user check
                # (could happen if scheduled by a different session)
                try:
                    if action == "pause":
                        await execute(
                            "UPDATE scheduled_reports SET is_active = false WHERE id = $1 AND org_id = $2",
                            report_id, user["org_id"], source_key=user["source_key"]
                        )
                    elif action == "resume":
                        await execute(
                            "UPDATE scheduled_reports SET is_active = true WHERE id = $1 AND org_id = $2",
                            report_id, user["org_id"], source_key=user["source_key"]
                        )
                    else:
                        await execute(
                            "DELETE FROM scheduled_reports WHERE id = $1 AND org_id = $2",
                            report_id, user["org_id"], source_key=user["source_key"]
                        )
                    ok = True
                except Exception:
                    ok = False
            return {"type": f"schedule_{action}", "success": ok, "report_id": report_id}

        return "ERROR: Unknown manage_schedule action"

    elif tool_name == "send_to_user":
        from app.services.whatsapp import send_text as _send_text, send_document as _send_doc
        recipient_phone = tool_input.get("recipient_phone", "")
        recipient_name  = tool_input.get("recipient_name", "someone")
        message         = tool_input.get("message", "")
        sender_name     = tool_input.get("sender_name") or user.get("user_name", "A colleague")

        if not recipient_phone or not message:
            return "ERROR: recipient_phone and message are required"

        # Validate phone against users table — prevents wrong numbers from context bleed
        valid = await fetch_one(
            "SELECT name, phone FROM users WHERE org_id = $1 AND phone = $2",
            user["org_id"], recipient_phone, source_key=user["source_key"]
        )
        if not valid:
            return (
                f"ERROR: {recipient_phone} is not a registered user in this org. "
                f"You MUST query the users table to get the correct phone for {recipient_name} "
                f"before calling send_to_user."
            )

        confirmed_name = valid["name"]
        try:
            header = f"📨 *Message from {sender_name}:*\n\n"
            await _send_text(recipient_phone, header + message)
            return {
                "type": "sent_to_user",
                "recipient": confirmed_name,
                "recipient_phone": recipient_phone,
                "success": True
            }
        except Exception as e:
            return f"ERROR sending to {confirmed_name}: {str(e)}"


async def _summarize_turns(conversation_history: list, existing: str | None = None) -> str:
    """Summarize overflow conversation turns using a cheap LLM call."""
    if not conversation_history:
        return existing or ""
    
    # Build a simple summary from the conversation
    # For now, just concatenate key points - could be enhanced with LLM call
    summary_parts = []
    for msg in conversation_history[-5:]:  # Last 5 messages for summary
        role = msg.get("role", "")
        content = msg.get("content", "")
        if content:
            summary_parts.append(f"{role}: {content[:200]}")
    
    summary = " | ".join(summary_parts)
    if existing:
        summary = f"{existing} | {summary}"
    return summary


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
        greeting_data = await _build_greeting_response_with_menu(user, msg_stripped)
        history_to_save = [{"role": "user", "content": message}]
        # Return special marker for webhook to send interactive menu
        return greeting_data["text"], history_to_save, {
            "_send_menu": True,
            "menu_sections": greeting_data["menu_sections"],
            "button_label": greeting_data["button_label"]
        }

    if _is_help_request(msg_stripped):
        help_text = await _build_help_response(user)
        history_to_save = [{"role": "user", "content": message},
                           {"role": "assistant", "content": help_text}]
        return help_text, history_to_save, {}
    
    # ── Fast-path: direct workflow execution by intent_key ─────────────────
    # If message is exactly a workflow intent_key the user has permission for, execute it
    from app.db import fetch_all as _fetch_all
    perms = set(user.get("permissions", []))
    workflows = await _fetch_all(
        "SELECT intent_key, name, workflow_type, sql_template, entity_schema, "
        "sql_params_order, response_format, business_glossary, llm_system_prompt, "
        "pdf_config, response_template, otp_required, otp_threshold, approval_threshold, "
        "steps, calc_rules "
        "FROM workflows WHERE org_id = $1 AND is_active = true",
        user["org_id"], source_key=user["source_key"]
    )
    workflow_map = {w["intent_key"]: dict(w) for w in workflows if w["intent_key"] in perms}
    
    if msg_stripped in workflow_map:
        wf = workflow_map[msg_stripped]
        print(f"[AGENT] Direct workflow execution: {wf['intent_key']}")
        # Execute read workflow directly (no entities)
        if wf["workflow_type"] == "read" and not wf.get("entity_schema"):
            from app.services.query_engine import execute_query
            result = await execute_query(
                sql=wf["sql_template"],
                params=[user["org_id"]],
                user=user,
                response_format=wf.get("response_format", "generic"),
                business_glossary=wf.get("business_glossary", {})
            )
            history_to_save = [{"role": "user", "content": message}]
            return result, history_to_save, {}
        else:
            # For workflows with entities or action workflows, let agent handle it
            # Prepend a clear instruction
            message = f"Execute the {wf['name']} workflow."
    
    # ── Fast-path: clarify selection handling ────────────────────────────────
    # If user sent a number and previous message was a clarify, extract the selection
    if conversation_history:
        # Find the most recent assistant message
        last_assistant_msg = next(
            (m for m in reversed(conversation_history) if m.get("role") == "assistant"),
            None
        )
        last_assistant = last_assistant_msg.get("content", "") if last_assistant_msg else ""

        if "🤔" in last_assistant:
            # User is responding to a clarify menu
            if msg_stripped.lower() in ("all", "all of them", "summary", "all customers", "sab"):
                # User wants all options - append this context
                message = "Show results for all options (summary)"
            elif msg_stripped.isdigit():
                # User is selecting a specific option
                lines = last_assistant.split("\n")
                selected_option = None
                for line in lines:
                    stripped_line = line.strip()
                    if stripped_line.startswith(msg_stripped + ".") or \
                       stripped_line.startswith(msg_stripped + " "):
                        selected_option = stripped_line[len(msg_stripped):].lstrip(". ").strip()
                        break
                if selected_option:
                    # Provide the full context: what the user was doing + what they picked
                    draft_intent = (pending_action or {}).get("intent_key", "the previous request")
                    message = (
                        f"User selected option {msg_stripped}: {selected_option}. "
                        f"Continue with {draft_intent} for this customer/selection."
                    )
    # ─────────────────────────────────────────────────────────────────────────
    
    # Format pending action context for LLM
    def _format_pending_action_context(pending_action: dict | None) -> str:
        if not pending_action:
            return ""
        fields = pending_action.get("fields") or {}
        correction = pending_action.get("correction_hint", "")
        correction_line = (
            f"\nUser just said: \"{correction}\" — treat this as a correction to the draft above. "
            "Update only the relevant field(s), keep everything else.\n"
        ) if correction else ""
        return (
            "\n=== ACTIVE DRAFT (from this conversation — do NOT discard or replace unless user changes it) ===\n"
            f"Intent: {pending_action.get('intent_key')}\n"
            f"Stage: {pending_action.get('stage', 'collecting')}\n"
            f"Collected fields: {json.dumps(fields, default=str)}\n"
            f"{correction_line}"
            "Only ask for fields NOT listed above. Never invent values not provided by the user.\n"
            "=== END ACTIVE DRAFT ===\n"
        )

    # ── Context limit + summary ────────────────────────────────────────────────
    limit = user.get("context_message_limit") or 12
    draft_summary = None
    if pending_action:
        from app.services.draft_store import get_active_draft
        db_draft = await get_active_draft(user["org_id"], user["user_id"], user["source_key"])
        if db_draft:
            draft_summary = db_draft.get("conversation_summary")
    
    if len(conversation_history) > limit:
        overflow = conversation_history[:-limit]
        # Fold dropped turns into a rolling summary (one cheap LLM call)
        summary = await _summarize_turns(overflow, existing=draft_summary)
        # Update draft summary if a draft is active
        if pending_action:
            from app.services.draft_store import upsert_draft
            # Parse fields if it's a JSON string from DB
            fields = pending_action.get("fields", {})
            if isinstance(fields, str):
                try:
                    fields = json.loads(fields)
                except (json.JSONDecodeError, TypeError):
                    fields = {}
            await upsert_draft(
                org_id=user["org_id"],
                user_id=user["user_id"],
                intent_key=pending_action.get("intent_key"),
                fields=fields,
                stage=pending_action.get("stage", "collecting"),
                summary=summary,
                source_key=user["source_key"],
            )
        conversation_history = conversation_history[-limit:]
    
    # Inject summary into system prompt if it exists
    if draft_summary:
        # This will be added to the system prompt in _build_system_prompt
        pass

    try:
        system_prompt = await _build_system_prompt(user)
        print(f"[AGENT] System prompt built, length: {len(system_prompt)}")
    except Exception as e:
        print(f"[AGENT] Error building system prompt: {e}")
        import traceback
        traceback.print_exc()
        return f"Error building system prompt: {str(e)}", [], {}

    # Abandon stale collecting drafts — they belong to old conversations
    if _is_draft_stale(pending_action):
        print(f"[AGENT] Stale draft detected (intent={pending_action.get('intent_key')}) — abandoning")
        pending_action = None
        # Note: webhook will clean it up from session on next session_patch write

    # Inject prior conversation (last N turns)
    messages = [
        {"role": "system", "content": system_prompt}  # clean system prompt, no draft appended
    ]

    if conversation_history:
        messages.extend(conversation_history)

    # Inject active draft as the most recent assistant context — gets higher attention than system
    if pending_action and not _is_draft_stale(pending_action):
        fields = pending_action.get("fields") or {}
        stage = pending_action.get("stage", "collecting")
        correction = pending_action.get("correction_hint", "")
        correction_line = (
            f"\nThe user just said: \"{correction}\" — this is a correction. "
            "Update only the relevant field(s), keep everything else intact.\n"
        ) if correction else ""

        draft_msg = (
            f"[ACTIVE DRAFT — intent: {pending_action.get('intent_key')}, stage: {stage}]\n"
            f"Already collected: {json.dumps(fields, default=str)}\n"
            f"{correction_line}"
            "Only ask for fields NOT listed above. Never re-ask for already-collected data."
        )
        messages.append({"role": "assistant", "content": draft_msg})

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
            content = assistant_message.content or ""

            # Intercept: LLM printed a ⚠️ Confirm block as plain text instead of
            # calling confirm_action tool. This happens when all info is given in one
            # message and the model skips tool-calling. Inject a corrective message
            # and retry so the draft gets properly saved to Redis.
            if "⚠️" in content and ("confirm" in content.lower() or "yes" in content.lower()):
                # Only intercept if there's a draft being collected
                active_draft = session_patch.get("pending_action") or pending_action
                if active_draft and active_draft.get("stage") in ("collecting", "awaiting_confirmation"):
                    print(f"[AGENT] Intercepted plain-text confirm block — forcing tool retry")
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user",
                        "content": (
                            "SYSTEM CORRECTION: You printed the confirmation block as plain text. "
                            "This does NOT work — the user's 'yes' cannot be detected without the tool. "
                            "You MUST now call update_draft (with all collected fields and "
                            "stage='awaiting_confirmation') followed immediately by confirm_action. "
                            "Use the exact same details you just showed. Do it now."
                        )
                    })
                    continue  # retry this iteration

            # Intercept: LLM printed a ✅ Scheduled confirmation as plain text instead of
            # calling manage_schedule tool. Nothing gets saved to DB in this case.
            # IMPORTANT: only intercept if manage_schedule create was NOT already called
            # successfully in this iteration — otherwise we'd create duplicates.
            schedule_created_this_turn = session_patch.get("_schedule_created_this_turn", False)
            if (
                not schedule_created_this_turn
                and ("✅ Scheduled" in content or ("scheduled" in content.lower() and "first delivery" in content.lower()))
            ):
                print(f"[AGENT] Intercepted plain-text schedule confirmation — forcing tool retry")
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": (
                        "SYSTEM CORRECTION: You printed the schedule confirmation as plain text. "
                        "Nothing was saved — the schedule does NOT exist yet. "
                        "You MUST call the manage_schedule tool with action='create' and all the "
                        "details you just described. Do it now."
                    )
                })
                continue  # retry this iteration

            print(f"[AGENT] No tool calls, returning text response: {content[:200]}")
            history_to_save = _serialize_history(messages)
            return content.strip(), history_to_save, session_patch

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
            # Bug 12 fix: catch per-tool exceptions so a failing tool (e.g. generate_pdf
            # network error) doesn't propagate out of run_agent and lose session_patch
            # that was accumulated from earlier update_draft calls in the same turn.
            try:
                result = await _execute_tool(
                    tool_name=tool_call.function.name,
                    tool_input=json.loads(tool_call.function.arguments),
                    user=user,
                    phone=phone,
                    message=message
                )
            except Exception as tool_err:
                print(f"[AGENT] Tool {tool_call.function.name} raised: {tool_err}")
                import traceback as _tb; _tb.print_exc()
                result = f"ERROR: {tool_err}"
            result_str = str(result)[:100] if result else "None"
            print(f"[AGENT] Tool result: {result_str}...")

            # Convert dict results to JSON string for OpenAI API
            content = json.dumps(result) if isinstance(result, dict) else str(result)
            tool_results.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "content": content
            })

            # Track if manage_schedule create succeeded this turn — prevents
            # the plain-text intercept from firing again and creating duplicates
            if (
                tool_call.function.name == "manage_schedule"
                and isinstance(result, dict)
                and result.get("type") == "schedule_created"
            ):
                session_patch["_schedule_created_this_turn"] = True

            # If this was a clarify call, stop the loop
            if tool_call.function.name == "clarify":
                clarify_question = json.loads(tool_call.function.arguments).get("question", "")
                options = json.loads(tool_call.function.arguments).get("options", [])
                if options:
                    opts = "\n".join(
                        f"{i+1}. {o}" for i, o in enumerate(options)
                    )
                    history_to_save = _serialize_history(messages)
                    clarify_text = f"🤔 {clarify_question}\n\n{opts}"
                    history_to_save.append({"role": "assistant", "content": clarify_text})
                    return clarify_text, history_to_save, session_patch  # Fix 2: return session_patch
                history_to_save = _serialize_history(messages)
                clarify_text = f"🤔 {clarify_question}"
                history_to_save.append({"role": "assistant", "content": clarify_text})
                return clarify_text, history_to_save, session_patch  # Fix 2: return session_patch

            # If this was a show_menu call, return menu data
            if tool_call.function.name == "show_menu":
                from app.services.menu import build_menu_sections
                sections = await build_menu_sections(user["org_id"], user)
                menu_text = "📋 Here's what you can do:"
                history_to_save = _serialize_history(messages)
                history_to_save.append({"role": "assistant", "content": menu_text})
                return menu_text, history_to_save, {
                    "_send_menu": True,
                    "menu_sections": sections,
                    "button_label": "📋 Menu"
                }

            # If update_draft was called, capture session patch
            if tool_call.function.name == "update_draft":
                if isinstance(result, dict) and result.get("type") == "draft_update":
                    # Build pending_action from result
                    current_draft = pending_action or {}
                    old_fields = current_draft.get("fields", {})
                    # Ensure old_fields is a dict (might be JSON string from DB or corrupted list)
                    if isinstance(old_fields, str):
                        try:
                            old_fields = json.loads(old_fields)
                        except (json.JSONDecodeError, TypeError):
                            old_fields = {}
                    if not isinstance(old_fields, dict):
                        print(f"[AGENT] Corrupted old_fields detected (type={type(old_fields).__name__}) — resetting")
                        old_fields = {}
                    new_fields = result.get("fields", {})

                    # Deep-merge items array: if the correction only contains partial
                    # item data (e.g. just making_charges), merge into each existing
                    # item rather than replacing the whole array.
                    merged_fields = {**old_fields}
                    for k, v in new_fields.items():
                        if (
                            k == "items"
                            and isinstance(v, list)
                            and isinstance(old_fields.get("items"), list)
                            and len(old_fields["items"]) > 0
                        ):
                            old_items = old_fields["items"]
                            new_items = v
                            # If correction has fewer items than original, it's a partial
                            # patch — merge each new item's keys into the corresponding
                            # existing item by index.
                            if len(new_items) <= len(old_items):
                                merged_items = []
                                for i, old_item in enumerate(old_items):
                                    if i < len(new_items):
                                        # new_items[i] may only have changed keys — merge
                                        merged_items.append({**old_item, **new_items[i]})
                                    else:
                                        merged_items.append(old_item)
                                merged_fields["items"] = merged_items
                            else:
                                # More items than before — full replacement is intentional
                                merged_fields["items"] = v
                        else:
                            merged_fields[k] = v

                    updated_draft = {
                        "intent_key": result.get("intent_key") or current_draft.get("intent_key"),
                        "stage": result.get("stage") or current_draft.get("stage", "collecting"),
                        "fields": merged_fields,
                        "raw_text": result.get("raw_text", message),
                        "created_at": current_draft.get("created_at") or __import__("datetime").datetime.now().isoformat()
                    }
                    # Reset reprompt_count whenever fields actually advance
                    if new_fields and any(k not in old_fields or old_fields[k] != v for k, v in new_fields.items()):
                        updated_draft["reprompt_count"] = 0
                    else:
                        updated_draft["reprompt_count"] = current_draft.get("reprompt_count", 0)
                    session_patch["pending_action"] = updated_draft
                    pending_action = updated_draft  # Fix 1: refresh local var for subsequent iterations
                # Continue loop to let LLM respond with confirmation or next question

            # If confirm_action was called, pause and return the prompt
            if tool_call.function.name == "confirm_action":
                if isinstance(result, dict) and result.get("type") == "confirm_pending":
                    # Update session patch with stage from confirm_action result
                    if result.get("stage"):
                        if not session_patch.get("pending_action"):
                            session_patch["pending_action"] = pending_action or {}
                        session_patch["pending_action"]["stage"] = result["stage"]
                    
                    # Validate draft is complete before allowing confirmation
                    draft = session_patch.get("pending_action") or pending_action or {}

                    # QA verification: validate + recompute via calc_rules
                    # This catches missing fields AND silently corrects LLM arithmetic
                    from app.services.qa_verifier import verify_draft, VerificationError, diff_for_audit, _validate_schema
                    workflow_row = await fetch_one(
                        "SELECT * FROM workflows WHERE intent_key=$1 AND org_id=$2 AND is_active=true",
                        draft.get("intent_key"), user["org_id"], source_key=user["source_key"]
                    )
                    if not workflow_row:
                        tool_results[-1]["content"] = json.dumps({
                            "error": f"Workflow '{draft.get('intent_key')}' not found. Cannot confirm."
                        })
                        break

                    # Check if workflow has ai_price_interpret step
                    steps = _parse_jsonb(workflow_row.get("steps"), []) or []
                    has_price_interp = any(
                        (json.loads(s) if isinstance(s, str) else s).get("op") == "ai_price_interpret"
                        for s in steps
                    )

                    if has_price_interp:
                        # Only validate presence of raw required fields (customer_name, items[].description,
                        # items[].weight, etc.) — skip calc_rules entirely; unit_price isn't resolved yet.
                        entity_schema = _parse_jsonb(workflow_row.get("entity_schema"), {})
                        missing, invalid = _validate_schema(entity_schema, draft.get("fields", {}))
                        if missing or invalid:
                            tool_results[-1]["content"] = json.dumps({
                                "error": f"Missing: {missing}. Invalid: {invalid}. Ask the user for these before confirming."
                            })
                            break
                        verified_fields = draft.get("fields", {})   # unresolved rate_text stays as-is; resolved at execution time
                    else:
                        try:
                            verified_fields = await verify_draft(
                                dict(workflow_row), draft.get("fields", {}), user["org_id"], user["source_key"]
                            )
                        except VerificationError as e:
                            missing_str = ", ".join(e.missing_fields + e.invalid_fields)
                            tool_results[-1]["content"] = json.dumps({
                                "error": (
                                    f"Draft incomplete/invalid. Missing: {e.missing_fields}. "
                                    f"Invalid: {e.invalid_fields}. "
                                    f"Ask the user for: {missing_str} before calling confirm_action again."
                                )
                            })
                            break

                    # Log any corrections the QA layer made
                    mismatches = diff_for_audit(draft.get("fields", {}), verified_fields)
                    if mismatches:
                        print(f"[QA] Corrected LLM-drafted values before confirmation: {mismatches}")

                    # Store verified fields — these are what gets executed, not the LLM's originals
                    draft["fields"] = verified_fields
                    draft["stage"]  = "awaiting_confirmation"
                    session_patch["pending_action"] = draft
                action_desc = json.loads(tool_call.function.arguments).get("action_description", "")
                details = json.loads(tool_call.function.arguments).get("details", {})
                lines = [f"⚠️ *Confirm Action*\n\n{action_desc}"]
                if details:
                    for k, v in details.items():
                        lines.append(f"  • {k}: {v}")
                lines.append("\nReply *yes* to confirm or *no* to cancel.")
                confirm_text = "\n".join(lines)
                history_to_save = _serialize_history(messages)
                history_to_save.append({"role": "assistant", "content": confirm_text})
                return confirm_text, history_to_save, session_patch

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
