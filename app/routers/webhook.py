import os
from fastapi import APIRouter, Request, Response
from dotenv import load_dotenv

from app.services.identity import resolve_identity, check_permission
from app.services.whatsapp import send_text
from app.services.otp_service import verify_otp
from app.classifier.classifier import classify_message
from app.executor.workflow_executor import execute_intent, resume_after_otp
from app.redis_client import get_session, set_session, get_redis
from app.db import execute

load_dotenv()

router = APIRouter()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "orchestrai_verify_2024")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")


# ── META WEBHOOK VERIFICATION (GET) ──────────────────
@router.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


# ── INBOUND MESSAGES (POST) ───────────────────────────
@router.post("/webhook/whatsapp")
async def receive_message(request: Request):
    body = await request.json()

    try:
        entry   = body["entry"][0]
        changes = entry["changes"][0]["value"]

        # ── Ignore status updates (delivered, read, sent) ──
        if "statuses" in changes and "messages" not in changes:
            return {"status": "ok"}

        # ── Ignore if no messages ──
        if "messages" not in changes:
            return {"status": "ok"}

        msg      = changes["messages"][0]
        phone    = msg["from"]
        msg_id   = msg["id"]
        msg_type = msg.get("type", "text")

        # ── Ignore echo (message from our own bot number) ──
        if phone == WHATSAPP_PHONE_ID:
            return {"status": "ok"}

        # ── Deduplication — ignore already processed message IDs ──
        redis = get_redis()
        dedup_key = f"msg_processed:{msg_id}"
        already_processed = await redis.get(dedup_key)
        if already_processed:
            print(f"[WEBHOOK] Duplicate msg_id {msg_id} — skipping")
            return {"status": "ok"}
        await redis.setex(dedup_key, 300, "1")  # TTL 5 min

        # ── Normalize: WhatsApp omits +, DB stores with + ──
        if phone and not phone.startswith('+'):
            phone = '+' + phone

        # ── Extract text ──
        if msg_type == "text":
            text = msg["text"]["body"]
        elif msg_type == "interactive":
            text = msg["interactive"]["button_reply"]["id"]
        else:
            return {"status": "ok"}

        print(f"[WEBHOOK] From: {phone} | Message: {text}")
        await handle_message(phone=phone, text=text)

    except (KeyError, IndexError) as e:
        print(f"[WEBHOOK] Parse error: {e}")

    return {"status": "ok"}


# ── CORE MESSAGE HANDLER ──────────────────────────────
async def handle_message(phone: str, text: str):
    # 1. Identity
    user = await resolve_identity(phone)
    if not user:
        await send_text(phone,
            "👋 Your number isn't registered with OrchestrAI.\n"
            "Contact your admin to get access."
        )
        return

    if not user["is_active"] or not user["org_active"]:
        await send_text(phone, "❌ Your account is inactive. Contact admin.")
        return

    # 2. Session
    session_id = f"{user['org_id']}:{phone}"
    session = await get_session(session_id)

    # 3. OTP state
    if session.get("state") == "awaiting_otp":
        await _handle_otp_reply(phone, text, user, session, session_id)
        return

    # 4. Classify
    result = await classify_message(text, org_name=user["org_name"])
    intent = result["intent"]
    tier   = result["tier"]
    print(f"[CLASSIFIER] Intent: {intent} | Tier: {tier}")

    # 5. Permission gate
    if not check_permission(user, intent):
        await send_text(phone,
            f"❌ You don't have permission for: *{intent}*\n"
            f"Your role: *{user['role']}*"
        )
        return

    # 6. Static action intents
    if intent == "action:greet":
        await send_text(phone,
            f"👋 Hi *{user['user_name']}*! I'm OrchestrAI.\n\n"
            f"You can ask:\n"
            f"• *stock [item]* — check inventory\n"
            f"• *dues [customer]* — check outstanding\n"
            f"• *invoice [customer] ₹amount* — create invoice\n"
            f"• *dues report* — all overdue summary\n"
            f"• *help* — show this menu"
        )
        return

    if intent == "action:menu":
        await send_text(phone,
            f"📋 *What can I help with?*\n\n"
            f"📦 *Stock* — stock gold ring\n"
            f"💰 *Dues* — dues Mehta Jewellers\n"
            f"🧾 *Invoice* — invoice Mehta ₹50000\n"
            f"📊 *Report* — dues report"
        )
        return

    if intent == "action:retry_otp":
        await set_session(session_id, {})
        await send_text(phone, "🔄 Session cleared. Please resend your original request.")
        return

    if intent == "unknown":
        await send_text(phone,
            "🤔 Didn't understand that.\n"
            "Try: *stock rings* | *dues Mehta* | *help*"
        )
        return

    # 7. Save session and execute
    await set_session(session_id, {**session, "last_intent": intent})

    reply = await execute_intent(
        intent=intent,
        entity_raw=result.get("entity_raw"),
        user=user,
        session_id=session_id,
        session=session,
        raw_text=text
    )

    await send_text(phone, reply)


# ── OTP REPLY HANDLER ─────────────────────────────────
async def _handle_otp_reply(phone, text, user, session, session_id):
    if text.strip().lower() == "retry":
        await set_session(session_id, {})
        await send_text(phone, "🔄 Session cleared. Please resend your original request.")
        return

    result = await verify_otp(user["user_id"], text.strip())

    if result["valid"]:
        await set_session(session_id, {**session, "state": "otp_verified", "otp_verified": True})
        reply = await resume_after_otp(user, session_id, session)
        await send_text(phone, reply)
    else:
        await send_text(phone, f"❌ {result['reason']}")
