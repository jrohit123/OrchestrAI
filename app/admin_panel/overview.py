"""The Overview screen: numbers and short lists, all read only."""

from fastapi import APIRouter

from app.admin_panel.cases import get_enums, query_cases
from app.admin_panel.common import CtxDep, PanelRoute, rows
from app.db import fetch_all, fetch_one

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

_CFG = "WITH cfg AS (SELECT $2::text[] AS closed, $3::text[] AS prios) "


@router.get("/overview")
async def overview(ctx: CtxDep):
    out: dict = {"cases": None, "people": None, "workflows": None, "events": []}
    enums = await get_enums(ctx)
    args = (ctx.org_id, ctx.closed_values, enums["priorities"])

    if ctx.caps.get("cases"):
        due = (
            "COALESCE(c.due_date, c.created_at + make_interval(mins => t.tat_minutes))"
            if ctx.caps.get("targets")
            else "c.due_date"
        )
        tat = (
            "LEFT JOIN priority_tat_rules t ON t.org_id = c.org_id AND t.priority = c.priority"
            if ctx.caps.get("targets")
            else ""
        )
        base = (
            f"SELECT c.*, {due} AS due_at, (c.status = ANY(cfg.closed)) AS is_closed "
            f"FROM cases c CROSS JOIN cfg {tat} WHERE c.org_id = $1"
        )
        k = await fetch_one(
            f"{_CFG}SELECT count(*) AS total, "
            "count(*) FILTER (WHERE NOT is_closed) AS open, "
            "count(*) FILTER (WHERE NOT is_closed AND assigned_to_id IS NULL) AS unassigned, "
            "count(*) FILTER (WHERE NOT is_closed AND due_at < now()) AS overdue, "
            "count(*) FILTER (WHERE NOT is_closed AND priority = (SELECT prios[1] FROM cfg)) AS top_priority_open, "
            "count(*) FILTER (WHERE closed_at >= now() - interval '7 days') AS closed_7d, "
            "count(*) FILTER (WHERE created_at >= now() - interval '7 days') AS created_7d "
            f"FROM ({base}) b",
            *args,
            source_key=ctx.source_key,
        )
        by_status = await fetch_all(
            "SELECT status, count(*) AS n FROM cases WHERE org_id = $1 GROUP BY status",
            ctx.org_id,
            source_key=ctx.source_key,
        )
        by_priority = await fetch_all(
            f"{_CFG}SELECT priority, count(*) AS n FROM cases c WHERE org_id = $1 "
            "AND NOT (c.status = ANY((SELECT closed FROM cfg)::text[])) GROUP BY priority",
            *args,
            source_key=ctx.source_key,
        )
        if ctx.caps.get("case_category"):
            by_category = await fetch_all(
                f"{_CFG}SELECT k.id, COALESCE(k.label, 'No category') AS label, count(*) AS n "
                "FROM cases c LEFT JOIN case_categories k ON k.id = c.category_id "
                "WHERE c.org_id = $1 AND NOT (c.status = ANY((SELECT closed FROM cfg)::text[])) "
                "GROUP BY k.id, k.label ORDER BY n DESC LIMIT 8",
                *args,
                source_key=ctx.source_key,
            )
        else:
            by_category = []
        trend = await fetch_all(
            "SELECT d::date AS day, "
            "(SELECT count(*) FROM cases c WHERE c.org_id = $1 AND c.created_at::date = d::date) AS created, "
            "(SELECT count(*) FROM cases c WHERE c.org_id = $1 AND c.closed_at::date = d::date) AS closed "
            "FROM generate_series(current_date - 13, current_date, interval '1 day') d ORDER BY d",
            ctx.org_id,
            source_key=ctx.source_key,
        )
        unassigned, _ = await query_cases(
            ctx, status="open", unassigned=True, sort="priority", limit=5
        )
        overdue, _ = await query_cases(
            ctx, status="open", overdue=True, sort="due", limit=5
        )
        out["cases"] = {
            "kpis": dict(k),
            "by_status": rows(by_status),
            "by_priority": rows(by_priority),
            "by_category": rows(by_category),
            "trend": rows(trend),
            "unassigned": unassigned,
            "overdue": overdue,
            "top_priority": enums["priorities"][0] if enums["priorities"] else None,
            "statuses": enums["statuses"],
            "priorities": enums["priorities"],
            "closed_values": ctx.closed_values,
        }

    p = await fetch_one(
        "SELECT count(*) AS total, count(*) FILTER (WHERE is_active) AS active, "
        "count(*) FILTER (WHERE (channel = 'telegram' AND phone LIKE 'tg:%') "
        "OR (COALESCE(channel, '') <> 'telegram' AND phone IS NOT NULL)) AS reachable "
        "FROM users WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    out["people"] = dict(p)

    w = await fetch_one(
        "SELECT count(*) AS total, count(*) FILTER (WHERE is_active) AS active "
        "FROM workflows WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    out["workflows"] = dict(w)

    if ctx.caps.get("events"):
        out["events"] = rows(
            await fetch_all(
                "SELECT id, created_at, actor_label, area, summary FROM admin_events "
                "WHERE org_id = $1 ORDER BY created_at DESC LIMIT 8",
                ctx.org_id,
                source_key=ctx.source_key,
            )
        )
    return out
