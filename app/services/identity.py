import asyncpg

from app.db import fetch_one, get_all_source_keys
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

# A failure here means we couldn't check this source at all (network/DB down),
# as opposed to the query running fine and simply finding no match. Those two
# cases must not be conflated — see the `unreachable` handling below.
_CONNECTION_ERRORS = (OSError, TimeoutError, asyncpg.exceptions.PostgresConnectionError)


async def resolve_identity(phone: str) -> dict | None:
    """
    Phone number → user record with org, role, permissions, email.
    Returns None only once every data source has actually been checked and
    none matched. If a source couldn't be reached, raises instead of
    returning None — a connection failure must never be reported to the
    user as "not registered".
    """
    source_keys = await get_all_source_keys()
    unreachable: list[str] = []

    for source_key in source_keys:
        try:
            row = await fetch_one(
                """
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
                    r.readable_entity_types AS readable_entity_types,
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
            """,
                phone,
                source_key=source_key,
            )

            if row:
                return {
                    "user_id": str(row["user_id"]),
                    "user_name": row["user_name"],
                    "email": row["email"],
                    "phone": row["phone"],
                    "is_active": row["is_active"],
                    "role_id": str(row["role_id"]),
                    "role": row["role"],
                    "permissions": list(row["permissions"])
                    if row["permissions"]
                    else [],
                    "readable_tables": list(row["readable_tables"])
                    if row["readable_tables"]
                    else [],
                    "readable_entity_types": list(row["readable_entity_types"])
                    if row["readable_entity_types"]
                    else [],
                    "org_id": str(row["org_id"]),
                    "org_name": row["org_name"],
                    "org_slug": row["org_slug"],
                    "org_active": row["org_active"],
                    "context_message_limit": row.get("context_message_limit", 12),
                    "org_settings": row.get("org_settings", {}),
                    "source_key": source_key,
                }
        except _CONNECTION_ERRORS as e:
            logger.warning(
                f"resolve_identity: source_key={source_key} unreachable, cannot confirm registration: {e}"
            )
            unreachable.append(source_key)
            continue
        except Exception as e:
            # Source key may not have the users table — genuinely doesn't apply, try next
            logger.debug(
                f"resolve_identity: source_key={source_key} lookup failed, trying next: {e}"
            )
            continue

    if unreachable:
        raise RuntimeError(
            f"resolve_identity: could not verify '{phone}' — unreachable source(s): {unreachable}"
        )

    return None


async def find_unlinked_user_by_email(email: str) -> dict | None:
    """Find a user row with this email that has no chat_id bound yet.
    Returns None only once every source has actually been checked; raises
    if a source was unreachable, for the same reason resolve_identity does."""
    source_keys = await get_all_source_keys()
    unreachable: list[str] = []
    for source_key in source_keys:
        try:
            row = await fetch_one(
                """
                SELECT u.id AS user_id, u.name AS user_name, u.email,
                       o.id AS org_id, o.name AS org_name
                FROM users u JOIN orgs o ON o.id = u.org_id
                WHERE LOWER(u.email) = LOWER($1) AND (u.phone IS NULL OR u.phone = '')
            """,
                email,
                source_key=source_key,
            )
            if row:
                # Convert UUID to string for JSON serialization
                return {
                    "user_id": str(row["user_id"]),
                    "user_name": row["user_name"],
                    "email": row["email"],
                    "org_id": str(row["org_id"]),
                    "org_name": row["org_name"],
                    "source_key": source_key,
                }
        except _CONNECTION_ERRORS as e:
            logger.warning(
                f"find_unlinked_user_by_email: source_key={source_key} unreachable: {e}"
            )
            unreachable.append(source_key)
            continue
        except Exception as e:
            logger.debug(
                f"find_unlinked_user_by_email: source_key={source_key} lookup failed, trying next: {e}"
            )
            continue

    if unreachable:
        raise RuntimeError(
            f"find_unlinked_user_by_email: could not verify '{email}' — unreachable source(s): {unreachable}"
        )

    return None


async def bind_telegram_phone(
    user_id: str, chat_id: str, source_key: str
) -> dict | None:
    """Bind chat_id to a user — call ONLY after OTP verification succeeds."""
    tg_phone = f"tg:{chat_id}"
    row = await fetch_one(
        """
        UPDATE users SET phone = $1
        WHERE id = $2 AND (phone IS NULL OR phone = '')
        RETURNING id
    """,
        tg_phone,
        user_id,
        source_key=source_key,
    )
    if row:
        return await resolve_identity(tg_phone)
    return None
