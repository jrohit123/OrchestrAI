"""The builder's "Ask the AI" step (op ai.ask): the AI does one job with text from the flow.

    {"op": "ai.ask", "params": {
        "task": "write" | "pick" | "extract",
        "instructions": "Be short and polite.",          optional, the admin's own (a system prompt)
        "prompt": "Complaint: {title}, at {location}",   what the AI works on ({data} filled in)
        "choices": ["Lift", "Plumbing", ...]             pick: the choices, or
                   {"table": "case_categories", "column": "label"}   the values of a column
        "if_unsure": "Other",                            pick: the choice to use when none fits
        "fields": [{"name": "visit_date", "type": "date", "description": "the day of the visit"}],
        "into": "category"}}                             write / pick: the field the answer goes in

write keeps the text the AI wrote; pick keeps exactly one of the choices (never anything else);
extract keeps each detail as its own field. The rest of the flow uses them like any answer.
In a rehearsal ("Try it") the AI is not asked: the fields get a stand-in that says so.
AI is only used where the admin put this step; everything around it stays exact steps.
"""

import json
import re

from app.db import fetch_all
from app.logging_config import get_context_logger
from app.services.prompt_loader import PROMPTS_DIR, _read

logger = get_context_logger(__name__)

_BASE = _read(PROMPTS_DIR / "ai_step.txt") or ""
_TASKS = {
    "write": 'Write the text asked for. Reply {"text": "<the text>"}.',
    "pick": 'Pick the ONE choice that fits the text best. Reply {"choice": "<one of the choices, exactly as written>"}.',
    "extract": 'Pull these details out of the text. Reply {"<name>": <value or null>, ...} with every name listed; null when the text does not say.',
}
_COLUMN = re.compile(r"^[a-z_][a-z0-9_]*$")


def strip_fences(text: str) -> str:
    """The JSON inside an answer that came wrapped in ```json fences, or the answer as it is."""
    text = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return m.group(1) if m else text


def _si():
    from app.services import step_interpreter

    return step_interpreter


async def _choices(params: dict, ctx: dict) -> list[str]:
    given = params.get("choices")
    if isinstance(given, list):
        return [str(c) for c in given if str(c).strip()]
    if isinstance(given, dict):
        table, column = given.get("table"), given.get("column")
        if not (
            isinstance(table, str)
            and isinstance(column, str)
            and _COLUMN.match(table)
            and _COLUMN.match(column)
        ):
            raise _si().StepError("Ask the AI: the list to pick from is not valid.")
        allowed = await _si()._load_schema_allowlist(ctx["source_key"])
        if column not in (allowed.get(table) or set()):
            raise _si().StepError(f"Ask the AI: '{table}' has no column '{column}'.")
        rows = await fetch_all(
            f"SELECT DISTINCT {column} AS v FROM {table} WHERE org_id = $1 AND {column} IS NOT NULL",
            ctx["org_id"],
            source_key=ctx["source_key"],
        )
        return sorted(str(r["v"]) for r in rows)
    return []


def _text(template: str, ctx: dict) -> str:
    return _si()._notify_message({"message_template": template or ""}, ctx)


async def _op_ai_ask(params: dict, ctx: dict) -> dict:
    si = _si()
    task = params.get("task") or "write"
    if task not in _TASKS:
        raise si.StepError(f"Ask the AI: '{task}' is not a job it knows.")
    into = params.get("into")
    fields = [
        f for f in params.get("fields") or [] if isinstance(f, dict) and f.get("name")
    ]
    if task in ("write", "pick") and not into:
        raise si.StepError("Ask the AI: say which field the answer goes in.")
    if task == "extract" and not fields:
        raise si.StepError("Ask the AI: say which details to pull out.")
    choices = await _choices(params, ctx) if task == "pick" else []
    if task == "pick" and not choices:
        raise si.StepError("Ask the AI: there is nothing to pick from.")

    if ctx.get("dry_run"):  # a rehearsal does not call the AI
        stand_in = "(the AI's answer)"
        if task == "extract":
            for f in fields:
                ctx["fields"][f["name"]] = stand_in
        else:
            ctx["fields"][into] = choices[0] if task == "pick" else stand_in
        ctx.setdefault("preview", []).append(
            "The AI will "
            + {
                "write": "write the text",
                "pick": "pick one of " + str(len(choices)) + " choices",
                "extract": "pull out " + ", ".join(f["name"] for f in fields),
            }[task]
        )
        return ctx

    job = _TASKS[task]
    if task == "pick":
        job += "\nThe choices:\n" + "\n".join(f"- {c}" for c in choices)
    if task == "extract":
        job += "\nThe details:\n" + "\n".join(
            f"- {f['name']} ({f.get('type') or 'text'}): {f.get('description') or ''}"
            for f in fields
        )
    own = _text(params.get("instructions") or "", ctx).strip()
    from app.services import platform_prompt

    system = (
        await platform_prompt.preamble(ctx.get("source_key"))
        + "\n\n"
        + _BASE
        + job
        + (f"\nThe organisation's own instructions:\n{own}" if own else "")
    )
    user_text = _text(params.get("prompt") or "", ctx)

    from app.services.llm_router import chat_completion

    try:
        response = await chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            max_tokens=800,
            temperature=float(params.get("temperature") or 0),
        )
        answer = json.loads(strip_fences(response.choices[0].message.content or ""))
    except Exception as e:
        logger.warning(f"ai.ask ({task}) got no usable answer: {e}")
        answer = {}
    if not isinstance(answer, dict):
        answer = {}

    if task == "write":
        text = str(answer.get("text") or "").strip()
        if not text:
            raise si.StepError("Ask the AI: the AI gave no text.")
        ctx["fields"][into] = text
    elif task == "pick":
        said = str(answer.get("choice") or "").strip().lower()
        chosen = next((c for c in choices if c.lower() == said), None)
        if chosen is None:
            chosen = params.get("if_unsure")
            if chosen not in choices:
                raise si.UserFacingStepError(
                    "Sorry, I could not work that out. Please say it another way."
                )
        ctx["fields"][into] = chosen
    else:
        for f in fields:
            value = answer.get(f["name"])
            if value not in (None, ""):
                ctx["fields"][f["name"]] = value
    return ctx


AI_PRIMITIVES = {"ai.ask": _op_ai_ask}
