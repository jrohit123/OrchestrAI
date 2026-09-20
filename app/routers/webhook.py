import hashlib
import hmac
import json
import os
import re

from dotenv import load_dotenv
from fastapi import APIRouter, Request, Response

from app.config import required
from app.executor.workflow_executor import handle_approval_response, resume_after_otp
from app.logging_config import get_context_logger
from app.redis_client import (
    check_auth_token,
    delete_session,
    get_redis,
    get_session,
    set_auth_token,
    set_session,
)
from app.services.action_executor import execute_pending_action
from app.services.agent import run_agent
from app.services.identity import resolve_identity
from app.services.messaging import send_text
from app.services.onboarding_parsing import extract_email, extract_otp_candidates
from app.services.otp_service import generate_and_send_otp, verify_otp

logger = get_context_logger(__name__)
from app.db import execute, fetch_all, fetch_one

load_dotenv()

router = APIRouter()

VERIFY_TOKEN = required("WHATSAPP_VERIFY_TOKEN")
APP_SECRET = required("WHATSAPP_APP_SECRET")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")

# Confirm/cancel/self-reference vocabulary is per-org config now — see
# app/services/vocabulary.py. What used to be hardcoded here is that
# module's built-in default, applied when an org hasn't overridden it via
# orgs.settings->'vocabulary'.


async def _clear_stuck_draft(
    user: dict,
    session: dict,
    session_id: str,
    session_ttl: int,
    reason: str = "cancelled",
) -> None:
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

    await close_draft(
        user["org_id"], user["user_id"], reason, source_key=user["source_key"]
    )
    session.pop("pending_action", None)
    await set_session(session_id, session, ttl=session_ttl)


