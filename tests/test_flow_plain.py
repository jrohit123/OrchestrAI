"""Build with AI: the plain flow the admin edits, its check, and the engine steps it becomes (flow_plain.py, flow_ops.py)."""

import asyncio

from app.services import flow_plain, step_catalog, step_interpreter

LISTS = {
    "booking": {
        "label": "Booking",
        "plural": "Bookings",
        "table_name": "bookings",
        "prefix": "BO",
        "fields": {
            "place": {"label": "Place", "kind": "choice"},
            "date": {"label": "Date", "kind": "date"},
            "time": {"label": "Time", "kind": "time"},
            "flat": {"label": "Flat", "kind": "text"},
        },
    }
}

BOOKING = {
    "start": {"type": "chat", "words": "book clubhouse, book hall"},
    "asks": [
        {"label": "Place", "q": "Which place?", "kind": "choice", "options": ["Clubhouse", "Party hall"]},
        {"label": "Date", "q": "Which date?", "kind": "date"},
        {"label": "Time", "q": "What time?", "kind": "time"},
    ],
    "steps": [
        {"a": "find", "list": "Bookings", "match": {"Place": "[Place]", "Date": "[Date]", "Time": "[Time]"}, "name": "Clash"},
        {"a": "if", "tests": [{"q": "Clash found", "op": "is", "value": "yes"}],
         "yes": [{"a": "say", "text": "Sorry, [Place] is taken then."}, {"a": "stop"}],
         "no": []},
        {"a": "save", "list": "Booking", "values": {"Place": "[Place]", "Date": "[Date]", "Time": "[Time]", "Flat": "[Flat]"}},
        {"a": "say", "text": "Booked [Place] on [Date]. Number [Booking number]."},
        {"a": "tell", "role": "Committee", "text": "New booking: [Place], flat [Flat]"},
    ],
}  # fmt: skip


def test_a_fitting_flow_has_no_problems():
    assert flow_plain.check(BOOKING, LISTS, roles={"committee"}) == []


def test_after_a_check_that_stops_on_one_side_the_other_side_carries_on():
    # "Booking number" comes after the check: the yes lane stops, so only the no lane goes on, and it is known there
    assert not [p for p in flow_plain.check(BOOKING, LISTS) if p["need"] == "Booking number"]


def test_a_value_nothing_gives_is_named():
    plain = {**BOOKING, "asks": BOOKING["asks"][:1]}  # Date and Time are no longer asked
    needs = {p["need"] for p in flow_plain.check(plain, LISTS, roles={"committee"})}
    assert {"Date", "Time"} <= needs


def test_unknown_lists_columns_and_roles_are_named():
    plain = {"asks": [], "steps": [
        {"a": "save", "list": "Parcels", "values": {}},
        {"a": "find", "list": "Bookings", "match": {"Colour": "red"}, "name": "X"},
        {"a": "tell", "role": "Watchmen", "text": "hi"},
    ]}  # fmt: skip
    texts = " ".join(p["text"] for p in flow_plain.check(plain, LISTS, roles={"committee"}))
    assert "no list called Parcels" in texts and "nothing called Colour" in texts and "no role called Watchmen" in texts


def test_the_compiled_steps_pass_the_step_checker():
    out = flow_plain.compile_flow(BOOKING, LISTS)
    schema = {"bookings": {"id", "org_id", "record_number", "place", "date", "time", "flat"}}
    res = step_catalog.validate_steps(out["steps"], schema=schema, entity_schema=out["entity_schema"])
    assert res["errors"] == []
    assert out["training_phrases"] == ["book clubhouse", "book hall"]
    assert out["entity_schema"]["place"]["enum"] == ["Clubhouse", "Party hall"]
    assert out["steps"][0]["op"] == "flow.my_flat"  # Flat is used, so it is found first


def test_an_if_becomes_one_decision_and_guards_on_it():
    out = flow_plain.compile_flow(BOOKING, LISTS)
    ops = [s["op"] for s in out["steps"]]
    assert ops.count("flow.decide") == 1
    lane = [s for s in out["steps"] if s.get("when")]
    assert lane and all(s["when"] == {"field": "$fields._if_1", "equals": "yes"} for s in lane)


def _run(steps: list, fields: dict) -> dict:
    user = {"org_id": "00000000-0000-0000-0000-000000000001", "user_id": "u1", "user_name": "Priya", "role": "member", "source_key": "test"}
    wf = {"name": "T", "intent_key": "t", "steps": steps}
    return asyncio.run(step_interpreter.run_workflow_steps(wf, fields, user, "123", dry_run=True))


