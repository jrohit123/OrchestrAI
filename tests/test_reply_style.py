"""How a report is worded when the AI words it (agent._llm_format_report): the reply style comes from the
client's database when it has one, else from the prompt file, and a saved text that cannot be filled in
never stops a reply."""

import asyncio
from types import SimpleNamespace

import pytest

from app.services import agent, config_store, platform_prompt, prompt_loader

WF = {"name": "Stock list", "business_glossary": {"sku": "item code"}}


@pytest.fixture
def chat(monkeypatch):
    """A pretend language model: it answers "worded" and keeps what it was asked."""
    asked = {}

    async def fake_chat(messages, **kwargs):
        asked["prompt"] = messages[0]["content"]
        reply = SimpleNamespace(
            message=SimpleNamespace(content="worded"), finish_reason="stop"
        )
        return SimpleNamespace(choices=[reply])

    monkeypatch.setattr(agent, "_llm_chat", fake_chat)
    return asked


def _style(monkeypatch, text, seen=None):
    async def prompt(source_key, key, default, *, pack=None):
        if seen is not None:
            seen.update(source_key=source_key, key=key, default=default, pack=pack)
        return text

    monkeypatch.setattr(config_store, "prompt", prompt)


def test_the_clients_reply_style_is_used_and_filled_in(monkeypatch, chat):
    seen = {}
    _style(monkeypatch, "STYLE {workflow_name} | {glossary_json} | {raw_data}", seen)
    out = asyncio.run(agent._llm_format_report(WF, "ROWS", "alpha"))
    assert out == "worded"
    assert chat["prompt"] == 'STYLE Stock list | {"sku": "item code"} | ROWS'
    assert seen["source_key"] == "alpha" and seen["key"] == "agent.reply_style"
    assert seen["default"] == prompt_loader.reply_style_built_in()


def test_without_a_saved_text_the_prompt_file_is_what_the_ai_is_told(monkeypatch, chat):
    async def nothing_saved(source_key, key, default, *, pack=None):
        return default

    monkeypatch.setattr(config_store, "prompt", nothing_saved)
    asyncio.run(agent._llm_format_report(WF, "ROWS", "alpha"))
    template = prompt_loader.reply_style_built_in()
    assert chat["prompt"] == template.format(
        **platform_prompt.defaults(),  # no database here: the platform facts keep their defaults
        workflow_name="Stock list",
        glossary_json='{"sku": "item code"}',
        raw_data="ROWS",
    )  # exactly what it was told before the reply style could be changed


def test_a_saved_text_that_cannot_be_filled_in_falls_back_to_the_prompt_file(
    monkeypatch, chat
):
    _style(monkeypatch, "broken {raw_data.x}")
    out = asyncio.run(agent._llm_format_report(WF, "ROWS", "alpha"))
    assert out == "worded"  # the reply still goes out
    assert chat["prompt"].startswith(prompt_loader.reply_style_built_in()[:30])
    assert "ROWS" in chat["prompt"]


def test_a_stray_brace_in_a_saved_text_does_not_stop_the_reply(monkeypatch, chat):
    _style(monkeypatch, "Use {curly} words. {raw_data}")
    asyncio.run(agent._llm_format_report(WF, "ROWS", "alpha"))
    assert (
        chat["prompt"] == "Use {curly} words. ROWS"
    )  # an unknown name is left as it is
