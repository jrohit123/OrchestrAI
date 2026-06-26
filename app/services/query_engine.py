"""
Dynamic SQL Query Engine — delegates to read agent and legacy templates.
"""
from app.services.read_agent import handle_read
from app.services.query_engine_legacy import execute_template


async def execute_read_query(
    org_id: str,
    role: str,
    raw_text: str,
    intent: str,
    parameters: dict | None = None,
) -> str:
    user = {"org_id": org_id, "role": role, "user_name": "", "org_name": "", "permissions": []}
    result = await handle_read(user, raw_text, intent, parameters)
    return result["message"]


async def execute_read(
    org_id: str,
    intent: str,
    parameters: dict,
    response_format: str = "generic",
    raw_text: str = "",
    role: str = "owner",
) -> str:
    return await execute_read_query(org_id, role, raw_text or intent, intent, parameters)
