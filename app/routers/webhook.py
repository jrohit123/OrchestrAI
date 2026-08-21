import os
import json
import hmac
import hashlib
from fastapi import APIRouter, Request, Response
from dotenv import load_dotenv

from app.config import required
from app.logging_config import get_context_logger, bind_context
from app.services.identity import resolve_identity, check_permission, check_route_permission
from app.services.messaging import send_text
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

logger = get_context_logger(__name__)
from app.db import fetch_one, execute

load_dotenv()

router = APIRouter()

VERIFY_TOKEN      = required("WHATSAPP_VERIFY_TOKEN")
APP_SECRET        = required("WHATSAPP_APP_SECRET")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")

_CONFIRM_WORDS = frozenset({
    "yes", "y", "haan", "ha", "ok", "confirm", "confirmed",
    "theek hai", "thik hai", "sahi hai", "go ahead", "proceed", "👍",
})
_CANCEL_WORDS = frozenset({
    "no", "n", "nahi", "na", "cancel", "stop",
    "start over", "restart", "forget it", "scrap it", "scrap that",
    "discard", "discard it", "reset", "never mind", "nevermind",
})
_RESTART_WORDS = frozenset({
    "restart", "start over", "new", "fresh", "cancel", "stop",
    "register_complaint", "complaint", "case", "file", "register"
})


async def _clear_stuck_draft(user: dict, session: dict, session_id: str, session_ttl: int,
                              reason: str = "cancelled") -> None:
    """
    Single source of truth for clearing a draft. MUST be used everywhere a
    draft is abandoned/cancelled/timed-out/capped. Closing only the Redis
    session copy (session.pop("pending_action")) without also closing the
    authoritative `user_drafts` DB row leaves that row active — the
    DB-rehydration logic in handle_message will silently bring the exact
    same "cleared" draft right back on the very next message.

    `reason` must be a value allowed by user_drafts_stage_check — currently:
    collecting / awaiting_confirmation / awaiting_otp / awaiting_approval /
    done / cancelled. Use "cancelled" unless you've added a new allowed
    value (see the optional 'expired' migration note below).
    """
    from app.services.draft_store import close_draft
    await close_draft(user["org_id"], user["user_id"], reason, source_key=user["source_key"])
    session.pop("pending_action", None)
    await set_session(session_id, session, ttl=session_ttl)


def verify_signature(raw: bytes, header: str | None) -> bool:
    """Verify WhatsApp webhook signature using HMAC-SHA256."""
    if not header or not header.startswith('sha256='):
        return False
    expected = hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split('=', 1)[1])


# ── META WEBHOOK VERIFICATION (GET) ──────────────────
@router.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and hmac.compare_digest(token or "", VERIFY_TOKEN):
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


# ── INBOUND MESSAGES (POST) ───────────────────────────
@router.post("/webhook/whatsapp")
async def receive_message(request: Request):
    # Verify signature first - fail-closed
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=403)
    
    body = json.loads(raw)

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

        # ── Normalize: WhatsApp omits +, DB stores with + ──
        if phone and not phone.startswith('+'):
            phone = '+' + phone

        # ── Extract text ──
        if msg_type == "text":
            text = msg["text"]["body"]
        elif msg_type == "interactive":
            inter = msg["interactive"]
            if inter.get("type") == "list_reply":
                text = inter["list_reply"]["id"]
            else:
                text = inter["button_reply"]["id"]
        else:
            return {"status": "ok"}

        # ── Deduplication: atomic check-and-set using message ID ──
        redis = get_redis()
        
        # Single atomic operation: set only if key doesn't exist
        msg_dedup_key = f"msg_processed:{msg_id}"
        was_set = await redis.set(msg_dedup_key, "1", ex=300, nx=True)
        if not was_set:
            logger.info(f"Duplicate msg_id {msg_id} — skipping")
            return {"status": "ok"}
        
        logger.debug(f"Deduplication key set: {msg_dedup_key}")
        logger.info(f"Message from {phone}: {text}")
        try:
            await handle_message(phone=phone, text=text, msg_type=msg_type)
        except Exception as e:
            logger.error(f"handle_message error: {e}", exc_info=True)
            try:
                await send_text(phone, "❌ Something went wrong. Please try again.")
            except Exception:
                pass

    except (KeyError, IndexError) as e:
        logger.warning(f"Parse error: {e}")

    return {"status": "ok"}


