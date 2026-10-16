"""The chat bot's name for each organisation (for example "GM AI" for Godrej, "Jack" for Baanganga), set in the dashboard
(Settings > Chat bot name) and kept in orgs.settings.bot_name. Without one it is "OrchestrAI".

It is what the bot calls itself: the AI is told its name, and the standard texts that name the product ("Welcome to
OrchestrAI!") say this name instead. The WhatsApp number's own profile name is Meta's and is not changed here."""

import json
import re
import time

from app.db import fetch_one
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

DEFAULT = "OrchestrAI"
MAX = 30
_CACHE_SECONDS = 60
_cache: dict[str, tuple[float, str]] = {}


def invalidate() -> None:
    _cache.clear()


def clean(text) -> str:
    return " ".join(str(text or "").split())[:MAX]


async def of(source_key: str | None) -> str:
    """This organisation's chat bot name, or OrchestrAI. Never raises."""
    if not source_key:
        return DEFAULT
    hit = _cache.get(source_key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    name = DEFAULT
    try:
        row = await fetch_one(
            "SELECT settings FROM orgs WHERE is_active = true ORDER BY created_at LIMIT 1",
            source_key=source_key,
        )
        settings = row["settings"] if row else {}
        settings = (
            json.loads(settings) if isinstance(settings, str) else (settings or {})
        )
        name = clean(settings.get("bot_name")) or DEFAULT
    except Exception as e:
        logger.debug(f"bot name: using {DEFAULT} ({e})")
    _cache[source_key] = (time.monotonic(), name)
    return name


def named(text: str, name: str) -> str:
    """A standard text that names the product, with the organisation's own name for the bot instead."""
    if not text or not name or name == DEFAULT:
        return text
    return text.replace(DEFAULT, name)


# How the bot introduced itself before it had a name. Old chats are full of it and the AI copies it from them.
_OLD_INTRO = re.compile(r"your (?:business )?ERP assistant(?= for)", re.IGNORECASE)


def fix_intro(text: str, name: str) -> str:
    """An AI reply with the old "I'm your ERP assistant for X" introduction, saying the bot's name instead."""
    if not text:
        return text
    return _OLD_INTRO.sub(f"*{name}*, the chat bot", text).replace(
        "the chat bot for", "the chat bot of"
    )
