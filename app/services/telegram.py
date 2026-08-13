"""
telegram.py — Telegram Bot API adapter.
Mirrors whatsapp.py's function signatures exactly so messaging.py can dispatch cleanly.
"""
import httpx
import os
from app.config import required
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

TELEGRAM_BOT_TOKEN = required("TELEGRAM_BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


async def send_text(to: str, message: str):
    """Send a plain text Telegram message. `to` is the raw chat_id (no tg: prefix)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": to,
            "text": message,
            "parse_mode": "Markdown"
        })
        resp.raise_for_status()
    return resp.json()


async def send_buttons(to: str, body: str, buttons: list[dict]):
    """
    Send an inline keyboard message.
    buttons = [{"id": "approve", "title": "✅ Approve"}, ...]  — max 3
    """
    keyboard = [[{"text": b["title"], "callback_data": b["id"]}] for b in buttons[:3]]
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": to,
            "text": body,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": keyboard}
        })
        resp.raise_for_status()
    return resp.json()


async def send_document(to: str, pdf_bytes: bytes, filename: str, caption: str = ""):
    """Send a PDF document."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/sendDocument",
            data={"chat_id": to, "caption": caption},
            files={"document": (filename, pdf_bytes, "application/pdf")}
        )
        resp.raise_for_status()
    return resp.json()


async def send_list(to: str, body: str, button_label: str, sections: list[dict]):
    """
    Telegram has no native list widget — flatten sections into an inline keyboard.
    Max 10 rows total (same as WhatsApp list limit).
    """
    keyboard = []
    total = 0
    for section in sections:
        for row in section.get("rows", []):
            if total >= 10:
                break
            keyboard.append([{"text": row["title"], "callback_data": row["id"]}])
            total += 1
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": to,
            "text": body,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": keyboard}
        })
        resp.raise_for_status()
    return resp.json()