# ── CORE MESSAGE HANDLER ──────────────────────────────
async def handle_message(phone: str, text: str, msg_type: str = "text"):
    # 1. Identity
    user = await resolve_identity(phone)
    if not user:
        # Telegram linking flow — unregistered tg: user links via email + OTP
        if phone.startswith("tg:"):
            import re as _re
            chat_id = phone[3:]
            link_session_id = f"tglink:{phone}"
            pending_link = await get_session(link_session_id)

            # Step 2: user is replying with the OTP code
            if pending_link.get("state") == "awaiting_link_otp":
                if text.strip().lower() == "retry":
                    await delete_session(link_session_id)
                    await send_text(phone, "🔄 Cancelled. Please send your email again to restart linking.")
                    return

                result = await verify_otp(
                    pending_link["user_id"], text.strip(), pending_link["source_key"]
                )
                if result["valid"]:
                    from app.services.identity import bind_telegram_phone
                    linked_user = await bind_telegram_phone(
                        user_id=pending_link["user_id"],
                        chat_id=chat_id,
                        source_key=pending_link["source_key"],
                    )
                    await delete_session(link_session_id)
                    if linked_user:
                        await send_text(phone,
                            f"✅ *Linked!* Welcome, {linked_user['user_name']}.\n"
                            f"Your Telegram account is now connected to OrchestrAI.\n"
                            f"Send /help to see available commands."
                        )
                    else:
                        await send_text(phone, "❌ Something went wrong linking your account. Please try again.")
                else:
                    await send_text(phone, f"❌ {result['reason']}")
                return

            # Step 1: user just sent an email
            if _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text.strip()):
                from app.services.identity import find_unlinked_user_by_email
                candidate = await find_unlinked_user_by_email(text.strip())
                if candidate:
                    sent = await generate_and_send_otp(
                        user_id=candidate["user_id"],
                        user_email=candidate["email"],
                        user_name=candidate["user_name"],
                        org_name=candidate["org_name"],
                        org_id=candidate["org_id"],
                        action_context={"type": "telegram_link"},
                        source_key=candidate["source_key"],
                    )
                    if sent:
                        await set_session(link_session_id, {
                            "state": "awaiting_link_otp",
                            "user_id": str(candidate["user_id"]),
                            "source_key": candidate["source_key"],
                        }, ttl=180)
                        await send_text(phone,
                            f"🔐 A verification code has been sent to *{candidate['email']}*.\n"
                            f"Reply with the code to link your Telegram account.\n\n"
                            f"_Code expires in 3 minutes. Reply 'retry' to cancel and restart._"
                        )
                    else:
                        await send_text(phone, "❌ Could not send verification email. Contact admin.")
                else:
                    await send_text(phone,
                        "❌ No account found with that email. "
                        "Contact your admin to get registered, then send your email here to link."
                    )
                return

            await send_text(phone,
                "👋 Welcome to OrchestrAI!\n\n"
                "Your Telegram account isn't linked yet.\n"
                "Reply with your *registered email address* to link your account.\n\n"
                "_Example: john@example.com_"
            )
            return
        await send_text(phone,
            "👋 Your number isn't registered with OrchestrAI.\n"
            "Contact your admin to get access."
        )
        return

    if not user["is_active"] or not user["org_active"]:
        await send_text(phone, "❌ Your account is inactive. Contact admin.")
        return

    # ── Slash commands & menu ────────────────────────────────────────────
    from app.services.menu import build_menu_sections, resolve_slash_command
    from app.services.messaging import send_list

    text_stripped = text.strip()

    if text_stripped.startswith("/"):
        if text_stripped.lower() == "/cancel":
            await cancel_user_draft(user, phone, confirm=False)
            return
        if text_stripped.lower() in ("/help", "/h"):
            await send_text(phone,
                "📖 *How to use OrchestrAI*\n\n"
                "• Type / or 'menu' to see available workflows\n"
                "• Use slash commands for quick actions\n"
                "• Ask questions in plain English or Hindi\n"
                "• Say 'pdf' after any result to get a document\n"
                "• Tap /cancel to clear a draft in progress"
            )
            return
        if text_stripped.lower() in ("/status", "/mystatus", "/s"):
            from app.services.draft_store import get_active_draft
            draft = await get_active_draft(user["org_id"], user["user_id"], user["source_key"])
            if draft:
                intent = draft["intent_key"]
                stage = draft["stage"]
                fields = draft.get("fields", {})
                await send_text(phone,
                    f"📋 *Draft Status*\n"
                    f"Workflow: {intent}\n"
                    f"Stage: {stage}\n"
                    f"Fields collected: {len(fields)}\n\n"
                    f"Tap /cancel to clear this draft."
                )
            else:
                await send_text(phone, "✅ No active draft. You're ready to start fresh.")
            return
        wf = await resolve_slash_command(user["org_id"], user, text_stripped)
        if wf:
            # Pass intent_key directly to agent for execution
            text = wf['intent_key']
        else:
            sections = await build_menu_sections(user["org_id"], user)
            await send_list(phone, "Didn't recognise that command — here's what's available:",
                            "📋 Menu", sections)
            return

    # 2. Fetch org TTL
    org_row = await fetch_one(
        "SELECT session_ttl_minutes FROM orgs WHERE id = $1",
        user["org_id"], source_key=user["source_key"]
    )
    ttl_minutes = org_row["session_ttl_minutes"] if org_row else 480

    # 3. Security auth check
    sec_session_id = f"sec:{user['org_id']}:{phone}"
    is_authenticated = await check_auth_token(user["org_id"], phone)

    if not is_authenticated:
        pre_session = await get_session(sec_session_id)

        if pre_session.get("state") == "awaiting_security_otp":
            # Handle explicit retry — generate a fresh OTP instead of re-checking the stale one
            if text.strip().lower() == "retry":
                pending_text = pre_session.get("pending_text", "")
                sent = await generate_and_send_otp(
                    user_id=user["user_id"],
                    user_email=user["email"],
                    user_name=user["user_name"],
                    org_name=user["org_name"],
                    org_id=user["org_id"],
                    action_context={"type": "security_auth"},
                    source_key=user["source_key"]
                )
                if sent:
                    await set_session(sec_session_id, {
                        "state": "awaiting_security_otp",
                        "pending_text": pending_text
                    }, ttl=180)
                    await send_text(phone,
                        f"🔐 A new verification code has been sent to *{user['email']}*.\n"
                        f"Reply with the code to continue."
                    )
                else:
                    await send_text(phone, "❌ Could not send verification email. Contact admin.")
                return

            # User is replying with security OTP
            result = await verify_otp(user["user_id"], text.strip(), user["source_key"])
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
            org_id=user["org_id"],
            action_context={"type": "security_auth"},
            source_key=user["source_key"]
        )
        if sent:
            await set_session(sec_session_id, {
                "state": "awaiting_security_otp",
                "pending_text": text
            }, ttl=180)
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

    # Sanitize conversation history immediately after loading - remove tool messages
    # to prevent OpenAI API errors from corrupted history
    conversation_history = session.get("conversation_history", [])
    has_corrupted = False
    sanitized_history = []
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

    if has_corrupted:
        logger.warning(f"Corrupted history detected, sanitizing session {session_id}")
        session["conversation_history"] = sanitized_history
        conversation_history = sanitized_history
        await set_session(session_id, session, ttl=ttl_minutes * 60)

    # Rehydrate draft from DB if Redis has no pending_action but DB has active draft
    if not session.get("pending_action"):
        from app.services.draft_store import get_active_draft
        db_draft = await get_active_draft(user["org_id"], user["user_id"], user["source_key"])
        if db_draft and db_draft.get("intent_key"):
            logger.info(f"Rehydrating draft from DB: {db_draft['intent_key']}")
            # Parse fields if it's a JSON string from DB
            fields = db_draft.get("fields", {})
            if isinstance(fields, str):
                try:
                    fields = json.loads(fields)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Failed to parse draft fields: {e}")
                    fields = {}
            session["pending_action"] = {
                "intent_key": db_draft["intent_key"],
                "fields": fields,
                "stage": db_draft["stage"],
                "rehydrated": True
            }
            await set_session(session_id, session, ttl=ttl_minutes * 60)
            # Send greeting to user about the unfinished draft
            await send_text(phone,
                f"You have an unfinished *{db_draft['intent_key']}* — continue, or tap /cancel."
            )

    # 5. Approval button responses
    if msg_type == "interactive" and (text.startswith("action:approve:") or text.startswith("action:reject:")):
        parts = text.split(":")
        if len(parts) == 3:
            action = f"{parts[0]}:{parts[1]}"
            approval_id = parts[2]
            await handle_approval_response(phone, action, approval_id, user)
        return

    # 6. Disambiguation state (customer selection) - handled by agent clarify tool
    # Legacy disambiguation removed - agent now handles this via clarify tool

    # 7. OTP state (for invoice high value)
    if session.get("state") == "awaiting_otp":
        await _handle_otp_reply(phone, text, user, session, session_id)
        return

    session_ttl = ttl_minutes * 60
    pending_action = session.get("pending_action")

    # ── GUARD: same workflow re-tapped while its draft is already active ──
    # Tapping a menu row or slash command sends the raw intent_key as text
    # (e.g. "register_complaint"). If that intent_key matches the draft
    # that's already in progress, treating it as a free-text correction or
    # instruction corrupts the draft: it downgrades stage back to
    # "collecting" and stores the intent_key itself as a nonsensical
    # correction_hint, which then confuses the LLM into producing garbled
    # or fabricated replies. Just re-show the current draft instead.
    if (
        pending_action
        and pending_action.get("stage") in ("collecting", "awaiting_confirmation")
        and text.strip() == pending_action.get("intent_key")
    ):
        fields = pending_action.get("fields") or {}
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except (json.JSONDecodeError, TypeError):
                fields = {}
        details = "\n".join(f"  • {k}: {v}" for k, v in fields.items()) or "  (nothing yet)"
        if pending_action.get("stage") == "awaiting_confirmation":
            await send_text(phone,
                f"You already have a *{pending_action['intent_key']}* draft waiting for confirmation:\n"
                f"{details}\n\nReply *yes* to confirm, *no* to cancel, or tell me what to change."
            )
        else:
            await send_text(phone,
                f"You're already filling out *{pending_action['intent_key']}*. So far:\n"
                f"{details}\n\nPlease continue with the remaining details, or /cancel to start over."
            )
        return

    async def _send_action_pdf(exec_result: dict):
        if not exec_result.get("pdf_bytes"):
            return
        from app.services.messaging import send_document
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
                result = await execute_pending_action(pending_action, user, phone=phone)
            except Exception as e:
                logger.error(f"execute_pending_action error: {e}", exc_info=True)
                await send_text(phone, "❌ Something went wrong creating the document. Please try again.")
                return

            if result.get("success"):
                session.pop("pending_action", None)
                session["conversation_history"] = (session.get("conversation_history") or []) + [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": result.get("message", "Action completed successfully")}
                ]
                session["conversation_history"] = session["conversation_history"][-15:]
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(phone, result.get("message", "Action completed successfully"))
                await _send_action_pdf(result)
            elif result.get("stage") == "awaiting_otp":
                pending_action["stage"]       = "awaiting_otp"
                pending_action["resume_step"] = result.get("resume_step", 0)
                await set_session(session_id, {**session, "pending_action": pending_action}, ttl=session_ttl)
                await send_text(phone, result.get("message"))
            elif result.get("stage") == "awaiting_approval":
                pending_action["stage"]       = "awaiting_approval"
                pending_action["resume_step"] = result.get("resume_step", 0)
                await set_session(session_id, {**session, "pending_action": pending_action}, ttl=session_ttl)
                await send_text(phone, result.get("message"))
            else:
                session.pop("pending_action", None)
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(phone, result.get("message", "Action failed"))
            return

        if text_lower in _CANCEL_WORDS:
            await _clear_stuck_draft(user, session, session_id, session_ttl, reason="cancelled")
            await send_text(phone, "❌ Action cancelled.")
            return

        # Unrecognised reply while awaiting confirm — check staleness first, then treat as correction
        if pending_action:
            from app.services.agent import _is_draft_stale, _MAX_REPROMPT_COUNT

            if _is_draft_stale(pending_action):
                # Confirmation window (10 min) has expired — drop the draft entirely
                # and let the message fall through as a brand-new request.
                logger.info(f"Stale awaiting_confirmation draft detected — clearing")
                await _clear_stuck_draft(user, session, session_id, session_ttl, reason="cancelled")
                pending_action = None
                await send_text(phone,
                    "_⏱️ Your previous confirmation timed out and was cleared. "
                    "Let me help with your new request._"
                )
                # fall through to agent with pending_action=None
            else:
                # Check if user wants to restart with a new intent
                text_lower_for_restart = text.strip().lower()
                if any(word in text_lower_for_restart for word in _RESTART_WORDS):
                    # Clear existing draft and start fresh
                    from app.services.draft_store import close_draft
                    logger.info(f"Intent restart detected — clearing draft")
                    session.pop("pending_action", None)
                    await set_session(session_id, session, ttl=session_ttl)
                    # Also clear from database
                    await close_draft(user["org_id"], user["user_id"], "cancelled", source_key=user["source_key"])
                    await send_text(phone,
                        "_⏱️ Previous draft cleared. Starting fresh..._"
                    )
                    # fall through to agent with pending_action=None
                    pending_action = None
                else:
                    # Still fresh — treat as a correction to the existing draft.
                    # Downgrade stage so the agent re-enters collection mode.
                    # NOTE: reprompt_count is incremented once, later, by the
                    # collecting-stage check further down — do NOT increment it
                    # here too, or corrections get double-counted and hit the
                    # cap in half the intended number of turns.
                    current_reprompt_count = pending_action.get("reprompt_count", 0)
                    if current_reprompt_count >= _MAX_REPROMPT_COUNT:
                        # Cap hit — the user and the bot are going in circles. Force a clean restart.
                        logger.warning(f"Reprompt cap ({_MAX_REPROMPT_COUNT}) reached — clearing draft")
                        await _clear_stuck_draft(user, session, session_id, session_ttl, reason="cancelled")
                        await send_text(phone,
                            "🤔 I'm having trouble understanding the details for this request. "
                            "Let's start fresh — please send your request again with all the details "
                            "in one message, e.g. *\"invoice Mehta Enterprises Rs.92,000\"*."
                        )
                        return
                    pending_action["stage"] = "collecting"
                    pending_action["correction_hint"] = text
                    session["pending_action"] = pending_action
                    await set_session(session_id, session, ttl=session_ttl)
                    # fall through to agent — step 10 below will increment reprompt_count once
        else:
            # No draft at all — just fall through
            pass
        # fall through to agent

    # 9. OTP reply for pending action
    elif pending_action and pending_action.get("stage") == "awaiting_otp":
        if text.strip().lower() == "retry":
            session.pop("pending_action", None)
            session.pop("state", None)
            await set_session(session_id, session, ttl=session_ttl)
            await send_text(phone, "🔄 Session cleared. Please resend your original request.")
            return

        otp_result = await verify_otp(user["user_id"], text.strip(), user["source_key"])

        if otp_result["valid"]:
            try:
                exec_result = await execute_pending_action(pending_action, user, phone=phone, otp_verified=True)
            except Exception as e:
                logger.error(f"execute_pending_action after OTP error: {e}", exc_info=True)
                await send_text(phone, "❌ Something went wrong after verification. Please try again.")
                return

            if exec_result.get("success"):
                session.pop("pending_action", None)
                session["conversation_history"] = (session.get("conversation_history") or []) + [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": exec_result.get("message", "Action completed successfully")}
                ]
                session["conversation_history"] = session["conversation_history"][-15:]
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(phone, exec_result.get("message", "Action completed successfully"))
                await _send_action_pdf(exec_result)
            elif exec_result.get("stage") == "awaiting_approval":
                pending_action["stage"]       = "awaiting_approval"
                pending_action["resume_step"] = exec_result.get("resume_step", 0)
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

    # Reprompt cap check for collecting stage (same cap, different entry point than confirm stage)
    if pending_action and pending_action.get("stage") == "collecting":
        from app.services.agent import _MAX_REPROMPT_COUNT
        reprompt_count = pending_action.get("reprompt_count", 0)
        if reprompt_count >= _MAX_REPROMPT_COUNT:
            print(f"[WEBHOOK] Collecting-stage reprompt cap ({_MAX_REPROMPT_COUNT}) reached — clearing draft")
            await _clear_stuck_draft(user, session, session_id, session_ttl, reason="cancelled")
            await send_text(phone,
                "🤔 I'm having trouble understanding the details for this request. "
                "Let's start fresh — please send your request again with all the details "
                "in one message, e.g. *\"invoice Mehta Enterprises Rs.92,000\"*."
            )
            return
        # Increment reprompt_count each turn we stay in collecting mode
        pending_action["reprompt_count"] = reprompt_count + 1
        session["pending_action"] = pending_action
        await set_session(session_id, session, ttl=session_ttl)

    try:
        reply, updated_history, session_patch = await run_agent(
            text, user, phone,
            conversation_history=conversation_history,
            pending_action=pending_action
        )

        # Capture the menu flag BEFORE popping it
        sent_menu = bool(session_patch.get("_send_menu"))

        # Check if agent wants to send interactive menu
        if sent_menu:
            from app.services.messaging import send_list
            await send_list(phone, reply, session_patch["button_label"], session_patch["menu_sections"])
            # Remove menu flag from session_patch before saving
            session_patch.pop("_send_menu", None)
            session_patch.pop("menu_sections", None)
            session_patch.pop("button_label", None)
            # Save history without assistant reply (menu is the reply)
            updated_history = updated_history or [{"role": "user", "content": text}]
        else:
            # Apply session patch if any
            if session_patch:
                session = {**session, **session_patch}
                # Update pending_action reference for next iteration
                pending_action = session_patch.get("pending_action")

            # Save last 15 messages (7-8 turns) for context
            # Ensure agent reply is in history (it's present for normal text replies,
            # but clarify-path skips it — add it here unconditionally if not already last)
            if not updated_history or updated_history[-1].get("content") != reply:
                updated_history = updated_history + [{"role": "assistant", "content": reply}]

            updated_history = updated_history[-15:]
            session["last_message"] = text
        session["conversation_history"] = updated_history
        await set_session(session_id, session, ttl=session_ttl)

        # Only send text reply if not sending menu
        if not sent_menu:
            await send_text(phone, reply)

            # Log to audit_log
            await execute("""
                INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome)
                VALUES ($1, $2, 'agent', $3, 'success')
            """, user["org_id"], user["user_id"], text, source_key=user["source_key"])
        else:
            # Log to audit_log for menu responses too
            await execute("""
                INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome)
                VALUES ($1, $2, 'menu', $3, 'success')
            """, user["org_id"], user["user_id"], text, source_key=user["source_key"])

    except Exception as e:
        logger.error(f"handle_message error: {e}", exc_info=True)
        correlation_id = ""
        try:
            from app.logging_config import correlation_id as get_correlation_id
            correlation_id = get_correlation_id.get()
        except:
            pass
        await send_text(phone,
            f"❌ Something went wrong. Error ID: {correlation_id}. Please try again or contact support."
        )


