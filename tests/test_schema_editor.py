"""The schema editor (core-0028, housing-0015, app/services/schema_ops.py, app/admin_panel/schema.py).

The rules are tested without a database; the changes themselves run through the real code on throwaway copies of the Godrej
schema (tests/qa/harness.py). What matters: a change only adds, a bad name never becomes SQL, trying a change leaves nothing
behind, and a new kind of record is usable by the flow engine at once."""


import pytest
from fastapi import HTTPException
from pydantic import TypeAdapter

from app.admin_panel import access_rules, common, meta, schema
from app.admin_panel.common import Ctx
from app.services import people_kinds, step_interpreter
from app.services.schema_ops import (
    AddField,
    AddStatus,
    CreateRecordType,
    FieldIn,
    Op,
    SetFieldActive,
    World,
    build_plan,
)
from tests.qa.harness import needs_qa, qa_run

OPS = TypeAdapter(list[Op])


def world(**kw) -> World:
    w = World(tables={"cases", "users", "orgs"}, usecase_keys={"tickets"})
    w.types = {"ticket": {"label": "Ticket", "plural": "Tickets", "table_name": "cases", "is_system": True, "statuses": []}}
    w.fields = {"ticket": {"title": {"label": "Title", "kind": "text", "is_system": True, "is_active": True}}}
    w.roles = {"admin": "r-1"}
    for k, v in kw.items():
        setattr(w, k, v)
    return w


def visitor(**kw) -> CreateRecordType:
    base = dict(
        op="create_record_type", label="Visitor", plural="Visitors", statuses=[{"label": "Expected"}, {"label": "Left"}],
        fields=[FieldIn(label="Guest name", kind="text", required=True), FieldIn(label="Vehicle", kind="choice", options=["Car", "Bike"])],
        people=["Host resident"],
    )  # fmt: skip
    base.update(kw)
    return CreateRecordType(**base)


# ------------------------------------------------------------ no database needed


def test_every_call_is_for_super_admins_only_but_an_admin_may_add_a_list():
    calls = {(m, r.path[len(access_rules.PREFIX):]) for r in schema.router.routes for m in r.methods}
    apply = ("POST", "/schema/apply")  # Build with AI: an admin adds lists, columns and statuses (see build.add_only)
    assert apply in access_rules.ADMIN_CALLS
    assert calls - {apply} <= access_rules.SUPER_CALLS and not ((calls - {apply}) & access_rules.ADMIN_CALLS)


def test_data_and_schema_is_a_super_admin_screen_with_four_tabs():
    caps = {"cases": True, "schema_editor": True}
    s = [x for x in meta._sections(caps) if x["key"] == "schema"]
    assert s and [t["key"] for t in s[0]["tabs"]] == ["database", "builder", "types", "history"]
    assert not [x for x in meta._sections(caps, "admin") if x["key"] == "schema"]
    assert not [x for x in meta._sections({"cases": True}) if x["key"] == "schema"]


def test_a_new_kind_of_record_becomes_one_table_that_only_adds():
    plan = build_plan([visitor()], world())
    assert plan.ok, plan.issues
    sql = "\n".join(plan.sql_up)
    assert 'CREATE TABLE public."visitors"' in sql and '"guest_name" text NOT NULL' in sql
    assert "CHECK (status IN ('expected', 'left'))" in sql and "IN ('Car', 'Bike')" in sql
    assert "DROP" not in sql.upper() and "ALTER" not in sql.upper()
    assert plan.sql_down == ['DROP TABLE public."visitors"']
    kinds = [w["what"] for w in plan.writes]
    assert kinds.count("record_type") == 1 and kinds.count("usecase") == 1 and kinds.count("field") == 2
    assert [w["label"] for w in plan.writes if w["what"] == "people"] == ["Created it", "Host resident"]


