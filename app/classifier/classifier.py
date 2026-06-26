"""
Classifier — only deterministic handling for WhatsApp interactive button payloads.
All natural-language messages go to the LLM message router.
"""

# WhatsApp approval buttons and OTP retry — fixed IDs from Meta, not NLU
INTERACTIVE_MAP = {
    "1":                "action:approve",
    "2":                "action:reject",
    "action:approve":   "action:approve",
    "action:reject":    "action:reject",
    "retry":            "action:retry_otp",
}


def _interactive_intent(text: str) -> str | None:
    return INTERACTIVE_MAP.get(text.strip().lower())


async def classify_message(
    text: str,
    org_name: str = "your organisation",
    org_id: str = None,
    user_role: str = "owner",
) -> dict:
    interactive = _interactive_intent(text)
    if interactive:
        return {
            "intent": interactive,
            "tier": 1,
            "confidence": 1.0,
            "route_type": "system",
            "entity_raw": None,
        }

    if not org_id:
        return {
            "route_type": "unknown",
            "tier": 3,
            "intent": "unknown",
            "entity_raw": None,
            "confidence": 0.0,
        }

    from app.services.message_router import route_message
    return await route_message(text, org_id, org_name, user_role)


def invalidate_patterns_cache(org_id: str = None):
    from app.services.message_router import invalidate_router_cache
    invalidate_router_cache(org_id)
