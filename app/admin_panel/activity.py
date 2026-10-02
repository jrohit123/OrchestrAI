"""Activity: chats grouped by conversation, and the dashboard's own change log."""

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
    row comes from the classic endpoint /api/activity/session."""
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
