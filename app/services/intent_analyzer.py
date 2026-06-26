"""
Intent analyzer — delegates entirely to LLM message router.
"""
from app.services.message_router import route_message


async def analyze_intent(text: str, org_id: str, org_name: str, user_role: str) -> dict:
    return await route_message(text, org_id, org_name, user_role)
