"""The chat bot's own name per organisation (app/services/bot_name.py)."""

import asyncio

from app.admin_panel import access_rules, footer_settings
from app.services import bot_name, config_store, messages


def test_standard_texts_say_the_bots_own_name_and_default_to_orchestrai():
    assert (
        bot_name.named("👋 Welcome to OrchestrAI!", "GM AI") == "👋 Welcome to GM AI!"
    )
    assert (
        bot_name.named("👋 Welcome to OrchestrAI!", "OrchestrAI")
        == "👋 Welcome to OrchestrAI!"
    )
    assert (
        bot_name.clean("  GM    AI  ") == "GM AI"
        and len(bot_name.clean("x" * 99)) == bot_name.MAX
    )
    assert asyncio.run(bot_name.of(None)) == "OrchestrAI"


def test_say_uses_the_name_of_the_organisation(monkeypatch):
    async def message(source_key, key, default, **values):
        return default

    async def of(source_key):
        return "Jack" if source_key == "baanganga" else "OrchestrAI"

    monkeypatch.setattr(config_store, "message", message)
    monkeypatch.setattr(bot_name, "of", of)
    key = next(
        k
        for k, m in messages.MESSAGES.items()
        if "OrchestrAI" in m.text and not m.values
    )
    assert "Jack" in asyncio.run(
        messages.say("baanganga", key)
    ) and "OrchestrAI" not in asyncio.run(messages.say("baanganga", key))
    assert "OrchestrAI" in asyncio.run(messages.say("godrej", key))


def test_the_ai_is_told_its_name():
    from pathlib import Path

    text = (
        Path(messages.__file__).parents[1] / "prompts" / "agent_system_wrapper.txt"
    ).read_text(encoding="utf-8")
    assert text.startswith("You are {bot_name}, the chat bot of {org_name}.")


def test_only_super_admins_change_the_name():
    calls = {
        (m, r.path[len(access_rules.PREFIX) :])
        for r in footer_settings.router.routes
        for m in r.methods
    }
    assert (
        {("GET", "/bot-name"), ("PUT", "/bot-name")}
        <= calls
        <= access_rules.SUPER_CALLS
    )
