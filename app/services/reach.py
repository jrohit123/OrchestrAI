"""Reaching a person on WhatsApp inside WhatsApp's 24-hour rule, without a message template.

The rule: the chat bot may start a WhatsApp message to a person only if that person wrote to the bot
in the last 24 hours. Their message "opens the door"; every new message opens it again for 24 hours.
Outside it WhatsApp accepts the send and then never delivers it (Meta error 131047), which used to look
like "completed successfully". Telegram has no such rule, so nothing here touches a Telegram person.

What this module does about it. Numbers are the organisation's own (the limits hold_days, hold_max and
door_margin_minutes), the on/off switches live in orgs.settings -> reach, and every sentence is a
message on the Messages screen (group "hold").

  record_inbound       every message a person sends the bot is noted, whatever its kind.
  door_open            was there one in the last 24 hours (a little less: door_margin_minutes)? Redis
                       first; the chat log is the second witness when Redis lost its notes.
  deliver_text         door open: send as before, with a "Got it" button so one tap opens the door for
                       another 24 hours. Door closed: the message is NOT sent. It is kept for the person,
                       emailed to them at once (with a one-tap link that opens WhatsApp with a message
                       ready to send), and the person who asked is told the truth.
  deliver_waiting      the moment the person writes anything, what was kept is sent, and the senders
                       are told it arrived.
  handle_failed_reports  if Meta still refuses a send we believed in, the same thing happens.

Nothing is stored in a table: the notes and the kept messages are in Redis. If Redis is wiped, what was
kept is lost, but the email already carried the full message.
"""

import datetime
import html
import json
import re
import time
import urllib.parse
import uuid
from zoneinfo import ZoneInfo

import httpx

from app.db import fetch_one
from app.logging_config import get_context_logger
from app.redis_client import get_redis
from app.services import config_store, mailer, messaging, otp_service, whatsapp
from app.services.messages import say

logger = get_context_logger(__name__)

WINDOW_SECONDS = 24 * 60 * 60  # WhatsApp's rule, not ours
OUTSIDE_THE_WINDOW = (
    131047  # Meta's error: "Re-engagement message" (more than 24 hours have passed)
)
GOT_IT = (
    "reach_got_it"  # the id of the button; people never see it (the title is a message)
)
BUTTON_BODY_MAX = 1000  # WhatsApp allows 1024 characters in a message that has buttons
BUTTON_TITLE_MAX = 20
SENT_KEEP_SECONDS = (
    2 * 60 * 60
)  # how long we remember what we sent, to act on a late "failed" report
DOOR_KEEP_SECONDS = 40 * 24 * 60 * 60


def is_whatsapp(phone) -> bool:
    """Telegram people are "tg:<id>"; everyone else is a WhatsApp number."""
    return bool(phone) and not str(phone).startswith("tg:")


def feature_on(settings: dict | None) -> bool:
    """orgs.settings -> reach.enabled; on unless an organisation switched it off."""
    return config_store.setting(settings, "reach.enabled", True) is not False


def template_of(settings: dict | None) -> tuple[str, str] | None:
    """The approved WhatsApp template this organisation uses to ask a person to open their WhatsApp again:
    orgs.settings -> reach.template = {"name": "...", "language": "en"}. None when none is chosen."""
    chosen = config_store.setting(settings, "reach.template", None)
    if isinstance(chosen, dict) and str(chosen.get("name") or "").strip():
        return str(chosen["name"]).strip(), str(chosen.get("language") or "en").strip()
    return None


def got_it_on(settings: dict | None) -> bool:
    return config_store.setting(settings, "reach.got_it_button", True) is not False


def _last4(phone) -> str:
    return "..." + str(phone or "")[-4:]


# ------------------------------------------------------------------ the door


async def record_inbound(phone: str) -> None:
    """Note that this person just wrote to the bot (any kind of message). Never raises."""
    if not is_whatsapp(phone):
        return
    redis = get_redis()
    if redis is None:
        return
    try:
        await redis.set(f"door:{phone}", str(int(time.time())), ex=DOOR_KEEP_SECONDS)
    except Exception as e:
        logger.warning(f"reach: could not note a message from {_last4(phone)}: {e}")


