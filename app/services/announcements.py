"""Announcements: one message to many people at once (housing-0017).

Who gets it is a set of ticks kept as data (`filters`), read against the flat list (residents: relation, primary
member, lives here, wing; housing-0016) and the people's roles, at the moment it is sent:
    {"lives": ["here", "away"], "relations": ["owner", ...], "primary": "any" | "only" | "not",
     "wings": [] (all) or ["A", ...], "roles": [] (any) or [role id, ...], "by_flat": true}
With "by_flat": false the flats are not looked at and only the roles count (for example everyone on the committee).
Only active people, and only active homes, count. A person who matches through two flats gets it once.

How each person is reached is decided by what we know about them, never by a list kept here:
    Telegram   sent at once.
    WhatsApp   through reach.deliver_text: if they wrote to the chat bot in the last 24 hours it is sent at once with
               a Got it button; if not, it is kept, emailed to them when they have an email, the organisation's
               approved template (the "Awaiting your response / Proceed" one) asks them to open WhatsApp, and it is
               delivered the moment they tap or write. Nothing about WhatsApp's 24-hour handling changes here.
    email      people with no number get it by email.
An attached file goes with it on Telegram and on an open WhatsApp; on a closed WhatsApp it is emailed (when they have
an email), and the message says so.

The sending is done by the every-minute job (and started at once for "Send now"). Each person is claimed before
being sent to (FOR UPDATE SKIP LOCKED), so two runs can never send to the same person twice. What happened to each
person is kept in announcement_recipients; WhatsApp's delivery reports and a tap on Got it move it forward."""

import asyncio
import datetime as dt
import html
import json
import re
import time

from app.db import fetch_all, fetch_one, get_all_source_keys, get_pool
from app.logging_config import get_context_logger
from app.redis_client import get_redis
from app.services import config_store, mailer, messaging, otp_service, reach
from app.services.messages import say

logger = get_context_logger(__name__)

LIVES = ("here", "away")
PRIMARY = ("any", "only", "not")
ORDER = ["waiting", "sending", "kept", "sent", "emailed", "delivered", "read", "got_it"]
BATCH = 25  # people claimed at a time
AT_ONCE = 5  # sends in flight at a time
_RUNNING: set = set()  # "Send now" tasks still going
TRACK_SECONDS = (
    7 * 24 * 3600
)  # how long a WhatsApp message id is remembered for its reports
STUCK_MINUTES = (
    10  # a person still "sending" after this was interrupted (the app restarted)
)


# ------------------------------------------------------------------ who gets it


def clean_filters(raw: dict | None) -> dict:
    """The ticks, checked and put one way. Raises ValueError with a sentence for the person."""
    raw = raw if isinstance(raw, dict) else {}
    by_flat = raw.get("by_flat", True) is not False
    lives = [x for x in (raw.get("lives") or []) if x in LIVES]
    relations = [str(x) for x in (raw.get("relations") or []) if str(x).strip()][:20]
    primary = raw.get("primary") if raw.get("primary") in PRIMARY else "any"
    wings = sorted(
        {str(x).strip().upper() for x in (raw.get("wings") or []) if str(x).strip()}
    )[:50]
    roles = [
        str(x)
        for x in (raw.get("roles") or [])
        if re.fullmatch(r"[0-9a-fA-F-]{36}", str(x))
    ][:50]
    if by_flat and not lives:
        raise ValueError("Tick “Lives here”, “Lives elsewhere” or both.")
    if by_flat and not relations:
        raise ValueError("Tick at least one relation to the flat (Owner, Tenant...).")
    if not by_flat and not roles:
        raise ValueError("Pick at least one role.")
    return {
        "by_flat": by_flat,
        "lives": lives,
        "relations": relations,
        "primary": primary,
        "wings": wings,
        "roles": roles,
    }


def channel_of(phone: str | None, email: str | None) -> str:
    if phone and str(phone).startswith("tg:"):
        return "telegram"
    if phone:
        return "whatsapp"
    if email:
        return "email"
    return "none"


