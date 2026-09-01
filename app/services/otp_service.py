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
SENDER_EMAIL  = required("SENDER_EMAIL")
SENDER_NAME   = required("SENDER_NAME")


def _hash(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


async def _get_otp_config(org_id: str, source_key: str) -> dict:
    """Per-org OTP behaviour. Columns are NOT NULL with defaults, so this
    always returns real values once migration 009 has run."""
    row = await fetch_one(
        """SELECT otp_expiry_minutes, otp_max_attempts, otp_length,
                  otp_resend_cooldown_seconds
           FROM orgs WHERE id = $1""",
        org_id, source_key=source_key
    )
    return {
        "expiry_minutes": row["otp_expiry_minutes"] if row else 3,
        "max_attempts": row["otp_max_attempts"] if row else 3,
        "otp_length": row["otp_length"] if row else 4,
        "resend_cooldown_seconds": row["otp_resend_cooldown_seconds"] if row else 60,
    }


async def generate_and_send_otp(
    user_id: str,
    user_email: str,
    user_name: str,
    org_name: str,
    org_id: str,
    action_context: dict,
    source_key: str
) -> dict:
    """
    Generates OTP, saves hash to DB, sends email via Brevo.
    Returns {"sent": bool, "reason": str | None, "expiry_minutes": int,
             "otp_length": int, "wait_seconds": int | None}.
    "reason": "cooldown" if a resend was requested too soon after the last one.
    """
    config = await _get_otp_config(org_id, source_key)

    last = await fetch_one(
        "SELECT created_at FROM otp_tokens WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
        user_id, source_key=source_key
    )
    if last:
        elapsed = (datetime.now(timezone.utc) - last["created_at"]).total_seconds()
        remaining = config["resend_cooldown_seconds"] - elapsed
        if remaining > 0:
            return {
                "sent": False,
                "reason": "cooldown",
                "wait_seconds": int(remaining) + 1,
                "expiry_minutes": config["expiry_minutes"],
                "otp_length": config["otp_length"],
            }

    otp_length = config["otp_length"]
    otp = str(random.randint(10 ** (otp_length - 1), 10 ** otp_length - 1))
    otp_hash = _hash(otp)
    expiry = datetime.now(timezone.utc) + timedelta(minutes=config["expiry_minutes"])

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
        org_name=org_name,
        expiry_minutes=config["expiry_minutes"],
    )

    # Raw OTP no longer referenced after this point
    return {
        "sent": success,
        "reason": None if success else "send_failed",
        "expiry_minutes": config["expiry_minutes"],
        "otp_length": otp_length,
        "wait_seconds": None,
    }


async def verify_otp(user_id: str, entered_otp: str, source_key: str) -> dict:
    """
    Verifies OTP. Returns {"valid": True/False, "action_context": dict, "reason": str}
    """
    entered_hash = _hash(entered_otp)
    now = datetime.now(timezone.utc)

    row = await fetch_one("""
        SELECT id, org_id, action_context, expires_at, attempts
        FROM otp_tokens
        WHERE user_id = $1
          AND used = false
        ORDER BY created_at DESC
        LIMIT 1
    """, user_id, source_key=source_key)

    if not row:
        return {"valid": False, "reason": "No active OTP found. Reply 'retry' to get a new code."}

    max_attempts = (await _get_otp_config(str(row["org_id"]), source_key))["max_attempts"]

    # Check attempts
    if row["attempts"] >= max_attempts:
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
        remaining = max_attempts - (row["attempts"] + 1)
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
    org_name: str,
    expiry_minutes: int
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
      <p style="color:#e53935;">⚠️ This code expires in {expiry_minutes} minutes and can only be used once.</p>
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
