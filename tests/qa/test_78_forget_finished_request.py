"""A request that was cancelled or finished is forgotten by the chat bot's AI, and a bare "hello" can never bring it back.

Seen on a real phone: after "No" (cancelled), a "hello" showed the same "Here's what I'll save" summary again, and after the
save another "hello" showed it a third time. The cause: the AI's memory of the chat still held the request, so it filled it
in again. The fix has two parts, both tested here: the memory is cleared when a request ends, and a message with no request
in it cannot start or confirm one."""

import pytest

from app.redis_client import get_session
from app.services import agent
from tests.qa.harness import llm_message, needs_qa, qa_run
from tests.qa.qa_helpers import open_drafts, phone_of

OLD_CHAT = [
    {"role": "user", "content": "my tap is leaking in T5-901, urgent"},
    {
        "role": "assistant",
        "content": "Here's what I'll save... Reply yes to save, no to cancel.",
    },
]


@pytest.mark.parametrize(
    "message, args, expected",
    [
        ("hello", None, True),
        ("हेलो", None, True),
        ("ok", None, True),
        ("yes please", None, True),
        ("/complaint", "leak", True),
        ("T5-901", None, False),
        ("my tap is leaking", None, False),
        ("/complaint", "tap leaking badly", False),
        ("plumber 2", None, False),
    ],
)
def test_a_message_that_asks_for_nothing_is_told_by_length_and_digits_in_any_language(
    message, args, expected
):
    assert agent._adds_nothing(message, args) is expected


async def session_of(w, name):
    user = await w.user(name)
    return await get_session(f"{user['org_id']}:{user['phone']}")


async def remember(w, name, history):
    from app.redis_client import set_session

    user = await w.user(name)
    key = f"{user['org_id']}:{user['phone']}"
    session = await get_session(key)
    session["conversation_history"] = list(history)
    await set_session(key, session, ttl=480 * 60)


@needs_qa
def test_saying_no_makes_the_chat_bot_forget_the_request():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "tap leak"})
        await remember(w, "member", OLD_CHAT)
        await w.say(phone_of(w, "member"), "no")
        session = await session_of(w, "member")
        assert not session.get("pending_action")
        assert session.get("conversation_history") == []
        assert await open_drafts(w, "member") == 0

    qa_run(scenario)


@needs_qa
def test_a_hello_after_a_cancel_gets_a_greeting_and_no_summary_even_if_the_ai_tries_to_revive_the_request():
    async def scenario(w):
        await w.login("member")
        phone = phone_of(w, "member")
        await w.make_pending("member", "qa_note", {"title": "tap leak"})
        await w.say(phone, "no")
        # the AI, remembering the old request somehow, tries to start it again and show the summary; once the chat bot
        # tells it there is no request in "hello" it greets instead
        seen = {"n": 0}

        def ai(*args, **kwargs):
            messages = kwargs.get("messages") or (args[0] if args else [])
            told_no = any(
                "does not ask for anything"
                in str(
                    m.get("content", "")
                    if isinstance(m, dict)
                    else getattr(m, "content", "")
                )
                for m in messages[-3:]
            )
            seen["n"] += 1
            if told_no:
                return llm_message(content="Hello! What do you need?")
            if seen["n"] == 1:
                return llm_message(
                    tool_calls=[
                        {
                            "name": "update_draft",
                            "args": {
                                "intent_key": "qa_note",
                                "fields": {"title": "tap leak"},
                            },
                        }
                    ]
                )
            return llm_message(
                tool_calls=[
                    {
                        "name": "confirm_action",
                        "args": {"action_description": "Save a note"},
                    }
                ]
            )

        w.llm.handler(ai)
        await w.say(phone, "hello")
        texts = w.texts_to(phone)
        assert not any("Here's what I'll save" in t for t in texts)
        assert any("What do you need" in t for t in texts), texts
        assert await open_drafts(w, "member") == 0
        assert not (await session_of(w, "member")).get("pending_action")

    qa_run(scenario)


@needs_qa
def test_control_a_real_request_in_words_still_reaches_its_summary():
    async def scenario(w):
        await w.login("member")
        phone = phone_of(w, "member")
        w.llm.queue(
            llm_message(
                tool_calls=[
                    {
                        "name": "update_draft",
                        "args": {
                            "intent_key": "qa_note",
                            "fields": {"title": "tap leak"},
                        },
                    }
                ]
            ),
            llm_message(
                tool_calls=[
                    {
                        "name": "confirm_action",
                        "args": {"action_description": "Save a note"},
                    }
                ]
            ),
        )
        await w.say(phone, "please save a note called tap leak")
        assert any("Here's what I'll save" in t for t in w.texts_to(phone))
        assert await open_drafts(w, "member") == 1

    qa_run(scenario)


@needs_qa
def test_a_finished_request_is_forgotten_except_its_closing_exchange():
    async def scenario(w):
        await w.login("member")
        phone = phone_of(w, "member")
        await w.make_pending("member", "qa_note", {"title": "saved one"})
        await remember(w, "member", OLD_CHAT * 5)
        await w.say(phone, "yes")
        history = (await session_of(w, "member"))["conversation_history"]
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "yes"}
        assert history[1]["role"] == "assistant"

    qa_run(scenario)


@needs_qa
def test_the_cancel_command_also_makes_the_chat_bot_forget():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "tap leak"})
        await remember(w, "member", OLD_CHAT)
        await w.say(phone_of(w, "member"), "/cancel")
        session = await session_of(w, "member")
        assert session.get("conversation_history") == []
        assert not session.get("pending_action")

    qa_run(scenario)
