"""Catalogue groups C (draft, confirm, cancel), D (workflow engine) and parts of B and G, run end to end through the
real chat handler on throwaway databases. Every bug test has a control test next to it that proves the set-up works,
so a failure means the bug and not a broken test.

A case that fails today is `xfail(strict=True)` tagged with its bug ID (see test_10_pure.py).
"""

import asyncio
import json

import pytest

from tests.qa.harness import llm_message, needs_qa, qa_run
from tests.qa.qa_helpers import (
    count,
    notes,
    open_drafts,
    pending_approval_ids,
    phone_of,
)
from tests.qa.seed import NOTE_STEP


def bug(ident: str, why: str = ""):
    return pytest.mark.xfail(strict=True, reason=f"{ident} {why}".strip())


async def start_big_request(
    w, title: str, amount: int = 60000, who: str = "staff"
) -> str:
    """The requester says yes to a request that needs approval; returns the id of the approval that was created."""
    await w.login(who)
    await w.make_pending(who, "qa_note_big", {"title": title, "amount": amount})
    await w.say(phone_of(w, who), "yes")
    ids = await pending_approval_ids(w)
    assert len(ids) == 1, f"expected one pending approval, found {ids}"
    return ids[0]


# ───────────────────────────── C. draft, confirm, cancel ─────────────────────────────


@needs_qa
def test_C_control_one_yes_runs_the_action_once():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "control"})
        await w.say(phone_of(w, "member"), "yes")
        assert await notes(w, "control") == 1
        assert await open_drafts(w, "member") == 0

    qa_run(scenario)


@needs_qa
@bug("QA-003", "two 'yes' at once both read the draft and both run every step")
def test_C01_two_yes_at_once_run_the_action_once():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "double-yes"})
        from app.routers import webhook

        w.slow_after(
            webhook, "get_session", 0.05
        )  # a real Redis answer takes a few milliseconds
        phone = phone_of(w, "member")
        await asyncio.gather(w.say(phone, "yes"), w.say(phone, "yes"))
        assert await notes(w, "double-yes") == 1

    qa_run(scenario)


@needs_qa
@bug("QA-006", "a 'yes' runs a draft that is two hours old")
def test_C02_yes_to_a_two_hour_old_draft_does_not_run_it():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "stale"}, age_minutes=120)
        await w.say(phone_of(w, "member"), "yes")
        assert await notes(w, "stale") == 0

    qa_run(scenario)


@needs_qa
def test_C08_plain_cancel_clears_the_draft_and_says_so():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "cancel-me"})
        phone = phone_of(w, "member")
        await w.say(phone, "cancel")
        assert await open_drafts(w, "member") == 0
        assert await notes(w, "cancel-me") == 0
        assert w.texts_to(phone), "the person heard nothing"

    qa_run(scenario)


@needs_qa
def test_C09_a_hindi_confirmation_word_from_the_organisations_list_confirms():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "haan"})
        await w.say(phone_of(w, "member"), "haan")
        assert await notes(w, "haan") == 1

    qa_run(scenario)


@needs_qa
def test_C07_cancel_followed_by_a_thing_is_not_swallowed_by_the_cancel_gate():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "keep"})
        w.llm.queue(llm_message(content="Which invoice?"))
        await w.say(phone_of(w, "member"), "cancel invoice INV-1")
        assert await open_drafts(w, "member") == 1, (
            "the draft was cleared by a message about an invoice"
        )

    qa_run(scenario)


@needs_qa
@bug("QA-021", "the second message's write replaces the first one's history")
def test_C11_two_quick_messages_both_stay_in_the_conversation():
    async def scenario(w):
        from app.redis_client import get_session

        await w.login("member")

        async def slow(*a, **k):
            await asyncio.sleep(0.3)
            return llm_message(content="Noted.")

        w.llm.handler(slow)
        phone = phone_of(w, "member")
        await asyncio.gather(
            w.say(phone, "first question please"),
            w.say(phone, "second question please"),
        )
        session = await get_session(f"{w.ids.org_id}:{phone}")
        said = " ".join(
            str(m.get("content"))
            for m in session.get("conversation_history", [])
            if m.get("role") == "user"
        )
        assert "first question" in said and "second question" in said, said

    qa_run(scenario)


