import asyncio
import contextvars
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager

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
from app.services import config_store, photos, reach
from app.services.action_executor import execute_pending_action
from app.services.agent import run_agent
from app.services.identity import resolve_identity
from app.services.messages import length_text, say
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


def _log_failed_deliveries(body: dict) -> None:
    """WhatsApp accepts a message and tells us LATER, in a separate "statuses" report, whether it could
    be delivered. After 24 hours without a message from the person it never is (Meta error 131047), and
    until now we threw the report away, so a failed delivery looked like "completed successfully".
    A failed report is now written to the log as an ERROR with Meta's error code, the message id and
    only the last 4 digits of the recipient. Nothing else changes. Never raises."""
    try:
        for entry in body.get("entry") or []:
            for change in entry.get("changes") or []:
                for status in (change.get("value") or {}).get("statuses") or []:
                    if status.get("status") != "failed":
                        continue
                    error = (status.get("errors") or [{}])[0]
                    logger.error(
                        "WhatsApp could not deliver a message: "
                        f"code={error.get('code')} title={error.get('title')!r} "
                        f"message_id={status.get('id')} to=...{str(status.get('recipient_id') or '')[-4:]}"
                    )
    except (
        Exception
    ) as e:  # a strange report must never stop the webhook from answering
        logger.warning(f"could not read a WhatsApp delivery report: {e}")


# ── INBOUND MESSAGES (POST) ───────────────────────────
@router.post("/webhook/whatsapp")
async def receive_message(request: Request):
    # Verify signature first - fail-closed
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=403)

    body = json.loads(raw)
    _log_failed_deliveries(body)
    await reach.handle_failed_reports(
        body
    )  # a send WhatsApp refused: keep it and email it

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

        # The person wrote to the bot, of whatever kind: WhatsApp's 24-hour door is open again.
        await reach.record_inbound(phone)

        # ── Extract text ──
        attachments = None
        unreadable = False
        if msg_type == "text":
            text = msg["text"]["body"]
        elif msg_type == "image":
            # a photo: WhatsApp hands over a reference; it is saved (see photos.py) once we know whose it is
            image = msg.get("image") or {}
            text = image.get("caption") or ""
            if not image.get("id"):
                return {"status": "ok"}
            attachments = [f"{photos.WHATSAPP}{image['id']}"]
        elif msg_type == "button":
            # a tap on the button of a template message ("Proceed"): the person has answered, so the door is open
            text = (msg.get("button") or {}).get("text") or ""
        elif msg_type in _UNREADABLE_KINDS:
            text = ""
            unreadable = True
        elif msg_type == "interactive":
            inter = msg["interactive"]
            if inter.get("type") == "list_reply":
                text = inter["list_reply"]["id"]
            elif inter.get("type") == "nfm_reply":
                # the answer of a WhatsApp Flow (the in-panel menu): the workflow chosen there is taken like a
                # tap on a menu row
                text = _flow_choice(inter)
                if not text:
                    logger.info(
                        "A WhatsApp Flow answer without a workflow was left alone"
                    )
                    return {"status": "ok"}
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
        if unreadable:
            # a voice note, video, document, location or contact: say so instead of staying silent
            logger.info(f"Message from {phone}: ({msg_type})")
            try:
                await send_text(
                    phone,
                    await say(await _channel_source_key(phone), "photo.unsupported"),
                )
            except Exception as e:
                logger.warning(f"could not answer an unreadable message: {e}")
            return {"status": "ok"}
        logger.info(
            f"Message from {phone}: {text}" + (" (+photo)" if attachments else "")
        )
        try:
            await handle_message(
                phone=phone, text=text, msg_type=msg_type, attachments=attachments
            )
        except Exception as e:
            logger.error(f"handle_message error: {e}", exc_info=True)
            try:
                await send_text(phone, await say(None, "error.generic"))
            except Exception as fallback_err:
                logger.warning(
                    f"Fallback error message to {phone} also failed: {fallback_err}"
                )

    except (KeyError, IndexError) as e:
        logger.warning(f"Parse error: {e}")

    return {"status": "ok"}


async def _channel_source_key(phone: str) -> str | None:
    """The client that owns the messaging channel this chat came in on, for the texts someone
    sees before they are linked to an account. None when it cannot be told (no such client, or
    more than one): the built-in wording is used then. Never raises."""
    from app.db import get_source_key_for_channel

    try:
        return await get_source_key_for_channel(
            "telegram" if phone.startswith("tg:") else "whatsapp"
        )
    except Exception as e:
        logger.debug(f"no client found for the channel of {phone}: {e}")
        return None


_WHATSAPP_WORDING = {
    "onboarding.welcome": "onboarding.welcome_whatsapp",
    "onboarding.code_sent": "onboarding.code_sent_whatsapp",
    "onboarding.linked": "onboarding.linked_whatsapp",
}


def _flow_choice(inter: dict) -> str:
    """The workflow a person chose in a WhatsApp Flow: the "workflow" in the answer's response_json, only when
    it looks like a workflow's key (letters, digits, underscore). Anything else is "" and is left alone."""
    try:
        data = json.loads((inter.get("nfm_reply") or {}).get("response_json") or "{}")
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    logger.info(f"WhatsApp Flow answer with: {sorted(data)}")
    photos = data.get("photos")
    if photos:  # only the shape of what came back, never its content
        first = photos[0] if isinstance(photos, list) and photos else photos
        shape = sorted(first) if isinstance(first, dict) else type(first).__name__
        count = len(photos) if isinstance(photos, list) else 1
        logger.info(f"WhatsApp Flow answer photos: {count} of shape {shape}")
    choice = str(data.get("workflow") or "").strip()
    return choice if re.fullmatch(r"[A-Za-z0-9_]{1,80}", choice) else ""


