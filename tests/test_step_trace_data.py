"""What a rehearsal ("Try it" / "Test this step") tells the step window about each step: the record a
look-up found, the values a save would write, the message that would go out. Private columns are
hidden, a problem in showing the data never stops the rehearsal, and real runs are untouched."""

import asyncio
import datetime
import uuid

import pytest

from app.services import step_interpreter as si
from app.services.step_catalog import validate_steps


def run(coro):
    return asyncio.run(coro)


def rehearsal(**extra):
    ctx = {
        "dry_run": True,
        "trace": [],
        "fields": {"case_no": "CS-26-10-0042", "note": "Lift is still not working"},
        "computed": {},
        "generated": {},
        "inserted": {},
        "user": {"user_name": "Asha", "role": "manager"},
        "org_id": "o1",
        "source_key": "alpha",
        "workflow": {},
    }
    ctx.update(extra)
    return ctx


def test_private_columns_are_hidden_and_the_organisation_id_is_left_out():
    got = si._tidy_data(
        {
            "name": "Meera",
            "phone": "+919800000001",
            "assignee_phone": "+919800000002",
            "Email": "m@example.in",
            "api_token": "abc",
            "org_id": "o1",
            "config": {"k": 1},
            "status": "open",
            "count": 3,
            "ok": True,
            "gone": None,
        }
    )
    assert got == {
        "name": "Meera",
        "phone": "(hidden)",
        "assignee_phone": "(hidden)",
        "Email": "(hidden)",
        "api_token": "(hidden)",
        "config": "(hidden)",
        "status": "open",
        "count": 3,
        "ok": True,
        "gone": None,
    }


def test_values_are_short_plain_and_json_safe():
    got = si._tidy_data(
        {
            "long": "x" * 500,
            "tags": ["a", "b"],
            "id": uuid.UUID("7e1c0000-0000-4000-8000-000000000000"),
            "at": datetime.datetime(2026, 10, 6, 12, 0, tzinfo=datetime.timezone.utc),
        }
    )
    assert len(got["long"]) == 301 and got["long"].endswith("…")
    assert got["tags"] == '["a", "b"]'
    assert got["id"] == "7e1c0000…"
    assert got["at"] == "6 Oct, 5:30 pm"


def test_nothing_comes_out_when_there_is_nothing_to_show():
    assert si._tidy_data(None) is None
    assert si._tidy_data({}) is None
    assert si._tidy_data({"org_id": "o1"}) is None
    assert len(si._tidy_data({f"k{i}": i for i in range(100)})) == 40


def test_a_look_up_reports_the_record_it_found():
    async def find(params, ctx):
        ctx["case"] = {
            "case_number": "CS-26-10-0042",
            "status": "open",
            "complainant_phone": "+919800000003",
        }
        return ctx

    step = {
        "op": "resolve_entity",
        "params": {"table": "cases", "into": "case", "name_from": "$fields.case_no"},
    }
    ctx = rehearsal()
    run(si._run_op("resolve_entity", find, step, ctx))
    line = ctx["trace"][0]
    assert line["status"] == "ran"
    assert line["data"] == {
        "case_number": "CS-26-10-0042",
        "status": "open",
        "complainant_phone": "(hidden)",
    }


def test_a_value_worked_out_is_reported_by_name():
    async def work_out(params, ctx):
        ctx["fields"]["due"] = "2026-10-08"
        return ctx

    step = {"op": "derive_field", "params": {"field": "due", "expr": "x"}}
    ctx = rehearsal()
    run(si._run_op("derive_field", work_out, step, ctx))
    assert ctx["trace"][0]["data"] == {"due": "2026-10-08"}


def test_a_save_reports_what_it_would_write_and_never_runs():
    async def must_not_run(params, ctx):
        raise AssertionError("a rehearsal must not save anything")

    step = {
        "op": "db.insert_row",
        "params": {
            "table": "case_notes",
            "values": {"note": "$fields.note", "by": "$user.name", "kind": "note"},
        },
    }
    ctx = rehearsal()
    run(si._run_op("db.insert_row", must_not_run, step, ctx))
    line = ctx["trace"][0]
    assert line["status"] == "would"
    assert line["data"] == {
        "note": "Lift is still not working",
        "by": "Asha",
        "kind": "note",
    }


def test_a_change_reports_the_values_it_would_set():
    async def must_not_run(params, ctx):
        raise AssertionError("a rehearsal must not change anything")

    step = {
        "op": "db.update_row",
        "params": {"table": "cases", "set": {"status": "closed"}, "where": {}},
    }
    ctx = rehearsal()
    run(si._run_op("db.update_row", must_not_run, step, ctx))
    assert ctx["trace"][0]["data"] == {"status": "closed"}


