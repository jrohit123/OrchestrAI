# OrchestrAI — Intent + Action Routing: Full Implementation Guide

> **Goal:** Replace regex/`trigger_patterns` routing with a two-path LLM system:
> - **General Read** — ad-hoc DB queries (dues reports, stock, Hindi, top-N) without dedicated workflows
> - **Registered Workflow** — mutations, PDFs, OTP-gated actions via existing adapters
>
> **No pgvector. No new tables. No utterance embeddings.**

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Architecture](#2-architecture)
3. [What Changes vs What Stays](#3-what-changes-vs-what-stays)
4. [Database — Cleanup Only (No Schema Migration)](#4-database--cleanup-only-no-schema-migration)
5. [New Files](#5-new-files)
6. [Code Changes — File by File](#6-code-changes--file-by-file)
7. [Prompt Templates](#7-prompt-templates)
8. [Permission Model](#8-permission-model)
9. [Migration Steps](#9-migration-steps)
10. [Workflows to Create (Admin Panel)](#10-workflows-to-create-admin-panel)
11. [Test Queries — Full Matrix](#11-test-queries--full-matrix)
12. [Testing Checklist](#12-testing-checklist)

---

## 1. The Problem

Current routing in `classifier.py`:

```
Tier 1  exact match (hi, help)
Tier 2  regex — hardcoded + DB trigger_patterns   ← fragile, English-centric
Tier 3  LLM picks intent_key + entity_raw          ← maps "top 3 dues" → get_outstanding + entity "Customers"
```

**Example failure:**

| User says | Current result | Expected |
|-----------|----------------|----------|
| Top 3 dues customer wise | `get_outstanding` → "Which customer?" | Aggregate report, no entity |
| Mehta ka kitna baaki hai | May miss regex | Mehta pending ₹1,07,000 |
| Give me overdue summary | Depends on pattern | All overdue customers |

**Root cause:** The system routes to **intent keys** and extracts **entities**, but many queries are **Read operations** that should never map to a workflow.

---

## 2. Architecture

```
User message
    │
    ▼
Tier 1 — Exact match (hi / help / 1 / 2 / retry)          instant, free
    │ miss
    ▼
Tier 2 — System-only regex (clear_sessions, manage_schedule)  security-critical
    │ miss
    ▼
Intent Analyzer LLM
    │
    ├── route_type: "clarify"     → ask user a question, stop
    │
    ├── route_type: "general_read"
    │       action: Read
    │       intent: plain-English query plan
    │       ▼
    │   Safe Query Engine (allowlisted tables, org_id scoped, SELECT only)
    │       ▼
    │   Formatted WhatsApp reply
    │
    └── route_type: "workflow"
            action: Create | Update | Delete | Execute
            workflow_key: e.g. create_invoice
            parameters: {customer_name, amount, ...}
            ▼
        Permission check (workflow_key + action)
            ▼
        workflow_executor → adapter_method
```

### Design rules

| Query type | Route | Example |
|------------|-------|---------|
| Lookup / report / aggregate | `general_read` | "top 3 dues", "stock gold ring", "Mehta ka kitna" |
| Create invoice / order / quotation | `workflow` | "invoice Mehta 45000", Tanishq bangle quote |
| Send PDF | `workflow` | "send dues statement Mehta" |
| Update status / rates | `workflow` | "mark order ORD-101 as delivered" |
| Scheduled report config | `workflow` + system regex | "schedule dues report every Monday 9 AM" |

**Do NOT create workflows for:** check stock, customer dues lookup, top-N reports, list orders, metal rates, credit limits — these are all `general_read`.

---

## 3. What Changes vs What Stays

### Remove

| Item | Location |
|------|----------|
| DB-driven `trigger_patterns` matching | `classifier.py` → `tier2_keyword` DB rules loop |
| `load_patterns_from_db()` for regex | `classifier.py` |
| Admin workflow generator producing `trigger_patterns` | `admin.py` |
| Saving non-empty `trigger_patterns` | `admin.py` save endpoint |
| Workflows for pure reads (`check_stock`, `get_outstanding`, `get_orders`, etc.) | DB — delete and do not recreate |

### Keep (unchanged or lightly updated)

| Item | Why |
|------|-----|
| Tier 1 exact map | Free, instant |
| Tier 2 `clear_sessions`, `manage_schedule` | Security-critical |
| All adapters (`crm`, `inventory`, `accounting`, `orders`, `quotation`) | Execution layer for mutations/PDFs |
| PDF services | Business output |
| OTP / approval flow | Security gates |
| Disambiguation in adapters | Multiple customer matches |
| `workflows` table | Stores workflow instructions + `adapter_method` |
| Scheduler (`weekly_dues_report`) | Cron job still needs a workflow row |

### Optional simplification in adapters

Keep `parse_invoice_details`, `parse_quotation_command`, etc. as **fallback** when LLM parameters are incomplete. Primary param source becomes Intent Analyzer output passed through `workflow_executor`.

---

## 4. Database — Cleanup Only (No Schema Migration)

No new columns required. Reuse existing fields:

| Column | New purpose |
|--------|-------------|
| `workflows.description` | Rich natural-language workflow spec (LLM reads this in Intent Analyzer) |
| `workflows.steps` | Ordered step instructions (JSON array of strings) |
| `workflows.trigger_patterns` | Always `[]` — deprecated, never matched |
| `workflows.adapter_method` | Unchanged — `module.function` |

### Step 1 — Backup (run in Neon SQL editor)

```sql
-- Verify current workflows before delete
SELECT intent_key, name, adapter_method, trigger_patterns
FROM workflows
WHERE org_id = '11111111-0000-0000-0000-000000000001'
ORDER BY created_at;

-- Optional: export to CSV from Neon dashboard before proceeding
```

### Step 2 — Delete all workflows (after backup confirmed)

```sql
DELETE FROM workflows
WHERE org_id = '11111111-0000-0000-0000-000000000001';
```

### Step 3 — Insert system workflow for scheduler only

The scheduled dues report job in `app/scheduler/jobs.py` looks up `intent_key = 'weekly_dues_report'`. Keep this one row even though ad-hoc "top 3 dues" queries use `general_read`:

```sql
INSERT INTO workflows (
    org_id, intent_key, name, description, steps,
    adapter_method, trigger_patterns, is_active, is_scheduled
) VALUES (
    '11111111-0000-0000-0000-000000000001',
    'weekly_dues_report',
    'Scheduled Dues Report',
    'System workflow for cron-scheduled overdue summary. Not used for ad-hoc user queries.',
    ARRAY['["Send aggregated overdue report to scheduled user via WhatsApp"]'::jsonb],
    'crm.get_all_overdue',
    '[]'::jsonb,
    true,
    false
);
```

All other workflows will be created via Admin Panel **after** code changes are deployed.

### Step 4 — Add action permissions to roles (optional but recommended)

```sql
-- Allow all roles to use general Read path (adjust per role as needed)
UPDATE roles SET permissions = array_append(permissions, 'general_read')
WHERE org_id = '11111111-0000-0000-0000-000000000001'
  AND NOT 'general_read' = ANY(permissions);

-- Owner already has broad permissions; ensure accountant/sales get general_read
UPDATE roles SET permissions = array_append(permissions, 'general_read')
WHERE org_id = '11111111-0000-0000-0000-000000000001'
  AND name IN ('accountant', 'sales', 'warehouse')
  AND NOT 'general_read' = ANY(permissions);
```

---

## 5. New Files

Create these two new modules:

```
app/services/intent_analyzer.py   ← LLM Intent + Action analyzer
app/services/query_engine.py      ← Safe Read query executor
```

---

## 6. Code Changes — File by File

---

### 6.1 NEW — `app/services/intent_analyzer.py`

```python
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
4. If the query needs PDF generation, invoice creation, order mutation, rate update → route_type = "workflow"
5. NEVER route aggregate/report/top-N/dues-summary queries to a single-customer workflow
6. Hindi/Hinglish queries: understand meaning, respond with same routing logic
7. If critical info is missing AND query cannot proceed → route_type = "clarify" with clarification_question
8. workflow_key must be null for general_read; must be one of {json.dumps(valid_workflow_keys)} for workflow
9. parameters: extract all entities (customer_name, product_name, invoice_number, amount, qty, order_number, status, metal_type, weight_grams, design_code, limit)

Return ONLY valid JSON:
{{
  "route_type": "general_read" | "workflow" | "clarify" | "unknown",
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
```

---

### 6.2 NEW — `app/services/query_engine.py`

```python
"""
Safe Read Query Engine — executes general_read requests.
LLM produces a query PLAN (not raw SQL). Engine maps plans to parameterized SQL.
"""
import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv
from app.db import fetch_all, fetch_one

load_dotenv()
_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Allowlisted query templates — LLM picks template + fills params
QUERY_TEMPLATES = {
    "customer_outstanding": {
        "description": "Outstanding invoices for ONE customer by name",
        "sql": """
            SELECT c.name, c.city, i.invoice_number, i.amount, i.status, i.due_date
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.org_id = $1 AND c.org_id = $1
              AND i.status IN ('pending', 'overdue')
              AND c.name ILIKE $2
            ORDER BY i.due_date ASC
        """,
        "params": ["org_id", "customer_name"],
    },
    "top_customers_by_dues": {
        "description": "Aggregate pending+overdue by customer, sorted by total desc",
        "sql": """
            SELECT c.name, c.city,
                   SUM(i.amount) AS total_dues,
                   COUNT(i.id) AS invoice_count,
                   MIN(i.due_date) AS oldest_due
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.org_id = $1 AND i.status IN ('pending', 'overdue')
            GROUP BY c.id, c.name, c.city
            ORDER BY total_dues DESC
            LIMIT $2
        """,
        "params": ["org_id", "limit"],
    },
    "all_overdue_customers": {
        "description": "Customers with overdue invoices only",
        "sql": """
            SELECT c.name, c.city,
                   SUM(i.amount) AS total_overdue,
                   COUNT(i.id) AS invoice_count
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.org_id = $1 AND i.status = 'overdue'
            GROUP BY c.id, c.name, c.city
            ORDER BY total_overdue DESC
            LIMIT $2
        """,
        "params": ["org_id", "limit"],
    },
    "product_stock": {
        "description": "Stock for a product by fuzzy name",
        "sql": """
            SELECT name, qty, location, reorder_level, unit_price
            FROM inventory
            WHERE org_id = $1 AND (
                similarity(name, $2) > 0.3
                OR LOWER(name) LIKE $3
            )
            ORDER BY similarity(name, $2) DESC
            LIMIT 3
        """,
        "params": ["org_id", "product_name", "product_like"],
    },
    "low_stock_items": {
        "description": "Items at or below reorder level",
        "sql": """
            SELECT name, qty, reorder_level, location
            FROM inventory
            WHERE org_id = $1 AND qty <= reorder_level
            ORDER BY qty ASC
        """,
        "params": ["org_id"],
    },
    "metal_rates": {
        "description": "All current metal rates",
        "sql": """
            SELECT metal_type, rate_per_gram, making_charge_pct
            FROM metal_rates WHERE org_id = $1 ORDER BY metal_type
        """,
        "params": ["org_id"],
    },
    "customer_credit_limit": {
        "description": "Credit limit for one customer",
        "sql": """
            SELECT name, city, credit_limit
            FROM customers
            WHERE org_id = $1 AND name ILIKE $2
            ORDER BY similarity(name, $3) DESC LIMIT 3
        """,
        "params": ["org_id", "customer_name", "customer_name_exact"],
    },
    "active_orders": {
        "description": "Orders not yet delivered",
        "sql": """
            SELECT order_number, customer_name, description, status, estimated_amount
            FROM orders
            WHERE org_id = $1 AND status != 'delivered'
            ORDER BY created_at DESC
            LIMIT $2
        """,
        "params": ["org_id", "limit"],
    },
    "invoice_lookup": {
        "description": "Find invoice by number",
        "sql": """
            SELECT i.invoice_number, i.amount, i.status, i.due_date, c.name AS customer_name
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE i.org_id = $1 AND i.invoice_number ILIKE $2
        """,
        "params": ["org_id", "invoice_number"],
    },
}


async def _pick_template(intent: str, parameters: dict) -> dict:
    """LLM picks the best allowlisted template + fills params."""
    template_list = "\n".join(
        f"- {k}: {v['description']}" for k, v in QUERY_TEMPLATES.items()
    )
    prompt = f"""Pick the best query template for this intent.

INTENT: {intent}
PARAMETERS: {json.dumps(parameters)}

AVAILABLE TEMPLATES:
{template_list}

Return ONLY JSON:
{{"template": "template_key", "params": {{"limit": 3, "customer_name": "Mehta", ...}}}}

Rules:
- Default limit to 10 if not specified for list queries
- For "top N" queries set limit = N
- customer_name: partial match OK (e.g. "Mehta" matches "Mehta Jewellers")
- product_name: the product search term
"""

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=300,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.choices[0].message.content.strip()
    start, end = raw.find("{"), raw.rfind("}") + 1
    return json.loads(raw[start:end])


def _build_sql_args(template_key: str, org_id: str, params: dict) -> tuple[str, list]:
    tpl = QUERY_TEMPLATES[template_key]
    args = []
    for p in tpl["params"]:
        if p == "org_id":
            args.append(org_id)
        elif p == "limit":
            args.append(int(params.get("limit") or 10))
        elif p == "customer_name" or p == "customer_name_exact":
            name = params.get("customer_name") or params.get("customer") or ""
            args.append(f"%{name}%")
            if p == "customer_name_exact":
                args.append(name)
        elif p == "product_name":
            args.append(params.get("product_name") or params.get("product") or "")
        elif p == "product_like":
            name = params.get("product_name") or params.get("product") or ""
            args.append(f"%{name.lower()}%")
        elif p == "invoice_number":
            inv = params.get("invoice_number") or ""
            if not inv.upper().startswith("INV-"):
                inv = f"INV-{inv}" if inv.isdigit() else inv
            args.append(inv)
        else:
            args.append(params.get(p))
    return tpl["sql"], args


def _format_whatsapp(template_key: str, rows: list, params: dict) -> str:
    if not rows:
        return "✅ No matching records found."

    if template_key == "customer_outstanding":
        lines = []
        total = 0
        customer_name = rows[0]["name"]
        for r in rows:
            total += float(r["amount"])
            icon = "🔴" if r["status"] == "overdue" else "🟡"
            lines.append(f"{icon} {r['invoice_number']} — ₹{r['amount']:,.0f} ({r['status']})")
        return (
            f"💰 *{customer_name}* — Outstanding\n\n"
            + "\n".join(lines)
            + f"\n\n*Total: ₹{total:,.0f}*"
        )

    if template_key == "top_customers_by_dues":
        limit = params.get("limit")
        title = f"Top {limit} Customers by Dues" if limit else "Customers by Dues"
        lines = [
            f"{i+1}. *{r['name']}* ({r['city']}) — ₹{r['total_dues']:,.0f} ({r['invoice_count']} inv.)"
            for i, r in enumerate(rows)
        ]
        grand = sum(float(r["total_dues"]) for r in rows)
        return f"📊 *{title}*\n\n" + "\n".join(lines) + f"\n\n*Total shown: ₹{grand:,.0f}*"

    if template_key == "all_overdue_customers":
        lines = [
            f"• *{r['name']}* ({r['city']}) — ₹{r['total_overdue']:,.0f}"
            for r in rows
        ]
        return "📊 *Overdue Customers*\n\n" + "\n".join(lines)

    if template_key == "product_stock":
        r = rows[0]
        low = r["qty"] <= r["reorder_level"]
        warn = "\n⚠️ _Below reorder level!_" if low else ""
        return (
            f"📦 *{r['name']}*\n"
            f"Available: *{r['qty']} pcs*\n"
            f"Location: {r['location']}\n"
            f"Unit price: ₹{r['unit_price']:,.0f}{warn}"
        )

    if template_key == "low_stock_items":
        lines = [f"• *{r['name']}* — {r['qty']} pcs (reorder: {r['reorder_level']})" for r in rows]
        return "⚠️ *Low Stock Items*\n\n" + "\n".join(lines)

    if template_key == "metal_rates":
        lines = [f"• *{r['metal_type']}* — ₹{r['rate_per_gram']:,.0f}/g (making: {r['making_charge_pct']}%)" for r in rows]
        return "💰 *Metal Rates*\n\n" + "\n".join(lines)

    if template_key == "customer_credit_limit":
        if len(rows) > 1:
            opts = "\n".join(f"{i+1}. {r['name']} ({r['city']})" for i, r in enumerate(rows))
            return f"🔍 Multiple matches:\n{opts}\n\nReply with customer name."
        r = rows[0]
        cl = r["credit_limit"]
        return f"💳 *{r['name']}* — Credit Limit: ₹{cl:,.0f}" if cl else f"ℹ️ *{r['name']}* — no credit limit set"

    if template_key == "active_orders":
        lines = [
            f"• *{r['order_number']}* — {r['customer_name']}: {r['description']} [{r['status']}]"
            for r in rows
        ]
        return f"📋 *Active Orders* ({len(rows)})\n\n" + "\n".join(lines)

    if template_key == "invoice_lookup":
        r = rows[0]
        return (
            f"🧾 *{r['invoice_number']}*\n"
            f"Customer: {r['customer_name']}\n"
            f"Amount: ₹{r['amount']:,.0f}\n"
            f"Status: {r['status']}"
        )

    # Generic fallback
    return f"Found {len(rows)} record(s)."


async def execute_read(org_id: str, intent: str, parameters: dict) -> str:
    """Execute a general_read request. Returns WhatsApp-formatted message."""
    try:
        picked = await _pick_template(intent, parameters)
        template_key = picked["template"]
        if template_key not in QUERY_TEMPLATES:
            return "🤔 Could not determine how to fetch that data. Try rephrasing."

        sql, args = _build_sql_args(template_key, org_id, picked.get("params", parameters))
        rows = await fetch_all(sql, *args)
        rows = [dict(r) for r in rows]
        return _format_whatsapp(template_key, rows, picked.get("params", parameters))
    except Exception as e:
        print(f"[QUERY_ENGINE] Error: {e}")
        return f"⚠️ Could not run query: {str(e)}"
```

---

### 6.3 REPLACE — `app/classifier/classifier.py`

**Remove entirely:**
- `_db_patterns_cache` and `load_patterns_from_db()`
- DB rules in `tier2_keyword()` (keep only `KEYWORD_RULES` hardcoded system intents)
- `tier3_llm()` old intent_key classifier

**Replace `classify_message()` with:**

```python
async def classify_message(text: str, org_name: str = "your organisation",
                           org_id: str = None, user_role: str = "owner") -> dict:
    # Tier 1
    t1 = tier1_exact(text)
    if t1:
        return {"intent": t1, "tier": 1, "confidence": 1.0,
                "route_type": "system", "entity_raw": None}

    # Tier 2 — system-only regex (NOT DB patterns)
    t2 = tier2_keyword(text, db_rules=None)
    if t2:
        return {**t2, "route_type": "system"}

    # Tier 3 — Intent Analyzer
    if not org_id:
        return {"route_type": "unknown", "tier": 3, "intent": "unknown",
                "entity_raw": None, "confidence": 0.0}

    from app.services.intent_analyzer import analyze_intent
    result = await analyze_intent(text, org_id, org_name, user_role)
    return result
```

**Update `tier2_keyword()` signature** — remove `db_rules` parameter and the `all_rules.extend(db_rules)` block. Only iterate `KEYWORD_RULES`.

**Remove or stub `invalidate_patterns_cache()`** — can remain as no-op for admin compatibility:

```python
def invalidate_patterns_cache(org_id: str = None):
    pass  # No pattern cache in Intent+Action routing
```

---

### 6.4 UPDATE — `app/services/identity.py`

Add action-based permission checking:

```python
# Tables allowed per role for general_read (extend as needed)
ROLE_READ_ACCESS = {
    "owner":      {"customers", "invoices", "inventory", "orders", "metal_rates", "quotations"},
    "accountant": {"customers", "invoices", "inventory", "orders"},
    "sales":      {"customers", "inventory", "orders", "quotations", "metal_rates"},
    "warehouse":  {"inventory"},
}

WORKFLOW_ACTIONS = {
    "create_invoice":       "Create",
    "create_quotation":     "Create",
    "create_order":         "Create",
    "send_invoice_pdf":     "Execute",
    "send_dues_statement":  "Execute",
    "set_metal_rate":       "Update",
    "update_order_status":  "Update",
}


def check_permission(user: dict, intent: str) -> bool:
    """Legacy — still used for system intents."""
    if intent.startswith("action:") or intent == "unknown":
        return True
    return intent in user.get("permissions", [])


def check_route_permission(user: dict, analysis: dict) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    analysis = output from Intent Analyzer
    """
    route = analysis.get("route_type")
    role = user.get("role", "")

    if route == "clarify":
        return True, ""

    if route == "general_read":
        if "general_read" in user.get("permissions", []):
            return True, ""
        # Fallback: owner always allowed
        if role == "owner":
            return True, ""
        return False, "general_read"

    if route == "workflow":
        wk = analysis.get("workflow_key")
        if not wk:
            return False, "unknown workflow"
        if wk not in user.get("permissions", []):
            return False, wk
        return True, ""

    if route == "system":
        return check_permission(user, analysis.get("intent", "")), analysis.get("intent", "")

    return False, "unknown route"
```

---

### 6.5 UPDATE — `app/routers/webhook.py`

Replace the classify + permission + execute block (steps 8–10):

```python
# 8. Classify
result = await classify_message(
    text,
    org_name=user["org_name"],
    org_id=user["org_id"],
    user_role=user["role"],
)
route_type = result.get("route_type", "unknown")
print(f"[CLASSIFIER] route={route_type} | action={result.get('action')} | tier={result.get('tier')}")

# 9. Permission gate
allowed, denied = check_route_permission(user, result)
if not allowed:
    await send_text(phone,
        f"❌ You don't have permission for: *{denied}*\n"
        f"Your role: *{user['role']}*"
    )
    return

# 10a. Clarification
if route_type == "clarify":
    q = result.get("clarification_question") or "Could you provide more details?"
    await send_text(phone, f"🤔 {q}")
    return

# 10b. Static action intents (unchanged)
if result.get("intent") == "action:greet":
    ...  # keep existing

# 10c. General Read
if route_type == "general_read":
    from app.services.query_engine import execute_read
    reply = await execute_read(
        org_id=user["org_id"],
        intent=result.get("intent", text),
        parameters=result.get("parameters") or {},
    )
    await send_text(phone, reply)
    return

# 10d. Unknown
if route_type == "unknown" or result.get("intent") == "unknown":
    await send_text(phone, "🤔 Didn't understand that.\nTry: *dues Mehta* | *top 3 dues* | *help*")
    return

# 10e. Workflow execution
intent = result.get("workflow_key") or result.get("intent")
entity_raw = (
    result.get("parameters", {}).get("customer_name")
    or result.get("parameters", {}).get("product_name")
    or result.get("entity_raw")
)
await set_session(session_id, {**session, "last_intent": intent, "last_parameters": result.get("parameters", {})})

reply = await execute_intent(
    intent=intent,
    entity_raw=entity_raw,
    user=user,
    session_id=session_id,
    session=session,
    raw_text=text,
    parameters=result.get("parameters") or {},  # NEW kwarg
)
await send_text(phone, reply)
```

Add import at top:

```python
from app.services.identity import resolve_identity, check_permission, check_route_permission
```

---

### 6.6 UPDATE — `app/executor/workflow_executor.py`

Add `parameters: dict = None` to `execute_intent()` and pass to `_dispatch_dynamic_intent()`:

```python
async def execute_intent(..., parameters: dict = None) -> str:
    parameters = parameters or {}
    ...
    if db_workflow:
        adapter_method = db_workflow.get("adapter_method", "generic")
        result_msg = await _dispatch_dynamic_intent(
            intent, entity_raw, org_id, raw_text, adapter_method,
            session_id, user_id, phone,
            parameters=parameters,  # NEW
        )
```

Update `_dispatch_dynamic_intent()` to merge parameters into adapter kwargs:

```python
async def _dispatch_dynamic_intent(..., parameters: dict = None, **ignored):
    parameters = parameters or {}
    context = {
        "org_id": org_id,
        "user_id": user_id,
        "phone": phone,
        "raw_text": raw_text,
        "entity_raw": entity,
        **parameters,  # LLM-extracted fields override
    }
    try:
        result = await adapter_func(**context)
    except TypeError:
        result = await adapter_func(org_id, entity if entity else None)
```

---

### 6.7 UPDATE — `app/routers/admin.py`

**Replace workflow generator prompt** — remove all `trigger_patterns` instructions:

```python
prompt = f"""You are a Workflow Creator for a WhatsApp jewellery ERP.

User wants this workflow:
"{description}"

Generate ONLY this JSON (no markdown, no extra text):
{{
  "name": "2-4 word name",
  "intent_key": "snake_case matching adapter function name",
  "description": "Detailed multi-paragraph spec: purpose, when to use, parameters needed, examples, business context",
  "steps": [
    "Step 1: ...",
    "Step 2: ...",
    "Step 3: ..."
  ],
  "adapter_method": "module.function",
  "otp_required": false,
  "otp_threshold": null,
  "approval_threshold": null
}}

Rules:
- intent_key MUST match the function name in adapter_method (e.g. accounting.create_invoice → create_invoice)
- description must be detailed enough for an LLM to route correctly WITHOUT regex patterns
- steps: 3-6 ordered execution steps
- adapter_method MUST be one of:
  accounting.create_invoice, accounting.send_invoice_pdf, accounting.send_dues_statement,
  quotation.create_quotation, quotation.set_metal_rate,
  orders.create_order, orders.update_order_status
- Do NOT generate trigger_patterns — routing is LLM-based
- Do NOT create workflows for simple DB reads (stock check, dues lookup, reports)

Return ONLY the JSON."""
```

**Update save endpoint** — always save empty trigger_patterns:

```python
await execute("""
    INSERT INTO workflows (
        org_id, name, intent_key, description, steps, trigger_patterns,
        adapter_method, otp_required, otp_threshold, approval_threshold, is_active
    ) VALUES ($1, $2, $3, $4, $5, '[]'::jsonb, $6, $7, $8, $9, true)
""",
    org_id,
    body.get("name"),
    body.get("intent_key"),
    body.get("description"),
    body.get("steps", []),  # NEW — array of step strings
    adapter_method,
    ...
)
```

**Update admin HTML `saveWorkflow()` JS** — remove trigger_patterns, add steps:

```javascript
const config = {
  name: ...,
  intent_key: ...,
  description: ...,
  steps: (window.generatedConfig && window.generatedConfig.steps) || [],
  adapter_method: ...,
  // trigger_patterns removed — always empty
  ...
};
```

Add a read-only `steps` textarea in the workflow form UI.

---

### 6.8 UPDATE — `test_classifier.py`

Replace with Intent+Action tests:

```python
TEST_MESSAGES = [
    # Tier 1
    ("hi", "system"),
    ("help", "system"),
    # General reads — no workflow needed
    ("top 3 customers by pending dues", "general_read"),
    ("Mehta ka kitna baaki hai", "general_read"),
    ("stock gold ring", "general_read"),
    ("show low stock items", "general_read"),
    ("Sharma credit limit", "general_read"),
    ("all overdue customers", "general_read"),
    # Workflows — after workflows created in admin
    ("send dues statement for Mehta", "workflow"),
    ("invoice Mehta 45000", "workflow"),
    ("set gold rate to 6500", "workflow"),
]
```

---

## 7. Prompt Templates

### 7.1 Intent Analyzer (core)

See full prompt in `intent_analyzer.py` section 6.1.

**Key output contract:**

```json
{
  "route_type": "general_read",
  "action": "Read",
  "intent": "Outstanding dues from invoices grouped by customer, top 3 by amount descending",
  "workflow_key": null,
  "parameters": {"limit": 3},
  "clarification_question": null,
  "confidence": 0.92
}
```

### 7.2 Workflow Creator (admin panel)

See section 6.7.

**Example admin input:**

> I want users to create invoices for customers. If amount exceeds ₹50,000 require OTP. Above ₹1,00,000 needs owner approval.

**Expected generated JSON:**

```json
{
  "name": "Create Invoice",
  "intent_key": "create_invoice",
  "description": "Creates a sales invoice for a customer, generates PDF, sends via WhatsApp. Requires customer name and amount. Optional: item name and quantity for stock deduction. Used by sales and accounts team when billing customers.",
  "steps": [
    "Step 1: Validate customer exists in customers table",
    "Step 2: Check stock if item+qty specified",
    "Step 3: Create invoice record in invoices table",
    "Step 4: Generate PDF and send via WhatsApp",
    "Step 5: Deduct inventory if applicable"
  ],
  "adapter_method": "accounting.create_invoice",
  "otp_required": true,
  "otp_threshold": 50000,
  "approval_threshold": 100000
}
```

---

## 8. Permission Model

| Role | general_read | Workflows allowed |
|------|-------------|-------------------|
| owner | ✅ all tables | all |
| accountant | ✅ customers, invoices, inventory, orders | create_invoice, send_invoice_pdf, send_dues_statement, update_order_status |
| sales | ✅ customers, inventory, orders, quotations, metal_rates | create_invoice, create_quotation, create_order |
| warehouse | ✅ inventory only | none (reads only) |

After saving each workflow in admin, permissions are appended to selected roles (existing behavior).

**New permission key:** `general_read` — add to all roles that should ask data questions.

---

## 9. Migration Steps

Execute in this order:

```
1. Deploy code changes (sections 6.1–6.8)
2. Run SQL backup query (section 4, step 1)
3. DELETE all workflows (section 4, step 2)
4. INSERT weekly_dues_report system row (section 4, step 3)
5. ADD general_read permission to roles (section 4, step 4)
6. Create mutation workflows via Admin Panel (section 10)
7. Run test queries (section 11)
```

---

## 10. Workflows to Create (Admin Panel)

After code deploy, create **only these workflows** via Admin → AI Workflow Builder.
Do **NOT** recreate read-only workflows (`check_stock`, `get_outstanding`, `get_orders`, etc.).

### Workflow 1 — Create Invoice

**Admin input:**
> Create invoice for a customer with amount. Generate PDF and send on WhatsApp. OTP required above ₹50,000. Owner approval above ₹1,00,000.

| Field | Value |
|-------|-------|
| intent_key | `create_invoice` |
| adapter_method | `accounting.create_invoice` |
| otp_required | true |
| otp_threshold | 50000 |
| approval_threshold | 100000 |
| roles | owner, accountant, sales |

---

### Workflow 2 — Send Invoice PDF

**Admin input:**
> Send PDF of an existing invoice to the user on WhatsApp. User provides invoice number like INV-001.

| Field | Value |
|-------|-------|
| intent_key | `send_invoice_pdf` |
| adapter_method | `accounting.send_invoice_pdf` |
| roles | owner, accountant |

---

### Workflow 3 — Send Dues Statement PDF

**Admin input:**
> Generate and send a PDF statement of all outstanding invoices for a specific customer.

| Field | Value |
|-------|-------|
| intent_key | `send_dues_statement` |
| adapter_method | `accounting.send_dues_statement` |
| roles | owner, accountant |

---

### Workflow 4 — Create Quotation

**Admin input:**
> Create price quotation for a customer. Needs customer name, metal type (22kt/18kt/silver), weight in grams, optional design code. Generates quotation PDF.

| Field | Value |
|-------|-------|
| intent_key | `create_quotation` |
| adapter_method | `quotation.create_quotation` |
| roles | owner, sales |

**Complex example user query (after workflow exists):**
> Generate an invoice for Tanishq Jewellers for 40 pieces of 22kt gold bangle (Design Code: D001) each piece at Rs.35,000 plus 14% making charges and GST

Route: `workflow` → `create_quotation` or `create_invoice` depending on Intent Analyzer (quotation vs invoice). Parameters extracted from natural language — no regex.

---

### Workflow 5 — Update Metal Rate

**Admin input:**
> Update the daily rate for a metal type (gold/silver/platinum). Owner and sales only.

| Field | Value |
|-------|-------|
| intent_key | `set_metal_rate` |
| adapter_method | `quotation.set_metal_rate` |
| roles | owner |

---

### Workflow 6 — Create Production Order

**Admin input:**
> Create a new production/manufacturing order for a customer with item description and optional metal type.

| Field | Value |
|-------|-------|
| intent_key | `create_order` |
| adapter_method | `orders.create_order` |
| roles | owner, sales |

---

### Workflow 7 — Update Order Status

**Admin input:**
> Change status of a production order (confirmed, in production, quality check, ready, delivered).

| Field | Value |
|-------|-------|
| intent_key | `update_order_status` |
| adapter_method | `orders.update_order_status` |
| roles | owner, accountant, sales |

---

## 11. Test Queries — Full Matrix

Use org `11111111-0000-0000-0000-000000000001` sample data.
Test as **owner** user (Kartik / Ravi) unless testing role restrictions.

### 11.1 General Read — No Workflow Required

| # | Query | Expected route | Expected answer (from sample data) |
|---|-------|----------------|-------------------------------------|
| 1 | `top 3 customers by pending dues` | general_read | 1. Sharma ₹1,60,000 2. Mehta ₹1,07,000 3. Agarwal ₹71,000 |
| 2 | `Give me the top 3 dues customer wise` | general_read | Same as #1 — **must NOT ask "which customer?"** |
| 3 | `Top 3 outstanding customers` | general_read | Overdue only: 1. Agarwal ₹71,000 2. Sharma ₹35,000 |
| 4 | `Mehta ka kitna baaki hai?` | general_read | Mehta Jewellers outstanding: INV-001 ₹45,000 + INV-004 ₹62,000 = ₹1,07,000 |
| 5 | `dues Mehta` | general_read | Same as #4 |
| 6 | `how much does Sharma owe` | general_read | Sharma: INV-002 ₹1,25,000 pending + INV-005 ₹35,000 overdue |
| 7 | `stock gold ring` | general_read | 22kt Gold Ring — 41 pcs, Rack B-3, ₹45,000 |
| 8 | `kitna necklace hai` | general_read | 22kt Gold Necklace — 2 pcs (low stock warning) |
| 9 | `show low stock items` | general_read | Mangalsutra (15), Necklace (2), Diamond Bangle (12), etc. |
| 10 | `Sharma credit limit` | general_read | Sharma Gold House — ₹3,00,000 |
| 11 | `current metal rates` | general_read | Lists all metal_rates rows |
| 12 | `who has paid invoices` | general_read | Patel Fine Jewellery — INV-003 paid ₹1,85,000 |
| 13 | `show active orders` | general_read | All non-delivered orders (if any seeded) |
| 14 | `invoice INV-001 details` | general_read | INV-001, Mehta, ₹45,000, pending |

### 11.2 General Read — Hindi / Hinglish

| # | Query | Expected route | Notes |
|---|-------|----------------|-------|
| 15 | `Mehta ka hisaab batao` | general_read | Same as dues Mehta |
| 16 | `sabse zyada baaki kiska hai` | general_read | Top customer by dues (Sharma) |
| 17 | `gold ring ka stock kitna hai` | general_read | 41 pcs |
| 18 | `Patel ka kitna baaki hai` | general_read | ₹0 — INV-003 is paid |

### 11.3 Workflow Mutations (create workflows first)

| # | Query | workflow_key | Expected behavior |
|---|-------|-------------|-------------------|
| 19 | `send dues statement for Mehta` | send_dues_statement | PDF sent, total ₹1,07,000 |
| 20 | `send invoice INV-001` | send_invoice_pdf | PDF for Mehta ₹45,000 |
| 21 | `invoice Mehta 45000` | create_invoice | New invoice created (if OTP ok) |
| 22 | `quote Mehta 22kt 15g` | create_quotation | Quotation PDF generated |
| 23 | `set gold rate to 6500` | set_metal_rate | 22kt rate updated (owner only) |
| 24 | `new order Mehta 22kt gold bangle` | create_order | Order ORD-xxxx created |
| 25 | `mark order ORD-1101 as delivered` | update_order_status | Status updated |

### 11.4 Complex Natural Language (LLM parameter extraction)

| # | Query | Expected |
|---|-------|----------|
| 26 | `Generate an invoice for Tanishq Jewellers for 40 pieces of 22kt gold bangle (Design Code: D001) each piece to be charged at Rs.35,000 plus 14% making charges and GST` | workflow → create_quotation or create_invoice; extracts customer, qty, item, rate |
| 27 | `Help me with the Top 3 customers in terms of pending dues` | general_read → top 3 report |

### 11.5 Clarification Cases

| # | Query | Expected |
|---|-------|----------|
| 28 | `send invoice` | clarify — "Which invoice number?" |
| 29 | `create invoice` | clarify — "Which customer and amount?" |
| 30 | `dues statement` | clarify — "Which customer?" |

### 11.6 Permission Tests

| # | User role | Query | Expected |
|---|-----------|-------|----------|
| 31 | warehouse | `dues Mehta` | ❌ no general_read permission |
| 32 | warehouse | `stock gold ring` | ✅ if general_read added to warehouse |
| 33 | sales | `set gold rate to 6500` | ❌ no set_metal_rate permission |
| 34 | accountant | `invoice Mehta 45000` | ✅ if create_invoice permission |

### 11.7 System Intents (unchanged)

| # | Query | Expected |
|---|-------|----------|
| 35 | `hi` | Greet menu |
| 36 | `help` | Help menu |
| 37 | `schedule dues report every Monday 9 AM` | Schedule updated (owner only) |
| 38 | `clear all sessions` | Emergency lockdown (owner only) |

### 11.8 Regression — Must NOT Happen

| Query | ❌ Wrong behavior | ✅ Correct behavior |
|-------|------------------|---------------------|
| `top 3 dues customer wise` | "Which customer? Try dues Mehta" | Top 3 aggregate report |
| `Top 3 outstanding customers` | entity "Customers" not found | Aggregate report |
| `all outstanding` | Routes to get_outstanding | general_read aggregate |

---

## 12. Testing Checklist

### Pre-flight

- [ ] Code deployed: `intent_analyzer.py`, `query_engine.py`
- [ ] `classifier.py` no longer loads DB trigger_patterns
- [ ] `webhook.py` handles `route_type` branches
- [ ] `identity.py` has `check_route_permission`
- [ ] Workflows backed up
- [ ] All old workflows deleted
- [ ] `weekly_dues_report` system row inserted
- [ ] `general_read` permission added to roles
- [ ] 7 mutation workflows created via admin

### Smoke tests (run in order)

- [ ] `hi` → greet
- [ ] `top 3 customers by pending dues` → 3 customers listed, no "which customer?"
- [ ] `Mehta ka kitna baaki hai` → ₹1,07,000
- [ ] `stock gold ring` → 41 pcs
- [ ] `send dues statement for Mehta` → PDF received
- [ ] `invoice Mehta 45000` → invoice created (OTP if configured)
- [ ] Test as accountant — confirm read works, owner-only blocked
- [ ] Test as warehouse — confirm dues query blocked if no general_read

### Audit

- [ ] Check `audit_log` entries for workflow intents
- [ ] Confirm no `trigger_patterns` in new workflow rows (`SELECT trigger_patterns FROM workflows` → all `[]`)

---

## Quick Reference — Files Touched

| File | Action |
|------|--------|
| `app/services/intent_analyzer.py` | **CREATE** |
| `app/services/query_engine.py` | **CREATE** |
| `app/classifier/classifier.py` | **REWRITE** routing (remove DB regex) |
| `app/services/identity.py` | **ADD** `check_route_permission` |
| `app/routers/webhook.py` | **UPDATE** route_type handling |
| `app/executor/workflow_executor.py` | **UPDATE** pass `parameters` |
| `app/routers/admin.py` | **UPDATE** workflow creator (no patterns) |
| `test_classifier.py` | **UPDATE** test cases |
| `app/adapters/*.py` | **KEEP** — optional: rely on LLM params first |
| `ORCHESTRAI_NLP_ROUTING_FIX.md` | **DEPRECATED** — do not follow |
| `ORCHESTRAI_SEMANTIC_ROUTING.md` | **DEPRECATED** — do not follow |

---

*Document version: 2026-06-26 — Intent + Action routing for OrchestrAI*
