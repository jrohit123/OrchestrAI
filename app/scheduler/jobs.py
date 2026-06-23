import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.db import fetch_all
from app.services.whatsapp import send_text

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


async def send_weekly_dues_report():
    print("[SCHEDULER] Running dues report...")
    from app.adapters.crm import get_all_overdue

    workflows = await fetch_all("""
        SELECT org_id, scheduled_by
        FROM workflows
        WHERE intent_key = 'weekly_dues_report' AND is_scheduled = true
    """)

    for wf in workflows:
        try:
            user = await fetch_one("""
                SELECT u.phone, u.name, o.name as org_name
                FROM users u
                JOIN orgs o ON o.id = u.org_id
                WHERE u.id = $1 AND u.is_active = true AND u.phone IS NOT NULL
            """, wf["scheduled_by"])

            if not user:
                print(f"[SCHEDULER] User {wf['scheduled_by']} not found or inactive")
                continue

            report = await get_all_overdue(str(wf["org_id"]))
            message = (
                f"📊 *Scheduled Dues Report — {user['org_name']}*\n\n"
                + (report["message"] if report["count"] > 0
                   else "✅ No overdue invoices. All clear!")
            )
            await send_text(user["phone"], message)
            print(f"[SCHEDULER] Sent to {user['name']} ({user['org_name']})")
        except Exception as e:
            print(f"[SCHEDULER] Error for workflow: {e}")


def reschedule_dues_report(day_of_week: str, hour: int, minute: int = 0):
    """Reschedule dues report job at runtime — no restart needed."""
    trigger_kwargs = {"hour": hour, "minute": minute, "timezone": "Asia/Kolkata"}
    if day_of_week != "*":
        trigger_kwargs["day_of_week"] = day_of_week

    scheduler.add_job(
        send_weekly_dues_report,
        trigger=CronTrigger(**trigger_kwargs),
        id="weekly_dues_report",
        replace_existing=True
    )
    print(f"[SCHEDULER] Rescheduled → day={day_of_week} hour={hour}")


def stop_dues_report():
    """Pause the scheduled job."""
    job = scheduler.get_job("weekly_dues_report")
    if job:
        job.pause()
        print("[SCHEDULER] Dues report paused")


def resume_dues_report(day_of_week: str = "mon", hour: int = 9):
    """Resume or restart the job."""
    reschedule_dues_report(day_of_week, hour)


def get_job_schedule() -> str:
    """Return human readable current schedule."""
    job = scheduler.get_job("weekly_dues_report")
    if not job or job.next_run_time is None:
        return "not scheduled"
    return str(job.next_run_time.strftime("%A %d %b %Y at %I:%M %p IST"))


def start_scheduler():
    reschedule_dues_report("mon", 9)
    scheduler.start()
    print("[SCHEDULER] Started — default Monday 9AM IST")


def stop_scheduler():
    scheduler.shutdown()
