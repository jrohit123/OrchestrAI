"""The time to fix (TAT) of a ticket, kept by the database (migrations/features/housing/housing-0013_reminder_plans.sql):
kinds with no time limit, when the handler got a ticket, a paused clock, a reopened ticket, and the starting reminder plan.
Run on a throwaway copy of the Godrej schema with the migration applied (see harness.TEMPLATE_MIGRATIONS)."""

import json
from pathlib import Path

import asyncpg
import pytest

from tests.qa.harness import needs_qa, qa_run

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "features"
    / "housing"
    / "housing-0013_reminder_plans.sql"
)


async def kinds(w):
    org = w.ids.org_id
    ids = {}
    for name, minutes, no_limit, parent in [
        ("Suggestions", None, True, None),
        ("Garden", 60, False, "Suggestions"),
        ("Benches", None, False, "Suggestions"),
        ("Lift", 120, False, None),
    ]:
        ids[name] = await w.one(
            "INSERT INTO case_categories (org_id, key, label, target_minutes, no_time_limit, parent_id) "
            "VALUES ($1, $2, $2, $3, $4, $5) RETURNING id",
            org, name.lower(), minutes, no_limit, ids.get(parent),
        )  # fmt: skip
        ids[name] = ids[name]["id"]
    return ids


async def new_case(
    w, number, *, category=None, due_hours=4, assigned=None, status="reported"
):
    row = await w.one(
        "INSERT INTO cases (org_id, case_number, title, status, category_id, due_date, assigned_to_id) "
        "VALUES ($1, $2, 'A problem', $3, $4, now() + make_interval(hours => $5), $6) RETURNING *",
        w.ids.org_id, number, status, category, due_hours, assigned,
    )  # fmt: skip
    return row


async def case(w, case_id):
    return await w.one("SELECT * FROM cases WHERE id = $1", case_id)


@needs_qa
def test_the_migration_is_safe_to_run_twice_and_starts_switched_off_with_one_plan():
    async def scenario(w):
        pool = w.pools["housing"]
        sql = MIGRATION.read_text(encoding="utf-8")
        await pool.execute(
            sql
        )  # the QA organisation exists now, so it gets its starting plan
        await pool.execute(sql)
        org = w.ids.org_id
        plans = await w.sql("SELECT * FROM reminder_plans WHERE org_id = $1", org)
        assert (
            len(plans) == 1
            and plans[0]["is_default"]
            and plans[0]["name"] == "Standard plan"
        )
        steps = await w.sql(
            "SELECT * FROM reminder_plan_steps WHERE plan_id = $1 ORDER BY sort_order",
            plans[0]["id"],
        )
        assert [
            (
                float(s["at_percent"]) if s["at_percent"] is not None else None,
                s["every_minutes"],
                s["only_if"],
            )
            for s in steps
        ] == [
            (25.0, None, "always"),
            (40.0, None, "no_action"),
            (100.0, None, "always"),
            (None, 10080, "always"),
        ]
        assert json.loads(steps[1]["actions"]) == [
            {"do": "reassign", "to": "backup"},
            {"do": "tell", "to": "raiser"},
        ]
        settings = json.loads(
            (await w.one("SELECT settings FROM orgs WHERE id = $1", org))["settings"]
        )
        assert settings["reminders"]["enabled"] is False
        assert settings["vocabulary"]  # what was there before is kept

    qa_run(scenario)


@needs_qa
def test_a_kind_with_no_time_limit_gives_its_tickets_no_due_time_but_a_sub_kind_with_minutes_keeps_one():
    async def scenario(w):
        k = await kinds(w)
        assert (await new_case(w, "T-1", category=k["Suggestions"]))["due_date"] is None
        assert (await new_case(w, "T-2", category=k["Benches"]))[
            "due_date"
        ] is None  # copies its parent
        assert (await new_case(w, "T-3", category=k["Garden"]))[
            "due_date"
        ] is not None  # its own minutes win
        assert (await new_case(w, "T-4", category=k["Lift"]))["due_date"] is not None
        later = await new_case(w, "T-5")
        assert later["due_date"] is not None
        await w.run(
            "UPDATE cases SET category_id = $1 WHERE id = $2",
            k["Suggestions"],
            later["id"],
        )
        assert (await case(w, later["id"]))[
            "due_date"
        ] is None  # the flow sets the kind after saving
        await w.run(
            "UPDATE cases SET due_date = now() + interval '1 day' WHERE id = $1",
            later["id"],
        )
        assert (await case(w, later["id"]))["due_date"] is None

    qa_run(scenario)


