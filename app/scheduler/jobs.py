"""
jobs.py — Universal scheduled report runner.

One job fires every minute. It checks scheduled_reports for anything due,
calls run_agent with the stored query_text, and delivers the result via
WhatsApp (text or PDF) and/or email — same as the user typing the query manually.
"""

import datetime
import json
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import execute, fetch_all, fetch_one, routing_pool
from app.logging_config import get_context_logger
from app.scheduler.locks import run_if_free
from app.services import config_store, reach
from app.services.cleanup import run_cleanup

logger = get_context_logger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
_IST = ZoneInfo("Asia/Kolkata")


# ── Compute next_run_at from a schedule row ──────────────────────────────────


def compute_next_run(row: dict, from_dt: datetime.datetime = None) -> datetime.datetime:
    """
    Given a scheduled_reports row, compute the next UTC datetime it should run.
    from_dt defaults to now (UTC). Returns timezone-aware UTC datetime.
    """
    now = from_dt or datetime.datetime.now(datetime.timezone.utc)
    now_ist = now.astimezone(_IST)
    stype = row["schedule_type"]

    if stype == "minutely":
        interval = int(row.get("interval_minutes") or 1)
        return now + datetime.timedelta(minutes=interval)

    if stype == "hourly":
        minute = int(row.get("minute") or 0)
        next_dt = now_ist.replace(minute=minute, second=0, microsecond=0)
        if next_dt <= now_ist:
            next_dt += datetime.timedelta(hours=1)
        return next_dt.astimezone(datetime.timezone.utc)

    if stype == "daily":
        hour = int(row.get("hour") or 8)
        minute = int(row.get("minute") or 0)
        next_dt = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_dt <= now_ist:
            next_dt += datetime.timedelta(days=1)
        return next_dt.astimezone(datetime.timezone.utc)

    if stype == "weekly":
        hour = int(row.get("hour") or 9)
        minute = int(row.get("minute") or 0)
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        target_dow = day_names.index(str(row.get("day_of_week") or "mon").lower()[:3])
        days_ahead = (target_dow - now_ist.weekday()) % 7
        next_dt = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
        next_dt += datetime.timedelta(days=days_ahead)
        if next_dt <= now_ist:
            next_dt += datetime.timedelta(weeks=1)
        return next_dt.astimezone(datetime.timezone.utc)

    if stype == "monthly":
        import calendar

        hour = int(row.get("hour") or 9)
        minute = int(row.get("minute") or 0)
        day_of_month = int(row.get("day_of_month") or 1)
        last_day = calendar.monthrange(now_ist.year, now_ist.month)[1]
        day_of_month = min(day_of_month, last_day)
        next_dt = now_ist.replace(
            day=day_of_month, hour=hour, minute=minute, second=0, microsecond=0
        )
        if next_dt <= now_ist:
            if now_ist.month == 12:
                next_dt = next_dt.replace(year=now_ist.year + 1, month=1)
            else:
                next_dt = next_dt.replace(month=now_ist.month + 1)
        return next_dt.astimezone(datetime.timezone.utc)

    return now + datetime.timedelta(days=1)


# ── Main scheduled job — runs every minute ───────────────────────────────────