async def audience(source_key: str, org_id, filters: dict) -> list[dict]:
    """The people these ticks reach, with the flats through which they match: [{id, name, phone, email, flats}]."""
    f = clean_filters(filters)
    roles = f["roles"]
    if not f["by_flat"]:
        rows = await fetch_all(
            "SELECT u.id, u.name, u.phone, u.email, "
            "(SELECT string_agg(COALESCE(h.wing || '-', '') || h.flat_no, ', ' ORDER BY h.wing, h.flat_no) "
            "   FROM residents h WHERE h.user_id = u.id AND h.status = 'active') AS flats "
            "FROM users u WHERE u.org_id = $1 AND u.is_active AND u.role_id = ANY($2::uuid[]) ORDER BY u.name",
            org_id,
            roles,
            source_key=source_key,
        )
    else:
        rows = await fetch_all(
            "WITH m AS ("
            "  SELECT h.user_id, string_agg(COALESCE(h.wing || '-', '') || h.flat_no, ', ' "
            "         ORDER BY h.wing, h.flat_no) AS flats"
            "    FROM residents h"
            "   WHERE h.org_id = $1 AND h.user_id IS NOT NULL AND h.status = 'active'"
            "     AND ((h.lives_here AND $2) OR (NOT h.lives_here AND $3))"
            "     AND h.relation = ANY($4::text[])"
            "     AND ($5 = 'any' OR ($5 = 'only' AND h.is_primary) OR ($5 = 'not' AND NOT h.is_primary))"
            "     AND (cardinality($6::text[]) = 0 OR COALESCE(h.wing, '') = ANY($6::text[]))"
            "   GROUP BY h.user_id) "
            "SELECT u.id, u.name, u.phone, u.email, m.flats FROM users u JOIN m ON m.user_id = u.id "
            "WHERE u.org_id = $1 AND u.is_active "
            "  AND (cardinality($7::uuid[]) = 0 OR u.role_id = ANY($7::uuid[])) ORDER BY u.name",
            org_id,
            "here" in f["lives"],
            "away" in f["lives"],
            f["relations"],
            f["primary"],
            f["wings"],
            roles,
            source_key=source_key,
        )
    return [dict(r) for r in rows]


async def left_out(source_key: str, org_id, filters: dict, chosen: set) -> list[dict]:
    """Everyone active who does not get it, with the first reason in words."""
    f = clean_filters(filters)
    rows = await fetch_all(
        "SELECT u.id, u.name, u.role_id::text AS role_id, "
        "COALESCE(jsonb_agg(jsonb_build_object('wing', COALESCE(h.wing, ''), 'flat', h.flat_no, "
        "'relation', h.relation, 'primary', h.is_primary, 'lives', h.lives_here)) "
        "FILTER (WHERE h.id IS NOT NULL AND h.status = 'active'), '[]') AS homes "
        "FROM users u LEFT JOIN residents h ON h.user_id = u.id "
        "WHERE u.org_id = $1 AND u.is_active GROUP BY u.id ORDER BY u.name",
        org_id,
        source_key=source_key,
    )
    out = []
    for r in rows:
        if r["id"] in chosen:
            continue
        homes = (
            r["homes"]
            if isinstance(r["homes"], list)
            else json.loads(r["homes"] or "[]")
        )
        flats = ", ".join(
            (h["wing"] + "-" if h["wing"] else "") + h["flat"] for h in homes
        )
        if f["roles"] and r["role_id"] not in f["roles"] or not f["by_flat"]:
            why = "role not picked"
        elif not homes:
            why = "no flat on the list"
        elif f["wings"] and not any(h["wing"] in f["wings"] for h in homes):
            why = "other wing"
        elif not any(("here" if h["lives"] else "away") in f["lives"] for h in homes):
            why = "lives elsewhere" if "here" in f["lives"] else "lives here"
        elif not any(h["relation"] in f["relations"] for h in homes):
            why = "relation not ticked"
        elif f["primary"] == "only":
            why = "not the primary member"
        elif f["primary"] == "not":
            why = "is the primary member"
        else:
            why = "does not match all the ticks together"
        out.append({"id": str(r["id"]), "name": r["name"], "flats": flats, "why": why})
    return out


