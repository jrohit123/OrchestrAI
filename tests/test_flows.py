"""WhatsApp Flows (the menu and the complaint form as panels): what is sent from the database, what comes back, and
the rule that anything not set up or failing falls back to the list menu and the chat questions. No database or
network: the few things a Flow reads are replaced."""

import asyncio
import json
from typing import ClassVar

from app.services import flows

USER = {"org_id": "o1", "source_key": "godrej", "user_id": "u1"}


def run(coro):
    return asyncio.run(coro)


def workflows(*rows):
    async def get(org_id, user):
        return [dict(r) for r in rows]

    return get


def wf(key, name, section, desc="", slash=None):
    return {
        "intent_key": key,
        "name": name,
        "menu_section": section,
        "command_description": desc,
        "slash_command": slash,
    }


# ------------------------------------------------------------ what is shown


def test_the_menu_groups_what_the_role_may_use_into_sections_with_their_workflows(
    monkeypatch,
):
    monkeypatch.setattr(
        flows.menu,
        "get_menu_workflows",
        workflows(
            wf("file_a_complaint", "File a complaint", "create", "Report a problem"),
            wf(
                "view_all_cases",
                "All Tickets",
                "reports",
                "Every case in the society and more",
            ),
            wf("my_cases", "My Open Tickets", "reports", "Cases you are on"),
        ),
    )
    screen, data = run(flows.menu_data(USER))
    assert screen == "MENU"
    titles = [i["main-content"]["title"] for i in data["items"]]
    assert titles == [
        "Reports",
        "Create",
    ]  # the order the list menu has always had, no pictures
    reports = data["items"][0]
    assert reports["main-content"]["description"] == "2 options"
    inner = reports["on-click-action"]["payload"]["items"]
    assert [i["id"] for i in inner] == ["view_all_cases", "my_cases"]
    assert inner[0]["on-click-action"]["payload"] == {"workflow": "view_all_cases"}
    assert len(inner[0]["main-content"]["description"]) <= flows.DESCRIPTION_MAX


def test_a_person_with_one_section_goes_straight_to_its_workflows(monkeypatch):
    monkeypatch.setattr(
        flows.menu,
        "get_menu_workflows",
        workflows(wf("file_a_complaint", "File a complaint", "create")),
    )
    screen, data = run(flows.menu_data(USER))
    assert screen == "SECTION" and data["items"][0]["id"] == "file_a_complaint"


def test_nothing_to_show_means_no_panel(monkeypatch):
    monkeypatch.setattr(flows.menu, "get_menu_workflows", workflows())
    assert run(flows.menu_data(USER)) is None


def test_long_names_are_cut_and_a_section_shows_at_most_twenty(monkeypatch):
    many = [
        wf(f"w{i:02d}", "A very long workflow name that does not fit at all", "other")
        for i in range(25)
    ]
    monkeypatch.setattr(
        flows.menu, "get_menu_workflows", workflows(*many, wf("x", "X", "create"))
    )
    _screen, data = run(flows.menu_data(USER))
    other = next(i for i in data["items"] if i["id"] == "other")
    inner = other["on-click-action"]["payload"]["items"]
    assert len(inner) == flows.MAX_ITEMS
    assert all(len(i["main-content"]["title"]) <= flows.TITLE_MAX for i in inner)


def test_a_section_that_is_not_one_of_the_usual_three_still_appears(monkeypatch):
    monkeypatch.setattr(
        flows.menu,
        "get_menu_workflows",
        workflows(wf("a", "A", "create"), wf("b", "B", "finance")),
    )
    _screen, data = run(flows.menu_data(USER))
    assert [i["id"] for i in data["items"]] == ["create", "finance"]


# ------------------------------------------------------------ set up or not


def test_a_flow_is_used_only_when_it_is_switched_on_and_has_an_id():
    on = {"whatsapp_flows": {"menu": {"enabled": True, "flow_id": " 123 "}}}
    assert flows.flow_of(on, "menu")["flow_id"] == "123"
    assert (
        flows.flow_of(
            {"whatsapp_flows": {"menu": {"enabled": False, "flow_id": "1"}}}, "menu"
        )
        is None
    )
    assert (
        flows.flow_of({"whatsapp_flows": {"menu": {"enabled": True}}}, "menu") is None
    )
    assert (
        flows.flow_of(
            {"whatsapp_flows": {"menu": {"enabled": "yes", "flow_id": "1"}}}, "menu"
        )
        is None
    )
    assert (
        flows.flow_of({}, "menu") is None and flows.flow_of(None, "complaint") is None
    )


