"""
Dynamic greeting — delegates to read agent (schema + live DB samples).
"""
from app.services.read_agent import handle_greet_or_capabilities


async def generate_greeting(user: dict, org_name: str, ttl_str: str = "") -> str:
    return await handle_greet_or_capabilities(user, ttl_str)


async def generate_help(user: dict, org_name: str) -> str:
    return await handle_greet_or_capabilities(user)