@needs_qa
def test_C_control_one_slow_message_is_kept_in_the_conversation():
    async def scenario(w):
        from app.redis_client import get_session

        await w.login("member")
        w.llm.queue(llm_message(content="Noted."))
        phone = phone_of(w, "member")
        await w.say(phone, "only question")
        session = await get_session(f"{w.ids.org_id}:{phone}")
        assert "only question" in " ".join(
            str(m.get("content")) for m in session.get("conversation_history", [])
        )

    qa_run(scenario)


@needs_qa
@bug("QA-016", "a draft for a switched-off workflow stays active and comes back")
def test_C13_a_draft_for_a_switched_off_workflow_does_not_come_back():
    async def scenario(w):
        await w.login("member")
        await w.make_pending("member", "qa_note", {"title": "dead"})
        await w.run(
            "UPDATE workflows SET is_active = false WHERE intent_key = 'qa_note'"
        )
        await w.say(phone_of(w, "member"), "yes")
        assert await notes(w, "dead") == 0
        assert await open_drafts(w, "member") == 0, (
            "the draft is still open and will be offered again"
        )

    qa_run(scenario)


# ───────────────────────────── D. workflow engine, approvals ─────────────────────────────


@needs_qa
def test_D_control_an_approval_is_asked_for_and_one_tap_runs_the_action_once():
    async def scenario(w):
        approval = await start_big_request(w, "control-approval")
        assert await notes(w, "control-approval") == 0, "ran before the approval"
        buttons = [
            m
            for m in w.sent
            if m["kind"] == "buttons" and m["to"] == phone_of(w, "approver")
        ]
        assert buttons, "the approver was not asked"
        await w.login("approver")
        await w.say(
            phone_of(w, "approver"), f"action:approve:{approval}", "interactive"
        )
        assert await notes(w, "control-approval") == 1

    qa_run(scenario)


@needs_qa
def test_D27_the_approval_gate_asks_the_approver_and_tells_the_requester_it_was_sent():
    async def scenario(w):
        await w.login("staff")
        await w.make_pending("staff", "qa_note_big", {"title": "gate", "amount": 60000})
        await w.say(phone_of(w, "staff"), "yes")
        asked = [
            m
            for m in w.sent
            if m["kind"] == "buttons" and m["to"] == phone_of(w, "approver")
        ]
        said = " ".join(w.texts_to(phone_of(w, "staff"))).lower()
        assert asked, "the approver was never asked"
        assert "couldn't save" not in said, said

    qa_run(scenario)


@needs_qa
@bug(
    "QA-004",
    "two taps on Approve both pass the 'pending' check and both run the action",
)
def test_D20_two_taps_on_approve_run_the_action_once():
    async def scenario(w):
        approval = await start_big_request(w, "tapped-twice")
        from app.executor import workflow_executor

        w.slow_after(
            workflow_executor,
            "fetch_one",
            0.1,
            when=lambda q, *a, **k: "pending_approvals" in q,
        )
        await w.login("approver")
        phone = phone_of(w, "approver")
        tap = (phone, f"action:approve:{approval}", "interactive")
        await asyncio.gather(w.say(*tap), w.say(*tap))
        assert await notes(w, "tapped-twice") == 1

    qa_run(scenario)


@needs_qa
@bug(
    "QA-017", "the approved run resumes at a stored step number in the CURRENT workflow"
)
def test_D26_an_approved_action_runs_even_if_the_workflow_was_edited_while_it_waited():
    async def scenario(w):
        approval = await start_big_request(w, "resume-after-edit")
        # while the approval waits, the owner removes the approval step (the workflow now has one step)
        await w.run(
            "UPDATE workflows SET steps = $1::jsonb WHERE intent_key = 'qa_note_big'",
            json.dumps([NOTE_STEP]),
        )
        await w.login("approver")
        await w.say(
            phone_of(w, "approver"), f"action:approve:{approval}", "interactive"
        )
        assert await notes(w, "resume-after-edit") == 1

    qa_run(scenario)


