"""How a flow starts: on a schedule and after another flow (services/flow_triggers.py, the dashboard
calls in admin_panel/triggers.py, the every-minute job and the hook in the flow engine).

The first half needs no database. The second half runs the real code against throwaway databases on
THIS computer (the QA harness, MIGRATE_TEST_PG): the migration, the calls, the job and the engine, with
nothing able to reach the outside world."""

import asyncio
import datetime as dt
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.admin_panel import access_rules, common, studio, triggers, workflows
from app.admin_panel.common import Ctx
from app.admin_panel.triggers import AfterBody, CadenceBody
from app.services import flow_triggers as ft
from tests.js_page import run_page
from tests.qa.harness import needs_qa, qa_run
from tests.qa.seed import insert_workflow

UTC = dt.timezone.utc
IST = ft.zone_of("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "core" / "core-0026_flow_triggers.sql"


def utc(y, m, d, h=0, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=UTC)


# ───────────────────────────── the cadence (no database) ─────────────────────────────


def test_a_good_cadence_is_kept_and_a_bad_one_is_explained():
    ok, bad = ft.clean_cadence({"every": "week", "time": "9:05", "days": [4, 0, 4]})
    assert bad == []
    assert ok == {
        "every": "week",
        "time": "09:05",
        "days": [0, 4],
        "working_days_only": False,
    }
    ok, bad = ft.clean_cadence({"every": "month", "time": "18:30", "day_of_month": 31})
    assert (bad, ok["day_of_month"]) == ([], 31)
    for raw in (
        None,
        {},
        {"every": "year", "time": "09:00"},
        {"every": "day", "time": "25:00"},
        {"every": "day", "time": "nine"},
        {"every": "week", "time": "09:00", "days": []},
        {"every": "week", "time": "09:00", "days": [9]},
        {"every": "month", "time": "09:00", "day_of_month": 0},
        {"every": "month", "time": "09:00", "day_of_month": 32},
    ):
        cadence, problems = ft.clean_cadence(raw)
        assert cadence is None and problems, raw
        assert all(p[0].isupper() and p.endswith(".") for p in problems)


def test_the_cadence_reads_as_plain_words():
    words = lambda raw: ft.cadence_words(ft.clean_cadence(raw)[0])
    assert words({"every": "day", "time": "09:00"}) == "Every day at 9:00 am"
    assert (
        words({"every": "week", "time": "17:30", "days": [0, 2, 4]})
        == "Every Monday, Wednesday and Friday at 5:30 pm"
    )
    assert (
        words({"every": "week", "time": "00:00", "days": [6]})
        == "Every Sunday at 12:00 am"
    )
    assert (
        words({"every": "month", "time": "09:00", "day_of_month": 1})
        == "On the 1st of every month at 9:00 am"
    )
    assert "last day in a shorter month" in words(
        {"every": "month", "time": "09:00", "day_of_month": 31}
    )
    assert words({"every": "day", "time": "09:00", "working_days_only": True}).endswith(
        "on working days only"
    )
    for n, text in ((2, "2nd"), (3, "3rd"), (11, "11th"), (22, "22nd"), (13, "13th")):
        assert ft._ordinal(n) == text


def cad(**kw):
    return ft.clean_cadence({"time": "09:00", **kw})[0]


def test_the_time_is_the_organisations_time_not_the_servers():
    after = utc(2026, 10, 15, 0, 0)  # Thursday 05:30 in India
    assert ft.next_run(cad(every="day"), after, IST) == utc(2026, 10, 15, 3, 30)
    assert ft.next_run(cad(every="day"), utc(2026, 10, 15, 4, 0), IST) == utc(
        2026, 10, 16, 3, 30
    )
    new_york = ft.zone_of("America/New_York")  # summer time: 9:00 is 13:00 UTC
    assert ft.next_run(cad(every="day"), after, new_york) == utc(2026, 10, 15, 13, 0)
    # a zone name that does not exist falls back to the organisation default
    assert str(ft.zone_of("Mars/Olympus")) == "Asia/Kolkata"


def test_a_slot_is_never_run_twice_the_next_is_strictly_later():
    slot = utc(2026, 10, 15, 3, 30)
    assert ft.next_run(cad(every="day"), slot, IST) == utc(2026, 10, 16, 3, 30)
    assert ft.next_run(cad(every="day"), slot - dt.timedelta(seconds=1), IST) == slot


def test_weekly_runs_on_the_chosen_days_only():
    mon_fri = cad(every="week", days=[0, 4])
    assert ft.next_run(mon_fri, utc(2026, 10, 15), IST) == utc(2026, 10, 16, 3, 30)
    assert ft.next_run(mon_fri, utc(2026, 10, 16, 4), IST) == utc(2026, 10, 19, 3, 30)


def test_monthly_uses_the_last_day_of_a_short_month():
    assert ft.next_run(
        cad(every="month", day_of_month=31), utc(2026, 2, 1), IST
    ) == utc(2026, 2, 28, 3, 30)
    assert ft.next_run(
        cad(every="month", day_of_month=31), utc(2028, 2, 1), IST
    ) == utc(2028, 2, 29, 3, 30)  # a leap year
    assert ft.next_run(
        cad(every="month", day_of_month=15), utc(2026, 10, 15, 4), IST
    ) == utc(2026, 11, 15, 3, 30)


def test_working_days_skip_a_day_off_and_move_a_monthly_run_forward():
    daily = cad(every="day", working_days_only=True)
    friday_late = utc(2026, 10, 16, 10, 0)
    assert ft.next_run(daily, friday_late, IST) == utc(2026, 10, 19, 3, 30)  # Monday
    monthly = cad(every="month", day_of_month=1, working_days_only=True)
    # 1 August 2026 is a Saturday: it runs on Monday the 3rd
    assert ft.next_run(monthly, utc(2026, 7, 31), IST) == utc(2026, 8, 3, 3, 30)
    # the organisation's own working days and holidays win over the Monday-to-Friday default
    assert ft.next_run(
        daily, friday_late, IST, {"working_days": [0, 1, 2, 3, 4, 5]}
    ) == utc(2026, 10, 17, 3, 30)
    assert ft.next_run(daily, friday_late, IST, {"holidays": ["2026-10-19"]}) == utc(
        2026, 10, 20, 3, 30
    )


# ───────────────────────────── can a flow start alone? (no database) ─────────────────────────────


def flow(**kw):
    base = {
        "name": "Nightly tidy",
        "kind": "workflow",
        "workflow_type": "action",
        "steps": [{"op": "db.insert_row", "params": {"table": "t", "values": {}}}],
        "entity_schema": {},
        "gates": [],
    }
    return {**base, **kw}


def test_a_flow_with_nothing_to_ask_can_start_alone():
    assert ft.unfit_reasons(flow()) == []
    optional = {"note": {"type": "string", "required": False}}
    assert ft.unfit_reasons(flow(entity_schema=optional)) == []


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"kind": "block"}, "building block"),
        ({"kind": "case_action"}, "button on a ticket"),
        ({"workflow_type": "read"}, "saved report"),
        ({"steps": []}, "no steps"),
        (
            {"entity_schema": {"title": {"required": True, "label": "a title"}}},
            "has to ask for a title",
        ),
        (
            {"entity_schema": {"flat_no": {"required_if": {"field": "a"}}}},
            "has to ask for flat no",
        ),
        ({"steps": [{"op": "otp_gate", "params": {}}]}, "code or an approval"),
        ({"steps": [{"op": "approval_gate", "params": {}}]}, "code or an approval"),
    ],
)
def test_a_flow_that_needs_a_person_is_refused_in_plain_words(change, words):
    reasons = ft.unfit_reasons(flow(**change))
    assert reasons and words in " ".join(reasons)
    assert "case" not in " ".join(reasons).lower().replace("case_action", "")
    assert "assistant" not in " ".join(reasons).lower()


