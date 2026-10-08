"""The launch blockers (P0 in docs/launch/QA-priority-work-order.md): tests written for them.

Each test fails before its fix and passes after it. They run on throwaway databases like the rest of tests/qa.
"""

import json

from tests.qa.harness import _patch, llm_message, needs_qa, qa_run
from tests.qa.qa_helpers import notes, open_drafts, phone_of

# ───────────────────────────── P0-1 · the open doors (QA-015, QA-002) ─────────────────────────────


@needs_qa
def test_I02_the_debug_routes_are_gone():
    async def scenario(w):
        async with w.client() as c:
            for path in ("/debug/schema/" + w.key, "/debug/clear-schema-cache"):
                answer = await c.get(path)
                assert answer.status_code in (401, 403, 404, 405), (
                    f"{path} answered {answer.status_code}"
                )
                assert "tables" not in answer.text

    qa_run(scenario)


@needs_qa
def test_I03_health_makes_no_paid_calls():
    async def scenario(w):
        from app import main

        class Boom:
            made = 0

            def __init__(self, *a, **k):
                Boom.made += 1
                raise AssertionError(
                    "/health created an AI client: that is a paid call on every visit"
                )

        _patch(w, main, "AsyncOpenAI", Boom)
        async with w.client() as c:
            answer = await c.get("/health")
        assert answer.status_code == 200
        body = answer.json()
        assert Boom.made == 0
        outside = [u for u in w.http_calls if "testserver" not in u]
        assert not outside, f"/health reached out to {outside}"
        assert {"database", "redis"} <= set(body["dependencies"])
        assert not ({"openai", "cerebras", "llm_ladder"} & set(body["dependencies"]))

    qa_run(scenario)


@needs_qa
def test_I04_the_deep_health_check_needs_a_super_admin_sign_in():
    async def scenario(w):
        async with w.client() as c:
            answer = await c.get("/health/deep")
        assert answer.status_code == 401

    qa_run(scenario)


# ───────────────────────────── P0-4 · the reminder storm (QA-011) ─────────────────────────────


@needs_qa
def test_H05c_a_case_nobody_can_be_reached_about_is_given_up_after_the_limit_and_the_limit_is_a_setting():
    async def scenario(w):
        from app.scheduler.jobs import run_case_reminders
        from tests.qa.test_50_scheduler_and_reports import (
            add_case,
            reminded,
            reminders_world,
        )

        await reminders_world(w)
        await w.run(
            "UPDATE orgs SET settings = settings || $1::jsonb",
            json.dumps({"limits": {"reminder_max_failures": 2}}),
        )
        await add_case(w, "G-1", "3 hours", complainant="approver")
        everyone = {phone_of(w, "member"), phone_of(w, "approver")}
        attempts = []

        def refuse(to, kind):
            if to in everyone:
                attempts.append(to)
                return RuntimeError("blocked the bot")

        w.fail_sends = refuse
        await run_case_reminders()
        assert not await reminded(w, "G-1"), (
            "given up after one failed pass although the limit is 2"
        )
        await run_case_reminders()
        assert await reminded(w, "G-1"), "still not given up after 2 failed passes"
        before = len(attempts)
        await run_case_reminders()
        await run_case_reminders()
        assert len(attempts) == before, "it kept trying after it gave up"

    qa_run(scenario)


@needs_qa
def test_H05d_a_rate_limited_bot_pauses_the_pass_and_the_case_is_not_given_up():
    async def scenario(w):
        from app.scheduler.jobs import run_case_reminders
        from app.services.telegram import TelegramRateLimitedError
        from tests.qa.test_50_scheduler_and_reports import (
            add_case,
            reminded,
            reminders_world,
        )

        await reminders_world(w)
        await w.run(
            "UPDATE orgs SET settings = settings || $1::jsonb",
            json.dumps({"limits": {"reminder_max_failures": 1}}),
        )
        await add_case(w, "L-1", "3 hours")
        await add_case(w, "L-2", "3 hours")
        w.fail_sends = lambda to, kind: TelegramRateLimitedError(30)
        for _ in range(3):
            await run_case_reminders()
        assert not await reminded(w, "L-1") and not await reminded(w, "L-2"), (
            "a rate limit was counted as a failed try"
        )
        w.fail_sends = None
        await run_case_reminders()
        assert await reminded(w, "L-1") and await reminded(w, "L-2"), (
            "the reminders did not go out once Telegram allowed them"
        )

    qa_run(scenario)


