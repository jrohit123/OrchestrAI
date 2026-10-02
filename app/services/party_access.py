"""
party_access.py — workflows a person may use because they are on a case, not because of their role.

A workflow's settings can say who_can_use: ["assignee", "level2", "helper"]. A person who holds one of
those roles on any case is given that workflow (menu, slash command, permission) on top of what their
role allows. The step case.authorize then checks they are on the case they name, and case lookups only
find their own cases (see field_reader and resolve_entity's only_mine).

People whose role already allows the workflow are left alone: it covers every case for them.
On a database without the case tables or the settings column this gives nothing and never fails.
"""

import time

from app.db import fetch_all
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

_CACHE_SECONDS = 30
_cache: dict[str, tuple[float, dict]] = {}


async def party_workflows(user: dict) -> dict[str, list[str]]:
    """{intent_key: [roles]} for the active workflows that name who on a case may use them."""
    key = f"{user['source_key']}:{user['org_id']}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    rows = await fetch_all(
        "SELECT intent_key, to_jsonb(w) -> 'settings' -> 'who_can_use' AS roles "
        "FROM workflows w WHERE org_id = $1 AND is_active = true "
        "AND jsonb_typeof(to_jsonb(w) -> 'settings' -> 'who_can_use') = 'array'",
        user["org_id"],
        source_key=user["source_key"],
    )
    import json

    found: dict[str, list[str]] = {}
    for r in rows:
        roles = r["roles"]
        roles = json.loads(roles) if isinstance(roles, str) else roles
        found[r["intent_key"]] = [x for x in roles if isinstance(x, str)]
    _cache[key] = (time.monotonic(), found)
    return found


async def add_party_permissions(user: dict) -> dict:
    """The person with the extra workflows they get from being on a case. Never raises."""
    try:
        wanted = await party_workflows(user)
        if not wanted:
            return user
        rows = await fetch_all(
            "SELECT DISTINCT party_role FROM case_parties "
            "WHERE org_id = $1 AND user_id = $2 AND ended_at IS NULL",
            user["org_id"],
            user["user_id"],
            source_key=user["source_key"],
        )
    except (
        Exception
    ) as e:  # no case tables here, or a hiccup: the person keeps their role's access
        logger.debug(f"party access not applied: {e}")
        return user
    held = {r["party_role"] for r in rows}
    permissions = set(user.get("permissions") or [])
    access: dict[str, list[str]] = {}
    for key, roles in wanted.items():
        if key in permissions:
            continue
        if held & set(roles):
            permissions.add(key)
            access[key] = roles
    if not access:
        return user
    return {**user, "permissions": sorted(permissions), "party_access": access}
