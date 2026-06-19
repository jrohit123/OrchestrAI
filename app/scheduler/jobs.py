"""
Scheduled jobs for OrchestrAI.
Weekly dues report: every Monday 9AM IST → sends summary to org owner via WhatsApp.

To run the scheduler, APScheduler starts automatically with the FastAPI app.
No separate process needed.
"""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import fetch_all
from app.adapters.crm import get_all_overdue
from app.services.whatsapp import send_text


scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


async def send_weekly_dues_report():
    """
    Runs every Monday at 9AM IST.
    Fetches all active orgs → sends dues report to owner's WhatsApp.
    """
    print("[SCHEDULER] Running weekly dues report...")

    orgs = await fetch_all("""
        SELECT o.id as org_id, o.name as org_name,
               u.phone as owner_phone, u.name as owner_name
        FROM orgs o
        JOIN users u ON u.org_id = o.id
        JOIN roles r ON r.id = u.role_id
        WHERE o.is_active = true
          AND r.name = 'owner'
          AND u.is_active = true
    """)

    for org in orgs:
        try:
            report = await get_all_overdue(str(org["org_id"]))

            if report["count"] == 0:
                message = (
                    f"📊 *Weekly Dues Report — {org['org_name']}*\n\n"
                    f"✅ No overdue invoices this week. All clear!"
                )
            else:
                message = (
                    f"📊 *Weekly Dues Report — {org['org_name']}*\n"
                    f"_(as of this Monday)_\n\n"
                    + report["message"]
                )

            await send_text(org["owner_phone"], message)
            print(f"[SCHEDULER] Sent dues report to {org['org_name']} → {org['owner_phone']}")

        except Exception as e:
            print(f"[SCHEDULER] Error for org {org['org_name']}: {e}")


def start_scheduler():
    """Call this from main.py lifespan to start the scheduler."""
    scheduler.add_job(
        send_weekly_dues_report,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_dues_report",
        replace_existing=True
    )
    scheduler.start()
    print("[SCHEDULER] Started — weekly dues report every Monday 9AM IST")


def stop_scheduler():
    scheduler.shutdown()
