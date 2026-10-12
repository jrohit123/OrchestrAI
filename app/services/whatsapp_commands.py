"""The "/" command list on the WhatsApp number, made from the workflows in the database.

WhatsApp shows a list of commands, with a one-line hint each, when a person types "/" in the chat with the number. Meta keeps
one list per number, the same for everyone, so it lists every workflow that has a slash command (and "/menu"); a person's role
is still checked when they use one. Nothing here names a workflow: a workflow added, renamed or switched off on the dashboard
changes the list by itself (the scheduler looks every few minutes and only calls Meta when the list really changed).

Switched on by orgs.settings -> whatsapp_commands = {"enabled": true}. Meta's limits are kept: up to 30 commands, names of up to
32 letters, digits and underscores, hints of up to 256 characters and no emoji. Whatever goes wrong, nothing is raised: the
list on the number simply stays as it was."""

import hashlib
import json
import re

from app.db import fetch_all, fetch_one
from app.logging_config import get_context_logger
from app.redis_client import get_redis
from app.services import config_store, whatsapp
from app.services.messages import say

logger = get_context_logger(__name__)

MAX_COMMANDS = 30
MAX_HINT = 256
NAME_OK = re.compile(r"^[a-z0-9_]{1,32}$")
EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿️‍]")
SIGNATURE_KEY = "wa_commands:signature"
FAILED_KEY = "wa_commands:failed"
SIGNATURE_DAYS = 30  # asked again now and then, in case the list was changed by hand in WhatsApp Manager
RETRY_AFTER_FAILURE_SECONDS = 3600


def _clean(text) -> str:
    text = " ".join(EMOJI.sub("", str(text or "")).split())
    return text[:MAX_HINT]


async def build(source_key: str, org_id) -> list[dict]:
    """The commands to show: "/menu" first, then each active workflow that has a slash command, in menu order."""
    commands = [
        {
            "command_name": "menu",
            "command_description": _clean(await say(source_key, "commands.menu_hint")),
        }
    ]
    try:
        rows = await fetch_all(
            "SELECT slash_command, name, command_description FROM workflows "
            "WHERE org_id = $1 AND is_active AND COALESCE(slash_command, '') <> '' "
            "AND COALESCE(kind, 'workflow') <> 'block' ORDER BY menu_section, name",
            org_id,
            source_key=source_key,
        )
    except Exception as e:  # an older database without the kind column
        logger.debug(
            f"whatsapp commands: reading workflows failed ({e}); trying without kind"
        )
        rows = await fetch_all(
            "SELECT slash_command, name, command_description FROM workflows "
            "WHERE org_id = $1 AND is_active AND COALESCE(slash_command, '') <> '' "
            "ORDER BY menu_section, name",
            org_id,
            source_key=source_key,
        )
    seen = {"menu"}
    for r in rows:
        name = str(r["slash_command"]).strip().lstrip("/").lower()
        if not NAME_OK.match(name) or name in seen:
            continue
        seen.add(name)
        hint = _clean(r["command_description"]) or _clean(r["name"]) or name
        commands.append({"command_name": name, "command_description": hint})
    return commands[:MAX_COMMANDS]


def signature(commands: list[dict]) -> str:
    return hashlib.sha256(json.dumps(commands, sort_keys=True).encode()).hexdigest()


async def sync(force: bool = False) -> str:
    """Bring the number's "/" list in line with the workflows. Returns what happened, in a few words. Never raises."""
    try:
        from app.db import get_source_key_for_channel

        try:
            source_key = await get_source_key_for_channel("whatsapp")
        except RuntimeError:
            return "no client owns the WhatsApp number"
        org = await fetch_one("SELECT id FROM orgs LIMIT 1", source_key=source_key)
        if not org:
            return "no organisation"
        settings = await config_store.org_settings(source_key, org["id"])
        if config_store.setting(settings, "whatsapp_commands.enabled") is not True:
            return "off"
        redis = get_redis()
        if redis is not None and await redis.get(FAILED_KEY):
            return "waiting after a failure"
        commands = await build(source_key, org["id"])
        sig = signature(commands)
        if not force and redis is not None and await redis.get(SIGNATURE_KEY) == sig:
            return "unchanged"
        current = await whatsapp.conversational_automation()
        await whatsapp.set_commands(commands, current)
        if redis is not None:
            await redis.set(SIGNATURE_KEY, sig, ex=SIGNATURE_DAYS * 86400)
        logger.info(f"whatsapp commands: {len(commands)} commands set on the number")
        return f"synced {len(commands)}"
    except Exception as e:
        logger.warning(
            f"whatsapp commands: could not update the list ({type(e).__name__}): {e}"
        )
        try:
            redis = get_redis()
            if redis is not None:
                await redis.set(FAILED_KEY, "1", ex=RETRY_AFTER_FAILURE_SECONDS)
        except Exception as e2:
            logger.debug(f"whatsapp commands: could not note the failure: {e2}")
        return f"failed: {type(e).__name__}"
