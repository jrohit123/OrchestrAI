"""Catalogue groups H (scheduler), G12 and G (AI-written SQL, end to end), and L04 (a failed send).

Time is frozen with a small stand-in for the `datetime` module that the scheduler imports, so a test can say
"it is 10:00 in India on 31 January" without waiting. A case that fails today is `xfail(strict=True)` tagged with its
bug ID; each has a control test beside it.
"""

import asyncio
import datetime as dt
import json
import logging
from types import SimpleNamespace

import pytest

from tests.qa.harness import _patch, llm_message, needs_qa, qa_run
from tests.qa.qa_helpers import phone_of

UTC = dt.timezone.utc


def bug(ident: str, why: str = ""):
    return pytest.mark.xfail(strict=True, reason=f"{ident} {why}".strip())


# ───────────────────────────── a clock the tests can set ─────────────────────────────


class Clock(dt.datetime):
    frozen = None

    @classmethod
    def now(cls, tz=None):
        return cls.frozen.astimezone(tz) if tz else cls.frozen.replace(tzinfo=None)


def set_time(w, when: dt.datetime) -> None:
    """From now on the scheduler believes it is `when` (an aware datetime)."""
    from app.scheduler import jobs

    Clock.frozen = when
    shim = SimpleNamespace(
        datetime=Clock,
        timedelta=dt.timedelta,
        timezone=dt.timezone,
        date=dt.date,
        time=dt.time,
    )
    _patch(w, jobs, "datetime", shim)


def utc(y, m, d, h=0, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=UTC)


async def add_report(
    w,
    who: str,
    schedule_type: str,
    next_run_at: dt.datetime,
    hour=9,
    minute=0,
    day_of_month=None,
    day_of_week=None,
    open_door=True,
):
    user = await w.user(who)
    if open_door:  # the person wrote to the chat bot today, so WhatsApp lets it write back (see test_70)
        from app.services import reach

        await reach.record_inbound(user["phone"])
    await w.run(
        """INSERT INTO scheduled_reports (org_id, user_id, phone, query_text, report_label, schedule_type, hour, minute, day_of_month, day_of_week, delivery, next_run_at, source_key)
           VALUES ($1, $2, $3, 'open cases by category', 'Open cases', $4, $5, $6, $7, $8, 'whatsapp', $9, $10)""",
        user["org_id"],
        user["user_id"],
        user["phone"],
        schedule_type,
        hour,
        minute,
        day_of_month,
        day_of_week,
        next_run_at,
        user["source_key"],
    )
    return user


def script_report_text(w, text="Here is your report."):
    w.llm.handler(lambda *a, **k: llm_message(content=text))


async def tick(w, when: dt.datetime) -> None:
    from app.scheduler import jobs

    set_time(w, when)
    await jobs.run_scheduled_reports()


def reports_sent_to(w, phone: str) -> int:
    return len([t for t in w.texts_to(phone) if "Scheduled:" in t])


# ───────────────────────────── H. scheduled reports ─────────────────────────────


@needs_qa
def test_H_control_a_daily_report_is_sent_once_and_moves_to_tomorrow():
    async def scenario(w):
        script_report_text(w)
        user = await add_report(
            w, "member", "daily", utc(2026, 10, 8, 3, 30)
        )  # 09:00 in India
        await tick(w, utc(2026, 10, 8, 4, 0))
        await tick(w, utc(2026, 10, 8, 4, 1))
        assert reports_sent_to(w, user["phone"]) == 1
        row = await w.one("SELECT next_run_at, run_count FROM scheduled_reports")
        assert row["next_run_at"] == utc(2026, 10, 9, 3, 30) and row["run_count"] == 1

    qa_run(scenario)


@needs_qa
def test_H03_a_report_that_was_missed_for_three_days_is_sent_once_not_three_times():
    async def scenario(w):
        script_report_text(w)
        user = await add_report(w, "member", "daily", utc(2026, 10, 5, 3, 30))
        await tick(w, utc(2026, 10, 8, 4, 0))
        await tick(w, utc(2026, 10, 8, 4, 1))
        assert reports_sent_to(w, user["phone"]) == 1

    qa_run(scenario)


