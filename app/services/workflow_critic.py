"""
workflow_critic.py — LLM-based semantic critique of a compiled workflow spec.

workflow_validator.py catches structural/internal-consistency bugs
deterministically — does the JSON shape make sense (computed fields marked
correctly, gate levels increasing, etc.). It cannot catch the harder class:
perfectly valid JSON that is semantically wrong — a field mapped to a real
column that means something different than the field name claims, or an
"update" request silently compiled into an unconditional insert. That class
of bug is exactly what native structured-output / schema-conformance
guarantees do NOT catch either (constrained decoding guarantees syntax, not
factual correctness) — it needs an independent semantic review, not a
stricter shape check.

Two narrow critics, not one broad one — research on LLM-as-judge prompting
is consistent that splitting a review into focused questions gets more
reliable verdicts than asking one model "is everything right?" in one shot.
Both force reasoning before verdict (not verdict-first), and both return
problems in the SAME shape workflow_validator.py does, so they plug directly
into workflow_compiler.py's existing guided-re-ask retry loop — a critique
FAIL gets the identical "here's what was wrong, fix it" treatment as a
structural validation failure, for free.

Best-effort only: a critique-call failure (timeout, bad JSON, provider
outage) must never block a workflow from compiling — it's reinforcement on
top of validate_workflow_config, not a replacement gate. Swallow and log,
return no problems, and let the deterministic validator remain the hard
gate it already is.
"""
import json
from app.services.llm_router import chat_completion as _llm_chat
from app.services.prompt_loader import PROMPTS_DIR, _read
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

_FIELD_MAPPING_PROMPT  = _read(PROMPTS_DIR / "critic_field_mapping.txt")
_STEPS_LOGIC_PROMPT    = _read(PROMPTS_DIR / "critic_steps_logic.txt")
_CROSS_CHECK_PROMPT    = _read(PROMPTS_DIR / "cross_check_mapping.txt")

# Whichever provider the main compile call happened to succeed on isn't
# tracked back to the caller today, so rather than plumb that through, the
# cross-check simply always prefers a provider different from the default
# ladder's first choice (see ai_models_config.json's provider_order) — near-
# guaranteed independence without needing to know what actually answered.
_CROSS_CHECK_PROVIDER = "gemini"


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if "```" in text:
        text = text[text.find("{"):text.rfind("}") + 1]
    return json.loads(text)


async def critique_field_mappings(spec: dict, description_block: str, schema_text: str) -> list[str]:
    """Reviews entity_schema's table/column mappings against the original
    request and the schema. Returns a list of problem strings, empty if
    nothing looked wrong (or the critique call itself failed — see module
    docstring on why that fails open, not closed)."""
    entity_schema = spec.get("entity_schema") or {}
    if not entity_schema or not _FIELD_MAPPING_PROMPT:
        return []

    prompt = _FIELD_MAPPING_PROMPT.format(
        description_block=description_block,
        schema_text=schema_text,
        entity_schema_json=json.dumps(entity_schema, indent=2, default=str),
    )
    try:
        response = await _llm_chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2500,
            temperature=0.1,
        )
        result = _extract_json(response.choices[0].message.content)
    except Exception as e:
        logger.warning(f"Field-mapping critique failed, skipping (fail-open): {e}")
        return []

    if not isinstance(result, dict):
        return []

    problems = []
    for field_name, verdict in result.items():
        if not isinstance(verdict, dict):
            continue
        if str(verdict.get("verdict", "")).upper() == "FAIL":
            reasoning = verdict.get("reasoning", "no reasoning given")
            fix = verdict.get("fix_suggestion")
            msg = f"entity_schema['{field_name}'] mapping looks wrong: {reasoning}"
            if fix:
                msg += f" Suggested fix: {fix}"
            problems.append(msg)
    return problems


