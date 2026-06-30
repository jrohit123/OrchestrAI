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

_CONFIRM_WORDS = frozenset({
    "yes", "y", "haan", "ha", "ok", "confirm", "confirmed",
    "theek hai", "thik hai", "sahi hai", "go ahead", "proceed", "👍",
})
_CANCEL_WORDS = frozenset({"no", "n", "nahi", "na", "cancel", "stop"})


def _sanitize_history(history: list) -> list:
    """Remove tool messages and tool_call assistant messages from history."""
    sanitized = []
    for msg in history:
        if msg.get("role") == "tool":
            continue
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            continue
        if msg.get("role") in ("user", "assistant"):
            if msg.get("content") and not msg.get("tool_calls"):
                sanitized.append(msg)
    return sanitized


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
        try:
            await handle_message(phone=phone, text=text, msg_type=msg_type)
        except Exception as e:
            print(f"[WEBHOOK] handle_message error: {e}")
            import traceback
            traceback.print_exc()
            try:
                await send_text(phone, "❌ Something went wrong. Please try again.")
            except Exception:
                pass

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

    session_ttl = ttl_minutes * 60
    pending_action = session.get("pending_action")

    async def _send_action_pdf(exec_result: dict):
        if not exec_result.get("pdf_bytes"):
            return
        from app.services.whatsapp import send_document
        import re
        doc_id = exec_result.get("invoice_number") or exec_result.get("quotation_number") or "document"
        safe_filename = re.sub(r'[^\w\-]', '_', str(doc_id))[:50] + ".pdf"
        await send_document(
            to=phone,
            pdf_bytes=exec_result["pdf_bytes"],
            filename=safe_filename,
            caption=f"📄 {doc_id}"
        )

    # 8. Pending action confirmation
    if pending_action and pending_action.get("stage") == "awaiting_confirmation":
        text_lower = text.strip().lower()
        if text_lower in _CONFIRM_WORDS:
            try:
                result = await execute_pending_action(pending_action, user)
            except Exception as e:
                print(f"[WEBHOOK] execute_pending_action error: {e}")
                import traceback
                traceback.print_exc()
                await send_text(phone, "❌ Something went wrong creating the document. Please try again.")
                return

            if result.get("success"):
                session.pop("pending_action", None)
                session["conversation_history"] = _sanitize_history((session.get("conversation_history") or []) + [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": result.get("message", "Action completed successfully")}
                ])
                session["conversation_history"] = session["conversation_history"][-15:]
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(phone, result.get("message", "Action completed successfully"))
                await _send_action_pdf(result)
            elif result.get("stage") == "awaiting_otp":
                pending_action["stage"] = "awaiting_otp"
                await set_session(session_id, {**session, "pending_action": pending_action}, ttl=session_ttl)
                await send_text(phone, result.get("message"))
            elif result.get("stage") == "awaiting_approval":
                pending_action["stage"] = "awaiting_approval"
                await set_session(session_id, {**session, "pending_action": pending_action}, ttl=session_ttl)
                await send_text(phone, result.get("message"))
            else:
                session.pop("pending_action", None)
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(phone, result.get("message", "Action failed"))
            return

        if text_lower in _CANCEL_WORDS:
            session.pop("pending_action", None)
            await set_session(session_id, session, ttl=session_ttl)
            await send_text(phone, "❌ Action cancelled.")
            return

        # Unrecognised reply while awaiting confirm — treat as correction/new info
        session.pop("pending_action", None)
        await set_session(session_id, session, ttl=session_ttl)
        pending_action = None
        # fall through to agent

    # 9. OTP reply for pending action
    elif pending_action and pending_action.get("stage") == "awaiting_otp":
        if text.strip().lower() == "retry":
            session.pop("pending_action", None)
            session.pop("state", None)
            await set_session(session_id, session, ttl=session_ttl)
            await send_text(phone, "🔄 Session cleared. Please resend your original request.")
            return

        otp_result = await verify_otp(user["user_id"], text.strip())

        if otp_result["valid"]:
            try:
                exec_result = await execute_pending_action(pending_action, user, otp_verified=True)
            except Exception as e:
                print(f"[WEBHOOK] execute_pending_action after OTP error: {e}")
                import traceback
                traceback.print_exc()
                await send_text(phone, "❌ Something went wrong after verification. Please try again.")
                return

            if exec_result.get("success"):
                session.pop("pending_action", None)
                session["conversation_history"] = _sanitize_history((session.get("conversation_history") or []) + [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": exec_result.get("message", "Action completed successfully")}
                ])
                session["conversation_history"] = session["conversation_history"][-15:]
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(phone, exec_result.get("message", "Action completed successfully"))
                await _send_action_pdf(exec_result)
            elif exec_result.get("stage") == "awaiting_approval":
                pending_action["stage"] = "awaiting_approval"
                await set_session(session_id, {**session, "pending_action": pending_action}, ttl=session_ttl)
                await send_text(phone, exec_result.get("message"))
            else:
                session.pop("pending_action", None)
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(phone, exec_result.get("message", "Action failed"))
        else:
            await send_text(phone, f"❌ {otp_result['reason']}")
        return

    # 10. Run the agent — refresh session in case it was updated above
    session = await get_session(session_id)
    conversation_history = session.get("conversation_history", [])
    pending_action = session.get("pending_action")

    # Slot extraction mode: if pending_action exists, extract fields and merge
    if pending_action and pending_action.get("stage") != "awaiting_confirmation":
        from app.services.agent import _extract_fields_from_message
        intent_key = pending_action.get("intent_key")
        existing_fields = pending_action.get("fields", {})

        print(f"[WEBHOOK] Slot extraction mode for intent: {intent_key}")

        # Extract fields from new message
        extracted_fields = await _extract_fields_from_message(text, intent_key, user)
        print(f"[WEBHOOK] Extracted fields: {extracted_fields}")

        # Merge into existing draft
        merged_fields = {**existing_fields, **extracted_fields}

        # Validate merged draft
        from app.services.agent import _validate_draft
        validation = await _validate_draft(intent_key, merged_fields, user["org_id"])

        # Update pending_action with merged fields
        pending_action["fields"] = merged_fields
        session["pending_action"] = pending_action

        if validation.get("complete"):
            # Draft complete - move to confirmation
            pending_action["stage"] = "awaiting_confirmation"
            session["pending_action"] = pending_action
            await set_session(session_id, session, ttl=session_ttl)

            # Generate confirmation message
            confirm_text = f"⚠️ Confirm Action\n\n"
            confirm_text += pending_action.get("action_description", "Complete the action")
            confirm_text += "\n\nReply yes to confirm or no to cancel."

            session["conversation_history"] = _sanitize_history(conversation_history + [
                {"role": "user", "content": text},
                {"role": "assistant", "content": confirm_text}
            ])
            session["conversation_history"] = session["conversation_history"][-15:]
            await set_session(session_id, session, ttl=session_ttl)

            await send_text(phone, confirm_text)
            return
        else:
            # Draft incomplete - ask for missing fields
            missing = validation.get("missing_fields", [])
            ask_text = f"I have the following information:\n"
            for key, value in merged_fields.items():
                if value:
                    ask_text += f"  • {key}: {value}\n"
            ask_text += f"\nI still need: {', '.join(missing)}"
            ask_text += "\n\nPlease provide the missing details."

            session["conversation_history"] = _sanitize_history(conversation_history + [
                {"role": "user", "content": text},
                {"role": "assistant", "content": ask_text}
            ])
            session["conversation_history"] = session["conversation_history"][-15:]
            await set_session(session_id, session, ttl=session_ttl)

            await send_text(phone, ask_text)
            return

    # Sanitize conversation history - remove tool messages and tool_call assistant messages
    sanitized_history = []
    has_corrupted = False
    for msg in conversation_history:
        if msg.get("role") == "tool":
            has_corrupted = True
            continue
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            has_corrupted = True
            continue
        if msg.get("role") in ("user", "assistant"):
            if msg.get("content") and not msg.get("tool_calls"):
                sanitized_history.append(msg)

    # If corrupted history detected, clear the session to prevent API errors
    if has_corrupted:
        print(f"[WEBHOOK] Corrupted history detected, clearing session {session_id}")
        session = {"conversation_history": [], "pending_action": None}
        conversation_history = []
        pending_action = None
        await set_session(session_id, session, ttl=session_ttl)
    else:
        conversation_history = sanitized_history

    # Emergency: if conversation history is too long (>20 messages), clear it
    if len(conversation_history) > 20:
        print(f"[WEBHOOK] History too long ({len(conversation_history)}), clearing session {session_id}")
        session = {"conversation_history": [], "pending_action": None}
        conversation_history = []
        pending_action = None
        await set_session(session_id, session, ttl=session_ttl)

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
        updated_history = _sanitize_history(updated_history[-15:])
        session["last_message"] = text
        session["conversation_history"] = updated_history
        await set_session(session_id, session, ttl=session_ttl)

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
