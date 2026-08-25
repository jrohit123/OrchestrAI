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

from app.db import fetch_all, execute, fetch_one
from app.services.messaging import send_text

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
        hour   = int(row.get("hour") or 8)
        minute = int(row.get("minute") or 0)
        next_dt = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_dt <= now_ist:
            next_dt += datetime.timedelta(days=1)
        return next_dt.astimezone(datetime.timezone.utc)

    if stype == "weekly":
        hour       = int(row.get("hour") or 9)
        minute     = int(row.get("minute") or 0)
        day_names  = ["mon","tue","wed","thu","fri","sat","sun"]
        target_dow = day_names.index(str(row.get("day_of_week") or "mon").lower()[:3])
        days_ahead = (target_dow - now_ist.weekday()) % 7
        next_dt = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
        next_dt += datetime.timedelta(days=days_ahead)
        if next_dt <= now_ist:
            next_dt += datetime.timedelta(weeks=1)
        return next_dt.astimezone(datetime.timezone.utc)

    if stype == "monthly":
        import calendar
        hour         = int(row.get("hour") or 9)
        minute       = int(row.get("minute") or 0)
        day_of_month = int(row.get("day_of_month") or 1)
        last_day = calendar.monthrange(now_ist.year, now_ist.month)[1]
        day_of_month = min(day_of_month, last_day)
        next_dt = now_ist.replace(day=day_of_month, hour=hour, minute=minute, second=0, microsecond=0)
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
    print(f"[SCHEDULER] Tick at {now.strftime('%H:%M:%S')} UTC")

    # Get all source keys and query each one
    source_keys = await get_all_source_keys()
    all_due = []

    for source_key in source_keys:
        try:
            due = await fetch_all("""
                SELECT sr.*, u.name as user_name, u.role_id,
                       o.name as org_name, o.gst_rate,
                       r.permissions, r.name as role_name
                FROM scheduled_reports sr
                JOIN users u ON u.id = sr.user_id
                JOIN orgs  o ON o.id = sr.org_id
                JOIN roles r ON r.id = u.role_id
                WHERE sr.is_active = true
                  AND sr.next_run_at <= $1
            """, now, source_key=source_key)
        except Exception as e:
            # Table might not exist in some databases
            if "scheduled_reports" in str(e):
                continue
            raise
        
        # Add source_key to each row for later use
        for row in due:
            row_dict = dict(row)
            row_dict["source_key"] = source_key
            all_due.append(row_dict)

    if not all_due:
        return

    print(f"[SCHEDULER] {len(all_due)} report(s) due")

    from app.services.agent import run_agent

    for row in all_due:
        report_id  = str(row["id"])
        phone      = row["phone"]
        query_text = row["query_text"]
        label      = row["report_label"]
        delivery   = row["delivery"]

        try:
            print(f"[SCHEDULER] Running '{label}' for {phone}")

            user = {
                "user_id":    str(row["user_id"]),
                "org_id":     str(row["org_id"]),
                "user_name":  row["user_name"],
                "org_name":   row["org_name"],
                "role":       row.get("role_name", "member"),
                "role_id":    str(row["role_id"]),
                "permissions": list(row["permissions"] or []),
                "phone":      phone,
                "email":      row.get("email") or "",
                "org_active": True,
                "is_active":  True,
                "source_key": row.get("source_key", "platform"),
            }

            if delivery == "email":
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

            if delivery in ("whatsapp", "both"):
                header = f"🕐 *Scheduled: {label}*\n\n"
                await send_text(phone, header + reply)

            next_run = compute_next_run(dict(row), from_dt=now)
            await execute("""
                UPDATE scheduled_reports
                SET last_run_at = $1,
                    next_run_at = $2,
                    run_count   = run_count + 1
                WHERE id = $3
            """, now, next_run, report_id, source_key=row.get("source_key", "platform"))

            print(f"[SCHEDULER] ✅ '{label}' done. Next: {next_run.astimezone(_IST).strftime('%d %b %H:%M IST')}")

        except Exception as e:
            import traceback
            print(f"[SCHEDULER] ❌ Error running '{label}' for {phone}: {e}")
            traceback.print_exc()
            try:
                next_run = compute_next_run(dict(row), from_dt=now)
                await execute(
                    "UPDATE scheduled_reports SET next_run_at = $1 WHERE id = $2",
                    next_run, report_id, source_key=row.get("source_key", "platform")
                )
            except Exception:
                pass


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
                source_key=source_key
            )
        except Exception:
            continue

        for org in orgs:
            settings = org["settings"]
            if isinstance(settings, str):
                settings = json.loads(settings)
            cfg = (settings or {}).get("case_reminders")
            if not cfg or not cfg.get("enabled"):
                continue

            org_id = str(org["id"])

            await _run_case_notification_pass(
                org_id=org_id, cfg=cfg, source_key=source_key,
                minutes_col="reminder_threshold_minutes",
                sent_col_key="reminder_sent_column",
                assignee_tmpl_key="assignee_message_template",
                complainant_tmpl_key="complainant_message_template",
            )
            if cfg.get("tat_breach_sent_column"):
                await _run_case_notification_pass(
                    org_id=org_id, cfg=cfg, source_key=source_key,
                    minutes_col="tat_minutes",
                    sent_col_key="tat_breach_sent_column",
                    assignee_tmpl_key="assignee_tat_message_template",
                    complainant_tmpl_key="complainant_tat_message_template",
                )


