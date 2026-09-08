"""
telegram.py — Telegram Bot API adapter.
Mirrors whatsapp.py's function signatures exactly so messaging.py can dispatch cleanly.
"""
import httpx
from app.config import required
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

TELEGRAM_BOT_TOKEN = required("TELEGRAM_BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


class TelegramRateLimitedError(Exception):
    """Telegram returned 429 — the bot token is under flood control.

    Raised instead of a generic HTTPStatusError so callers can skip sending
    a "something went wrong" fallback message, which would just hit the
    same lock and cascade into more failed calls (this is what was
    happening before: one failed send -> fallback send -> fallback's
    fallback send, all 429, all in the same request).
    """
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Telegram rate-limited, retry after {retry_after}s")


def _raise_if_rate_limited(resp: httpx.Response):
    if resp.status_code == 429:
        try:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 30)
        except Exception:
            retry_after = 30
        logger.warning(f"Telegram rate-limited (429), retry_after={retry_after}s")
        raise TelegramRateLimitedError(retry_after)


async def send_text(to: str, message: str):
    """Send a plain text Telegram message. `to` is the raw chat_id (no tg: prefix)."""
    # Try with Markdown first, fall back to plain text if Telegram rejects it
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": to,
            "text": message,
            "parse_mode": "Markdown"
        })
        _raise_if_rate_limited(resp)
        if resp.status_code == 400:
            # Markdown parsing failed — retry as plain text
            logger.warning(f"Telegram Markdown parsing failed for chat_id {to}, retrying as plain text")
            resp = await client.post(f"{BASE_URL}/sendMessage", json={
                "chat_id": to,
                "text": message
            })
            _raise_if_rate_limited(resp)
        if resp.status_code != 200:
            logger.error(f"Telegram API error: {resp.status_code} - {resp.text}")
            logger.error(f"Message length: {len(message)} characters")
            logger.error(f"Message preview: {message[:200]}...")
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
        _raise_if_rate_limited(resp)
        if resp.status_code == 400:
            resp = await client.post(f"{BASE_URL}/sendMessage", json={
                "chat_id": to,
                "text": body,
                "reply_markup": {"inline_keyboard": keyboard}
            })
            _raise_if_rate_limited(resp)
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
        _raise_if_rate_limited(resp)
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
        _raise_if_rate_limited(resp)
        if resp.status_code == 400:
            resp = await client.post(f"{BASE_URL}/sendMessage", json={
                "chat_id": to,
                "text": body,
                "reply_markup": {"inline_keyboard": keyboard}
            })
            _raise_if_rate_limited(resp)
        resp.raise_for_status()
    return resp.json()
