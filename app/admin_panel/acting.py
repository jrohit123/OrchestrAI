"""Acting as a person of the organisation: what the flow engine needs to know about whoever runs a
flow, found by id or by email."""

from app.admin_panel.common import Ctx
from app.db import fetch_one
from app.services.party_access import add_party_permissions

_WHO = (
    "SELECT u.id, u.name, u.email, u.phone, u.is_active, u.role_id, r.name AS role, "
    "r.permissions, r.readable_tables, r.readable_entity_types, o.name AS org_name "
    "FROM users u JOIN roles r ON r.id = u.role_id JOIN orgs o ON o.id = u.org_id "
)


async def chat_user(
    ctx: Ctx,
    *,
    user_id=None,
    email: str | None = None,
    party: bool = True,
) -> dict | None:
    """The engine's description of a person of this organisation, or None when nobody matches
    (or the person has no role). `party` adds the flows the person gets from being on a case;
    a dashboard action leaves it out, because a signed-in admin acts as an admin, not as
    somebody on one particular case."""
    if user_id is not None:
        row = await fetch_one(
            _WHO + "WHERE u.id = $1 AND u.org_id = $2",
            user_id,
            ctx.org_id,
            source_key=ctx.source_key,
        )
    else:
        row = await fetch_one(
            _WHO + "WHERE lower(u.email) = $1 AND u.org_id = $2 AND u.is_active "
            "ORDER BY u.created_at LIMIT 1",
            (email or "").strip().lower(),
            ctx.org_id,
            source_key=ctx.source_key,
        )
    if row is None:
        return None
    user = {
        "user_id": str(row["id"]),
        "user_name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "is_active": row["is_active"],
        "role_id": str(row["role_id"]),
        "role": row["role"],
        "permissions": list(row["permissions"] or []),
        "readable_tables": list(row["readable_tables"] or []),
        "readable_entity_types": list(row["readable_entity_types"] or []),
        "org_id": str(ctx.org_id),
        "org_name": row["org_name"],
        "source_key": ctx.source_key,
    }
    return await add_party_permissions(user) if party else user
