"""Making something new with the assistant: it always makes the kind the admin chose in the form
(a workflow, a building block or a case button), however the description sounds."""

import asyncio
import json

import pytest

from app.admin_panel import studio
from app.admin_panel.common import Ctx

STEP = {
    "op": "compute",
    "params": {},
}  # a step that is fine in a workflow and in a building block


def _ctx(kinds=True):
    return Ctx(
        source_key="alpha",
        org_id="o1",
        org_name="Alpha",
        caps={"workflow_kind": kinds},
        actor="test",
        closed_values=["closed"],
    )


def _answer(kind, steps):
    return json.dumps(
        {
            "reply": "Here it is.",
            "workflow": {
                "name": "Add a note",
                "kind": kind,
                "description": "Adds a note.",
                "fields": {},
                "example_phrases": [],
                "steps": steps,
            },
        }
    )


@pytest.fixture
def assistant(monkeypatch):
    """A pretend assistant: it says what the test queued, and every question to it is kept."""
    asked, answers = [], []

    async def schema(ctx):
        return {}

    async def workflows(ctx, exclude_id=None):
        return {}

    async def ask(system, payload, history, extra):
        asked.append({"payload": payload, "extra": extra})
        return answers.pop(0)

    monkeypatch.setattr(studio, "load_schema", schema)
    monkeypatch.setattr(studio, "load_workflows", workflows)
    monkeypatch.setattr(studio, "_ask", ask)
    monkeypatch.setattr(studio, "_rate_limit", lambda key: None)
    return asked, answers


def draft(kind, ctx=None):
    body = studio.ChatBody(message="add a note to a case", kind=kind)
    return asyncio.run(studio.studio_chat(body, ctx or _ctx()))


@pytest.mark.parametrize("kind", ["workflow", "block", "case_action"])
def test_the_assistant_is_told_what_the_admin_is_making(assistant, kind):
    asked, answers = assistant
    answers.append(_answer(kind, [STEP]))
    draft(kind)
    assert asked[0]["payload"]["kind"] == kind
    assert asked[0]["payload"]["allowed_kinds"] == ["workflow", "case_action", "block"]


@pytest.mark.parametrize("chosen", ["workflow", "block", "case_action"])
@pytest.mark.parametrize("said", ["workflow", "block", "case_action", "nonsense", None])
def test_the_draft_is_the_kind_that_was_chosen_whatever_the_assistant_says(
    assistant, chosen, said
):
    _, answers = assistant
    answers.append(_answer(said, [STEP]))
    got = draft(chosen)
    assert got["proposal"]["kind"] == chosen


def test_a_building_block_with_two_steps_is_sent_back_and_the_fixed_one_is_taken(
    assistant,
):
    asked, answers = assistant
    answers.append(_answer("block", [STEP, STEP]))
    answers.append(_answer("block", [STEP]))
    got = draft("block")
    assert got["proposal"]["kind"] == "block"
    assert len(got["proposal"]["steps"]) == 1
    assert "building block is one step" in asked[1]["extra"]


def test_a_building_block_that_stays_two_steps_is_not_offered(assistant):
    _, answers = assistant
    answers.extend([_answer("block", [STEP, STEP]), _answer("block", [STEP, STEP])])
    got = draft("block")
    assert got["proposal"] is None
    assert any("building block is one step" in p for p in got["problems"])


def test_the_same_two_steps_are_fine_in_a_workflow(assistant):
    _, answers = assistant
    answers.append(_answer("block", [STEP, STEP]))
    got = draft("workflow")
    assert got["proposal"]["kind"] == "workflow" and len(got["proposal"]["steps"]) == 2


def test_an_organisation_without_kinds_only_makes_workflows(assistant):
    asked, answers = assistant
    answers.append(_answer("block", [STEP]))
    got = draft("block", _ctx(kinds=False))
    assert got["proposal"]["kind"] == "workflow"
    assert asked[0]["payload"]["allowed_kinds"] == ["workflow"]
