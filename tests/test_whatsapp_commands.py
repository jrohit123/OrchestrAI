"""The "/" command list on the WhatsApp number: made from the workflows, kept inside Meta's limits, only sent when it
changed, and never raising. No database or network: what it reads and calls is replaced."""

import asyncio

from app.services import whatsapp_commands as wc


def run(coro):
    return asyncio.run(coro)


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value


def world(monkeypatch, workflows, enabled=True, fail=False, current=None, redis=None):
    redis = redis if redis is not None else FakeRedis()
    calls = []

    async def say(source_key, key, **_):
        return "Show what I can do 😀"

    async def fetch_all(sql, *a, **k):
        return workflows

    async def fetch_one(sql, *a, **k):
        return {"id": "o1"}

    async def org_settings(source_key, org_id):
        return (
            {"whatsapp_commands": {"enabled": enabled}} if enabled is not None else {}
        )

    async def automation():
        return current or {}

    async def set_commands(commands, keep=None):
        if fail:
            raise RuntimeError("Meta refused")
        calls.append({"commands": commands, "keep": keep})

    async def source_key_for_channel(channel):
        return "godrej"

    monkeypatch.setattr(wc, "say", say)
    monkeypatch.setattr(wc, "fetch_all", fetch_all)
    monkeypatch.setattr(wc, "fetch_one", fetch_one)
    monkeypatch.setattr(wc, "get_redis", lambda: redis)
    monkeypatch.setattr(wc.config_store, "org_settings", org_settings)
    monkeypatch.setattr(wc.whatsapp, "conversational_automation", automation)
    monkeypatch.setattr(wc.whatsapp, "set_commands", set_commands)
    monkeypatch.setattr("app.db.get_source_key_for_channel", source_key_for_channel)
    return calls, redis


def wf(slash, name="Name", hint="A hint"):
    return {"slash_command": slash, "name": name, "command_description": hint}


def test_the_list_is_menu_first_then_each_workflow_with_a_slash_command_and_no_emoji(
    monkeypatch,
):
    world(
        monkeypatch,
        [
            wf("complaint", "File a complaint", "Report a problem"),
            wf("/Cases", hint=""),
        ],
    )
    got = run(wc.build("godrej", "o1"))
    assert [c["command_name"] for c in got] == ["menu", "complaint", "cases"]
    assert got[0]["command_description"] == "Show what I can do"  # the emoji is gone
    assert got[2]["command_description"] == "Name"  # no hint: the workflow's name


def test_names_that_meta_would_refuse_and_repeats_are_dropped_and_the_list_stops_at_thirty(
    monkeypatch,
):
    many = [wf(f"w{i:02d}") for i in range(40)]
    world(
        monkeypatch,
        [
            wf("has space"),
            wf("UPPER_ok"),
            wf("a" * 33),
            wf("menu"),
            wf("dup"),
            wf("dup"),
            *many,
        ],
    )
    got = [c["command_name"] for c in run(wc.build("godrej", "o1"))]
    assert got[:3] == ["menu", "upper_ok", "dup"] and len(got) == wc.MAX_COMMANDS
    assert len(set(got)) == len(got)


def test_a_long_hint_is_cut_to_what_meta_allows(monkeypatch):
    world(monkeypatch, [wf("x", hint="word " * 100)])
    assert len(run(wc.build("godrej", "o1"))[1]["command_description"]) <= wc.MAX_HINT


def test_it_does_nothing_unless_it_is_switched_on(monkeypatch):
    calls, _redis = world(monkeypatch, [wf("complaint")], enabled=None)
    assert run(wc.sync()) == "off" and calls == []


def test_it_calls_meta_once_and_again_only_when_the_list_changes(monkeypatch):
    workflows = [wf("complaint")]
    calls, _redis = world(
        monkeypatch,
        workflows,
        current={"prompts": ["Menu"], "enable_welcome_message": False},
    )
    assert run(wc.sync()) == "synced 2"
    assert calls[0]["keep"] == {
        "prompts": ["Menu"],
        "enable_welcome_message": False,
    }  # only the commands change
    assert run(wc.sync()) == "unchanged" and len(calls) == 1
    workflows.append(wf("cases"))
    assert run(wc.sync()) == "synced 3" and len(calls) == 2
    assert run(wc.sync(force=True)) == "synced 3" and len(calls) == 3


def test_a_refusal_from_meta_is_kept_quiet_and_not_retried_straight_away(monkeypatch):
    _calls, redis = world(monkeypatch, [wf("complaint")], fail=True)
    assert run(wc.sync()).startswith("failed")
    assert wc.FAILED_KEY in redis.data
    assert run(wc.sync()) == "waiting after a failure"


def test_no_redis_still_works(monkeypatch):
    calls, _ = world(monkeypatch, [wf("complaint")], redis=None)
    monkeypatch.setattr(wc, "get_redis", lambda: None)
    assert run(wc.sync()) == "synced 2" and len(calls) == 1
