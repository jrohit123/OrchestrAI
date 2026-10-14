"""Reminder plans (app/services/reminder_plans.py): at a share of a ticket's time to fix, remind the handler, tell the backup,
hand it to the backup when nobody acted, tell the person who raised it or a whole role; repeat for tickets with no limit;
wait in quiet hours; never twice; and the older reminders stand aside for an organisation that switched its plans on.
Run through the real code on throwaway databases (the migration is applied by the harness); WhatsApp is fake."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.scheduler import jobs
from app.services import config_store, reminder_plans
from tests.qa.harness import needs_qa, qa_run


async def switch_on(w, **extra):
    settings = {
        "reach": {"enabled": False},
        "reminders": {"enabled": True, "pause_statuses": []},
    }
    settings["reminders"].update(extra)
    await w.run(
        "UPDATE orgs SET settings = settings || $1::jsonb WHERE id = $2",
        json.dumps(settings),
        w.ids.org_id,
    )
    config_store.invalidate()


async def plan(w, steps, *, name="Standard plan", default=True, kinds=()):
    p = (await w.one(
        "INSERT INTO reminder_plans (org_id, name, is_default) VALUES ($1, $2, $3) RETURNING id", w.ids.org_id, name, default
    ))["id"]  # fmt: skip
    for i, (at, every, only, actions) in enumerate(steps):
        await w.run(
            "INSERT INTO reminder_plan_steps (org_id, plan_id, sort_order, at_percent, every_minutes, only_if, actions) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)",
            w.ids.org_id, p, i, at, every, only, json.dumps(actions),
        )  # fmt: skip
    for k in kinds:
        await w.run(
            "INSERT INTO reminder_plan_categories (plan_id, category_id, org_id) VALUES ($1, $2, $3)",
            p,
            k,
            w.ids.org_id,
        )
    return p


STANDARD = [
    (25, None, "always", [{"do": "remind"}, {"do": "tell", "to": "backup"}]),
    (
        40,
        None,
        "no_action",
        [{"do": "reassign", "to": "backup"}, {"do": "tell", "to": "raiser"}],
    ),
]


async def ticket(w, number, *, minutes_ago, tat=100, category=None, priority="medium"):
    """A ticket with Sam Staff handling it, Arun Approver as the backup, raised by Meera Member."""
    start = datetime.now(ZoneInfo("UTC")) - timedelta(minutes=minutes_ago)
    row = await w.one(
        "INSERT INTO cases (org_id, case_number, title, location, priority, complainant_id, assigned_to_id, category_id, "
        "tat_started_at, assigned_at, created_at, due_date) "
        "VALUES ($1, $2, 'Tap leaking', 'T5-901', $3, $4, $5, $6, $7, $7, $7, $8) RETURNING id",
        w.ids.org_id, number, priority, w.ids.user["member"], w.ids.user["staff"], category, start,
        start + timedelta(minutes=tat) if tat else None,
    )  # fmt: skip
    await w.run(
        "INSERT INTO case_parties (org_id, case_id, user_id, party_role) VALUES ($1, $2, $3, 'level2')",
        w.ids.org_id, row["id"], w.ids.user["approver"],
    )  # fmt: skip
    return row["id"]


async def age(w, case_id, minutes_ago, tat=100):
    start = datetime.now(ZoneInfo("UTC")) - timedelta(minutes=minutes_ago)
    await w.run(
        "UPDATE cases SET tat_started_at = $1, due_date = $2 WHERE id = $3",
        start,
        start + timedelta(minutes=tat),
        case_id,
    )


def texts(w, who):
    return w.texts_to(getattr(w.ids, f"phone_{who}"))


async def log(w, case_id):
    return [dict(r) for r in await w.sql(
        "SELECT s.at_percent, s.every_minutes, l.outcome, l.detail, l.repeat_no FROM case_reminder_log l "
        "JOIN reminder_plan_steps s ON s.id = l.step_id WHERE l.case_id = $1 ORDER BY s.sort_order, l.repeat_no", case_id
    )]  # fmt: skip


@needs_qa
def test_at_a_quarter_of_the_time_the_handler_is_reminded_and_the_backup_told_once():
    async def scenario(w):
        await switch_on(w)
        await plan(w, STANDARD)
        c = await ticket(w, "TK-1", minutes_ago=30)
        await reminder_plans.run_reminder_plans()
        assert (
            len(texts(w, "staff")) == 1
            and "has used 30% of its time to fix" in texts(w, "staff")[0]
        )
        assert (
            len(texts(w, "approver")) == 1
            and "You are the backup" in texts(w, "approver")[0]
        )
        assert texts(w, "member") == []
        await reminder_plans.run_reminder_plans()  # never twice
        assert len(texts(w, "staff")) == 1
        assert [r["outcome"] for r in await log(w, c)] == ["done"]
        assert (
            await w.one(
                "SELECT count(*) AS n FROM case_activity WHERE case_id = $1 AND activity_type = 'reminder'",
                c,
            )
        )["n"] == 1

    qa_run(scenario)


@needs_qa
def test_when_nobody_acted_it_goes_to_the_backup_and_everyone_is_told():
    async def scenario(w):
        await switch_on(w)
        await plan(w, STANDARD)
        c = await ticket(w, "TK-2", minutes_ago=30)
        await reminder_plans.run_reminder_plans()
        await age(w, c, 45)
        await reminder_plans.run_reminder_plans()
        row = await w.one("SELECT assigned_to_id FROM cases WHERE id = $1", c)
        assert str(row["assigned_to_id"]) == w.ids.user["approver"]
        assert "is now with you" in texts(w, "approver")[-1]
        assert "has moved to Arun Approver" in texts(w, "staff")[-1]
        assert (
            "is being followed up. It is with Arun Approver" in texts(w, "member")[-1]
        )
        parties = {(r["user_id"], r["party_role"]) for r in await w.sql(
            "SELECT user_id::text, party_role FROM case_parties WHERE case_id = $1 AND ended_at IS NULL", c)}  # fmt: skip
        assert (w.ids.user["approver"], "assignee") in parties
        assert (
            w.ids.user["staff"],
            "level2",
        ) in parties  # the old handler keeps hearing about it
        assert (
            await w.one(
                "SELECT count(*) AS n FROM case_activity WHERE case_id = $1 AND activity_type = 'escalation'",
                c,
            )
        )["n"] == 1

    qa_run(scenario)


@needs_qa
def test_a_handler_who_acted_keeps_the_ticket():
    async def scenario(w):
        await switch_on(w)
        await plan(w, STANDARD)
        c = await ticket(w, "TK-3", minutes_ago=30)
        await reminder_plans.run_reminder_plans()
        await w.run(
            "INSERT INTO case_activity (org_id, case_id, activity_type, actor_user_id, payload) VALUES ($1, $2, 'comment', $3, '{}'::jsonb)",
            w.ids.org_id, c, w.ids.user["staff"],
        )  # fmt: skip
        await age(w, c, 45)
        await reminder_plans.run_reminder_plans()
        assert (
            str(
                (await w.one("SELECT assigned_to_id FROM cases WHERE id = $1", c))[
                    "assigned_to_id"
                ]
            )
            == w.ids.user["staff"]
        )
        steps = await log(w, c)
        assert (
            steps[1]["outcome"] == "skipped"
            and "already acted" in json.loads(steps[1]["detail"])["why"]
        )
        assert texts(w, "member") == []

    qa_run(scenario)


@needs_qa
def test_steps_reached_together_run_only_the_furthest_so_nobody_gets_a_pile():
    async def scenario(w):
        await switch_on(w)
        await plan(
            w, STANDARD + [(100, None, "always", [{"do": "tell", "role_id": "ROLE"}])]
        )
        await w.run(
            "UPDATE reminder_plan_steps SET actions = jsonb_build_array(jsonb_build_object('do', 'tell', 'role_id', $1::text)) WHERE at_percent = 100",
            w.ids.role["approver"],
        )
        c = await ticket(
            w, "TK-4", minutes_ago=150
        )  # 150% when the plans are switched on
        await reminder_plans.run_reminder_plans()
        assert [r["outcome"] for r in await log(w, c)] == ["skipped", "skipped", "done"]
        assert (
            len(texts(w, "approver")) == 1
            and "is still open" in texts(w, "approver")[0]
        )
        assert texts(w, "staff") == []

    qa_run(scenario)


@needs_qa
def test_a_ticket_with_no_time_limit_gets_a_regular_nudge():
    async def scenario(w):
        await switch_on(w)
        await plan(w, STANDARD + [(None, 1440, "always", [{"do": "remind"}])])
        c = await ticket(w, "TK-5", minutes_ago=25 * 60, tat=None)
        await reminder_plans.run_reminder_plans()
        await reminder_plans.run_reminder_plans()
        assert (
            len(texts(w, "staff")) == 1
            and "still open after 1 day 1 hour" in texts(w, "staff")[0]
        )
        await w.run(
            "UPDATE cases SET tat_started_at = now() - interval '49 hours' WHERE id = $1",
            c,
        )
        await reminder_plans.run_reminder_plans()
        assert len(texts(w, "staff")) == 2
        assert [r["repeat_no"] for r in await log(w, c)] == [1, 2]

    qa_run(scenario)


@needs_qa
def test_in_quiet_hours_messages_wait_but_a_hand_over_still_happens():
    async def scenario(w):
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        quiet = {
            "from": (now - timedelta(hours=1)).strftime("%H:%M"),
            "to": (now + timedelta(hours=1)).strftime("%H:%M"),
        }
        await switch_on(w, quiet_hours=quiet)
        await plan(w, STANDARD)
        waits = await ticket(w, "TK-6", minutes_ago=30)
        moves = await ticket(w, "TK-7", minutes_ago=45)
        await reminder_plans.run_reminder_plans()
        assert await log(w, waits) == []  # nothing written: it runs in the morning
        assert (
            str(
                (await w.one("SELECT assigned_to_id FROM cases WHERE id = $1", moves))[
                    "assigned_to_id"
                ]
            )
            == w.ids.user["approver"]
        )

    qa_run(scenario)


@needs_qa
def test_a_kind_with_its_own_plan_uses_it_and_so_do_the_kinds_under_it():
    async def scenario(w):
        await switch_on(w)
        await plan(w, STANDARD)
        lift = (
            await w.one(
                "INSERT INTO case_categories (org_id, key, label) VALUES ($1, 'lift', 'Lift') RETURNING id",
                w.ids.org_id,
            )
        )["id"]
        stuck = (await w.one(
            "INSERT INTO case_categories (org_id, key, label, parent_id) VALUES ($1, 'stuck', 'Stuck', $2) RETURNING id", w.ids.org_id, lift
        ))["id"]  # fmt: skip
        await plan(
            w,
            [(10, None, "always", [{"do": "tell", "to": "raiser"}])],
            name="Lifts: faster",
            default=False,
            kinds=[lift],
        )
        c = await ticket(w, "TK-8", minutes_ago=15, category=stuck)
        await reminder_plans.run_reminder_plans()
        assert len(texts(w, "member")) == 1 and texts(w, "staff") == []
        assert [float(r["at_percent"]) for r in await log(w, c)] == [10.0]

    qa_run(scenario)


@needs_qa
def test_paused_closed_and_switched_off_tickets_are_left_alone():
    async def scenario(w):
        await switch_on(w)
        await plan(w, STANDARD)
        paused = await ticket(w, "TK-9", minutes_ago=30)
        await w.run("UPDATE cases SET tat_paused_at = now() WHERE id = $1", paused)
        closed = await ticket(w, "TK-10", minutes_ago=30)
        await w.run("UPDATE cases SET status = 'closed' WHERE id = $1", closed)
        await reminder_plans.run_reminder_plans()
        assert await log(w, paused) == [] and await log(w, closed) == []
        await w.run(
            "UPDATE orgs SET settings = jsonb_set(settings, '{reminders,enabled}', 'false') WHERE id = $1",
            w.ids.org_id,
        )
        config_store.invalidate()
        await w.run("UPDATE cases SET tat_paused_at = NULL WHERE id = $1", paused)
        await reminder_plans.run_reminder_plans()
        assert await log(w, paused) == [] and texts(w, "staff") == []

    qa_run(scenario)


@needs_qa
def test_the_older_reminders_stand_aside_once_the_plans_are_switched_on():
    async def scenario(w):
        legacy = {
            "enabled": True, "table": "cases", "case_number_column": "case_number", "title_column": "title",
            "priority_column": "priority", "status_column": "status", "created_at_column": "created_at",
            "assignee_id_column": "assigned_to_id", "complainant_id_column": "complainant_id",
            "reminder_sent_column": "reminder_sent_at", "assignee_message_template": "Old reminder {case_number}",
            "complainant_message_template": "", "closed_values": ["closed"],
        }  # fmt: skip
        await w.run("UPDATE orgs SET settings = settings || $1::jsonb WHERE id = $2",
                    json.dumps({"case_reminders": legacy, "reach": {"enabled": False}}), w.ids.org_id)  # fmt: skip
        await w.run(
            "INSERT INTO priority_tat_rules (org_id, priority, tat_minutes, reminder_threshold_minutes) VALUES ($1, 'medium', 60, 1)",
            w.ids.org_id,
        )
        await ticket(w, "TK-11", minutes_ago=30)
        await switch_on(
            w
        )  # the plans are on: the older job leaves this organisation alone
        await jobs.run_case_reminders()
        assert not any("Old reminder" in t for t in texts(w, "staff"))
        await w.run(
            "UPDATE orgs SET settings = jsonb_set(settings, '{reminders,enabled}', 'false') WHERE id = $1",
            w.ids.org_id,
        )
        config_store.invalidate()
        await jobs.run_case_reminders()
        assert any("Old reminder TK-11" in t for t in texts(w, "staff"))

    qa_run(scenario)