async def doors(source_key: str, org_id, people: list[dict]) -> dict[str, bool]:
    """For each WhatsApp number: did the person write to the chat bot in the last 24 hours (so a normal message
    arrives)? One Redis read and one query for everyone, the same two witnesses reach.door_open uses."""
    phones = [
        p["phone"]
        for p in people
        if channel_of(p.get("phone"), p.get("email")) == "whatsapp"
    ]
    if not phones:
        return {}
    last: dict[str, float] = {}
    redis = get_redis()
    if redis is not None:
        try:
            for phone, raw in zip(
                phones, await redis.mget([f"door:{p}" for p in phones]), strict=True
            ):
                if raw:
                    last[phone] = float(raw)
        except Exception as e:
            logger.debug(f"announcements: door notes not read: {e}")
    try:
        for r in await fetch_all(
            "SELECT u.phone, max(a.created_at) AS at FROM audit_log a JOIN users u ON u.id = a.user_id "
            "WHERE u.phone = ANY($1::text[]) GROUP BY u.phone",
            phones,
            source_key=source_key,
        ):
            last[r["phone"]] = max(last.get(r["phone"], 0.0), r["at"].timestamp())
    except Exception as e:
        logger.debug(f"announcements: the chat log was not read: {e}")
    settings = await config_store.org_settings(source_key, org_id)
    spare = config_store.limit_of(settings, "door_margin_minutes") * 60
    now = time.time()
    return {
        p: (p in last and now - last[p] < reach.WINDOW_SECONDS - spare) for p in phones
    }


# ------------------------------------------------------------------ the words


async def compose(source_key: str, ann: dict, name: str, org_name: str) -> str:
    """The announcement as one person reads it."""
    parts = []
    if ann.get("greet"):
        first = (name or "").split(" ")[0] or name
        parts.append(await say(source_key, "announce.greeting", first_name=first))
    if (ann.get("title") or "").strip():
        parts.append(f"*{ann['title'].strip()}*")
    parts.append(ann["body"].strip())
    parts.append(await say(source_key, "announce.sign_off", org_name=org_name))
    return "\n\n".join(parts)


def _html(text: str) -> str:
    shown = html.escape(text)
    shown = re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", shown)
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in shown.split("\n\n"))


def _subject_title(ann: dict) -> str:
    title = (ann.get("title") or "").strip()
    if title:
        return title
    first = next((ln.strip() for ln in ann["body"].splitlines() if ln.strip()), "")
    return re.sub(r"[*_~`]", "", first)[:70]


# ------------------------------------------------------------------ sending


async def _set(source_key: str, rid, **cols) -> None:
    sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(cols))
    pool = await get_pool(source_key)
    await pool.execute(
        f"UPDATE announcement_recipients SET {sets}, updated_at = now() WHERE id = $1",
        rid,
        *cols.values(),
    )


async def _remember(wamid: str | None, source_key: str, rid) -> None:
    redis = get_redis()
    if not wamid or redis is None:
        return
    try:
        await redis.set(
            f"ann:{wamid}",
            json.dumps({"s": source_key, "r": str(rid)}),
            ex=TRACK_SECONDS,
        )
    except Exception as e:
        logger.debug(f"announcements: a message id was not noted: {e}")