@needs_qa
def test_the_clock_starts_when_raised_and_notes_when_the_handler_got_it():
    async def scenario(w):
        a, b = w.ids.user["member"], w.ids.user["staff"]
        c = await new_case(w, "T-6", assigned=a)
        assert (
            c["tat_started_at"] is not None
            and c["assigned_at"] is not None
            and c["tat_cycle"] == 0
        )
        await w.run(
            "UPDATE cases SET assigned_at = now() - interval '2 hours' WHERE id = $1",
            c["id"],
        )
        await w.run("UPDATE cases SET assigned_to_id = $1 WHERE id = $2", b, c["id"])
        after = await case(w, c["id"])
        assert after["assigned_at"] > c["assigned_at"] - __import__(
            "datetime"
        ).timedelta(minutes=1)
        await w.run("UPDATE cases SET title = 'Renamed' WHERE id = $1", c["id"])
        assert (await case(w, c["id"]))["assigned_at"] == after[
            "assigned_at"
        ]  # other changes leave it alone

    qa_run(scenario)


@needs_qa
def test_a_paused_ticket_moves_its_due_time_on_by_the_pause():
    async def scenario(w):
        await w.run(
            "UPDATE orgs SET settings = jsonb_set(settings, '{reminders}', '{\"pause_statuses\": [\"under_review\"]}'::jsonb, true) WHERE id = $1",
            w.ids.org_id,
        )
        c = await new_case(w, "T-7")
        await w.run("UPDATE cases SET status = 'under_review' WHERE id = $1", c["id"])
        paused = await case(w, c["id"])
        assert paused["tat_paused_at"] is not None
        await w.run(
            "UPDATE cases SET tat_paused_at = now() - interval '30 minutes' WHERE id = $1",
            c["id"],
        )
        await w.run("UPDATE cases SET status = 'action_taken' WHERE id = $1", c["id"])
        back = await case(w, c["id"])
        assert back["tat_paused_at"] is None
        assert 30 <= back["tat_paused_minutes"] <= 31
        moved = (back["due_date"] - c["due_date"]).total_seconds() / 60
        assert 30 <= moved <= 31

    qa_run(scenario)


@needs_qa
def test_a_reopened_ticket_gets_a_fresh_clock_of_the_same_length_and_a_new_cycle():
    async def scenario(w):
        c = await new_case(w, "T-8", due_hours=4)
        await w.run(
            "UPDATE cases SET status = 'closed', tat_started_at = now() - interval '2 days', "
            "due_date = now() - interval '2 days' + interval '4 hours' WHERE id = $1",
            c["id"],
        )
        await w.run("UPDATE cases SET status = 'reported' WHERE id = $1", c["id"])
        r = await case(w, c["id"])
        assert r["tat_cycle"] == 1
        length = (r["due_date"] - r["tat_started_at"]).total_seconds() / 3600
        assert abs(length - 4) < 0.01

    qa_run(scenario)


@needs_qa
def test_the_timeline_may_say_reminder_and_a_step_is_either_a_share_or_a_repeat():
    async def scenario(w):
        c = await new_case(w, "T-9")
        await w.run(
            "INSERT INTO case_activity (org_id, case_id, activity_type, payload) VALUES ($1, $2, 'reminder', '{}'::jsonb)",
            w.ids.org_id, c["id"],
        )  # fmt: skip
        plan = await w.one(
            "INSERT INTO reminder_plans (org_id, name, is_default) VALUES ($1, 'P', true) RETURNING id",
            w.ids.org_id,
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await w.run(
                "INSERT INTO reminder_plan_steps (org_id, plan_id, at_percent, every_minutes) VALUES ($1, $2, 25, 60)",
                w.ids.org_id, plan["id"],
            )  # fmt: skip
        with pytest.raises(
            asyncpg.UniqueViolationError
        ):  # one default plan per organisation
            await w.run(
                "INSERT INTO reminder_plans (org_id, name, is_default) VALUES ($1, 'Q', true)",
                w.ids.org_id,
            )

    qa_run(scenario)
