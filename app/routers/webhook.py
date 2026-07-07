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
            inter = msg["interactive"]
            if inter.get("type") == "list_reply":
                text = inter["list_reply"]["id"]
            else:
                text = inter["button_reply"]["id"]
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

    # ── Slash commands & menu ────────────────────────────────────────────
    from app.services.menu import build_menu_sections, resolve_slash_command, get_menu_workflows
    from app.services.whatsapp import send_list

    text_stripped = text.strip()

    if text_stripped in ("/", "/menu") or text_stripped.lower() == "menu":
        sections = await build_menu_sections(user["org_id"], user)
        await send_list(phone, "What would you like to do?", "📋 Menu", sections)
        return

    # Detect natural language menu requests
    menu_keywords = ["menu", "options", "what can i do", "what can you do", "help me", "show menu", "access menu"]
    if any(kw in text_stripped.lower() for kw in menu_keywords):
        sections = await build_menu_sections(user["org_id"], user)
        await send_list(phone, "What would you like to do?", "📋 Menu", sections)
        return

    if text_stripped.startswith("/"):
        if text_stripped.lower() == "/cancel":
            await cancel_user_draft(user, phone, confirm=False)
            return
        if text_stripped.lower() in ("/help", "/h"):
            await send_text(phone,
                "📖 *How to use OrchestrAI*\n\n"
                "• Type / or 'menu' to see available workflows\n"
                "• Use slash commands like /invoice, /quote for quick access\n"
                "• Ask questions in plain English or Hindi\n"
                "• Say 'pdf' after any result to get a document\n"
                "• Tap /cancel to clear a draft in progress"
            )
            return
        if text_stripped.lower() in ("/status", "/mystatus", "/s"):
            from app.services.draft_store import get_active_draft
            draft = await get_active_draft(user["org_id"], user["user_id"])
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

    # ── Direct intent_key from a list-row tap ────────────────────────────
    # This is now redundant since we pass intent_key directly from slash commands
    # But keep it for other cases where intent_key comes directly
    allowed = {w["intent_key"]: w for w in await get_menu_workflows(user["org_id"], user)}
    
    if text_stripped in allowed:
        # Already handled by slash command logic above, skip to avoid duplicate
        pass

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
            org_id=user["org_id"],
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
        print(f"[WEBHOOK] Corrupted history detected, sanitizing session {session_id}")
        session["conversation_history"] = sanitized_history
        conversation_history = sanitized_history
        await set_session(session_id, session, ttl=ttl_minutes * 60)

    # Rehydrate draft from DB if Redis has no pending_action but DB has active draft
    if not session.get("pending_action"):
        from app.services.draft_store import get_active_draft
        db_draft = await get_active_draft(user["org_id"], user["user_id"])
        if db_draft:
            print(f"[WEBHOOK] Rehydrating draft from DB: {db_draft['intent_key']}")
            session["pending_action"] = {
                "intent_key": db_draft["intent_key"],
                "fields": db_draft.get("fields", {}),
                "stage": db_draft["stage"],
                "rehydrated": True
            }
            await set_session(session_id, session, ttl=ttl_minutes * 60)
            # Send greeting to user about the unfinished draft
            await send_text(phone,
                f"You have an unfinished *{db_draft['intent_key']}* — continue, or tap /cancel."
            )

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
                result = await execute_pending_action(pending_action, user, phone=phone)
            except Exception as e:
                print(f"[WEBHOOK] execute_pending_action error: {e}")
                import traceback
                traceback.print_exc()
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
            session.pop("pending_action", None)
            await set_session(session_id, session, ttl=session_ttl)
            await send_text(phone, "❌ Action cancelled.")
            return

        # Unrecognised reply while awaiting confirm — check staleness first, then treat as correction
        if pending_action:
            from app.services.agent import _is_draft_stale, _MAX_REPROMPT_COUNT

            if _is_draft_stale(pending_action):
                # Confirmation window (10 min) has expired — drop the draft entirely
                # and let the message fall through as a brand-new request.
                print(f"[WEBHOOK] Stale awaiting_confirmation draft detected — clearing")
                session.pop("pending_action", None)
                await set_session(session_id, session, ttl=session_ttl)
                pending_action = None
                await send_text(phone,
                    "_⏱️ Your previous confirmation timed out and was cleared. "
                    "Let me help with your new request._"
                )
                # fall through to agent with pending_action=None
            else:
                # Still fresh — treat as a correction to the existing draft.
                # Downgrade stage so the agent re-enters collection mode.
                reprompt_count = pending_action.get("reprompt_count", 0) + 1
                if reprompt_count >= _MAX_REPROMPT_COUNT:
                    # Cap hit — the user and the bot are going in circles. Force a clean restart.
                    print(f"[WEBHOOK] Reprompt cap ({_MAX_REPROMPT_COUNT}) reached — clearing draft")
                    session.pop("pending_action", None)
                    await set_session(session_id, session, ttl=session_ttl)
                    await send_text(phone,
                        "🤔 I'm having trouble understanding the details for this request. "
                        "Let's start fresh — please send your request again with all the details "
                        "in one message, e.g. *\"invoice Mehta Enterprises Rs.92,000\"*."
                    )
                    return
                pending_action["stage"] = "collecting"
                pending_action["correction_hint"] = text
                pending_action["reprompt_count"] = reprompt_count
                session["pending_action"] = pending_action
                await set_session(session_id, session, ttl=session_ttl)
                # fall through to agent
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

        otp_result = await verify_otp(user["user_id"], text.strip())

        if otp_result["valid"]:
            try:
                exec_result = await execute_pending_action(pending_action, user, phone=phone, otp_verified=True)
            except Exception as e:
                print(f"[WEBHOOK] execute_pending_action after OTP error: {e}")
                import traceback
                traceback.print_exc()
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
            session.pop("pending_action", None)
            await set_session(session_id, session, ttl=session_ttl)
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

        # Check if agent wants to send interactive menu
        if session_patch.get("_send_menu"):
            from app.services.whatsapp import send_list
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
        if not session_patch.get("_send_menu"):
            await send_text(phone, reply)

            # Log to audit_log
            await execute("""
                INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome)
                VALUES ($1, $2, 'agent', $3, 'success')
            """, user["org_id"], user["user_id"], text)
        else:
            # Log to audit_log for menu responses too
            await execute("""
                INSERT INTO audit_log (org_id, user_id, intent_key, input_text, outcome)
                VALUES ($1, $2, 'menu', $3, 'success')
            """, user["org_id"], user["user_id"], text)

    except Exception as e:
        print(f"[AGENT] Error: {e}")
        import traceback
        traceback.print_exc()
        await send_text(phone,
            f"🤔 Error: {str(e)}"
        )


