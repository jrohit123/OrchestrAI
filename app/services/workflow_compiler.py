"""
workflow_compiler.py — Single source of truth for workflow compilation.

Extracted from admin.py so both the chat builder and the legacy free-text path
call the same logic. Takes either a workflow_drafts row OR a plain {"description": "..."}
dict and returns a full workflow spec + plain_english_summary.
"""
import json
from app.services.llm_router import chat_completion as _llm_chat
from app.services.prompt_loader import PROMPTS_DIR, _read
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

_COMPILER_WRAPPER, _, _COMPILER_RULES = _read(PROMPTS_DIR / "workflow_compiler.txt").partition("\n===RULES===\n")


def _parse(val, default):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return val if val is not None else default


async def dry_run_sql_template(sql_template: str, sql_params_order: list, org_id: str, source_key: str) -> str | None:
    """
    Plan a compiled read-workflow query against the REAL schema via EXPLAIN —
    this parses and plans the query (checking every table/column reference
    and join) but never executes it, returns no rows, and mutates nothing.
    $1 is always org_id per RULE 4; every other placeholder gets NULL, which
    Postgres can still type-check against its context in the query (the same
    binding mechanism used at real runtime, so a query that fails to plan
    here would also fail for a real user).
    Returns an error message string, or None if the query plans cleanly.
    """
    from app.db import fetch_one
    params = [org_id] + [None] * len(sql_params_order)
    try:
        await fetch_one(f"EXPLAIN {sql_template}", *params, source_key=source_key)
        return None
    except Exception as e:
        return f"sql_template does not run against the live schema — {type(e).__name__}: {e}"


async def compile_workflow_spec(draft: dict, org_id: str, source_key: str = "platform") -> dict:
    """
    Compile a workflow_drafts row (or legacy {"description":"..."} dict) into
    a full spec dict including plain_english_summary.

    Returns the spec dict. Raises ValueError if compilation fails after 3 attempts.
    """
    # Load schema for context using shared business schema function
    from app.services.schema_utils import get_business_schema, format_schema_text
    
    table_cols = await get_business_schema(source_key=source_key)
    schema_text = format_schema_text(table_cols)

    # Detect if this is a chat-built draft or a legacy free-text description
    if "purpose" in draft and draft.get("purpose"):
        raw_fields = _parse(draft.get("raw_fields"), [])
        # Gates are captured deterministically by the builder agent's set_gates
        # tool call, separately from this compile step — the compiler LLM never
        # otherwise sees them. Without this, RULE 16 (plain_english_summary
        # must state "any OTP/approval rule") had nothing to go on and
        # defaulted to "There are no OTP or approval rules" even when a real
        # gate existed, contradicting the actual (correct) gates saved on the
        # draft. Found live: reproduced on two separate test workflows, one
        # with an approval gate and one with an OTP threshold.
        from app.services.workflow_builder_agent import _describe_gate
        draft_gates_for_prompt = _parse(draft.get("gates"), [])
        gates_text = (
            "\n".join(_describe_gate(g) for g in draft_gates_for_prompt)
            if draft_gates_for_prompt else "(none set)"
        )
        description_block = f"""PURPOSE: {draft.get('purpose', '')}
WORKFLOW TYPE HINT: {draft.get('workflow_type', 'unclear — infer from purpose')}
FIELDS DISCUSSED WITH THE ADMIN: {', '.join(raw_fields) if raw_fields else '(none specified yet)'}
BUSINESS RULES MENTIONED: {draft.get('business_rules') or '(none)'}
CONSTRAINTS ALREADY SET (state these accurately in plain_english_summary — do not say "no OTP or approval rules" if any are listed here):
{gates_text}"""
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

    prompt = _COMPILER_WRAPPER.format(
        description_block=description_block,
        pdf_context=pdf_context,
        schema_text=schema_text,
    ) + "\n" + _COMPILER_RULES

    last_error = "Unknown error"
    for attempt in range(3):
        try:
            response = await _llm_chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
                temperature=0.1 + attempt * 0.1,
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

                # gates[] is captured deterministically by the builder agent's
                # set_gates tool call (workflow_builder_agent.py) whenever the
                # admin states a constraint — never guessed by this LLM, so it
                # always wins verbatim over anything the compiler produced.
                draft_gates = draft.get("gates")
                if isinstance(draft_gates, str):
                    try:
                        draft_gates = json.loads(draft_gates)
                    except (json.JSONDecodeError, TypeError):
                        draft_gates = []
                spec["gates"] = draft_gates or []

            # Validate consistency before accepting this attempt
            from app.services.workflow_validator import validate_workflow_config
            problems = validate_workflow_config(spec)
            if problems:
                last_error = f"Attempt {attempt+1}: " + "; ".join(problems)
                logger.warning(f"Validation failed — retrying: {last_error}")
                continue

            # Actually plan the compiled query against the live schema (EXPLAIN —
            # no execution, no rows, nothing mutated) instead of trusting the LLM
            # got table/column names and joins right. workflow_validator's check
            # only catches placeholder-syntax mistakes (e.g. a sentinel like
            # "$current_user" leaking into the SQL text); it can't catch a typo'd
            # column, a bad join, or a type mismatch — the class of error that
            # otherwise only surfaces when a real user triggers the workflow and
            # Postgres rejects it live.
            if spec.get("workflow_type") == "read" and spec.get("sql_template"):
                dry_run_error = await dry_run_sql_template(
                    spec["sql_template"], spec.get("sql_params_order") or [], org_id, source_key
                )
                if dry_run_error:
                    last_error = f"Attempt {attempt+1}: {dry_run_error}"
                    logger.warning(f"SQL dry-run failed — retrying: {last_error}")
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
