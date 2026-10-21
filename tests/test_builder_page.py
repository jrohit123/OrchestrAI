"""The builder's page script turns steps into boxes and back by the same rules as
app/services/builder_model.py. Run in Node on every live Godrej and Baanganga workflow and block
(tests/fixtures/live_workflow_definitions.json): the page must make the same boxes as the server,
and give back exactly the steps it was given."""

import json
from pathlib import Path

from app.admin_panel.ui import js_builder, js_studio_form
from app.services import builder_model as bm
from tests.js_page import run_page

FIX = Path(__file__).parent / "fixtures"
LIVE = json.loads((FIX / "live_workflow_definitions.json").read_text(encoding="utf-8"))
OLD = json.loads((FIX / "godrej_case_workflows.json").read_text(encoding="utf-8"))
ALL = [w for d in LIVE.values() for w in d["workflows"]] + OLD


def canon(v):
    return json.dumps(v, sort_keys=True)


def test_the_page_makes_the_same_boxes_as_the_server_and_gives_the_steps_back():
    steps = [w.get("steps") or [] for w in ALL]
    got = run_page(
        "const all = " + json.dumps(steps) + ";\n"
        "return { boxes: all.map(s => blToBoxes(s)), back: all.map(s => blFromBoxes(blToBoxes(s))) };",
        js_studio_form,
        js_builder,
    )
    for wf, s, boxes, back in zip(ALL, steps, got["boxes"], got["back"]):
        assert canon(boxes) == canon(bm.to_boxes(s)), wf["intent_key"]
        assert canon(back) == canon(s), wf["intent_key"]


def test_the_page_writes_new_ifs_as_the_server_would():
    boxes = [
        {"kind": "step", "step": {"op": "compute", "params": {}}},
        {
            "kind": "if",
            "rule": {"or": [{"field": "$fields.a", "exists": True}, {"field": "$fields.b", "equals": "x"}]},
            "yes": [
                {"kind": "step", "step": {"op": "notify.user", "params": {}}},
                {"kind": "if", "rule": {"field": "$fields.c", "gt": 3}, "yes": [{"kind": "step", "step": {"op": "compute", "params": {}}}], "no": []},
            ],
            "no": [{"kind": "step", "step": {"op": "db.insert_row", "params": {}}}],
        },
    ]
    got = run_page("return { steps: blFromBoxes(" + json.dumps(boxes) + ") };", js_studio_form, js_builder)
    assert canon(got["steps"]) == canon(bm.from_boxes(boxes))
    again = run_page("return { b: blToBoxes(" + json.dumps(got["steps"]) + ") };", js_studio_form, js_builder)
    assert canon(again["b"]) == canon(bm.to_boxes(got["steps"]))


def test_tokens_in_a_message_follow_the_server_rule():
    paths = ["$fields.note", "$case.title", "$user.name", "$inserted.cases.case_number", "NOW()", "plain"]
    got = run_page("return { t: " + json.dumps(paths) + ".map(tokenFor) };", js_studio_form)
    assert got["t"][:4] == [bm.token_for(p) for p in paths[:4]]
    assert got["t"][4:] == ["", ""]