# ── SYSTEM ROW HANDLERS ─────────────────────────────────
async def handle_system_row(text: str, user: dict, phone: str):
    """Handle sys:status, sys:cancel, sys:help from menu."""
    from app.services.draft_store import get_active_draft, close_draft
    
    if text == "sys:status":
        draft = await get_active_draft(user["org_id"], user["user_id"])
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
            "• Use slash commands like /invoice, /quote for quick access\n"
            "• Ask questions in plain English or Hindi\n"
            "• Say 'pdf' after any result to get a document\n"
            "• Tap /cancel to clear a draft in progress"
        )

async def cancel_user_draft(user: dict, phone: str, confirm: bool = True):
    """Cancel the user's active draft."""
    from app.services.draft_store import get_active_draft, close_draft
    
    draft = await get_active_draft(user["org_id"], user["user_id"])
    if not draft:
        await send_text(phone, "✅ No active draft to cancel.")
        return
    
    if confirm and len(draft.get("fields", {})) >= 2:
        # Ask for confirmation if draft has substantial data
        await send_text(phone,
            f"⚠️ You have a draft for *{draft['intent_key']}* with {len(draft['fields'])} fields.\n"
            f"Reply 'yes' to cancel, or continue working."
        )
        # Note: In a full implementation, we'd set a state to await confirmation
        # For now, we'll cancel directly as this is a safety escape hatch
        await close_draft(user["org_id"], user["user_id"], "cancelled")
        await send_text(phone, "🔄 Draft cancelled.")
    else:
        await close_draft(user["org_id"], user["user_id"], "cancelled")
        await send_text(phone, "🔄 Draft cancelled.")


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