async def last_inbound(phone: str, source_key: str) -> float | None:
    """When this person last wrote to the bot (seconds since 1970), or None if nothing says."""
    best: float | None = None
    redis = get_redis()
    if redis is not None:
        try:
            raw = await redis.get(f"door:{phone}")
            if raw:
                best = float(raw)
        except Exception as e:
            logger.warning(f"reach: could not read the note for {_last4(phone)}: {e}")
    try:  # the chat log is the second witness: it survives a Redis restart
        row = await fetch_one(
            "SELECT max(a.created_at) AS at FROM audit_log a "
            "JOIN users u ON u.id = a.user_id WHERE u.phone = $1",
            phone,
            source_key=source_key,
        )
        if row and row["at"] is not None:
            best = max(best or 0.0, row["at"].timestamp())
    except Exception as e:
        logger.debug(f"reach: the chat log could not be asked for {_last4(phone)}: {e}")
    return best


async def door_open(
    phone: str, source_key: str, org_id=None, *, settings: dict | None = None
) -> bool:
    """True when the bot may start a WhatsApp message to this person right now. Always True for a
    Telegram person, and when the organisation switched the feature off (then the bot just tries, as
    it always did). Nothing known about the person means closed: they never wrote to the bot."""
    if not is_whatsapp(phone):
        return True
    if settings is None:
        settings = await config_store.org_settings(source_key, org_id)
    if not feature_on(settings):
        return True
    last = await last_inbound(phone, source_key)
    if last is None:
        return False
    spare = config_store.limit_of(settings, "door_margin_minutes") * 60
    return time.time() - last < WINDOW_SECONDS - spare


# ------------------------------------------------------------------ the number people write to


async def _ask_meta_for_the_number() -> str | None:
    from app.services import whatsapp

    if not whatsapp.WHATSAPP_PHONE_ID:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://graph.facebook.com/v19.0/{whatsapp.WHATSAPP_PHONE_ID}",
                params={"fields": "display_phone_number"},
                headers=whatsapp.HEADERS,
            )
        if resp.status_code != 200:
            logger.warning(
                f"reach: Meta did not give the bot's number ({resp.status_code})"
            )
            return None
        digits = re.sub(r"\D", "", resp.json().get("display_phone_number") or "")
        return digits or None
    except Exception as e:
        logger.warning(f"reach: could not ask Meta for the bot's number: {e}")
        return None


async def bot_number(settings: dict | None) -> str | None:
    """The WhatsApp number people write to, digits only: orgs.settings -> reach.whatsapp_number, else
    what Meta says our number is (remembered a day; a failed look is remembered ten minutes)."""
    chosen = re.sub(
        r"\D", "", str(config_store.setting(settings, "reach.whatsapp_number", ""))
    )
    if chosen:
        return chosen
    redis = get_redis()
    try:
        if redis is not None:
            cached = await redis.get("reach:botnumber")
            if cached is not None:
                return cached or None
    except Exception as e:
        logger.debug(f"reach: the bot's number was not in the note: {e}")
    found = await _ask_meta_for_the_number()
    try:
        if redis is not None:
            await redis.set("reach:botnumber", found or "", ex=86400 if found else 600)
    except Exception as e:
        logger.debug(f"reach: the bot's number could not be noted: {e}")
    return found


async def ready_link(source_key: str, settings: dict | None) -> str | None:
    """A link that opens WhatsApp on the bot's chat with a message ready to send, or None when the
    number is not known (the email then says to send any message instead)."""
    number = await bot_number(settings)
    if not number:
        return None
    ready = await say(source_key, "hold.ready_text")
    return f"https://wa.me/{number}?text={urllib.parse.quote(ready)}"


# ------------------------------------------------------------------ the email


def _first_line(text: str, limit: int = 90) -> str:
    for line in (text or "").splitlines():
        line = re.sub(r"[*_`~]", "", line).strip()
        if line:
            return line[:limit]
    return ""


def _paragraphs_html(parts: list[str], link: str | None) -> str:
    out = []
    for part in parts:
        shown = html.escape(part).replace("\n", "<br>")
        if link:
            safe = html.escape(link)
            shown = shown.replace(
                safe, f'<a href="{html.escape(link, quote=True)}">{safe}</a>'
            )
        out.append(f"<p>{shown}</p>")
    return "".join(out)