def test_an_if_is_decided_once_even_if_a_lane_changes_the_value():
    plain = {"asks": [{"label": "Size", "q": "?", "kind": "text"}], "steps": [
        {"a": "if", "tests": [{"q": "Size", "op": "is", "value": "big"}],
         "yes": [{"a": "set", "name": "Size", "value": "small"}, {"a": "say", "text": "yes lane"}],
         "no": [{"a": "say", "text": "no lane"}]},
    ]}  # fmt: skip
    res = _run(flow_plain.compile_flow(plain, {})["steps"], {"size": "big"})
    assert "Reply: yes lane" in res["preview"] and "Reply: no lane" not in res["preview"]


def test_stop_ends_the_flow():
    plain = {"asks": [], "steps": [{"a": "say", "text": "one"}, {"a": "stop"}, {"a": "say", "text": "two"}]}
    res = _run(flow_plain.compile_flow(plain, {})["steps"], {})
    assert res["preview"] == ["Reply: one"]


def test_a_set_value_fills_in_answers():
    plain = {"asks": [{"label": "Wing", "q": "?", "kind": "text"}], "steps": [
        {"a": "set", "name": "Where", "value": "Wing [Wing]"}, {"a": "say", "text": "At [Where]"}]}  # fmt: skip
    res = _run(flow_plain.compile_flow(plain, {})["steps"], {"wing": "B"})
    assert res["preview"] == ["Reply: At Wing B"]


def test_the_old_editor_is_not_offered_the_builder_steps():
    assert {"flow.decide", "flow.say", "flow.stop"} <= step_catalog.BUILDER_OPS


def test_checks_before_the_questions_are_kept_apart_and_also_start_the_steps():
    plain = {
        "before": [
            {"a": "find", "list": "Bookings", "match": {"Flat": "[Flat]"}, "name": "Old booking"},
            {"a": "if", "tests": [{"q": "Old booking found", "op": "is", "value": "yes"}],
             "yes": [{"a": "say", "text": "You have one already."}, {"a": "stop"}], "no": []},
        ],
        "asks": BOOKING["asks"],
        "steps": [{"a": "say", "text": "Booked [Place]"}],
    }  # fmt: skip
    assert flow_plain.check(plain, LISTS) == []
    out = flow_plain.compile_flow(plain, LISTS)
    pre_ops = [s["op"] for s in out["precheck"]]
    assert pre_ops == ["flow.my_flat", "flow.lookup", "flow.decide", "flow.say", "flow.stop"]
    assert [s["op"] for s in out["steps"]][:5] == pre_ops  # the same checks start the steps (a WhatsApp form skips the chat)


def test_a_check_before_the_questions_cannot_use_an_answer():
    plain = {"before": [{"a": "say", "text": "Hi [Place]"}], "asks": BOOKING["asks"], "steps": []}
    assert [p["need"] for p in flow_plain.check(plain, LISTS)] == ["Place"]


def test_a_stopping_precheck_tells_what_was_said():
    plain = {"before": [{"a": "if", "tests": [{"q": "Role", "op": "is", "value": "tenant"}],
                         "yes": [{"a": "say", "text": "Only owners can book."}, {"a": "stop"}], "no": []}],
             "asks": [], "steps": []}  # fmt: skip
    pre = flow_plain.compile_flow(plain, {})["precheck"]
    user = {"org_id": "00000000-0000-0000-0000-000000000001", "user_id": "u1", "user_name": "Priya", "role": "tenant", "source_key": "test"}
    res = asyncio.run(step_interpreter.run_workflow_steps({"name": "T", "intent_key": "t", "steps": pre}, {}, user, "1", dry_run=True))
    assert res["stopped"] and res["said"] == ["Only owners can book."]


def test_the_card_gets_what_each_step_needs_gives_and_knows():
    problems, info = flow_plain.analyse(BOOKING, LISTS, roles={"committee"})
    assert problems == []
    find = info["steps.0"]
    assert {"n": "Place", "ok": True} in find["needs"] and find["gives"] == ["Clash found"]
    assert "Clash found" in info["steps.1"]["known"]  # the check sees what the step before it gave
    assert "Booking number" in [x["n"] for x in info["steps.3"]["needs"]]