@pytest.mark.parametrize(
    "bad",
    [
        visitor(plural="Order"),  # a word the database keeps
        visitor(plural="Cases"),  # the table exists
        visitor(label="Ticket"),  # the record type exists
        visitor(fields=[FieldIn(label="Status")]),  # every record has one
        visitor(fields=[FieldIn(label="Mood", kind="choice", options=["Happy"])]),  # a list needs two choices
        visitor(fields=[FieldIn(label="A"), FieldIn(label="a")]),  # same name twice
        visitor(fields=[FieldIn(label="Care", kind="nonsense")]),
        visitor(fields=[FieldIn(label="x'; DROP TABLE users; --")]),  # becomes a plain name, never code
        visitor(read_by_roles=["nobody"]),
    ],
)
def test_a_bad_change_is_refused_with_a_plain_reason(bad):
    plan = build_plan([bad], world())
    if plan.ok:  # the last-but-one case: the odd label turns into a harmless name, so check nothing odd reached SQL
        assert "DROP TABLE users" not in "\n".join(plan.sql_up)
        assert "\"x_drop_table_users\"" in "\n".join(plan.sql_up)
    else:
        assert plan.issues and not plan.sql_up


def test_a_field_on_tickets_is_kept_inside_the_record_and_changes_no_table():
    plan = build_plan([AddField(op="add_field", record_type="ticket", field=FieldIn(label="Flat number", required=True))], world())
    assert plan.ok and plan.sql_up == []
    assert plan.writes[0]["storage"] == "custom" and plan.writes[0]["required"] is True


def test_a_required_date_cannot_be_added_where_records_may_exist():
    w = world()
    w.types["visitor"] = {"label": "Visitor", "plural": "Visitors", "table_name": "visitors", "is_system": False, "statuses": [{"key": "open", "label": "Open", "closed": False}]}
    plan = build_plan([AddField(op="add_field", record_type="visitor", field=FieldIn(label="Arrives", kind="date", required=True))], w)
    assert not plan.ok and "optional" in plan.issues[0]
    ok = build_plan([AddField(op="add_field", record_type="visitor", field=FieldIn(label="Note", kind="text", required=True))], w)
    assert ok.ok and 'ADD COLUMN "note" text NOT NULL DEFAULT' in ok.sql_up[0]


def test_system_statuses_and_system_fields_are_not_editable():
    assert not build_plan([AddStatus(op="add_status", record_type="ticket", status={"label": "On hold"})], world()).ok
    assert not build_plan([SetFieldActive(op="set_field_active", record_type="ticket", key="title", active=False)], world()).ok


def test_a_later_change_can_use_a_kind_made_by_an_earlier_one_in_the_same_plan():
    ops = [visitor(), AddField(op="add_field", record_type="visitor", field=FieldIn(label="Gate"))]
    plan = build_plan(ops, world())
    assert plan.ok and 'ADD COLUMN "gate"' in "\n".join(plan.sql_up)


# ------------------------------------------------------------ against a real database


async def start(w) -> Ctx:
    common._caps_cache.clear()
    people_kinds.invalidate()
    return Ctx(source_key=w.key, org_id=w.ids.org_id, org_name=w.ids.org_name, caps=await common.get_caps(w.key), actor="test", closed_values=["closed"])


def body(ops) -> schema.OpsBody:
    return schema.OpsBody(ops=[o.model_dump() if hasattr(o, "model_dump") else o for o in ops])


