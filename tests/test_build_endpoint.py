"""Build with AI: what an admin may apply, and the endpoints' access rules (build.py)."""

from pydantic import TypeAdapter

from app.admin_panel import access_rules, build
from app.services.schema_ops import Op

_OPS = TypeAdapter(list[Op])


def test_an_admin_may_only_add():
    add = _OPS.validate_python([
        {"op": "create_record_type", "label": "Booking", "plural": "Bookings", "fields": [{"label": "Place", "kind": "text"}]},
        {"op": "add_field", "record_type": "booking", "field": {"label": "Guests", "kind": "number"}},
        {"op": "add_status", "record_type": "booking", "status": {"label": "Cancelled", "closed": True}},
    ])  # fmt: skip
    hide = _OPS.validate_python([{"op": "set_field_active", "record_type": "booking", "key": "place", "active": False}])
    assert build.add_only(add) and not build.add_only(hide)


def test_the_builder_is_open_to_admins():
    for call in [("GET", "/build"), ("GET", "/build/context"), ("POST", "/build/chat"), ("POST", "/build/save")]:
        assert call in access_rules.ADMIN_CALLS


def test_proposed_lists_count_as_there_until_created():
    lists = build._lists_with({}, [{"op": "create_record_type", "label": "Booking", "plural": "Bookings",
                                   "fields": [{"label": "Place", "kind": "choice"}]}])  # fmt: skip
    assert lists["booking"]["pending"] and lists["booking"]["fields"]["place"]["label"] == "Place"


def test_a_list_not_created_yet_gets_the_columns_the_steps_use():
    ops = [{"op": "create_record_type", "label": "Booking", "plural": "Bookings", "fields": [{"label": "Date", "kind": "date"}]}]
    flow = {"asks": [{"label": "Purpose", "q": "?", "kind": "text"}],
            "steps": [{"a": "save", "list": "Booking", "values": {"Date": "[Date]", "Purpose": "[Purpose]"}}]}  # fmt: skip
    build._fill_pending(flow, ops)
    assert [f["label"] for f in ops[0]["fields"]] == ["Date", "Purpose"]


def test_a_check_on_a_role_that_does_not_exist_is_named():
    from app.services import flow_plain

    plain = {"asks": [], "steps": [{"a": "if", "tests": [{"q": "Role", "op": "oneof", "value": "Defaulter"}], "yes": [{"a": "stop"}], "no": []}]}
    assert [p["need"] for p in flow_plain.check(plain, {}, roles={"owner", "tenant"})] == ["Defaulter"]


def test_unknown_or_leftover_steps_are_dropped_at_every_depth():
    steps = [{"a": "say", "text": "hi"}, {"a": "HERE"},
             {"a": "if", "tests": [{"q": "Role", "op": "is", "value": "Owner"}], "yes": [{"a": "wait"}, {"a": "stop"}], "no": "x"}]  # fmt: skip
    out = build._known_steps(steps)
    assert [s["a"] for s in out] == ["say", "if"] and out[1]["yes"] == [{"a": "stop"}] and out[1]["no"] == []


def test_the_draft_and_try_it_are_open_to_admins():
    for call in [("PUT", "/build/{workflow_id}/draft"), ("DELETE", "/build/{workflow_id}/draft"), ("POST", "/build/{workflow_id}/restore"),
                 ("POST", "/build/check"), ("POST", "/build/try")]:  # fmt: skip
        assert call in access_rules.ADMIN_CALLS


def test_the_ai_may_not_change_a_step_kept_from_the_flows_editor():
    kept = {"a": "engine", "step": {"op": "run_workflow", "params": {"workflow": "case_save_new"}}, "words": "Run"}
    current = {"steps": [kept]}
    moved = {"steps": [{"a": "say", "text": "hi"}, kept]}
    changed = {"steps": [{**kept, "step": {"op": "run_workflow", "params": {"workflow": "something_else"}}}]}
    assert build._engine_changed(moved, current) == [] and build._engine_changed({"steps": []}, current) == []
    assert build._engine_changed(changed, current)


def test_a_report_keeps_what_it_looks_up_whatever_the_ai_sends():
    current = {"start": {"type": "chat", "words": "all"}, "asks": [], "steps": [], "report": {"words": "Lists cases", "format": "list"}}
    out = build._clean({"start": {"type": "chat", "words": "all"}, "asks": [], "steps": [{"a": "say", "text": "x"}]}, current)
    assert out["report"] == current["report"] and out["steps"] == []


def test_only_a_super_admin_opens_a_building_block():
    import pytest
    from fastapi import HTTPException

    class C:
        level = "admin"

        def need_super(self, what):
            raise HTTPException(403, what)

    with pytest.raises(HTTPException):
        build._need_block_rights(C(), {"kind": "block"})
    build._need_block_rights(C(), {"kind": "workflow"})


def test_an_admin_may_change_a_flows_own_copy_of_a_block_but_not_the_shared_one():
    import pytest
    from fastapi import HTTPException

    class C:
        level = "admin"

        def need_super(self, what):
            raise HTTPException(403, what)

    build._need_block_rights(C(), {"kind": "block", "settings": {"copy_for": "a-flow-id"}})
    build._need_block_rights(C(), {"kind": "block", "settings": '{"copy_for": "a-flow-id"}'})
    with pytest.raises(HTTPException):
        build._need_block_rights(C(), {"kind": "block", "settings": {}})
    assert ("POST", "/build/{workflow_id}/copy_block") in access_rules.ADMIN_CALLS


def test_a_block_says_what_it_does_how_many_flows_use_it_and_whether_it_is_a_copy():
    flows = [
        {"id": 1, "intent_key": "tell", "name": "Tell everyone", "kind": "block", "description": "Messages everyone.", "settings": {},
         "entity_schema": {}, "steps": [{"op": "notify.parties", "params": {}, "when": {"field": "$fields.buttons", "equals": "yes"}}]},
        {"id": 2, "intent_key": "tell__own_1", "name": "Tell everyone (copy)", "kind": "block", "settings": {"copy_for": "x"}, "entity_schema": {}, "steps": []},
        {"id": 3, "intent_key": "assign", "name": "Assign", "kind": "workflow", "steps": [{"op": "run_workflow", "params": {"workflow": "tell"}}]},
        {"id": 4, "intent_key": "close", "name": "Close", "kind": "workflow", "steps": [{"op": "run_workflow", "params": {"workflow": "tell"}}]},
    ]  # fmt: skip
    info = build._block_info(flows)
    assert info["tell"]["used_by"] == 2 and info["tell"]["about"] == "Messages everyone." and not info["tell"]["own"]
    assert info["tell"]["steps"][0]["when_words"] == "Buttons is yes"
    assert info["tell__own_1"]["own"] and info["tell__own_1"]["used_by"] == 0