# kinds of WhatsApp message the chat bot cannot read (a reaction or a system note is not one of them)
_UNREADABLE_KINDS = ("audio", "video", "document", "location", "contacts", "sticker")


def _onboarding_key(key: str, phone: str) -> str:
    """The text for this kind of chat: the Telegram wording, or the WhatsApp one for a WhatsApp number."""
    return key if phone.startswith("tg:") else _WHATSAPP_WORDING[key]


async def _whatsapp_linking_on(phone: str) -> bool:
    """Whether a WhatsApp number that is not in the system may link itself with an email and a code: on,
    unless the client that owns WhatsApp switched it off (orgs.settings -> onboarding.whatsapp_link = false)."""
    source_key = await _channel_source_key(phone)
    if not source_key:
        return True
    try:
        row = await fetch_one(
            "SELECT settings FROM orgs WHERE is_active = true LIMIT 1",
            source_key=source_key,
        )
        settings = row["settings"] if row else None
        if isinstance(settings, str):
            settings = json.loads(settings)
        return (
            config_store.setting(settings, "onboarding.whatsapp_link", True)
            is not False
        )
    except Exception as e:
        logger.debug(f"could not read the whatsapp_link switch: {e}")
        return True


async def _self_registration_roles(source_key: str) -> list[str]:
    """The role names (lower case) a stranger may take when she registers herself in the chat:
    orgs.settings -> self_registration.roles, the organisation's own list. When it names none,
    nobody can register themselves: a new person is added by an admin and then links this chat
    with the email the admin entered."""
    row = await fetch_one(
        "SELECT settings FROM orgs WHERE is_active = true LIMIT 1",
        source_key=source_key,
    )
    settings = row["settings"] if row else None
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except ValueError:
            settings = {}
    roles = ((settings or {}).get("self_registration") or {}).get("roles")
    if not isinstance(roles, list):
        return []
    return [r.strip().lower() for r in roles if isinstance(r, str) and r.strip()]


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
    from app.services.identity import chat_channel, find_unlinked_user_by_email

    candidate = await find_unlinked_user_by_email(
        email,
        channel=chat_channel(phone),
        prefer_source_key=await _channel_source_key(phone),
    )
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
                await say(
                    candidate["source_key"],
                    _onboarding_key("onboarding.code_sent", phone),
                    email=candidate["email"],
                    expiry_minutes=result["expiry_minutes"],
                ),
            )
        elif result["reason"] == "cooldown":
            await send_text(
                phone,
                await say(
                    candidate["source_key"],
                    "otp.cooldown",
                    wait_seconds=result["wait_seconds"],
                ),
            )
        else:
            await send_text(
                phone, await say(candidate["source_key"], "otp.email_failed")
            )
    else:
        source_key = await _channel_source_key(phone)
        if not source_key or not await _self_registration_roles(source_key):
            # no client owns this kind of chat, or it does not let people register themselves in the chat
            await delete_session(link_session_id)
            await send_text(phone, await say(source_key, "onboarding.closed"))
            return
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
            await say(await _channel_source_key(phone), "onboarding.no_account"),
        )


# ── CORE MESSAGE HANDLER ──────────────────────────────


async def _audit_turn(
    user: dict,
    session_id: str,
    intent_key: str,
    text: str,
    reply: str,
    outcome: str = "success",
) -> None:
    """One line in the activity log for a turn the engine answered itself (yes, cancel), so the
    chat in the dashboard ends with what was done, not with "Reply yes to save". Never raises."""
    try:
        await execute(
            """
            INSERT INTO audit_log (org_id, user_id, intent_key, input_text, response_text, session_id, outcome)
            VALUES ($1, $2, $3, $4, $5, $6 || ':' || to_char(now(), 'YYYY-MM-DD'), $7)
            """,
            user["org_id"],
            user["user_id"],
            intent_key,
            text,
            reply,
            session_id,
            outcome,
            source_key=user["source_key"],
        )
    except (
        Exception
    ) as e:  # the answer already went out; a missing log line must not break it
        logger.warning(f"activity log not written: {e}")


async def _photo_draft(user: dict) -> dict | None:
    """The request being filled in, if its workflow takes photos."""
    from app.services.draft_store import get_active_draft

    draft = await get_active_draft(user["org_id"], user["user_id"], user["source_key"])
    if not draft:
        return None
    row = await fetch_one(
        "SELECT to_jsonb(w) -> 'settings' ->> 'photos' AS photos FROM workflows w "
        "WHERE org_id = $1 AND intent_key = $2",
        user["org_id"],
        draft["intent_key"],
        source_key=user["source_key"],
    )
    return draft if row and row["photos"] == "true" else None


async def _add_photos(user: dict, phone: str, draft: dict, file_ids: list[str]) -> int:
    """Put photos on the draft (and on the chat's copy of it). Returns how many are attached."""
    from app.services.draft_store import upsert_draft

    fields = draft.get("fields") or {}
    if isinstance(fields, str):
        fields = json.loads(fields)
    have = list(fields.get("_photos") or [])
    for file_id in file_ids:
        if file_id not in have:
            have.append(file_id)
    conf = await config_store.org_settings(user["source_key"], user["org_id"])
    have = have[: config_store.limit_of(conf, "photo_max")]
    await upsert_draft(
        org_id=user["org_id"],
        user_id=user["user_id"],
        intent_key=draft["intent_key"],
        fields={"_photos": have},
        stage=draft["stage"],
        source_key=user["source_key"],
        reset_fields=False,
    )
    session_id = f"{user['org_id']}:{phone}"
    session = await get_session(session_id)
    pending = session.get("pending_action")
    if pending and pending.get("intent_key") == draft["intent_key"]:
        pending.setdefault("fields", {})["_photos"] = have
        await set_session(session_id, session, ttl=480 * 60)
    return len(have)


