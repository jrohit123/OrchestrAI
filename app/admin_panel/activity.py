"""Activity: every message the assistant answered, chats grouped by conversation, a transcript,
and the dashboard's own change log."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.admin_panel.common import CtxDep, PanelRoute, jb, rows
from app.db import fetch_all, fetch_one

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


@router.get("/chats")
async def list_chats(
    ctx: CtxDep,
    user_id: UUID | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
):
    """One row per conversation (audit_log rows sharing a session_id). The transcript of a
    row comes from /activity/session."""
    ctx.need("audit")
    params: list = [ctx.org_id]
    where = ["a.org_id = $1"]

    def add(value) -> str:
        params.append(value)
        return f"${len(params)}"

    if user_id:
        where.append(f"a.user_id = {add(user_id)}")
    if q:
        like = add(f"%{q.strip()}%")
        where.append(f"(a.input_text ILIKE {like} OR a.response_text ILIKE {like})")
    if date_from:
        where.append(f"a.created_at >= {add(date_from)}::date")
    if date_to:
        where.append(f"a.created_at < ({add(date_to)}::date + interval '1 day')")
    grouped = f"""
        SELECT COALESCE(a.session_id, a.id::text) AS session_key,
               max(a.session_id) AS session_id,
               (array_agg(a.user_id ORDER BY a.created_at))[1] AS user_id,
               min(a.created_at) AS started_at, max(a.created_at) AS last_at,
               count(*) AS turns,
               (array_agg(a.input_text ORDER BY a.created_at DESC))[1] AS last_input,
               (array_agg(a.response_text ORDER BY a.created_at DESC))[1] AS last_reply,
               bool_or(a.outcome = 'error') AS had_error,
               array_remove(array_agg(DISTINCT (
                   SELECT w.name FROM workflows w
                    WHERE w.org_id = a.org_id AND w.intent_key = a.intent_key LIMIT 1
               )), NULL) AS workflows
          FROM audit_log a WHERE {" AND ".join(where)}
         GROUP BY COALESCE(a.session_id, a.id::text)
    """
    total = await fetch_one(
        f"SELECT count(*) AS n FROM ({grouped}) g", *params, source_key=ctx.source_key
    )
    found = await fetch_all(
        f"SELECT g.*, u.name AS user_name FROM ({grouped}) g "
        "LEFT JOIN users u ON u.id = g.user_id "
        f"ORDER BY g.last_at DESC LIMIT {page_size} OFFSET {(page - 1) * page_size}",
        *params,
        source_key=ctx.source_key,
    )
    people = await fetch_all(
        "SELECT DISTINCT u.id, u.name FROM audit_log a JOIN users u ON u.id = a.user_id "
        "WHERE a.org_id = $1 ORDER BY u.name",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {
        "rows": rows(found),
        "total": total["n"],
        "page": page,
        "page_size": page_size,
        "people": rows(people),
    }


@router.get("/activity")
async def list_activity(
    ctx: CtxDep,
    user_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    outcome: str | None = None,
    search: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """Every message the assistant answered, newest first. intent_key is 'agent' or 'menu' for
    ordinary chat turns (the real content is in input_text and response_text); anything else is a
    genuine workflow name and is shown as it is. 'agent' and 'menu' say nothing useful, so they
    are shown as "Chat"."""
    ctx.need("audit")
    params: list = [ctx.org_id]
    where = "a.org_id = $1"

    def add(value) -> str:
        params.append(value)
        return f"${len(params)}"

    if user_id:
        where += f" AND a.user_id = {add(user_id)}"
    if date_from:
        where += f" AND a.created_at >= {add(date_from)}::date"
    if date_to:
        where += f" AND a.created_at < ({add(date_to)}::date + interval '1 day')"
    if outcome:
        where += f" AND a.outcome = {add(outcome)}"
    if search:
        like = add(f"%{search}%")
        where += f" AND (a.input_text ILIKE {like} OR a.response_text ILIKE {like})"

    total = await fetch_one(
        f"SELECT COUNT(*) AS n FROM audit_log a WHERE {where}",
        *params,
        source_key=ctx.source_key,
    )
    found = await fetch_all(
        "SELECT a.id, a.created_at, a.user_id, u.name AS user_name, a.intent_key, "
        "a.input_text, a.response_text, a.outcome, a.session_id "
        "FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
        f"WHERE {where} ORDER BY a.created_at DESC "
        f"LIMIT {page_size} OFFSET {(page - 1) * page_size}",
        *params,
        source_key=ctx.source_key,
    )
    people = await fetch_all(
        "SELECT DISTINCT u.id, u.name FROM audit_log a JOIN users u ON u.id = a.user_id "
        "WHERE a.org_id = $1 ORDER BY u.name",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    out = []
    for r in found:
        d = dict(r)
        d["id"] = str(d["id"])
        d["user_id"] = str(d["user_id"]) if d["user_id"] else None
        d["workflow"] = (
            d["intent_key"] if d["intent_key"] not in ("agent", "menu") else "Chat"
        )
        out.append(d)
    return {
        "rows": out,
        "total": total["n"] if total else 0,
        "page": page,
        "page_size": page_size,
        "users": [{"id": str(u["id"]), "name": u["name"]} for u in people],
    }


@router.get("/activity/session")
async def session_transcript(ctx: CtxDep, session_id: str):
    """The whole conversation: every row that shares this session_id, oldest first so it reads
    top to bottom like a chat."""
    ctx.need("audit")
    found = await fetch_all(
        "SELECT a.created_at, u.name AS user_name, a.input_text, a.response_text "
        "FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
        "WHERE a.org_id = $1 AND a.session_id = $2 ORDER BY a.created_at ASC",
        ctx.org_id,
        session_id,
        source_key=ctx.source_key,
    )
    return {"rows": rows(found)}


@router.get("/events")
async def list_events(
    ctx: CtxDep,
    area: str | None = None,
    q: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
):
    """What was changed from the dashboard (and by which migration or screen)."""
    ctx.need("events")
    params: list = [ctx.org_id]
    where = ["org_id = $1"]
    if area:
        params.append(area)
        where.append(f"area = ${len(params)}")
    if q:
        params.append(f"%{q.strip()}%")
        where.append(
            f"(summary ILIKE ${len(params)} OR actor_label ILIKE ${len(params)})"
        )
    clause = " AND ".join(where)
    total = await fetch_one(
        f"SELECT count(*) AS n FROM admin_events WHERE {clause}",
        *params,
        source_key=ctx.source_key,
    )
    found = rows(
        await fetch_all(
            "SELECT id, created_at, actor_label, area, action, target_type, target_id, "
            f"summary, before_state, after_state FROM admin_events WHERE {clause} "
            f"ORDER BY created_at DESC LIMIT {page_size} OFFSET {(page - 1) * page_size}",
            *params,
            source_key=ctx.source_key,
        )
    )
    for e in found:
        e["before_state"] = jb(e["before_state"], None)
        e["after_state"] = jb(e["after_state"], None)
    areas = await fetch_all(
        "SELECT DISTINCT area FROM admin_events WHERE org_id = $1 ORDER BY area",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {
        "rows": found,
        "total": total["n"],
        "page": page,
        "page_size": page_size,
        "areas": [a["area"] for a in areas],
    }