# ───────────────────────────── who may use it (no database) ─────────────────────────────


def test_only_a_super_admin_may_change_how_a_flow_starts():
    calls = {
        ("GET", "/workflows/{workflow_id}/schedule"),
        ("PUT", "/workflows/{workflow_id}/schedule"),
        ("DELETE", "/workflows/{workflow_id}/schedule"),
        ("POST", "/workflows/{workflow_id}/schedule/run"),
        ("PUT", "/workflows/{workflow_id}/after"),
        ("DELETE", "/workflows/{workflow_id}/after"),
    }
    assert calls <= access_rules.SUPER_CALLS
    assert not calls & access_rules.ADMIN_CALLS


def test_the_card_and_the_list_are_wired_into_the_page():
    from app.admin_panel.ui import js_flows, js_studio

    assert "function startCard()" in js_studio.JS
    assert "startCard() : null" in js_studio.JS
    for words in (
        "Someone does it",
        "On a schedule",
        "After another flow",
        "Run it now",
    ):
        assert words in js_studio.JS
    assert "Someone starts it" in js_flows.JS
    card = js_studio.JS.split("function startCard()")[1].split(
        "// the use case a flow is filed under"
    )[0]
    assert "assistant" not in card.lower()
    assert "case" not in card.lower().replace("case_action", "")  # tickets, not cases