def settings_are(monkeypatch, settings):
    async def org_settings(source_key, org_id):
        return settings

    monkeypatch.setattr(flows.config_store, "org_settings", org_settings)


def sent_flows(monkeypatch, fail=False):
    sent = []

    async def send_flow(to, **kw):
        if fail:
            raise RuntimeError("Meta refused")
        sent.append({"to": to, **kw})
        return {}

    monkeypatch.setattr(flows.whatsapp, "send_flow", send_flow)
    return sent


async def say(source_key, key, **_):
    return {"flow.menu_button": "Open menu"}.get(key, key)


MENU_ON = {"whatsapp_flows": {"menu": {"enabled": True, "flow_id": "123"}}}


def test_the_menu_panel_is_sent_with_the_persons_own_data(monkeypatch):
    monkeypatch.setattr(
        flows.menu,
        "get_menu_workflows",
        workflows(wf("a", "A", "create"), wf("b", "B", "reports")),
    )
    settings_are(monkeypatch, MENU_ON)
    sent = sent_flows(monkeypatch)
    assert run(flows.send_menu(USER, "+919000000001", "Pick one", say)) is True
    one = sent[0]
    assert (
        one["flow_id"] == "123"
        and one["screen"] == "MENU"
        and one["body"] == "Pick one"
    )
    assert (
        one["cta"] == "Open menu"
        and one["flow_token"].startswith("menu:")
        and one["draft"] is False
    )
    assert len(one["data"]["items"]) == 2


def test_a_draft_flow_can_be_tried_before_it_is_published(monkeypatch):
    monkeypatch.setattr(
        flows.menu, "get_menu_workflows", workflows(wf("a", "A", "create"))
    )
    settings_are(
        monkeypatch,
        {
            "whatsapp_flows": {
                "menu": {"enabled": True, "flow_id": "1", "mode": "draft"}
            }
        },
    )
    sent = sent_flows(monkeypatch)
    run(flows.send_menu(USER, "+919000000001", "x", say))
    assert sent[0]["draft"] is True


def test_the_list_menu_is_the_fallback_when_it_is_off_unreachable_or_failing(
    monkeypatch,
):
    monkeypatch.setattr(
        flows.menu, "get_menu_workflows", workflows(wf("a", "A", "create"))
    )
    sent = sent_flows(monkeypatch)
    settings_are(monkeypatch, {})
    assert run(flows.send_menu(USER, "+919000000001", "x", say)) is False  # not set up
    settings_are(monkeypatch, MENU_ON)
    assert (
        run(flows.send_menu(USER, "tg:55", "x", say)) is False
    )  # Telegram has its own menu
    assert sent == []
    sent_flows(monkeypatch, fail=True)
    assert (
        run(flows.send_menu(USER, "+919000000001", "x", say)) is False
    )  # Meta refused


# ------------------------------------------------------------ the complaint form

SCHEMA = {
    "title": {"label": "Problem"},
    "location": {"label": "Where"},
    "priority": {"label": "Priority", "enum": ["urgent", "high", "medium", "low"]},
}
FORM_ON = {
    "whatsapp_flows": {
        "complaint": {"enabled": True, "flow_id": "456", "workflow": "file_a_complaint"}
    }
}


def form_world(monkeypatch, settings=FORM_ON):
    settings_are(monkeypatch, settings)

    async def schema(user, intent_key):
        return SCHEMA

    async def fetch_all(sql, *a, **k):
        return [
            {"key": "plumbing", "label": "Plumbing"},
            {"key": "lift", "label": "Lift issues"},
        ]

    monkeypatch.setattr(flows, "_complaint_schema", schema)
    monkeypatch.setattr(flows, "fetch_all", fetch_all)
    return sent_flows(monkeypatch)


def test_a_bare_tap_on_the_complaint_workflow_opens_the_form_with_the_workflows_own_choices(
    monkeypatch,
):
    sent = form_world(monkeypatch)
    assert (
        run(flows.start_form(USER, "+919000000001", "file_a_complaint", None, say))
        is True
    )
    one = sent[0]
    assert one["screen"] == "COMPLAINT" and one["flow_token"].startswith("complaint:")
    assert [p["id"] for p in one["data"]["priorities"]] == [
        "urgent",
        "high",
        "medium",
        "low",
    ]
    assert [c["id"] for c in one["data"]["categories"]] == ["plumbing", "lift"]


