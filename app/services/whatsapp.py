import httpx
import os
from dotenv import load_dotenv
from app.config import required

load_dotenv()

WHATSAPP_TOKEN    = required("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
BASE_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
MEDIA_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/media"

HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    "Content-Type": "application/json"
}


async def send_text(to: str, message: str):
    """Send a plain text WhatsApp message."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(BASE_URL, json=payload, headers=HEADERS)
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
            }
        }
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(BASE_URL, json=payload, headers=HEADERS)
        resp.raise_for_status()
    return resp.json()


async def send_document(to: str, pdf_bytes: bytes, filename: str, caption: str = ""):
    """
    Upload PDF to WhatsApp media and send as document.
    """
    auth_header = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    # Step 1: Upload PDF to Meta media endpoint
    async with httpx.AsyncClient() as client:
        upload_resp = await client.post(
            MEDIA_URL,
            headers=auth_header,
            data={"messaging_product": "whatsapp"},
            files={"file": (filename, pdf_bytes, "application/pdf")}
        )
        upload_resp.raise_for_status()
        media_id = upload_resp.json()["id"]

    # Step 2: Send document message
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename,
            "caption": caption
        }
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(BASE_URL, json=payload, headers=HEADERS)
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
        resp.raise_for_status()
    return resp.json()