async def run_scheduled_reports():
    """
    Fires every minute. Finds all active scheduled_reports whose next_run_at
    is <= now, runs each via run_agent, delivers result, updates next_run_at.
    """
    from app.db import get_all_source_keys

    now = datetime.datetime.now(datetime.timezone.utc)
    logger.debug(f"Tick at {now.strftime('%H:%M:%S')} UTC")

    # Get all source keys and query each one
    source_keys = await get_all_source_keys()
    all_due = []

    for source_key in source_keys:
        try:
            due = await fetch_all(
                """
                SELECT sr.*, u.name as user_name, u.role_id, u.email as user_email,
                       o.name as org_name, o.gst_rate,
                       r.permissions, r.name as role_name
                FROM scheduled_reports sr
                JOIN users u ON u.id = sr.user_id
                JOIN orgs  o ON o.id = sr.org_id
                JOIN roles r ON r.id = u.role_id
                WHERE sr.is_active = true
                  AND sr.next_run_at <= $1
            """,
                now,
                source_key=source_key,
            )
        except Exception as e:
            # Table might not exist in some databases, or this source's DB
            # might be temporarily unreachable — either way, one bad source
            # must not stop every other org's scheduled reports from running
            # this tick (this used to only skip on a missing-table message
            # and re-raise everything else, which aborted the whole job).
            logger.warning(
                f"run_scheduled_reports: could not load due reports for source_key={source_key}: {e}"
            )
            continue

        # Add source_key to each row for later use
        for row in due:
            row_dict = dict(row)
            row_dict["source_key"] = source_key
            all_due.append(row_dict)

    if not all_due:
        return

    logger.info(f"{len(all_due)} report(s) due")

    from app.services.agent import run_agent

    for row in all_due:
        report_id = str(row["id"])
        phone = row["phone"]
        query_text = row["query_text"]
        label = row["report_label"]
        delivery = row["delivery"]

        try:
            logger.info(f"Running '{label}' for {phone}")

            user = {
                "user_id": str(row["user_id"]),
                "org_id": str(row["org_id"]),
                "user_name": row["user_name"],
                "org_name": row["org_name"],
                "role": row.get("role_name", "member"),
                "role_id": str(row["role_id"]),
                "permissions": list(row["permissions"] or []),
                "phone": phone,
                "email": row.get("email") or row.get("user_email") or "",
                "org_active": True,
                "is_active": True,
                "source_key": row.get("source_key", "platform"),
            }

            # A WhatsApp report goes only to someone who wrote to the chat bot in the last 24 hours;
            # otherwise WhatsApp accepts it and never delivers it. Then it goes by email instead, with
            # the way to get the next ones on WhatsApp (see reach.py).
            closed = False
            if delivery in ("whatsapp", "both") and reach.is_whatsapp(phone):
                org_settings = await config_store.org_settings(
                    row.get("source_key"), row["org_id"]
                )
                closed = reach.feature_on(org_settings) and not await reach.door_open(
                    phone, row.get("source_key"), row["org_id"], settings=org_settings
                )
            if closed:
                user["force_send_via"] = "email"
                user["email_note_html"] = await reach.footer_html(
                    row.get("source_key"), org_settings
                )
                effective_query = query_text + " — email only"
            elif delivery == "email":
                effective_query = query_text + " — email only"
            elif delivery == "both":
                effective_query = query_text + " — send to both whatsapp and email"
            else:
                effective_query = query_text

            reply, _history, _patch = await run_agent(
                message=effective_query,
                user=user,
                phone=phone,
                conversation_history=[],
                pending_action=None,
            )

            if delivery in ("whatsapp", "both") and not user.get("_report_emailed"):
                header = f"🕐 *Scheduled: {label}*\n\n"
                await reach.deliver_text(
                    phone,
                    header + reply,
                    source_key=row.get("source_key"),
                    org_id=row["org_id"],
                    org_name=row.get("org_name") or "",
                    replace=report_id,
                )

            next_run = compute_next_run(dict(row), from_dt=now)
            await execute(
                """
                UPDATE scheduled_reports
                SET last_run_at = $1,
                    next_run_at = $2,
                    run_count   = run_count + 1
                WHERE id = $3
            """,
                now,
                next_run,
                report_id,
                source_key=row.get("source_key", "platform"),
            )

            logger.info(
                f"'{label}' done. Next: {next_run.astimezone(_IST).strftime('%d %b %H:%M IST')}"
            )

        except Exception as e:
            import traceback

            logger.error(f"Error running '{label}' for {phone}: {e}")
            traceback.print_exc()
            try:
                next_run = compute_next_run(dict(row), from_dt=now)
                await execute(
                    "UPDATE scheduled_reports SET next_run_at = $1 WHERE id = $2",
                    next_run,
                    report_id,
                    source_key=row.get("source_key", "platform"),
                )
            except Exception as reschedule_err:
                logger.error(
                    f"Failed to reschedule '{label}' after error: {reschedule_err}"
                )