def test_the_form_is_not_used_when_words_came_with_the_command_or_for_other_workflows_or_other_chats(
    monkeypatch,
):
    sent = form_world(monkeypatch)
    assert (
        run(
            flows.start_form(
                USER, "+919000000001", "file_a_complaint", "water leak", say
            )
        )
        is False
    )
    assert (
        run(flows.start_form(USER, "+919000000001", "view_all_cases", None, say))
        is False
    )
    assert run(flows.start_form(USER, "tg:55", "file_a_complaint", None, say)) is False
    settings_are(monkeypatch, {})
    assert (
        run(flows.start_form(USER, "+919000000001", "file_a_complaint", None, say))
        is False
    )
    assert sent == []


def test_a_failing_form_send_falls_back_to_the_chat_questions(monkeypatch):
    form_world(monkeypatch)
    sent_flows(monkeypatch, fail=True)
    assert (
        run(flows.start_form(USER, "+919000000001", "file_a_complaint", None, say))
        is False
    )


def answer(**data):
    return {
        "nfm_reply": {"name": "flow", "body": "Sent", "response_json": json.dumps(data)}
    }


def test_a_chosen_workflow_is_its_key_and_anything_odd_is_left_alone():
    assert run(flows.read_answer("+91", answer(workflow="view_all_cases"))) == (
        "view_all_cases",
        [],
        None,
    )
    assert run(flows.read_answer("+91", answer(workflow="x; drop table cases"))) == (
        "",
        [],
        None,
    )
    assert run(flows.read_answer("+91", answer(other="x"))) == ("", [], None)
    assert run(
        flows.read_answer("+91", {"nfm_reply": {"response_json": "not json"}})
    ) == ("", [], None)
    assert run(flows.read_answer("+91", {"nfm_reply": {"response_json": "[1]"}})) == (
        "",
        [],
        None,
    )


def test_a_filled_form_is_the_complaint_workflows_key_with_its_answers_and_photos(
    monkeypatch,
):
    form_world(monkeypatch)

    async def resolve_identity(phone):
        return USER

    monkeypatch.setattr("app.services.identity.resolve_identity", resolve_identity)
    data = {
        "flow_token": "complaint:abc",
        "location": "T5-901",
        "problem": "Leakage in bathroom",
        "category": "plumbing",
        "priority": "urgent",
        "photos": [{"id": "m1", "mime_type": "image/jpeg"}, {"id": "m2"}],
    }
    text, refs, form = run(flows.read_answer("+919000000001", answer(**data)))
    assert text == "file_a_complaint" and refs == ["wa:m1", "wa:m2"]
    assert form == {"data": data}


def test_an_empty_form_or_an_unknown_person_is_left_alone(monkeypatch):
    form_world(monkeypatch)

    async def resolve_identity(phone):
        return USER

    monkeypatch.setattr("app.services.identity.resolve_identity", resolve_identity)
    assert run(flows.read_answer("+91", answer(location="", problem=""))) == (
        "",
        [],
        None,
    )

    async def nobody(phone):
        return None

    monkeypatch.setattr("app.services.identity.resolve_identity", nobody)
    assert run(flows.read_answer("+91", answer(location="T5", problem="Leak"))) == (
        "",
        [],
        None,
    )


# ------------------------------------------------------------ the form's answers go straight into the draft


class FakeAgent:
    """What use_form needs of the chat bot's own code: reading a workflow's schema and saving the checked draft."""

    seen: ClassVar[dict] = {}

    @staticmethod
    def _parse_jsonb(value, default):
        return value if value is not None else default

    @staticmethod
    async def _confirm_by_code(user, wf, fields, display, *, message, history, limit):
        FakeAgent.seen = {"fields": fields, "message": message, "limit": limit}
        return (
            "SUMMARY",
            (history or []) + [{"role": "assistant", "content": "SUMMARY"}],
            {
                "pending_action": {
                    "intent_key": wf["intent_key"],
                    "fields": fields,
                    "stage": "awaiting_confirmation",
                },
                "_buttons": [{"id": "yes"}],
            },
        )


def use_form_world(monkeypatch, wf_row="default"):
    sent, saved, closed = [], {}, []
    form_world(monkeypatch)
    row = {
        "intent_key": "file_a_complaint",
        "name": "File a complaint",
        "entity_schema": {**SCHEMA, "description": {}},
    }

    async def fetch_one(sql, *a, **k):
        if "FROM workflows" in sql:
            return None if wf_row is None else row
        return {"label": "Plumbing"}

    async def send_text(to, text):
        sent.append((to, text))

    async def set_session(session_id, data, ttl=600):
        saved.update({"id": session_id, "data": dict(data), "ttl": ttl})

    async def close_draft(org_id, user_id, stage, source_key=None):
        closed.append(stage)

    monkeypatch.setattr(flows, "fetch_one", fetch_one)
    monkeypatch.setattr("app.services.messaging.send_text", send_text)
    monkeypatch.setattr("app.redis_client.set_session", set_session)
    monkeypatch.setattr("app.services.draft_store.close_draft", close_draft)
    monkeypatch.setattr(
        "app.services.agent._parse_jsonb", FakeAgent._parse_jsonb, raising=False
    )
    monkeypatch.setattr(
        "app.services.agent._confirm_by_code", FakeAgent._confirm_by_code, raising=False
    )
    return sent, saved, closed


