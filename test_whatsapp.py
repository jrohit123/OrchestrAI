"""
Test sending a WhatsApp message directly.
Confirm WHATSAPP_TOKEN and WHATSAPP_PHONE_ID are in .env before running.

Run with:  python test_whatsapp.py
"""
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN    = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
BASE_URL = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}


def test_send(to_number: str):
    """
    to_number: full number with country code e.g. +919876543210
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "body": (
                "✅ *OrchestrAI is connected!*\n\n"
                "WhatsApp API is working correctly.\n"
                "Reply *hi* to start."
            )
        }
    }

    resp = httpx.post(BASE_URL, json=payload, headers=HEADERS)

    if resp.status_code == 200:
        print(f"✅ Message sent to {to_number}")
        print(f"   Message ID: {resp.json()['messages'][0]['id']}")
    else:
        print(f"❌ Failed: {resp.status_code}")
        print(f"   Error: {resp.text}")


if __name__ == "__main__":
    to = input("Enter WhatsApp number (with country code e.g. +919876543210): ").strip()
    test_send(to)
