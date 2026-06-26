from app.db import fetch_one


async def resolve_identity(phone: str) -> dict | None:
    row = await fetch_one("""
        SELECT
            u.id AS user_id, u.name AS user_name, u.email, u.phone,
            u.is_active, r.name AS role, r.permissions,
            o.id AS org_id, o.name AS org_name, o.slug AS org_slug, o.is_active AS org_active
        FROM users u
        JOIN roles r ON r.id = u.role_id
        JOIN orgs o ON o.id = u.org_id
        WHERE u.phone = $1
    """, phone)

    if not row:
        return None

    return {
        "user_id":     str(row["user_id"]),
        "user_name":   row["user_name"],
        "email":       row["email"],
        "phone":       row["phone"],
        "is_active":   row["is_active"],
        "role":        row["role"],
        "permissions": list(row["permissions"]) if row["permissions"] else [],
        "org_id":      str(row["org_id"]),
        "org_name":    row["org_name"],
        "org_slug":    row["org_slug"],
        "org_active":  row["org_active"],
    }


def check_permission(user: dict, intent: str) -> bool:
    if intent.startswith("action:"):
        return True
    if intent == "unknown":
        return True
    if intent in ("general_read", "identity"):
        return "general_read" in user.get("permissions", [])
    return intent in user.get("permissions", [])


def check_route_permission(user: dict, analysis: dict) -> tuple[bool, str]:
    route = analysis.get("route_type")
    role = user.get("role", "")

    if route in ("clarify", "identity", "capabilities"):
        return True, ""

    if route == "general_read":
        if "general_read" in user.get("permissions", []) or role == "owner":
            return True, ""
        return False, "general_read"

    if route == "workflow":
        wk = analysis.get("workflow_key")
        if not wk:
            return False, "unknown workflow"
        if wk not in user.get("permissions", []):
            return False, wk
        return True, ""

    if route == "system":
        return check_permission(user, analysis.get("intent", "")), analysis.get("intent", "")

    return False, "unknown route"