# ───────────────────────────── with databases ─────────────────────────────


async def ready(w):
    """The world, plus the new tables (the migration, run twice: it must be safe to repeat)."""
    sql = MIGRATION.read_text(encoding="utf-8")
    await w.pools[w.kinds[0]].execute(sql)
    await w.pools[w.kinds[0]].execute(sql)
    common._caps_cache.clear()
    ft._no_tables.clear()


async def ctx_of(w, level="super"):
    org = await w.one("SELECT id, name FROM orgs")
    return Ctx(
        source_key=w.key,
        org_id=str(org["id"]),
        org_name=org["name"],
        caps=await common.get_caps(w.key),
        actor="dashboard · test",
        closed_values=["closed"],
        level=level,
    )


def broken():
    """A step the engine refuses: it names a table that does not exist."""
    return {
        "op": "db.insert_row",
        "params": {"table": "no_such_table", "values": {"name": "x"}},
    }


def tick(label):
    """A step that writes one row nobody else writes, so a run shows as a row."""
    return {
        "op": "db.insert_row",
        "params": {
            "table": "routing_rules",
            "values": {"name": label, "assign_role_id": None, "is_active": False},
        },
    }


async def make(w, key, label=None, *, active=True, **spec):
    steps = spec.pop("steps", [tick(label or key)])
    for s in steps:  # the rule table wants exactly one target
        v = s.get("params", {}).get("values", {})
        if "assign_role_id" in v:
            v["assign_role_id"] = w.ids.role["admin"]
    row = await insert_workflow(
        w.pools[w.kinds[0]],
        w.ids.org_id,
        key,
        {
            "name": key.replace("_", " "),
            "steps": steps,
            "entity_schema": {},
            "gates": [],
            **spec,
        },
        is_active=active,
    )
    return str(row["id"])


async def rows_named(w, label):
    return (
        await w.one("SELECT count(*) AS n FROM routing_rules WHERE name = $1", label)
    )["n"]


async def runs_of(w, wid):
    return await w.sql(
        "SELECT how_started, status, message, depth, caused_by_id FROM flow_runs "
        "WHERE workflow_id = $1 ORDER BY started_at, depth",
        wid,
    )


def daily(**kw):
    return CadenceBody(every="day", time="09:00", **kw)


async def due_now(w, wid, ago=dt.timedelta(minutes=1)):
    await w.run(
        "UPDATE flow_schedules SET next_run_at = now() - $2::interval WHERE workflow_id = $1",
        wid,
        ago,
    )


@needs_qa
def test_the_migration_makes_three_empty_tables_and_can_run_twice():
    async def scenario(w):
        await ready(w)
        for table in ("flow_schedules", "flow_chains", "flow_runs"):
            assert (await w.one(f"SELECT count(*) AS n FROM {table}"))["n"] == 0
        caps = await common.get_caps(w.key)
        assert caps["flow_triggers"] is True

    qa_run(scenario)


