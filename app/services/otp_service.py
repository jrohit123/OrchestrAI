import random
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from app.db import fetch_one, execute

from app.config import required

load_dotenv()

BREVO_API_KEY = required("BREVO_API_KEY")
SENDER_EMAIL  = "sales@aitamate.com"
SENDER_NAME   = "OrchestrAI | Baanganga Gold"
OTP_EXPIRY_MINUTES = 3
MAX_ATTEMPTS = 3


def _hash(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


async def generate_and_send_otp(
    user_id: str,
    user_email: str,
    user_name: str,
    org_name: str,
    org_id: str,
    action_context: dict,
    source_key: str
) -> bool:
    """
    Generates OTP, saves hash to DB, sends email via Brevo.
    Returns True if email sent successfully.
    """
    otp = str(random.randint(1000, 9999))
    otp_hash = _hash(otp)
    expiry = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

    # Invalidate any previous unused OTPs for this user
    await execute(
        "UPDATE otp_tokens SET used = true WHERE user_id = $1 AND used = false",
        user_id,
        source_key=source_key
    )

    # Save new OTP record
    await execute("""
        INSERT INTO otp_tokens (user_id, otp_hash, action_context, expires_at, used, org_id)
        VALUES ($1, $2, $3, $4, false, $5)
    """, user_id, otp_hash, json.dumps(action_context), expiry, org_id, source_key=source_key)

    # Send via Brevo — raw OTP only lives here
    success = await _send_brevo_email(
        to_email=user_email,
        user_name=user_name,
        otp=otp,
        action_desc=action_context.get("description", "your request"),
        org_name=org_name
    )

    # Raw OTP no longer referenced after this point
    return success


async def verify_otp(user_id: str, entered_otp: str, source_key: str) -> dict:
    """
    Verifies OTP. Returns {"valid": True/False, "action_context": dict, "reason": str}
    """
    entered_hash = _hash(entered_otp)
    now = datetime.now(timezone.utc)

    row = await fetch_one("""
        SELECT id, action_context, expires_at, attempts
        FROM otp_tokens
        WHERE user_id = $1
          AND used = false
        ORDER BY created_at DESC
        LIMIT 1
    """, user_id, source_key=source_key)

    if not row:
        return {"valid": False, "reason": "No active OTP found. Reply 'retry' to get a new code."}

    # Check attempts
    if row["attempts"] >= MAX_ATTEMPTS:
        await execute("UPDATE otp_tokens SET used = true WHERE id = $1", row["id"], source_key=source_key)
        return {"valid": False, "reason": "Too many attempts. Reply 'retry' to get a new code."}

    # Check expiry
    if row["expires_at"] < now:
        return {"valid": False, "reason": "Code has expired. Reply 'retry' to get a new code."}

    # Check hash
    if row["attempts"] is not None:
        await execute(
            "UPDATE otp_tokens SET attempts = attempts + 1 WHERE id = $1",
            row["id"],
            source_key=source_key
        )

    # Re-fetch to check hash properly
    valid_row = await fetch_one("""
        SELECT id, action_context FROM otp_tokens
        WHERE id = $1 AND otp_hash = $2 AND used = false
    """, row["id"], entered_hash, source_key=source_key)

    if not valid_row:
        remaining = MAX_ATTEMPTS - (row["attempts"] + 1)
        return {
            "valid": False,
            "reason": f"Incorrect code. {remaining} attempt(s) remaining."
        }

    # Mark used immediately — single use enforced
    await execute("UPDATE otp_tokens SET used = true WHERE id = $1", valid_row["id"], source_key=source_key)

    return {
        "valid": True,
        "action_context": json.loads(valid_row["action_context"])
            if isinstance(valid_row["action_context"], str)
            else valid_row["action_context"]
    }


async def _send_brevo_email(
    to_email: str,
    user_name: str,
    otp: str,
    action_desc: str,
    org_name: str
) -> bool:
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;">
      <h2 style="color:#1a1a2e;">🔐 OrchestrAI Verification Code</h2>
      <p>Hi {user_name},</p>
      <p>You requested to <strong>{action_desc}</strong> via WhatsApp.</p>
      <p>Your one-time verification code is:</p>
      <div style="font-size:36px;font-weight:bold;letter-spacing:12px;
                  text-align:center;padding:16px;background:#f0f0ff;
                  border-radius:8px;color:#4a00e0;margin:16px 0;">
        {otp}
      </div>
      <p style="color:#e53935;">⚠️ This code expires in {OTP_EXPIRY_MINUTES} minutes and can only be used once.</p>
      <p style="color:#e53935;">🚫 If you did not make this request, contact your admin immediately.</p>
      <hr style="margin:20px 0;border:none;border-top:1px solid #eee;">
      <p style="color:#888;font-size:12px;">— OrchestrAI Security System · {org_name}</p>
    </div>
    """

    payload = {
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to": [{"email": to_email, "name": user_name}],
        "subject": f"🔐 Your OrchestrAI Code — {org_name}",
        "htmlContent": html
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"}
        )
        return resp.status_code == 201


async def send_email_with_pdf(
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    pdf_bytes: bytes,
    filename: str,
    org_name: str,
) -> bool:
    """
    Send an email with a PDF attachment via Brevo.
    Used by the agent's generate_pdf tool when delivery = 'email' or 'both'.
    """
    import base64

    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
      <h2 style="color:#185FA5;">📄 {subject}</h2>
      <p>Hi {to_name},</p>
      <p>{body}</p>
      <p>Please find the PDF attached to this email.</p>
      <hr style="margin:20px 0;border:none;border-top:1px solid #eee;">
      <p style="color:#888;font-size:12px;">— OrchestrAI · {org_name}</p>
    </div>
    """

    payload = {
        "sender":      {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to":          [{"email": to_email, "name": to_name}],
        "subject":     subject,
        "htmlContent": html_body,
        "attachment":  [{"name": filename, "content": pdf_b64}],
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers={
                    "api-key": BREVO_API_KEY,
                    "Content-Type": "application/json"
                },
                timeout=15.0
            )
            return resp.status_code == 201
    except Exception as e:
        print(f"[EMAIL] Failed to send PDF email: {e}")
        return False
