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

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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
        pdf_analysis = _parse(draft.get("pdf_sample_analysis"), None)
    else:
        description_block = draft.get("description", "")
        pdf_analysis = None

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
  Mark computed fields with "computed": true — these are NEVER collected from the user.

RULE 4 — sql_template: Full parameterized SELECT for read workflows ($1=org_id, $2+ for entities).
  null for action workflows.

RULE 5 — sql_params_order: entity_schema keys in $2,$3... order. [] for action workflows.

RULE 6 — response_format: outstanding_summary|inventory|orders|customers|quotations|invoices|users|generic
  null for action workflows.

RULE 7 — business_glossary: 3-6 term mappings for this specific workflow.

RULE 8 — llm_system_prompt: Under 300 words. What it does, tables involved, 3 example inputs,
  1 disambiguation rule.

RULE 9 — adapter_method: "generic" for all workflows (execution is driven by steps[]).

RULE 10 — intent_key: unique snake_case. reads: describe data. actions: describe action.

RULE 11 — pdf_config: doc_type, title_template, aging_analysis, show_key_insights, insight_focus.
  For action workflows also add theme and render_instructions (RULE 15).

RULE 12 — response_template: WhatsApp message after action. Use {{variable}} placeholders. null for reads.

RULE 13 — calc_rules (action workflows with computed fields):
  item_rules: per-line-item expressions using item fields + org columns.
  aggregate_rules: top-level expressions (e.g. sum of items).
  Available functions: round(x,n), abs(x), min(a,b), max(a,b), sum_field(items,'field'), count_field(items).
  {{}} for read workflows.

RULE 14 — steps (action workflows — this IS the execution logic):
  Ordered array of {{"op":"...", "params":{{...}}}}.
  Available ops:
    resolve_entity  — {{"table","name_from":"$fields.X","into":"alias","match_column":"name"}}
    compute         — {{}}
    otp_gate        — {{"amount_field":"$computed.total_amount"}}
    approval_gate   — {{"amount_field":"$computed.total_amount"}}
    db.insert_row   — {{"table","values":{{"col":"$fields.X|$computed.X|$alias.id|$org_id|$user.user_id|literal"}},
                       "sequence":{{"field":"doc_number_col","prefix":"INV-","start":100}}}}
    pdf.generate    — {{"subtitle":""}}
    notify.whatsapp — {{"attach_pdf":true}}
  Typical pipeline: resolve_entity→compute→otp_gate→approval_gate→db.insert_row→pdf.generate→notify.whatsapp
  [] for read workflows.

RULE 15 — pdf_config theme + render_instructions (action workflows):
  "theme": {{"primary":"#hex","light_bg":"#hex","text":"#hex","muted":"#hex"}}
  "render_instructions": "200-400 words — exact layout instructions for the PDF:
    badge/header style, customer block, items table columns and alignment,
    totals block, footer text. Written so an LLM can rebuild this layout from scratch."

RULE 16 — plain_english_summary (NEW — always required):
  2-5 short lines a non-technical business owner can read in one glance.
  Structure:
    - What it's called and when it triggers (example phrases)
    - What it collects, in plain words
    - What's calculated automatically, if anything
    - Any OTP/approval rule, in plain words
    - What document it produces, if any
  End with: "Shall I create this?"
  No JSON, no field names, no technical jargon.

══════════════════ MANDATORY ══════════════════════════════════════
training_phrases ≥ 8. entity_schema not empty. business_glossary not empty.
llm_system_prompt not null. action workflows must have steps[].

══════════════════ OUTPUT ══════════════════════════════════════════
Return ONLY this JSON, no markdown:
{{
  "name":"...", "intent_key":"...", "workflow_type":"read|action",
  "description":"...", "training_phrases":[...], "entity_schema":{{}},
  "calc_rules":{{}}, "steps":[...], "sql_template":null, "sql_params_order":[],
  "response_format":"...", "business_glossary":{{}}, "llm_system_prompt":"...",
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