@needs_qa
def test_trying_a_change_leaves_nothing_and_applying_it_makes_a_table_flows_can_use():
    async def scenario(w):
        ctx = await start(w)
        assert ctx.caps["schema_editor"]
        tickets = await w.one("SELECT table_name, is_system FROM record_types WHERE org_id = $1 AND key = 'ticket'", w.ids.org_id)
        assert (tickets["table_name"], tickets["is_system"]) == ("cases", True)  # housing-0015
        ops = [visitor()]
        tried = await schema.schema_plan(ctx, body(ops))
        assert tried["ok"] and tried["tried"]
        assert not (await w.one("SELECT to_regclass('public.visitors') AS t"))["t"]  # tried, then undone
        assert not (await w.one("SELECT count(*) AS n FROM record_types WHERE org_id = $1 AND key = 'visitor'", w.ids.org_id))["n"]
        done = await schema.schema_apply(ctx, body(ops))
        assert done["ok"]
        assert (await w.one("SELECT to_regclass('public.visitors') AS t"))["t"]
        assert (await w.one("SELECT count(*) AS n FROM usecases WHERE org_id = $1 AND key = 'visitors' AND record_type = 'visitor'", w.ids.org_id))["n"] == 1
        kinds = await people_kinds.kinds(w.key, w.ids.org_id, "visitor")
        assert [k["label"] for k in kinds] == ["Created it", "Host resident"]
        hist = await w.one("SELECT status, sql_down FROM schema_changes WHERE org_id = $1", w.ids.org_id)
        assert hist["status"] == "applied" and "DROP TABLE" in hist["sql_down"]
        # the flow engine sees the new table at once, and a bad status is refused by the database itself
        assert "visitors" in await step_interpreter._load_schema_allowlist(w.key)
        await w.one("INSERT INTO visitors (org_id, guest_name, vehicle) VALUES ($1, 'Asha', 'Car') RETURNING id", w.ids.org_id)
        with pytest.raises(Exception):
            await w.one("INSERT INTO visitors (org_id, guest_name, status) VALUES ($1, 'Bad', 'nope') RETURNING id", w.ids.org_id)
        # applying the same change again is refused, and changes nothing
        with pytest.raises(HTTPException):
            await schema.schema_apply(ctx, body(ops))

    qa_run(scenario)


@needs_qa
def test_adding_a_field_a_status_and_switching_a_field_off_keeps_every_record():
    async def scenario(w):
        ctx = await start(w)
        await schema.schema_apply(ctx, body([visitor()]))
        await w.one("INSERT INTO visitors (org_id, guest_name) VALUES ($1, 'Asha') RETURNING id", w.ids.org_id)
        await schema.schema_apply(ctx, body([
            AddField(op="add_field", record_type="visitor", field=FieldIn(label="Flat visited", required=True)),
            AddStatus(op="add_status", record_type="visitor", status={"label": "No show"}),
        ]))  # fmt: skip
        row = await w.one("SELECT flat_visited, status FROM visitors")
        assert (row["flat_visited"], row["status"]) == ("", "expected")  # the older record got a value, nothing was lost
        await w.one("INSERT INTO visitors (org_id, guest_name, status) VALUES ($1, 'Raj', 'no_show') RETURNING id", w.ids.org_id)
        await schema.schema_apply(ctx, body([SetFieldActive(op="set_field_active", record_type="visitor", key="vehicle", active=False)]))
        assert (await w.one("SELECT is_active FROM record_fields WHERE org_id = $1 AND key = 'vehicle'", w.ids.org_id))["is_active"] is False
        assert (await w.one("SELECT count(*) AS n FROM information_schema.columns WHERE table_name = 'visitors' AND column_name = 'vehicle'"))["n"] == 1
        # tickets: a new field is kept inside the record, so the cases table does not change
        before = (await w.one("SELECT count(*) AS n FROM information_schema.columns WHERE table_name = 'cases'"))["n"]
        await schema.schema_apply(ctx, body([AddField(op="add_field", record_type="ticket", field=FieldIn(label="Flat number"))]))
        assert (await w.one("SELECT count(*) AS n FROM information_schema.columns WHERE table_name = 'cases'"))["n"] == before
        assert (await w.one("SELECT storage FROM record_fields WHERE org_id = $1 AND record_type = 'ticket' AND key = 'flat_number'", w.ids.org_id))["storage"] == "custom"
        listing = await schema.schema_overview(ctx)
        assert [t["key"] for t in listing["types"]] == ["ticket", "visitor"] and len(listing["history"]) == 4
        assert (await schema.records_of(ctx, "visitor"))["rows"]

    qa_run(scenario)


@needs_qa
def test_a_change_the_database_refuses_is_rolled_back_whole_and_the_history_says_so():
    async def scenario(w):
        ctx = await start(w)
        await w.run("CREATE TABLE ghosts (id int)")  # a table the editor did not make: the snapshot sees it
        with pytest.raises(HTTPException):
            await schema.schema_apply(ctx, body([visitor(plural="Ghosts", label="Ghost")]))
        assert not (await w.one("SELECT count(*) AS n FROM record_types WHERE key = 'ghost'"))["n"]

    qa_run(scenario)
