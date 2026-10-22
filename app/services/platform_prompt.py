"""What every AI job of the platform is told first (app/prompts/platform.txt), filled in for one organisation.

The facts come from the organisation's own data, never from a list kept in code:
    channel       how its people reach the chat bot: the default of the users table's channel column
    currency      orgs.settings -> locale.currency          (default "Rs.")
    number style  orgs.settings -> locale.number_style      ("indian" = 1,45,000, the default; "international" = 145,000)
    time zone     the orgs row's timezone                   (default config_store.DEFAULT_TIMEZONE)
    bot name      orgs.settings -> bot_name                 (see bot_name.py)

Prompt texts use these as {channel}, {currency}, {number_style}, {money_example}, {timezone}, {org_name} and
{bot_name}. apply() swaps only those names, so a text full of JSON braces is never touched otherwise."""

import re
import time

from app.db import fetch_one
from app.logging_config import get_context_logger
from app.services import config_store
from app.services.prompt_loader import PROMPTS_DIR, _read

logger = get_context_logger(__name__)

PLATFORM = _read(PROMPTS_DIR / "platform.txt") or ""
NAMES = (
    "channel",
    "currency",
    "number_style",
    "money_example",
    "timezone",
    "org_name",
    "bot_name",
)
_STYLES = {
    "indian": (
        "Indian grouping (from the right: 3 digits, then groups of 2)",
        "1,45,000",
    ),
    "international": ("groups of 3 digits", "145,000"),
}
_cache: dict[str, tuple[float, dict]] = {}
_TTL = 60


def defaults() -> dict:
    """The facts when nothing is known about the organisation."""
    label, sample = _STYLES["indian"]
    return {
        "channel": "WhatsApp or Telegram",
        "currency": "Rs.",
        "number_style": label,
        "money_example": "Rs." + sample,
        "timezone": config_store.DEFAULT_TIMEZONE,
        "org_name": "the organisation",
        "bot_name": "the chat bot",
    }


async def facts(source_key: str | None) -> dict:
    """The organisation's facts for the prompts. Never raises: anything unreadable keeps its default."""
    out = defaults()
    if not source_key:
        return out
    hit = _cache.get(source_key)
    if hit and hit[0] > time.monotonic():
        return dict(hit[1])
    try:
        org = await fetch_one(
            "SELECT id, name, settings, to_jsonb(o)->>'timezone' AS tz FROM orgs o WHERE is_active LIMIT 1",
            source_key=source_key,
        )
        col = await fetch_one(
            "SELECT column_default FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = 'users' AND column_name = 'channel'",
            source_key=source_key,
        )
        if org:
            settings = await config_store.org_settings(source_key, org["id"])
            out["org_name"] = org["name"] or out["org_name"]
            out["timezone"] = org["tz"] or out["timezone"]
            currency = str(
                config_store.setting(settings, "locale.currency", "") or ""
            ).strip()
            if currency:
                out["currency"] = currency
            style = str(
                config_store.setting(settings, "locale.number_style", "indian")
                or "indian"
            ).lower()
            label, sample = _STYLES.get(style, _STYLES["indian"])
            out["number_style"] = label
            out["money_example"] = out["currency"] + sample
        found = re.match(r"'([^']*)'", (col["column_default"] if col else "") or "")
        if found:
            out["channel"] = found.group(1).capitalize()
        from app.services import bot_name

        out["bot_name"] = await bot_name.of(source_key)
    except Exception as e:  # a prompt must never fail because a fact could not be read
        logger.warning(f"platform facts not read for {source_key}: {e!r}")
    _cache[source_key] = (time.monotonic() + _TTL, dict(out))
    return out


def apply(text: str, values: dict) -> str:
    """The text with {channel}, {currency}... filled in. Every other brace stays as it is."""
    for name in NAMES:
        if name in values:
            text = text.replace("{" + name + "}", str(values[name]))
    return text


async def preamble(source_key: str | None) -> str:
    """platform.txt filled in for this organisation: the first thing every AI job reads."""
    return apply(PLATFORM, await facts(source_key)).strip()


async def fill_for(source_key: str | None, text: str) -> str:
    """Any prompt text with this organisation's facts filled in."""
    return apply(text, await facts(source_key))
