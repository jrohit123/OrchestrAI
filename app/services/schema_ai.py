"""The AI's part of the schema editor: it reads a plain description and DRAFTS ops (app/services/schema_ops.py). It writes no
SQL, applies nothing and touches nothing; a super admin sees the plan, can change it, and applies it. If the AI is down or
answers badly, the person is told and can still make the change by hand."""

import json

from pydantic import TypeAdapter, ValidationError

from app.logging_config import get_context_logger
from app.services.llm_router import chat_completion as _llm_chat
from app.services.schema_ops import KINDS, MAX_FIELDS, Op, World

logger = get_context_logger(__name__)

_OPS = TypeAdapter(list[Op])

_SYSTEM = """You help a super admin of a society / business chat bot add a new kind of record to their database.
You never write SQL. You answer with ONE JSON object and nothing else.

If something essential is missing (what is kept, or what each record needs), ask at most 3 short plain questions:
  {"questions": ["...", "..."]}
Otherwise draft the change:
  {"intro": "one or two plain sentences", "ops": [ ... ]}

The ops you may use (nothing else exists):
  {"op": "create_record_type", "label": "Visitor", "plural": "Visitors", "prefix": "VS", "icon": "🚪", "about": "one line",
   "statuses": [{"label": "Expected"}, {"label": "Arrived"}, {"label": "Left", "closed": true}],
   "fields": [{"label": "Visitor name", "kind": "text", "required": true}, {"label": "Vehicle", "kind": "choice", "options": ["Car", "Bike"]}],
   "people": ["Host resident", "Guard on duty"], "read_by_roles": []}
  {"op": "add_field", "record_type": "visitor", "field": {"label": "...", "kind": "text", "required": false, "options": []}}
  {"op": "add_status", "record_type": "visitor", "status": {"label": "...", "closed": false}}

Field kinds: %s. Use "choice" with at least two options for a fixed list. Keep it small: only the fields a person must give,
at most %d. Never use a field called Number, Status or Created: records already have them. People are the kinds of people on a
record besides the one who created it. If a kind of record already exists (listed below), add to it instead of making another.
Statuses are in order; mark the last "closed". Labels are short plain words a resident understands.
"""


def _world_text(w: World) -> str:
    lines = []
    for k, t in w.types.items():
        fields = ", ".join(
            f"{f['label']} ({f['kind']})"
            for f in w.fields.get(k, {}).values()
            if f.get("is_active", True)
        )
        lines.append(
            f"- {k}: {t['plural']}; fields: {fields or 'none yet'}"
            + ("; system record, statuses fixed" if t["is_system"] else "")
        )
    return "\n".join(lines) or "- nothing yet"


def _json(text: str) -> dict:
    text = (text or "").strip()
    if "```" in text or not text.startswith("{"):
        text = text[text.find("{") : text.rfind("}") + 1]
    return json.loads(text)


async def draft(messages: list[dict], world: World) -> dict:
    """{"reply": str, "questions": [str], "ops": [..] | None}. Never raises."""
    sys_prompt = (
        _SYSTEM % (", ".join(KINDS), MAX_FIELDS)
        + "\nWhat exists now:\n"
        + _world_text(world)
    )
    convo = [{"role": "system", "content": sys_prompt}] + [
        {"role": m["role"], "content": str(m["content"])[:4000]}
        for m in messages[-12:]
        if m.get("role") in ("user", "assistant")
    ]
    try:
        resp = await _llm_chat(messages=convo, max_tokens=2500, temperature=0.2)
        data = _json(resp.choices[0].message.content)
    except Exception as e:
        logger.warning(f"schema draft failed: {e!r}")
        return {
            "reply": "I could not draft that just now. You can make the change by hand with “New kind of record”.",
            "questions": [],
            "ops": None,
        }
    if isinstance(data.get("questions"), list) and data["questions"]:
        qs = [str(q)[:200] for q in data["questions"][:3]]
        return {
            "reply": "A few questions so I do not guess.",
            "questions": qs,
            "ops": None,
        }
    try:
        ops = _OPS.validate_python(data.get("ops") or [])
    except ValidationError as e:
        logger.info(f"schema draft invalid: {e.error_count()} problems")
        return {
            "reply": "I drafted something the editor cannot accept. Say it again in other words, or make it by hand.",
            "questions": [],
            "ops": None,
        }
    if not ops:
        return {
            "reply": "I could not find a change in that. Say what should be kept, for example “visitors, with the guest’s name and who they visit”.",
            "questions": [],
            "ops": None,
        }
    return {
        "reply": str(
            data.get("intro")
            or "Here is a draft. Check it, change anything, then check and apply."
        )[:500],
        "questions": [],
        "ops": [o.model_dump() for o in ops],
    }