# ── SYSTEM ROW HANDLERS ─────────────────────────────────
async def handle_system_row(text: str, user: dict, phone: str):
    """Handle sys:status, sys:cancel, sys:help from menu."""
    from app.services.draft_store import get_active_draft, close_draft
    
    if text == "sys:status":
        draft = await get_active_draft(user["org_id"], user["user_id"], user["source_key"])
        if draft:
            intent = draft["intent_key"]
            stage = draft["stage"]
            fields = draft.get("fields", {})
            await send_text(phone,
                f"📋 *Draft Status*\n"
                f"Workflow: {intent}\n"
                f"Stage: {stage}\n"
                f"Fields collected: {len(fields)}\n\n"
                f"Tap /cancel to clear this draft."
            )
        else:
            await send_text(phone, "✅ No active draft. You're ready to start fresh.")
    
    elif text == "sys:cancel":
        await cancel_user_draft(user, phone, confirm=True)
    
    elif text == "sys:help":
        await send_text(phone,
            "📖 *How to use OrchestrAI*\n\n"
            "• Type / or 'menu' to see available workflows\n"
            "• Use slash commands for quick actions\n"
            "• Ask questions in plain English or Hindi\n"
            "• Say 'pdf' after any result to get a document\n"
            "• Tap /cancel to clear a draft in progress"
        )