async def run_case_reminders():
    """
    Fires every minute. Runs TWO fire-once passes per org, both driven by
    orgs.settings->'case_reminders':
      1. "reminder"   — threshold = reminder_threshold_minutes
      2. "tat_breach" — threshold = tat_minutes (the case's full TAT);
         only runs if the org has configured tat_breach_sent_column.
    Same mechanism, different threshold column / sent-column / templates.
    """
    from app.db import get_all_source_keys

    source_keys = await get_all_source_keys()

    for source_key in source_keys:
        try:
            orgs = await fetch_all(
                "SELECT id, settings FROM orgs WHERE is_active = true",
                source_key=source_key,
            )
        except Exception as e:
            logger.warning(
                f"run_case_reminders: could not load orgs for source_key={source_key}: {e}"
            )
            continue

        for org in orgs:
            settings = org["settings"]
            if isinstance(settings, str):
                settings = json.loads(settings)
            cfg = (settings or {}).get("case_reminders")
            if not cfg or not cfg.get("enabled"):
                continue
            if config_store.setting(settings, "reminders.enabled", False) is True:
                continue  # its reminder plans run instead (app/services/reminder_plans.py)

            org_id = str(org["id"])

            await _run_case_notification_pass(
                org_id=org_id,
                cfg=cfg,
                source_key=source_key,
                minutes_col="reminder_threshold_minutes",
                sent_col_key="reminder_sent_column",
                assignee_tmpl_key="assignee_message_template",
                complainant_tmpl_key="complainant_message_template",
            )
            if cfg.get("tat_breach_sent_column"):
                await _run_case_notification_pass(
                    org_id=org_id,
                    cfg=cfg,
                    source_key=source_key,
                    minutes_col="tat_minutes",
                    sent_col_key="tat_breach_sent_column",
                    assignee_tmpl_key="assignee_tat_message_template",
                    complainant_tmpl_key="complainant_tat_message_template",
                )


# A case whose reminder could not reach anybody is tried again on the next pass, but not for ever.
# case -> passes in which nobody could be reached (the limit is a setting: reminder_max_failures)
_reminder_failures: dict[tuple, int] = {}
_bad_templates_logged: set[tuple[str, str]] = set()


class _BlankValues(dict):
    """Values missing from a message template read as empty, and are remembered."""

    def __init__(self, values: dict):
        super().__init__(values)
        self.missing: set[str] = set()

    def __missing__(self, key):
        self.missing.add(key)
        return ""


def _fill_reminder(template: str, vals: dict, label: str) -> str:
    """The reminder text with the case's values in it. A template with an unknown {name} or a stray
    brace must never stop the pass: the unknown part is left empty and the template is named in the
    log, once."""
    values = _BlankValues(vals)
    problem = ""
    try:
        text = template.format_map(values)
        if values.missing:
            problem = (
                f"uses values that do not exist: {', '.join(sorted(values.missing))}"
            )
    except (ValueError, IndexError, KeyError, AttributeError) as e:
        text, problem = template, f"cannot be filled in ({e})"
    if problem and (label, template) not in _bad_templates_logged:
        _bad_templates_logged.add((label, template))
        logger.error(
            f"the case reminder message '{label}' {problem}; it is sent with those parts empty"
        )
    return text


