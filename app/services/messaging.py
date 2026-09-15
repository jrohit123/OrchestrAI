"""
messaging.py — Channel-agnostic send dispatcher.

Routes outbound messages to WhatsApp or Telegram based on the `to` identifier:
  - Plain phone number (+919...)  → WhatsApp
  - tg:<chat_id>                  → Telegram

Usage (drop-in replacement for whatsapp imports):
    from app.services.messaging import send_text, send_buttons, send_document, send_list
"""
from app.services import whatsapp

# Headroom under both WhatsApp's and Telegram's ~4096-character hard cap per
# text message. A long agent response (e.g. "show me all cases" on an org
# with enough cases) routinely exceeds that — without splitting, the send
# fails outright (confirmed live: Telegram rejected a 4709-char message with
# "Bad Request: message is too long", both as Markdown AND on the plain-text
# retry, since neither attempt is actually shorter) and the user gets a bare
# "something went wrong" instead of their answer.
_CHUNK_LIMIT = 4000


def _is_telegram(to: str) -> bool:
    return str(to).startswith("tg:")


def _tg_id(to: str) -> str:
    """Strip tg: prefix to get raw Telegram chat_id."""
    return to[3:]


def _split_for_send(message: str, limit: int = _CHUNK_LIMIT) -> list[str]:
    """
    Split a long message into chunks that each fit one platform send, on
    paragraph boundaries (blank lines) so a numbered list item or other
    coherent block isn't cut mid-way. Falls back to a hard split on spaces
    only for a single paragraph that's itself over the limit (rare — one
    giant unbroken block of text).
    """
    if len(message) <= limit:
        return [message]

    chunks: list[str] = []
    current = ""
    for para in message.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(para) <= limit:
            current = para
            continue
        # This one paragraph alone is over the limit — hard-split on
        # whitespace so at least no single word gets cut in half.
        piece = ""
        for word in para.split(" "):
            candidate_piece = f"{piece} {word}" if piece else word
            if len(candidate_piece) <= limit:
                piece = candidate_piece
            else:
                chunks.append(piece)
                piece = word
        current = piece
    if current:
        chunks.append(current)
    return chunks


async def send_text(to: str, message: str):
    sender = telegram_send if _is_telegram(to) else whatsapp.send_text
    target = _tg_id(to) if _is_telegram(to) else to

    result = None
    for chunk in _split_for_send(message):
        result = await sender(target, chunk)
    return result


async def telegram_send(chat_id: str, message: str):
    from app.services import telegram
    return await telegram.send_text(chat_id, message)


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
