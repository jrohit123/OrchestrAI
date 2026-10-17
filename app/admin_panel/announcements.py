"""The Announcements screen: write a message, tick who gets it (see services/announcements.py for what the ticks
mean), see exactly who that is and how each person will be reached, then send it now or at a set time. Afterwards,
what happened to each person.

Ready choices of who gets it are rows of announcement_audiences, so they are added and removed here, not in code.
Both a super admin and an admin of the organisation may use it. Sending itself is done by the every-minute job and,
for "Send now", started at once (services/announcements.py)."""

import base64
import datetime as dt
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.admin_panel.common import (
    CtxDep,
    PanelRoute,
    check_values,
    log_event,
    people_channel,
    rows,
    tx,
)
from app.db import fetch_all, fetch_one
from app.services import announcements as ann_service
from app.services import config_store, reach
from app.services.messages import say

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

MAX_FILE_BYTES = 8_000_000
MAX_BODY = 3000
RECIPIENT_STATES = (
    "waiting",
    "sending",
    "kept",
    "sent",
    "emailed",
    "delivered",
    "read",
    "got_it",
    "failed",
)


def _filters(raw) -> dict:
    try:
        return ann_service.clean_filters(raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


async def _words(ctx, f: dict) -> str:
    """The ticks in one sentence, with the organisation's own words for the values."""
    labels = (ctx.settings or {}).get("labels") or {}
    word = lambda v: labels.get(v) or v.replace("_", " ").capitalize()
    roles = {}
    if f["roles"]:
        roles = {
            str(r["id"]): r["name"]
            for r in await fetch_all(
                "SELECT id, name FROM roles WHERE org_id = $1",
                ctx.org_id,
                source_key=ctx.source_key,
            )
        }
    role_text = " / ".join(roles.get(r, "?") for r in f["roles"])
    if not f["by_flat"]:
        return f"Everyone whose role is {role_text}."
    every = await check_values(ctx, "residents", "relation")
    lives = (
        "live here or elsewhere"
        if len(f["lives"]) == 2
        else "live here"
        if f["lives"] == ["here"]
        else "live elsewhere"
    )
    s = f"People who {lives}"
    if set(f["relations"]) != set(every):
        s += ", who are " + " / ".join(word(r) for r in f["relations"])
    if f["primary"] == "only":
        s += ", and are the primary member of the flat"
    elif f["primary"] == "not":
        s += ", and are not the primary member"
    s += f", in wing {' / '.join(f['wings'])}" if f["wings"] else ", in all wings"
    if f["roles"]:
        s += f", whose role is {role_text}"
    return s + "."


@router.get("/announcements/setup")
async def setup(ctx: CtxDep):
    """What the screen needs: the ready choices, the relations and wings to tick, the roles, the words around the
    message, and how a closed WhatsApp is handled."""
    ctx.need("announcements")
    labels = (ctx.settings or {}).get("labels") or {}
    audiences = await fetch_all(
        "SELECT id, name, hint, filters, created_by FROM announcement_audiences WHERE org_id = $1 "
        "ORDER BY sort_order, name",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    wings = await fetch_all(
        "SELECT DISTINCT wing FROM residents WHERE org_id = $1 AND wing IS NOT NULL ORDER BY wing",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    roles = await fetch_all(
        "SELECT r.id, r.name, (SELECT count(*) FROM users u WHERE u.role_id = r.id AND u.is_active) AS people "
        "FROM roles r WHERE r.org_id = $1 ORDER BY r.name",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    settings = await config_store.org_settings(ctx.source_key, ctx.org_id)
    template = reach.template_of(settings)
    flats = await fetch_one(
        "SELECT count(*) AS homes, count(DISTINCT user_id) AS people FROM residents WHERE org_id = $1 "
        "AND user_id IS NOT NULL AND status = 'active'",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {
        "audiences": [
            {
                "id": str(a["id"]),
                "name": a["name"],
                "hint": a["hint"],
                "filters": a["filters"]
                if isinstance(a["filters"], dict)
                else json.loads(a["filters"]),
                "own": a["created_by"] != "seed",
            }
            for a in audiences
        ],
        "relations": [
            [v, labels.get(v) or v.replace("_", " ").capitalize()]
            for v in await check_values(ctx, "residents", "relation")
        ],
        "wings": [w["wing"] for w in wings],
        "roles": [
            {"id": str(r["id"]), "name": r["name"], "people": r["people"]}
            for r in roles
        ],
        "texts": {
            "greeting": await say(
                ctx.source_key, "announce.greeting", first_name="{first_name}"
            ),
            "sign_off": await say(
                ctx.source_key, "announce.sign_off", org_name=ctx.org_name
            ),
            "file_emailed": await say(
                ctx.source_key, "announce.file_emailed", file_name="{file_name}"
            ),
            "file_ask": await say(
                ctx.source_key, "announce.file_ask", file_name="{file_name}"
            ),
            "got_it": await say(ctx.source_key, "hold.got_it_title"),
        },
        "channel": await people_channel(ctx.source_key),
        "template": template[0] if template else None,
        "reach_on": reach.feature_on(settings),
        "linked": {"homes": flats["homes"], "people": flats["people"]},
    }


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: dict


@router.post("/announcements/preview")
async def preview(ctx: CtxDep, body: PreviewBody):
    """Who these ticks reach right now, how each one will be reached, and who is left out and why. Sends nothing."""
    ctx.need("announcements")
    f = _filters(body.filters)
    people = await ann_service.audience(ctx.source_key, ctx.org_id, f)
    open_ = await ann_service.doors(ctx.source_key, ctx.org_id, people)
    out = []
    for p in people:
        ch = ann_service.channel_of(p["phone"], p["email"])
        how = (
            ("whatsapp" if open_.get(p["phone"]) else "whatsapp_closed")
            if ch == "whatsapp"
            else ch
        )
        out.append(
            {
                "id": str(p["id"]),
                "name": p["name"],
                "flats": p["flats"] or "",
                "how": how,
                "has_email": bool((p["email"] or "").strip()),
            }
        )
    left = await ann_service.left_out(
        ctx.source_key, ctx.org_id, f, {p["id"] for p in people}
    )
    counts: dict[str, int] = {}
    for p in out:
        counts[p["how"]] = counts.get(p["how"], 0) + 1
    return {
        "people": out,
        "left_out": left,
        "counts": counts,
        "flats": len(
            {x.strip() for p in out for x in p["flats"].split(",") if x.strip()}
        ),
        "words": await _words(ctx, f),
    }


class NewAnnouncement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field("", max_length=120)
    body: str = Field(..., min_length=1, max_length=MAX_BODY)
    greet: bool = True
    filters: dict
    audience_name: str = Field("", max_length=120)
    send_at: dt.datetime | None = None  # empty: now
    file_name: str | None = Field(None, max_length=160)
    file_type: str | None = Field(None, max_length=100)
    file_b64: str | None = Field(None, max_length=11_000_000)


@router.post("/announcements")
async def create(ctx: CtxDep, body: NewAnnouncement):
    """Save an announcement to send now or at a set time. Who gets it is worked out again when it goes."""
    ctx.need("announcements")
    f = _filters(body.filters)
    text = body.body.strip()
    if not text:
        raise HTTPException(400, "Write the message first.")
    now = dt.datetime.now(dt.timezone.utc)
    send_at = body.send_at
    if send_at is not None:
        if send_at.tzinfo is None:
            raise HTTPException(400, "The time needs its time zone.")
        if send_at < now - dt.timedelta(minutes=1):
            raise HTTPException(400, "That time has already passed.")
    data = None
    if body.file_b64:
        try:
            data = base64.b64decode(body.file_b64, validate=True)
        except ValueError as e:
            raise HTTPException(
                400, "The file did not arrive whole. Choose it again."
            ) from e
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(400, "The file is too big (8 MB at most).")
        if not body.file_name:
            raise HTTPException(400, "The file needs a name.")
    people = await ann_service.audience(ctx.source_key, ctx.org_id, f)
    if not people:
        raise HTTPException(400, "Nobody matches these ticks.")
    words = await _words(ctx, f)
    async with tx(ctx) as conn:
        new_id = await conn.fetchval(
            "INSERT INTO announcements (org_id, title, body, greet, filters, audience_text, audience_name, "
            "file_name, file_type, file_data, status, send_at, created_by) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, 'planned', $11, $12) RETURNING id",
            ctx.org_id,
            body.title.strip(),
            text,
            body.greet,
            json.dumps(f),
            words,
            body.audience_name.strip(),
            body.file_name if data else None,
            (body.file_type or "application/pdf") if data else None,
            data,
            send_at or now,
            ctx.actor,
        )
        await log_event(
            ctx,
            "announcements",
            "create",
            f"Announcement “{body.title.strip() or text[:40]}” "
            + (f"planned for {send_at.isoformat()}" if send_at else "sent")
            + f" to {len(people)} people ({words})",
            target_type="announcement",
            target_id=new_id,
            after={"filters": f, "people": len(people), "send_at": str(send_at or now)},
            conn=conn,
        )
    if send_at is None or send_at <= now:
        ann_service.start_now(ctx.source_key, new_id)
    return {"ok": True, "id": str(new_id), "people": len(people)}


@router.get("/announcements")
async def list_announcements(ctx: CtxDep):
    ctx.need("announcements")
    found = await fetch_all(
        "SELECT a.id, a.title, left(a.body, 160) AS body, a.status, a.send_at, a.started_at, a.finished_at, "
        "a.audience_name, a.audience_text, a.file_name, a.created_by, a.created_at, "
        "(SELECT jsonb_object_agg(s, n) FROM (SELECT status AS s, count(*) AS n FROM announcement_recipients r "
        "  WHERE r.announcement_id = a.id GROUP BY status) x) AS counts "
        "FROM announcements a WHERE a.org_id = $1 ORDER BY a.created_at DESC LIMIT 200",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    out = rows(found)
    for a in out:
        a["counts"] = (
            a["counts"]
            if isinstance(a["counts"], dict)
            else json.loads(a["counts"] or "{}")
        )
    return {"rows": out}


@router.get("/announcements/{ann_id}")
async def one(ctx: CtxDep, ann_id: UUID):
    ctx.need("announcements")
    a = await fetch_one(
        "SELECT id, title, body, greet, filters, audience_text, audience_name, file_name, status, send_at, "
        "started_at, finished_at, created_by, created_at FROM announcements WHERE id = $1 AND org_id = $2",
        ann_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not a:
        raise HTTPException(404, "Announcement not found")
    a = dict(a)
    a["filters"] = (
        a["filters"] if isinstance(a["filters"], dict) else json.loads(a["filters"])
    )
    people = rows(
        await fetch_all(
            "SELECT user_id, name, flats, channel, status, emailed, note, sent_at, delivered_at, read_at, "
            "got_it_at, updated_at FROM announcement_recipients WHERE announcement_id = $1 ORDER BY name",
            ann_id,
            source_key=ctx.source_key,
        )
    )
    counts = {s: 0 for s in RECIPIENT_STATES}
    for p in people:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    return {"announcement": a, "people": people, "counts": counts}


@router.get("/announcements/{ann_id}/file")
async def file(ctx: CtxDep, ann_id: UUID):
    ctx.need("announcements")
    a = await fetch_one(
        "SELECT file_name, file_type, file_data FROM announcements WHERE id = $1 AND org_id = $2",
        ann_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not a or not a["file_data"]:
        raise HTTPException(404, "No file")
    return Response(
        bytes(a["file_data"]),
        media_type=a["file_type"] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{a["file_name"]}"'},
    )


async def _planned(ctx, conn, ann_id: UUID):
    a = await conn.fetchrow(
        "SELECT id, title, body, status FROM announcements WHERE id = $1 AND org_id = $2 FOR UPDATE",
        ann_id,
        ctx.org_id,
    )
    if not a:
        raise HTTPException(404, "Announcement not found")
    if a["status"] != "planned":
        raise HTTPException(409, "It has already gone out, so it cannot be changed.")
    return a


@router.post("/announcements/{ann_id}/send-now")
async def send_now(ctx: CtxDep, ann_id: UUID):
    ctx.need("announcements")
    async with tx(ctx) as conn:
        a = await _planned(ctx, conn, ann_id)
        await conn.execute(
            "UPDATE announcements SET send_at = now() WHERE id = $1", ann_id
        )
        await log_event(
            ctx,
            "announcements",
            "send",
            f"Announcement “{a['title'] or a['body'][:40]}” sent now instead of at its planned time",
            target_type="announcement",
            target_id=ann_id,
            conn=conn,
        )
    ann_service.start_now(ctx.source_key, ann_id)
    return {"ok": True}


@router.post("/announcements/{ann_id}/cancel")
async def cancel(ctx: CtxDep, ann_id: UUID):
    ctx.need("announcements")
    async with tx(ctx) as conn:
        a = await _planned(ctx, conn, ann_id)
        await conn.execute(
            "UPDATE announcements SET status = 'cancelled' WHERE id = $1", ann_id
        )
        await log_event(
            ctx,
            "announcements",
            "cancel",
            f"Announcement “{a['title'] or a['body'][:40]}” cancelled before it went out",
            target_type="announcement",
            target_id=ann_id,
            conn=conn,
        )
    return {"ok": True}


class AudienceNew(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=2, max_length=80)
    hint: str = Field("", max_length=120)
    filters: dict


@router.post("/announcement-audiences")
async def add_audience(ctx: CtxDep, body: AudienceNew):
    """Keep the current ticks as a ready choice."""
    ctx.need("announcements")
    f = _filters(body.filters)
    async with tx(ctx) as conn:
        if await conn.fetchval(
            "SELECT 1 FROM announcement_audiences WHERE org_id = $1 AND lower(name) = lower($2)",
            ctx.org_id,
            body.name.strip(),
        ):
            raise HTTPException(409, "There is already a ready choice with that name.")
        new_id = await conn.fetchval(
            "INSERT INTO announcement_audiences (org_id, name, hint, filters, sort_order, created_by) "
            "VALUES ($1, $2, $3, $4::jsonb, (SELECT COALESCE(max(sort_order), 0) + 1 FROM announcement_audiences "
            "WHERE org_id = $1), $5) RETURNING id",
            ctx.org_id,
            body.name.strip(),
            body.hint.strip(),
            json.dumps(f),
            ctx.actor,
        )
        await log_event(
            ctx,
            "announcements",
            "audience",
            f"Saved the ready choice “{body.name.strip()}”",
            target_type="announcement_audience",
            target_id=new_id,
            after=f,
            conn=conn,
        )
    return {"ok": True, "id": str(new_id)}


@router.delete("/announcement-audiences/{audience_id}")
async def remove_audience(ctx: CtxDep, audience_id: UUID):
    ctx.need("announcements")
    async with tx(ctx) as conn:
        gone = await conn.fetchrow(
            "DELETE FROM announcement_audiences WHERE id = $1 AND org_id = $2 RETURNING name, filters",
            audience_id,
            ctx.org_id,
        )
        if not gone:
            raise HTTPException(404, "Not found")
        await log_event(
            ctx,
            "announcements",
            "audience",
            f"Removed the ready choice “{gone['name']}”",
            target_type="announcement_audience",
            target_id=audience_id,
            before=dict(gone),
            conn=conn,
        )
    return {"ok": True}