async def _run_case_notification_pass(
    org_id: str, cfg: dict, source_key: str,
    minutes_col: str, sent_col_key: str,
    assignee_tmpl_key: str, complainant_tmpl_key: str,
):
    """One fire-once notification pass — see run_case_reminders() above."""
    from app.services.step_interpreter import _load_schema_allowlist, _validate_identifier

    table = cfg["table"]
    sent_column = cfg.get(sent_col_key)
    if not sent_column:
        return

    col_keys = [
        "case_number_column", "title_column", "priority_column",
        "status_column", "created_at_column",
        "assignee_id_column", "complainant_id_column",
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

    closed_values = cfg.get("closed_values", ["closed"])

    sql = f"""
        SELECT t.{cfg['case_number_column']} AS case_number,
               t.{cfg['title_column']} AS title,
               t.{cfg['priority_column']} AS priority,
               t.{cfg['status_column']} AS status,
               t.{cfg['assignee_id_column']} AS assignee_id,
               t.{cfg['complainant_id_column']} AS complainant_id,
               t.id AS row_id
        FROM {table} t
        JOIN priority_tat_rules ptr
          ON ptr.org_id = t.org_id AND ptr.priority = t.{cfg['priority_column']}
        WHERE t.org_id = $1
          AND t.{cfg['status_column']} != ALL($2)
          AND t.{sent_column} IS NULL
          AND t.{cfg['created_at_column']} + (ptr.{minutes_col} || ' minutes')::interval <= now()
    """
    due = await fetch_all(sql, org_id, closed_values, source_key=source_key)

    for row in due:
        assignee = (
            await fetch_one("SELECT phone FROM users WHERE id = $1",
                             row["assignee_id"], source_key=source_key)
            if row["assignee_id"] else None
        )
        complainant = (
            await fetch_one("SELECT phone FROM users WHERE id = $1",
                             row["complainant_id"], source_key=source_key)
            if row["complainant_id"] else None
        )

        vals = dict(row)
        assignee_tmpl    = cfg.get(assignee_tmpl_key)
        complainant_tmpl = cfg.get(complainant_tmpl_key)

        if assignee and assignee["phone"] and assignee_tmpl:
            await send_text(assignee["phone"], assignee_tmpl.format(**vals))

        # Self-assigned case: assignee == complainant. Don't send the same
        # person two near-identical messages — they already got the
        # assignee-role one above.
        same_person = (
            assignee and complainant
            and assignee["phone"] == complainant["phone"]
        )
        if complainant and complainant["phone"] and complainant_tmpl and not same_person:
            await send_text(complainant["phone"], complainant_tmpl.format(**vals))

        await execute(
            f"UPDATE {table} SET {sent_column} = now() WHERE id = $1",
            row["row_id"], source_key=source_key
        )


# ── Schedule management helpers ───────────────────────────────────────────────

async def create_scheduled_report(
    org_id, user_id, phone, email, query_text, report_label,
    schedule_type, delivery="whatsapp", interval_minutes=None,
    hour=None, minute=0, day_of_week=None, day_of_month=None,
    source_key=None,
) -> dict:
    if not source_key:
        raise ValueError("create_scheduled_report: source_key is required")
    row = {
        "schedule_type": schedule_type, "interval_minutes": interval_minutes,
        "hour": hour, "minute": minute,
        "day_of_week": day_of_week, "day_of_month": day_of_month,
    }
    next_run = compute_next_run(row)
    rec = await fetch_one("""
        INSERT INTO scheduled_reports (
            org_id, user_id, phone, email, query_text, report_label,
            schedule_type, interval_minutes, hour, minute,
            day_of_week, day_of_month, delivery, is_active, next_run_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,true,$14)
        RETURNING id, next_run_at
    """, org_id, user_id, phone, email or "", query_text, report_label,
        schedule_type, interval_minutes, hour, minute,
        day_of_week, day_of_month, delivery, next_run,
        source_key=source_key)
    return {"id": str(rec["id"]), "next_run_at": rec["next_run_at"]}


async def list_scheduled_reports(user_id: str, source_key: str = None) -> list:
    if not source_key:
        raise ValueError("list_scheduled_reports: source_key is required")
    rows = await fetch_all("""
        SELECT id, report_label, schedule_type, interval_minutes,
               hour, minute, day_of_week, day_of_month,
               delivery, is_active, next_run_at, last_run_at, run_count
        FROM scheduled_reports WHERE user_id = $1 ORDER BY created_at DESC
    """, user_id, source_key=source_key)
    return [dict(r) for r in rows]


async def pause_scheduled_report(report_id: str, user_id: str, source_key: str = None) -> bool:
    if not source_key:
        raise ValueError("pause_scheduled_report: source_key is required")
    result = await fetch_one("""
        UPDATE scheduled_reports SET is_active = false
        WHERE id = $1 AND user_id = $2 RETURNING id
    """, report_id, user_id, source_key=source_key)
    return result is not None


async def resume_scheduled_report(report_id: str, user_id: str, source_key: str = None) -> bool:
    if not source_key:
        raise ValueError("resume_scheduled_report: source_key is required")
    now = datetime.datetime.now(datetime.timezone.utc)
    row = await fetch_one(
        "SELECT * FROM scheduled_reports WHERE id = $1 AND user_id = $2",
        report_id, user_id, source_key=source_key
    )
    if not row:
        return False
    next_run = compute_next_run(dict(row), from_dt=now)
    await execute("""
        UPDATE scheduled_reports SET is_active = true, next_run_at = $1
        WHERE id = $2 AND user_id = $3
    """, next_run, report_id, user_id, source_key=source_key)
    return True


async def delete_scheduled_report(report_id: str, user_id: str, source_key: str = None) -> bool:
    if not source_key:
        raise ValueError("delete_scheduled_report: source_key is required")
    result = await fetch_one("""
        DELETE FROM scheduled_reports WHERE id = $1 AND user_id = $2 RETURNING id
    """, report_id, user_id, source_key=source_key)
    return result is not None


# ── Scheduler startup/shutdown ────────────────────────────────────────────────

def start_scheduler():
    scheduler.add_job(
        run_scheduled_reports,
        trigger=CronTrigger(minute="*", timezone="Asia/Kolkata"),
        id="universal_scheduled_reports",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_case_reminders,
        trigger=CronTrigger(minute="*", timezone="Asia/Kolkata"),
        id="case_reminders",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    print("[SCHEDULER] Started — universal runner + case reminders every minute")


def stop_scheduler():
    scheduler.shutdown()
