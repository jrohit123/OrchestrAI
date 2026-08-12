from app.db import fetch_one, get_all_source_keys


async def resolve_identity(phone: str) -> dict | None:
    """
    Phone number → user record with org, role, permissions, email.
    Returns None if phone not registered.
    Loops through all data sources to find the user.
    """
    source_keys = await get_all_source_keys()
    
    for source_key in source_keys:
        try:
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
                    r.readable_tables AS readable_tables,
                    o.id          AS org_id,
                    o.name        AS org_name,
                    o.slug        AS org_slug,
                    o.is_active   AS org_active,
                    o.context_message_limit AS context_message_limit,
                    o.settings    AS org_settings
                FROM users u
                JOIN roles r ON r.id = u.role_id
                JOIN orgs  o ON o.id = u.org_id
                WHERE u.phone = $1
            """, phone, source_key=source_key)
            
            if row:
                return {
                    "user_id":    str(row["user_id"]),
                    "user_name":  row["user_name"],
                    "email":      row["email"],
                    "phone":      row["phone"],
                    "is_active":  row["is_active"],
                    "role_id":    str(row["role_id"]),
                    "role":       row["role"],
                    "permissions": list(row["permissions"]) if row["permissions"] else [],
                    "readable_tables": list(row["readable_tables"]) if row["readable_tables"] else [],
                    "org_id":     str(row["org_id"]),
                    "org_name":   row["org_name"],
                    "org_slug":   row["org_slug"],
                    "org_active": row["org_active"],
                    "context_message_limit": row.get("context_message_limit", 12),
                    "org_settings": row.get("org_settings", {}),
                    "source_key": source_key,
                }
        except Exception:
            # Source key may not have the users table or connection failed, try next
            continue

    return None


def check_permission(user: dict, intent: str) -> bool:
    """
    Returns True if the user's role has permission for this intent.
    Authorization defaults to deny - fail closed.
    """
    # Action intents (approve/reject) are NOT always allowed - check permissions
    if intent.startswith("action:"):
        return intent in user.get("permissions", [])
    # Unknown intent is NOT allowed - fail closed
    if intent == "unknown":
        return False
    if intent in ("general_read", "identity"):
        return "general_read" in user.get("permissions", [])
    return intent in user.get("permissions", [])


# ROLE_READ_ACCESS removed - now data-driven via roles.readable_tables column

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