@needs_qa
def test_H05e_a_reminder_that_reached_one_person_is_not_repeated_to_that_person():
    async def scenario(w):
        from app.scheduler.jobs import run_case_reminders
        from tests.qa.test_50_scheduler_and_reports import (
            add_case,
            reminded,
            reminders_world,
        )

        await reminders_world(w)
        await add_case(w, "P-1", "3 hours", complainant="approver")
        approver = phone_of(w, "approver")
        w.fail_sends = lambda to, kind: (
            RuntimeError("blocked") if to == approver else None
        )
        for _ in range(3):
            await run_case_reminders()
        mine = [t for t in w.texts_to(phone_of(w, "member")) if "P-1" in t]
        assert len(mine) == 1 and await reminded(w, "P-1")

    qa_run(scenario)


# ───────────────────────────── P0-6 · "yes, but…" and "cancel invoice" (QA-007, QA-024) ─────────────────────────────


@needs_qa
def test_C10_yes_but_does_not_save_the_old_values():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "old-title"})
        w.llm.queue(llm_message(content="What should the title be?"))
        await w.say(phone_of(w, "member"), "yes but call it new-title")
        assert await notes(w, "old-title") == 0, "the old values were saved"
        assert await open_drafts(w, "member") == 1, "the draft was thrown away"

    qa_run(scenario)


@needs_qa
def test_C12_yes_with_a_polite_word_still_saves():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "polite"})
        await w.say(phone_of(w, "member"), "yes save it")
        assert await notes(w, "polite") == 1

    qa_run(scenario)


@needs_qa
def test_C14_no_problem_go_ahead_does_not_cancel_the_draft():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "keep-me"})
        w.llm.queue(llm_message(content="Shall I save it?"))
        await w.say(phone_of(w, "member"), "no problem, go ahead")
        assert await open_drafts(w, "member") == 1, (
            "a message with 'no' in it cancelled the draft"
        )

    qa_run(scenario)


@needs_qa
def test_C15_dont_cancel_does_not_cancel_the_draft():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "dont"})
        w.llm.queue(llm_message(content="OK, I will keep it."))
        await w.say(phone_of(w, "member"), "don't cancel")
        assert await open_drafts(w, "member") == 1, "'don't cancel' cancelled the draft"

    qa_run(scenario)


@needs_qa
def test_C16_please_cancel_cancels_the_draft():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "bye"})
        await w.say(phone_of(w, "member"), "please cancel")
        assert await open_drafts(w, "member") == 0
        assert await notes(w, "bye") == 0

    qa_run(scenario)


@needs_qa
def test_C17_a_strangers_account_is_not_created_by_a_yes_that_changes_something():
    """The same rule for the account details a stranger on Telegram is asked to confirm."""

    async def scenario(w):
        from app.services.vocabulary import get_vocabulary, matches_vocab

        vocab = await get_vocabulary(w.ids.org_id, w.key)
        fillers = vocab["filler_words"]
        assert matches_vocab("yes please", vocab["confirm_words"], fillers)
        assert not matches_vocab(
            "yes but my email is other@example.test", vocab["confirm_words"], fillers
        )

    qa_run(scenario)


# ───────────────────────────── P0-5 · one message at a time per person (QA-003, QA-021) ─────────────────────────────


async def _telegram_person_with_a_draft(w, chat: int, title: str):
    """A registered Telegram person in the middle of a request that waits for her yes."""
    import datetime as dt

    from app.redis_client import get_session, set_session
    from app.services.draft_store import upsert_draft
    from app.services.identity import resolve_identity

    await w.run(
        "INSERT INTO users (org_id, role_id, name, phone, email, channel) VALUES ($1, $2, $3, $4, $5, 'telegram')",
        w.ids.org_id,
        w.ids.role["member"],
        f"Telegram Person {chat}",
        f"tg:{chat}",
        f"tg{chat}@example.test",
    )
    user = await resolve_identity(f"tg:{chat}")
    fields = {"title": title}
    await upsert_draft(
        org_id=user["org_id"],
        user_id=user["user_id"],
        intent_key="qa_note",
        fields=fields,
        stage="awaiting_confirmation",
        source_key=user["source_key"],
    )
    session_id = f"{user['org_id']}:tg:{chat}"
    session = await get_session(session_id)
    session["pending_action"] = {
        "intent_key": "qa_note",
        "fields": fields,
        "stage": "awaiting_confirmation",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "reprompt_count": 0,
    }
    await set_session(session_id, session, ttl=480 * 60)
    await w.login(f"tg:{chat}")
    return user