@needs_qa
@bug("QA-028", "after a rejection the requester's draft stays at 'awaiting approval'")
def test_D19_a_rejected_request_closes_the_requesters_draft():
    async def scenario(w):
        approval = await start_big_request(w, "rejected")
        await w.login("approver")
        await w.say(phone_of(w, "approver"), f"action:reject:{approval}", "interactive")
        assert await notes(w, "rejected") == 0
        assert await open_drafts(w, "staff") == 0

    qa_run(scenario)


@needs_qa
@bug(
    "QA-019",
    "(a) the approval row is made and the requester is told it was sent, but nobody is asked",
)
@pytest.mark.parametrize("how", ["approver_switched_off"])
def test_D17_a_request_with_no_approver_is_not_reported_as_sent(how):
    async def scenario(w):
        await w.run(
            "UPDATE users SET is_active = false WHERE phone = $1",
            phone_of(w, "approver"),
        )
        await w.login("staff")
        await w.make_pending(
            "staff", "qa_note_big", {"title": "no-approver", "amount": 60000}
        )
        await w.say(phone_of(w, "staff"), "yes")
        said = " ".join(w.texts_to(phone_of(w, "staff"))).lower()
        asked = [m for m in w.sent if m["kind"] == "buttons"]
        assert asked or any(
            w_ in said for w_ in ("no one", "nobody", "no approver", "could not find")
        ), said

    qa_run(scenario)


@needs_qa
@bug(
    "QA-005",
    "a failed second step leaves the first step's row, and the person is told to try again",
)
def test_D14_a_failed_second_step_leaves_no_half_written_rows():
    async def scenario(w):
        await w.login("admin")
        await w.make_pending("admin", "qa_partial_fail", {"title": "half"})
        await w.say(phone_of(w, "admin"), "yes")
        n = await count(
            w, "SELECT count(*) AS n FROM cases WHERE case_number = 'QA-PARTIAL-1'"
        )
        assert n == 0, f"{n} row(s) from the failed run are still there"

    qa_run(scenario)


@needs_qa
def test_D_control_the_failed_second_step_really_fails_and_the_person_is_told():
    async def scenario(w):
        await w.login("admin")
        await w.make_pending("admin", "qa_partial_fail", {"title": "half"})
        phone = phone_of(w, "admin")
        await w.say(phone, "yes")
        assert any(
            "save" in t.lower() or "went wrong" in t.lower() or "couldn" in t.lower()
            for t in w.texts_to(phone)
        ), w.texts_to(phone)

    qa_run(scenario)


@needs_qa
@bug(
    "QA-027",
    "the number is worked out and inserted without a lock that lasts, so concurrent runs collide",
)
def test_D23_ten_concurrent_runs_get_ten_different_case_numbers():
    async def scenario(w):
        from app.services.action_executor import execute_pending_action

        user = await w.user("member")
        pending = {
            "intent_key": "qa_case_file",
            "fields": {"title": "race", "description": "x"},
            "stage": "awaiting_confirmation",
        }
        await asyncio.gather(
            *[
                execute_pending_action(dict(pending), user, phone=user["phone"])
                for _ in range(10)
            ]
        )
        n = await count(w, "SELECT count(*) AS n FROM cases WHERE title = 'race'")
        assert n == 10, f"only {n} of 10 concurrent runs produced a case"

    qa_run(scenario)


@needs_qa
def test_D_control_ten_runs_one_after_another_get_ten_numbers():
    async def scenario(w):
        from app.services.action_executor import execute_pending_action

        user = await w.user("member")
        pending = {
            "intent_key": "qa_case_file",
            "fields": {"title": "serial", "description": "x"},
            "stage": "awaiting_confirmation",
        }
        for _ in range(10):
            await execute_pending_action(dict(pending), user, phone=user["phone"])
        rows = await w.sql("SELECT case_number FROM cases WHERE title = 'serial'")
        assert len({r["case_number"] for r in rows}) == 10

    qa_run(scenario)
