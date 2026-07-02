import os
import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from app.db import fetch_all, fetch_one, execute
from openai import AsyncOpenAI

router = APIRouter()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "orchestrai_admin_2024")
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _check_token(request: Request):
    token = request.query_params.get("token") or \
            request.headers.get("X-Admin-Token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    _check_token(request)
    token = request.query_params.get("token", "")
    return HTMLResponse(content=_build_html(token))


@router.get("/admin/api/data")
async def admin_data(request: Request):
    _check_token(request)

    org = await fetch_one("SELECT id, name FROM orgs WHERE is_active = true LIMIT 1")
    if not org:
        return {"error": "No active org found"}

    org_id = str(org["id"])

    workflows = await fetch_all("""
        SELECT id, name, intent_key, is_active, otp_required,
               otp_threshold, approval_threshold, last_run
        FROM workflows WHERE org_id = $1
        ORDER BY created_at
    """, org_id)

    stats = await fetch_one("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'paid') AS total_invoices,
            COALESCE(SUM(amount) FILTER (WHERE status = 'paid'), 0) AS total_amount,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending_invoices,
            (SELECT COUNT(*) FROM customers WHERE org_id = $1) AS total_customers
        FROM invoices WHERE org_id = $1
    """, org_id)

    low_stock = await fetch_all("""
        SELECT name, qty, reorder_level FROM inventory
        WHERE org_id = $1 AND qty <= reorder_level
    """, org_id)

    recent_logs = await fetch_all("""
        SELECT a.intent_key, a.outcome, a.otp_used,
               a.created_at, u.name as user_name
        FROM audit_log a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE a.org_id = $1
        ORDER BY a.created_at DESC LIMIT 8
    """, org_id)

    return {
        "org": dict(org),
        "workflows": [dict(w) for w in workflows],
        "stats": dict(stats),
        "low_stock": [dict(r) for r in low_stock],
        "recent_logs": [dict(r) for r in recent_logs]
    }


@router.post("/admin/api/workflow/{workflow_id}/toggle")
async def toggle_otp(workflow_id: str, request: Request):
    _check_token(request)
    row = await fetch_one(
        "SELECT otp_required, org_id FROM workflows WHERE id = $1", workflow_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    new_val = not row["otp_required"]
    await execute(
        "UPDATE workflows SET otp_required = $1 WHERE id = $2",
        new_val, workflow_id
    )
    return {"otp_required": new_val}


@router.post("/admin/api/workflow/{workflow_id}/threshold")
async def update_threshold(workflow_id: str, request: Request):
    _check_token(request)
    body = await request.json()
    threshold = float(body.get("threshold", 50000))
    await execute(
        "UPDATE workflows SET otp_threshold = $1 WHERE id = $2",
        threshold, workflow_id
    )
    return {"otp_threshold": threshold}


@router.post("/admin/api/workflow/{workflow_id}/approval_threshold")
async def update_approval_threshold(workflow_id: str, request: Request):
    _check_token(request)
    body = await request.json()
    threshold = float(body.get("threshold", 100000))
    await execute(
        "UPDATE workflows SET approval_threshold = $1 WHERE id = $2",
        threshold, workflow_id
    )
    return {"approval_threshold": threshold}


@router.get("/admin/api/roles")
async def get_roles(request: Request):
    _check_token(request)
    roles = await fetch_all("SELECT name FROM roles ORDER BY name")
    return [{"name": r["name"], "selected": r["name"] == "owner"} for r in roles]


@router.get("/admin/api/security")
async def get_security_settings(request: Request):
    _check_token(request)
    org = await fetch_one(
        "SELECT session_ttl_minutes FROM orgs WHERE is_active = true LIMIT 1"
    )
    return {"session_ttl_minutes": org["session_ttl_minutes"] or 480}


@router.post("/admin/api/security/ttl")
async def update_session_ttl(request: Request):
    _check_token(request)
    body = await request.json()
    minutes = int(body.get("minutes", 480))
    if minutes < 5 or minutes > 10080:  # 5 min to 7 days
        raise HTTPException(status_code=400, detail="TTL must be between 5 and 10080 minutes")
    await execute(
        "UPDATE orgs SET session_ttl_minutes = $1 WHERE is_active = true", minutes
    )
    return {"session_ttl_minutes": minutes}


@router.post("/admin/api/sessions/clear")
async def admin_clear_sessions(request: Request):
    _check_token(request)
    from app.redis_client import clear_all_sessions
    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1")
    await clear_all_sessions(str(org["id"]))
    return {"cleared": True, "message": "All sessions cleared"}


@router.post("/admin/api/workflow/generate")
async def generate_workflow_config(request: Request):
    _check_token(request)
    body = await request.json()
    description = body.get("description", "").strip()

    if not description:
        raise HTTPException(status_code=400, detail="Description is required")

    # Load schema for context
    schema_rows = await fetch_all("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name IN ('customers','inventory','invoices','orders',
                              'quotations','users','roles')
        ORDER BY table_name, ordinal_position
    """)

    # Build compact schema
    table_cols: dict = {}
    for r in schema_rows:
        table_cols.setdefault(r["table_name"], []).append(r["column_name"])
    schema_text = "\n".join(
        f"  {t}: {', '.join(cs)}" for t, cs in sorted(table_cols.items())
    )

    # Detect if this is read or action
    action_keywords = ["create", "update", "send", "generate", "delete", "set",
                       "change", "make", "add", "produce", "dispatch", "mark"]
    is_likely_action = any(kw in description.lower() for kw in action_keywords)

    prompt = f"""You are a Workflow Compiler for a multi-sector WhatsApp ERP system.

The admin wants to add a workflow to their system. You must generate a COMPLETE, STRUCTURED workflow record that will be saved to the database. This record will make the system fully autonomous for this type of query â€” no hardcoding anywhere in the codebase.

ADMIN DESCRIPTION:
"{description}"

DATABASE SCHEMA (available tables):
{schema_text}

WORKFLOW TYPES:
- "read": Query the DB and return data. Use when the intent is to VIEW/CHECK/GET/SHOW/LIST/REPORT information.
- "action": Call a business function. Use when the intent is to CREATE/UPDATE/SEND/GENERATE/DELETE/SET something.

YOUR TASK: Generate a complete workflow record as JSON. Follow these rules exactly.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• RULES â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

RULE 1 â€” workflow_type:
  Detect from the description: read or action.
  When uncertain, prefer "read".

RULE 2 â€” training_phrases (CRITICAL â€” this is how users will trigger this workflow):
  Generate 8-12 realistic user phrases in WhatsApp style.
  Include English, Hinglish, and abbreviated forms.
  Use {{slot_name}} for entity placeholders.
  Example for "check customer dues": [
    "{{customer_name}} ka baaki", "dues {{customer_name}}",
    "{{customer_name}} outstanding", "{{customer_name}} ka udhaar",
    "{{customer_name}} pending amount", "check dues {{customer_name}}",
    "{{customer_name}} ka kitna baaki hai", "balance {{customer_name}}",
    "{{customer_name}} owes how much"
  ]
  Be realistic â€” think about how non-technical WhatsApp users actually type.
  Include common abbreviations and short forms.

RULE 3 â€” entity_schema:
  Only include entities ACTUALLY needed to answer the query.
  For each entity:
    "table": which DB table it comes from (or null for computed values)
    "column": which column to match against
    "match": "ILIKE" for text search, "exact" for status/codes
    "required": true/false
    "format": "wildcard" for ILIKE (adds % wrapping), "exact" for = comparisons
    "type": "string" (default) | "integer" | "float"
    "default": optional default value if not provided
  Example: {{"customer_name": {{"table": "customers", "column": "name", "match": "ILIKE", "required": true, "format": "wildcard"}}}}

RULE 4 â€” sql_template (ONLY for workflow_type = "read"):
  Write a complete, parameterized PostgreSQL SELECT query.
  ALWAYS use $1 for org_id.
  Use $2, $3, ... for entity params in the order listed in sql_params_order.
  For ILIKE, DO NOT add % in the SQL â€” the executor adds wildcards based on entity_schema.format.
  Include appropriate JOINs, WHERE clauses, GROUP BY, ORDER BY, and LIMIT.
  NEVER use subqueries unless absolutely necessary â€” prefer JOINs.
  Default LIMIT = 20 unless the query is inherently aggregate.
  Example: "SELECT c.name, SUM(i.amount) AS total_outstanding FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE i.org_id=$1 AND c.name ILIKE $2 AND i.status IN ('pending','overdue') GROUP BY c.id, c.name ORDER BY total_outstanding DESC"

RULE 5 â€” sql_params_order:
  List entity_schema keys in the order they appear as $2, $3, etc. in sql_template.
  Example: ["customer_name"] or ["limit", "status"]
  Must be empty [] for action workflows.

RULE 6 â€” response_format:
  Choose the most appropriate formatter:
  "outstanding_summary" â€” customer + outstanding amounts (from invoices aggregation)
  "inventory" â€” product name + qty + location
  "orders" â€” order_number + customer + status
  "customers" â€” customer name + city + credit_limit
  "quotations" â€” quotation_number + customer_id + total_amount + status + items
  "invoices" â€” invoice_number + amount + status + due_date
  "users" â€” user name + role
  "generic" â€” use for anything else
  null â€” for action workflows

RULE 7 â€” business_glossary:
  Map common user terms FOR THIS SPECIFIC WORKFLOW to what they mean.
  Include the 3-6 most likely alternative phrasings users might type.
  Example for dues workflow: {{"baaki": "outstanding", "udhaar": "unpaid dues", "pending": "pending/overdue invoices", "payment baki": "outstanding balance"}}

RULE 8 â€” llm_system_prompt:
  Write a focused system prompt that an LLM would use ONLY for this workflow when keyword matching is ambiguous.
  Include:
  a) One sentence: what this workflow does
  b) The DB tables and JOIN pattern involved
  c) Business glossary for this workflow
  d) 3 concrete example inputs and what entity to extract
  e) One disambiguation rule (what this workflow is NOT)
  Keep under 300 words.

RULE 9 â€” adapter_method (ONLY for workflow_type = "action"):
  Format: "module.function"
  Derive it from the admin's description. Use sensible module names.
  Examples: "accounting.create_invoice", "inventory.check_stock", "orders.create_order"
  For read workflows: null.

RULE 10 â€” intent_key:
  Must be unique, snake_case, descriptive.
  For reads: describe the data (get_outstanding, check_stock, list_orders_by_status)
  For actions: describe the action (create_invoice, update_order_status, send_dues_pdf)

RULE 11 â€” pdf_config (for all workflows):
  How should PDFs look when generated from this workflow's data?
  "doc_type": one of report/invoice/statement/orders/quotation
    - statement: single customer's dues with aging + customer header
    - report: multi-customer lists, inventory, order lists
    - invoice: ONLY single specific Tax Invoice (not lists)
    - quotation: price quotations
    - orders: production order lists
  "title_template": e.g. "Outstanding Statement â€” {{customer_name}}"
  "aging_analysis": true if data has due_date and risk bucketing makes sense
  "show_key_insights": true for financial/operational summaries
  "insight_focus": ONE sentence â€” what Key Actions should focus on
  For action workflows: null

RULE 12 â€” response_template (for action workflows):
  WhatsApp response format after action completes.
  Use {{variable}} placeholders. Use *bold* for key values. Include emoji.
  Example: "âœ… *Invoice Created*\\n\\nInvoice #: *{{invoice_number}}*\\nCustomer: {{customer_name}}\\nAmount: *Rs.{{amount}}*\\n\\nðŸ“„ PDF sent above â†‘"
  For read workflows: null

RULE 13 â€” calc_rules (REQUIRED for action workflows with computed numeric fields):
  Defines how the system calculates derived values deterministically.
  The LLM NEVER fills computed fields â€” it only collects raw inputs.
  {{
    "item_rules": {{
      "<computed_field>": "<expression using raw item fields + org columns>"
    }},
    "aggregate_rules": {{
      "<computed_field>": "<expression using top-level fields>"
    }}
  }}
  Available names: every field on the item/draft + every column on the orgs table.
  Available functions ONLY: round(x, n), abs(x), min(a,b), max(a,b),
    sum_field(items, 'field_name'), count_field(items).
  Mark every field these rules produce as "computed": true in entity_schema.
  Example for a GST invoice:
    calc_rules = {{
      "item_rules": {{
        "gst": "round(unit_price * qty * gst_rate / 100, 2)",
        "total": "round(unit_price * qty + gst, 2)"
      }},
      "aggregate_rules": {{
        "total_amount": "round(sum_field(items, 'total'), 2)"
      }}
    }}
  For read workflows: {{}}.

RULE 14 â€” steps (REQUIRED for workflow_type="action"):
  Ordered array of {{"op": ..., "params": {{...}}}} â€” this IS the execution logic.
  Available ops:
    resolve_entity   â€” look up a named entity (customer, vendorâ€¦) from any table
      params: {{table, name_from: "$fields.<field>", into: "<alias>", match_column: "name"}}
    compute          â€” run QA verification + recompute all calc_rules
      params: {{}}
    otp_gate         â€” halt for OTP if amount >= otp_threshold
      params: {{amount_field: "$computed.<total_field>"}}
    approval_gate    â€” halt for approval if amount >= approval_threshold
      params: {{amount_field: "$computed.<total_field>"}}
    db.insert_row    â€” insert one row into any table
      params: {{
        table: "<table_name>",
        values: {{
          "<column>": "$fields.<field>" | "$computed.<field>" | "$<alias>.id" | "$org_id" | "$user.user_id" | "literal_value"
        }},
        sequence: {{field: "<doc_number_column>", prefix: "INV-", start: 100}}
      }}
    pdf.generate     â€” generate PDF from pdf_config
      params: {{subtitle: ""}}
    notify.whatsapp  â€” send PDF + success message
      params: {{attach_pdf: true}}
  Typical pipeline for an invoice/quotation:
    resolve_entity â†’ compute â†’ otp_gate â†’ approval_gate â†’ db.insert_row â†’ pdf.generate â†’ notify.whatsapp
  For read workflows: [].

RULE 15 â€” pdf_config render_instructions and theme (for action workflows):
  Add these two keys to pdf_config:
  "theme": {{"primary": "#hex", "light_bg": "#hex", "text": "#hex", "muted": "#hex"}}
  "render_instructions": "200-400 words describing the exact document layout â€”
    badge/header style, customer block, items table columns and alignment,
    totals block structure, footer text, any special formatting.
    Written as instructions for an LLM to follow when building the HTML."

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• MANDATORY FIELDS â€” NEVER EMPTY â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

CRITICAL: The following fields MUST ALWAYS be populated with valid content. Never return empty arrays or null for these:
- training_phrases: MUST have 8-12 phrases. Never empty [].
- entity_schema: MUST include all entities mentioned in training_phrases. Never empty {{}}.
- business_glossary: MUST have 3-6 term mappings. Never empty {{}}.
- llm_system_prompt: MUST be a focused prompt under 300 words. Never null or empty string.

If you cannot determine appropriate values for these fields from the description, make reasonable assumptions based on the workflow type and database schema.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• OUTPUT FORMAT â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

Return ONLY this JSON, no markdown, no explanation:
{{
  "name": "2-4 word display name",
  "intent_key": "snake_case_unique_key",
  "workflow_type": "read|action",
  "description": "One clear sentence: what does this workflow do and for whom.",
  "training_phrases": ["phrase1", "phrase2", "...8-12 phrases total"],
  "entity_schema": {{}},
  "sql_template": "SELECT ... (null for action workflows)",
  "sql_params_order": [],
  "response_format": "format_name or null",
  "business_glossary": {{}},
  "llm_system_prompt": "...",
  "adapter_method": "module.function or null",
  "steps": ["Step 1", "Step 2", "Step 3"],
  "otp_required": false,
  "otp_threshold": null,
  "approval_threshold": null,
  "pdf_config": {{
    "doc_type": "report|invoice|statement|orders|quotation",
    "title_template": "...",
    "aging_analysis": true/false,
    "show_key_insights": true/false,
    "insight_focus": "..."
  }} or null,
  "response_template": "..." or null
}}"""

    last_error = "Unknown error"
    for attempt in range(3):
        try:
            response = await openai_client.chat.completions.create(
                model="gpt-4o",
                max_tokens=4000,
                temperature=0.1 + (attempt * 0.1),   # slight temp bump on retry
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.choices[0].message.content.strip()
            if "```" in content:
                start = content.find("{")
                end   = content.rfind("}") + 1
                content = content[start:end]

            config = json.loads(content)
            config["trigger_patterns"] = []

            raw_steps = config.get("steps", [])
            if isinstance(raw_steps, str):
                raw_steps = json.loads(raw_steps)
            config["steps"] = [s if isinstance(s, str) else json.dumps(s) for s in raw_steps]

            # Validate â€” if any field is missing, retry instead of crashing
            phrases = config.get("training_phrases", [])
            if not phrases or len(phrases) < 5:
                last_error = f"Attempt {attempt+1}: only {len(phrases)} training_phrases (need â‰¥5)"
                print(f"[GENERATE] {last_error} â€” retrying")
                continue
            if not config.get("entity_schema"):
                last_error = f"Attempt {attempt+1}: empty entity_schema"
                print(f"[GENERATE] {last_error} â€” retrying")
                continue
            if not config.get("business_glossary"):
                last_error = f"Attempt {attempt+1}: empty business_glossary"
                print(f"[GENERATE] {last_error} â€” retrying")
                continue
            if not config.get("llm_system_prompt"):
                last_error = f"Attempt {attempt+1}: empty llm_system_prompt"
                print(f"[GENERATE] {last_error} â€” retrying")
                continue
            # Action workflows must have steps[]
            if config.get("workflow_type") == "action" and not config.get("steps"):
                last_error = f"Attempt {attempt+1}: action workflow missing steps[]"
                print(f"[GENERATE] {last_error} â€” retrying")
                continue

            print(f"[GENERATE] âœ… Succeeded on attempt {attempt+1}")
            return config

        except json.JSONDecodeError as e:
            last_error = f"Attempt {attempt+1}: invalid JSON â€” {e}"
            print(f"[GENERATE] {last_error} â€” retrying")
            continue

    raise HTTPException(
        status_code=500,
        detail=f"Failed after 3 attempts. Last error: {last_error}"
    )


@router.post("/admin/api/workflow/save")
async def save_generated_workflow(request: Request):
    _check_token(request)
    body = await request.json()

    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1")
    if not org:
        raise HTTPException(status_code=404, detail="No active org found")
    org_id = str(org["id"])

    existing = await fetch_one(
        "SELECT id FROM workflows WHERE org_id = $1 AND intent_key = $2",
        org_id, body.get("intent_key")
    )
    if existing:
        raise HTTPException(status_code=400, detail="Intent key already exists")

    # Validate mandatory fields are not empty
    training_phrases = body.get("training_phrases", [])
    entity_schema = body.get("entity_schema", {})
    business_glossary = body.get("business_glossary", {})
    llm_system_prompt = body.get("llm_system_prompt")

    if not training_phrases or len(training_phrases) < 5:
        raise HTTPException(status_code=400, detail="training_phrases must have at least 5 phrases")
    if not entity_schema:
        raise HTTPException(status_code=400, detail="entity_schema cannot be empty")
    if not business_glossary:
        raise HTTPException(status_code=400, detail="business_glossary cannot be empty")
    if not llm_system_prompt:
        raise HTTPException(status_code=400, detail="llm_system_prompt cannot be empty")

    try:
        await execute("""
            INSERT INTO workflows (
                org_id, name, intent_key, description,
                workflow_type, training_phrases, entity_schema,
                sql_template, sql_params_order, response_format,
                business_glossary, llm_system_prompt,
                trigger_patterns, adapter_method,
                otp_required, otp_threshold, approval_threshold,
                is_active, steps,
                pdf_config, response_template, calc_rules
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6::jsonb, $7::jsonb,
                $8, $9::jsonb, $10,
                $11::jsonb, $12,
                '[]'::jsonb, $13,
                $14, $15, $16,
                true, $17::jsonb,
                $18::jsonb, $19, $20::jsonb
            )
        """,
            org_id,
            body.get("name"),
            body.get("intent_key"),
            body.get("description"),
            body.get("workflow_type", "action"),
            json.dumps(body.get("training_phrases", [])),
            json.dumps(body.get("entity_schema", {})),
            body.get("sql_template"),
            json.dumps(body.get("sql_params_order", [])),
            body.get("response_format") or "generic",
            json.dumps(body.get("business_glossary", {})),
            body.get("llm_system_prompt"),
            body.get("adapter_method") or "generic",
            body.get("otp_required", False),
            body.get("otp_threshold"),
            body.get("approval_threshold"),
            json.dumps(body.get("steps", [])),
            json.dumps(body.get("pdf_config")) if body.get("pdf_config") else None,
            body.get("response_template"),
            json.dumps(body.get("calc_rules", {})),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error saving workflow: {e}")

    # Grant permissions to selected roles
    intent_key = body.get("intent_key")
    for role_name in body.get("roles", ["owner"]):
        await execute("""
            UPDATE roles
            SET permissions = array_append(permissions, $1)
            WHERE name = $2 AND NOT $1 = ANY(permissions)
        """, intent_key, role_name)

    return {"success": True, "message": f"Workflow '{body.get('name')}' created successfully"}


@router.post("/admin/api/gst-rate")
async def update_gst_rate(request: Request):
    _check_token(request)
    body = await request.json()
    gst = float(body.get("gst_rate", 3.0))
    await execute(
        "UPDATE orgs SET gst_rate = $1 WHERE is_active = true", gst
    )
    return {"gst_rate": gst}


# â”€â”€ New endpoints: workflow detail, edit, delete, chat builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/admin/api/workflow/{workflow_id}/detail")
async def get_workflow_detail(workflow_id: str, request: Request):
    _check_token(request)
    row = await fetch_one("SELECT * FROM workflows WHERE id = $1", workflow_id)
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return dict(row)


@router.put("/admin/api/workflow/{workflow_id}")
async def update_workflow(workflow_id: str, request: Request):
    _check_token(request)
    body = await request.json()

    allowed = [
        "name", "description", "is_active", "otp_required", "otp_threshold",
        "approval_threshold", "training_phrases", "entity_schema", "calc_rules",
        "steps", "sql_template", "sql_params_order", "response_format",
        "business_glossary", "llm_system_prompt", "pdf_config",
        "response_template", "workflow_type"
    ]
    jsonb_fields = {
        "training_phrases", "entity_schema", "calc_rules", "steps",
        "sql_params_order", "business_glossary", "pdf_config"
    }

    sets, vals = [], []
    for field in allowed:
        if field in body:
            sets.append(f"{field} = ${len(vals)+2}")
            val = body[field]
            if field in jsonb_fields:
                val = json.dumps(val) if not isinstance(val, str) else val
                sets[-1] = f"{field} = ${len(vals)+2}::jsonb"
            vals.append(val)

    if not sets:
        raise HTTPException(status_code=400, detail="No fields to update")

    await execute(
        f"UPDATE workflows SET {', '.join(sets)} WHERE id = $1",
        workflow_id, *vals
    )
    return {"success": True}


@router.delete("/admin/api/workflow/{workflow_id}")
async def delete_workflow(workflow_id: str, request: Request):
    _check_token(request)
    row = await fetch_one(
        "SELECT intent_key, org_id FROM workflows WHERE id = $1", workflow_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    # Remove from roles permissions
    await execute("""
        UPDATE roles SET permissions = array_remove(permissions, $1)
        WHERE org_id = $2
    """, row["intent_key"], row["org_id"])
    await execute("DELETE FROM workflows WHERE id = $1", workflow_id)
    return {"success": True, "deleted": row["intent_key"]}


@router.post("/admin/api/workflow-builder/chat")
async def workflow_builder_chat(request: Request):
    _check_token(request)
    body = await request.json()
    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1")
    if not org:
        raise HTTPException(status_code=404, detail="No active org found")
    org_id = str(org["id"])

    from app.services.workflow_builder_agent import run_builder_agent
    result = await run_builder_agent(
        message=body.get("message", ""),
        org_id=org_id,
        draft_id=body.get("draft_id"),
        attachment_b64=body.get("attachment"),
    )
    return result


@router.post("/admin/api/workflow-builder/pdf-extract")
async def extract_pdf_template_endpoint(request: Request):
    _check_token(request)
    form = await request.form()
    upload = form.get("pdf_file")
    doc_type_hint = form.get("doc_type_hint", "")
    if not upload:
        raise HTTPException(status_code=400, detail="pdf_file is required")
    pdf_bytes = await upload.read()
    from app.services.pdf_template_extractor import extract_pdf_template
    try:
        spec = await extract_pdf_template(pdf_bytes, doc_type_hint)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not analyze PDF: {e}")
    return spec




def _build_html(token: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OrchestrAI Admin</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f4f8;color:#1a1a2e;font-size:14px}}
.header{{background:#185FA5;color:#fff;padding:16px 28px;display:flex;justify-content:space-between;align-items:center}}
.header h1{{font-size:20px;font-weight:600}}
.container{{max-width:1200px;margin:0 auto;padding:24px 20px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}}
.stat-card{{background:#fff;border-radius:10px;padding:18px 20px;border-left:4px solid #185FA5;box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
.stat-label{{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:6px}}
.stat-value{{font-size:26px;font-weight:600;color:#185FA5}}
.stat-sub{{font-size:11px;color:#aaa;margin-top:3px}}
.card{{background:#fff;border-radius:10px;padding:20px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
.card-title{{font-size:14px;font-weight:600;color:#185FA5;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid #e8edf5}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.6px;color:#888;padding:0 0 10px 0;font-weight:500}}
td{{padding:10px 0;border-bottom:1px solid #f0f4f8;font-size:13px;vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
.badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500}}
.badge-active{{background:#dcfce7;color:#16a34a}}
.badge-inactive{{background:#fee2e2;color:#dc2626}}
.badge-read{{background:#dbeafe;color:#185FA5}}
.badge-action{{background:#fef3c7;color:#d97706}}
.toggle{{position:relative;width:42px;height:24px;display:inline-block}}
.toggle input{{opacity:0;width:0;height:0}}
.slider{{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:#ccc;border-radius:24px;transition:.3s}}
.slider:before{{position:absolute;content:"";height:18px;width:18px;left:3px;bottom:3px;background:white;border-radius:50%;transition:.3s}}
input:checked+.slider{{background:#185FA5}}
input:checked+.slider:before{{transform:translateX(18px)}}
.threshold-input{{border:1px solid #e8edf5;border-radius:6px;padding:4px 8px;font-size:12px;color:#1a1a2e}}
.threshold-input:focus{{outline:none;border-color:#185FA5}}
.btn{{border:none;border-radius:6px;padding:6px 14px;font-size:12px;cursor:pointer;font-weight:500}}
.btn-primary{{background:#185FA5;color:#fff}}
.btn-purple{{background:#8b5cf6;color:#fff}}
.btn-danger{{background:#dc2626;color:#fff}}
.btn-gray{{background:#e5e7eb;color:#374151}}
.btn:hover{{opacity:0.88}}
.loading{{text-align:center;padding:40px;color:#888}}
/* Modal */
.modal-bg{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100;align-items:center;justify-content:center}}
.modal-bg.open{{display:flex}}
.modal{{background:#fff;border-radius:12px;padding:24px;width:90%;max-width:800px;max-height:90vh;overflow-y:auto}}
.modal-title{{font-size:16px;font-weight:600;margin-bottom:16px;color:#185FA5}}
.field-row{{margin-bottom:12px}}
.field-label{{font-size:11px;color:#888;text-transform:uppercase;margin-bottom:4px}}
.field-input{{width:100%;border:1px solid #e8edf5;border-radius:6px;padding:7px 10px;font-size:13px;font-family:inherit}}
.field-input:focus{{outline:none;border-color:#8b5cf6}}
.json-editor{{width:100%;border:1px solid #e8edf5;border-radius:6px;padding:8px;font-size:12px;font-family:monospace;min-height:120px;resize:vertical}}
/* Chat builder */
.chat-messages{{height:320px;overflow-y:auto;border:1px solid #e8edf5;border-radius:8px;padding:12px;background:#fafbfc;margin-bottom:10px}}
.chat-msg{{margin-bottom:10px;display:flex}}
.chat-msg.user{{justify-content:flex-end}}
.chat-bubble{{max-width:80%;padding:9px 13px;border-radius:10px;font-size:13px;white-space:pre-wrap;line-height:1.5}}
.chat-msg.user .chat-bubble{{background:#8b5cf6;color:#fff}}
.chat-msg.bot .chat-bubble{{background:#fff;border:1px solid #e8edf5;color:#1a1a2e}}
.summary-card{{background:#f0fdf4;border:2px solid #16a34a;border-radius:8px;padding:14px;margin:10px 0;font-size:13px;line-height:1.6}}
.chat-input-row{{display:flex;gap:8px}}
</style>
</head>
<body>
<div class="header">
  <h1>🎛 OrchestrAI Admin</h1>
  <span id="orgName">Loading...</span>
</div>
<div class="container">
  <div id="loading" class="loading">Loading...</div>
  <div id="content" style="display:none">

    <div class="stats" id="statsGrid"></div>

    <!-- ── WORKFLOW LIST ─────────────────────────────────────────── -->
    <div class="card">
      <div class="card-title" style="display:flex;justify-content:space-between;align-items:center">
        <span>⚙️ Workflows</span>
        <button class="btn btn-purple" onclick="openBuilderChat()">✨ Build New Workflow</button>
      </div>
      <table>
        <thead><tr>
          <th>Name</th><th>Type</th><th>Active</th>
          <th>OTP Threshold</th><th>Approval Threshold</th><th>Actions</th>
        </tr></thead>
        <tbody id="workflowsTable"></tbody>
      </table>
    </div>

    <!-- ── SECURITY ──────────────────────────────────────────────── -->
    <div class="card" style="border-left:4px solid #dc2626">
      <div class="card-title" style="color:#dc2626">🔒 Security — Session Management</div>
      <div style="display:flex;align-items:flex-start;gap:32px;flex-wrap:wrap">
        <div>
          <div class="stat-label">Session Timeout</div>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px">
            <input class="threshold-input" type="number" id="ttl_value" value="8" min="1" style="width:70px">
            <select id="ttl_unit" style="border:1px solid #e8edf5;border-radius:6px;padding:4px 8px;font-size:12px;background:#fff">
              <option value="hours">hours</option>
              <option value="minutes">minutes</option>
            </select>
            <button class="btn btn-primary" onclick="saveTTL()">Save</button>
          </div>
        </div>
        <div style="margin-left:auto">
          <button class="btn btn-danger" onclick="clearSessions()">🔒 Clear All Sessions</button>
          <div style="font-size:11px;color:#aaa;margin-top:4px">Forces all users to re-authenticate</div>
        </div>
      </div>
    </div>

    <!-- ── RECENT ACTIVITY ───────────────────────────────────────── -->
    <div class="card">
      <div class="card-title">📋 Recent Activity</div>
      <table>
        <thead><tr><th>User</th><th>Action</th><th>Timestamp</th><th>Status</th></tr></thead>
        <tbody id="activityTable"></tbody>
      </table>
    </div>

  </div><!-- /content -->
</div><!-- /container -->

<!-- ── WORKFLOW EDIT MODAL ───────────────────────────────────────── -->
<div class="modal-bg" id="editModal">
  <div class="modal">
    <div class="modal-title">✏️ Edit Workflow</div>
    <input type="hidden" id="editId">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div class="field-row">
        <div class="field-label">Name</div>
        <input class="field-input" id="editName">
      </div>
      <div class="field-row">
        <div class="field-label">Intent Key (read-only)</div>
        <input class="field-input" id="editIntentKey" readonly style="background:#f9f9f9">
      </div>
    </div>
    <div class="field-row">
      <div class="field-label">Description</div>
      <textarea class="field-input" id="editDescription" rows="2"></textarea>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
      <div class="field-row">
        <div class="field-label">Workflow Type</div>
        <select class="field-input" id="editType">
          <option value="action">action</option>
          <option value="read">read</option>
        </select>
      </div>
      <div class="field-row">
        <div class="field-label">OTP Threshold (Rs.)</div>
        <input class="field-input" id="editOtpThreshold" type="number">
      </div>
      <div class="field-row">
        <div class="field-label">Approval Threshold (Rs.)</div>
        <input class="field-input" id="editApprovalThreshold" type="number">
      </div>
    </div>
    <div class="field-row">
      <div class="field-label">steps (JSON array)</div>
      <textarea class="json-editor" id="editSteps"></textarea>
    </div>
    <div class="field-row">
      <div class="field-label">calc_rules (JSON)</div>
      <textarea class="json-editor" id="editCalcRules"></textarea>
    </div>
    <div class="field-row">
      <div class="field-label">entity_schema (JSON)</div>
      <textarea class="json-editor" id="editEntitySchema"></textarea>
    </div>
    <div class="field-row">
      <div class="field-label">pdf_config (JSON)</div>
      <textarea class="json-editor" id="editPdfConfig"></textarea>
    </div>
    <div class="field-row">
      <div class="field-label">response_template</div>
      <textarea class="field-input" id="editResponseTemplate" rows="2"></textarea>
    </div>
    <div style="display:flex;gap:8px;margin-top:16px">
      <button class="btn btn-primary" onclick="saveWorkflowEdit()">💾 Save Changes</button>
      <button class="btn btn-gray" onclick="closeModal('editModal')">Cancel</button>
    </div>
  </div>
</div>

<!-- ── WORKFLOW CHAT BUILDER MODAL ──────────────────────────────── -->
<div class="modal-bg" id="builderModal">
  <div class="modal" style="max-width:640px">
    <div class="modal-title" style="display:flex;justify-content:space-between">
      <span>🤖 Build New Workflow</span>
      <button class="btn btn-gray" onclick="closeModal('builderModal')" style="padding:4px 10px">✕</button>
    </div>
    <div id="chatMessages" class="chat-messages"></div>
    <div class="chat-input-row">
      <input type="file" id="chatAttachment" accept="application/pdf" style="display:none"
             onchange="document.getElementById('attachLabel').textContent = this.files[0]?.name || ''">
      <button class="btn btn-gray" onclick="document.getElementById('chatAttachment').click()" title="Attach sample PDF">📎</button>
      <span id="attachLabel" style="font-size:11px;color:#888;align-self:center;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
      <input id="chatInput" class="field-input" placeholder="Describe your workflow..."
             style="flex:1" onkeydown="if(event.key==='Enter'&&!event.shiftKey){{event.preventDefault();sendChatMsg()}}">
      <button class="btn btn-purple" onclick="sendChatMsg()">Send</button>
    </div>
    <div id="builderStatus" style="font-size:11px;color:#888;margin-top:6px;text-align:center"></div>
  </div>
</div>

<script>
const TOKEN = "{token}";
const API  = path => `/admin/api${{path}}?token=${{TOKEN}}`;
let chatDraftId = null;
let chatTyping  = false;

// ── Utility ───────────────────────────────────────────────────────
function closeModal(id) {{ document.getElementById(id).classList.remove('open'); }}
function openModal(id)  {{ document.getElementById(id).classList.add('open'); }}
function fmtRs(v) {{ return v ? 'Rs.' + Number(v).toLocaleString('en-IN') : '—'; }}
function fmtDate(d) {{ return d ? new Date(d).toLocaleString('en-IN',{{dateStyle:'medium',timeStyle:'short'}}) : '—'; }}

// ── Security ──────────────────────────────────────────────────────
async function saveTTL() {{
  const val = parseInt(document.getElementById('ttl_value').value);
  const unit = document.getElementById('ttl_unit').value;
  const mins = unit === 'hours' ? val * 60 : val;
  await fetch(API('/security/ttl'), {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{minutes:mins}})}});
  alert('✅ Session timeout updated');
}}
async function clearSessions() {{
  if (!confirm('⚠️ Log out ALL users immediately?')) return;
  await fetch(API('/sessions/clear'), {{method:'POST'}});
  alert('🔒 All sessions cleared');
}}

// ── Workflow List ─────────────────────────────────────────────────
function renderWorkflows(workflows) {{
  const tbody = document.getElementById('workflowsTable');
  if (!workflows.length) {{
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#aaa;padding:20px">No workflows yet — click Build New Workflow to add one</td></tr>';
    return;
  }}
  tbody.innerHTML = workflows.map(w => `
    <tr>
      <td><strong>${{w.name}}</strong><br><span style="font-size:11px;color:#888">${{w.intent_key}}</span></td>
      <td><span class="badge badge-${{w.workflow_type}}">${{w.workflow_type}}</span></td>
      <td>
        <label class="toggle">
          <input type="checkbox" ${{w.is_active ? 'checked' : ''}} onchange="toggleActive('${{w.id}}',this.checked)">
          <span class="slider"></span>
        </label>
      </td>
      <td>
        <input class="threshold-input" id="otp_${{w.id}}" type="number" value="${{w.otp_threshold||''}}" style="width:90px">
        <button class="btn btn-primary" style="margin-left:4px" onclick="saveOtp('${{w.id}}')">Save</button>
      </td>
      <td>
        <input class="threshold-input" id="apr_${{w.id}}" type="number" value="${{w.approval_threshold||''}}" style="width:90px">
        <button class="btn btn-primary" style="margin-left:4px" onclick="saveApr('${{w.id}}')">Save</button>
      </td>
      <td style="white-space:nowrap">
        <button class="btn btn-gray" onclick="openEdit('${{w.id}}')" style="margin-right:4px">✏️ Edit</button>
        <button class="btn btn-danger" onclick="deleteWorkflow('${{w.id}}','${{w.name}}')">🗑️</button>
      </td>
    </tr>
  `).join('');
}}

async function toggleActive(id, active) {{
  await fetch(API(`/workflow/${{id}}/toggle`), {{method:'POST'}});
}}
async function saveOtp(id) {{
  const val = document.getElementById('otp_' + id).value;
  await fetch(API(`/workflow/${{id}}/threshold`), {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{threshold:parseFloat(val)}})}});
  alert('✅ OTP threshold saved');
}}
async function saveApr(id) {{
  const val = document.getElementById('apr_' + id).value;
  await fetch(API(`/workflow/${{id}}/approval_threshold`), {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{threshold:parseFloat(val)}})}});
  alert('✅ Approval threshold saved');
}}

async function deleteWorkflow(id, name) {{
  if (!confirm(`Delete workflow "${{name}}"?\\nThis cannot be undone.`)) return;
  const r = await fetch(API(`/workflow/${{id}}`), {{method:'DELETE'}});
  const d = await r.json();
  if (d.success) {{ alert('✅ Deleted'); loadData(); }}
  else alert('Error: ' + (d.detail || 'unknown'));
}}

// ── Edit Modal ────────────────────────────────────────────────────
async function openEdit(id) {{
  const r = await fetch(API(`/workflow/${{id}}/detail`));
  const w = await r.json();
  document.getElementById('editId').value = id;
  document.getElementById('editName').value = w.name || '';
  document.getElementById('editIntentKey').value = w.intent_key || '';
  document.getElementById('editDescription').value = w.description || '';
  document.getElementById('editType').value = w.workflow_type || 'action';
  document.getElementById('editOtpThreshold').value = w.otp_threshold || '';
  document.getElementById('editApprovalThreshold').value = w.approval_threshold || '';
  document.getElementById('editSteps').value = JSON.stringify(w.steps || [], null, 2);
  document.getElementById('editCalcRules').value = JSON.stringify(w.calc_rules || {{}}, null, 2);
  document.getElementById('editEntitySchema').value = JSON.stringify(w.entity_schema || {{}}, null, 2);
  document.getElementById('editPdfConfig').value = w.pdf_config ? JSON.stringify(w.pdf_config, null, 2) : '';
  document.getElementById('editResponseTemplate').value = w.response_template || '';
  openModal('editModal');
}}

async function saveWorkflowEdit() {{
  const id = document.getElementById('editId').value;
  let steps, calcRules, entitySchema, pdfConfig;
  try {{
    steps        = JSON.parse(document.getElementById('editSteps').value || '[]');
    calcRules    = JSON.parse(document.getElementById('editCalcRules').value || '{{}}');
    entitySchema = JSON.parse(document.getElementById('editEntitySchema').value || '{{}}');
    const pdfRaw = document.getElementById('editPdfConfig').value.trim();
    pdfConfig    = pdfRaw ? JSON.parse(pdfRaw) : null;
  }} catch(e) {{
    alert('JSON parse error: ' + e.message);
    return;
  }}
  const body = {{
    name:                document.getElementById('editName').value,
    description:         document.getElementById('editDescription').value,
    workflow_type:       document.getElementById('editType').value,
    otp_threshold:       parseFloat(document.getElementById('editOtpThreshold').value) || null,
    approval_threshold:  parseFloat(document.getElementById('editApprovalThreshold').value) || null,
    steps, calc_rules: calcRules, entity_schema: entitySchema, pdf_config: pdfConfig,
    response_template:   document.getElementById('editResponseTemplate').value || null,
  }};
  const r = await fetch(API(`/workflow/${{id}}`), {{
    method:'PUT', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(body)
  }});
  const d = await r.json();
  if (d.success) {{ alert('✅ Saved'); closeModal('editModal'); loadData(); }}
  else alert('Error: ' + (d.detail || JSON.stringify(d)));
}}

// ── Chat Builder ─────────────────────────────────────────────────
function openBuilderChat() {{
  chatDraftId = null;
  document.getElementById('chatMessages').innerHTML = '';
  document.getElementById('chatInput').value = '';
  document.getElementById('attachLabel').textContent = '';
  document.getElementById('builderStatus').textContent = '';
  openModal('builderModal');
  appendBotMsg('Hi! Tell me about the workflow you want to build — what should it do?');
}}

function appendBotMsg(text) {{
  const el = document.createElement('div');
  el.className = 'chat-msg bot';
  el.innerHTML = `<div class="chat-bubble">${{text.replace(/\\n/g,'<br>')}}</div>`;
  document.getElementById('chatMessages').appendChild(el);
  el.scrollIntoView({{behavior:'smooth'}});
}}
function appendUserMsg(text) {{
  const el = document.createElement('div');
  el.className = 'chat-msg user';
  el.innerHTML = `<div class="chat-bubble">${{text}}</div>`;
  document.getElementById('chatMessages').appendChild(el);
  el.scrollIntoView({{behavior:'smooth'}});
}}
function appendSummaryCard(text) {{
  const el = document.createElement('div');
  el.className = 'summary-card';
  el.innerHTML = '📋 <strong>Summary</strong><br><br>' + text.replace(/\\n/g,'<br>');
  document.getElementById('chatMessages').appendChild(el);
  el.scrollIntoView({{behavior:'smooth'}});
}}

async function sendChatMsg() {{
  if (chatTyping) return;
  const input = document.getElementById('chatInput');
  const msg   = input.value.trim();
  if (!msg) return;

  appendUserMsg(msg);
  input.value = '';

  // Handle PDF attachment
  let attachment = null;
  const fileInput = document.getElementById('chatAttachment');
  if (fileInput.files.length) {{
    const buf = await fileInput.files[0].arrayBuffer();
    attachment = btoa(String.fromCharCode(...new Uint8Array(buf)));
    fileInput.value = '';
    document.getElementById('attachLabel').textContent = '';
  }}

  chatTyping = true;
  document.getElementById('builderStatus').textContent = 'Thinking...';

  try {{
    const resp = await fetch(API('/workflow-builder/chat'), {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ message: msg, draft_id: chatDraftId, attachment }})
    }});
    const data = await resp.json();
    chatDraftId = data.draft_id;

    if (data.summary_card) appendSummaryCard(data.summary_card);
    if (data.reply) appendBotMsg(data.reply);

    if (data.published) {{
      document.getElementById('builderStatus').textContent = '✅ Workflow published!';
      setTimeout(() => {{ closeModal('builderModal'); loadData(); }}, 2000);
    }} else {{
      document.getElementById('builderStatus').textContent = '';
    }}
  }} catch(e) {{
    appendBotMsg('Something went wrong — please try again.');
    document.getElementById('builderStatus').textContent = '';
  }}
  chatTyping = false;
}}

// ── Load Data ─────────────────────────────────────────────────────
async function loadData() {{
  try {{
    const resp = await fetch(API('/data'));
    const data = await resp.json();

    document.getElementById('orgName').textContent = data.org.name;

    try {{
      const sec = await fetch(API('/security')).then(r => r.json());
      const mins = sec.session_ttl_minutes || 480;
      if (mins >= 60 && mins % 60 === 0) {{
        document.getElementById('ttl_value').value = mins / 60;
        document.getElementById('ttl_unit').value = 'hours';
      }} else {{
        document.getElementById('ttl_value').value = mins;
        document.getElementById('ttl_unit').value = 'minutes';
      }}
    }} catch(e) {{}}

    const s = data.stats;
    document.getElementById('statsGrid').innerHTML = `
      <div class="stat-card"><div class="stat-label">Paid Invoices</div>
        <div class="stat-value">${{s.total_invoices||0}}</div></div>
      <div class="stat-card" style="border-color:#16a34a">
        <div class="stat-label">Total Revenue</div>
        <div class="stat-value" style="color:#16a34a;font-size:20px">Rs.${{Number(s.total_amount||0).toLocaleString('en-IN')}}</div></div>
      <div class="stat-card" style="border-color:#f59e0b">
        <div class="stat-label">Pending Invoices</div>
        <div class="stat-value" style="color:#f59e0b">${{s.pending_invoices||0}}</div></div>
      <div class="stat-card" style="border-color:#3b82f6">
        <div class="stat-label">Customers</div>
        <div class="stat-value" style="color:#3b82f6">${{s.total_customers||0}}</div></div>
    `;

    renderWorkflows(data.workflows || []);

    const logs = data.recent_logs || [];
    document.getElementById('activityTable').innerHTML = logs.map(l => `
      <tr>
        <td>${{l.user_name || '—'}}</td>
        <td>${{l.intent_key}}</td>
        <td style="color:#888;font-size:12px">${{fmtDate(l.created_at)}}</td>
        <td><span class="badge ${{l.outcome==='success'?'badge-active':l.outcome==='pending'?'badge-inactive':'badge-inactive'}}">${{l.outcome}}</span></td>
      </tr>
    `).join('') || '<tr><td colspan="4" style="color:#aaa">No recent activity</td></tr>';

    document.getElementById('loading').style.display = 'none';
    document.getElementById('content').style.display = 'block';
  }} catch(e) {{
    document.getElementById('loading').textContent = 'Error loading data: ' + e.message;
  }}
}}

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""