def _held_key(user: dict, phone: str) -> str:
    return f"photos_held:{user['org_id']}:{phone}"


async def _photo_added_note(user: dict, draft: dict, count: int) -> str:
    """What to tell someone after a photo went onto their request."""
    key = (
        "photo.added_confirm"
        if draft["stage"] == "awaiting_confirmation"
        else "photo.added"
    )
    return await say(user["source_key"], key, count=count)


async def _take_photos(
    user: dict, phone: str, file_ids: list[str], quiet: bool = False
) -> None:
    """Attach photos sent in chat to the request being filled in (when its workflow takes photos).
    A photo sent first, before /complaint or /update, is kept for a few minutes and attached as
    soon as such a request is started."""
    file_ids, problem = await photos.keep_whatsapp_photos(user, file_ids)
    if problem:
        conf = await config_store.org_settings(user["source_key"], user["org_id"])
        await send_text(
            phone,
            await say(
                user["source_key"],
                problem,
                limit_mb=config_store.limit_of(conf, "photo_max_mb"),
            ),
        )
    if not file_ids:
        return
    draft = await _photo_draft(user)
    if not draft:
        held = await get_session(_held_key(user, phone))
        ids = list(held.get("ids") or [])
        for file_id in file_ids:
            if file_id not in ids:
                ids.append(file_id)
        conf = await config_store.org_settings(user["source_key"], user["org_id"])
        hold = config_store.limit_of(conf, "photo_hold_minutes")
        await set_session(
            _held_key(user, phone),
            {"ids": ids[: config_store.limit_of(conf, "photo_max")]},
            ttl=hold * 60,
        )
        if (
            not quiet
        ):  # with a caption the text is handled next, then the photo is attached
            await send_text(
                phone, await say(user["source_key"], "photo.held", minutes=hold)
            )
        return
    count = await _add_photos(user, phone, draft, file_ids)
    await send_text(phone, await _photo_added_note(user, draft, count))


async def _attach_held_photos(user: dict, phone: str, hint: bool = False) -> None:
    """After a turn: if a photo is waiting and a request that takes photos is now open, attach
    it. That covers photo first then text, a photo with a caption, and a photo then /command.
    With hint, say so when nothing could take it. Never raises."""
    try:
        held = await get_session(_held_key(user, phone))
        ids = held.get("ids") or []
        if not ids:
            return
        draft = await _photo_draft(user)
        if not draft:
            if hint:
                conf = await config_store.org_settings(
                    user["source_key"], user["org_id"]
                )
                await send_text(
                    phone,
                    await say(
                        user["source_key"],
                        "photo.held",
                        minutes=config_store.limit_of(conf, "photo_hold_minutes"),
                    ),
                )
            return
        count = await _add_photos(user, phone, draft, ids)
        await delete_session(_held_key(user, phone))
        await send_text(phone, await _photo_added_note(user, draft, count))
    except Exception as e:
        logger.warning(f"held photo not attached: {e}")


_turn_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "turn_user", default=None
)
# the phone whose turn this very task already holds (a message that waited for a code is handled again
# from inside its own turn: it must not wait for itself)
_turn_held: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "turn_held", default=None
)


async def _set_up_email(user: dict, phone: str, text: str) -> None:
    """A person an admin added with only a name and a number has no email yet. Their number is known, so no
    sign-up: they are asked for their email, a code is sent to it, and when they send the code back the email is
    saved on their account (it is where the code that renews their session goes, every few days)."""
    source_key = user["source_key"]
    session_id = f"emailsetup:{user['user_id']}"
    pending = await get_session(session_id)
    first_name = (user.get("user_name") or "").split(" ")[0]

    if pending.get("state") == "awaiting_code":
        if text.strip().lower().startswith("retry"):
            await delete_session(session_id)
            pending = {}
        else:
            candidates = extract_otp_candidates(text)
            if not candidates:
                await send_text(phone, await say(source_key, "otp.not_a_code"))
                return
            if len(candidates) > 1:
                await send_text(phone, await say(source_key, "otp.many_numbers"))
                return
            result = await verify_otp(user["user_id"], candidates[0], source_key)
            if not result["valid"]:
                await send_text(
                    phone,
                    await say(source_key, "otp.rejected", reason=result["reason"]),
                )
                return
            await fetch_one(
                "UPDATE users SET email = $1 WHERE id = $2 AND COALESCE(email, '') = '' RETURNING id",
                pending["email"],
                user["user_id"],
                source_key=source_key,
            )
            await delete_session(session_id)
            org_row = await fetch_one(
                "SELECT session_ttl_minutes FROM orgs WHERE id = $1",
                user["org_id"],
                source_key=source_key,
            )
            await set_auth_token(
                user["org_id"],
                phone,
                org_row["session_ttl_minutes"] if org_row else 480,
            )
            await send_text(
                phone, await say(source_key, "onboarding.email_done", name=first_name)
            )
            return

    email = extract_email(text)
    if not email:
        await send_text(
            phone, await say(source_key, "onboarding.email_ask", name=first_name)
        )
        return
    taken = await fetch_one(
        "SELECT 1 AS used FROM users WHERE org_id = $1 AND lower(email) = lower($2) AND id <> $3",
        user["org_id"],
        email,
        user["user_id"],
        source_key=source_key,
    )
    if taken:
        await send_text(phone, await say(source_key, "onboarding.email_taken"))
        return
    result = await generate_and_send_otp(
        user_id=user["user_id"],
        user_email=email,
        user_name=user["user_name"],
        org_name=user["org_name"],
        org_id=user["org_id"],
        action_context={"type": "email_setup", "description": "confirm your email"},
        source_key=source_key,
    )
    if result["sent"]:
        await set_session(
            session_id, {"state": "awaiting_code", "email": email}, ttl=900
        )
        await send_text(
            phone,
            await say(
                source_key,
                "onboarding.email_code_sent",
                email=email,
                expiry_minutes=result["expiry_minutes"],
            ),
        )
    elif result["reason"] == "cooldown":
        await send_text(
            phone,
            await say(source_key, "otp.cooldown", wait_seconds=result["wait_seconds"]),
        )
    else:
        await send_text(phone, await say(source_key, "otp.email_failed"))