@needs_qa
def test_setting_a_schedule_stores_it_and_says_when_it_runs_next():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        wid = await make(w, "tidy")
        out = await triggers.set_schedule(
            wid, CadenceBody(every="week", time="08:30", days=[0, 3]), ctx
        )
        assert out["words"] == "Every Monday and Thursday at 8:30 am"
        assert out["switched_off"] is False
        assert out["next_run_at"] > dt.datetime.now(UTC)
        state = await triggers.start_state(wid, ctx)
        assert state["kind"] == "schedule"
        assert state["schedule"]["words"] == out["words"]
        assert state["timezone"] == "Asia/Kolkata"
        assert state["problems"] == []
        # saving again changes it, it does not make a second one
        await triggers.set_schedule(wid, daily(), ctx)
        assert (await w.one("SELECT count(*) AS n FROM flow_schedules"))["n"] == 1
        shown = await workflows.list_workflows(ctx)
        mine = next(r for r in shown["rows"] if str(r["id"]) == wid)
        assert mine["start"] == {"kind": "schedule", "words": "Every day at 9:00 am"}
        other = next(r for r in shown["rows"] if str(r["id"]) != wid)
        assert other["start"] is None  # a person starts it

    qa_run(scenario)


@needs_qa
def test_a_flow_that_needs_a_person_cannot_be_scheduled_or_chained():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        asks = await make(
            w,
            "needs_title",
            entity_schema={"title": {"type": "string", "required": True}},
        )
        block = await make(w, "a_block")
        await w.run("UPDATE workflows SET kind = 'block' WHERE id = $1", block)
        fine = await make(w, "fine")
        with pytest.raises(HTTPException) as e:
            await triggers.set_schedule(asks, daily(), ctx)
        assert e.value.status_code == 422
        assert "has to ask for title" in " ".join(e.value.detail["problems"])
        with pytest.raises(HTTPException) as e:
            await triggers.set_schedule(block, daily(), ctx)
        assert "building block" in e.value.detail["problems"][0]
        with pytest.raises(HTTPException) as e:
            await triggers.set_after(asks, AfterBody(after_id=fine), ctx)
        assert e.value.status_code == 422
        with pytest.raises(HTTPException) as e:  # a bad time
            await triggers.set_schedule(
                fine, CadenceBody(every="day", time="25:99"), ctx
            )
        assert "time of day" in " ".join(e.value.detail["problems"])
        with pytest.raises(HTTPException) as e:  # nothing follows a building block
            await triggers.set_after(fine, AfterBody(after_id=block), ctx)
        assert "building block" in " ".join(e.value.detail["problems"])
        assert (await w.one("SELECT count(*) AS n FROM flow_schedules"))["n"] == 0
        assert (await w.one("SELECT count(*) AS n FROM flow_chains"))["n"] == 0

    qa_run(scenario)


@needs_qa
def test_a_due_flow_runs_once_and_the_next_slot_is_set_before_it_runs():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        wid = await make(w, "morning", "morning-row")
        await triggers.set_schedule(wid, daily(), ctx)
        assert await ft.run_due_schedules() == 0  # not due yet
        assert await rows_named(w, "morning-row") == 0
        await due_now(w, wid)
        assert await ft.run_due_schedules() == 1
        assert await rows_named(w, "morning-row") == 1
        [run] = await runs_of(w, wid)
        assert (run["how_started"], run["status"], run["depth"]) == (
            "schedule",
            "success",
            0,
        )
        row = await w.one("SELECT next_run_at, last_run_at FROM flow_schedules")
        assert row["next_run_at"] > dt.datetime.now(UTC) and row["last_run_at"]
        assert await ft.run_due_schedules() == 0  # the same slot is not run again
        assert await rows_named(w, "morning-row") == 1

    qa_run(scenario)


@needs_qa
def test_two_copies_of_the_app_racing_for_one_slot_run_it_once():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        wid = await make(w, "race", "race-row")
        await triggers.set_schedule(wid, daily(), ctx)
        await due_now(w, wid)
        started = await asyncio.gather(*[ft.run_due_schedules() for _ in range(5)])
        assert sum(started) == 1
        assert await rows_named(w, "race-row") == 1

    qa_run(scenario)