async def footer_text(source_key: str, link: str | None) -> str:
    key = "hold.email_footer_link" if link else "hold.email_footer_nolink"
    return await say(source_key, key, link=link or "")


async def footer_html(source_key: str, settings: dict | None) -> str:
    """The closing lines of an email that carries something WhatsApp could not deliver, as HTML (a
    report's email adds this to its own text)."""
    link = await ready_link(source_key, settings)
    return _paragraphs_html([await footer_text(source_key, link)], link)


async def _email_message(
    source_key: str,
    settings: dict | None,
    *,
    person: dict,
    text: str,
    sender_name: str,
    org_name: str,
    automatic: bool = False,
) -> bool:
    """The held message, by email, with the full text in it (so nothing waits on a tap)."""
    link = await ready_link(source_key, settings)
    subject = _first_line(text) or await say(
        source_key, "hold.email_subject", sender_name=sender_name, org_name=org_name
    )
    intro = await say(
        source_key,
        "hold.email_intro_automatic" if automatic else "hold.email_intro",
        sender_name=sender_name,
        org_name=org_name,
    )
    footer = await footer_text(source_key, link)
    return await mailer.send_email(
        person["email"],
        person["name"],
        subject,
        f"{intro}\n\n{text}\n\n{footer}",
        _paragraphs_html([intro, text, footer], link),
    )


async def person_by_phone(phone: str, source_key: str, org_id) -> dict:
    try:
        row = await fetch_one(
            "SELECT id, name, email FROM users WHERE phone = $1 AND org_id = $2 LIMIT 1",
            phone,
            org_id,
            source_key=source_key,
        )
    except Exception as e:
        logger.warning(f"reach: could not look up {_last4(phone)}: {e}")
        row = None
    if not row:
        return {"user_id": None, "name": "", "email": ""}
    return {
        "user_id": str(row["id"]),
        "name": row["name"] or "",
        "email": row["email"] or "",
    }


# ------------------------------------------------------------------ what is kept for a person


def _wait_key(phone: str) -> str:
    return f"waiting:{phone}"


async def _keep(phone: str, item: dict, settings: dict | None) -> None:
    redis = get_redis()
    if redis is None:
        logger.warning(
            f"reach: Redis not available — cannot hold message for {_last4(phone)}"
        )
        return
    try:
        if item.get(
            "replace"
        ):  # a newer copy of the same report replaces the older one
            for old in await _read(phone):
                if old.get("replace") == item["replace"]:
                    await redis.lrem(_wait_key(phone), 0, json.dumps(old))
        await redis.rpush(_wait_key(phone), json.dumps(item))
        await redis.ltrim(
            _wait_key(phone), -config_store.limit_of(settings, "hold_max"), -1
        )
        days = config_store.limit_of(settings, "hold_days")
        await redis.expire(_wait_key(phone), days * 86400)
        length = await redis.llen(_wait_key(phone))
        logger.info(
            f"reach: held 1 message for {_last4(phone)} (now {length} waiting, expires in {days}d)"
        )
    except Exception as e:
        logger.warning(f"reach: could not keep a message for {_last4(phone)}: {e}")


async def _read(phone: str) -> list[dict]:
    redis = get_redis()
    if redis is None:
        return []
    try:
        raw = await redis.lrange(_wait_key(phone), 0, -1)
    except Exception:
        return []
    items = []
    for entry in raw or []:
        try:
            item = json.loads(entry)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("until", 0) > time.time():
            items.append(item)
    return items


async def has_waiting(phone: str) -> bool:
    return bool(await _read(phone))


async def _take(phone: str) -> list[dict]:
    """Everything kept for this person, removed in one step so two answers cannot both send it."""
    redis = get_redis()
    if redis is None:
        return []
    try:
        pipe = redis.pipeline(transaction=True)
        pipe.lrange(_wait_key(phone), 0, -1)
        pipe.delete(_wait_key(phone))
        raw, _ = await pipe.execute()
    except Exception as e:
        logger.warning(
            f"reach: could not take the kept messages of {_last4(phone)}: {e}"
        )
        return []
    items = []
    for entry in raw or []:
        try:
            item = json.loads(entry)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("until", 0) > time.time():
            items.append(item)
    return items


