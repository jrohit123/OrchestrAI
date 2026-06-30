import os
from fastapi import APIRouter, Request, Response
from dotenv import load_dotenv

from app.services.identity import resolve_identity, check_permission, check_route_permission
from app.services.whatsapp import send_text
from app.services.otp_service import verify_otp, generate_and_send_otp
from app.services.agent import run_agent
from app.services.action_executor import execute_pending_action
from app.executor.workflow_executor import (
    resume_after_otp, handle_approval_response
)
from app.redis_client import (
    get_session, set_session, delete_session, get_redis,
    set_auth_token, check_auth_token
)
from app.db import fetch_one, execute

load_dotenv()

router = APIRouter()

VERIFY_TOKEN      = os.getenv("WHATSAPP_VERIFY_TOKEN", "orchestrai_verify_2024")
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
        await handle_message(phone=phone, text=text, msg_type=msg_type)

    except (KeyError, IndexError) as e:
        print(f"[WEBHOOK] Parse error: {e}")

    return {"status": "ok"}


# ── CORE MESSAGE HANDLER ──────────────────────────────
async def handle_message(phone: str, text: str, msg_type: str = "text"):
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

    # 2. Fetch org TTL
    org_row = await fetch_one(
        "SELECT session_ttl_minutes FROM orgs WHERE id = $1",
        user["org_id"]
    )
    ttl_minutes = org_row["session_ttl_minutes"] if org_row else 480

    # 3. Security auth check
    sec_session_id = f"sec:{user['org_id']}:{phone}"
    is_authenticated = await check_auth_token(user["org_id"], phone)

    if not is_authenticated:
        pre_session = await get_session(sec_session_id)

        if pre_session.get("state") == "awaiting_security_otp":
            # User is replying with security OTP
            result = await verify_otp(user["user_id"], text.strip())
            if result["valid"]:
                await set_auth_token(user["org_id"], phone, ttl_minutes)
                pending_text = pre_session.get("pending_text", "")
                await delete_session(sec_session_id)
                hours   = ttl_minutes // 60
                mins    = ttl_minutes % 60
                ttl_str = f"{hours}h {mins}m" if mins else f"{hours}h"
                if ttl_minutes < 60:
                    ttl_str = f"{ttl_minutes} mins"
                await send_text(phone,
                    f"✅ Identity verified!\n"
                    f"_Session active for {ttl_str}. Processing your request..._"
                )
                if pending_text:
                    await handle_message(phone=phone, text=pending_text, msg_type="text")
            else:
                await send_text(phone, f"❌ {result['reason']}")
            return

        # Session expired — send security OTP
        sent = await generate_and_send_otp(
            user_id=user["user_id"],
            user_email=user["email"],
            user_name=user["user_name"],
            org_name=user["org_name"],
            action_context={"type": "security_auth"}
        )
        if sent:
            await set_session(sec_session_id, {
                "state": "awaiting_security_otp",
                "pending_text": text
            }, ttl=300)
            hours   = ttl_minutes // 60
            mins    = ttl_minutes % 60
            ttl_str = f"{hours} hours" if not mins else f"{hours}h {mins}m"
            if ttl_minutes < 60:
                ttl_str = f"{ttl_minutes} minutes"
            await send_text(phone,
                f"🔐 *Security Verification Required*\n\n"
                f"Your session has expired.\n"
                f"A verification code has been sent to *{user['email']}*.\n"
                f"Reply with the code to continue.\n\n"
                f"_Required every {ttl_str} for security._"
            )
        else:
            await send_text(phone, "❌ Could not send verification email. Contact admin.")
        return

    # 4. Normal session
    session_id = f"{user['org_id']}:{phone}"
    session    = await get_session(session_id)

    # 5. Approval button responses
    if msg_type == "interactive" and text in ("action:approve", "action:reject"):
        await handle_approval_response(phone, text, user)
        return

    # 6. Disambiguation state (customer selection) - handled by agent clarify tool
    # Legacy disambiguation removed - agent now handles this via clarify tool

    # 7. OTP state (for invoice high value)
    if session.get("state") == "awaiting_otp":
        await _handle_otp_reply(phone, text, user, session, session_id)
        return

    # 8. Pending action confirmation check (NEW - replaces pending_confirm)
    pending_action = session.get("pending_action")
    if pending_action and pending_action.get("stage") == "awaiting_confirmation":
        if text.strip().lower() in ("yes", "y", "haan", "ha", "ok", "confirm"):
            # User confirmed - execute the action
            result = await execute_pending_action(pending_action, user)

            if result.get("success"):
                # Clear pending action on success but preserve conversation history
                session.pop("pending_action", None)
                # Append execution result to conversation history
                session["conversation_history"] = (session.get("conversation_history") or []) + [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": result.get("message", "Action completed successfully")}
                ]
                session["conversation_history"] = session["conversation_history"][-15:]
                await set_session(session_id, session)
                reply = result.get("message", "Action completed successfully")
                await send_text(phone, reply)

                # Send PDF if generated
                if result.get("pdf_bytes"):
                    from app.services.whatsapp import send_document
                    import re
                    safe_filename = re.sub(r'[^\w\-]', '_', result.get("invoice_number", result.get("quotation_number", "document")))[:50] + ".pdf"
                    await send_document(
                        to=phone,
                        pdf_bytes=result["pdf_bytes"],
                        filename=safe_filename,
                        caption=f"📄 {result.get('invoice_number', result.get('quotation_number', 'Document'))}"
                    )
            else:
                # Check if we need to move to OTP stage
                if result.get("stage") == "awaiting_otp":
                    pending_action["stage"] = "awaiting_otp"
                    await set_session(session_id, {**session, "pending_action": pending_action})
                    await send_text(phone, result.get("message"))
                elif result.get("stage") == "awaiting_approval":
                    pending_action["stage"] = "awaiting_approval"
                    await set_session(session_id, {**session, "pending_action": pending_action})
                    await send_text(phone, result.get("message"))
                else:
                    # Error - clear pending action but preserve history
                    session.pop("pending_action", None)
                    await set_session(session_id, session)
                    await send_text(phone, result.get("message", "Action failed"))
        else:
            # User cancelled - clear pending action but preserve history
            session.pop("pending_action", None)
            await set_session(session_id, session)
            await send_text(phone, "❌ Action cancelled.")
        return

    # 9. OTP reply for pending action (NEW)
    if pending_action and pending_action.get("stage") == "awaiting_otp":
        if text.strip().lower() == "retry":
            await set_session(session_id, {})
            await send_text(phone, "🔄 Session cleared. Please resend your original request.")
            return

        result = await verify_otp(user["user_id"], text.strip())

        if result["valid"]:
            # OTP verified - execute the action
            exec_result = await execute_pending_action(pending_action, user, otp_verified=True)

            if exec_result.get("success"):
                await set_session(session_id, {})
                reply = exec_result.get("message", "Action completed successfully")
                await send_text(phone, reply)

                # Send PDF if generated
                if exec_result.get("pdf_bytes"):
                    from app.services.whatsapp import send_document
                    import re
                    safe_filename = re.sub(r'[^\w\-]', '_', exec_result.get("invoice_number", exec_result.get("quotation_number", "document")))[:50] + ".pdf"
                    await send_document(
                        to=phone,
                        pdf_bytes=exec_result["pdf_bytes"],
                        filename=safe_filename,
                        caption=f"📄 {exec_result.get('invoice_number', exec_result.get('quotation_number', 'Document'))}"
                    )
            else:
                # Check if we need approval
                if exec_result.get("stage") == "awaiting_approval":
                    pending_action["stage"] = "awaiting_approval"
                    await set_session(session_id, {"pending_action": pending_action})
                    await send_text(phone, exec_result.get("message"))
                else:
                    await set_session(session_id, {})
                    await send_text(phone, exec_result.get("message", "Action failed"))
        else:
            await send_text(phone, f"❌ {result['reason']}")
        return

    # 10. Run the agent — replaces classify + execute pipeline
    # Load conversation history from session
    conversation_history = session.get("conversation_history", [])

    try:
        reply, updated_history, session_patch = await run_agent(
            text, user, phone,
            conversation_history=conversation_history,
            pending_action=pending_action
        )

        # Apply session patch if any
        if session_patch:
            session = {**session, **session_patch}
            # Update pending_action reference for next iteration
            pending_action = session_patch.get("pending_action")

        # Save last 15 messages (7-8 turns) for context
        updated_history = updated_history[-15:]
        session["last_message"] = text
        session["conversation_history"] = updated_history
        await set_session(session_id, session)

        await send_text(phone, reply)

        # Log to audit_log
        await execute("""
            INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome)
            VALUES ($1, $2, 'agent', $3, 'success')
        """, user["org_id"], user["user_id"], text)

    except Exception as e:
        print(f"[AGENT] Error: {e}")
        import traceback
        traceback.print_exc()
        await send_text(phone,
            f"🤔 Error: {str(e)}"
        )


# ── OTP REPLY HANDLER (invoice high value) ────────────
async def _handle_otp_reply(phone, text, user, session, session_id):
    if text.strip().lower() == "retry":
        await set_session(session_id, {})
        await send_text(phone, "🔄 Session cleared. Please resend your original request.")
        return

    result = await verify_otp(user["user_id"], text.strip())

    if result["valid"]:
        # Refresh auth token on successful OTP
        org_row = await fetch_one(
            "SELECT session_ttl_minutes FROM orgs WHERE id = $1", user["org_id"]
        )
        ttl = org_row["session_ttl_minutes"] if org_row else 480
        await set_auth_token(user["org_id"], phone, ttl)
        await set_session(session_id, {**session, "state": "otp_verified", "otp_verified": True})
        reply = await resume_after_otp(user, session_id, session)
        await send_text(phone, reply)
    else:
        await send_text(phone, f"❌ {result['reason']}")
