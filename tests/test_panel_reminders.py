"""The Reminders screen and the clock of one ticket (app/admin_panel/reminders.py), and "no time limit" on the Categories
screen (app/admin_panel/routing.py).

Run through the real code on throwaway copies of the Godrej schema with housing-0013 applied (tests/qa/harness.py), with the
endpoint functions called directly. The organisation is made after the template was built, so each test runs the migration
once more to give it its starting plan and settings, the way a live organisation got them."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException

from app.admin_panel import access_rules, common, reminders, routing
from app.admin_panel import router as panel_router
from app.admin_panel.common import Ctx
from tests.qa.harness import needs_qa, qa_run

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "features"
    / "housing"
    / "housing-0013_reminder_plans.sql"
)


async def start(w) -> Ctx:
    """The QA organisation with its starting plan and settings, and a dashboard context for it (a super admin)."""
    await w.pools["housing"].execute(MIGRATION.read_text(encoding="utf-8"))
    common._caps_cache.clear()
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


async def kind(w, label, *, minutes=None, no_limit=False, parent=None):
    return (await w.one(
        "INSERT INTO case_categories (org_id, key, label, target_minutes, no_time_limit, parent_id) "
        "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
        w.ids.org_id, label.lower().replace(" ", "_"), label, minutes, no_limit, parent,
    ))["id"]  # fmt: skip


async def settings_of(w) -> dict:
    row = await w.one("SELECT settings FROM orgs WHERE id = $1", w.ids.org_id)
    return json.loads(row["settings"])


async def standard_plan(w):
    return await w.one(
        "SELECT id FROM reminder_plans WHERE org_id = $1 AND is_default",
        w.ids.org_id,
    )


async def step_ids(w, plan_id) -> list:
    return [
        r["id"]
        for r in await w.sql(
            "SELECT id FROM reminder_plan_steps WHERE plan_id = $1 ORDER BY sort_order",
            plan_id,
        )
    ]


# ─────────────────────────── no database needed ───────────────────────────


def test_every_new_call_has_its_rule_and_only_the_clock_is_open_to_admins():
    new_super = {
        ("GET", "/reminders"),
        ("PUT", "/reminders/settings"),
        ("PUT", "/reminders/urgency"),
        ("POST", "/reminders/plans"),
        ("PATCH", "/reminders/plans/{plan_id}"),
        ("DELETE", "/reminders/plans/{plan_id}"),
        ("PUT", "/reminders/plans/{plan_id}/steps"),
    }
    assert new_super <= access_rules.SUPER_CALLS
    assert not (new_super & access_rules.ADMIN_CALLS)
    assert ("GET", "/cases/{case_id}/clock") in access_rules.ADMIN_CALLS
    assert ("GET", "/cases/{case_id}/clock") not in access_rules.SUPER_CALLS
    paths = {
        (m, r.path[len(access_rules.PREFIX) :])
        for r in reminders.router.routes
        for m in r.methods
    }
    assert paths == new_super | {("GET", "/cases/{case_id}/clock")}


def test_an_organisation_without_reminder_plans_is_told_so_instead_of_an_error():
    import asyncio

    ctx = Ctx("alpha", "o", "Alpha", {"cases": True}, "t", ["closed"])
    assert asyncio.run(reminders.get_reminders(ctx)) == {"available": False}
    case_id = "00000000-0000-0000-0000-000000000001"
    assert asyncio.run(reminders.case_clock(ctx, case_id)) == {"available": False}
    e = asyncio.run(
        refused(
            reminders.put_reminder_settings(
                ctx, reminders.ReminderSettingsBody(enabled=True)
            )
        )
    )
    assert e.status_code == 409 and "housing-0013" in e.detail


# ─────────────────────────── the screen ───────────────────────────


@needs_qa
def test_the_screen_gets_everything_it_needs_in_one_call():
    async def scenario(w):
        ctx = await start(w)
        assert ctx.caps["reminders"] and ctx.caps["tat_clock"]
        lift = await kind(w, "Lift", minutes=120)
        await kind(w, "Suggestions", no_limit=True)
        await w.run(
            "INSERT INTO priority_tat_rules (org_id, priority, tat_minutes, reminder_threshold_minutes) "
            "VALUES ($1, 'urgent', 240, 60)",
            w.ids.org_id,
        )
        d = await reminders.get_reminders(ctx)
        assert d["available"] is True and d["enabled"] is False
        assert d["quiet_hours"] == {"from": "22:00", "to": "07:00"}
        assert d["pause_statuses"] == []
        assert d["statuses"] == ["reported", "under_review", "action_taken", "closed"]
        assert d["conditions"] == ["always", "no_action", "not_started"]
        assert d["by_urgency"] == [
            {"priority": "urgent", "tat_minutes": 240},
            {"priority": "high", "tat_minutes": None},
            {"priority": "medium", "tat_minutes": None},
            {"priority": "low", "tat_minutes": None},
        ]
        [plan] = d["plans"]
        assert (
            plan["name"] == "Standard plan" and plan["is_default"] and plan["is_active"]
        )
        assert plan["kinds"] == []
        assert [(s["at_percent"], s["every_minutes"], s["only_if"]) for s in plan["steps"]] == [
            (25.0, None, "always"), (40.0, None, "no_action"), (100.0, None, "always"), (None, 10080, "always"),
        ]  # fmt: skip
        assert plan["steps"][1]["actions"] == [
            {"do": "reassign", "to": "backup"},
            {"do": "tell", "to": "raiser"},
        ]
        assert set(plan["steps"][0]) == {
            "id", "sort_order", "at_percent", "every_minutes", "only_if", "actions", "is_active",
        }  # fmt: skip
        kinds = {k["label"]: k for k in d["kinds"]}
        assert kinds["Lift"]["id"] == lift and kinds["Lift"]["target_minutes"] == 120
        assert kinds["Suggestions"]["no_time_limit"] is True
        assert kinds["Lift"]["no_time_limit"] is False
        assert set(kinds["Lift"]) >= {
            "id",
            "label",
            "parent_id",
            "target_minutes",
            "no_time_limit",
        }
        assert {r["name"] for r in d["roles"]} == {
            "admin",
            "member",
            "approver",
            "staff",
        }
        assert d["people"] == []

    qa_run(scenario)


@needs_qa
def test_settings_are_merged_into_the_organisation_and_checked_in_plain_words():
    async def scenario(w):
        ctx = await start(w)
        put = reminders.put_reminder_settings
        body = reminders.ReminderSettingsBody

        out = await put(ctx, body(enabled=True))
        assert out["enabled"] is True and out["quiet_hours"] == {
            "from": "22:00",
            "to": "07:00",
        }
        s = await settings_of(w)
        assert (
            s["reminders"]["enabled"] is True
            and s["reminders"]["quiet_hours"]["from"] == "22:00"
        )
        assert s["vocabulary"]  # everything else in the settings is kept

        await put(ctx, body(quiet_hours={"from": "7:30", "to": "23:00"}, pause_statuses=["under_review", "under_review"]))  # fmt: skip
        s = await settings_of(w)
        assert s["reminders"] == {
            "enabled": True,
            "quiet_hours": {"from": "07:30", "to": "23:00"},
            "pause_statuses": ["under_review"],
        }
        # the database trigger reads it at once: the clock of a ticket stops at that status
        c = await w.one(
            "INSERT INTO cases (org_id, case_number, title, status) VALUES ($1, 'S-1', 'x', 'reported') RETURNING id",
            w.ids.org_id,
        )
        await w.run("UPDATE cases SET status = 'under_review' WHERE id = $1", c["id"])
        assert (await w.one("SELECT tat_paused_at FROM cases WHERE id = $1", c["id"]))[
            "tat_paused_at"
        ]

        await put(ctx, body(quiet_hours=None))
        assert (await settings_of(w))["reminders"]["quiet_hours"] is None
        assert (await reminders.get_reminders(ctx))["quiet_hours"] is None

        event = await w.one(
            "SELECT * FROM admin_events WHERE area = 'reminders' AND action = 'settings' ORDER BY created_at LIMIT 1"
        )
        assert event["summary"] == "Reminders: reminder plans switched on"

        for bad, words in [
            ({"quiet_hours": {"from": "25:00", "to": "07:00"}}, "HH:MM"),
            ({"quiet_hours": {"from": "22:00"}}, "start ('from') and an end ('to')"),
            ({"quiet_hours": {"from": "22:00", "to": "22:00"}}, "different times"),
            ({"pause_statuses": ["closed"]}, "finished"),
            ({"pause_statuses": ["sleeping"]}, "not a ticket status"),
            ({"enabled": None}, "true or false"),
            ({}, "Nothing to change"),
        ]:
            before = await settings_of(w)
            e = await refused(put(ctx, body(**bad)))
            assert e.status_code == 400 and words in e.detail, (bad, e.detail)
            assert await settings_of(w) == before

    qa_run(scenario)


@needs_qa
def test_the_time_to_fix_of_each_urgency_can_be_changed():
    async def scenario(w):
        ctx = await start(w)
        await w.run(
            "INSERT INTO priority_tat_rules (org_id, priority, tat_minutes, reminder_threshold_minutes) "
            "VALUES ($1, 'high', 600, 500)",
            w.ids.org_id,
        )
        out = await reminders.put_urgency(ctx, {"urgent": 240, "high": 300})
        got = {r["priority"]: r["tat_minutes"] for r in out["by_urgency"]}
        assert got["urgent"] == 240 and got["high"] == 300 and got["low"] is None
        rows = {
            r["priority"]: r
            for r in await w.sql("SELECT * FROM priority_tat_rules WHERE org_id = $1", w.ids.org_id)
        }  # fmt: skip
        # the older reminder is never later than the time to fix
        assert rows["high"]["reminder_threshold_minutes"] == 300
        assert rows["urgent"]["reminder_threshold_minutes"] == 240
        event = await w.one("SELECT summary FROM admin_events WHERE action = 'urgency'")
        assert "high 5 hours (was 10 hours)" in event["summary"]
        for bad, words in [
            ({"someday": 60}, "not an urgency"),
            ({"low": 0}, "between 1 minute and one year"),
            ({"low": 525601}, "between 1 minute and one year"),
            ({}, "Nothing to change"),
        ]:
            e = await refused(reminders.put_urgency(ctx, bad))
            assert e.status_code == 400 and words in e.detail

    qa_run(scenario)


@needs_qa
def test_plans_are_made_changed_and_deleted_and_a_kind_has_only_one():
    async def scenario(w):
        ctx = await start(w)
        lift = await kind(w, "Lift", minutes=120)
        garden = await kind(w, "Garden")
        default = (await standard_plan(w))["id"]

        made = await reminders.create_plan(
            ctx, reminders.PlanNew(name="  Lifts:  faster ", kind_ids=[lift, lift])
        )
        plans = {p["name"]: p for p in (await reminders.get_reminders(ctx))["plans"]}
        mine = plans["Lifts: faster"]
        assert mine["id"] == made["id"] and not mine["is_default"]
        assert mine["kinds"] == [{"id": lift, "label": "Lift"}]
        # it starts with the default plan's steps, so the lifts keep their reminders
        assert (
            len(mine["steps"]) == 4
            and mine["steps"][1]["actions"]
            == plans["Standard plan"]["steps"][1]["actions"]
        )

        e = await refused(
            reminders.create_plan(
                ctx, reminders.PlanNew(name="Lifts again", kind_ids=[lift])
            )
        )
        assert (
            e.status_code == 409
            and "'Lift' already has its own plan, 'Lifts: faster'" in e.detail
        )
        e = await refused(
            reminders.update_plan(
                ctx, default, reminders.PlanPatch(kind_ids=[garden, lift])
            )
        )
        assert e.status_code == 409 and "'Lift'" in e.detail
        e = await refused(
            reminders.create_plan(ctx, reminders.PlanNew(name="LIFTS: FASTER"))
        )
        assert e.status_code == 409 and "already a plan called" in e.detail
        e = await refused(reminders.create_plan(ctx, reminders.PlanNew(name="Other", kind_ids=["00000000-0000-0000-0000-0000000000ff"])))  # fmt: skip
        assert e.status_code == 404

        await reminders.update_plan(
            ctx,
            made["id"],
            reminders.PlanPatch(name="Lifts", is_active=False, kind_ids=[]),
        )
        p = await w.one(
            "SELECT name, is_active FROM reminder_plans WHERE id = $1", made["id"]
        )
        assert p["name"] == "Lifts" and p["is_active"] is False
        await reminders.update_plan(
            ctx, default, reminders.PlanPatch(kind_ids=[lift])
        )  # now free
        assert (
            await w.one(
                "SELECT plan_id FROM reminder_plan_categories WHERE category_id = $1",
                lift,
            )
        )["plan_id"] == default

        e = await refused(reminders.delete_plan(ctx, default))
        assert e.status_code == 409 and "cannot be deleted" in e.detail
        await reminders.delete_plan(ctx, made["id"])
        assert (
            await w.one("SELECT 1 FROM reminder_plans WHERE id = $1", made["id"])
            is None
        )
        assert (
            await w.one(
                "SELECT count(*) AS n FROM reminder_plan_steps WHERE plan_id = $1",
                made["id"],
            )
        )["n"] == 0
        e = await refused(reminders.delete_plan(ctx, made["id"]))
        assert e.status_code == 404
        actions = [r["action"] for r in await w.sql("SELECT action FROM admin_events WHERE area = 'reminders' ORDER BY created_at")]  # fmt: skip
        assert actions == ["plan_create", "plan_update", "plan_update", "plan_delete"]

    qa_run(scenario)


# ─────────────────────────── the steps of a plan ───────────────────────────


@needs_qa
def test_a_plans_steps_are_replaced_in_one_go_and_a_kept_step_keeps_what_it_did():
    async def scenario(w):
        ctx = await start(w)
        plan = (await standard_plan(w))["id"]
        first, second, *_ = await step_ids(w, plan)
        c = await w.one(
            "INSERT INTO cases (org_id, case_number, title) VALUES ($1, 'S-2', 'x') RETURNING id",
            w.ids.org_id,
        )
        await w.run(
            "INSERT INTO case_reminder_log (org_id, case_id, step_id, outcome) VALUES ($1, $2, $3, 'done')",
            w.ids.org_id, c["id"], first,
        )  # fmt: skip
        body = reminders.StepsBody(
            steps=[
                {"id": str(first), "at_percent": 30, "actions": [{"do": "remind"}, {"do": "remind"}]},
                {"at_percent": 50, "only_if": "not_started",
                 "actions": [{"do": "tell", "role_id": w.ids.role["approver"]}, {"do": "tell", "user_id": w.ids.user["admin"]}]},
                {"every_minutes": 1440, "actions": [{"do": "raise_priority"}, {"do": "tell", "to": "also"}]},
            ]
        )  # fmt: skip
        out = await reminders.put_steps(ctx, plan, body)
        assert [(s["at_percent"], s["every_minutes"], s["only_if"]) for s in out["steps"]] == [
            (30.0, None, "always"), (50.0, None, "not_started"), (None, 1440, "always"),
        ]  # fmt: skip
        assert out["steps"][0]["id"] == first and out["steps"][0]["actions"] == [
            {"do": "remind"}
        ]
        assert second not in await step_ids(w, plan)
        log = await w.one(
            "SELECT step_id FROM case_reminder_log WHERE case_id = $1", c["id"]
        )
        assert (
            log["step_id"] == first
        )  # what it did stays linked, so it does not run again on that ticket
        got = await reminders.get_reminders(ctx)
        assert [p["name"] for p in got["people"]] == ["Asha Admin"]
        event = await w.one("SELECT summary FROM admin_events WHERE action = 'steps'")
        assert (
            event["summary"]
            == "Changed the steps of the reminder plan 'Standard plan' (3 steps, was 4)"
        )

    qa_run(scenario)


@needs_qa
def test_a_step_that_makes_no_sense_is_refused_and_nothing_changes():
    async def scenario(w):
        ctx = await start(w)
        plan = (await standard_plan(w))["id"]
        before = await step_ids(w, plan)
        stranger = "00000000-0000-0000-0000-0000000000ff"
        cases = [
            ({"at_percent": 25, "actions": [{"do": "dance"}]}, 400, "not understood"),
            ({"at_percent": 25, "actions": [{"do": "tell", "to": "everyone"}]}, 400, "not understood"),
            ({"at_percent": 25, "actions": [{"do": "remind", "loudly": True}]}, 400, "not understood"),
            ({"at_percent": 25, "actions": ["remind"]}, 400, "A step can remind"),
            ({"at_percent": 25, "actions": []}, 400, "does nothing"),
            ({"at_percent": 25, "every_minutes": 60, "actions": [{"do": "remind"}]}, 400, "one of the two"),
            ({"actions": [{"do": "remind"}]}, 400, "one of the two"),
            ({"at_percent": 0, "actions": [{"do": "remind"}]}, 400, "more than 0%"),
            ({"at_percent": 1001, "actions": [{"do": "remind"}]}, 400, "at most 1000%"),
            ({"every_minutes": 30, "actions": [{"do": "remind"}]}, 400, "once an hour"),
            ({"at_percent": 25, "only_if": "sometimes", "actions": [{"do": "remind"}]}, 400, "always, no_action, not_started"),
            ({"every_minutes": 1440, "actions": [{"do": "reassign", "to": "backup"}]}, 400, "back and forth"),
            ({"at_percent": 25, "actions": [{"do": "tell", "role_id": stranger}]}, 400, "role who is not in this organisation"),
            ({"at_percent": 25, "actions": [{"do": "tell", "user_id": stranger}]}, 400, "person who is not in this organisation"),
            ({"id": stranger, "at_percent": 25, "actions": [{"do": "remind"}]}, 409, "Reload"),
        ]  # fmt: skip
        for step, status, words in cases:
            body = reminders.StepsBody(steps=[step])
            e = await refused(reminders.put_steps(ctx, plan, body))
            assert e.status_code == status and words in e.detail, (step, e.detail)
        twice = reminders.StepsBody(steps=[
            {"at_percent": 25, "actions": [{"do": "remind"}]}, {"at_percent": 25.0, "actions": [{"do": "remind"}]},
        ])  # fmt: skip
        e = await refused(reminders.put_steps(ctx, plan, twice))
        assert e.status_code == 400 and "already at 25%" in e.detail
        assert await step_ids(w, plan) == before
        e = await refused(
            reminders.put_steps(ctx, stranger, reminders.StepsBody(steps=[]))
        )
        assert e.status_code == 404

    qa_run(scenario)


# ─────────────────────────── the clock of one ticket ───────────────────────────


async def ticket(w, number, *, minutes_ago, tat=100):
    start = datetime.now(ZoneInfo("UTC")) - timedelta(minutes=minutes_ago)
    row = await w.one(
        "INSERT INTO cases (org_id, case_number, title, assigned_to_id, tat_started_at, created_at, due_date) "
        "VALUES ($1, $2, 'Tap leaking', $3, $4, $4, $5) RETURNING id",
        w.ids.org_id, number, w.ids.user["staff"], start, start + timedelta(minutes=tat) if tat else None,
    )  # fmt: skip
    return row["id"], start


def near(when, expected, seconds=90) -> bool:
    return abs((when - expected).total_seconds()) <= seconds


@needs_qa
def test_the_clock_of_a_ticket_shows_what_ran_what_is_next_and_what_comes_later():
    async def scenario(w):
        ctx = await start(w)
        # no quiet hours, so the times below do not depend on the hour the test runs at
        await reminders.put_reminder_settings(
            ctx, reminders.ReminderSettingsBody(enabled=True, quiet_hours=None)
        )
        plan = await standard_plan(w)
        quarter = (await step_ids(w, plan["id"]))[0]

        case_id, began = await ticket(w, "C-1", minutes_ago=30)
        fired = datetime.now(ZoneInfo("UTC")) - timedelta(minutes=5)
        await w.run(
            "INSERT INTO case_reminder_log (org_id, case_id, step_id, outcome, fired_at, detail) "
            "VALUES ($1, $2, $3, 'done', $4, $5::jsonb)",
            w.ids.org_id, case_id, quarter, fired, json.dumps({"told": ["Sam Staff"], "percent": 25}),
        )  # fmt: skip
        c = await reminders.case_clock(ctx, case_id)
        assert c["available"] and c["enabled"] and not c["paused"] and not c["closed"]
        assert c["plan"] == {"id": plan["id"], "name": "Standard plan"}
        assert c["total_minutes"] == 100 and 29 <= c["elapsed_minutes"] <= 31
        assert 29.0 <= c["percent"] <= 31.0
        assert near(c["started_at"], began, 2) and near(
            c["due_at"], began + timedelta(minutes=100), 2
        )
        steps = c["steps"]
        assert [(s["at_percent"], s["state"]) for s in steps] == [
            (25.0, "done"),
            (40.0, "next"),
            (100.0, "later"),
        ]
        assert steps[0]["when"] == fired and steps[0]["detail"]["told"] == ["Sam Staff"]
        assert near(steps[1]["when"], began + timedelta(minutes=40))
        assert near(steps[2]["when"], began + timedelta(minutes=100))
        assert steps[1]["only_if"] == "no_action" and steps[1]["actions"][0] == {
            "do": "reassign",
            "to": "backup",
        }
        assert set(steps[0]) >= {
            "id",
            "at_percent",
            "every_minutes",
            "only_if",
            "actions",
            "state",
            "when",
            "detail",
        }

        # two shares passed together: the job runs only the furthest, so the clock says the other is skipped
        late, _ = await ticket(w, "C-2", minutes_ago=50)
        states = [
            (s["at_percent"], s["state"])
            for s in (await reminders.case_clock(ctx, late))["steps"]
        ]
        assert states == [(25.0, "skipped"), (40.0, "next"), (100.0, "later")]

        # a ticket with no time limit: only the repeating step applies
        open_ended, start2 = await ticket(w, "C-3", minutes_ago=60, tat=None)
        c = await reminders.case_clock(ctx, open_ended)
        assert (
            c["total_minutes"] is None and c["percent"] is None and c["due_at"] is None
        )
        assert [
            (s["every_minutes"], s["state"], s["repeat_no"]) for s in c["steps"]
        ] == [(10080, "next", 1)]
        assert near(c["steps"][0]["when"], start2 + timedelta(minutes=10080))

        # a stopped clock stands still and cannot say when the next step comes
        await w.run(
            "UPDATE cases SET tat_paused_at = now() - interval '10 minutes' WHERE id = $1",
            case_id,
        )
        c = await reminders.case_clock(ctx, case_id)
        assert c["paused"] and 19 <= c["elapsed_minutes"] <= 21
        assert [(s["state"], s["when"]) for s in c["steps"][1:]] == [
            ("next", None),
            ("later", None),
        ]

        # a closed ticket has nothing next
        await w.run(
            "UPDATE cases SET status = 'closed', tat_paused_at = NULL WHERE id = $1",
            late,
        )
        c = await reminders.case_clock(ctx, late)
        assert c["closed"] and "next" not in [s["state"] for s in c["steps"]]

        e = await refused(
            reminders.case_clock(ctx, "00000000-0000-0000-0000-0000000000ff")
        )
        assert e.status_code == 404

    qa_run(scenario)


@needs_qa
def test_a_kind_with_its_own_plan_shows_that_plan_on_the_clock():
    async def scenario(w):
        ctx = await start(w)
        await reminders.put_reminder_settings(
            ctx, reminders.ReminderSettingsBody(quiet_hours=None)
        )
        lift = await kind(w, "Lift")
        stuck = await kind(w, "Stuck", parent=lift)
        made = await reminders.create_plan(
            ctx, reminders.PlanNew(name="Lifts", kind_ids=[lift])
        )
        await reminders.put_steps(ctx, made["id"], reminders.StepsBody(steps=[{"at_percent": 10, "actions": [{"do": "remind"}]}]))  # fmt: skip
        case_id, _ = await ticket(w, "C-4", minutes_ago=5)
        await w.run("UPDATE cases SET category_id = $1 WHERE id = $2", stuck, case_id)
        c = await reminders.case_clock(ctx, case_id)
        assert c["plan"]["name"] == "Lifts"
        assert [(s["at_percent"], s["state"]) for s in c["steps"]] == [(10.0, "next")]

    qa_run(scenario)


@needs_qa
def test_the_calls_work_over_http_with_json_bodies_and_answers():
    """The same calls through FastAPI (signing in is replaced by a ready context), so the bodies are parsed and the
    answers turned into JSON the way the dashboard gets them."""

    async def scenario(w):
        ctx = await start(w)
        app = FastAPI()
        app.include_router(panel_router)
        app.dependency_overrides[common.get_ctx] = lambda: ctx
        base = "/admin/qa_housing/api/v2"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            got = (await http.get(f"{base}/reminders")).json()
            assert (
                got["available"] and got["plans"][0]["steps"][0]["at_percent"] == 25.0
            )
            plan_id = got["plans"][0]["id"]

            r = await http.put(
                f"{base}/reminders/settings",
                json={"enabled": True, "quiet_hours": None},
            )
            assert (
                r.status_code == 200
                and r.json()["enabled"] is True
                and r.json()["quiet_hours"] is None
            )
            r = await http.put(
                f"{base}/reminders/settings",
                json={"quiet_hours": {"from": "x", "to": "07:00"}},
            )
            assert r.status_code == 400 and "HH:MM" in r.json()["detail"]

            r = await http.put(f"{base}/reminders/urgency", json={"urgent": 120})
            assert r.status_code == 200 and r.json()["by_urgency"][0] == {
                "priority": "urgent",
                "tat_minutes": 120,
            }

            steps = got["plans"][0]["steps"][:2]  # sent back as they came, ids and all
            r = await http.put(
                f"{base}/reminders/plans/{plan_id}/steps", json={"steps": steps}
            )
            assert r.status_code == 200 and [s["id"] for s in r.json()["steps"]] == [
                s["id"] for s in steps
            ]
            r = await http.put(f"{base}/reminders/plans/{plan_id}/steps", json={"steps": [{"at_percent": 5, "actions": [{"do": "x"}]}]})  # fmt: skip
            assert r.status_code == 400 and "Step 1" in r.json()["detail"]

            made = await http.post(f"{base}/reminders/plans", json={"name": "Quick"})
            assert made.status_code == 200
            r = await http.patch(
                f"{base}/reminders/plans/{made.json()['id']}", json={"is_active": False}
            )
            assert r.status_code == 200
            r = await http.delete(f"{base}/reminders/plans/{plan_id}")
            assert r.status_code == 409

            case_id, _ = await ticket(w, "H-1", minutes_ago=30)
            r = await http.get(f"{base}/cases/{case_id}/clock")
            body = r.json()
            assert r.status_code == 200 and body["plan"]["name"] == "Standard plan"
            assert [s["state"] for s in body["steps"]] == [
                "next",
                "later",
            ]  # 25% and 40% are left
            assert isinstance(body["steps"][0]["when"], str)

    qa_run(scenario)


# ─────────────────────────── categories: no time limit ───────────────────────────


@needs_qa
def test_a_category_has_either_a_time_to_fix_or_no_time_limit():
    async def scenario(w):
        ctx = await start(w)
        made = await routing.create_category(
            ctx, routing.CategoryBody(label="Suggestions", no_time_limit=True)
        )

        async def row():
            return await w.one(
                "SELECT target_minutes, no_time_limit FROM case_categories WHERE id = $1",
                made["id"],
            )

        assert dict(await row()) == {"target_minutes": None, "no_time_limit": True}
        listed = {r["label"]: r for r in (await routing.list_categories(ctx))["rows"]}
        assert listed["Suggestions"]["no_time_limit"] is True

        await routing.update_category(
            ctx, made["id"], routing.CategoryPatch(target_minutes=60)
        )
        assert dict(await row()) == {"target_minutes": 60, "no_time_limit": False}
        await routing.update_category(
            ctx, made["id"], routing.CategoryPatch(no_time_limit=True)
        )
        assert dict(await row()) == {"target_minutes": None, "no_time_limit": True}
        await routing.update_category(
            ctx, made["id"], routing.CategoryPatch(no_time_limit=False)
        )
        assert dict(await row()) == {"target_minutes": None, "no_time_limit": False}

        e = await refused(routing.create_category(ctx, routing.CategoryBody(label="Both", target_minutes=60, no_time_limit=True)))  # fmt: skip
        assert e.status_code == 400 and "not both" in e.detail
        e = await refused(routing.update_category(ctx, made["id"], routing.CategoryPatch(target_minutes=60, no_time_limit=True)))  # fmt: skip
        assert e.status_code == 400

        plain = await routing.create_category(
            ctx, routing.CategoryBody(label="Lift", target_minutes=90)
        )
        lift = await w.one(
            "SELECT target_minutes, no_time_limit FROM case_categories WHERE id = $1",
            plain["id"],
        )
        assert lift["target_minutes"] == 90 and lift["no_time_limit"] is False

        # a database before housing-0013 can still list and save categories; it cannot keep "no time limit"
        old = Ctx(**{**ctx.__dict__, "caps": {**ctx.caps, "tat_clock": False}})
        assert all(
            r["no_time_limit"] is False
            for r in (await routing.list_categories(old))["rows"]
        )
        e = await refused(
            routing.create_category(
                old, routing.CategoryBody(label="Garden", no_time_limit=True)
            )
        )
        assert e.status_code == 409 and "housing-0013" in e.detail
        await routing.create_category(
            old,
            routing.CategoryBody(
                label="Garden", target_minutes=30, no_time_limit=False
            ),
        )
        e = await refused(
            routing.update_category(
                old, plain["id"], routing.CategoryPatch(no_time_limit=False)
            )
        )
        assert e.status_code == 400 and "Nothing to change" in e.detail

    qa_run(scenario)