async def send_one(source_key: str, org: dict, ann: dict, rec: dict) -> None:
    """Reach one person and write down what happened. Never raises."""
    rid = rec["id"]
    try:
        person = await fetch_one(
            "SELECT name, phone, email, is_active FROM users WHERE id = $1",
            rec["user_id"],
            source_key=source_key,
        )
        if not person or not person["is_active"]:
            await _set(source_key, rid, status="failed", note="No longer on the list.")
            return
        phone, email = person["phone"], (person["email"] or "").strip()
        channel = channel_of(phone, email)
        text = await compose(source_key, ann, person["name"], org["name"])
        file = (
            (ann["file_data"], ann["file_name"], ann["file_type"] or "application/pdf")
            if ann.get("file_data")
            else None
        )
        if channel == "none":
            await _set(
                source_key,
                rid,
                channel="none",
                status="failed",
                note="No WhatsApp number and no email.",
            )
            return
        if channel == "email":
            subject = await say(
                source_key,
                "announce.email_subject",
                title=_subject_title(ann),
                org_name=org["name"],
            )
            if file:
                ok = await otp_service.send_email_with_pdf(
                    to_email=email, to_name=person["name"], subject=subject, body=_html(text),
                    pdf_bytes=bytes(file[0]), filename=file[1], org_name=org["name"],
                )  # fmt: skip
            else:
                ok = await mailer.send_email(
                    email, person["name"], subject, text, _html(text)
                )
            await _set(
                source_key, rid, channel="email", status="emailed" if ok else "failed", emailed=bool(ok),
                sent_at=dt.datetime.now(dt.timezone.utc) if ok else None,
                note=None if ok else "The email could not be sent.",
            )  # fmt: skip
            return
        if channel == "telegram":
            answer = await messaging.send_text(phone, text)
            if file:
                await messaging.send_document(
                    phone, bytes(file[0]), file[1], "", file[2]
                )
            await _set(
                source_key,
                rid,
                channel="telegram",
                status="sent",
                sent_at=dt.datetime.now(dt.timezone.utc),
            )
            logger.debug(f"announcements: telegram answer {bool(answer)}")
            return
        # WhatsApp: the 24-hour handling is reach's, unchanged
        settings = await config_store.org_settings(source_key, org["id"])
        is_open = await reach.door_open(phone, source_key, org["id"], settings=settings)
        if file and not is_open:
            emailed_file = bool(email) and await otp_service.send_email_with_pdf(
                to_email=email, to_name=person["name"],
                subject=await say(source_key, "announce.email_subject", title=_subject_title(ann), org_name=org["name"]),
                body=_html(text), pdf_bytes=bytes(file[0]), filename=file[1], org_name=org["name"],
            )  # fmt: skip
            text += "\n\n" + await say(
                source_key,
                "announce.file_emailed" if emailed_file else "announce.file_ask",
                file_name=file[1],
            )
        track = {"s": source_key, "r": str(rid)}
        out = await reach.deliver_text(
            phone,
            text,
            source_key=source_key,
            org_id=org["id"],
            org_name=org["name"],
            track=track,
        )
        now = dt.datetime.now(dt.timezone.utc)
        if out.get("status") == "sent":
            wamid = reach._wamid(out.get("answer"))
            await _remember(wamid, source_key, rid)
            if file and is_open:
                await messaging.send_document(
                    phone, bytes(file[0]), file[1], "", file[2]
                )
            await _set(
                source_key,
                rid,
                channel="whatsapp",
                status="sent",
                sent_at=now,
                wamid=wamid,
            )
        else:
            await _set(
                source_key, rid, channel="whatsapp", status="kept", emailed=bool(out.get("emailed")),
                note="Their WhatsApp was closed: it goes when they tap the button or write"
                + (", and it was emailed." if out.get("emailed") else "."),
            )  # fmt: skip
    except Exception as e:
        logger.warning(
            f"announcements: one person could not be reached ({type(e).__name__}): {e}"
        )
        try:
            await _set(
                source_key,
                rid,
                status="failed",
                note="Could not be sent. Try sending it again later.",
            )
        except Exception as e2:
            logger.error(f"announcements: could not note a failure: {e2}")


