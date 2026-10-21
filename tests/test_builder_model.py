"""Tests for the plain-words builder's view of a workflow (app/services/builder_model.py).

The round-trip tests open every live Godrej and Baanganga workflow and block as boxes and turn
the boxes back into steps: what comes back must be exactly what went in (as the database stores
it). tests/fixtures/live_workflow_definitions.json holds their definitions only (steps, questions
and wording, no people or cases), read from the backups of 16 Oct 2026.
"""

import json
from pathlib import Path

import pytest

from app.services import builder_model as bm

FIX = Path(__file__).parent / "fixtures"
LIVE = json.loads((FIX / "live_workflow_definitions.json").read_text(encoding="utf-8"))
OLD = json.loads((FIX / "godrej_case_workflows.json").read_text(encoding="utf-8"))
ALL = [
    pytest.param(w, id=f"{org}:{w['intent_key']}")
    for org, d in LIVE.items()
    for w in d["workflows"]
] + [pytest.param(w, id=f"old:{w['intent_key']}") for w in OLD]


def same(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@pytest.mark.parametrize("wf", ALL)
def test_every_live_workflow_comes_back_unchanged(wf):
    steps = wf.get("steps") or []
    assert same(bm.from_boxes(bm.to_boxes(steps)), steps)


def test_the_fixture_has_both_organisations():
    assert len(LIVE["godrej"]["workflows"]) >= 40
    assert len(LIVE["baanganga"]["workflows"]) >= 5


def test_steps_sharing_a_guard_become_one_if_with_two_lanes():
    yes = {"field": "$fields.tell_buttons", "equals": "yes"}
    no = {"field": "$fields.tell_buttons", "not_equals": "yes"}
    steps = [
        {"op": "run_workflow", "params": {"workflow": "a"}},
        {"op": "notify.parties", "when": yes, "params": {"buttons": {"Close": "/close"}}},
        {"op": "notify.user", "when": yes, "params": {"to": "$user.phone"}},
        {"op": "notify.parties", "when": no, "params": {}},
    ]
    boxes = bm.to_boxes(steps)
    assert [b["kind"] for b in boxes] == ["step", "if"]
    assert boxes[1]["rule"] == yes
    assert len(boxes[1]["yes"]) == 2 and len(boxes[1]["no"]) == 1
    assert "when" not in boxes[1]["yes"][0]["step"]
    assert "rule_no" not in boxes[1]  # the plain opposite: no need to keep it
    assert same(bm.from_boxes(boxes), steps)


def test_a_lone_guard_is_an_if_without_otherwise():
    c = {"field": "$fields.comment_text", "exists": True}
    boxes = bm.to_boxes([{"op": "run_workflow", "when": c, "params": {"workflow": "x"}}])
    assert boxes[0]["kind"] == "if" and boxes[0]["no"] == []


def test_guards_joined_with_and_become_nested_ifs():
    a = {"field": "$fields.amount", "gt": 5000}
    b = {"field": "$fields.kind", "equals": "travel"}
    c = {"field": "$fields.urgent", "exists": True}
    steps = [
        {"op": "notify.user", "when": {"and": [a, b, c]}, "params": {"to": "$user.phone"}}
    ]
    boxes = bm.to_boxes(steps)
    assert boxes[0]["rule"] == a
    inner = boxes[0]["yes"][0]
    assert inner["kind"] == "if" and inner["rule"] == b
    assert inner["yes"][0]["rule"] == c
    assert same(bm.from_boxes(boxes), steps)


@pytest.mark.parametrize("join", ["and", "or"])
def test_an_if_with_several_rules_and_an_otherwise_lane_opens_again_as_one_if(join):
    rule = {join: [{"field": "$fields.a", "exists": True}, {"field": "$fields.b", "equals": "x"}]}
    boxes = [
        {
            "kind": "if",
            "rule": rule,
            "yes": [{"kind": "step", "step": {"op": "compute", "params": {}}}],
            "no": [{"kind": "step", "step": {"op": "notify.user", "params": {}}}],
        }
    ]
    steps = bm.from_boxes(boxes)
    assert steps[1]["when"] == {"not": rule}
    again = bm.to_boxes(steps)
    assert len(again) == 1 and again[0]["rule"] == rule
    assert len(again[0]["yes"]) == 1 and len(again[0]["no"]) == 1


def test_nested_ifs_without_otherwise_still_open_nested():
    a, b = {"field": "$fields.a", "exists": True}, {"field": "$fields.b", "exists": True}
    steps = [{"op": "compute", "params": {}, "when": a}, {"op": "compute", "params": {}, "when": {"and": [a, b]}}]
    boxes = bm.to_boxes(steps)
    assert len(boxes) == 1 and boxes[0]["rule"] == a
    assert boxes[0]["yes"][1]["kind"] == "if" and boxes[0]["yes"][1]["rule"] == b


def test_a_new_otherwise_lane_is_written_as_the_opposite_guard():
    boxes = [
        {
            "kind": "if",
            "rule": {"field": "$fields.answer", "equals": "Approve"},
            "yes": [{"kind": "step", "step": {"op": "db.insert_row", "params": {}}}],
            "no": [{"kind": "step", "step": {"op": "notify.user", "params": {}}}],
        }
    ]
    steps = bm.from_boxes(boxes)
    assert steps[0]["when"] == {"field": "$fields.answer", "equals": "Approve"}
    assert steps[1]["when"] == {"field": "$fields.answer", "not_equals": "Approve"}


@pytest.mark.parametrize(
    "cond, expected",
    [
        ({"field": "$f.x", "exists": True}, {"field": "$f.x", "exists": False}),
        ({"field": "$f.x", "gt": 5}, {"field": "$f.x", "lte": 5}),
        ({"field": "$f.x", "in": ["a"]}, {"field": "$f.x", "not_in": ["a"]}),
        ({"and": [{"field": "$f.x", "exists": True}]}, {"not": {"and": [{"field": "$f.x", "exists": True}]}}),
        ({"not": {"field": "$f.x", "exists": True}}, {"field": "$f.x", "exists": True}),
    ],
)
def test_opposite(cond, expected):
    assert bm.opposite(cond) == expected


def test_steps_that_cannot_be_shown_as_ifs_keep_their_own_guard():
    x, y, z = ({"field": f"$fields.{k}", "exists": True} for k in "xyz")
    odd = {"and": [x, {"and": [y, z]}]}  # an "and" inside an "and": lanes would flatten it
    steps = [{"op": "notify.user", "when": odd, "params": {}}]
    boxes = bm.to_boxes(steps)
    assert boxes[0]["kind"] == "step" and boxes[0]["step"]["when"] == odd
    assert same(bm.from_boxes(boxes), steps)


def test_a_box_of_an_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        bm.from_boxes([{"kind": "rocket"}])


# ── the data panel ───────────────────────────────────────────────────────────

SCHEMA = {
    "cases": {"id", "case_number", "title", "location", "assigned_to_id"},
    "case_activity": {"id", "case_id", "payload"},
}


def test_base_data_is_the_person_and_the_answers():
    items = bm.base_data({"case_number": {"label": "Case"}, "comment_text": {}})
    paths = [i["path"] for i in items]
    assert "$user.name" in paths and "$fields.case_number" in paths
    assert next(i for i in items if i["path"] == "$fields.case_number")["label"] == "Case"
    assert next(i for i in items if i["path"] == "$fields.comment_text")["label"] == "Comment text"
    block = bm.base_data({"note": {}}, kind="block")
    assert block[-1]["group"] == "What it needs"


def test_a_found_record_gives_its_columns():
    step = {"op": "resolve_entity", "params": {"table": "cases", "into": "case"}}
    items = bm.data_made_by(step, SCHEMA)
    title = next(i for i in items if i["path"] == "$case.title")
    assert title["label"] == "Case – Title" and title["token"] == "{case_title}"


def test_a_saved_row_gives_its_columns_and_number():
    step = {
        "op": "db.insert_row",
        "params": {"table": "cases", "values": {"title": "$fields.title"}, "sequence": {"field": "case_number"}},
    }
    paths = [i["path"] for i in bm.data_made_by(step, SCHEMA)]
    assert "$inserted.cases.case_number" in paths


def test_a_block_gives_what_its_steps_find_or_what_it_names():
    wfs = {
        "find_case": {"name": "Find the case", "steps": [{"op": "resolve_entity", "params": {"table": "cases", "into": "case"}}]},
        "named": {"name": "Check slot", "steps": [], "settings": {"outputs": [{"label": "Already booked", "path": "$clash.id"}]}},
    }
    found = bm.data_made_by({"op": "run_workflow", "params": {"workflow": "find_case"}}, SCHEMA, wfs)
    assert any(i["path"] == "$case.title" for i in found)
    named = bm.data_made_by({"op": "run_workflow", "params": {"workflow": "named"}}, SCHEMA, wfs)
    assert named == [{"label": "Check slot – Already booked", "path": "$clash.id", "token": "{clash.id}", "group": "Check slot"}]


def test_a_block_that_runs_itself_does_not_loop():
    wfs = {"a": {"steps": [{"op": "run_workflow", "params": {"workflow": "a"}}]}}
    assert bm.data_made_by({"op": "run_workflow", "params": {"workflow": "a"}}, SCHEMA, wfs) == []


def test_new_steps_give_their_answers():
    appr = bm.data_made_by({"op": "ask_approval", "params": {"into": "committee"}}, SCHEMA)
    assert [i["path"] for i in appr] == ["$fields.committee", "$fields.committee_by"]
    ai = bm.data_made_by({"op": "ai.ask", "params": {"task": "extract", "fields": [{"name": "date"}]}}, SCHEMA)
    assert ai[0]["path"] == "$fields.date"


@pytest.mark.parametrize(
    "path, token",
    [("$fields.note", "{note}"), ("$case.title", "{case_title}"), ("$user.name", "{user.name}"), ("$inserted.cases.case_number", "{inserted.cases.case_number}")],
)
def test_tokens(path, token):
    assert bm.token_for(path) == token


# ── the endpoint the builder calls while editing ─────────────────────────────


@pytest.fixture
def studio_ctx(monkeypatch):
    import asyncio

    from app.admin_panel import studio
    from app.admin_panel.common import Ctx

    async def schema(ctx):
        return SCHEMA

    async def workflows(ctx, exclude_id=None):
        return {}

    monkeypatch.setattr(studio, "load_schema", schema)
    monkeypatch.setattr(studio, "load_workflows", workflows)
    ctx = Ctx(source_key="alpha", org_id="o1", org_name="Alpha", caps={"workflow_kind": True}, actor="test", closed_values=["closed"])
    return lambda body: asyncio.run(studio.builder_compile(studio.BuilderBody(**body), ctx))


def test_compile_gives_the_steps_their_data_and_the_problems(studio_ctx):
    got = studio_ctx(
        {
            "boxes": [
                {"kind": "step", "step": {"op": "resolve_entity", "params": {"table": "cases", "into": "case", "name_from": "$fields.case_number", "match_column": "case_number"}}},
                {"kind": "if", "rule": {"field": "$case.assigned_to_id", "exists": True},
                 "yes": [{"kind": "step", "step": {"op": "notify.user", "params": {"to": "$user.phone", "message_template": "Case {case_title}"}}}], "no": []},
                {"kind": "step", "step": {"op": "db.update_row", "params": {"table": "cases", "set": {"nope": 1}, "where": {"id": "$case.id"}}}},
            ],
            "entity_schema": {"case_number": {"type": "string", "required": True}},
        }
    )
    assert got["steps"][1]["when"] == {"field": "$case.assigned_to_id", "exists": True}
    assert any(i["path"] == "$case.title" for i in got["step_data"][0])
    assert any("nope" in e for e in got["errors"])


def test_compile_refuses_boxes_that_are_not_valid(studio_ctx):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        studio_ctx({"boxes": [{"kind": "if", "yes": []}]})
    assert e.value.status_code == 422


def test_builder_view_lists_one_data_entry_per_step():
    steps = LIVE["godrej"]["workflows"][0]["steps"]
    view = bm.builder_view(steps, {}, SCHEMA, {}, "workflow")
    assert len(view["step_data"]) == len(steps)