# ------------------------------------------------------------------ sending


def _wamid(answer) -> str | None:
    try:
        return answer["messages"][0]["id"]
    except Exception:
        return None


async def _send_with_got_it(to: str, text: str, source_key: str, settings: dict | None):
    """The text, with a "Got it" button when it fits; one tap on it opens the person's door again."""
    if got_it_on(settings) and len(text) <= BUTTON_BODY_MAX:
        try:
            title = (await say(source_key, "hold.got_it_title"))[:BUTTON_TITLE_MAX]
            return await messaging.send_buttons(
                to, text, [{"id": GOT_IT, "title": title}]
            )
        except Exception as e:
            logger.warning(
                f"reach: the Got it button could not be sent, sending plain text: {e}"
            )
    return await messaging.send_text(to, text)


async def _remember_sent(
    answer, to: str, text: str, *, source_key, org_id, org_name, sender
) -> None:
    """Meta tells us a little later, in a "statuses" report, if the send failed. Remember what it was."""
    wamid = _wamid(answer)
    redis = get_redis()
    if not wamid or redis is None:
        return
    who = {k: (sender or {}).get(k) for k in ("user_name", "phone", "org_name")}
    record = {
        "to": to,
        "text": text,
        "source_key": source_key,
        "org_id": str(org_id),
        "org_name": org_name,
        "sender": who if (who["user_name"] or who["phone"]) else None,
    }
    try:
        await redis.set(f"sent:{wamid}", json.dumps(record), ex=SENT_KEEP_SECONDS)
    except Exception as e:
        logger.debug(f"reach: what was sent could not be noted: {e}")


async def _send_template(to: str, settings: dict | None) -> bool:
    """Ask the person, with the organisation's approved template, to tap its button so their WhatsApp opens
    again (the kept message then arrives). At most once in template_hours per person. Whatever goes wrong, the
    kept message and the email are not affected. Never raises."""
    chosen = template_of(settings)
    redis = get_redis()
    if not chosen or redis is None:
        return False
    key = f"tpl:{to}"
    try:
        hours = config_store.limit_of(settings, "template_hours")
        if not await redis.set(key, "1", ex=hours * 3600, nx=True):
            return False  # one was sent lately
    except Exception as e:
        logger.warning(f"reach: could not note the template for {_last4(to)}: {e}")
        return False
    try:
        await whatsapp.send_template(to, *chosen)
        return True
    except Exception as e:
        logger.warning(
            f"reach: the template could not be sent to {_last4(to)}: {type(e).__name__}"
        )
        try:
            await redis.delete(key)  # nothing went, so the next message may try again
        except Exception as e2:
            logger.debug(f"reach: the template note could not be removed: {e2}")
        return False


async def hold(
    to: str,
    text: str,
    *,
    source_key: str,
    org_id,
    org_name: str = "",
    sender: dict | None = None,
    settings: dict | None = None,
    replace: str | None = None,
    track: dict | None = None,
) -> dict:
    """The door is closed: keep the message, email it, and word what to tell the person who asked. `track` is
    carried with the kept message and handed back when it is finally sent (an announcement notes it)."""
    if settings is None:
        settings = await config_store.org_settings(source_key, org_id)
    person = await person_by_phone(to, source_key, org_id)
    sender = sender or {}
    sender_name = sender.get("user_name") or org_name or ""
    now = time.time()
    await _keep(
        to,
        {
            "id": uuid.uuid4().hex,
            "text": text,
            "at": now,
            "until": now + config_store.limit_of(settings, "hold_days") * 86400,
            "sender_name": sender_name,
            "sender_phone": sender.get("phone"),
            "person_name": person["name"],
            "source_key": source_key,
            "org_id": str(org_id),
            "org_name": org_name,
            "replace": replace,
            "track": track,
        },
        settings,
    )
    emailed = False
    if person["email"]:
        try:
            emailed = await _email_message(
                source_key,
                settings,
                person=person,
                text=text,
                sender_name=sender_name,
                org_name=org_name,
                automatic=not sender,
            )
        except Exception as e:
            logger.warning(f"reach: the email for {_last4(to)} could not be sent: {e}")
    asked = await _send_template(to, settings)
    logger.info(
        f"reach: WhatsApp is closed for {_last4(to)}: the message is kept"
        + (" and was emailed" if emailed else ", no email could be sent")
        + (" and the template was sent" if asked else "")
    )
    note = None
    if sender:
        key = "hold.sender_told_emailed" if emailed else "hold.sender_told_no_email"
        note = await say(source_key, key, person=person["name"] or _last4(to))
    return {"status": "held", "emailed": emailed, "note": note}


