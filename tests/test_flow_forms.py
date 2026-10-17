"""WhatsApp forms for any workflow (flow_forms.py): a form is sent only for a workflow that has one in the settings and
only to someone allowed to use it, its lists are filled from data, its answer is told apart from a tap on the menu
panel, and the answer becomes the workflow's own fields. Nothing is sent: the sender and the database are replaced."""

import asyncio
import json

from app.services import flow_forms, flows

SETTINGS = {
    "whatsapp_flows": {
        "time_slots": ["07:00", "18:30"],
        "forms": {
            "preapprove_visitor": {
                "flow_id": "2192",
                "button": "Approve a visitor",
                "screen": "VISITOR",
                "data": {"times": "times", "today": "today"},
                "join": {"visit_time": ["visit_date", "visit_hour"]},
            },
            "book_facility": {
                "flow_id": "994",
                "screen": "BOOKING",
                "data": {"facilities": "choices:facility"},
            },
            "send_announcement": {
                "flow_id": "2023",
                "screen": "ANNOUNCEMENT",
                "data": {"audiences": "ready_choices"},
                "enabled": False,
            },
        },
    }
}
WORKFLOWS = {
    "preapprove_visitor": {
        "intent_key": "preapprove_visitor",
        "name": "Pre-approve a visitor",
        "description": "Lets the gate know.",
        "entity_schema": json.dumps(
            {"visitor_name": {"label": "Visitor"}, "visit_time": {"label": "When"}}
        ),
    },
    "book_facility": {
        "intent_key": "book_facility",
        "name": "Book a facility",
        "description": "",
        "entity_schema": {
            "facility": {"enum": ["Clubhouse", "Party hall"]},
            "booking_date": {},
            "booking_time": {},
        },
    },
}
USER = {
    "org_id": "o",
    "source_key": "s",
    "user_id": "u",
    "permissions": ["preapprove_visitor", "book_facility", "send_announcement"],
}


def _world(monkeypatch):
    sent = []

    async def settings(*a):
        return SETTINGS

    async def workflow(user, key):
        return WORKFLOWS.get(key)

    async def send_flow(to, **kw):
        sent.append(kw)

    monkeypatch.setattr(flow_forms.config_store, "org_settings", settings)
    monkeypatch.setattr(flow_forms, "_workflow", workflow)
    monkeypatch.setattr(flow_forms.whatsapp, "send_flow", send_flow)
    return sent


def test_a_form_is_sent_only_for_a_workflow_that_has_one_and_to_someone_allowed(
    monkeypatch,
):
    sent = _world(monkeypatch)
    run = lambda user, text, args=None: asyncio.run(
        flow_forms.start(user, "+919000000001", text, args)
    )
    assert run(USER, "preapprove_visitor")
    kw = sent[-1]
    assert (
        kw["flow_id"] == "2192"
        and kw["screen"] == "VISITOR"
        and kw["cta"] == "Approve a visitor"
    )
    assert kw["data"]["times"] == [
        {"id": "07:00", "title": "7:00 am"},
        {"id": "18:30", "title": "6:30 pm"},
    ]
    assert len(kw["data"]["today"]) == 10 and kw["flow_token"].startswith(
        "form:preapprove_visitor:"
    )
    assert run(USER, "book_facility") and sent[-1]["data"]["facilities"][1] == {
        "id": "Party hall",
        "title": "Party hall",
    }
    assert not run(
        {**USER, "permissions": []}, "preapprove_visitor"
    )  # not allowed: the questions as before
    assert not run(USER, "send_announcement")  # switched off in the settings
    assert not run(
        USER, "file_a_complaint"
    )  # no form of its own here (the complaint form is flows.py's)
    assert not run(
        USER, "preapprove_visitor", "Ramesh tomorrow"
    )  # typed details: no form
    assert not asyncio.run(
        flow_forms.start(USER, "tg:5", "preapprove_visitor", None)
    )  # Telegram has no forms
    assert len(sent) == 2


def test_a_filled_form_is_told_apart_from_a_menu_tap():
    assert not flow_forms.is_form_answer(
        {"workflow": "my_cases", "flow_token": "menu:abc"}
    )
    assert flow_forms.is_form_answer(
        {"workflow": "book_facility", "facility": "Clubhouse", "flow_token": "x"}
    )
    assert flow_forms.is_form_answer({"flow_token": "form:book_facility:1"})
    answer = {
        "nfm_reply": {
            "response_json": json.dumps(
                {
                    "workflow": "book_facility",
                    "facility": "Clubhouse",
                    "flow_token": "form:book_facility:1",
                }
            )
        }
    }
    text, refs, form = asyncio.run(flows.read_answer("+919000000001", answer))
    assert (
        text == "book_facility"
        and form["generic"]
        and form["data"]["facility"] == "Clubhouse"
    )
    tap = {
        "nfm_reply": {
            "response_json": json.dumps(
                {"workflow": "my_cases", "flow_token": "menu:abc"}
            )
        }
    }
    assert asyncio.run(flows.read_answer("+919000000001", tap)) == (
        "my_cases",
        [],
        None,
    )


def test_the_answers_become_the_workflows_own_fields(monkeypatch):
    _world(monkeypatch)
    data = {
        "workflow": "preapprove_visitor",
        "visitor_name": "Ramesh",
        "visit_date": "2026-10-18",
        "visit_hour": "11:00",
        "flow_token": "form:preapprove_visitor:1",
    }
    key, fields, details, wf = asyncio.run(flow_forms.fields_of(USER, data))
    assert key == "preapprove_visitor" and wf
    assert fields == {"visitor_name": "Ramesh", "visit_time": "2026-10-18 11:00"}
    assert details == "Visitor: Ramesh\nWhen: 2026-10-18 11:00"
    key, fields, _, wf = asyncio.run(
        flow_forms.fields_of(USER, {"workflow": "drop_all_tables", "x": "1"})
    )
    assert (
        wf is None and fields == {}
    )  # a workflow with no form in the settings is never filled from a form