async def _start(source_key: str, ann_id) -> bool:
    """A planned announcement whose time has come: work out who gets it now and mark it sending."""
    pool = await get_pool(source_key)
    async with pool.acquire() as conn, conn.transaction():
        ann = await conn.fetchrow(
            "SELECT * FROM announcements WHERE id = $1 AND status = 'planned' AND send_at <= now() "
            "FOR UPDATE SKIP LOCKED",
            ann_id,
        )
        if not ann:
            return False
        people = await audience(
            source_key,
            ann["org_id"],
            json.loads(ann["filters"])
            if isinstance(ann["filters"], str)
            else ann["filters"],
        )
        for p in people:
            await conn.execute(
                "INSERT INTO announcement_recipients (announcement_id, user_id, name, flats, channel) "
                "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (announcement_id, user_id) DO NOTHING",
                ann_id, p["id"], p["name"], p["flats"] or "", channel_of(p["phone"], p["email"]),
            )  # fmt: skip
        await conn.execute(
            "UPDATE announcements SET status = 'sending', started_at = now() WHERE id = $1",
            ann_id,
        )
    logger.info(f"announcements: {ann_id} started for {len(people)} people")
    return True


async def _claim(source_key: str, ann_id) -> list[dict]:
    pool = await get_pool(source_key)
    rows = await pool.fetch(
        "UPDATE announcement_recipients SET status = 'sending', updated_at = now() WHERE id IN ("
        "  SELECT id FROM announcement_recipients WHERE announcement_id = $1 AND status = 'waiting' "
        "  ORDER BY name LIMIT $2 FOR UPDATE SKIP LOCKED) RETURNING id, user_id",
        ann_id,
        BATCH,
    )
    return [dict(r) for r in rows]


async def run_one(source_key: str, ann_id, deadline: float | None = None) -> int:
    """Send an announcement that is due, a batch at a time, until done or the time is up. Returns how many people
    were tried."""
    deadline = deadline or (time.monotonic() + 40)
    await _start(source_key, ann_id)
    ann = await fetch_one(
        "SELECT * FROM announcements WHERE id = $1", ann_id, source_key=source_key
    )
    if not ann or ann["status"] != "sending":
        return 0
    ann = dict(ann)
    org = await fetch_one(
        "SELECT id, name FROM orgs WHERE id = $1", ann["org_id"], source_key=source_key
    )
    org = dict(org)
    tried = 0
    gate = asyncio.Semaphore(AT_ONCE)

    async def one(rec):
        async with gate:
            await send_one(source_key, org, ann, rec)

    while time.monotonic() < deadline:
        batch = await _claim(source_key, ann_id)
        if not batch:
            break
        await asyncio.gather(*(one(r) for r in batch))
        tried += len(batch)
    pool = await get_pool(source_key)
    await pool.execute(
        "UPDATE announcements SET status = 'sent', finished_at = now() WHERE id = $1 AND status = 'sending' "
        "AND NOT EXISTS (SELECT 1 FROM announcement_recipients r WHERE r.announcement_id = $1 "
        "AND r.status IN ('waiting', 'sending'))",
        ann_id,
    )
    return tried


def start_now(source_key: str, ann_id) -> None:
    """For "Send now": begin at once instead of at the next minute. The every-minute job carries on if this stops."""

    async def go():
        try:
            await run_one(source_key, ann_id, time.monotonic() + 600)
        except Exception as e:
            logger.error(f"announcements: sending {ann_id} stopped: {e!r}")

    task = asyncio.get_running_loop().create_task(go())
    _RUNNING.add(task)  # held, so it is not dropped half-way
    task.add_done_callback(_RUNNING.discard)


async def run_due() -> int:
    """The every-minute job: start what is due and carry on with what is being sent, in every organisation."""
    tried = 0
    deadline = time.monotonic() + 40
    for source_key in await get_all_source_keys():
        try:
            pool = await get_pool(source_key)
            if not await pool.fetchval(
                "SELECT to_regclass('public.announcements') IS NOT NULL"
            ):
                continue
            await pool.execute(
                "UPDATE announcement_recipients SET status = 'failed', "
                "note = 'Not sure it went: sending was interrupted. Check with them, or send again.', updated_at = now() "
                f"WHERE status = 'sending' AND updated_at < now() - interval '{STUCK_MINUTES} minutes'"
            )
            due = await pool.fetch(
                "SELECT id FROM announcements WHERE (status = 'planned' AND send_at <= now()) OR status = 'sending' "
                "ORDER BY send_at LIMIT 10"
            )
        except Exception as e:
            logger.debug(f"announcements: nothing read for {source_key}: {e}")
            continue
        for row in due:
            if time.monotonic() >= deadline:
                return tried
            try:
                tried += await run_one(source_key, row["id"], deadline)
            except Exception as e:
                logger.error(f"announcements: {row['id']} failed: {e!r}")
    return tried


