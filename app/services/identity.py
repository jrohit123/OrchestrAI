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
            u.role_id     AS role_id,
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
        "role_id":    str(row["role_id"]),
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
    if intent in ("general_read", "identity"):
        return "general_read" in user.get("permissions", [])
    return intent in user.get("permissions", [])


# Tables allowed per role for general_read (extend as needed)
ROLE_READ_ACCESS = {
    "owner":      {"customers", "invoices", "inventory", "orders", "quotations"},
    "accountant": {"customers", "invoices", "inventory", "orders", "quotations"},
    "sales":      {"customers", "inventory", "orders", "quotations"},
    "warehouse":  {"inventory"},
}

WORKFLOW_ACTIONS = {
    "create_invoice":       "Create",
    "create_quotation":     "Create",
    "create_order":         "Create",
    "send_invoice_pdf":     "Execute",
    "send_dues_statement":  "Execute",
    "set_metal_rate":       "Update",
    "update_order_status":  "Update",
}


def check_route_permission(user: dict, analysis: dict) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    analysis = output from Intent Analyzer
    """
    route = analysis.get("route_type")
    role = user.get("role", "")

    if route == "clarify":
        return True, ""

    if route == "identity":
        # Identity queries (who am I, my permissions) always allowed for authenticated users
        return True, ""

    if route == "general_read":
        if "general_read" in user.get("permissions", []):
            return True, ""
        # Fallback: owner always allowed
        if role == "owner":
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
