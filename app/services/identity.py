from app.db import fetch_one


async def resolve_identity(phone: str) -> dict | None:
    """
    Phone number → user record with org, role, permissions, email.
    Returns None if phone not registered.
    """
    row = await fetch_one("""
        SELECT
            u.id          AS user_id,
            u.name        AS user_name,
            u.email       AS email,
            u.phone       AS phone,
            u.is_active   AS is_active,
            r.name        AS role,
            r.permissions AS permissions,
            o.id          AS org_id,
            o.name        AS org_name,
            o.slug        AS org_slug,
            o.is_active   AS org_active
        FROM users u
        JOIN roles r ON r.id = u.role_id
        JOIN orgs  o ON o.id = u.org_id
        WHERE u.phone = $1
    """, phone)

    if not row:
        return None

    return {
        "user_id":    str(row["user_id"]),
        "user_name":  row["user_name"],
        "email":      row["email"],
        "phone":      row["phone"],
        "is_active":  row["is_active"],
        "role":       row["role"],
        "permissions": list(row["permissions"]) if row["permissions"] else [],
        "org_id":     str(row["org_id"]),
        "org_name":   row["org_name"],
        "org_slug":   row["org_slug"],
        "org_active": row["org_active"],
    }


def check_permission(user: dict, intent: str) -> bool:
    """
    Returns True if the user's role has permission for this intent.
    Action intents (approve/reject/greet/menu) are always allowed.
    Unknown intent is always allowed (will be handled gracefully).
    """
    if intent.startswith("action:"):
        return True
    if intent == "unknown":
        return True
    return intent in user.get("permissions", [])