FORM = {
    "data": {
        "problem": "Leak",
        "location": "T5-901",
        "category": "plumbing",
        "priority": "urgent",
    }
}


def test_a_filled_form_is_saved_as_a_draft_by_code_and_the_summary_is_sent(monkeypatch):
    sent, saved, closed = use_form_world(monkeypatch)
    done, details = run(
        flows.use_form(
            {**USER, "context_message_limit": 5},
            "+919000000001",
            FORM,
            {},
            "o1:+919000000001",
            600,
        )
    )
    assert done is True and details is None
    assert FakeAgent.seen["fields"] == {
        "title": "Leak",
        "location": "T5-901",
        "priority": "urgent",
        "description": "Category: Plumbing",
    }
    assert FakeAgent.seen["limit"] == 5
    assert sent == [("+919000000001", "SUMMARY")] and closed == [
        "cancelled"
    ]  # an old draft is dropped first
    assert (
        saved["data"]["pending_action"]["stage"] == "awaiting_confirmation"
        and "_buttons" not in saved["data"]
    )


def test_a_priority_the_workflow_does_not_know_is_left_out_and_a_missing_problem_hands_over_to_the_chat_bot(
    monkeypatch,
):
    use_form_world(monkeypatch)
    bad = {"data": {**FORM["data"], "priority": "whenever"}}
    run(flows.use_form(USER, "+91", bad, {}, "s", 600))
    assert "priority" not in FakeAgent.seen["fields"]
    sent, _saved, _closed = use_form_world(monkeypatch)
    no_problem = {"data": {"location": "T5-901", "priority": "low"}}
    done, details = run(flows.use_form(USER, "+91", no_problem, {}, "s", 600))
    assert done is False and "Where: T5-901" in details and sent == []


def test_when_the_workflow_cannot_be_found_the_chat_bot_gets_the_details(monkeypatch):
    use_form_world(monkeypatch, wf_row=None)
    done, details = run(flows.use_form(USER, "+91", FORM, {}, "s", 600))
    assert (
        done is False and "Problem: Leak" in details and "Category: Plumbing" in details
    )


def test_the_menu_groups_flows_by_use_case_and_only_shows_switched_on_ones(monkeypatch):
    """With use cases (Build > Use cases), the groups are the use cases with their flows; a flow filed under none
    stays in its section after them. get_menu_workflows already leaves out switched-off and not-allowed flows."""
    tickets, visitors = (
        "11111111-0000-0000-0000-000000000001",
        "22222222-0000-0000-0000-000000000002",
    )
    monkeypatch.setattr(
        flows.menu,
        "get_menu_workflows",
        workflows(
            {
                **wf("file_a_complaint", "File a complaint", "create"),
                "usecase_id": tickets,
            },
            {**wf("my_cases", "My Open Tickets", "reports"), "usecase_id": tickets},
            {
                **wf("preapprove_visitor", "Pre-approve a visitor", "create"),
                "usecase_id": visitors,
            },
            {**wf("general_read", "Ask anything", "reports"), "usecase_id": None},
        ),
    )

    async def fetch_all(query, *args, **kw):
        assert "FROM usecases" in query
        return [
            {"id": tickets, "name": "Tickets", "icon": "🎫"},
            {
                "id": "33333333-0000-0000-0000-000000000003",
                "name": "Bookings",
                "icon": "📅",
            },  # nothing on: not shown
            {"id": visitors, "name": "Visitors", "icon": "🚪"},
        ]

    monkeypatch.setattr(flows.menu, "fetch_all", fetch_all)
    groups = run(flows.menu.menu_groups("o1", USER))
    assert [g["title"] for g in groups] == ["🎫 Tickets", "🚪 Visitors", "📊 Reports"]
    assert [w["intent_key"] for w in groups[0]["flows"]] == [
        "file_a_complaint",
        "my_cases",
    ]
    screen, data = run(flows.menu_data(USER))
    assert screen == "MENU" and [i["main-content"]["title"] for i in data["items"]] == [
        "Tickets",
        "Visitors",
        "Reports",
    ]
    sections = run(flows.menu.build_menu_sections("o1", USER))
    assert [s["title"] for s in sections] == ["🎫 Tickets", "🚪 Visitors", "📊 Reports"]