async def critique_steps_logic(spec: dict, description_block: str) -> list[str]:
    """Reviews steps[] against the original request for CRUD correctness —
    right op for the right intent, branching present when an action/mode
    field demands it, no silent duplicate-alias resolve_entity calls, no
    writes to columns the request said not to touch. Same fail-open
    contract as critique_field_mappings."""
    steps = spec.get("steps") or []
    if not steps or not _STEPS_LOGIC_PROMPT:
        return []

    prompt = _STEPS_LOGIC_PROMPT.format(
        description_block=description_block,
        steps_json=json.dumps(steps, indent=2, default=str),
        entity_schema_json=json.dumps(spec.get("entity_schema") or {}, indent=2, default=str),
    )
    try:
        response = await _llm_chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.1,
        )
        result = _extract_json(response.choices[0].message.content)
    except Exception as e:
        logger.warning(f"Steps-logic critique failed, skipping (fail-open): {e}")
        return []

    if not isinstance(result, dict):
        return []

    if str(result.get("overall_verdict", "")).upper() == "FAIL":
        problems = result.get("problems") or []
        if not problems and result.get("reasoning"):
            problems = [result["reasoning"]]
        return [f"steps logic issue: {p}" for p in problems]
    return []


async def cross_check_field_mappings(spec: dict, description_block: str, schema_text: str) -> list[str]:
    """
    Independent second opinion on entity_schema's table/column mappings,
    deliberately routed through a different provider (see
    _CROSS_CHECK_PROVIDER) than whatever the primary compile+critique calls
    used. Self-consistency reinforcement, NOT a replacement for
    critique_field_mappings — research on best-of-N/self-consistency is
    explicit that two models agreeing doesn't prove correctness (they can
    share the same blind spot), only that DISAGREEING is a meaningful
    signal worth surfacing. Treat this the same way: agreement earns no
    special trust, but a disagreement is worth a human's attention.

    Deliberately does NOT feed into the retry loop's last_error/continue —
    it fails open both on error AND on disagreement. Callers should attach
    the result to the spec for visibility (e.g. spec['_cross_check_warnings'])
    rather than block publishing on it alone.
    """
    entity_schema = spec.get("entity_schema") or {}
    field_names = [
        f for f, fs in entity_schema.items()
        if isinstance(fs, dict) and not fs.get("computed") and fs.get("table") and fs.get("column")
    ]
    if not field_names or not _CROSS_CHECK_PROMPT:
        return []

    prompt = _CROSS_CHECK_PROMPT.format(
        description_block=description_block,
        schema_text=schema_text,
        field_names_json=json.dumps(field_names),
    )
    try:
        response = await _llm_chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.1,
            preferred_provider=_CROSS_CHECK_PROVIDER,
        )
        proposed = _extract_json(response.choices[0].message.content)
    except Exception as e:
        logger.info(f"Cross-check call failed, skipping (reinforcement-only, fails open): {e}")
        return []

    if not isinstance(proposed, dict):
        return []

    warnings = []
    for field in field_names:
        their_answer = proposed.get(field)
        if not isinstance(their_answer, dict):
            continue
        our_table, our_col = entity_schema[field].get("table"), entity_schema[field].get("column")
        their_table, their_col = their_answer.get("table"), their_answer.get("column")
        if their_table and their_col and (their_table, their_col) != (our_table, our_col):
            warnings.append(
                f"cross-check disagreement on '{field}': compiled as {our_table}.{our_col}, "
                f"independent second opinion proposed {their_table}.{their_col} — worth a human look, "
                f"not auto-corrected"
            )
    return warnings


async def critique_spec(spec: dict, description_block: str, schema_text: str) -> list[str]:
    """Runs both critics and returns the combined problem list. Order
    doesn't matter — both results feed into the same retry loop the same
    way workflow_validator.py's problems already do."""
    field_problems = await critique_field_mappings(spec, description_block, schema_text)
    steps_problems = await critique_steps_logic(spec, description_block)
    return field_problems + steps_problems