@needs_qa
def test_a_missed_stretch_runs_once_not_once_per_missed_day():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        wid = await make(w, "catchup", "catchup-row")
        await triggers.set_schedule(wid, daily(), ctx)
        await due_now(w, wid, dt.timedelta(days=5))  # the app was down for five days
        assert await ft.run_due_schedules() == 1
        assert await ft.run_due_schedules() == 0
        assert await rows_named(w, "catchup-row") == 1
        nxt = (await w.one("SELECT next_run_at FROM flow_schedules"))["next_run_at"]
        assert nxt > dt.datetime.now(UTC)

    qa_run(scenario)


@needs_qa
def test_a_switched_off_flow_is_skipped_and_the_schedule_moves_on():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        wid = await make(w, "sleeper", "sleeper-row", active=False)
        out = await triggers.set_schedule(wid, daily(), ctx)
        assert out["switched_off"] is True
        await due_now(w, wid)
        await ft.run_due_schedules()
        assert await rows_named(w, "sleeper-row") == 0
        [run] = await runs_of(w, wid)
        assert run["status"] == "skipped" and "switched off" in run["message"]
        assert (await w.one("SELECT next_run_at FROM flow_schedules"))[
            "next_run_at"
        ] > dt.datetime.now(UTC)
        # and it is not run by hand either
        with pytest.raises(HTTPException) as e:
            await triggers.run_now(wid, ctx)
        assert e.value.status_code == 409

    qa_run(scenario)


@needs_qa
def test_a_flow_that_breaks_is_logged_as_failed_with_the_reason_and_the_others_still_run():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        bad = await make(
            w,
            "broken",
            steps=[broken()],
        )
        good = await make(w, "healthy", "healthy-row")
        for wid in (bad, good):
            await triggers.set_schedule(wid, daily(), ctx)
            await due_now(w, wid)
        assert await ft.run_due_schedules() == 2
        [run] = await runs_of(w, bad)
        assert run["status"] == "failed" and run["message"]
        assert await rows_named(w, "healthy-row") == 1

    qa_run(scenario)


@needs_qa
def test_run_it_now_runs_once_logs_it_and_leaves_the_schedule_alone():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        wid = await make(w, "manual", "manual-row")
        with pytest.raises(HTTPException) as e:  # no schedule yet
            await triggers.run_now(wid, ctx)
        assert e.value.status_code == 409
        await triggers.set_schedule(wid, daily(), ctx)
        before = await w.one("SELECT next_run_at FROM flow_schedules")
        out = await triggers.run_now(wid, ctx)
        assert out["status"] == "success"
        assert await rows_named(w, "manual-row") == 1
        [run] = await runs_of(w, wid)
        assert run["how_started"] == "manual"
        assert (await w.one("SELECT next_run_at FROM flow_schedules"))[
            "next_run_at"
        ] == before["next_run_at"]
        state = await triggers.start_state(wid, ctx)
        assert state["runs"][0]["status"] == "success"

    qa_run(scenario)


@needs_qa
def test_removing_the_schedule_hands_the_flow_back_to_people():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        wid = await make(w, "handback", "handback-row")
        await triggers.set_schedule(wid, daily(), ctx)
        await triggers.remove_schedule(wid, ctx)
        assert (await triggers.start_state(wid, ctx))["kind"] == "people"
        assert await ft.run_due_schedules() == 0

    qa_run(scenario)


async def person(w, name="admin"):
    return await w.user(name)


async def finish(w, key):
    """A flow finishing the way it does for a person: through the engine, as a real person."""
    from app.services.step_interpreter import run_workflow_steps

    row = await w.one("SELECT * FROM workflows WHERE intent_key = $1", key)
    return await run_workflow_steps(dict(row), {}, await person(w), "")


