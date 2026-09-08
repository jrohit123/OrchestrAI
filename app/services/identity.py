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


async def find_unlinked_user_by_email(email: str) -> dict | None:
    """Find a user row with this email that has no chat_id bound yet."""
    source_keys = await get_all_source_keys()
    for source_key in source_keys:
        try:
            row = await fetch_one("""
                SELECT u.id AS user_id, u.name AS user_name, u.email,
                       o.id AS org_id, o.name AS org_name
                FROM users u JOIN orgs o ON o.id = u.org_id
                WHERE LOWER(u.email) = LOWER($1) AND (u.phone IS NULL OR u.phone = '')
            """, email, source_key=source_key)
            if row:
                # Convert UUID to string for JSON serialization
                return {
                    "user_id": str(row["user_id"]),
                    "user_name": row["user_name"],
                    "email": row["email"],
                    "org_id": str(row["org_id"]),
                    "org_name": row["org_name"],
                    "source_key": source_key
                }
        except Exception:
            continue
    return None


async def bind_telegram_phone(user_id: str, chat_id: str, source_key: str) -> dict | None:
    """Bind chat_id to a user — call ONLY after OTP verification succeeds."""
    from app.db import execute
    tg_phone = f"tg:{chat_id}"
    row = await fetch_one("""
        UPDATE users SET phone = $1
        WHERE id = $2 AND (phone IS NULL OR phone = '')
        RETURNING id
    """, tg_phone, user_id, source_key=source_key)
    if row:
        return await resolve_identity(tg_phone)
    return None
