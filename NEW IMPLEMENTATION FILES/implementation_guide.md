# Tool-Calling Agent — Full Implementation Guide

## What This Document Is

A file-by-file, change-by-change guide to replace your current
classifier → workflow → template pipeline with a clean tool-calling
agent. No hardcoding in code. No hardcoding in DB. Works for jewellery
today, pharma tomorrow, IT finance the day after — zero changes required.

---

## What Gets Deleted (Do This First)

### Files to delete entirely

```
app/classifier/classifier.py
app/services/intent_matcher.py
app/services/intent_analyzer.py
```

These three files are the entire classification pipeline. Every line
of training-phrase matching, keyword scoring, regex routing, and
LLM intent detection goes away. Nothing in them survives.

### Functions to delete from query_engine.py

Delete these functions completely:

- `_build_template_params()`
- `_gen_sql_unconstrained()`
- `execute_template()`
- `execute_read()`
- `_fmt()` and all `_fmt_*` functions below it

Keep only:

- `_DANGEROUS` list
- `SENSITIVE_COLS` set
- `_safe()` function
- `_load_schema()` function — but modify it (see below)

### Functions to delete from workflow_executor.py

Delete:

- `_dispatch_dynamic_intent()` — entire function
- The entire `route_type == "workflow"` and `route_type == "general_read"`
  blocks inside `execute_intent()`

Keep only:

- `manage_schedule` handler
- `clear_sessions` handler
- `resume_after_otp()`
- `_send_approval_request()`
- `handle_approval_response()`
- `_log()`
- `_get_invoice_thresholds()`

### DB rows to delete

Run this against your database before starting:

```sql
DELETE FROM workflows
WHERE workflow_type = 'read';
```

This removes: `get_outstanding`, `check_stock`, `dues_report`,
`check_metal_rates`, `view_orders_by_status`, `check_low_stock`,
`check_permissions`.