@needs_qa
def test_a_flow_starts_when_the_one_before_it_finishes_well():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        first = await make(w, "first_one", "first-row")
        second = await make(w, "second_one", "second-row")
        third = await make(w, "third_one", "third-row")
        await triggers.set_after(second, AfterBody(after_id=first), ctx)
        await triggers.set_after(third, AfterBody(after_id=second), ctx)
        assert (await triggers.start_state(second, ctx))["kind"] == "after_flow"
        shown = await workflows.list_workflows(ctx)
        mine = next(r for r in shown["rows"] if str(r["id"]) == second)
        assert mine["start"]["words"] == "After “first one”"
        result = await finish(w, "first_one")
        assert result["status"] == "done"
        for label in ("first-row", "second-row", "third-row"):
            assert await rows_named(w, label) == 1, label
        [r2] = await runs_of(w, second)
        [r3] = await runs_of(w, third)
        assert (r2["how_started"], r2["status"], r2["depth"]) == (
            "after_flow",
            "success",
            1,
        )
        assert str(r2["caused_by_id"]) == first
        assert (r3["status"], r3["depth"], str(r3["caused_by_id"])) == (
            "success",
            2,
            second,
        )
        assert (
            await runs_of(w, first) == []
        )  # a person started it: nothing to log for it

    qa_run(scenario)


@needs_qa
def test_a_flow_that_fails_starts_nothing_after_it():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        first = await make(
            w,
            "fails_first",
            steps=[broken()],
        )
        second = await make(w, "never_second", "never-row")
        await triggers.set_after(second, AfterBody(after_id=first), ctx)
        assert (await finish(w, "fails_first"))["status"] == "error"
        assert await rows_named(w, "never-row") == 0
        assert await runs_of(w, second) == []

    qa_run(scenario)


@needs_qa
def test_a_scheduled_flow_can_start_others_after_it():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        head = await make(w, "head", "head-row")
        tail = await make(w, "tail", "tail-row")
        await triggers.set_schedule(head, daily(), ctx)
        await triggers.set_after(tail, AfterBody(after_id=head), ctx)
        await due_now(w, head)
        await ft.run_due_schedules()
        assert (
            await rows_named(w, "head-row") == 1
            and await rows_named(w, "tail-row") == 1
        )
        state = await triggers.start_state(head, ctx)
        assert [f["name"] for f in state["followers"]] == ["tail"]

    qa_run(scenario)


@needs_qa
def test_a_loop_is_refused_when_it_is_saved_in_plain_words():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        a, b, c = [await make(w, k) for k in ("loop_a", "loop_b", "loop_c")]
        with pytest.raises(HTTPException) as e:  # itself
            await triggers.set_after(a, AfterBody(after_id=a), ctx)
        assert "cannot start after itself" in " ".join(e.value.detail["problems"])
        await triggers.set_after(b, AfterBody(after_id=a), ctx)
        await triggers.set_after(c, AfterBody(after_id=b), ctx)
        with pytest.raises(HTTPException) as e:  # directly back
            await triggers.set_after(a, AfterBody(after_id=b), ctx)
        assert e.value.status_code == 422
        assert "round in circles" in " ".join(e.value.detail["problems"])
        with pytest.raises(HTTPException) as e:  # through another flow
            await triggers.set_after(a, AfterBody(after_id=c), ctx)
        assert "round in circles" in " ".join(e.value.detail["problems"])
        assert (
            await w.one(
                "SELECT count(*) AS n FROM flow_chains WHERE workflow_id = $1", a
            )
        )["n"] == 0
        # the card does not even offer a flow that would make a loop
        offered = {o["id"] for o in (await triggers.start_state(a, ctx))["can_follow"]}
        assert offered.isdisjoint({b, c})
        # moving b to follow nothing-else is fine and re-pointing is allowed
        await triggers.set_after(c, AfterBody(after_id=a), ctx)

    qa_run(scenario)


