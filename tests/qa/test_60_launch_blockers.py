"""The launch blockers (P0 in docs/launch/QA-priority-work-order.md): tests written for them.

Each test fails before its fix and passes after it. They run on throwaway databases like the rest of tests/qa.
"""

import json

from tests.qa.harness import _patch, needs_qa, qa_run
from tests.qa.qa_helpers import phone_of

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