async def _run_case_notification_pass(
    org_id: str,
    cfg: dict,
    source_key: str,
    minutes_col: str,
    sent_col_key: str,
    assignee_tmpl_key: str,
    complainant_tmpl_key: str,
):
    """One fire-once notification pass — see run_case_reminders() above."""
    from app.services.step_interpreter import (
        _load_schema_allowlist,
        _validate_identifier,
    )

    table = cfg["table"]
    sent_column = cfg.get(sent_col_key)
    if not sent_column:
        return

    col_keys = [
        "case_number_column",
        "title_column",
        "priority_column",
        "status_column",
        "created_at_column",
        "assignee_id_column",
        "complainant_id_column",
    ]
    cols = [cfg[k] for k in col_keys] + [sent_column]

    allowlist = await _load_schema_allowlist(source_key)
    _validate_identifier(table, "table name")
    if table not in allowlist:
        return
    for c in cols:
        _validate_identifier(c, "column name")
        if c not in allowlist[table]:
            return

    # The SLA-rules table name used to be a hardcoded literal ("priority_tat_rules")
    # in the JOIN below — every other identifier in this query is config-driven
    # and schema-validated, this one wasn't. An org that enables case_reminders
    # without a matching table (or with different column names) would raise a
    # SQL error here that propagated straight up through run_case_reminders'
    # for-loop, aborting the notification pass for every org still queued in
    # that same minute-tick. Config-driven + validated like the rest, and a
    # missing/mismatched table now skips just this org's pass instead.
    tat_table = cfg.get("tat_rules_table", "priority_tat_rules")
    _validate_identifier(tat_table, "table name")
    if (
        tat_table not in allowlist
        or "org_id" not in allowlist[tat_table]
        or "priority" not in allowlist[tat_table]
        or minutes_col not in allowlist[tat_table]
    ):
        return

    closed_values = cfg.get("closed_values", ["closed"])

    sql = f"""
        SELECT t.{cfg["case_number_column"]} AS case_number,
               t.{cfg["title_column"]} AS title,
               t.{cfg["priority_column"]} AS priority,
               t.{cfg["status_column"]} AS status,
               t.{cfg["assignee_id_column"]} AS assignee_id,
               t.{cfg["complainant_id_column"]} AS complainant_id,
               t.id AS row_id
        FROM {table} t
        JOIN {tat_table} ptr
          ON ptr.org_id = t.org_id AND ptr.priority = t.{cfg["priority_column"]}
        WHERE t.org_id = $1
          AND t.{cfg["status_column"]} != ALL($2)
          AND t.{sent_column} IS NULL
          AND t.{cfg["created_at_column"]} + (ptr.{minutes_col} || ' minutes')::interval <= now()
    """
    due = await fetch_all(sql, org_id, closed_values, source_key=source_key)

    from app.services.telegram import TelegramRateLimitedError

    org_name = ""
    try:
        found = await fetch_one(
            "SELECT name FROM orgs WHERE id = $1", org_id, source_key=source_key
        )
        org_name = (found or {}).get("name") or ""
    except Exception as e:
        logger.debug(f"case reminder: organisation name not read: {e}")

    max_failures = config_store.limit_of(
        await config_store.org_settings(source_key, org_id), "reminder_max_failures"
    )
    live = {(source_key, table, sent_column, str(r["row_id"])) for r in due}
    for stale in [
        k
        for k in _reminder_failures
        if k[:3] == (source_key, table, sent_column) and k not in live
    ]:
        _reminder_failures.pop(stale, None)  # the case was closed or reminded meanwhile

    for row in due:
        case_key = (source_key, table, sent_column, str(row["row_id"]))
        vals = dict(row)
        sent_any = failed = paused = False
        targets: list[tuple[str, str, str]] = []  # (phone, which message, its text)
        try:
            assignee = (
                await fetch_one(
                    "SELECT phone FROM users WHERE id = $1",
                    row["assignee_id"],
                    source_key=source_key,
                )
                if row["assignee_id"]
                else None
            )
            complainant = (
                await fetch_one(
                    "SELECT phone FROM users WHERE id = $1",
                    row["complainant_id"],
                    source_key=source_key,
                )
                if row["complainant_id"]
                else None
            )
            assignee_tmpl = cfg.get(assignee_tmpl_key)
            complainant_tmpl = cfg.get(complainant_tmpl_key)
            if assignee and assignee["phone"] and assignee_tmpl:
                targets.append((assignee["phone"], assignee_tmpl_key, assignee_tmpl))
            # Self-assigned case: assignee == complainant. Don't send the same
            # person two near-identical messages — they already got the
            # assignee-role one above.
            same_person = (
                assignee and complainant and assignee["phone"] == complainant["phone"]
            )
            if (
                complainant
                and complainant["phone"]
                and complainant_tmpl
                and not same_person
            ):
                targets.append(
                    (complainant["phone"], complainant_tmpl_key, complainant_tmpl)
                )
        except Exception as e:
            logger.error(
                f"case reminder: could not look up the people of case {row['case_number']}: {e}"
            )
            failed = True

        # Each person is told in a try of its own: one who cannot be reached must not stop the others,
        # and must not make the ones already told hear it again on the next pass.
        for phone, label, template in targets:
            try:
                # a person on WhatsApp who has not written in 24 hours is emailed it (and it waits for them);
                # that still counts as reached
                await reach.deliver_text(
                    phone,
                    _fill_reminder(template, vals, label),
                    source_key=source_key,
                    org_id=org_id,
                    org_name=org_name,
                )
                sent_any = True
            except TelegramRateLimitedError as e:
                logger.warning(
                    f"case reminders paused: Telegram is limiting the bot (retry after {e.retry_after}s)"
                )
                paused = True
                break
            except Exception as e:
                failed = True
                logger.warning(
                    f"case reminder for case {row['case_number']} could not be sent: {e}"
                )

        if paused and not sent_any:
            return  # nothing counted against the case; the next pass starts here again
        if failed and not sent_any and not paused:
            count = _reminder_failures.get(case_key, 0) + 1
            if count < max_failures:
                _reminder_failures[case_key] = count
                continue  # nobody reached: try again on the next pass
            logger.error(
                f"case reminder for case {row['case_number']} could not be sent in {count} passes; giving up on it"
            )
        _reminder_failures.pop(case_key, None)
        try:
            await execute(
                f"UPDATE {table} SET {sent_column} = now() WHERE id = $1",
                row["row_id"],
                source_key=source_key,
            )
        except Exception as e:
            logger.error(
                f"case reminder: could not mark case {row['case_number']} as sent: {e}"
            )
        if paused:
            return