@needs_qa
@bug(
    "QA-010",
    "the next-run calculation raises for day 31 in a 30-day month, so the report stays due and is sent every minute",
)
def test_H10_a_monthly_report_on_the_31st_is_sent_once_per_month():
    async def scenario(w):
        script_report_text(w)
        user = await add_report(
            w, "member", "monthly", utc(2026, 1, 31, 3, 30), day_of_month=31
        )
        for minute in range(3):
            await tick(w, utc(2026, 1, 31, 4, 30 + minute))
        assert reports_sent_to(w, user["phone"]) == 1, (
            f"sent {reports_sent_to(w, user['phone'])} times in 3 minutes"
        )

    qa_run(scenario)


@needs_qa
def test_H06_an_empty_and_a_huge_report_are_both_sent_and_rescheduled():
    async def scenario(w):
        replies = iter(["", "x" * 50000])
        w.llm.handler(lambda *a, **k: llm_message(content=next(replies)))
        await add_report(w, "member", "daily", utc(2026, 10, 8, 3, 30))
        await add_report(w, "staff", "daily", utc(2026, 10, 8, 3, 30))
        await tick(w, utc(2026, 10, 8, 4, 0))
        rows = await w.sql("SELECT next_run_at, run_count FROM scheduled_reports")
        assert all(
            r["next_run_at"] > utc(2026, 10, 8, 4, 0) and r["run_count"] == 1
            for r in rows
        )

    qa_run(scenario)


@needs_qa
def test_L04_a_report_that_cannot_be_delivered_does_not_crash_the_job_or_repeat_every_minute(
    caplog,
):
    async def scenario(w):
        script_report_text(w)
        user = await add_report(w, "member", "daily", utc(2026, 10, 8, 3, 30))
        w.fail_sends = lambda to, kind: (
            RuntimeError("429 too many requests") if to == user["phone"] else None
        )
        with caplog.at_level(logging.ERROR):
            await tick(w, utc(2026, 10, 8, 4, 0))
        await tick(w, utc(2026, 10, 8, 4, 1))
        row = await w.one("SELECT next_run_at FROM scheduled_reports")
        assert row["next_run_at"] > utc(2026, 10, 8, 4, 1)
        assert any(r.levelno >= logging.ERROR for r in caplog.records), (
            "the failed delivery was not logged as an error"
        )

    qa_run(scenario)


@needs_qa
def test_H01_two_copies_of_the_scheduler_do_not_run_the_same_job_at_once():
    async def scenario(w):
        from app.scheduler.locks import run_if_free

        ran = []

        async def job():
            ran.append(1)
            await asyncio.sleep(0.3)

        results = await asyncio.gather(
            run_if_free(w.routing, "case_reminders", job),
            run_if_free(w.routing, "case_reminders", job),
        )
        assert sorted(results) == [False, True] and len(ran) == 1
        # H02: after it has finished, the next minute can run it again
        assert await run_if_free(w.routing, "case_reminders", job) is True

    qa_run(scenario)


# ───────────────────────────── H. case reminders ─────────────────────────────

CASE_REMINDERS = {
    "enabled": True,
    "table": "cases",
    "case_number_column": "case_number",
    "title_column": "title",
    "priority_column": "priority",
    "status_column": "status",
    "created_at_column": "created_at",
    "assignee_id_column": "assigned_to_id",
    "complainant_id_column": "complainant_id",
    "reminder_sent_column": "reminder_sent_at",
    "assignee_message_template": "Reminder: {case_number} {title}",
    "complainant_message_template": "Update on {case_number}",
    "closed_values": ["closed"],
}


