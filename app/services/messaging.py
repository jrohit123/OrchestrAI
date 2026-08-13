"""
messaging.py — Channel-agnostic send dispatcher.

Routes outbound messages to WhatsApp or Telegram based on the `to` identifier:
  - Plain phone number (+919...)  → WhatsApp
  - tg:<chat_id>                  → Telegram

Usage (drop-in replacement for whatsapp imports):
    from app.services.messaging import send_text, send_buttons, send_document, send_list
"""
from app.services import whatsapp


def _is_telegram(to: str) -> bool:
    return str(to).startswith("tg:")


def _tg_id(to: str) -> str:
    """Strip tg: prefix to get raw Telegram chat_id."""
    return to[3:]


async def send_text(to: str, message: str):
    if _is_telegram(to):
        from app.services import telegram
        return await telegram.send_text(_tg_id(to), message)
    return await whatsapp.send_text(to, message)


async def send_buttons(to: str, body: str, buttons: list[dict]):
    if _is_telegram(to):
        from app.services import telegram
        return await telegram.send_buttons(_tg_id(to), body, buttons)
    return await whatsapp.send_buttons(to, body, buttons)


async def send_document(to: str, pdf_bytes: bytes, filename: str, caption: str = ""):
    if _is_telegram(to):
        from app.services import telegram
        return await telegram.send_document(_tg_id(to), pdf_bytes, filename, caption)
    return await whatsapp.send_document(to, pdf_bytes, filename, caption)


async def send_list(to: str, body: str, button_label: str, sections: list[dict]):
    if _is_telegram(to):
        from app.services import telegram
        return await telegram.send_list(_tg_id(to), body, button_label, sections)
    return await whatsapp.send_list(to, body, button_label, sections)