# ------------------------------------------------------------------ what WhatsApp tells us afterwards


async def _move(
    source_key: str, rid: str, status: str, col: str | None, note: str | None = None
) -> None:
    """Move a person's status forward only (a late "delivered" never undoes a "read")."""
    later = ORDER[ORDER.index(status) :] if status in ORDER else [status]
    pool = await get_pool(source_key)
    sets = (
        "status = $2"
        + (f", {col} = now()" if col else "")
        + (", note = $4" if note else "")
    )
    args = [rid, status, later] + ([note] if note else [])
    await pool.execute(
        f"UPDATE announcement_recipients SET {sets}, updated_at = now() "
        "WHERE id = $1::uuid AND NOT (status = ANY($3::text[]))",
        *args,
    )


async def _tracked(wamid: str | None) -> dict | None:
    redis = get_redis()
    if not wamid or redis is None:
        return None
    try:
        raw = await redis.get(f"ann:{wamid}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def on_reports(body: dict) -> None:
    """WhatsApp's delivery reports (delivered, read, failed) for announcement messages. Never raises."""
    try:
        for entry in body.get("entry") or []:
            for change in entry.get("changes") or []:
                for status in (change.get("value") or {}).get("statuses") or []:
                    t = await _tracked(status.get("id"))
                    if not t:
                        continue
                    what = status.get("status")
                    if what == "delivered":
                        await _move(t["s"], t["r"], "delivered", "delivered_at")
                    elif what == "read":
                        await _move(t["s"], t["r"], "read", "read_at")
                    elif what == "failed":
                        code = ((status.get("errors") or [{}])[0]).get("code")
                        if (
                            code == reach.OUTSIDE_THE_WINDOW
                        ):  # reach keeps it and emails it
                            pool = await get_pool(t["s"])
                            await pool.execute(
                                "UPDATE announcement_recipients SET status = 'kept', updated_at = now(), "
                                "note = 'Their WhatsApp was closed after all: kept for when they write.' "
                                "WHERE id = $1::uuid AND status IN ('sent', 'delivered')",
                                t["r"],
                            )
                        else:
                            pool = await get_pool(t["s"])
                            await pool.execute(
                                "UPDATE announcement_recipients SET status = 'failed', note = $2, updated_at = now() "
                                "WHERE id = $1::uuid",
                                t["r"],
                                "WhatsApp could not deliver it"
                                + (
                                    f" ({(status.get('errors') or [{}])[0].get('title')})"
                                    if status.get("errors")
                                    else ""
                                )
                                + ".",
                            )
    except Exception as e:
        logger.warning(f"announcements: a delivery report was not read: {e}")


async def on_got_it(wamid: str | None) -> None:
    """A tap on Got it under an announcement. Never raises."""
    try:
        t = await _tracked(wamid)
        if t:
            await _move(t["s"], t["r"], "got_it", "got_it_at")
    except Exception as e:
        logger.warning(f"announcements: a Got it was not noted: {e}")


async def delivered_later(track: dict | None, answer) -> None:
    """reach sent what was kept for a person (they tapped the template's button or wrote). Never raises."""
    if not isinstance(track, dict) or not track.get("s") or not track.get("r"):
        return
    try:
        wamid = reach._wamid(answer)
        await _remember(wamid, track["s"], track["r"])
        pool = await get_pool(track["s"])
        await pool.execute(
            "UPDATE announcement_recipients SET status = 'sent', sent_at = now(), wamid = COALESCE($2, wamid), "
            "note = 'Sent when they opened their WhatsApp.', updated_at = now() "
            "WHERE id = $1::uuid AND status = 'kept'",
            track["r"],
            wamid,
        )
    except Exception as e:
        logger.warning(f"announcements: a late delivery was not noted: {e}")
