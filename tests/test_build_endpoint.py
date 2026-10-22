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