async def cancel_user_draft(user: dict, phone: str, confirm: bool = True):
    """Cancel the user's active draft. This always cancels immediately —
    `confirm` only controls whether the message mentions how much is being
    discarded. (Previously this claimed to wait for a 'yes' reply but
    cancelled unconditionally regardless of the reply — fixed to be honest
    about what it actually does.)"""
    from app.services.draft_store import get_active_draft, close_draft

    draft = await get_active_draft(user["org_id"], user["user_id"], user["source_key"])
    if not draft:
        await send_text(phone, "✅ No active draft to cancel.")
        return

    field_count = len(draft.get("fields", {}))
    await close_draft(user["org_id"], user["user_id"], "cancelled", source_key=user["source_key"])

    if confirm and field_count >= 2:
        await send_text(phone,
            f"🔄 Draft for *{draft['intent_key']}* cancelled ({field_count} field(s) discarded)."
        )
    else:
        await send_text(phone, "🔄 Draft cancelled.")


# ── OTP REPLY HANDLER (invoice high value) ────────────
async def _handle_otp_reply(phone, text, user, session, session_id):
    if text.strip().lower() == "retry":
        await set_session(session_id, {})
        await send_text(phone, "🔄 Session cleared. Please resend your original request.")
        return

    result = await verify_otp(user["user_id"], text.strip(), user["source_key"])

    if result["valid"]:
        # Refresh auth token on successful OTP
        org_row = await fetch_one(
            "SELECT session_ttl_minutes FROM orgs WHERE id = $1", user["org_id"], source_key=user["source_key"]
        )
        ttl = org_row["session_ttl_minutes"] if org_row else 480
        await set_auth_token(user["org_id"], phone, ttl)
        await set_session(session_id, {**session, "state": "otp_verified", "otp_verified": True})
        reply = await resume_after_otp(user, session_id, session)
        await send_text(phone, reply)
    else:
        await send_text(phone, f"❌ {result['reason']}")
