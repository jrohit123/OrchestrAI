"""Use cases and the kinds of people on a record (core-0027, housing-0014, app/admin_panel/usecases.py,
app/services/people_kinds.py). The kinds are data: the code never lists them, so a new one works without a change.

Run through the real code on throwaway copies of the Godrej schema with the migrations applied (tests/qa/harness.py)."""

import re

from fastapi import HTTPException

from app.admin_panel import access_rules, cases, common, meta, usecases
from app.admin_panel.common import Ctx
from app.services import case_ops, people_kinds, reminder_plans, step_interpreter
from tests.qa.harness import needs_qa, qa_run

TICKET_KINDS = ["assignee", "level2", "helper", "requester", "watcher"]


async def start(w) -> Ctx:
    common._caps_cache.clear()
    people_kinds.invalidate()
    return Ctx(
        source_key=w.key,
        org_id=w.ids.org_id,
        org_name=w.ids.org_name,
        caps=await common.get_caps(w.key),
        actor="test",
        closed_values=["closed"],
    )


async def refused(coro) -> HTTPException:
    try:
        await coro
    except HTTPException as e:
        return e
    raise AssertionError("expected the request to be refused")


async def a_ticket(w) -> dict:
    row = await w.one(
        "INSERT INTO cases (org_id, case_number, title, status, complainant_id, assigned_to_id) "
        "VALUES ($1, 'CS-T-' || substr(md5(random()::text), 1, 6), 'Leak', 'reported', $2, $3) RETURNING *",
        w.ids.org_id,
        w.ids.user["member"],
        w.ids.user["staff"],
    )
    return dict(row)


# ------------------------------------------------------------ no database needed


def test_every_call_is_for_super_admins_only():
    calls = {(m, r.path[len(access_rules.PREFIX) :]) for r in usecases.router.routes for m in r.methods}
    assert calls <= access_rules.SUPER_CALLS and not (calls & access_rules.ADMIN_CALLS)


def test_no_screen_or_engine_code_names_a_kind_of_person():
    from app.admin_panel import ui

    js = ui.APP_JS
    for word in ("'level2'", '"level2"', "'watcher'", "'requester'", "Raised the case", "PARTY = "):
        assert word not in js, word
    src = open(case_ops.__file__, encoding="utf-8").read() + open(reminder_plans.__file__, encoding="utf-8").read()
    assert not re.search(r"""["'](level2|watcher|helper|requester)["']""", src)


def test_the_menu_has_use_cases_under_build_for_a_super_admin_only():
    caps = {"cases": True, "workflow_kind": True, "usecases": True}
    assert "usecases" in [s["key"] for s in meta._sections(caps)]
    assert "usecases" not in [s["key"] for s in meta._sections(caps, "admin")]
    assert "usecases" not in [s["key"] for s in meta._sections({"cases": True})]


# ------------------------------------------------------------ the migration


@needs_qa
def test_tickets_are_the_first_use_case_and_its_kinds_are_the_keys_tickets_already_store():
    async def scenario(w):
        ctx = await start(w)
        assert ctx.caps["usecases"]
        found = await people_kinds.kinds(w.key, w.ids.org_id, "ticket")
        assert people_kinds.keys(found) == TICKET_KINDS  # the order people are told in
        assert {k["key"]: k["meaning"] for k in found} == {
            "assignee": "handler", "level2": "backup", "helper": "other", "requester": "raiser", "watcher": "informed",
        }  # fmt: skip
        assert [k["key"] for k in found if not k["added"]] == ["assignee", "requester"]  # set by the system
        uc = await w.one("SELECT name, record_type, keeps_photos FROM usecases WHERE org_id = $1", w.ids.org_id)
        assert (uc["name"], uc["record_type"], uc["keeps_photos"]) == ("Tickets", "ticket", True)

    qa_run(scenario)


@needs_qa
def test_a_ticket_only_takes_kinds_of_people_that_exist_and_a_new_one_works_at_once():
    async def scenario(w):
        await start(w)
        t = await a_ticket(w)
        parties = {r["party_role"] for r in await w.sql("SELECT party_role FROM case_parties WHERE case_id = $1", t["id"])}
        assert {"requester", "assignee"} <= parties  # the database still keeps these two itself
        try:
            await w.run(
                "INSERT INTO case_parties (org_id, case_id, user_id, party_role) VALUES ($1, $2, $3, 'contractor')",
                w.ids.org_id, t["id"], w.ids.user["approver"],
            )  # fmt: skip
            raise AssertionError("an unknown kind was taken")
        except AssertionError:
            raise
        except Exception as e:
            assert "not a kind of person on a ticket" in str(e)
        await w.run(
            "INSERT INTO record_people_kinds (org_id, record_type, key, label, meaning, added, sort_order) "
            "VALUES ($1, 'ticket', 'contractor', 'Contractor', 'other', true, 6)",
            w.ids.org_id,
        )
        await w.run(
            "INSERT INTO case_parties (org_id, case_id, user_id, party_role) VALUES ($1, $2, $3, 'contractor')",
            w.ids.org_id, t["id"], w.ids.user["approver"],
        )  # fmt: skip

    qa_run(scenario)


