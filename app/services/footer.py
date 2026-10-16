"""The footer note the chat bot adds under its WhatsApp messages.

Two levels, both changed on the dashboard (Settings > Footer note):
  * common       one text for every organisation, in the routing database (platform_settings 'footer', control-0002)
  * per client   orgs.settings.footer = {"mode": "common" | "own" | "off", "text": "...", "plain": true | false}
                 no setting = "common"

Where it shows: a message with buttons or a list gets WhatsApp's own footer line (small grey text, 60 characters at most).
A plain text message has no such line in WhatsApp, so the note is added as an italic last line, only when "plain" is on.
Templates are not touched (their footer is part of the template Meta approved). Nothing here ever stops a message: when
anything is missing or fails, the message simply goes without a footer."""

import time

from app.db import fetch_one, get_source_key_for_channel, routing_pool
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

MAX = 60  # WhatsApp's limit for a footer
MODES = ("common", "own", "off")
_CACHE_SECONDS = 60
_cache: dict[str, tuple[float, object]] = {}


def invalidate() -> None:
    _cache.clear()


def clean(text) -> str:
    return " ".join(str(text or "").split())[:MAX]


async def common() -> dict:
    """The common footer: {"text", "plain"}; empty text when none is set (or no table yet)."""
    hit = _cache.get("common")
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    found = {"text": "", "plain": False, "available": False}
    try:
        row = await routing_pool().fetchrow(
            "SELECT value FROM platform_settings WHERE key = 'footer'"
        )
        import json

        value = row["value"] if row else {}
        value = json.loads(value) if isinstance(value, str) else (value or {})
        found = {
            "text": clean(value.get("text")),
            "plain": value.get("plain") is True,
            "available": True,
        }
    except Exception as e:  # no control-0002 yet
        logger.debug(f"footer: no common footer ({e})")
    _cache["common"] = (time.monotonic(), found)
    return found


def effective(org_footer: dict | None, common_footer: dict) -> dict | None:
    """What actually goes out for one organisation: {"text", "plain"} or None."""
    mine = org_footer if isinstance(org_footer, dict) else {}
    mode = mine.get("mode") if mine.get("mode") in MODES else "common"
    if mode == "off":
        return None
    if mode == "own":
        text = clean(mine.get("text"))
        return {"text": text, "plain": mine.get("plain") is True} if text else None
    text = clean(common_footer.get("text"))
    return {"text": text, "plain": common_footer.get("plain") is True} if text else None


async def for_whatsapp() -> dict | None:
    """The footer of the organisation that owns the WhatsApp number. Never raises."""
    hit = _cache.get("whatsapp")
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    result = None
    try:
        import json

        source_key = await get_source_key_for_channel("whatsapp")
        row = await fetch_one(
            "SELECT settings FROM orgs WHERE is_active = true ORDER BY created_at LIMIT 1",
            source_key=source_key,
        )
        settings = row["settings"] if row else {}
        settings = (
            json.loads(settings) if isinstance(settings, str) else (settings or {})
        )
        result = effective(settings.get("footer"), await common())
    except Exception as e:
        logger.debug(f"footer: none for WhatsApp ({e})")
    _cache["whatsapp"] = (time.monotonic(), result)
    return result


def with_plain_line(message: str, foot: dict | None) -> str:
    """A plain message with the note as its italic last line (only when the footer says so)."""
    if not foot or not foot.get("plain") or not message:
        return message
    line = f"_{foot['text']}_"
    if message.rstrip().endswith(line):
        return message
    return f"{message.rstrip()}\n\n{line}"[:4096]