@needs_qa
def test_a_loop_that_got_into_the_data_anyway_is_cut_at_run_time():
    async def scenario(w):
        await ready(w)
        a = await make(w, "ring_a", "ring-a-row")
        b = await make(w, "ring_b", "ring-b-row")
        org = w.ids.org_id
        for child, parent in ((b, a), (a, b)):  # written by hand, around the check
            await w.run(
                "INSERT INTO flow_chains (org_id, workflow_id, after_workflow_id) VALUES ($1, $2, $3)",
                org, child, parent,
            )  # fmt: skip
        assert (await finish(w, "ring_a"))["status"] == "done"  # it ends
        assert await rows_named(w, "ring-a-row") == 1  # a person's own run, once
        assert await rows_named(w, "ring-b-row") == 1
        [stopped] = await runs_of(w, a)
        assert stopped["status"] == "failed" and "run itself" in stopped["message"]

    qa_run(scenario)


@needs_qa
def test_a_long_chain_is_cut_at_the_organisations_depth_limit():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        keys = [f"link_{i}" for i in range(4)]
        ids = [await make(w, k, k + "-row") for k in keys]
        for child, parent in zip(ids[1:], ids):
            await triggers.set_after(child, AfterBody(after_id=parent), ctx)
        await w.run(
            "UPDATE orgs SET settings = jsonb_set(settings, '{flows}', '{\"max_chain_depth\": 2}')"
        )
        await finish(w, "link_0")
        assert [await rows_named(w, k + "-row") for k in keys] == [1, 1, 1, 0]
        [cut] = await runs_of(w, ids[3])
        assert cut["status"] == "failed" and "more than 2 flows" in cut["message"]

    qa_run(scenario)


@needs_qa
def test_choosing_one_way_takes_the_other_away():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        a, b = await make(w, "way_a"), await make(w, "way_b")
        await triggers.set_schedule(b, daily(), ctx)
        await triggers.set_after(b, AfterBody(after_id=a), ctx)
        state = await triggers.start_state(b, ctx)
        assert state["kind"] == "after_flow" and state["schedule"] is None
        await triggers.set_schedule(b, daily(), ctx)
        state = await triggers.start_state(b, ctx)
        assert state["kind"] == "schedule" and state["after"] is None
        await triggers.remove_after(b, ctx)  # nothing to remove: harmless
        assert (await triggers.start_state(b, ctx))["kind"] == "schedule"

    qa_run(scenario)


@needs_qa
def test_a_flow_that_others_follow_cannot_be_deleted_and_editing_cannot_break_a_scheduled_flow():
    async def scenario(w):
        await ready(w)
        ctx = await ctx_of(w)
        a, b = await make(w, "keep_a", active=False), await make(w, "keep_b")
        await triggers.set_after(b, AfterBody(after_id=a), ctx)
        with pytest.raises(HTTPException) as e:
            await workflows.delete_workflow(a, ctx)
        assert e.value.status_code == 409 and "keep b" in e.value.detail
        # b starts by itself, so it may not be edited into something that must ask
        with pytest.raises(HTTPException) as e:
            await studio.save_definition(
                b,
                studio.DefinitionBody(
                    base_version=1,
                    entity_schema={"title": {"type": "string", "required": True}},
                ),
                ctx,
            )
        assert e.value.status_code == 422
        text = " ".join(e.value.detail["problems"])
        assert "starts by itself" in text and "has to ask for title" in text
        # the same edit is fine for a flow people start
        free = await make(w, "free_one")
        saved = await studio.save_definition(
            free,
            studio.DefinitionBody(
                base_version=1,
                entity_schema={"title": {"type": "string", "required": True}},
            ),
            ctx,
        )
        assert saved["ok"]

    qa_run(scenario)


@needs_qa
def test_a_database_without_the_tables_still_works_as_before():
    async def scenario(w):
        ft._no_tables.clear()
        ctx = await ctx_of(w)  # the migration was NOT applied
        assert ctx.caps["flow_triggers"] is False
        wid = await make(w, "plain", "plain-row")
        assert (await triggers.start_state(wid, ctx))["available"] is False
        with pytest.raises(HTTPException) as e:
            await triggers.set_schedule(wid, daily(), ctx)
        assert e.value.status_code == 409 and "core-0026" in e.value.detail
        shown = await workflows.list_workflows(ctx)
        assert all(r["start"] is None for r in shown["rows"])
        assert await ft.run_due_schedules() == 0  # no table: nothing to do, no crash
        assert (await finish(w, "plain"))[
            "status"
        ] == "done"  # the engine hook is harmless
        assert await rows_named(w, "plain-row") == 1

    qa_run(scenario)