def verify_signature(raw: bytes, header: str | None) -> bool:
    """Verify WhatsApp webhook signature using HMAC-SHA256."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


# ── META WEBHOOK VERIFICATION (GET) ──────────────────
@router.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
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
        entry = body["entry"][0]
        changes = entry["changes"][0]["value"]

        # ── Ignore status updates (delivered, read, sent) ──
        if "statuses" in changes and "messages" not in changes:
            return {"status": "ok"}

        # ── Ignore if no messages ──
        if "messages" not in changes:
            return {"status": "ok"}

        msg = changes["messages"][0]
        phone = msg["from"]
        msg_id = msg["id"]
        msg_type = msg.get("type", "text")

        # ── Ignore echo (message from our own bot number) ──
        if phone == WHATSAPP_PHONE_ID:
            return {"status": "ok"}

        # ── Normalize: WhatsApp omits +, DB stores with + ──
        if phone and not phone.startswith("+"):
            phone = "+" + phone

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
            except Exception as fallback_err:
                logger.warning(
                    f"Fallback error message to {phone} also failed: {fallback_err}"
                )

    except (KeyError, IndexError) as e:
        logger.warning(f"Parse error: {e}")

    return {"status": "ok"}


async def _handle_email_submission(
    phone: str, email: str, link_session_id: str
) -> None:
    """
    Given a candidate email address (already extracted from free text),
    either kicks off account linking (an existing unlinked user matches it)
    or starts self-registration (no match). Shared by the initial "send
    your email" step and the confirm screen's "change email to X" edit —
    both need identical branching, since changing the email mid-
    registration might turn out to match an existing account instead of
    just being a typo fix.
    """
    from app.services.identity import find_unlinked_user_by_email

    candidate = await find_unlinked_user_by_email(email)
    if candidate:
        result = await generate_and_send_otp(
            user_id=candidate["user_id"],
            user_email=candidate["email"],
            user_name=candidate["user_name"],
            org_name=candidate["org_name"],
            org_id=candidate["org_id"],
            action_context={"type": "telegram_link"},
            source_key=candidate["source_key"],
        )
        if result["sent"]:
            await set_session(
                link_session_id,
                {
                    "state": "awaiting_link_otp",
                    "user_id": str(candidate["user_id"]),
                    "source_key": candidate["source_key"],
                },
                ttl=180,
            )
            await send_text(
                phone,
                f"🔐 A verification code has been sent to *{candidate['email']}*.\n"
                f"Reply with the code to link your Telegram account.\n\n"
                f"_Code expires in {result['expiry_minutes']} minutes. Reply 'retry' to cancel and restart._",
            )
        elif result["reason"] == "cooldown":
            await send_text(
                phone,
                f"⏳ Please wait {result['wait_seconds']}s before requesting another code.",
            )
        else:
            await send_text(
                phone, "❌ Could not send verification email. Contact admin."
            )
    else:
        await set_session(
            link_session_id,
            {
                "state": "awaiting_new_user_name",
                "new_user_email": email,
            },
            ttl=300,
        )
        await send_text(
            phone,
            "No existing account found for that email.\n\n"
            "Want to register as a new member? Reply with your *full name* to "
            "get started — or contact your admin if you already have an "
            "account under a different email.",
        )


# ── CORE MESSAGE HANDLER ──────────────────────────────
async def handle_message(phone: str, text: str, msg_type: str = "text"):
    # 1. Identity
    user = await resolve_identity(phone)
    if not user:
        # Telegram linking flow — unregistered tg: user links via email + OTP,
        # or self-registers a brand-new account if no existing one matches.
        if phone.startswith("tg:"):
            chat_id = phone[3:]
            link_session_id = f"tglink:{phone}"
            pending_link = await get_session(link_session_id)

            # Self-registration needs SOME org to create the new user under.
            # Resolved from the routing DB's data_sources.messaging_channel
            # column — since this whole branch only runs for phone.startswith
            # ("tg:"), i.e. a message that arrived on the Telegram webhook,
            # whichever org is configured as owning "telegram" is the answer.
            # Not a Python-level guess: if a second org goes live on Telegram
            # this raises loudly (see get_source_key_for_channel) instead of
            # silently misrouting new accounts to the wrong org.
            from app.db import get_source_key_for_channel

            try:
                NEW_USER_ORG_SOURCE_KEY = await get_source_key_for_channel("telegram")
            except RuntimeError as e:
                logger.error(f"Cannot resolve org for Telegram self-registration: {e}")
                await send_text(
                    phone,
                    "❌ Registration isn't available right now. Please contact your admin.",
                )
                return

            # Step 3: user is registering a brand-new account (no existing
            # unlinked user matched their email) — collecting name, then
            # role, then a final confirm, before creating the account and
            # falling through to the SAME OTP-verify flow as Step 2 below.
            if pending_link.get("state") == "awaiting_new_user_name":
                from app.services.onboarding_parsing import clean_name

                name = clean_name(text)
                if not (2 <= len(name) <= 80) or "@" in name or name.startswith("/"):
                    await send_text(
                        phone,
                        "That doesn't look like a name — please reply with your full name.",
                    )
                    return
                roles = await fetch_all(
                    "SELECT id, name FROM roles WHERE org_id = ("
                    "SELECT id FROM orgs WHERE is_active = true LIMIT 1) ORDER BY name",
                    source_key=NEW_USER_ORG_SOURCE_KEY,
                )
                if not roles:
                    await send_text(
                        phone,
                        "❌ Registration isn't available right now. Please contact your admin.",
                    )
                    await delete_session(link_session_id)
                    return
                role_list = "\n".join(
                    f"{i + 1}. {r['name'].title()}" for i, r in enumerate(roles)
                )
                await set_session(
                    link_session_id,
                    {
                        **pending_link,
                        "state": "awaiting_new_user_role",
                        "name": name,
                        "role_options": [
                            {"id": str(r["id"]), "name": r["name"]} for r in roles
                        ],
                    },
                    ttl=300,
                )
                await send_text(
                    phone,
                    f"Thanks, {name}! Which role are you?\n\n{role_list}\n\nReply with the number.",
                )
                return

            if pending_link.get("state") == "awaiting_new_user_role":
                from app.services.onboarding_parsing import resolve_role_by_text

                options = pending_link.get("role_options", [])
                picked = resolve_role_by_text(text, options)
                if not picked:
                    # No clean digit/name/substring match — role names are
                    # dynamic per org, so a free-text answer ("I own my flat
                    # here") goes to the LLM mapper rather than a fixed
                    # keyword dict that would need reauthoring per org.
                    from app.services.onboarding_llm import llm_match_role

                    picked = await llm_match_role(text, options)
                if not picked:
                    role_list = "\n".join(
                        f"{i + 1}. {o['name'].title()}" for i, o in enumerate(options)
                    )
                    await send_text(
                        phone,
                        f"Didn't recognise that — please reply with the number:\n\n{role_list}",
                    )
                    return
                await set_session(
                    link_session_id,
                    {
                        **pending_link,
                        "state": "awaiting_new_user_confirm",
                        "role_id": picked["id"],
                        "role_name": picked["name"],
                    },
                    ttl=300,
                )
                await send_text(
                    phone,
                    f"📝 Confirm your details:\n"
                    f"  • Name: {pending_link.get('name')}\n"
                    f"  • Email: {pending_link.get('new_user_email')}\n"
                    f"  • Role: {picked['name'].title()}\n\n"
                    f"Reply *yes* to create your account, *no* to cancel, or tell me what "
                    f'to change (e.g. "change role to tenant").',
                )
                return

            if pending_link.get("state") == "awaiting_new_user_confirm":
                from app.services.onboarding_llm import (
                    llm_match_role,
                    llm_parse_confirm_intent,
                )
                from app.services.onboarding_parsing import (
                    clean_name,
                    parse_edit_command,
                    resolve_role_by_text,
                )
                from app.services.vocabulary import get_vocabulary, matches_vocab

                stripped = text.strip()
                role_options = pending_link.get("role_options", [])
                role_name = pending_link.get("role_name", "")

                # Vocabulary is per-org, but this user doesn't exist yet —
                # look it up via the org this registration is happening
                # under (same "single active org per source_key" query the
                # account-creation INSERT below already relies on).
                confirm_org_row = await fetch_one(
                    "SELECT id FROM orgs WHERE is_active = true LIMIT 1",
                    source_key=NEW_USER_ORG_SOURCE_KEY,
                )
                vocab = (
                    await get_vocabulary(
                        str(confirm_org_row["id"]), NEW_USER_ORG_SOURCE_KEY
                    )
                    if confirm_org_row
                    else {"confirm_words": frozenset(), "cancel_words": frozenset()}
                )

                def _confirm_card(prefix: str) -> str:
                    # Reads pending_link fresh (not the `role_name` local
                    # above) so it reflects whichever field was just edited.
                    current_role = pending_link.get("role_name", "")
                    return (
                        f"{prefix}\n"
                        f"  • Name: {pending_link.get('name')}\n"
                        f"  • Email: {pending_link.get('new_user_email')}\n"
                        f"  • Role: {current_role.title() if current_role else '—'}\n\n"
                        f"Reply *yes* to create your account, *no* to cancel, or tell me "
                        f'what to change (e.g. "change role to tenant").'
                    )

                confirmed = (
                    matches_vocab(stripped, vocab["confirm_words"])
                    or stripped.lower() == "yes"
                )
                cancelled = matches_vocab(
                    stripped, vocab["cancel_words"]
                ) or stripped.lower() in ("no", "cancel")

                if cancelled:
                    await delete_session(link_session_id)
                    await send_text(phone, "❌ Registration cancelled.")
                    return

                if not confirmed:
                    # Fast, deterministic path first: explicit "change X to
                    # Y" phrasing needs no LLM call. Anything freer-form
                    # ("no wait its actually X", "make it tenant instead")
                    # falls back to the LLM intent parser — which itself
                    # only ever proposes a field+value; nothing here trusts
                    # it blindly, every edit still goes through the same
                    # validation/lookup a first-time answer would get.
                    edit = parse_edit_command(stripped)
                    if edit:
                        action, field, value = "edit", edit[0], edit[1]
                    else:
                        parsed = await llm_parse_confirm_intent(
                            stripped,
                            pending_link.get("name", ""),
                            pending_link.get("new_user_email", ""),
                            role_name,
                        )
                        action, field, value = (
                            parsed["action"],
                            parsed.get("field"),
                            parsed.get("value"),
                        )

                    if action == "confirm":
                        confirmed = True
                    elif action == "cancel":
                        await delete_session(link_session_id)
                        await send_text(phone, "❌ Registration cancelled.")
                        return
                    elif action == "edit" and field == "name":
                        pending_link = {**pending_link, "name": clean_name(value)}
                        await set_session(link_session_id, pending_link, ttl=300)
                        await send_text(
                            phone, _confirm_card("📝 Updated. Confirm your details:")
                        )
                        return
                    elif action == "edit" and field == "role":
                        picked = resolve_role_by_text(
                            value, role_options
                        ) or await llm_match_role(value, role_options)
                        if not picked:
                            role_list = "\n".join(
                                f"{i + 1}. {o['name'].title()}"
                                for i, o in enumerate(role_options)
                            )
                            await send_text(
                                phone,
                                f"Didn't catch which role you meant — please reply with the number:\n\n{role_list}",
                            )
                            return
                        pending_link = {
                            **pending_link,
                            "role_id": picked["id"],
                            "role_name": picked["name"],
                        }
                        await set_session(link_session_id, pending_link, ttl=300)
                        await send_text(
                            phone, _confirm_card("📝 Updated. Confirm your details:")
                        )
                        return
                    elif action == "edit" and field == "email":
                        new_candidate_email = extract_email(value) or value.strip()
                        await _handle_email_submission(
                            phone, new_candidate_email, link_session_id
                        )
                        return
                    else:
                        await send_text(
                            phone,
                            "I didn't quite catch that — reply *yes* to confirm, *no* to cancel, "
                            'or tell me what to change (e.g. "change role to tenant").',
                        )
                        return

                new_email = pending_link.get("new_user_email")
                new_row = await fetch_one(
                    """
                    INSERT INTO users (org_id, role_id, name, email, channel, is_active)
                    VALUES ((SELECT id FROM orgs WHERE is_active = true LIMIT 1), $1, $2, $3, 'telegram', true)
                    RETURNING id, (SELECT id FROM orgs WHERE is_active = true LIMIT 1) AS org_id
                """,
                    pending_link["role_id"],
                    pending_link["name"],
                    new_email,
                    source_key=NEW_USER_ORG_SOURCE_KEY,
                )
                if not new_row:
                    await send_text(
                        phone,
                        "❌ Something went wrong creating your account. Please try again.",
                    )
                    await delete_session(link_session_id)
                    return
                org_row = await fetch_one(
                    "SELECT name FROM orgs WHERE id = $1",
                    new_row["org_id"],
                    source_key=NEW_USER_ORG_SOURCE_KEY,
                )
                result = await generate_and_send_otp(
                    user_id=str(new_row["id"]),
                    user_email=new_email,
                    user_name=pending_link["name"],
                    org_name=org_row["name"] if org_row else "",
                    org_id=str(new_row["org_id"]),
                    action_context={"type": "telegram_link"},
                    source_key=NEW_USER_ORG_SOURCE_KEY,
                )
                if result["sent"]:
                    # Same state the existing linking flow (Step 2 below) already
                    # verifies — reusing it as-is rather than duplicating OTP
                    # verification + bind_telegram_phone logic.
                    await set_session(
                        link_session_id,
                        {
                            "state": "awaiting_link_otp",
                            "user_id": str(new_row["id"]),
                            "source_key": NEW_USER_ORG_SOURCE_KEY,
                        },
                        ttl=180,
                    )
                    await send_text(
                        phone,
                        f"✅ Account created! A verification code has been sent to *{new_email}*.\n"
                        f"Reply with the code to activate your account.\n\n"
                        f"_Code expires in {result['expiry_minutes']} minutes._",
                    )
                else:
                    await send_text(
                        phone,
                        "❌ Could not send verification email. Please contact your admin.",
                    )
                    await delete_session(link_session_id)
                return

            # Step 2: user is replying with the OTP code
            if pending_link.get("state") == "awaiting_link_otp":
                # Deliberately NOT org-vocabulary-driven like the other "retry"
                # checks below — this fires before the phone is linked to any
                # org (resolve_identity above returned None), so there is no
                # org_id yet to look up a vocabulary override for. This is
                # platform-level linking protocol text, not business content.
                # Tolerant prefix match ("retry please") for the same reason
                # vocabulary.matches_vocab is — people don't type bare
                # keywords into chat.
                if text.strip().lower().startswith("retry"):
                    await delete_session(link_session_id)
                    await send_text(
                        phone,
                        "🔄 Cancelled. Please send your email again to restart linking.",
                    )
                    return

                # Extract the code rather than hashing the raw reply — "the
                # code is 4821" or "OTP: 4821" must not burn one of the 3
                # real attempts just because it wasn't typed as bare digits.
                candidates = extract_otp_candidates(text)
                if not candidates:
                    await send_text(
                        phone,
                        "That doesn't look like a code — please check your email and reply with just the digits.",
                    )
                    return
                if len(candidates) > 1:
                    await send_text(
                        phone,
                        "I found more than one number in that message — please reply with just the code from your email.",
                    )
                    return

                result = await verify_otp(
                    pending_link["user_id"], candidates[0], pending_link["source_key"]
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
                        # The OTP just verified IS the identity check — mark the
                        # session authenticated now, otherwise the user's very
                        # next message immediately triggers an unexplained
                        # second (security_auth) OTP challenge right after
                        # onboarding.
                        link_org_row = await fetch_one(
                            "SELECT session_ttl_minutes FROM orgs WHERE id = $1",
                            linked_user["org_id"],
                            source_key=pending_link["source_key"],
                        )
                        link_ttl_minutes = (
                            link_org_row["session_ttl_minutes"] if link_org_row else 480
                        )
                        await set_auth_token(
                            linked_user["org_id"],
                            linked_user["phone"],
                            link_ttl_minutes,
                        )
                        await send_text(
                            phone,
                            f"✅ *Linked!* Welcome, {linked_user['user_name']}.\n"
                            f"Your Telegram account is now connected to OrchestrAI.\n"
                            f"Send /help to see available commands.",
                        )
                    else:
                        await send_text(
                            phone,
                            "❌ Something went wrong linking your account. Please try again.",
                        )
                else:
                    await send_text(phone, f"❌ {result['reason']}")
                return

            # Step 1: user just sent an email — extracted from anywhere in
            # the message ("my email is X", "it's X@y.com") rather than
            # requiring the whole reply to be exactly the address.
            email = extract_email(text)
            if email:
                await _handle_email_submission(phone, email, link_session_id)
                return

            await send_text(
                phone,
                "👋 Welcome to OrchestrAI!\n\n"
                "Your Telegram account isn't linked yet.\n"
                "Reply with your *email address* — if you already have an account, "
                "we'll link it; if not, we'll help you register as a new member.\n\n"
                "_Example: john@example.com_",
            )
            return
        await send_text(
            phone,
            "👋 Your number isn't registered with OrchestrAI.\n"
            "Contact your admin to get access.",
        )
        return

    if not user["is_active"] or not user["org_active"]:
        await send_text(phone, "❌ Your account is inactive. Contact admin.")
        return

    if phone.startswith("tg:"):
        from app.services.menu import sync_telegram_commands

        await sync_telegram_commands(user, phone[3:])

    # ── Slash commands & menu ────────────────────────────────────────────
    from app.services.menu import build_menu_sections, resolve_slash_command
    from app.services.messaging import send_list

    text_stripped = text.strip()

    if text_stripped.startswith("/"):
        if text_stripped.lower() == "/cancel":
            await cancel_user_draft(user, phone, confirm=False)
            return
        if text_stripped.lower() == "/start":
            # /start is Telegram's own "user just opened this bot" signal —
            # sent automatically on first open or tapping Start, not
            # something typed expecting a specific command. It was falling
            # through to the generic "Didn't recognise that command"
            # fallback below, which reads as broken for a completely
            # normal first message. Kept SHORT and generic on purpose —
            # this is also the message a returning user sees replayed
            # right after "✅ Identity verified! Session active..." when
            # their session expired and they just re-verified, so a full
            # "Welcome to X, I'm your assistant" paragraph here would be
            # redundant with what they just saw seconds earlier.
            sections = await build_menu_sections(user["org_id"], user)
            await send_list(phone, "📋 Here's what I can help with:", "Menu", sections)
            return
        if text_stripped.lower() in ("/help", "/h"):
            from app.services.agent import _build_help_response

            await send_text(phone, await _build_help_response(user))
            return
        if text_stripped.lower() in ("/status", "/mystatus", "/s"):
            from app.services.draft_store import get_active_draft

            draft = await get_active_draft(
                user["org_id"], user["user_id"], user["source_key"]
            )
            if draft:
                intent = draft["intent_key"]
                stage = draft["stage"]
                fields = draft.get("fields", {})
                await send_text(
                    phone,
                    f"📋 *Draft Status*\n"
                    f"Workflow: {intent}\n"
                    f"Stage: {stage}\n"
                    f"Fields collected: {len(fields)}\n\n"
                    f"Tap /cancel to clear this draft.",
                )
            else:
                await send_text(
                    phone, "✅ No active draft. You're ready to start fresh."
                )
            return
        wf = await resolve_slash_command(user["org_id"], user, text_stripped)
        if wf:
            # Pass intent_key directly to agent for execution
            text = wf["intent_key"]
        else:
            sections = await build_menu_sections(user["org_id"], user)
            await send_list(
                phone,
                "Didn't recognise that command — here's what's available:",
                "📋 Menu",
                sections,
            )
            return

    # 2. Fetch org TTL
    org_row = await fetch_one(
        "SELECT session_ttl_minutes FROM orgs WHERE id = $1",
        user["org_id"],
        source_key=user["source_key"],
    )
    ttl_minutes = org_row["session_ttl_minutes"] if org_row else 480

    from app.services.vocabulary import get_vocabulary, matches_vocab

    vocab = await get_vocabulary(user["org_id"], user["source_key"])

    # 3. Security auth check
    sec_session_id = f"sec:{user['org_id']}:{phone}"
    is_authenticated = await check_auth_token(user["org_id"], phone)

    if not is_authenticated:
        pre_session = await get_session(sec_session_id)

        if pre_session.get("state") == "awaiting_security_otp":
            # Handle explicit retry — generate a fresh OTP instead of re-checking the stale one
            if matches_vocab(text, vocab["retry_words"]):
                pending_text = pre_session.get("pending_text", "")
                result = await generate_and_send_otp(
                    user_id=user["user_id"],
                    user_email=user["email"],
                    user_name=user["user_name"],
                    org_name=user["org_name"],
                    org_id=user["org_id"],
                    action_context={"type": "security_auth"},
                    source_key=user["source_key"],
                )
                if result["sent"]:
                    await set_session(
                        sec_session_id,
                        {
                            "state": "awaiting_security_otp",
                            "pending_text": pending_text,
                        },
                        ttl=180,
                    )
                    await send_text(
                        phone,
                        f"🔐 A new verification code has been sent to *{user['email']}*.\n"
                        f"Reply with the code to continue.",
                    )
                elif result["reason"] == "cooldown":
                    await send_text(
                        phone,
                        f"⏳ Please wait {result['wait_seconds']}s before requesting another code.",
                    )
                else:
                    await send_text(
                        phone, "❌ Could not send verification email. Contact admin."
                    )
                return

            # User is replying with security OTP — extract the digits
            # rather than hashing the raw reply, same reasoning as the
            # linking-OTP step above: "the code is 4821" shouldn't burn a
            # real attempt on a formatting mismatch.
            candidates = extract_otp_candidates(text)
            if not candidates:
                await send_text(
                    phone,
                    "That doesn't look like a code — please check your email and reply with just the digits.",
                )
                return
            if len(candidates) > 1:
                await send_text(
                    phone,
                    "I found more than one number in that message — please reply with just the code from your email.",
                )
                return

            result = await verify_otp(
                user["user_id"], candidates[0], user["source_key"]
            )
            if result["valid"]:
                await set_auth_token(user["org_id"], phone, ttl_minutes)
                pending_text = pre_session.get("pending_text", "")
                await delete_session(sec_session_id)
                hours = ttl_minutes // 60
                mins = ttl_minutes % 60
                ttl_str = f"{hours}h {mins}m" if mins else f"{hours}h"
                if ttl_minutes < 60:
                    ttl_str = f"{ttl_minutes} mins"
                await send_text(
                    phone,
                    f"✅ Identity verified!\n"
                    f"_Session active for {ttl_str}. Processing your request..._",
                )
                if pending_text:
                    await handle_message(
                        phone=phone, text=pending_text, msg_type="text"
                    )
            else:
                await send_text(phone, f"❌ {result['reason']}")
            return

        # Session expired — send security OTP
        result = await generate_and_send_otp(
            user_id=user["user_id"],
            user_email=user["email"],
            user_name=user["user_name"],
            org_name=user["org_name"],
            org_id=user["org_id"],
            action_context={"type": "security_auth"},
            source_key=user["source_key"],
        )
        if result["sent"]:
            await set_session(
                sec_session_id,
                {"state": "awaiting_security_otp", "pending_text": text},
                ttl=180,
            )
            hours = ttl_minutes // 60
            mins = ttl_minutes % 60
            ttl_str = f"{hours} hours" if not mins else f"{hours}h {mins}m"
            if ttl_minutes < 60:
                ttl_str = f"{ttl_minutes} minutes"
            await send_text(
                phone,
                f"🔐 *Security Verification Required*\n\n"
                f"Your session has expired.\n"
                f"A verification code has been sent to *{user['email']}*.\n"
                f"Reply with the code to continue.\n\n"
                f"_Required every {ttl_str} for security._",
            )
        elif result["reason"] == "cooldown":
            await send_text(
                phone,
                f"⏳ Please wait {result['wait_seconds']}s before requesting another code.",
            )
        else:
            await send_text(
                phone, "❌ Could not send verification email. Contact admin."
            )
        return

    # 4. Normal session
    session_id = f"{user['org_id']}:{phone}"
    session = await get_session(session_id)

    # Cancel gate — works at EVERY stage, not just awaiting_confirmation
    # This is the user's escape hatch and must never depend on LLM cooperation
    _t = text.strip().lower().rstrip("!.?")
    _tokens = set(re.findall(r"[a-z/]+", _t))

    if _t in vocab["cancel_tokens"] or (
        _tokens & {"cancel", "/cancel"} and len(_tokens) <= 3
    ):
        had_draft = bool(session.get("pending_action"))
        if not had_draft:
            from app.services.draft_store import get_active_draft

            had_draft = bool(
                await get_active_draft(
                    user["org_id"], user["user_id"], user["source_key"]
                )
            )
        await _clear_stuck_draft(
            user, session, session_id, ttl_minutes * 60, reason="cancelled"
        )
        # Wipe conversation history too — a cancelled draft's turns are the
        # main source of the LLM re-proposing the thing you just cancelled.
        session["conversation_history"] = []
        await set_session(session_id, session, ttl=ttl_minutes * 60)
        await send_text(
            phone,
            "🔄 Cleared. What would you like to do?\n\n_Type *menu* to see your options._"
            if had_draft
            else "✅ Nothing in progress. Type *menu* to see your options.",
        )
        return

    # Sanitize conversation history immediately after loading - remove tool messages
    # to prevent OpenAI API errors from corrupted history
    conversation_history = session.get("conversation_history", [])
    has_corrupted = False
    sanitized_history = []
    i = 0
    while i < len(conversation_history):
        m = conversation_history[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            want = {tc["id"] for tc in m["tool_calls"]}
            block, j = [], i + 1
            while (
                j < len(conversation_history)
                and conversation_history[j].get("role") == "tool"
            ):
                block.append(conversation_history[j])
                j += 1
            got = {t.get("tool_call_id") for t in block}
            if want and want <= got:
                sanitized_history.append(m)
                sanitized_history.extend(block)  # complete pair — keep
            else:
                has_corrupted = True  # orphan — drop both
            i = j
            continue
        if m.get("role") == "tool":
            has_corrupted = True
            i += 1
            continue  # orphan tool msg
        if m.get("role") in ("user", "assistant") and m.get("content"):
            sanitized_history.append(m)
        i += 1

    if has_corrupted:
        logger.warning(f"Corrupted history detected, sanitizing session {session_id}")
        session["conversation_history"] = sanitized_history
        conversation_history = sanitized_history
        await set_session(session_id, session, ttl=ttl_minutes * 60)

    # Rehydrate draft from DB if Redis has no pending_action but DB has active draft
    if not session.get("pending_action"):
        from app.services.draft_store import get_active_draft

        db_draft = await get_active_draft(
            user["org_id"], user["user_id"], user["source_key"]
        )
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
                "rehydrated": True,
                # D12: without this, _is_draft_stale() is a permanent no-op
                "created_at": (
                    db_draft.get("created_at") or db_draft.get("updated_at")
                ),
                "reprompt_count": 0,
            }
            await set_session(session_id, session, ttl=ttl_minutes * 60)
            # Send greeting to user about the unfinished draft
            await send_text(
                phone,
                f"You have an unfinished *{db_draft['intent_key']}* — continue, or tap /cancel.",
            )

    # 5. Approval button responses
    if msg_type == "interactive" and (
        text.startswith(("action:approve:", "action:reject:"))
    ):
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
        details = (
            "\n".join(f"  • {k}: {v}" for k, v in fields.items()) or "  (nothing yet)"
        )
        if pending_action.get("stage") == "awaiting_confirmation":
            await send_text(
                phone,
                f"You already have a *{pending_action['intent_key']}* draft waiting for confirmation:\n"
                f"{details}\n\nReply *yes* to confirm, *no* to cancel, or tell me what to change.",
            )
        else:
            await send_text(
                phone,
                f"You're already filling out *{pending_action['intent_key']}*. So far:\n"
                f"{details}\n\nPlease continue with the remaining details, or /cancel to start over.",
            )
        return

    async def _send_action_pdf(exec_result: dict):
        if not exec_result.get("pdf_bytes"):
            return
        import re

        from app.services.messaging import send_document

        doc_id = (
            exec_result.get("invoice_number")
            or exec_result.get("quotation_number")
            or "document"
        )
        safe_filename = re.sub(r"[^\w\-]", "_", str(doc_id))[:50] + ".pdf"
        await send_document(
            to=phone,
            pdf_bytes=exec_result["pdf_bytes"],
            filename=safe_filename,
            caption=f"📄 {doc_id}",
        )

    # 8. Pending action confirmation
    if pending_action and pending_action.get("stage") == "awaiting_confirmation":
        if matches_vocab(text, vocab["confirm_words"]):
            try:
                result = await execute_pending_action(pending_action, user, phone=phone)
            except Exception as e:
                logger.error(f"execute_pending_action error: {e}", exc_info=True)
                await send_text(
                    phone,
                    "❌ Something went wrong creating the document. Please try again.",
                )
                return

            if result.get("success"):
                session.pop("pending_action", None)
                session["conversation_history"] = (
                    session.get("conversation_history") or []
                ) + [
                    {"role": "user", "content": text},
                    {
                        "role": "assistant",
                        "content": result.get(
                            "message", "Action completed successfully"
                        ),
                    },
                ]
                session["conversation_history"] = session["conversation_history"][-15:]
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(
                    phone, result.get("message", "Action completed successfully")
                )
                await _send_action_pdf(result)
            elif result.get("stage") == "awaiting_otp":
                pending_action["stage"] = "awaiting_otp"
                pending_action["resume_step"] = result.get("resume_step", 0)
                await set_session(
                    session_id,
                    {**session, "pending_action": pending_action},
                    ttl=session_ttl,
                )
                await send_text(phone, result.get("message"))
            elif result.get("stage") == "awaiting_approval":
                pending_action["stage"] = "awaiting_approval"
                pending_action["resume_step"] = result.get("resume_step", 0)
                await set_session(
                    session_id,
                    {**session, "pending_action": pending_action},
                    ttl=session_ttl,
                )
                await send_text(phone, result.get("message"))
            else:
                session.pop("pending_action", None)
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(phone, result.get("message", "Action failed"))
            return

        if matches_vocab(text, vocab["cancel_words"]):
            await _clear_stuck_draft(
                user, session, session_id, session_ttl, reason="cancelled"
            )
            await send_text(phone, "❌ Action cancelled.")
            return

        # Unrecognised reply while awaiting confirm — check staleness first, then treat as correction
        if pending_action:
            from app.services.agent import _MAX_REPROMPT_COUNT, _is_draft_stale

            if _is_draft_stale(pending_action):
                # Confirmation window (10 min) has expired — drop the draft entirely
                # and let the message fall through as a brand-new request.
                logger.info("Stale awaiting_confirmation draft detected — clearing")
                await _clear_stuck_draft(
                    user, session, session_id, session_ttl, reason="cancelled"
                )
                pending_action = None
                await send_text(
                    phone,
                    "_⏱️ Your previous confirmation timed out and was cleared. "
                    "Let me help with your new request._",
                )
                # fall through to agent with pending_action=None
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
                    logger.warning(
                        f"Reprompt cap ({_MAX_REPROMPT_COUNT}) reached — clearing draft"
                    )
                    await _clear_stuck_draft(
                        user, session, session_id, session_ttl, reason="cancelled"
                    )
                    await send_text(
                        phone,
                        "🤔 I'm having trouble understanding the details for this request. "
                        "Let's start fresh — please send your request again with all the details "
                        "in one message.",
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
        if matches_vocab(text, vocab["retry_words"]):
            session.pop("pending_action", None)
            session.pop("state", None)
            await set_session(session_id, session, ttl=session_ttl)
            await send_text(
                phone, "🔄 Session cleared. Please resend your original request."
            )
            return

        otp_result = await verify_otp(user["user_id"], text.strip(), user["source_key"])

        if otp_result["valid"]:
            try:
                exec_result = await execute_pending_action(
                    pending_action, user, phone=phone, otp_verified=True
                )
            except Exception as e:
                logger.error(
                    f"execute_pending_action after OTP error: {e}", exc_info=True
                )
                await send_text(
                    phone,
                    "❌ Something went wrong after verification. Please try again.",
                )
                return

            if exec_result.get("success"):
                session.pop("pending_action", None)
                session["conversation_history"] = (
                    session.get("conversation_history") or []
                ) + [
                    {"role": "user", "content": text},
                    {
                        "role": "assistant",
                        "content": exec_result.get(
                            "message", "Action completed successfully"
                        ),
                    },
                ]
                session["conversation_history"] = session["conversation_history"][-15:]
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(
                    phone, exec_result.get("message", "Action completed successfully")
                )
                await _send_action_pdf(exec_result)
            elif exec_result.get("stage") == "awaiting_approval":
                pending_action["stage"] = "awaiting_approval"
                pending_action["resume_step"] = exec_result.get("resume_step", 0)
                await set_session(
                    session_id,
                    {**session, "pending_action": pending_action},
                    ttl=session_ttl,
                )
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
            logger.warning(
                f"Collecting-stage reprompt cap ({_MAX_REPROMPT_COUNT}) reached — clearing draft"
            )
            await _clear_stuck_draft(
                user, session, session_id, session_ttl, reason="cancelled"
            )
            await send_text(
                phone,
                "🤔 I'm having trouble understanding the details for this request. "
                "Let's start fresh — please send your request again with all the details "
                "in one message.",
            )
            return
        # Increment reprompt_count each turn we stay in collecting mode
        pending_action["reprompt_count"] = reprompt_count + 1
        session["pending_action"] = pending_action
        await set_session(session_id, session, ttl=session_ttl)

    try:
        reply, updated_history, session_patch = await run_agent(
            text,
            user,
            phone,
            conversation_history=conversation_history,
            pending_action=pending_action,
        )

        # Capture the menu flag BEFORE popping it
        sent_menu = bool(session_patch.get("_send_menu"))

        # Check if agent wants to send interactive menu
        if sent_menu:
            from app.services.messaging import send_list

            await send_list(
                phone,
                reply,
                session_patch["button_label"],
                session_patch["menu_sections"],
            )
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

            # Ensure agent reply is in history (it's present for normal text replies,
            # but clarify-path skips it — add it here unconditionally if not already last)
            # History length is capped by run_agent itself per the org's
            # context_message_limit — no separate cap needed here.
            if not updated_history or updated_history[-1].get("content") != reply:
                updated_history = updated_history + [
                    {"role": "assistant", "content": reply}
                ]

            session["last_message"] = text
        session["conversation_history"] = updated_history
        await set_session(session_id, session, ttl=session_ttl)

        # Only send text reply if not sending menu. reply can be genuinely
        # empty now (e.g. a successful generate_pdf/generate_excel, where
        # the document itself — already sent inside the tool call — is the
        # whole confirmation) — sending an empty text message would just
        # fail against the Telegram/WhatsApp API for nothing.
        if not sent_menu:
            if reply and reply.strip():
                await send_text(phone, reply)

            # Log to audit_log — response_text/session_id let the admin panel
            # show the actual reply and group turns into one conversation.
            # `session_id` (the Redis key) is a FIXED string per user, never
            # rotating — persisting it as-is would make the admin "View
            # conversation" modal grow unboundedly across a user's entire
            # lifetime of usage instead of showing one bounded conversation.
            # Bucketing by calendar day (computed in Postgres, already on
            # IST per db.py's _set_timezone, so no separate tz handling
            # here) keeps it to "this user's activity on this day".
            await execute(
                """
                INSERT INTO audit_log (org_id, user_id, intent_key, input_text, response_text, session_id, outcome)
                VALUES ($1, $2, 'agent', $3, $4, $5 || ':' || to_char(now(), 'YYYY-MM-DD'), 'success')
            """,
                user["org_id"],
                user["user_id"],
                text,
                reply,
                session_id,
                source_key=user["source_key"],
            )
        else:
            # Log to audit_log for menu responses too
            await execute(
                """
                INSERT INTO audit_log (org_id, user_id, intent_key, input_text, response_text, session_id, outcome)
                VALUES ($1, $2, 'menu', $3, $4, $5 || ':' || to_char(now(), 'YYYY-MM-DD'), 'success')
            """,
                user["org_id"],
                user["user_id"],
                text,
                reply,
                session_id,
                source_key=user["source_key"],
            )

    except Exception as e:
        # If this came from a Telegram send that's already flood-controlled
        # (429), sending a fallback "something went wrong" message would
        # just hit the same lock again — log and stop instead of cascading
        # into more failed sends.
        from app.services.telegram import TelegramRateLimitedError

        if isinstance(e, TelegramRateLimitedError):
            logger.warning(
                f"handle_message: Telegram rate-limited, dropping reply to {phone} (retry_after={e.retry_after}s)"
            )
            return

        logger.error(f"handle_message error: {e}", exc_info=True)
        correlation_id = ""
        try:
            from app.logging_config import correlation_id as get_correlation_id

            correlation_id = get_correlation_id.get()
        except Exception as corr_err:
            logger.debug(f"Could not read correlation_id for error message: {corr_err}")
        try:
            await send_text(
                phone,
                f"❌ Something went wrong. Error ID: {correlation_id}. Please try again or contact support.",
            )
        except TelegramRateLimitedError:
            logger.warning(
                f"handle_message: Telegram rate-limited while sending error fallback to {phone}"
            )

        # This is the whole reason the Recent Activity filter has an "error"
        # option — before this, a failed turn left NO trace in audit_log at
        # all (only in Railway's raw logs), so the filter had nothing to
        # ever match. Best-effort and isolated in its own try: we're already
        # in the failure path, a second failure here (e.g. DB down) must not
        # stop the user-facing error reply above from having already gone out.
        try:
            await execute(
                """
                INSERT INTO audit_log (org_id, user_id, intent_key, input_text, response_text, session_id, outcome)
                VALUES ($1, $2, 'agent', $3, $4, $5 || ':' || to_char(now(), 'YYYY-MM-DD'), 'error')
            """,
                user["org_id"],
                user["user_id"],
                text,
                f"[{correlation_id}] {e}"[:2000],
                session_id,
                source_key=user["source_key"],
            )
        except Exception as log_err:
            logger.error(f"handle_message: failed to log error to audit_log: {log_err}")


# ── SYSTEM ROW HANDLERS ─────────────────────────────────
async def handle_system_row(text: str, user: dict, phone: str):
    """Handle sys:status, sys:cancel, sys:help from menu."""
    import datetime as _dt

    from app.services.draft_store import get_active_draft

    if text == "sys:status":
        draft = await get_active_draft(
            user["org_id"], user["user_id"], user["source_key"]
        )
        if draft:
            intent = draft["intent_key"]
            fields = draft.get("fields", {})
            field_lines = (
                "\n".join(f"  • {k}: {v}" for k, v in fields.items())
                or "  (nothing yet)"
            )
            age_min = int(
                (
                    _dt.datetime.now(_dt.timezone.utc)
                    - draft.get("created_at", _dt.datetime.now(_dt.timezone.utc))
                ).total_seconds()
                // 60
            )
            await send_text(
                phone,
                f"📝 In progress: *{intent}* (started {age_min} min ago)\n"
                f"{field_lines}\n\n"
                f"Reply *cancel* to discard it, or continue where you left off.",
            )
        else:
            await send_text(phone, "✅ No active draft. You're ready to start fresh.")

    elif text == "sys:cancel":
        await cancel_user_draft(user, phone, confirm=True)

    elif text == "sys:help":
        from app.services.agent import _build_help_response

        await send_text(phone, await _build_help_response(user))


async def cancel_user_draft(user: dict, phone: str, confirm: bool = True):
    """Cancel the user's active draft. This always cancels immediately —
    `confirm` only controls whether the message mentions how much is being
    discarded. (Previously this claimed to wait for a 'yes' reply but
    cancelled unconditionally regardless of the reply — fixed to be honest
    about what it actually does.)"""
    from app.services.draft_store import close_draft, get_active_draft

    draft = await get_active_draft(user["org_id"], user["user_id"], user["source_key"])
    if not draft:
        await send_text(phone, "✅ No active draft to cancel.")
        return

    field_count = len(draft.get("fields", {}))
    await close_draft(
        user["org_id"], user["user_id"], "cancelled", source_key=user["source_key"]
    )

    if confirm and field_count >= 2:
        await send_text(
            phone,
            f"🔄 Draft for *{draft['intent_key']}* cancelled ({field_count} field(s) discarded).",
        )
    else:
        await send_text(phone, "🔄 Draft cancelled.")


# ── OTP REPLY HANDLER (invoice high value) ────────────
async def _handle_otp_reply(phone, text, user, session, session_id):
    from app.services.vocabulary import get_vocabulary, matches_vocab

    vocab = await get_vocabulary(user["org_id"], user["source_key"])
    if matches_vocab(text, vocab["retry_words"]):
        await set_session(session_id, {})
        await send_text(
            phone, "🔄 Session cleared. Please resend your original request."
        )
        return

    result = await verify_otp(user["user_id"], text.strip(), user["source_key"])

    if result["valid"]:
        # Refresh auth token on successful OTP
        org_row = await fetch_one(
            "SELECT session_ttl_minutes FROM orgs WHERE id = $1",
            user["org_id"],
            source_key=user["source_key"],
        )
        ttl = org_row["session_ttl_minutes"] if org_row else 480
        await set_auth_token(user["org_id"], phone, ttl)
        await set_session(
            session_id, {**session, "state": "otp_verified", "otp_verified": True}
        )
        reply = await resume_after_otp(user, session_id, session)
        await send_text(phone, reply)
    else:
        await send_text(phone, f"❌ {result['reason']}")