# ── Schedule management helpers ───────────────────────────────────────────────


async def create_scheduled_report(
    org_id,
    user_id,
    phone,
    email,
    query_text,
    report_label,
    schedule_type,
    delivery="whatsapp",
    interval_minutes=None,
    hour=None,
    minute=0,
    day_of_week=None,
    day_of_month=None,
    source_key=None,
) -> dict:
    if not source_key:
        raise ValueError("create_scheduled_report: source_key is required")
    row = {
        "schedule_type": schedule_type,
        "interval_minutes": interval_minutes,
        "hour": hour,
        "minute": minute,
        "day_of_week": day_of_week,
        "day_of_month": day_of_month,
    }
    next_run = compute_next_run(row)
    rec = await fetch_one(
        """
        INSERT INTO scheduled_reports (
            org_id, user_id, phone, email, query_text, report_label,
            schedule_type, interval_minutes, hour, minute,
            day_of_week, day_of_month, delivery, is_active, next_run_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,true,$14)
        RETURNING id, next_run_at
    """,
        org_id,
        user_id,
        phone,
        email or "",
        query_text,
        report_label,
        schedule_type,
        interval_minutes,
        hour,
        minute,
        day_of_week,
        day_of_month,
        delivery,
        next_run,
        source_key=source_key,
    )
    return {"id": str(rec["id"]), "next_run_at": rec["next_run_at"]}


async def list_scheduled_reports(user_id: str, source_key: str = None) -> list:
    if not source_key:
        raise ValueError("list_scheduled_reports: source_key is required")
    rows = await fetch_all(
        """
        SELECT id, report_label, schedule_type, interval_minutes,
               hour, minute, day_of_week, day_of_month,
               delivery, is_active, next_run_at, last_run_at, run_count
        FROM scheduled_reports WHERE user_id = $1 ORDER BY created_at DESC
    """,
        user_id,
        source_key=source_key,
    )
    return [dict(r) for r in rows]


async def pause_scheduled_report(
    report_id: str, user_id: str, source_key: str = None
) -> bool:
    if not source_key:
        raise ValueError("pause_scheduled_report: source_key is required")
    result = await fetch_one(
        """
        UPDATE scheduled_reports SET is_active = false
        WHERE id = $1 AND user_id = $2 RETURNING id
    """,
        report_id,
        user_id,
        source_key=source_key,
    )
    return result is not None


async def resume_scheduled_report(
    report_id: str, user_id: str, source_key: str = None
) -> bool:
    if not source_key:
        raise ValueError("resume_scheduled_report: source_key is required")
    now = datetime.datetime.now(datetime.timezone.utc)
    row = await fetch_one(
        "SELECT * FROM scheduled_reports WHERE id = $1 AND user_id = $2",
        report_id,
        user_id,
        source_key=source_key,
    )
    if not row:
        return False
    next_run = compute_next_run(dict(row), from_dt=now)
    await execute(
        """
        UPDATE scheduled_reports SET is_active = true, next_run_at = $1
        WHERE id = $2 AND user_id = $3
    """,
        next_run,
        report_id,
        user_id,
        source_key=source_key,
    )
    return True