def test_a_message_reports_its_text_and_only_the_end_of_the_number():
    async def must_not_run(params, ctx):
        raise AssertionError("a rehearsal must not message anyone")

    step = {
        "op": "notify.user",
        "params": {
            "to": "$person.phone",
            "message_template": "New note on {case_no}: {note}",
        },
    }
    ctx = rehearsal(person={"phone": "+919800001234"})
    run(si._run_op("notify.user", must_not_run, step, ctx))
    assert ctx["trace"][0]["data"] == {
        "to": "••••1234",
        "message": "New note on CS-26-10-0042: Lift is still not working",
    }
    ctx = rehearsal(person={})
    run(si._run_op("notify.user", must_not_run, step, ctx))
    assert ctx["trace"][0]["data"]["to"] == "no phone number on file"


def test_a_problem_in_showing_the_data_never_stops_the_rehearsal(monkeypatch):
    def boom(values):
        raise RuntimeError("the display broke")

    monkeypatch.setattr(si, "_tidy_data", boom)

    async def find(params, ctx):
        ctx["case"] = {"status": "open"}
        return ctx

    step = {"op": "resolve_entity", "params": {"table": "cases", "into": "case"}}
    ctx = rehearsal()
    run(si._run_op("resolve_entity", find, step, ctx))
    assert ctx["trace"][0]["status"] == "ran" and "data" not in ctx["trace"][0]


def test_a_real_run_does_none_of_this():
    seen = []

    async def op(params, ctx):
        seen.append("ran")
        return ctx

    ctx = {"dry_run": False, "trace": None, "fields": {}}
    got = run(si._run_op("derive_field", op, {"op": "derive_field", "params": {}}, ctx))
    assert got is ctx and seen == ["ran"] and ctx["trace"] is None


def test_the_message_of_a_step_is_the_same_text_the_real_step_sends(monkeypatch):
    sent = []

    async def send_text(to, text):
        sent.append((to, text))

    async def send_buttons(to, body, buttons):
        # a WhatsApp person who wrote today gets the text with a "Got it" button
        sent.append((to, body))

    async def door_open(*args, **kwargs):
        # (a person who did not write in the last 24 hours gets it by email: see reach.py)
        return True

    from app.services import messaging, reach

    monkeypatch.setattr(messaging, "send_text", send_text)
    monkeypatch.setattr(messaging, "send_buttons", send_buttons)
    monkeypatch.setattr(reach, "door_open", door_open)
    params = {"to": "$person.phone", "message_template": "Hello {case_no}"}
    ctx = rehearsal(person={"phone": "+919800001234"})
    ctx["dry_run"] = False
    run(si._op_notify_user(params, ctx))
    assert sent == [("+919800001234", "Hello CS-26-10-0042")]
    assert si._notify_message(params, ctx) == "Hello CS-26-10-0042"


def test_the_picker_s_their_name_is_the_name_the_person_has():
    ctx = {"user": {"user_name": "Asha", "user_id": "u1"}}
    assert si._resolve_path(ctx, "$user.name") == "Asha"
    assert si._resolve_path(ctx, "$user.user_name") == "Asha"
    assert (
        si._resolve_path({"user": {"name": "B", "user_name": "A"}}, "$user.name") == "B"
    )
    assert si._resolve_path({"user": {}}, "$user.name") is None


def test_a_step_can_carry_a_name_and_a_note():
    schema = {"cases": {"id", "org_id", "case_no"}}
    steps = [
        {
            "op": "resolve_entity",
            "name": "Find the case",
            "note": "The number comes from what the person typed.",
            "params": {
                "table": "cases",
                "into": "case",
                "name_from": "$fields.case_no",
                "match_column": "case_no",
            },
        }
    ]
    got = validate_steps(
        steps, schema=schema, entity_schema={"case_no": {"type": "string"}}
    )
    assert got["errors"] == []


@pytest.mark.parametrize("op", ["resolve_entity", "case.add_parties"])
def test_a_choice_in_the_catalog_explains_each_option_in_one_line(op):
    from app.services.step_catalog import STEP_BY_OP

    choices = [p for p in STEP_BY_OP[op]["params"] if p["kind"] == "choice"]
    assert choices
    for p in choices:
        for option in p["options"]:
            assert len(option) == 3 and option[2].endswith(".")
