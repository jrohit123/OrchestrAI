"""A scheduled report goes to the person's chat as it is now, never to the number saved in the report when it was
made (Baanganga moved from WhatsApp to Telegram and an old WhatsApp report reached Rohit through Godrej's number).
Nothing is sent: the database, the AI and the senders are replaced."""

import asyncio
import datetime as dt

from app.scheduler import jobs


def _row(**kw):
    return {
        "id": "r1", "org_id": "o1", "user_id": "u1", "phone": "+919000005977", "email": "rj@example.test",
        "query_text": "outstanding report pdf", "report_label": "Weekly Overdue Outstanding Report",
        "delivery": "whatsapp", "user_name": "Rohit", "role_id": "x", "user_email": "rj@example.test",
        "org_name": "Baanganga", "gst_rate": 3, "permissions": [], "role_name": "owner",
        "schedule_type": "weekly", "hour": 9, "minute": 0, "day_of_week": "mon", "day_of_month": None,
        "interval_minutes": None, "next_run_at": dt.datetime.now(dt.timezone.utc), **kw,
    }  # fmt: skip


def _run(monkeypatch, row):
    sent, asked = [], []

    async def keys():
        return ["baanganga"]

    async def fetch_all(sql, *a, **k):
        return [row] if "scheduled_reports" in sql else []

    async def execute(*a, **k):
        return None

    async def run_agent(message, user, phone, **k):
        asked.append((message, phone))
        return "the report", [], {}

    async def deliver_text(to, text, **k):
        sent.append(to)
        return {"status": "sent"}

    monkeypatch.setattr("app.db.get_all_source_keys", keys)
    monkeypatch.setattr(jobs, "fetch_all", fetch_all)
    monkeypatch.setattr(jobs, "execute", execute)
    monkeypatch.setattr("app.services.agent.run_agent", run_agent)
    monkeypatch.setattr(jobs.reach, "deliver_text", deliver_text)
    asyncio.run(jobs.run_scheduled_reports())
    return sent, asked


def test_a_report_goes_to_the_current_telegram_not_the_old_whatsapp_number(monkeypatch):
    sent, asked = _run(monkeypatch, _row(user_phone="tg:12345"))
    assert sent == ["tg:12345"] and asked[0][1] == "tg:12345"


def test_with_no_chat_linked_now_it_is_emailed_and_the_old_number_gets_nothing(
    monkeypatch,
):
    sent, asked = _run(monkeypatch, _row(user_phone=None))
    assert sent == []
    assert asked[0][0].endswith("email only") and asked[0][1] == ""