async def delete_scheduled_report(
    report_id: str, user_id: str, source_key: str = None
) -> bool:
    if not source_key:
        raise ValueError("delete_scheduled_report: source_key is required")
    result = await fetch_one(
        """
        DELETE FROM scheduled_reports WHERE id = $1 AND user_id = $2 RETURNING id
    """,
        report_id,
        user_id,
        source_key=source_key,
    )
    return result is not None


# ── Scheduler startup/shutdown ────────────────────────────────────────────────


async def _tick(name: str, job):
    """One run of a scheduled job. Only one copy of the app may run it at a time (see locks.py):
    a copy that finds another one already running it skips this run.
    A hard 50-second timeout prevents any job from blocking the next minute's run."""
    import asyncio

    async def _run():
        if not await run_if_free(routing_pool(), name, job):
            logger.debug(f"{name}: another copy of the app is running it, skipping")

    try:
        await asyncio.wait_for(_run(), timeout=50)
    except asyncio.TimeoutError:
        logger.error(
            f"{name}: job exceeded 50-second limit and was cancelled — "
            "check for a slow DB query or stuck network call"
        )


async def _tick_scheduled_reports():
    await _tick("scheduled_reports", run_scheduled_reports)


async def _tick_case_reminders():
    await _tick("case_reminders", run_case_reminders)


async def _tick_reminder_plans():
    from app.services.reminder_plans import run_reminder_plans

    await _tick("reminder_plans", run_reminder_plans)


async def run_flow_schedules():
    """Fires every minute: runs the flows whose schedule is due (see services/flow_triggers.py)."""
    from app.services import flow_triggers

    started = await flow_triggers.run_due_schedules(
        datetime.datetime.now(datetime.timezone.utc)
    )
    if started:
        logger.info(f"{started} scheduled flow(s) started")


async def _tick_flow_schedules():
    await _tick("flow_schedules", run_flow_schedules)


async def run_announcements():
    """Fires every minute: sends the announcements whose time has come (see services/announcements.py)."""
    from app.services import announcements

    tried = await announcements.run_due()
    if tried:
        logger.info(f"announcements: {tried} people reached this minute")


async def _tick_announcements():
    await _tick("announcements", run_announcements)


async def _tick_cleanup():
    await _tick("cleanup", run_cleanup)


async def _tidy_panel_keys():
    """Remove dashboard sign-in codes and sessions that can never be used again (nothing else)."""
    from app.admin_panel.auth import tidy_keys

    removed = await tidy_keys()
    if removed:
        logger.info(f"sign-in: removed {removed} codes and sessions that had ended")


async def _tick_panel_keys():
    await _tick("panel_keys", _tidy_panel_keys)


async def _update_whatsapp_commands():
    from app.services import whatsapp_commands

    outcome = await whatsapp_commands.sync()
    if outcome.startswith(("synced", "failed")):
        logger.info(f"whatsapp commands: {outcome}")


async def _tick_whatsapp_commands():
    await _tick("whatsapp_commands", _update_whatsapp_commands)


def start_scheduler():
    scheduler.add_job(
        _tick_scheduled_reports,
        trigger=CronTrigger(minute="*", timezone="Asia/Kolkata"),
        id="universal_scheduled_reports",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _tick_case_reminders,
        trigger=CronTrigger(minute="*", timezone="Asia/Kolkata"),
        id="case_reminders",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _tick_reminder_plans,
        trigger=CronTrigger(minute="*", timezone="Asia/Kolkata"),
        id="reminder_plans",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _tick_flow_schedules,
        trigger=CronTrigger(minute="*", timezone="Asia/Kolkata"),
        id="flow_schedules",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _tick_announcements,
        trigger=CronTrigger(minute="*", timezone="Asia/Kolkata"),
        id="announcements",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _tick_cleanup,
        trigger=CronTrigger(hour=3, minute=30, timezone="Asia/Kolkata"),
        id="cleanup",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _tick_panel_keys,
        trigger=CronTrigger(hour=3, minute=40, timezone="Asia/Kolkata"),
        id="panel_keys",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _tick_whatsapp_commands,
        trigger=CronTrigger(minute="*/10", timezone="Asia/Kolkata"),
        id="whatsapp_commands",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        "Started — universal runner + case reminders + flow schedules every minute, cleanup daily at 03:30, "
        "sign-in keys at 03:40"
    )


def stop_scheduler():
    scheduler.shutdown()