async def _take_the_turn(
    redis, key: str, token: str, lock_seconds: int, wait_seconds: int
) -> str:
    """ "got" once this person's turn is ours, "busy" when the wait ran out, "skipped" when Redis
    cannot be used (then nobody is made to wait: being answered matters more than the order)."""
    try:
        deadline = time.monotonic() + wait_seconds
        pause = min(0.25, max(0.02, wait_seconds / 50))
        while True:
            if await redis.set(key, token, nx=True, px=lock_seconds * 1000):
                return "got"
            if time.monotonic() >= deadline:
                return "busy"
            await asyncio.sleep(pause)
    except Exception as e:
        logger.warning(f"could not take the turn (going on without): {e}")
        return "skipped"


@asynccontextmanager
async def _one_turn_at_a_time(phone: str, conf: dict | None):
    """Yields True when this message may be handled now, False when the person's previous message
    is still being answered and the wait ran out.

    Two messages from one person used to be handled at once: two "yes" both read the draft and both
    ran it, and two quick messages each read the chat's copy, waited for the model, and wrote it
    back, so the second erased the first. Now a person's messages go through one at a time, in the
    order they arrived. The lock lives in Redis (shared by every copy of the app) and runs out by
    itself, so a crash cannot block someone for ever. How long a message waits, and how long a
    turn may hold the lock, are the organisation's settings (turn_wait_seconds, turn_lock_seconds)."""
    if _turn_held.get() == phone:
        yield True  # already inside this person's turn
        return
    redis = get_redis()
    if redis is None:
        yield True
        return
    key = f"turn_lock:{phone}"
    token = uuid.uuid4().hex
    state = await _take_the_turn(
        redis,
        key,
        token,
        config_store.limit_of(conf, "turn_lock_seconds"),
        config_store.limit_of(conf, "turn_wait_seconds"),
    )
    if state == "busy":
        yield False
        return
    mark = _turn_held.set(phone)
    try:
        yield True
    finally:
        _turn_held.reset(mark)
        if state == "got":
            try:
                if (
                    await redis.get(key) == token
                ):  # only our own lock, never a newer one
                    await redis.delete(key)
            except Exception as e:
                logger.warning(
                    f"could not give the turn back (it runs out by itself): {e}"
                )


async def _claim_confirmation(user: dict, pending: dict) -> tuple[bool, str | None]:
    """The first "yes" to a card claims it; a second one for the same card (a retry, a double tap)
    finds it claimed and must not run it again. (claimed, key to give back if saving fails.)
    Fails open when Redis cannot be used."""
    redis = get_redis()
    if redis is None:
        return True, None
    stamp = (
        pending.get("created_at")
        or hashlib.sha1(
            json.dumps(
                pending.get("fields") or {}, sort_keys=True, default=str
            ).encode()
        ).hexdigest()
    )
    key = f"confirm_claim:{user['user_id']}:{pending.get('intent_key')}:{stamp}"
    try:
        conf = await config_store.org_settings(user["source_key"], user["org_id"])
        seconds = config_store.limit_of(conf, "confirm_stale_minutes") * 60
        if await redis.set(key, "1", nx=True, ex=seconds):
            return True, key
        return False, None
    except Exception as e:
        logger.warning(f"could not claim the confirmation (going on without): {e}")
        return True, None


async def _turn_numbers(phone: str) -> tuple[dict | None, dict | None]:
    """(the person, their organisation's settings) for the numbers that govern the turn. Never
    raises: an unknown person, or a database that cannot be reached, gets the built-in numbers."""
    try:
        user = await resolve_identity(phone)
        if not user:
            return None, None
        return user, await config_store.org_settings(user["source_key"], user["org_id"])
    except Exception as e:
        logger.debug(f"no settings for the turn of {phone}: {e}")
        return None, None


async def _tell_busy(phone: str, user: dict | None) -> None:
    try:
        source_key = user["source_key"] if user else await _channel_source_key(phone)
        await send_text(phone, await say(source_key, "draft.busy"))
    except Exception as e:
        logger.warning(f"could not tell {phone} to wait: {e}")


async def _send_kept_messages(phone: str) -> None:
    """The person just wrote, so WhatsApp's door is open: send what was kept for them."""
    user = _turn_user.get()
    if user is None or phone.startswith("tg:"):
        return
    try:
        await reach.deliver_waiting(phone, user["source_key"], user["org_id"])
    except Exception as e:
        logger.warning(f"could not send the kept messages to {phone}: {e}")