@needs_qa
def test_the_system_actor_holds_what_the_roles_hold_and_is_not_a_person():
    async def scenario(w):
        actor = await ft.system_actor(w.key, w.ids.org_id)
        assert actor["role"] == "system" and actor["user_id"] == ft.NIL_ID
        assert (
            "qa_case_file" in actor["permissions"]
            and "cases" in actor["readable_tables"]
        )
        assert actor["org_name"] == "QA Housing Society"
        assert not await w.sql("SELECT 1 FROM users WHERE id = $1", actor["user_id"])

    qa_run(scenario)


# ───────────────────────────── the card, drawn by the page's own script ─────────────────────────────

PAGE_FAKES = r"""
const state = (over) => Object.assign({ available: true, kind: 'people', schedule: null, after: null, followers: [],
  can_follow: [{ id: 'o1', name: 'Close a ticket' }], problems: [], is_active: true, timezone: 'Asia/Kolkata',
  working_days: [0, 1, 2, 3, 4], runs: [] }, over || {});
const EW = { d: { id: 'w1', name: 'Nightly tidy', kind: 'workflow' } };
let sup = true;
const isSuper = () => sup;
const zoneLabel = z => z;
const icon = () => h('span', null);
"""


def test_the_card_shows_the_three_ways_and_the_choice_made():
    from app.admin_panel.ui import js_studio

    got = run_page(
        PAGE_FAKES
        + r"""
        EW.start = state({ kind: 'schedule', schedule: { cadence: { every: 'day', time: '09:00' }, words: 'Every day at 9:00 am',
          is_active: true, next_run_at: '2026-10-16T03:30:00Z', last_run_at: null }, runs: [
          { how_started: 'schedule', status: 'failed', message: 'It stopped before it finished.', started_at: '2026-10-15T03:30:00Z' }] });
        const card = startCard();
        const buttons = card.querySelectorAll('.nf-card');
        return { text: card.textContent, on: buttons.filter(b => b.className.includes(' on')).map(b => b.textContent.slice(0, 16)),
                 n: buttons.length, disabled: buttons.map(b => b.disabled) };
        """,
        js_studio,
    )
    assert got["n"] == 3 and got["disabled"] == [False, False, False]
    assert len(got["on"]) == 1 and got["on"][0].startswith("On a schedule")
    for words in (
        "Someone does it",
        "After another flow",
        "Run it now",
        "Last runs",
        "Failed",
    ):
        assert words in got["text"], words
    assert "Every day at 9:00 am" in got["text"] and "Asia/Kolkata" in got["text"]


def test_an_admin_sees_the_card_but_cannot_change_it():
    from app.admin_panel.ui import js_studio

    got = run_page(
        PAGE_FAKES
        + r"""
        sup = false;
        EW.start = state({ kind: 'after_flow', after: { id: 'o1', name: 'Close a ticket' } });
        const card = startCard();
        return { text: card.textContent, off: card.querySelectorAll('.nf-card').map(b => b.disabled),
                 saves: card.querySelectorAll('button').filter(b => !b.className.includes('nf-card')).length };
        """,
        js_studio,
    )
    assert got["off"] == [True, True, True] and got["saves"] == 0
    assert "Only a super admin can change how a flow starts" in got["text"]


def test_the_card_explains_what_stops_a_flow_starting_alone_and_a_missing_update():
    from app.admin_panel.ui import js_studio

    got = run_page(
        PAGE_FAKES
        + r"""
        EW.start = state({ kind: 'schedule', is_active: false, problems: ['“Nightly tidy” has to ask for a title.'] });
        const warn = startCard().textContent;
        EW.start = state({ available: false });
        const old = startCard().textContent;
        return { warn, old };
        """,
        js_studio,
    )
    assert "has to ask for a title" in got["warn"]
    assert "switched off" in got["warn"]
    assert "core-0026" in got["old"]