# ------------------------------------------------------------ the engine reads the data


@needs_qa
def test_steps_add_only_kinds_a_flow_may_add_and_reminders_find_people_by_meaning():
    async def scenario(w):
        await start(w)
        t = await a_ticket(w)
        ctx = {"source_key": w.key, "org_id": w.ids.org_id, "fields": {}, "case": t, "user": {"user_id": w.ids.user["staff"]}}
        add = step_interpreter.PRIMITIVES["case.add_parties"]
        await add({"case_id": "$case.id", "users_from": str(w.ids.user["approver"]), "role": "level2"}, ctx)
        try:
            await add({"case_id": "$case.id", "users_from": str(w.ids.user["approver"]), "role": "requester"}, ctx)
            raise AssertionError("a system kind was added by a step")
        except step_interpreter.StepError as e:
            assert "not a kind of person a flow may put on a ticket" in str(e) and "Also told" in str(e)
        # renaming a kind changes nothing for the engine: it goes by meaning
        await w.run("UPDATE record_people_kinds SET label = 'Second line' WHERE org_id = $1 AND key = 'level2'", w.ids.org_id)
        people_kinds.invalidate()
        who = await reminder_plans._people(w.key, t)
        assert [str(p["id"]) for p in who["backups"]] == [w.ids.user["approver"]]
        assert str(who["raiser"]["id"]) == w.ids.user["member"] and str(who["handler"]["id"]) == w.ids.user["staff"]

    qa_run(scenario)


# ------------------------------------------------------------ the dashboard


@needs_qa
def test_a_super_admin_adds_a_use_case_and_its_kinds_and_files_a_flow_under_it():
    async def scenario(w):
        ctx = await start(w)
        made = await usecases.create_usecase(ctx, usecases.NewUsecase(name="Visitors", icon="🚪", record_type="visitor"))
        assert made["record_type"] == "visitor"
        await usecases.save_kinds(ctx, "visitor", usecases.KindsBody(kinds=[
            usecases.Kind(label="Host resident", meaning="raiser"), usecases.Kind(label="Guard on duty", meaning="informed"),
        ]))  # fmt: skip
        d = await usecases.list_usecases(ctx)
        assert [u["name"] for u in d["usecases"]] == ["Tickets", "Visitors"]
        assert [k["label"] for k in d["kinds"]["visitor"]] == ["Host resident", "Guard on duty"]
        lk = await meta.lookups(ctx)
        assert [k["label"] for k in lk["people_kinds"]["visitor"]] == ["Host resident", "Guard on duty"]
        flow = await w.one("SELECT id FROM workflows WHERE org_id = $1 ORDER BY name LIMIT 1", w.ids.org_id)
        await usecases.set_flow_usecase(ctx, flow["id"], usecases.FlowUsecase(usecase_id=made["id"]))
        assert (await w.one("SELECT usecase_id FROM workflows WHERE id = $1", flow["id"]))["usecase_id"] is not None
        e = await refused(usecases.create_usecase(ctx, usecases.NewUsecase(name="visitors", record_type="visitor")))
        assert e.status_code == 409

    qa_run(scenario)


@needs_qa
def test_kinds_are_never_deleted_and_system_ones_keep_their_meaning():
    async def scenario(w):
        ctx = await start(w)
        d = await usecases.list_usecases(ctx)
        ticket = [usecases.Kind(**{k: v for k, v in x.items() if k in usecases.Kind.model_fields}) for x in d["kinds"]["ticket"]]
        e = await refused(usecases.save_kinds(ctx, "ticket", usecases.KindsBody(kinds=ticket[1:])))
        assert e.status_code == 422 and "never deleted" in e.detail
        changed = [k.model_copy(update={"meaning": "other"}) if k.key == "assignee" else k for k in ticket]
        e = await refused(usecases.save_kinds(ctx, "ticket", usecases.KindsBody(kinds=changed)))
        assert e.status_code == 422 and "set by the system" in e.detail
        renamed = [k.model_copy(update={"label": "With them now"}) if k.key == "assignee" else k for k in ticket]
        await usecases.save_kinds(ctx, "ticket", usecases.KindsBody(kinds=renamed))
        t = await a_ticket(w)
        page = await cases.case_detail(ctx, t["id"]) if hasattr(cases, "case_detail") else None
        if page:
            mine = next(p for p in page["parties"] if p["party_role"] == "assignee")
            assert mine["label"] == "With them now" and mine["meaning"] == "handler" and mine["rank"] == 0

    qa_run(scenario)
