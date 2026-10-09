import os

import httpx
from dotenv import load_dotenv

from app.config import required
from app.logging_config import get_context_logger

load_dotenv()

logger = get_context_logger(__name__)

WHATSAPP_TOKEN = required("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
BASE_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
MEDIA_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/media"

HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}


async def send_text(to: str, message: str):
    """Send a plain text WhatsApp message."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(BASE_URL, json=payload, headers=HEADERS)
        if resp.status_code >= 400:
            logger.error(f"send_text failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
    return resp.json()


async def send_buttons(to: str, body: str, buttons: list[dict]):
    """
    Send an interactive button message.
    buttons = [{"id": "approve", "title": "✅ Approve"}, ...]
    Max 3 buttons.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons[:3]
                ]
            },
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(BASE_URL, json=payload, headers=HEADERS)
        if resp.status_code >= 400:
            logger.error(f"send_buttons failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
    return resp.json()


async def send_document(
    to: str,
    pdf_bytes: bytes,
    filename: str,
    caption: str = "",
    mime_type: str = "application/pdf",
):
    """
    Upload a document (PDF, Excel, ...) to WhatsApp media and send it.
    `mime_type` defaults to PDF for backwards compatibility with every
    existing caller — pass the real one (e.g. an .xlsx sheet's) explicitly.
    """
    auth_header = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    # Step 1: Upload document to Meta media endpoint
    async with httpx.AsyncClient() as client:
        upload_resp = await client.post(
            MEDIA_URL,
            headers=auth_header,
            data={"messaging_product": "whatsapp"},
            files={"file": (filename, pdf_bytes, mime_type)},
        )
        if upload_resp.status_code >= 400:
            logger.error(
                f"upload_media failed ({upload_resp.status_code}): {upload_resp.text}"
            )
        upload_resp.raise_for_status()
        media_id = upload_resp.json()["id"]

    # Step 2: Send document message
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {"id": media_id, "filename": filename, "caption": caption},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(BASE_URL, json=payload, headers=HEADERS)
        if resp.status_code >= 400:
            logger.error(f"send_document failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
    return resp.json()


async def send_list(to: str, body: str, button_label: str, sections: list[dict]):
    """Interactive list message. Max 10 rows total across sections."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {"button": button_label[:20], "sections": sections},
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(BASE_URL, json=payload, headers=HEADERS)
        if resp.status_code >= 400:
            logger.error(f"send_list failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
    return resp.json()


GRAPH_URL = "https://graph.facebook.com/v19.0"


async def media_info(media_id: str) -> dict:
    """What Meta says about a file somebody sent: its temporary address, type and size (bytes)."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{GRAPH_URL}/{media_id}", headers=HEADERS)
        if resp.status_code >= 400:
            logger.error(f"media_info failed ({resp.status_code})")
        resp.raise_for_status()
    return resp.json()


async def download_media(url: str) -> bytes:
    """The file itself, from the temporary address Meta gave. Meta keeps it for about 30 days only."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        )
        if resp.status_code >= 400:
            logger.error(f"download_media failed ({resp.status_code})")
        resp.raise_for_status()
    return resp.content


async def send_image(
    to: str, data: bytes, mime_type: str = "image/jpeg", caption: str = ""
):
    """Upload a picture to WhatsApp and send it. Like any message the bot starts, it reaches the person
    only if they wrote to the bot in the last 24 hours."""
    async with httpx.AsyncClient() as client:
        upload = await client.post(
            MEDIA_URL,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            data={"messaging_product": "whatsapp"},
            files={"file": ("photo", data, mime_type)},
        )
        if upload.status_code >= 400:
            logger.error(f"upload_media failed ({upload.status_code}): {upload.text}")
        upload.raise_for_status()
        media_id = upload.json()["id"]
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"id": media_id, "caption": caption[:1000]},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(BASE_URL, json=payload, headers=HEADERS)
        if resp.status_code >= 400:
            logger.error(f"send_image failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()
    return resp.json()
