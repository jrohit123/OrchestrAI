"""The small engine additions the plain-words builder needs (2026-10-21):
- "or" and "not" in a step's guard (the builder's "Any one is true" and OTHERWISE lanes),
- {record.column} data inside a message,
- buttons under a plain message,
- ask_approval: "Get approval" that carries on after either answer,
- ai.ask: "Ask the AI" doing one job (write, pick one, pull out details).
Old flows are untouched: every addition is only used when a step asks for it."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.executor import workflow_executor as wx
from app.services import ai_step
from app.services import step_interpreter as si
from app.services.step_catalog import validate_steps


def run(coro):
    return asyncio.run(coro)


def ctx_with(**extra):
    ctx = {
        "fields": {"facility": "Clubhouse", "note": "hi"},
        "computed": {},
        "generated": {},
        "inserted": {},
        "user": {"user_id": "u1", "user_name": "Anuja", "role": "owner", "org_id": "o1"},
        "org_id": "o1",
        "source_key": "alpha",
        "workflow": {"intent_key": "book_facility", "name": "Book a facility"},
        "phone": "tg:100",
    }
    ctx.update(extra)
    return ctx


# ── guards ───────────────────────────────────────────────────────────────────

YES = {"field": "$fields.facility", "equals": "Clubhouse"}
NO = {"field": "$fields.facility", "equals": "Pool"}


@pytest.mark.parametrize(
    "when, expected",
    [
        ({"or": [NO, YES]}, True),
        ({"or": [NO, NO]}, False),
        ({"not": YES}, False),
        ({"not": NO}, True),
        ({"and": [YES, {"not": NO}]}, True),
        ({"and": [YES, {"or": [NO, {"not": YES}]}]}, False),
    ],
)
def test_or_and_not_in_a_guard(when, expected):
    assert si._step_enabled({"when": when}, ctx_with()) is expected


def test_the_old_guards_still_work():
    assert si._step_enabled({"when": {"and": [YES, {"field": "$fields.note", "exists": True}]}}, ctx_with())
    assert not si._step_enabled({"when": NO}, ctx_with())


def test_saving_checks_or_and_not_and_refuses_an_empty_one():
    ok = validate_steps([{"op": "compute", "params": {}, "when": {"or": [YES, {"not": NO}]}}], schema={}, entity_schema={"facility": {}})
    assert ok["errors"] == []
    bad = validate_steps([{"op": "compute", "params": {}, "when": {"or": []}}], schema={})
    assert bad["errors"]


# ── data in a message ────────────────────────────────────────────────────────


def test_record_columns_and_the_person_go_into_a_message():
    ctx = ctx_with(case={"title": "Lift stuck", "id": 1}, assignee={"name": "Suresh"})
    params = {"message_template": "{case.title} is with {assignee.name}. From {user.name} about {facility} ({case_title})."}
    assert si._notify_message(params, ctx) == "Lift stuck is with Suresh. From Anuja about Clubhouse (Lift stuck)."


def test_missing_data_reads_as_empty_and_braces_in_data_are_kept_as_text():
    ctx = ctx_with(case={"title": "Use {braces}"})
    assert si._notify_message({"message_template": "[{nothing.here}] {case.title}"}, ctx) == "[] Use {braces}"


def test_a_message_without_dotted_data_is_filled_as_before():
    assert si._notify_message({"message_template": "Hello {note}"}, ctx_with()) == "Hello hi"


def test_saved_rows_can_be_used_in_a_message():
    ctx = ctx_with(inserted={"cases": {"case_number": "CS-1"}})
    assert si.fill_dotted("No. {inserted.cases.case_number}", ctx) == "No. CS-1"


# ── buttons under a message ──────────────────────────────────────────────────


@pytest.fixture
def sent(monkeypatch):
    from app.services import messaging, reach

    out = []

    async def send_buttons(to, body, buttons):
        out.append(("buttons", to, body, buttons))

    async def deliver_text(to, text, **kw):
        out.append(("text", to, text))
        return {"status": "sent"}

    monkeypatch.setattr(messaging, "send_buttons", send_buttons)
    monkeypatch.setattr(reach, "deliver_text", deliver_text)
    return out


def test_buttons_go_under_a_message_on_telegram(sent):
    params = {"to": "$person.phone", "message_template": "Booked {facility}", "buttons": {"Cancel": "/cancel {facility}"}}
    run(si._op_notify_user(params, ctx_with(person={"phone": "tg:55"})))
    assert sent == [("buttons", "tg:55", "Booked Clubhouse", [{"id": "/cancel Clubhouse", "title": "Cancel"}])]


def test_whatsapp_gets_the_message_alone(sent):
    params = {"to": "$person.phone", "message_template": "Booked", "buttons": {"Cancel": "/cancel"}}
    run(si._op_notify_user(params, ctx_with(person={"phone": "+9198"})))
    assert sent == [("text", "+9198", "Booked")]


# ── ask_approval ─────────────────────────────────────────────────────────────


@pytest.fixture
def approval_world(monkeypatch):
    world = {"rows": [], "buttons": []}

    async def fetch_all(sql, *args, source_key=None):
        assert "r.name = $2" in sql
        return [{"id": "u2", "name": "Mr. Shah", "phone": "tg:2"}, {"id": "u1", "name": "Anuja", "phone": "tg:100"}]

    async def fetch_one(sql, *args, source_key=None):
        if sql.startswith("INSERT INTO pending_approvals"):
            world["rows"].append({"args": args, "context": json.loads(args[4])})
            return {"id": "p1"}
        if "FROM users WHERE org_id" in sql:
            return {"id": "u9", "name": "Rohit", "phone": args[1]}
        raise AssertionError(sql)

    async def say(ctx, key, **values):
        return f"[{key}] {values}"

    from app.services import messaging

    async def send_buttons(to, body, buttons):
        world["buttons"].append((to, body, buttons))

    monkeypatch.setattr(si, "fetch_all", fetch_all)
    monkeypatch.setattr(si, "fetch_one", fetch_one)
    monkeypatch.setattr(si, "_say", say)
    monkeypatch.setattr(messaging, "send_buttons", send_buttons)
    return world


def test_asking_a_role_sends_to_everyone_in_it_but_the_person_asking_and_waits(approval_world):
    params = {"role": "committee", "message": "{user.name} wants the {facility}", "into": "committee"}
    ctx = run(si._op_ask_approval(params, ctx_with(_step_index=2)))
    assert ctx["_halt"] == "awaiting_approval"
    assert "approval.waiting" in ctx["_halt_message"]
    assert [b[0] for b in approval_world["buttons"]] == ["tg:2"]
    to, body, buttons = approval_world["buttons"][0]
    assert body == "Anuja wants the Clubhouse"
    assert [b["id"] for b in buttons] == ["action:approve:p1", "action:reject:p1"]
    saved = approval_world["rows"][0]["context"]
    assert saved["mode"] == "answer" and saved["into"] == "committee"
    assert saved["approver_ids"] == ["u2"]
    assert saved["pending_action"]["resume_step"] == 3


def test_asking_one_person_found_earlier(approval_world):
    ctx = ctx_with(manager={"id": "u7", "name": "Rohit", "phone": "tg:7"})
    run(si._op_ask_approval({"approver": "$manager", "into": "ok"}, ctx))
    assert [b[0] for b in approval_world["buttons"]] == ["tg:7"]
    assert "approval.request_plain" in approval_world["buttons"][0][1]  # no wording given


def test_a_rehearsal_does_not_ask_and_carries_on_as_approved(approval_world):
    ctx = run(si._op_ask_approval({"role": "committee", "into": "c"}, ctx_with(dry_run=True)))
    assert not ctx.get("_halt") and approval_world["buttons"] == []
    assert ctx["fields"]["c"] == "Approve" and ctx["fields"]["c_by"] == "Mr. Shah"


def test_the_resumed_run_does_not_ask_again(approval_world):
    ctx = ctx_with()
    ctx["fields"]["c"] = "Reject"
    run(si._op_ask_approval({"role": "committee", "into": "c"}, ctx))
    assert approval_world["buttons"] == [] and not ctx.get("_halt")


def test_nobody_to_ask_is_said_in_plain_words(approval_world, monkeypatch):
    async def nobody(sql, *a, source_key=None):
        return []

    monkeypatch.setattr(si, "fetch_all", nobody)
    with pytest.raises(si.UserFacingStepError) as e:
        run(si._op_ask_approval({"role": "committee"}, ctx_with()))
    assert "approval.nobody" in str(e.value)


def test_a_building_block_cannot_wait_for_an_approval(approval_world):
    with pytest.raises(si.StepError):
        run(si._op_ask_approval({"role": "committee"}, ctx_with(_call_stack=["flow", "block"])))
    errors = validate_steps([{"op": "ask_approval", "params": {"role": "committee"}}], schema={}, kind="block")["errors"]
    assert any("cannot wait for an approval" in e for e in errors)


def test_after_the_approval_step_its_answer_is_known_to_the_checks():
    steps = [
        {"op": "ask_approval", "params": {"role": "committee", "into": "committee"}},
        {"op": "compute", "params": {}, "when": {"field": "$fields.committee", "equals": "Approve"}},
        {"op": "compute", "params": {}, "when": {"field": "$fields.committee_by", "exists": True}},
    ]
    assert validate_steps(steps, schema={})["warnings"] == []


@pytest.fixture
def answering(monkeypatch):
    seen = {"sent": [], "resumed": [], "decided": 0}
    context = {
        "mode": "answer",
        "into": "committee",
        "approver_ids": ["u2"],
        "pending_action": {"intent_key": "book_facility", "fields": {"facility": "Clubhouse"}, "resume_step": 3},
        "requester_id": "u1",
        "requester_phone": "tg:100",
    }

    async def fetch_one(sql, *args, source_key=None):
        if sql.lstrip().startswith("SELECT id, requester_id"):
            return {"id": "p1", "requester_id": "u1", "approver_role": "committee", "intent_key": "book_facility",
                    "context": json.dumps(context), "status": "pending", "gate_id": None, "level": None}
        if sql.startswith("UPDATE pending_approvals"):
            seen["decided"] += 1
            return {"id": "p1"} if seen["decided"] == 1 else None
        raise AssertionError(sql)

    async def execute(sql, *args, source_key=None):
        return None

    async def say(source_key, key, **values):
        return f"[{key}]"

    async def send_text(to, text):
        seen["sent"].append((to, text))

    async def resolve_identity(phone):
        return {"user_id": "u1", "org_id": "o1", "source_key": "alpha", "permissions": ["book_facility"]}

    async def execute_pending_action(pending_action, user, phone=None, **kw):
        seen["resumed"].append(pending_action)
        return {"success": True, "message": "Booked."}

    from app.services import action_executor, identity

    monkeypatch.setattr(wx, "fetch_one", fetch_one)
    monkeypatch.setattr(wx, "execute", execute)
    monkeypatch.setattr(wx, "say", say)
    monkeypatch.setattr(wx, "send_text", send_text)
    monkeypatch.setattr(identity, "resolve_identity", resolve_identity)
    monkeypatch.setattr(action_executor, "execute_pending_action", execute_pending_action)
    return seen


SHAH = {"user_id": "u2", "user_name": "Mr. Shah", "org_id": "o1", "source_key": "alpha", "role": "committee"}


@pytest.mark.parametrize("action, word", [("action:approve", "Approve"), ("action:reject", "Reject")])
def test_either_answer_carries_the_flow_on_with_the_answer(answering, action, word):
    run(wx.handle_approval_response("tg:2", action, "p1", SHAH))
    resumed = answering["resumed"][0]
    assert resumed["fields"]["committee"] == word and resumed["fields"]["committee_by"] == "Mr. Shah"
    assert resumed["resume_step"] == 3
    assert ("tg:2", "[approval.answer_ack]") in answering["sent"]
    assert ("tg:100", "Booked.") in answering["sent"]


def test_someone_it_was_not_sent_to_cannot_answer(answering):
    run(wx.handle_approval_response("tg:9", "action:approve", "p1", {**SHAH, "user_id": "u9"}))
    assert answering["resumed"] == [] and answering["sent"] == [("tg:9", "[approval.not_allowed]")]


def test_only_the_first_answer_counts(answering):
    run(wx.handle_approval_response("tg:2", "action:approve", "p1", SHAH))
    run(wx.handle_approval_response("tg:2", "action:reject", "p1", SHAH))
    assert len(answering["resumed"]) == 1
    assert ("tg:2", "[approval.already_handled]") in answering["sent"]


# ── ai.ask ───────────────────────────────────────────────────────────────────


@pytest.fixture
def ai(monkeypatch):
    asked = []
    answers = []

    async def chat_completion(messages, **kw):
        asked.append(messages)
        text = answers.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    from app.services import llm_router

    monkeypatch.setattr(llm_router, "chat_completion", chat_completion)
    return asked, answers


def test_the_ai_picks_exactly_one_of_the_choices(ai):
    asked, answers = ai
    answers.append('```json\n{"choice": "lift"}\n```')
    params = {"task": "pick", "prompt": "Problem: {note}", "choices": ["Lift", "Plumbing"], "into": "category", "instructions": "Be careful."}
    ctx = run(ai_step._op_ai_ask(params, ctx_with()))
    assert ctx["fields"]["category"] == "Lift"
    system, user = asked[0][0]["content"], asked[0][1]["content"]
    assert "- Lift" in system and "Be careful." in system and user == "Problem: hi"


def test_an_answer_outside_the_choices_uses_the_fallback_or_asks_again(ai):
    _, answers = ai
    answers += ['{"choice": "Gardening"}', '{"choice": "Gardening"}']
    params = {"task": "pick", "prompt": "x", "choices": ["Lift", "Other"], "into": "c", "if_unsure": "Other"}
    assert run(ai_step._op_ai_ask(params, ctx_with()))["fields"]["c"] == "Other"
    with pytest.raises(si.UserFacingStepError):
        run(ai_step._op_ai_ask({**params, "if_unsure": None}, ctx_with()))


def test_the_ai_writes_a_text_and_pulls_out_details(ai):
    _, answers = ai
    answers += ['{"text": "Lift stuck in B wing"}', '{"visit_date": "25 Oct", "guests": null}']
    ctx = run(ai_step._op_ai_ask({"task": "write", "prompt": "{note}", "into": "summary"}, ctx_with()))
    assert ctx["fields"]["summary"] == "Lift stuck in B wing"
    fields = [{"name": "visit_date", "type": "date"}, {"name": "guests"}]
    ctx = run(ai_step._op_ai_ask({"task": "extract", "prompt": "{note}", "fields": fields}, ctx_with()))
    assert ctx["fields"]["visit_date"] == "25 Oct" and "guests" not in ctx["fields"]


def test_a_rehearsal_never_calls_the_ai(ai):
    asked, _ = ai
    ctx = run(ai_step._op_ai_ask({"task": "pick", "prompt": "x", "choices": ["A", "B"], "into": "c"}, ctx_with(dry_run=True)))
    assert asked == [] and ctx["fields"]["c"] == "A"


def test_a_list_of_choices_must_be_a_real_column(ai, monkeypatch):
    async def allow(source_key):
        return {"case_categories": {"label"}}

    monkeypatch.setattr(si, "_load_schema_allowlist", allow)
    with pytest.raises(si.StepError):
        run(ai_step._op_ai_ask({"task": "pick", "prompt": "x", "choices": {"table": "case_categories", "column": "secret"}, "into": "c"}, ctx_with()))
    with pytest.raises(si.StepError):
        run(ai_step._op_ai_ask({"task": "pick", "prompt": "x", "choices": {"table": "users; drop", "column": "label"}, "into": "c"}, ctx_with()))


def test_the_checks_know_what_the_ai_step_gives_and_needs():
    steps = [
        {"op": "ai.ask", "params": {"task": "extract", "prompt": "{note}", "fields": [{"name": "visit_date"}]}},
        {"op": "compute", "params": {}, "when": {"field": "$fields.visit_date", "exists": True}},
    ]
    assert validate_steps(steps, schema={}, entity_schema={"note": {}}) == {"errors": [], "warnings": []}
    bad = validate_steps([{"op": "ai.ask", "params": {"task": "pick", "prompt": "x", "into": "c"}}], schema={})
    assert any("choices" in e for e in bad["errors"])


def test_the_new_steps_are_registered():
    assert {"ask_approval", "ai.ask"} <= set(si.PRIMITIVES)
