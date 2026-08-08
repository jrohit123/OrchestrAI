"""
workflow_compiler.py — Single source of truth for workflow compilation.

Extracted from admin.py so both the chat builder and the legacy free-text path
call the same logic. Takes either a workflow_drafts row OR a plain {"description": "..."}
dict and returns a full workflow spec + plain_english_summary.
"""
import json
import os
from openai import AsyncOpenAI
from app.db import fetch_all

from app.config import required

_client = AsyncOpenAI(api_key=required("OPENAI_API_KEY"))


def _parse(val, default):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return val if val is not None else default


async def compile_workflow_spec(draft: dict, org_id: str) -> dict:
    """
    Compile a workflow_drafts row (or legacy {"description":"..."} dict) into
    a full spec dict including plain_english_summary.

    Returns the spec dict. Raises ValueError if compilation fails after 3 attempts.
    """
    # Load schema for context
    schema_rows = await fetch_all("""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name IN ('customers','inventory','invoices','orders',
                             'quotations','users','roles')
        ORDER BY table_name, ordinal_position
    """)
    table_cols: dict = {}
    for r in schema_rows:
        table_cols.setdefault(r["table_name"], []).append(r["column_name"])
    schema_text = "\n".join(
        f"  {t}: {', '.join(cs)}" for t, cs in sorted(table_cols.items())
    )

    # Detect if this is a chat-built draft or a legacy free-text description
    if "purpose" in draft and draft.get("purpose"):
        raw_fields = _parse(draft.get("raw_fields"), [])
        description_block = f"""PURPOSE: {draft.get('purpose', '')}
WORKFLOW TYPE HINT: {draft.get('workflow_type', 'unclear — infer from purpose')}
FIELDS DISCUSSED WITH THE ADMIN: {', '.join(raw_fields) if raw_fields else '(none specified yet)'}
BUSINESS RULES MENTIONED: {draft.get('business_rules') or '(none)'}"""
        # Always check for PDF analysis regardless of how the draft was built
        pdf_analysis = _parse(draft.get("pdf_sample_analysis"), None)
    else:
        description_block = draft.get("description", "")
        pdf_analysis = _parse(draft.get("pdf_sample_analysis"), None)

    # If admin uploaded a sample PDF, inject the extracted layout spec
    pdf_context = ""
    if pdf_analysis:
        pdf_context = f"""
ADMIN UPLOADED A SAMPLE PDF — replicate this exact layout in render_instructions:
  doc_type_guess  : {pdf_analysis.get('doc_type_guess')}
  theme           : {json.dumps(pdf_analysis.get('theme', {}))}
  render_instructions: {pdf_analysis.get('render_instructions', '')}
"""

    prompt = f"""You are a Workflow Compiler for a multi-sector WhatsApp ERP system.
The admin wants to add a workflow. Generate a COMPLETE structured workflow record as JSON.

ADMIN DESCRIPTION:
{description_block}
{pdf_context}

DATABASE SCHEMA (available tables):
{schema_text}

══════════════════════════ RULES ══════════════════════════════════

RULE 1 — workflow_type: read or action. When uncertain, prefer "read".

RULE 2 — training_phrases: 8-12 realistic WhatsApp-style phrases, English + Hinglish.
  Use {{slot_name}} for entity placeholders.

RULE 3 — entity_schema: Only entities actually needed. Per field:
  table, column, match (ILIKE/exact), required, format (wildcard/exact), type (string/integer/float)
  CRITICAL: Mark computed fields with "computed": true — these are NEVER collected from the user.
  For items arrays, include item_schema with per-item field definitions.
  Example for an invoice with computed GST:
  {{
    "customer_name": {{"type":"string","required":true,"table":"customers","column":"name","match":"ILIKE","format":"wildcard"}},
    "items": {{
      "type":"array","required":true,
      "item_schema": {{
        "description": {{"type":"string","required":true}},
        "qty":         {{"type":"integer","required":true}},
        "unit_price":  {{"type":"float","required":true}},
        "gst":         {{"type":"float","required":false,"computed":true}},
        "total":       {{"type":"float","required":false,"computed":true}}
      }}
    }},
    "total_amount": {{"type":"float","required":false,"computed":true}}
  }}
  RULE: Every field produced by calc_rules MUST appear in entity_schema with "computed":true.
  RULE: Never mark a computed field as "required":true — the user never provides it.

RULE 4 — sql_template: Full parameterized SELECT for read workflows ($1=org_id, $2+ for entities).
  null for action workflows.

RULE 5 — sql_params_order: entity_schema keys in $2,$3... order. [] for action workflows.

RULE 6 — response_format: outstanding_summary|inventory|orders|customers|quotations|invoices|users|generic
  null for action workflows.

RULE 7 — business_glossary: 3-6 term mappings for this specific workflow.

RULE 8 — llm_system_prompt: Under 300 words. What it does, tables involved, 3 example inputs,
  1 disambiguation rule. Include the exact intent_key so the agent knows which workflow to use.

RULE 9 — adapter_method: "generic" for all workflows (execution is driven by steps[]).

RULE 10 — intent_key: unique snake_case. CRITICAL: Use EXACTLY these keys for standard workflows:
  - Creating a sales invoice → "create_sales_invoice"
  - Generating a price quotation → "generate_price_quotation"
  - Updating order status → "update_order_status"
  - Setting metal rates → "set_metal_rate"
  - Customer dues statement → "get_customer_dues_statement"
  For any other workflow, derive a clear snake_case key from the purpose.

RULE 11 — pdf_config: doc_type, title_template, aging_analysis, show_key_insights, insight_focus.
  For action workflows also add theme and render_instructions (RULE 15).

RULE 12 — response_template: WhatsApp message after action. Use {{variable}} placeholders. null for reads.

RULE 13 — calc_rules (action workflows with computed fields):
  item_rules: per-line-item expressions using item fields + org columns (e.g. gst_rate from orgs).
  aggregate_rules: top-level expressions (e.g. sum of items).
  Available functions: round(x,n), abs(x), min(a,b), max(a,b), sum_field(items,'field'), count_field(items).
  CRITICAL: Every field produced here MUST have "computed":true in entity_schema.
  CRITICAL: NEVER hardcode tax rates as decimals (0.03, 0.1). ALWAYS use org column names
  from the orgs table — for GST use "gst_rate" which is the actual column name:
    CORRECT: "round(unit_price * qty * gst_rate / 100, 2)"
    WRONG:   "round(unit_price * qty * 0.03, 2)"
  Example for GST invoice:
  {{
    "item_rules": {{
      "gst":   "round(unit_price * qty * gst_rate / 100, 2)",
      "total": "round(unit_price * qty + gst, 2)"
    }},
    "aggregate_rules": {{
      "total_amount": "round(sum_field(items, 'total'), 2)"
    }}
  }}
  {{}} for read workflows.

RULE 14 — steps (action workflows — this IS the execution logic):
  Ordered array of {{"op":"...", "params":{{...}}}}.
  Available ops:
    resolve_entity  — {{"table","name_from":"$fields.X","into":"alias","match_column":"name"}}
                      optional: "expose":{{"ctx_alias":"db_column"}} to copy row values into fields
    compute         — {{}} — REQUIRED whenever calc_rules is non-empty
    otp_gate        — {{"amount_field":"$computed.total_amount"}}
    approval_gate   — {{"amount_field":"$computed.total_amount"}}
    db.insert_row   — {{"table","values":{{"col":"$fields.X|$computed.X|$alias.id|$org_id|$user.user_id|literal"}},
                       "sequence":{{"field":"doc_number_col","prefix":"INV-","start":100}}}}
    db.update_row   — {{"table","set":{{"col":"$fields.X|NOW()"}},"where":{{"col":"$alias.id"}}}}
    db.upsert_row   — {{"table","values":{{...}},"conflict_columns":["col1","col2"]}}
    pdf.generate    — {{"subtitle":""}}
    notify.whatsapp — {{"attach_pdf":true}}

  CRITICAL DB INSERT RULES:
  - status values MUST be lowercase: "pending" NOT "PENDING", "sent" NOT "SENT"
  - For due dates use the special literal "TODAY+30" (30 days from today) or "TODAY"
    NEVER use SQL expressions like "NOW() + INTERVAL '30 days'" — they don't work as string literals
  - Never include columns that have DB defaults (created_at, updated_at) — let the DB handle them

  Example invoice insert:
  {{"op":"db.insert_row","params":{{"table":"invoices","values":{{
    "org_id":"$org_id","customer_id":"$customer.id","created_by":"$user.user_id",
    "items":"$fields.items","amount":"$computed.total_amount",
    "status":"pending","due_date":"TODAY+30"
  }},"sequence":{{"field":"invoice_number","prefix":"INV-","start":100}}}}}}

  Typical pipeline for invoice/quotation:
    resolve_entity → compute → otp_gate → approval_gate → db.insert_row → pdf.generate → notify.whatsapp
  For status update: resolve_entity → db.update_row → notify.whatsapp
  [] for read workflows.

RULE 15 — pdf_config theme + render_instructions (action workflows):
  "theme": {{"primary":"#hex","light_bg":"#hex","text":"#hex","muted":"#hex"}}
  "render_instructions": "200-400 words — exact layout instructions for the PDF:
    header style (badges, org name placement), customer/recipient block,
    items table columns with alignment (right-align amounts, center qty),
    totals block structure (subtotal, tax, grand total),
    footer text, any special visual elements.
    Written so an AI can rebuild this exact layout with new data."

RULE 16 — plain_english_summary (always required):
  2-5 short lines a non-technical business owner can read in one glance.
  - What it's called and when it triggers (example phrases)
  - What it collects, in plain words
  - What's calculated automatically, if anything
  - Any OTP/approval rule, in plain words
  - What document it produces, if any
  End with: "Shall I create this?"
  No JSON, no field names, no technical jargon.

══════════════════ MANDATORY VALIDATION ═══════════════════════════
BEFORE generating the final JSON, verify:
  1. Every field in calc_rules item_rules/aggregate_rules appears in entity_schema with "computed":true
  2. No computed field has "required":true
  3. Action workflows have at least resolve_entity + db.insert_row in steps (unless it's an update/upsert)
  4. training_phrases has ≥ 8 phrases
  5. plain_english_summary is present and ends with "Shall I create this?"

══════════════════ OUTPUT ══════════════════════════════════════════
Return ONLY this JSON, no markdown:
{{
  "name":"...", "intent_key":"...", "workflow_type":"read|action",
  "description":"...", "training_phrases":[...], "entity_schema":{{}},
  "calc_rules":{{}}, "steps":[...], "sql_template":null, "sql_params_order":[],
  "response_format":null, "business_glossary":{{}}, "llm_system_prompt":"...",
  "adapter_method":"generic", "otp_required":false, "otp_threshold":null,
  "approval_threshold":null,
  "pdf_config":{{"doc_type":"...","title_template":"...","theme":{{}},"render_instructions":"..."}},
  "response_template":"...",
  "plain_english_summary":"..."
}}"""

    last_error = "Unknown error"
    for attempt in range(3):
        try:
            response = await _client.chat.completions.create(
                model="gpt-4o",
                max_tokens=4000,
                temperature=0.1 + attempt * 0.1,
                messages=[{"role": "user", "content": prompt}]
            )
            content = response.choices[0].message.content.strip()
            if "```" in content:
                content = content[content.find("{"):content.rfind("}") + 1]

            spec = json.loads(content)

            # Normalize steps to list of dicts (not strings)
            raw_steps = spec.get("steps", [])
            if isinstance(raw_steps, str):
                raw_steps = json.loads(raw_steps)
            spec["steps"] = [
                json.loads(s) if isinstance(s, str) else s
                for s in raw_steps
            ]

            # Auto-fix: ensure every calc_rules field is marked computed:true in entity_schema
            calc_rules = spec.get("calc_rules") or {}
            entity_schema = spec.get("entity_schema") or {}
            item_rules = calc_rules.get("item_rules") or {}
            aggregate_rules = calc_rules.get("aggregate_rules") or {}

            # Fix aggregate-level computed fields
            for field_name in aggregate_rules:
                if field_name not in entity_schema:
                    entity_schema[field_name] = {"type": "float", "required": False, "computed": True}
                else:
                    entity_schema[field_name]["computed"] = True
                    entity_schema[field_name]["required"] = False

            # Fix item-level computed fields — they go into items.item_schema
            if item_rules:
                items_def = entity_schema.get("items") or {}
                item_schema = items_def.get("item_schema") or {}
                for field_name in item_rules:
                    if field_name not in item_schema:
                        item_schema[field_name] = {"type": "float", "required": False, "computed": True}
                    else:
                        item_schema[field_name]["computed"] = True
                        item_schema[field_name]["required"] = False
                items_def["item_schema"] = item_schema
                entity_schema["items"] = items_def

            spec["entity_schema"] = entity_schema

            # Passthrough: if PDF was uploaded, use extractor's render_instructions verbatim
            # Never let the compiler rewrite what the extractor already got right
            pdf_analysis = _parse(draft.get("pdf_sample_analysis"), None) if isinstance(draft, dict) else None
            if pdf_analysis and isinstance(pdf_analysis, dict):
                spec["pdf_config"] = {
                    **(spec.get("pdf_config") or {}),
                    "doc_type": (
                        pdf_analysis.get("doc_type_guess")
                        or (spec.get("pdf_config") or {}).get("doc_type", "report")
                    ),
                    "theme": (
                        pdf_analysis.get("theme")
                        or (spec.get("pdf_config") or {}).get("theme")
                    ),
                    "render_instructions": pdf_analysis.get("render_instructions"),
                }

            # Override OTP/approval thresholds from structured draft columns
            # These were captured precisely when the admin stated them — always win over LLM guesses
            if isinstance(draft, dict):
                if draft.get("otp_threshold") is not None:
                    spec["otp_required"] = True
                    spec["otp_threshold"] = float(draft["otp_threshold"])
                if draft.get("approval_threshold") is not None:
                    spec["approval_threshold"] = float(draft["approval_threshold"])

            # Validate consistency before accepting this attempt
            from app.services.workflow_validator import validate_workflow_config
            problems = validate_workflow_config(spec)
            if problems:
                last_error = f"Attempt {attempt+1}: " + "; ".join(problems)
                print(f"[COMPILER] Validation failed — retrying: {last_error}")
                continue

            # Validate mandatory fields
            if not spec.get("training_phrases") or len(spec["training_phrases"]) < 5:
                last_error = f"Attempt {attempt+1}: insufficient training_phrases"
                continue
            if not spec.get("entity_schema"):
                last_error = f"Attempt {attempt+1}: empty entity_schema"
                continue
            if not spec.get("business_glossary"):
                last_error = f"Attempt {attempt+1}: empty business_glossary"
                continue
            if not spec.get("llm_system_prompt"):
                last_error = f"Attempt {attempt+1}: empty llm_system_prompt"
                continue
            if spec.get("workflow_type") == "action" and not spec.get("steps"):
                last_error = f"Attempt {attempt+1}: action workflow missing steps"
                continue
            if not spec.get("plain_english_summary"):
                last_error = f"Attempt {attempt+1}: missing plain_english_summary"
                continue

            return spec

        except json.JSONDecodeError as e:
            last_error = f"Attempt {attempt+1}: JSON parse error — {e}"
            continue

    raise ValueError(f"Compilation failed after 3 attempts: {last_error}")
