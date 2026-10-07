"""Plain email through Brevo: the same account and sender the chat codes already use
(BREVO_API_KEY, SENDER_EMAIL, SENDER_NAME).

`send_email` never raises. It says whether Brevo took the message and, when it did not, logs a
short reason without the address or the answer (both can hold a person's details)."""

import httpx

from app.config import required
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


async def send_email(
    to_email: str, to_name: str, subject: str, text: str, html: str | None = None
) -> bool:
    try:
        payload = {
            "sender": {
                "name": required("SENDER_NAME"),
                "email": required("SENDER_EMAIL"),
            },
            "to": [{"email": to_email, "name": to_name or to_email}],
            "subject": subject,
            "textContent": text,
        }
        if html:
            payload["htmlContent"] = html
        headers = {
            "api-key": required("BREVO_API_KEY"),
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(BREVO_URL, json=payload, headers=headers)
    except Exception as e:
        logger.warning(f"email not sent ({type(e).__name__})")
        return False
    if resp.status_code != 201:
        logger.warning(f"email not sent: the mail service answered {resp.status_code}")
        return False
    return True