async def reminders_world(w, **cfg):
    from app.services import reach

    for name in (
        "admin",
        "member",
        "approver",
        "staff",
    ):  # they have written to the bot today: WhatsApp is open
        await reach.record_inbound(getattr(w.ids, f"phone_{name}"))
    await w.run(
        "UPDATE orgs SET settings = settings || $1::jsonb",
        json.dumps({"case_reminders": {**CASE_REMINDERS, **cfg}}),
    )
    await w.run(
        "INSERT INTO priority_tat_rules (org_id, priority, tat_minutes, reminder_threshold_minutes) VALUES ($1, 'medium', 120, 60)",
        w.ids.org_id,
    )


async def add_case(
    w,
    number: str,
    minutes_old: str,
    status="reported",
    assignee="member",
    complainant="approver",
):
    a = await w.user(assignee)
    c = await w.user(complainant)
    await w.run(
        f"INSERT INTO cases (org_id, case_number, title, status, priority, assigned_to_id, complainant_id, created_at) VALUES ($1, $2, $3, $4, 'medium', $5, $6, now() - interval '{minutes_old}')",
        w.ids.org_id,
        number,
        f"title {number}",
        status,
        a["user_id"],
        c["user_id"],
    )


async def reminded(w, number: str) -> bool:
    row = await w.one(
        "SELECT reminder_sent_at FROM cases WHERE case_number = $1", number
    )
    return row["reminder_sent_at"] is not None


@needs_qa
def test_H_control_an_overdue_open_case_gets_one_reminder():
    async def scenario(w):
        from app.scheduler.jobs import run_case_reminders

        await reminders_world(w)
        await add_case(w, "R-1", "3 hours")
        await run_case_reminders()
        await run_case_reminders()
        mine = [t for t in w.texts_to(phone_of(w, "member")) if "R-1" in t]
        assert len(mine) == 1 and await reminded(w, "R-1")

    qa_run(scenario)


@needs_qa
def test_H04_a_closed_case_gets_no_reminder():
    async def scenario(w):
        from app.scheduler.jobs import run_case_reminders

        await reminders_world(w)
        await add_case(w, "R-2", "3 hours", status="closed")
        await run_case_reminders()
        assert not await reminded(w, "R-2")
        assert not [t for t in w.texts_to(phone_of(w, "member")) if "R-2" in t]

    qa_run(scenario)


@needs_qa
def test_D22_the_reminder_comes_just_after_the_threshold_and_not_before():
    async def scenario(w):
        from app.scheduler.jobs import run_case_reminders

        await reminders_world(w)  # medium: remind after 60 minutes
        await add_case(w, "S-59", "59 minutes 30 seconds")
        await add_case(w, "S-60", "60 minutes 5 seconds")
        await add_case(w, "S-61", "61 minutes")
        await run_case_reminders()
        assert [await reminded(w, n) for n in ("S-59", "S-60", "S-61")] == [
            False,
            True,
            True,
        ]

    qa_run(scenario)


@needs_qa
def test_H05_one_reminder_that_cannot_be_sent_does_not_block_or_repeat_the_others():
    async def scenario(w):
        from app.scheduler.jobs import run_case_reminders

        await reminders_world(w)
        await add_case(w, "A-1", "3 hours", complainant="approver")
        await add_case(w, "B-1", "3 hours", complainant="staff")
        approver = phone_of(w, "approver")
        w.fail_sends = lambda to, kind: RuntimeError("429") if to == approver else None
        for _ in range(2):
            try:
                await run_case_reminders()
            except Exception:
                pass  # the job runner catches it; what matters is what happened to the data
        member = phone_of(w, "member")
        repeated = [t for t in w.texts_to(member) if "A-1" in t]
        assert await reminded(w, "B-1"), "the second case never got its reminder"
        assert len(repeated) <= 1, (
            f"the first case's reminder went out {len(repeated)} times"
        )

    qa_run(scenario)


@needs_qa
def test_H05b_a_bad_message_template_does_not_stop_the_pass():
    async def scenario(w):
        from app.scheduler.jobs import run_case_reminders

        await reminders_world(
            w, assignee_message_template="Reminder {case_number} {nope}"
        )
        await add_case(w, "T-1", "3 hours")
        await run_case_reminders()  # must not raise

    qa_run(scenario)


