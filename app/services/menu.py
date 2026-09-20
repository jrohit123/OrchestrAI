import hashlib
import json
import re

from app.db import fetch_all
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

SECTION_LABELS = {"reports": "📊 Reports", "create": "✍️ Create", "other": "⚙️ More"}
SECTION_ORDER = ["reports", "create", "other"]

# Telegram BotCommand.command: lowercase letters, digits, underscores only, 1-32 chars.
# One bad entry fails the WHOLE setMyCommands call, so invalid ones are dropped up front.
_VALID_TG_COMMAND = re.compile(r"^[a-z0-9_]{1,32}$")


async def get_menu_workflows(org_id: str, user: dict) -> list[dict]:
    rows = await fetch_all(
        """
        SELECT intent_key, name, command_description, menu_section, slash_command, workflow_type
        FROM workflows
        WHERE org_id = $1 AND is_active = true
        ORDER BY menu_section, name
    """,
        org_id,
        source_key=user["source_key"],
    )
    perms = set(user.get("permissions", []))
    return [dict(r) for r in rows if r["intent_key"] in perms]


async def build_menu_sections(org_id: str, user: dict) -> list[dict]:
    allowed = await get_menu_workflows(org_id, user)
    grouped: dict[str, list] = {}
    for r in allowed:
        grouped.setdefault(r["menu_section"] or "other", []).append(
            {
                "id": r["intent_key"],
                "title": r["name"][:24],
                "description": (r["command_description"] or "")[:72],
            }
        )
    sections = [
        {"title": SECTION_LABELS.get(k, k.title()), "rows": grouped[k]}
        for k in SECTION_ORDER
        if k in grouped
    ]
    # My Status / Cancel / Help used to be appended here as a fixed
    # non-DB "⚙️ More" section — always shown regardless of what's actually
    # configured for this org. Removed so the menu only ever lists what's
    # really in the workflows table; those three stay reachable exactly as
    # they were before (typing "status"/"cancel"/"help", or the sys:* row
    # id if a client still sends one — see handle_system_row in webhook.py),
    # just no longer force-listed as if they were workflows.
    # WhatsApp hard limit: 10 rows total across all sections.
    total = sum(len(s["rows"]) for s in sections)
    if total > 10:
        overflow = total - 10
        for s in reversed(sections):
            if overflow <= 0:
                break
            cut = min(overflow, len(s["rows"]))
            s["rows"] = s["rows"][: len(s["rows"]) - cut]
            overflow -= cut
        sections = [s for s in sections if s["rows"]]
    return sections


async def get_telegram_commands(org_id: str, user: dict) -> list[dict]:
    """Workflow slash commands + the fixed built-ins, shaped for Telegram's
    setMyCommands (the native '/' popup), in the same permission-filtered
    set the WhatsApp menu already uses."""
    workflows = await get_menu_workflows(org_id, user)
    commands = []
    seen = set()
    for w in workflows:
        cmd = (w["slash_command"] or "").strip().lower()
        if not cmd or cmd in seen or not _VALID_TG_COMMAND.match(cmd):
            continue
        seen.add(cmd)
        desc = (w["command_description"] or w["name"] or "").strip()[:256]
        commands.append({"command": cmd, "description": desc or w["name"][:256]})
    for cmd, desc in (
        ("status", "See your recent submissions"),
        ("cancel", "Clear the current draft"),
        ("help", "Show available commands"),
    ):
        if cmd not in seen:
            commands.append({"command": cmd, "description": desc})
    return commands[:100]  # Telegram hard limit


async def sync_telegram_commands(user: dict, chat_id: str) -> None:
    """Push this chat's '/' command menu to Telegram if it's changed since
    last time. Safe to call on every inbound message — a Redis fingerprint
    check makes the common case (nothing changed) a single Redis GET with
    no Telegram API call.

    The whole body is one try/except (not just the API call) — a prior
    version only wrapped the Telegram call and an upstream failure vanished
    with no log line and no crash, which made a real bug indistinguishable
    from "nothing to do"."""
    logger.info(f"sync_telegram_commands: called for chat {chat_id}")
    try:
        from app.redis_client import get_redis
        from app.services import telegram

        commands = await get_telegram_commands(user["org_id"], user)
        fingerprint = hashlib.sha256(
            json.dumps(commands, sort_keys=True).encode()
        ).hexdigest()

        redis = get_redis()
        cache_key = f"tg_cmds:{user['org_id']}:{chat_id}"
        cached = await redis.get(cache_key) if redis else None
        if cached == fingerprint:
            logger.info(f"sync_telegram_commands: already in sync for chat {chat_id}")
            return

        await telegram.set_commands(chat_id, commands)
        logger.info(
            f"sync_telegram_commands: synced {len(commands)} commands for "
            f"chat {chat_id}: {[c['command'] for c in commands]}"
        )
        if redis:
            await redis.setex(cache_key, 30 * 24 * 3600, fingerprint)
    except Exception:
        logger.warning(
            f"sync_telegram_commands: failed for chat {chat_id}", exc_info=True
        )


async def resolve_slash_command(org_id: str, user: dict, cmd: str) -> dict | None:
    """'/quo' → the quotation workflow. Exact match first, then unique prefix."""
    cmd = cmd.lstrip("/").lower().split()[0] if cmd.strip("/") else ""
    if not cmd:
        return None
    allowed = await get_menu_workflows(org_id, user)
    exact = [w for w in allowed if w["slash_command"] == cmd]
    if exact:
        return exact[0]
    prefix = [w for w in allowed if (w["slash_command"] or "").startswith(cmd)]
    return prefix[0] if len(prefix) == 1 else None