async def deliver_text(
    to: str,
    text: str,
    *,
    source_key: str,
    org_id,
    org_name: str = "",
    sender: dict | None = None,
    replace: str | None = None,
    track: dict | None = None,
) -> dict:
    """Send `text` to a person who did not just write to the bot (a flow's "tell this person", a
    scheduled report). {"status": "sent"} or {"status": "held", "note": <what to tell the sender>}."""
    settings = await config_store.org_settings(source_key, org_id)
    if not is_whatsapp(to) or not feature_on(settings):
        return {
            "status": "sent",
            "answer": await messaging.send_text(to, text),
            "note": None,
        }
    if await door_open(to, source_key, org_id, settings=settings):
        answer = await _send_with_got_it(to, text, source_key, settings)
        await _remember_sent(
            answer,
            to,
            text,
            source_key=source_key,
            org_id=org_id,
            org_name=org_name,
            sender=sender,
        )
        return {"status": "sent", "answer": answer, "note": None}
    return await hold(
        to, text, source_key=source_key, org_id=org_id, org_name=org_name,
        sender=sender, settings=settings, replace=replace, track=track,
    )  # fmt: skip


async def deliver_document(
    to: str,
    data: bytes,
    filename: str,
    caption: str,
    *,
    source_key: str,
    org_id,
    org_name: str = "",
    sender: dict | None = None,
    title: str = "",
    mime_type: str = "application/pdf",
) -> dict:
    """A file (a PDF or sheet someone asked to share) for a person who did not just write to the bot.
    Door open: sent on WhatsApp as before. Door closed: emailed to them as an attachment, with the way to
    get the next ones on WhatsApp. `label` is a few words for the tool result; `note` is what the sender is told."""
    settings = await config_store.org_settings(source_key, org_id)
    if (
        not is_whatsapp(to)
        or not feature_on(settings)
        or await door_open(to, source_key, org_id, settings=settings)
    ):
        answer = await messaging.send_document(to, data, filename, caption, mime_type)
        return {"status": "sent", "answer": answer, "label": None, "note": None}
    person = await person_by_phone(to, source_key, org_id)
    who = person["name"] or _last4(to)
    if not person["email"]:
        logger.warning(
            f"reach: a file for {_last4(to)} could not be delivered: closed, no email on file"
        )
        return {
            "status": "lost",
            "label": f"NOT delivered to {who}",
            "note": await say(source_key, "hold.file_no_email", person=who),
        }
    link = await ready_link(source_key, settings)
    sender_name = (sender or {}).get("user_name") or org_name
    intro = await say(
        source_key, "hold.email_intro", sender_name=sender_name, org_name=org_name
    )
    footer = await footer_text(source_key, link)
    sent = await otp_service.send_email_with_pdf(
        to_email=person["email"],
        to_name=person["name"],
        subject=f"{title or filename} — {org_name}".strip(" —"),
        body=_paragraphs_html([intro, title or filename, footer], link),
        pdf_bytes=data,
        filename=filename,
        org_name=org_name,
    )
    if not sent:
        return {
            "status": "lost",
            "label": f"NOT delivered to {who}",
            "note": await say(source_key, "hold.file_email_failed", person=who),
        }
    return {
        "status": "emailed",
        "label": f"Email to {who}",
        "note": await say(source_key, "hold.file_emailed", person=who),
    }


async def _tell_sender(
    sender_phone: str | None, source_key: str, org_id, text: str, settings: dict | None
) -> None:
    """A word to the person who sent something, but only if WhatsApp lets us say it right now."""
    if not sender_phone:
        return
    try:
        if await door_open(sender_phone, source_key, org_id, settings=settings):
            await messaging.send_text(sender_phone, text)
    except Exception as e:
        logger.warning(f"reach: could not tell {_last4(sender_phone)}: {e}")