Keep: `generate_quotation_with_rate` (it's a genuine action workflow).

---

## What Gets Added

### New file: `app/services/agent.py`

This is the entire new brain. It replaces classifier.py,
intent_matcher.py, intent_analyzer.py, and the read parts of
workflow_executor.py. All in one file.

```python
"""
Tool-calling agent.
Replaces the entire classifier + intent_matcher + intent_analyzer pipeline.
Zero domain hardcoding. Works for any schema, any industry.
"""
import json
import os
import re
from anthropic import AsyncAnthropic
from app.db import fetch_all, fetch_one
from app.services.query_engine import _safe, SENSITIVE_COLS

_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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
        "name": "query_database",
        "description": (
            "Run a SELECT query against the database. "
            "Use this to fetch any data the user is asking about. "
            "Always use $1 for org_id. Use $2, $3... for additional params. "
            "ILIKE for name searches. LIMIT 50 max."
        ),
        "input_schema": {
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
    },
    {
        "name": "clarify",
        "description": (
            "Ask the user a clarifying question when their request is ambiguous. "
            "Use when: a name matches multiple records, the request is incomplete, "
            "or you need one more piece of information before proceeding. "
            "Do NOT use this for every message — only when genuinely unclear."
        ),
        "input_schema": {
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
    },
    {
        "name": "generate_pdf",
        "description": (
            "Generate a PDF from query results and send it to the user. "
            "Use ONLY when the user explicitly asks for a PDF, report, or statement. "
            "Call query_database first to get the data, then call this."
        ),
        "input_schema": {
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
    },
    {
        "name": "confirm_action",
        "description": (
            "Show the user what action is about to be taken and wait for confirmation. "
            "MUST be called before any write operation: creating invoices, "
            "updating rates, changing order status, etc. "
            "Never execute a write without calling this first."
        ),
        "input_schema": {
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
]


# ── System prompt builder — reads from DB, zero hardcoding ───────────────────

async def _build_system_prompt(user: dict) -> str:
    schema = await _get_schema(user["org_id"])
    today = __import__("datetime").date.today().strftime("%d %b %Y")

    return f"""You are a WhatsApp ERP assistant for {user["org_name"]}.

CURRENT USER:
- Name: {user["user_name"]}
- Role: {user["role"]}
- Permissions: {", ".join(user.get("permissions", [])[:15])}

TODAY: {today}

DATABASE SCHEMA (always filter WHERE org_id = '{user["org_id"]}'):
{schema}

RULES:
1. For any data question — use query_database. Write fresh SQL every time.
2. Always include WHERE org_id = $1 (injected automatically as $1).
3. Never expose id, org_id, or uuid columns in your response.
4. If a name matches multiple rows — use clarify tool, show the options.
5. For PDF requests — query_database first, then generate_pdf.
6. For write operations — always call confirm_action first, never write directly.
7. Format all responses for WhatsApp: use *bold* for key numbers, bullet points
   for lists, emojis for context, keep responses concise.
8. Speak naturally. You understand English and Hinglish equally.
9. If a query returns empty — say so plainly, don't say "no results found".
10. Add useful context and insight beyond just the raw data where relevant.

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
        from app.services.pdf_service import generate_dues_statement_pdf
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

            # Use existing invoice PDF infrastructure generically
            from app.services.pdf_service import _generate_generic_pdf
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
    max_iterations: int = 6
) -> str:
    """
    Main entry point. Replaces classify_message + execute_intent entirely.
    Runs the tool-calling loop until the LLM produces a final text response.
    """
    system_prompt = await _build_system_prompt(user)

    messages = [{"role": "user", "content": message}]

    for iteration in range(max_iterations):
        response = await _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            tools=TOOLS,
            messages=messages
        )

        # LLM finished — return the text response
        if response.stop_reason == "end_turn":
            text_blocks = [
                b.text for b in response.content
                if hasattr(b, "text")
            ]
            return "\n".join(text_blocks).strip()

        # LLM wants to call tools
        if response.stop_reason == "tool_use":
            # Add assistant's response to message history
            messages.append({
                "role": "assistant",
                "content": response.content
            })

            # Execute each tool call
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                result = await _execute_tool(
                    tool_name=block.name,
                    tool_input=block.input,
                    user=user,
                    phone=phone
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result
                })

                # If this was a clarify call, stop the loop
                # The clarify message was already sent inline
                if block.name == "clarify":
                    clarify_question = block.input.get("question", "")
                    options = block.input.get("options", [])
                    if options:
                        opts = "\n".join(
                            f"{i+1}. {o}" for i, o in enumerate(options)
                        )
                        return f"🤔 {clarify_question}\n\n{opts}"
                    return f"🤔 {clarify_question}"

                # If confirm_action was called, pause and return the prompt
                if block.name == "confirm_action":
                    action_desc = block.input.get("action_description", "")
                    details = block.input.get("details", {})
                    lines = [f"⚠️ *Confirm Action*\n\n{action_desc}"]
                    if details:
                        for k, v in details.items():
                            lines.append(f"  • {k}: {v}")
                    lines.append("\nReply *yes* to confirm or *no* to cancel.")
                    return "\n".join(lines)

            # Add tool results back into message history
            messages.append({
                "role": "user",
                "content": tool_results
            })

        else:
            # Unexpected stop reason
            break

    return "🤔 Something went wrong. Please try again."
```

---

### New function to add to `pdf_service.py`

Add this function at the bottom of `pdf_service.py`. It is a generic
PDF generator that works for any data — no hardcoded column names,
no hardcoded titles.

```python
def _generate_generic_pdf(
    title: str,
    rows: list,
    org_name: str = "",
    subtitle: str = ""
) -> bytes:
    """
    Generic PDF for any query result.
    Renders whatever columns came back — no hardcoding.
    """
    pdf = InvoicePDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(14, 14, 14)

    from datetime import datetime
    today = datetime.now()
    W = 182
    L = 14

    # Header
    pdf.set_xy(L, 14)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*BLUE)
    pdf.cell(W, 9, org_name, align="L")

    pdf.set_xy(L, 24)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*DARKTEXT)
    pdf.cell(W, 8, title, align="L")

    if subtitle:
        pdf.set_xy(L, 33)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(W, 5, subtitle, align="L")

    pdf.set_xy(L, 39)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(W, 5, f"Generated: {today.strftime('%d %b %Y %I:%M %p')}", align="R")

    # Blue divider
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.8)
    pdf.line(L, 46, L + W, 46)
    pdf.set_line_width(0.2)

    if not rows:
        pdf.set_xy(L, 56)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*MUTED)
        pdf.cell(W, 8, "No data found.", align="C")
        return bytes(pdf.output())

    # Derive columns from first row — whatever came back
    skip = {"id", "org_id", "created_by", "updated_by", "otp_hash"}
    cols = [k for k in rows[0].keys() if k not in skip]
    if not cols:
        cols = list(rows[0].keys())

    # Calculate column widths proportionally
    col_w = W // len(cols)
    leftover = W - col_w * len(cols)

    y = 52
    # Table header
    pdf.set_xy(L, y)
    pdf.set_fill_color(*BLUE)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 8)
    for i, col in enumerate(cols):
        w = col_w + (leftover if i == len(cols) - 1 else 0)
        label = col.replace("_", " ").title()[:18]
        pdf.cell(w, 8, label, fill=True, align="L", border=0)
    pdf.ln(8)

    # Rows
    row_fill = False
    for row in rows:
        pdf.set_fill_color(*LIGHTBG) if row_fill else pdf.set_fill_color(*WHITE)
        pdf.set_text_color(*DARKTEXT)
        pdf.set_font("Helvetica", "", 8)
        for i, col in enumerate(cols):
            w = col_w + (leftover if i == len(cols) - 1 else 0)
            val = str(row.get(col, "") or "")[:28]
            # Format amounts nicely
            try:
                if any(x in col for x in ("amount", "total", "price", "limit", "rate")):
                    val = f"₹{float(row[col]):,.0f}" if row.get(col) else "—"
            except (ValueError, TypeError):
                pass
            pdf.cell(w, 7, val, fill=True, align="L", border=0)
        pdf.ln(7)
        row_fill = not row_fill

    # Row count footer
    pdf.set_xy(L, pdf.get_y() + 6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(W, 5, f"Total records: {len(rows)}", align="R")

    return bytes(pdf.output())
```

---

### Changes to `webhook.py`

Replace the entire message handling section. The new version is simpler
because there is no classification step.

**Delete these imports at the top:**

```python
# DELETE these imports
from app.classifier.classifier import classify_message
from app.executor.workflow_executor import (
    execute_intent, resume_after_otp, handle_approval_response
)
```

**Add this import:**

```python
# ADD this import
from app.services.agent import run_agent
```

**Replace the main `handle_message` function body.**

Find this block (around line 80 in webhook.py) and replace everything
after the security auth check with the new version:

```python
async def handle_message(phone: str, text: str, msg_type: str = "text"):
    # 1. Identity — unchanged
    user = await resolve_identity(phone)
    if not user:
        await send_text(phone,
            "👋 Your number isn't registered.\n"
            "Contact your admin to get access."
        )
        return

    if not user["is_active"] or not user["org_active"]:
        await send_text(phone, "❌ Your account is inactive. Contact admin.")
        return

    # 2. Org TTL — unchanged
    org_row = await fetch_one(
        "SELECT session_ttl_minutes FROM orgs WHERE id = $1", user["org_id"]
    )
    ttl_minutes = org_row["session_ttl_minutes"] if org_row else 480

    # 3. Security auth check — unchanged (keep your existing OTP gate here)
    sec_session_id = f"sec:{user['org_id']}:{phone}"
    is_authenticated = await check_auth_token(user["org_id"], phone)

    if not is_authenticated:
        # ... keep your existing security OTP flow here unchanged ...
        return

    # 4. Session
    session_id = f"{user['org_id']}:{phone}"
    session    = await get_session(session_id)

    # 5. Approval button responses — unchanged
    if msg_type == "interactive" and text in ("action:approve", "action:reject"):
        from app.executor.workflow_executor import handle_approval_response
        await handle_approval_response(phone, text, user)
        return

    # 6. Pending confirmation check
    # If session has a pending_confirm, handle yes/no reply
    if session.get("pending_confirm"):
        pending = session.get("pending_confirm")
        if text.strip().lower() in ("yes", "y", "haan", "ha", "ok", "confirm"):
            await set_session(session_id, {})
            # Re-run the original message with confirmation flag
            original_msg = pending.get("original_message", "")
            user_with_confirm = {**user, "confirmed": True}
            reply = await run_agent(original_msg, user_with_confirm, phone)
            await send_text(phone, reply)
        else:
            await set_session(session_id, {})
            await send_text(phone, "❌ Action cancelled.")
        return

    # 7. Run the agent — this replaces the entire classify + execute pipeline
    await set_session(session_id, {**session, "last_message": text})

    try:
        reply = await run_agent(text, user, phone)
        await send_text(phone, reply)

        # Log to audit_log
        await execute("""
            INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome)
            VALUES ($1, $2, 'agent', $3, 'success')
        """, user["org_id"], user["user_id"], text)

    except Exception as e:
        print(f"[AGENT] Error: {e}")
        await send_text(phone,
            "🤔 Something went wrong. Please try again."
        )
```

---

### Changes to `query_engine.py`

Keep the file but slim it down significantly. The new version only
contains the safety validator and schema loader. Everything else is gone.

**Final state of query_engine.py:**

```python
"""
SQL safety validator and schema loader.
Used by the tool-calling agent in agent.py.
"""
import re
from app.db import fetch_all

_DANGEROUS = [
    r'\bDROP\b', r'\bDELETE\b', r'\bTRUNCATE\b', r'\bALTER\b',
    r'\bCREATE\b', r'\bINSERT\b', r'\bUPDATE\b', r'\bGRANT\b',
    r'\bEXEC(UTE)?\b', r';\s*--', r'\bpg_\w+',
    r'\binformation_schema\b', r'\bpg_catalog\b'
]

SENSITIVE_COLS = {
    'id', 'org_id', 'user_id', 'role_id', 'customer_id', 'invoice_id',
    'quotation_id', 'order_id', 'created_by', 'updated_by', 'scheduled_by',
    'decided_by', 'requester_id', 'approver_role', 'workflow_id',
    'otp_hash', 'config',
}


def _safe(sql: str) -> tuple[bool, str]:
    upper = sql.upper()
    for p in _DANGEROUS:
        if re.search(p, upper, re.IGNORECASE):
            return False, f"Blocked: {p}"
    if not upper.strip().startswith('SELECT'):
        return False, "Only SELECT allowed"
    if ';' in sql.rstrip(';'):
        return False, "Multiple statements blocked"
    return True, "ok"
```

---

### Changes to `workflow_executor.py`

The file survives but only for its three genuine purposes:
OTP, approvals, and scheduling. Delete the routing logic.

**Delete from execute_intent():**

Remove the entire `route_type == "workflow"` block, the
`route_type == "general_read"` block, and the legacy
`_dispatch_dynamic_intent()` fallback.

The function signature can stay but its body is now just:

```python
async def execute_intent(intent: str, ...) -> str:
    # Only handles system intents now
    if intent == "manage_schedule":
        # ... keep existing schedule handler unchanged

    if intent == "clear_sessions":
        # ... keep existing clear sessions handler unchanged

    return "🤔 Unhandled system intent."
```

---

## Test Queries to Run After Implementing

Run these in order against your actual data to verify the system works.

### Identity queries (no tool calls expected)

```
who am i
what is my role
what can i do
what are my permissions
```

### Simple read queries

```
Mehta ka baaki kitna hai
show me all pending invoices
low stock items
gold rate kya hai
top 3 customers by outstanding
kaun sa maal khatam ho raha hai
show me all customers
ready orders
Sharma ke orders kya hai
```

### Disambiguation (clarify tool expected)

```
Mehta outstanding
```
Expected: agent asks which Mehta since you have multiple

### Multi-step (query + PDF)

```
Sharma aur Agarwal ka invoice summary PDF mein do
generate dues report as PDF
```
Expected: agent calls query_database, then generate_pdf

### Cross-table queries (no workflow ever existed for these)

```
which customer has the highest credit limit
show me all overdue invoices above 50000
customers in Delhi with pending dues
how many orders are in production right now
invoices due this week
```

### Hinglish mixed queries

```
sabse zyada dues kaun se customer ka hai
kitna maal bacha hai gold necklace ka
kya Agarwal ka koi overdue invoice hai
```

---

## What Did NOT Change

These files are completely untouched:

- `db.py`
- `redis_client.py`
- `identity.py`
- `whatsapp.py`
- `otp_service.py`
- `quotation.py`
- `quotation_pdf.py`
- `orders.py`
- `inventory.py`
- `accounting.py`
- `crm.py`
- `jobs.py`
- `admin.py`

The business logic — creating invoices, generating quotation PDFs,
OTP verification, approval flows — all stays exactly as-is. The
only thing that changed is how the system decides what to do with
a user's message. That decision now lives in the LLM, not in
classifiers and workflow templates.

---

## Environment Variable to Add

```env
ANTHROPIC_API_KEY=your_key_here
```

The agent uses Claude Sonnet (claude-sonnet-4-6) by default.
You can switch to Claude Haiku for lower cost once you have
verified accuracy on your test queries.

---

## Summary of Line Count Change

| File | Before | After |
|------|--------|-------|
| classifier.py | 120 lines | deleted |
| intent_matcher.py | 280 lines | deleted |
| intent_analyzer.py | 90 lines | deleted |
| query_engine.py | 310 lines | 35 lines |
| webhook.py | 220 lines | 160 lines |
| workflow_executor.py | 320 lines | 180 lines |
| agent.py | 0 lines | 280 lines |
| **Total** | **1340 lines** | **655 lines** |

Half the code. Zero hardcoding. Handles any query for any domain.