async def handle_message(
    phone: str,
    text: str,
    msg_type: str = "text",
    attachments: list[str] | None = None,
):
    """One incoming message. A person's messages are handled one at a time (see
    _one_turn_at_a_time). Photos and text can come in any order, so once the turn is done any photo
    that is waiting is attached to the request the turn just opened."""
    _turn_user.set(None)
    user, conf = (
        (None, None) if _turn_held.get() == phone else await _turn_numbers(phone)
    )
    try:
        async with _one_turn_at_a_time(phone, conf) as has_turn:
            if not has_turn:
                await _tell_busy(phone, user)
                return
            await _handle_message(phone, text, msg_type, attachments)
            await _send_kept_messages(phone)
    finally:
        user = _turn_user.get()
        if user is not None and not (attachments and not text.strip()):
            await _attach_held_photos(user, phone, hint=bool(attachments))


async def _handle_message(
    phone: str,
    text: str,
    msg_type: str = "text",
    attachments: list[str] | None = None,
):
    # 1. Identity
    user = await resolve_identity(phone)
    if not user:
        # Telegram linking flow — unregistered tg: user links via email + OTP,
        # or self-registers a brand-new account if no existing one matches.
        if phone.startswith("tg:") or await _whatsapp_linking_on(phone):
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
                NEW_USER_ORG_SOURCE_KEY = await get_source_key_for_channel(
                    "telegram" if phone.startswith("tg:") else "whatsapp"
                )
            except RuntimeError as e:
                # Linking an account an admin already added does not need this; only signing up as a brand-new
                # person does, so only that part of the conversation stops.
                NEW_USER_ORG_SOURCE_KEY = None
                logger.warning(
                    f"Cannot resolve the client for this chat's sign-up: {e}"
                )
                if str(pending_link.get("state") or "").startswith("awaiting_new_user"):
                    await send_text(
                        phone,
                        await say(None, "onboarding.unavailable"),
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
                        await say(NEW_USER_ORG_SOURCE_KEY, "onboarding.not_a_name"),
                    )
                    return
                roles = await fetch_all(
                    "SELECT id, name FROM roles WHERE org_id = ("
                    "SELECT id FROM orgs WHERE is_active = true LIMIT 1) "
                    "AND lower(name) = ANY($1::text[]) ORDER BY name",
                    await _self_registration_roles(NEW_USER_ORG_SOURCE_KEY),
                    source_key=NEW_USER_ORG_SOURCE_KEY,
                )
                if not roles:
                    await send_text(
                        phone,
                        await say(NEW_USER_ORG_SOURCE_KEY, "onboarding.unavailable"),
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
                    await say(
                        NEW_USER_ORG_SOURCE_KEY,
                        "onboarding.pick_role",
                        name=name,
                        role_list=role_list,
                    ),
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
                        await say(
                            NEW_USER_ORG_SOURCE_KEY,
                            "onboarding.pick_role_again",
                            role_list=role_list,
                        ),
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
                    await say(
                        NEW_USER_ORG_SOURCE_KEY,
                        "onboarding.confirm_details",
                        name=pending_link.get("name"),
                        email=pending_link.get("new_user_email"),
                        role=picked["name"].title(),
                    ),
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

                async def _confirm_card(key: str) -> str:
                    # Reads pending_link fresh (not the `role_name` local
                    # above) so it reflects whichever field was just edited.
                    current_role = pending_link.get("role_name", "")
                    return await say(
                        NEW_USER_ORG_SOURCE_KEY,
                        key,
                        name=pending_link.get("name"),
                        email=pending_link.get("new_user_email"),
                        role=current_role.title() if current_role else "—",
                    )

                fillers = vocab.get("filler_words", frozenset())
                confirmed = (
                    matches_vocab(stripped, vocab["confirm_words"], fillers)
                    or stripped.lower() == "yes"
                )
                cancelled = matches_vocab(
                    stripped, vocab["cancel_words"], fillers
                ) or stripped.lower() in ("no", "cancel")

                if cancelled:
                    await delete_session(link_session_id)
                    await send_text(
                        phone,
                        await say(NEW_USER_ORG_SOURCE_KEY, "onboarding.cancelled"),
                    )
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
                        await send_text(
                            phone,
                            await say(NEW_USER_ORG_SOURCE_KEY, "onboarding.cancelled"),
                        )
                        return
                    elif action == "edit" and field == "name":
                        pending_link = {**pending_link, "name": clean_name(value)}
                        await set_session(link_session_id, pending_link, ttl=300)
                        await send_text(
                            phone, await _confirm_card("onboarding.details_updated")
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
                                await say(
                                    NEW_USER_ORG_SOURCE_KEY,
                                    "onboarding.pick_role_again_edit",
                                    role_list=role_list,
                                ),
                            )
                            return
                        pending_link = {
                            **pending_link,
                            "role_id": picked["id"],
                            "role_name": picked["name"],
                        }
                        await set_session(link_session_id, pending_link, ttl=300)
                        await send_text(
                            phone, await _confirm_card("onboarding.details_updated")
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
                            await say(
                                NEW_USER_ORG_SOURCE_KEY, "onboarding.unclear_confirm"
                            ),
                        )
                        return

                still_allowed = await fetch_one(
                    "SELECT 1 AS ok FROM roles WHERE id = $1 AND lower(name) = ANY($2::text[])",
                    pending_link["role_id"],
                    await _self_registration_roles(NEW_USER_ORG_SOURCE_KEY),
                    source_key=NEW_USER_ORG_SOURCE_KEY,
                )
                if not still_allowed:
                    await send_text(
                        phone,
                        await say(NEW_USER_ORG_SOURCE_KEY, "onboarding.unavailable"),
                    )
                    await delete_session(link_session_id)
                    return

                new_email = pending_link.get("new_user_email")
                new_row = await fetch_one(
                    """
                    INSERT INTO users (org_id, role_id, name, email, channel, is_active)
                    VALUES ((SELECT id FROM orgs WHERE is_active = true LIMIT 1), $1, $2, $3, $4, true)
                    RETURNING id, (SELECT id FROM orgs WHERE is_active = true LIMIT 1) AS org_id
                """,
                    pending_link["role_id"],
                    pending_link["name"],
                    new_email,
                    "telegram" if phone.startswith("tg:") else "whatsapp",
                    source_key=NEW_USER_ORG_SOURCE_KEY,
                )
                if not new_row:
                    await send_text(
                        phone,
                        await say(NEW_USER_ORG_SOURCE_KEY, "onboarding.create_failed"),
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
                        await say(
                            NEW_USER_ORG_SOURCE_KEY,
                            "onboarding.account_created",
                            email=new_email,
                            expiry_minutes=result["expiry_minutes"],
                        ),
                    )
                else:
                    await send_text(
                        phone,
                        await say(
                            NEW_USER_ORG_SOURCE_KEY, "onboarding.email_failed_register"
                        ),
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
                # Tolerant prefix match ("retry please"): people don't type bare
                # keywords into chat.
                if text.strip().lower().startswith("retry"):
                    await delete_session(link_session_id)
                    await send_text(
                        phone,
                        await say(
                            pending_link.get("source_key"), "onboarding.link_restart"
                        ),
                    )
                    return

                # Extract the code rather than hashing the raw reply — "the
                # code is 4821" or "OTP: 4821" must not burn one of the 3
                # real attempts just because it wasn't typed as bare digits.
                candidates = extract_otp_candidates(text)
                if not candidates:
                    await send_text(
                        phone,
                        await say(pending_link.get("source_key"), "otp.not_a_code"),
                    )
                    return
                if len(candidates) > 1:
                    await send_text(
                        phone,
                        await say(pending_link.get("source_key"), "otp.many_numbers"),
                    )
                    return

                result = await verify_otp(
                    pending_link["user_id"], candidates[0], pending_link["source_key"]
                )
                if result["valid"]:
                    from app.services.identity import bind_chat_phone

                    linked_user = await bind_chat_phone(
                        user_id=pending_link["user_id"],
                        phone=phone,
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
                            await say(
                                pending_link["source_key"],
                                _onboarding_key("onboarding.linked", phone),
                                name=linked_user["user_name"],
                            ),
                        )
                    else:
                        await send_text(
                            phone,
                            await say(
                                pending_link["source_key"], "onboarding.link_failed"
                            ),
                        )
                else:
                    await send_text(
                        phone,
                        await say(
                            pending_link["source_key"],
                            "otp.rejected",
                            reason=result["reason"],
                        ),
                    )
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
                await say(
                    NEW_USER_ORG_SOURCE_KEY,
                    _onboarding_key("onboarding.welcome", phone),
                ),
            )
            return
        await send_text(
            phone,
            await say(await _channel_source_key(phone), "onboarding.not_registered"),
        )
        return

    if not user["is_active"] or not user["org_active"]:
        await send_text(phone, await say(user["source_key"], "onboarding.inactive"))
        return

    # workflows this person may use because they are on a case, on top of their role's
    from app.services.party_access import add_party_permissions

    user = await add_party_permissions(user)

    _turn_user.set(user)

    # Added by an admin with a name and a number only: finish the set-up by asking for their email first
    if not (user.get("email") or "").strip():
        await _set_up_email(user, phone, text)
        return

    # A message that only opens the door: a tap on the "Got it" button, or the ready message the emailed
    # link prepares. The kept messages are sent after this turn (see handle_message).
    door = (
        None
        if phone.startswith("tg:")
        else await reach.door_message(user["source_key"], text, msg_type)
    )
    if door:
        if door == "ready" and not await reach.has_waiting(phone):
            await send_text(
                phone, await say(user["source_key"], "hold.nothing_waiting")
            )
        return

    if attachments:
        await _take_photos(user, phone, attachments, quiet=bool(text.strip()))
        if not text.strip():
            return

    if phone.startswith("tg:"):
        from app.services.menu import sync_telegram_commands

        await sync_telegram_commands(user, phone[3:])

    # ── Slash commands & menu ────────────────────────────────────────────
    from app.services.menu import (
        build_menu_sections,
        exact_slash_command,
        resolve_slash_command,
    )
    from app.services.messaging import send_buttons, send_list

    text_stripped = text.strip()
    command_args = None  # what was typed after a slash command, e.g. "/assign CS-26-10-1 Rajeswari"

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
            await send_list(
                phone, await say(user["source_key"], "menu.intro"), "Menu", sections
            )
            return
        if text_stripped.lower() in ("/help", "/h"):
            from app.services.agent import _build_help_response

            await send_text(phone, await _build_help_response(user))
            return
        # /status, /mystatus and /s show the draft in progress, unless a workflow owns that exact
        # command (the Check Status workflow's /mystatus)
        if text_stripped.lower() in (
            "/status",
            "/mystatus",
            "/s",
        ) and not await exact_slash_command(user["org_id"], user, text_stripped):
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
                    await say(
                        user["source_key"],
                        "draft.status",
                        intent=intent,
                        stage=stage,
                        count=len(fields),
                    ),
                )
            else:
                await send_text(phone, await say(user["source_key"], "draft.none"))
            return
        wf = await resolve_slash_command(user["org_id"], user, text_stripped)
        if wf:
            # Pass intent_key directly to agent for execution; the words typed after the
            # command go along so the assistant does not have to ask for them again
            text = wf["intent_key"]
            parts = text_stripped.split(None, 1)
            command_args = parts[1].strip() if len(parts) > 1 else None
        else:
            sections = await build_menu_sections(user["org_id"], user)
            await send_list(
                phone,
                await say(user["source_key"], "menu.unknown_command"),
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
                        await say(
                            user["source_key"], "security.new_code", email=user["email"]
                        ),
                    )
                elif result["reason"] == "cooldown":
                    await send_text(
                        phone,
                        await say(
                            user["source_key"],
                            "otp.cooldown",
                            wait_seconds=result["wait_seconds"],
                        ),
                    )
                else:
                    await send_text(
                        phone, await say(user["source_key"], "otp.email_failed")
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
                    await say(user["source_key"], "otp.not_a_code"),
                )
                return
            if len(candidates) > 1:
                await send_text(
                    phone,
                    await say(user["source_key"], "otp.many_numbers"),
                )
                return

            result = await verify_otp(
                user["user_id"], candidates[0], user["source_key"]
            )
            if result["valid"]:
                await set_auth_token(user["org_id"], phone, ttl_minutes)
                pending_text = pre_session.get("pending_text", "")
                await delete_session(sec_session_id)
                ttl_str = length_text(ttl_minutes)
                await send_text(
                    phone,
                    await say(user["source_key"], "security.verified", ttl=ttl_str),
                )
                if pending_text:
                    await handle_message(
                        phone=phone, text=pending_text, msg_type="text"
                    )
            else:
                await send_text(
                    phone,
                    await say(
                        user["source_key"], "otp.rejected", reason=result["reason"]
                    ),
                )
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
            ttl_str = length_text(ttl_minutes)
            await send_text(
                phone,
                await say(
                    user["source_key"],
                    "security.required",
                    email=user["email"],
                    ttl=ttl_str,
                ),
            )
        elif result["reason"] == "cooldown":
            await send_text(
                phone,
                await say(
                    user["source_key"],
                    "otp.cooldown",
                    wait_seconds=result["wait_seconds"],
                ),
            )
        else:
            await send_text(phone, await say(user["source_key"], "otp.email_failed"))
        return

    # 4. Normal session
    session_id = f"{user['org_id']}:{phone}"
    session = await get_session(session_id)

    # Cancel gate — works at EVERY stage, not just awaiting_confirmation
    # This is the user's escape hatch and must never depend on LLM cooperation
    # A real cancel is the WHOLE message: a cancel word or token, with at most polite words around it
    # ("cancel", "please cancel", "forget it"). "cancel invoice INV-1" is a request about an invoice, and
    # "don't cancel" is the opposite of a cancel: both go on to the agent. The words are the
    # organisation's own (orgs.settings.vocabulary).
    fillers = vocab.get("filler_words", frozenset())
    if matches_vocab(text, vocab["cancel_tokens"], fillers):
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
            await say(
                user["source_key"],
                "draft.cleared" if had_draft else "draft.nothing_in_progress",
            ),
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
                await say(
                    user["source_key"],
                    "draft.unfinished",
                    intent=db_draft["intent_key"],
                ),
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
                await say(
                    user["source_key"],
                    "draft.waiting_confirm",
                    intent=pending_action["intent_key"],
                    details=details,
                ),
            )
        else:
            await send_text(
                phone,
                await say(
                    user["source_key"],
                    "draft.filling",
                    intent=pending_action["intent_key"],
                    details=details,
                ),
            )
        return

    async def _send_action_pdf(exec_result: dict):
        if not exec_result.get("pdf_bytes"):
            return

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
        intent = pending_action.get("intent_key") or "agent"
        if matches_vocab(text, vocab["confirm_words"], fillers):
            claimed, claim_key = await _claim_confirmation(user, pending_action)
            if not claimed:
                # the same card was already confirmed (a retry or a double tap): do not run it twice
                logger.warning(
                    f"a second yes for the same request ({intent}) was ignored"
                )
                return
            try:
                result = await execute_pending_action(pending_action, user, phone=phone)
            except Exception as e:
                logger.error(f"execute_pending_action error: {e}", exc_info=True)
                if claim_key:  # nothing was saved: the person may say yes again
                    try:
                        await get_redis().delete(claim_key)
                    except Exception:
                        logger.debug("could not give the claim back")
                oops = await say(user["source_key"], "error.document")
                await send_text(phone, oops)
                await _audit_turn(
                    user, session_id, intent, text, f"{oops} ({e})"[:2000], "error"
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
                        "content": result.get("message")
                        or await say(user["source_key"], "action.completed"),
                    },
                ]
                session["conversation_history"] = session["conversation_history"][-15:]
                await set_session(session_id, session, ttl=session_ttl)
                done = result.get("message") or await say(
                    user["source_key"], "action.completed"
                )
                await send_text(phone, done)
                await _audit_turn(user, session_id, intent, text, done)
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
                await _audit_turn(
                    user, session_id, intent, text, result.get("message") or ""
                )
            elif result.get("stage") == "awaiting_approval":
                pending_action["stage"] = "awaiting_approval"
                pending_action["resume_step"] = result.get("resume_step", 0)
                await set_session(
                    session_id,
                    {**session, "pending_action": pending_action},
                    ttl=session_ttl,
                )
                await send_text(phone, result.get("message"))
                await _audit_turn(
                    user, session_id, intent, text, result.get("message") or ""
                )
            else:
                session.pop("pending_action", None)
                await set_session(session_id, session, ttl=session_ttl)
                failed = result.get("message", "Action failed")
                await send_text(phone, failed)
                await _audit_turn(user, session_id, intent, text, failed, "error")
            return

        if matches_vocab(text, vocab["cancel_words"], fillers):
            await _clear_stuck_draft(
                user, session, session_id, session_ttl, reason="cancelled"
            )
            cancel_note = await say(user["source_key"], "draft.action_cancelled")
            await send_text(phone, cancel_note)
            await _audit_turn(user, session_id, intent, text, cancel_note)
            return

        # Unrecognised reply while awaiting confirm — check staleness first, then treat as correction
        if pending_action:
            from app.services.agent import _is_draft_stale

            org_conf = await config_store.org_settings(
                user["source_key"], user["org_id"]
            )
            reprompt_cap = config_store.limit_of(org_conf, "reprompt_max")
            if _is_draft_stale(pending_action, org_conf):
                # Confirmation window (10 min) has expired — drop the draft entirely
                # and let the message fall through as a brand-new request.
                logger.info("Stale awaiting_confirmation draft detected — clearing")
                await _clear_stuck_draft(
                    user, session, session_id, session_ttl, reason="cancelled"
                )
                pending_action = None
                await send_text(
                    phone,
                    await say(user["source_key"], "draft.confirm_timed_out"),
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
                if current_reprompt_count >= reprompt_cap:
                    # Cap hit — the user and the bot are going in circles. Force a clean restart.
                    logger.warning(
                        f"Reprompt cap ({reprompt_cap}) reached — clearing draft"
                    )
                    await _clear_stuck_draft(
                        user, session, session_id, session_ttl, reason="cancelled"
                    )
                    await send_text(
                        phone,
                        await say(user["source_key"], "draft.reprompt_restart"),
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
                phone, await say(user["source_key"], "draft.session_cleared")
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
                    await say(user["source_key"], "error.after_verification"),
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
                        "content": exec_result.get("message")
                        or await say(user["source_key"], "action.completed"),
                    },
                ]
                session["conversation_history"] = session["conversation_history"][-15:]
                await set_session(session_id, session, ttl=session_ttl)
                await send_text(
                    phone,
                    exec_result.get("message")
                    or await say(user["source_key"], "action.completed"),
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
            await send_text(
                phone,
                await say(
                    user["source_key"], "otp.rejected", reason=otp_result["reason"]
                ),
            )
        return

    # 10. Run the agent — refresh session in case it was updated above
    session = await get_session(session_id)
    conversation_history = session.get("conversation_history", [])
    pending_action = session.get("pending_action")

    # Reprompt cap check for collecting stage (same cap, different entry point than confirm stage)
    if pending_action and pending_action.get("stage") == "collecting":
        org_conf = await config_store.org_settings(user["source_key"], user["org_id"])
        reprompt_cap = config_store.limit_of(org_conf, "reprompt_max")
        reprompt_count = pending_action.get("reprompt_count", 0)
        if reprompt_count >= reprompt_cap:
            logger.warning(
                f"Collecting-stage reprompt cap ({reprompt_cap}) reached — clearing draft"
            )
            await _clear_stuck_draft(
                user, session, session_id, session_ttl, reason="cancelled"
            )
            await send_text(
                phone,
                await say(user["source_key"], "draft.reprompt_restart"),
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
            command_args=command_args,
        )
        # tap-to-answer buttons for the reply (Telegram only); never saved in the session
        buttons = session_patch.pop("_buttons", None)

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
                if buttons and phone.startswith("tg:"):
                    await send_buttons(phone, reply, buttons)
                else:
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
                await say(
                    (_turn_user.get() or {}).get("source_key"),
                    "error.with_id",
                    correlation_id=correlation_id,
                ),
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
                await say(
                    user["source_key"],
                    "draft.in_progress",
                    intent=intent,
                    age_min=age_min,
                    field_lines=field_lines,
                ),
            )
        else:
            await send_text(phone, await say(user["source_key"], "draft.none"))

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
        await send_text(phone, await say(user["source_key"], "draft.none_to_cancel"))
        return

    field_count = len(draft.get("fields", {}))
    await close_draft(
        user["org_id"], user["user_id"], "cancelled", source_key=user["source_key"]
    )

    if confirm and field_count >= 2:
        await send_text(
            phone,
            await say(
                user["source_key"],
                "draft.cancelled_count",
                intent=draft["intent_key"],
                count=field_count,
            ),
        )
    else:
        await send_text(phone, await say(user["source_key"], "draft.cancelled"))


# ── OTP REPLY HANDLER (invoice high value) ────────────
async def _handle_otp_reply(phone, text, user, session, session_id):
    from app.services.vocabulary import get_vocabulary, matches_vocab

    vocab = await get_vocabulary(user["org_id"], user["source_key"])
    if matches_vocab(text, vocab["retry_words"]):
        await set_session(session_id, {})
        await send_text(phone, await say(user["source_key"], "draft.session_cleared"))
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
        await send_text(
            phone,
            await say(user["source_key"], "otp.rejected", reason=result["reason"]),
        )