async def deliver_waiting(phone: str, source_key: str, org_id) -> int:
    """The person just wrote, so the door is open: send what was kept for them. Returns how many."""
    if not is_whatsapp(phone):
        return 0
    settings = await config_store.org_settings(source_key, org_id)
    if not feature_on(settings):
        return 0
    items = await _take(phone)
    logger.info(
        f"reach: deliver_waiting for {_last4(phone)}: found {len(items)} item(s)"
    )
    if not items:
        return 0
    lines = [await say(source_key, "hold.waiting_intro", count=len(items))]
    for item in items:
        who = item.get("sender_name") or ""
        sent_at = datetime.datetime.fromtimestamp(
            item.get("at") or time.time(), ZoneInfo(config_store.DEFAULT_TIMEZONE)
        ).strftime("%d/%m %H:%M")
        lines.append(
            await say(
                source_key,
                "hold.waiting_item",
                sender_name=who,
                sent_at=sent_at,
                held_text=item["text"],
            )
            if who
            else item["text"]
        )
    try:
        answer = await _send_with_got_it(
            phone, "\n\n".join(lines), source_key, settings
        )
    except Exception as e:
        logger.error(f"reach: could not send the kept messages to {_last4(phone)}: {e}")
        for item in items:  # keep them for the next time
            await _keep(phone, item, settings)
        return 0
    if any(item.get("track") for item in items):
        from app.services import announcements

        for item in items:
            await announcements.delivered_later(item.get("track"), answer)
    told: set = set()
    for item in items:
        mark = (item.get("sender_phone"), item.get("person_name"))
        if mark in told or not item.get("sender_phone"):
            continue
        told.add(mark)
        await _tell_sender(
            item["sender_phone"],
            source_key,
            org_id,
            await say(
                source_key,
                "hold.delivered_to_sender",
                person=item.get("person_name") or _last4(phone),
            ),
            settings,
        )
    return len(items)


async def door_message(source_key: str, text: str, msg_type: str) -> str | None:
    """ "got_it" for a tap on the Got it button, "ready" for the message the emailed link prepares (its words are
    a message on the Messages screen) or for a tap on a template's button, else None. Such a message only opens
    the door."""
    if msg_type == "interactive" and text == GOT_IT:
        return "got_it"
    if (
        msg_type == "button"
    ):  # a tap on the button of a template ("Proceed"): the person answered
        return "ready"
    ready = (await say(source_key, "hold.ready_text")).strip().casefold()
    if ready and text.strip().casefold() == ready:
        return "ready"
    return None


async def handle_failed_reports(body: dict) -> None:
    """Meta says a message could not be delivered because the 24 hours were over (131047), although we
    thought the door was open (our notes can be a little out): keep it and email it, as hold does.
    Never raises."""
    try:
        redis = get_redis()
        if redis is None:
            return
        for entry in body.get("entry") or []:
            for change in entry.get("changes") or []:
                for status in (change.get("value") or {}).get("statuses") or []:
                    errors = status.get("errors") or [{}]
                    if (
                        status.get("status") != "failed"
                        or errors[0].get("code") != OUTSIDE_THE_WINDOW
                    ):
                        continue
                    raw = await redis.get(f"sent:{status.get('id')}")
                    if not raw:
                        continue
                    await redis.delete(f"sent:{status.get('id')}")
                    rec = json.loads(raw)
                    settings = await config_store.org_settings(
                        rec["source_key"], rec["org_id"]
                    )
                    outcome = await hold(
                        rec["to"], rec["text"], source_key=rec["source_key"], org_id=rec["org_id"],
                        org_name=rec.get("org_name") or "", sender=rec.get("sender") or None,
                        settings=settings,
                    )  # fmt: skip
                    if outcome.get("note"):
                        await _tell_sender(
                            (rec.get("sender") or {}).get("phone"),
                            rec["source_key"],
                            rec["org_id"],
                            outcome["note"],
                            settings,
                        )
    except Exception as e:
        logger.warning(f"reach: could not act on a delivery report: {e}")