# ───────────────────────────── G. AI-written SQL and stored reports, end to end ─────────────────────────────


async def sql_user(w, tables):
    user = await w.user("admin")
    user["readable_tables"] = list(tables)
    return user


async def ask(w, user, sql: str) -> str:
    from app.services import agent

    return await agent._execute_tool(
        "query_database", {"sql": sql, "params": []}, user, user["phone"]
    )


@needs_qa
def test_G_control_the_ai_sql_tool_answers_a_plain_question_and_blocks_a_secret_column():
    async def scenario(w):
        user = await sql_user(w, ["users", "cases"])
        names = await ask(w, user, "SELECT name FROM users WHERE name LIKE 'Asha%'")
        assert "Asha Admin" in names
        assert "Query blocked" in await ask(w, user, "SELECT otp_hash FROM users")

    qa_run(scenario)


@needs_qa
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT to_jsonb(u) AS who FROM users u",
        "SELECT row_to_json(users) AS who FROM users",
    ],
)
def test_G03_the_ai_sql_tool_never_returns_a_phone_number_or_an_e_mail(sql):
    async def scenario(w):
        user = await sql_user(w, ["users", "cases"])
        out = await ask(w, user, sql)
        assert "+9190000" not in out and "@example.test" not in out, out[:300]

    qa_run(scenario)


@needs_qa
def test_G05_the_ai_sql_tool_can_find_a_person_by_phone_number():
    """The owner's decision: phone numbers and emails are open to the chat bot (see core-0021)."""

    async def scenario(w):
        user = await sql_user(w, ["users", "cases"])
        out = await ask(w, user, "SELECT name FROM users WHERE phone = '+919000000002'")
        assert "Meera Member" in out, out[:200]

    qa_run(scenario)


async def report_user(w):
    user = await w.user("member")
    user["readable_tables"] = ["cases"]
    return user


@needs_qa
def test_G_control_a_stored_report_on_an_allowed_table_works():
    async def scenario(w):
        from app.services.query_engine import execute_query

        await w.run(
            "INSERT INTO cases (org_id, case_number, title, status, priority) VALUES ($1, 'Q-1', 'visible title', 'reported', 'medium')",
            w.ids.org_id,
        )
        out = await execute_query(
            "SELECT title FROM cases WHERE org_id = $1", [], await report_user(w)
        )
        assert "visible title" in out
        refused = await execute_query(
            "SELECT name FROM users WHERE org_id = $1", [], await report_user(w)
        )
        assert refused.startswith("ERROR")

    qa_run(scenario)


@needs_qa
@bug(
    "QA-009",
    "a comma join hides the second table from the permission check, and an alias hides the column from the column filter",
)
def test_G12_a_stored_report_cannot_read_a_table_the_role_may_not_read():
    async def scenario(w):
        from app.services.query_engine import execute_query

        await w.run(
            "INSERT INTO cases (org_id, case_number, title, status, priority) VALUES ($1, 'Q-1', 'x', 'reported', 'medium')",
            w.ids.org_id,
        )
        out = await execute_query(
            "SELECT c.title, u.phone AS contact FROM cases c, users u WHERE c.org_id = $1",
            [],
            await report_user(w),
        )
        assert "+9190000" not in out, out[:200]

    qa_run(scenario)


@needs_qa
@bug(
    "QA-009",
    "the word LIMIT anywhere in the text (even in a column name) switches off the automatic row cap",
)
def test_G12b_a_stored_report_is_capped_at_100_rows_whatever_the_column_is_called():
    async def scenario(w):
        from app.services.query_engine import execute_query

        await w.run(
            "INSERT INTO cases (org_id, case_number, title, status, priority) SELECT $1, 'BULK-' || g, 'bulk', 'reported', 'medium' FROM generate_series(1, 150) g",
            w.ids.org_id,
        )
        out = await execute_query(
            "SELECT title AS limit_label FROM cases WHERE org_id = $1",
            [],
            await report_user(w),
        )
        assert len(json.loads(out)) <= 100, "more than 100 rows came back"

    qa_run(scenario)