@needs_qa
def test_C01b_two_yes_at_once_on_telegram_run_the_action_once():
    async def scenario(w):
        import asyncio

        from app.routers import webhook

        await _telegram_person_with_a_draft(w, 555, "tg-double-yes")
        w.slow_after(
            webhook, "get_session", 0.05
        )  # a real Redis answer takes a few milliseconds
        w.llm.queue(llm_message(content="There is nothing waiting for a yes."))
        first, second = await asyncio.gather(
            w.tg_post(555, "yes", update_id=9001), w.tg_post(555, "yes", update_id=9002)
        )
        assert first.status_code == 200 and second.status_code == 200
        assert await notes(w, "tg-double-yes") == 1, "the request was saved twice"

    qa_run(scenario)


@needs_qa
def test_C18_a_message_that_waits_too_long_is_asked_to_wait_and_the_turn_is_given_back():
    async def scenario(w):
        import asyncio

        await w.login("member")
        # how long a second message waits is the organisation's setting
        await w.run(
            "UPDATE orgs SET settings = settings || $1::jsonb",
            json.dumps({"limits": {"turn_wait_seconds": 1}}),
        )
        started = asyncio.Event()

        async def slow(*a, **k):
            started.set()
            await asyncio.sleep(2.5)
            return llm_message(content="Done thinking.")

        w.llm.handler(slow)
        phone = phone_of(w, "member")
        first = asyncio.create_task(w.say(phone, "first question"))
        await started.wait()
        await w.say(phone, "second question")  # waits 1 second, then is told to wait
        assert any("one moment" in t.lower() for t in w.texts_to(phone)), w.texts_to(
            phone
        )
        await first

        async def quick(*a, **k):
            return llm_message(content="Back to normal.")

        w.llm.handler(quick)
        await w.say(phone, "third question")  # the first turn gave its place back
        assert any("back to normal" in t.lower() for t in w.texts_to(phone)), (
            w.texts_to(phone)
        )

    qa_run(scenario)


@needs_qa
def test_C19_a_lock_left_behind_by_a_crash_runs_out_and_lets_the_next_message_through():
    async def scenario(w):
        from app.redis_client import get_redis

        await w.login("member")
        phone = phone_of(w, "member")
        await get_redis().set(f"turn_lock:{phone}", "left-behind", px=400)
        w.llm.queue(llm_message(content="Here I am."))
        await w.say(phone, "hello")
        assert any("here i am" in t.lower() for t in w.texts_to(phone)), w.texts_to(
            phone
        )

    qa_run(scenario)


@needs_qa
def test_C20_a_redis_problem_does_not_stop_people_being_answered():
    async def scenario(w):
        from app.routers import webhook

        class Down:
            async def set(self, *a, **k):
                raise ConnectionError("down")

            get = delete = set

        await w.login("member")
        _patch(w, webhook, "get_redis", lambda: Down())
        w.llm.queue(llm_message(content="Still here."))
        phone = phone_of(w, "member")
        await w.say(phone, "hello")
        assert any("still here" in t.lower() for t in w.texts_to(phone)), w.texts_to(
            phone
        )

    qa_run(scenario)


@needs_qa
def test_C21_a_second_yes_for_a_card_that_was_already_claimed_is_not_run_again():
    """If the lock ever fails (it runs out, or Redis blinks), the card itself can still be saved only once."""

    async def scenario(w):
        from app.redis_client import get_session
        from app.routers import webhook

        await w.login("member")
        user = await w.make_pending("member", "qa_note", {"title": "claimed-once"})
        phone = phone_of(w, "member")
        # the card was already claimed by an earlier yes, which is still being carried out
        session = await get_session(f"{user['org_id']}:{phone}")
        claimed, _ = await webhook._claim_confirmation(user, session["pending_action"])
        assert claimed
        await w.say(phone, "yes")
        assert await notes(w, "claimed-once") == 0, (
            "a second yes ran a card that was already being saved"
        )

    qa_run(scenario)
