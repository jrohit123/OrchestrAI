"""
onboarding_llm.py — LLM fallback for the Telegram self-registration/linking
flow, used ONLY when onboarding_parsing.py's regex pass can't confidently
parse a reply (free-text role answers, conversational edits at the confirm
step). Routed through llm_router's standard provider fallback ladder, same
as every other LLM call in this codebase.

Neither of these ever decides anything security-relevant — they only turn
messy free text into a candidate field value, which the caller still runs
through the same deterministic validation/lookup as a regex-parsed answer
would get. On any failure or low-confidence result, both return "no match"
rather than guessing.
"""
import json
from app.logging_config import get_context_logger
from app.services.llm_router import chat_completion as _llm_chat
from app.services.prompt_loader import PROMPTS_DIR, _read

logger = get_context_logger(__name__)

_ROLE_MATCH_PROMPT    = _read(PROMPTS_DIR / "role_match.txt")
_CONFIRM_INTENT_PROMPT = _read(PROMPTS_DIR / "confirm_intent.txt")


def _extract_json(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        text = text[text.find("{"):text.rfind("}") + 1]
    return json.loads(text)


async def llm_match_role(text: str, options: list[dict]) -> dict | None:
    """Maps a free-text answer to one of `options` ({"id","name"} dicts).
    Returns None if the model isn't confident or the call fails — the
    caller then re-shows the role list rather than guessing."""
    if not _ROLE_MATCH_PROMPT:
        return None
    role_names = ", ".join(o["name"] for o in options)
    prompt = _ROLE_MATCH_PROMPT.format(role_names=role_names, text=text)
    try:
        response = await _llm_chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,
        )
        result = _extract_json(response.choices[0].message.content)
        picked_name = (result.get("role_name") or "").strip().lower()
    except Exception as e:
        logger.warning(f"Role-match LLM call failed: {e}")
        return None

    if not picked_name:
        return None
    # Only ever trust the model's answer if it names an option that
    # actually exists — never act on a hallucinated role name.
    return next((o for o in options if o["name"].lower() == picked_name), None)


async def llm_parse_confirm_intent(text: str, name: str, email: str, role_name: str) -> dict:
    """Classifies a reply on the registration confirm screen.
    Returns {"action": "confirm"|"cancel"|"edit"|"unclear",
             "field": "name"|"email"|"role"|None, "value": str|None}.
    Falls back to "unclear" (never guesses confirm/cancel) on any failure."""
    unclear = {"action": "unclear", "field": None, "value": None}
    if not _CONFIRM_INTENT_PROMPT:
        return unclear
    prompt = _CONFIRM_INTENT_PROMPT.format(text=text, name=name, email=email, role=role_name)
    try:
        response = await _llm_chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0,
        )
        result = _extract_json(response.choices[0].message.content)
    except Exception as e:
        logger.warning(f"Confirm-intent LLM call failed: {e}")
        return unclear

    action = result.get("action")
    if action not in ("confirm", "cancel", "edit", "unclear"):
        return unclear
    field = result.get("field")
    if field not in ("name", "email", "role"):
        field = None
    value = result.get("value")
    if action == "edit" and (not field or not value):
        return unclear
    return {"action": action, "field": field, "value": value}
