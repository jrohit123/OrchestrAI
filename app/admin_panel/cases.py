"""Cases, read only. Changing a case (assign, comment, close, tell people) is done by the
org's workflows, never by code in this panel."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.admin_panel.common import (
    Ctx,
    CtxDep,
    PanelRoute,
    check_values,
    dump,
    jb,
    rows,
)
from app.db import fetch_all, fetch_one

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


async def get_enums(ctx: Ctx) -> dict[str, list[str]]:
    """Allowed case statuses and priorities (declared order), from the table itself."""
    if not ctx.caps.get("cases"):
        return {"statuses": [], "priorities": []}
    return {
        "statuses": await check_values(ctx, "cases", "status"),
        "priorities": await check_values(ctx, "cases", "priority"),
    }


# ── the list query (also used by the overview and the people screen) ─────────

_SORTS = {
    "newest": "x.created_at DESC",
    "oldest": "x.created_at ASC",
    "due": "x.due_at ASC NULLS LAST, x.created_at DESC",
    "priority": "x.prio_rank ASC NULLS LAST, x.created_at DESC",
    "number": "x.case_number DESC",
}


def case_columns(ctx: Ctx) -> tuple[str, str]:
    """(columns, joins) describing a case row. Parts that need tables this org lacks are
    left out rather than guessed."""
    cols = [
        "c.id",
        "c.case_number",
        "c.title",
        "c.status",
        "c.priority",
        "c.location",
        "c.created_at",
        "c.closed_at",
        "c.complainant_id",
        "cu.name AS complainant_name",
        "c.assigned_to_id",
        "au.name AS assignee_name",
    ]
    joins = [
        "LEFT JOIN users cu ON cu.id = c.complainant_id",
        "LEFT JOIN users au ON au.id = c.assigned_to_id",
    ]
    if ctx.caps.get("targets"):
        # the reminder job counts from created_at + the priority's response time
        joins.append(
            "LEFT JOIN priority_tat_rules t ON t.org_id = c.org_id AND t.priority = c.priority"
        )
        cols.append(
            "COALESCE(c.due_date, c.created_at + make_interval(mins => t.tat_minutes)) AS due_at"
        )
    else:
        cols.append("c.due_date AS due_at")
    if ctx.caps.get("case_category"):
        joins += [
            "LEFT JOIN case_categories k ON k.id = c.category_id",
            "LEFT JOIN case_categories pk ON pk.id = k.parent_id",
        ]
        cols += [
            "c.category_id",
            "k.key AS category_key",
            "k.label AS category_label",
            "pk.label AS category_parent_label",
        ]
    else:
        cols += [
            "NULL::uuid AS category_id",
            "NULL::text AS category_key",
            "NULL::text AS category_label",
            "NULL::text AS category_parent_label",
        ]
    return ", ".join(cols), "\n".join(joins)


def _uuid_or_400(value: str, what: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Bad {what}") from None


def _now_like(ref: datetime) -> datetime:
    return datetime.now(ref.tzinfo) if ref.tzinfo else datetime.now()


async def query_cases(
    ctx: Ctx,
    *,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    assignee: str | None = None,
    requester: str | None = None,
    q: str | None = None,
    overdue: bool = False,
    unassigned: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "newest",
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[dict], int]:
    cols, joins = case_columns(ctx)
    enums = await get_enums(ctx)
    # $2 and $3 always arrive through this one-row CTE, so every placeholder is used
    params: list = [ctx.org_id, ctx.closed_values, enums["priorities"]]
    ctes = ["cfg AS (SELECT $2::text[] AS closed, $3::text[] AS prios)"]
    where = ["c.org_id = $1"]

    def add(value) -> str:
        params.append(value)
        return f"${len(params)}"

    if status == "open":
        where.append("NOT (c.status = ANY(cfg.closed))")
    elif status:
        where.append(f"c.status = ANY({add(status.split(','))}::text[])")
    if priority:
        where.append(f"c.priority = ANY({add(priority.split(','))}::text[])")
    if category == "none" and ctx.caps.get("case_category"):
        where.append("c.category_id IS NULL")
    elif category and ctx.caps.get("case_category"):
        # the chosen category and everything under it
        ctes.append(
            "sub AS (SELECT id FROM case_categories WHERE id = "
            f"{add(_uuid_or_400(category, 'category'))}::uuid UNION ALL "
            "SELECT k2.id FROM case_categories k2 JOIN sub ON k2.parent_id = sub.id)"
        )
        where.append("c.category_id IN (SELECT id FROM sub)")
    if assignee == "none" or unassigned:
        where.append("c.assigned_to_id IS NULL")
    elif assignee:
        where.append(
            f"c.assigned_to_id = {add(_uuid_or_400(assignee, 'person'))}::uuid"
        )
    if requester:
        where.append(
            f"c.complainant_id = {add(_uuid_or_400(requester, 'person'))}::uuid"
        )
    if q:
        like = add(f"%{q.strip()}%")
        where.append(
            f"(c.title ILIKE {like} OR c.description ILIKE {like} OR c.case_number ILIKE {like} "
            f"OR c.location ILIKE {like} OR cu.name ILIKE {like} OR au.name ILIKE {like})"
        )
    if date_from:
        where.append(f"c.created_at >= {add(date_from)}::date")
    if date_to:
        where.append(f"c.created_at < ({add(date_to)}::date + interval '1 day')")

    # "overdue" needs the computed due_at, so it filters one level up
    inner = (
        f"WITH RECURSIVE {', '.join(ctes)} "
        f"SELECT {cols}, (c.status = ANY(cfg.closed)) AS is_closed, "
        "array_position(cfg.prios, c.priority) AS prio_rank "
        f"FROM cases c CROSS JOIN cfg {joins} WHERE {' AND '.join(where)}"
    )
    outer_where = "WHERE x.due_at < now() AND NOT x.is_closed" if overdue else ""
    total = await fetch_one(
        f"SELECT count(*) AS n FROM ({inner}) x {outer_where}",
        *params,
        source_key=ctx.source_key,
    )
    page = await fetch_all(
        f"SELECT x.* FROM ({inner}) x {outer_where} "
        f"ORDER BY {_SORTS.get(sort, _SORTS['newest'])} "
        f"LIMIT {int(limit)} OFFSET {int(offset)}",
        *params,
        source_key=ctx.source_key,
    )
    out = rows(page)
    for r in out:
        r.pop("prio_rank", None)
        r["is_overdue"] = bool(
            not r["is_closed"] and r["due_at"] and r["due_at"] < _now_like(r["due_at"])
        )
    return out, total["n"] if total else 0


def _is_overdue(ctx: Ctx, r: dict) -> bool:
    return bool(
        r["status"] not in ctx.closed_values
        and r["due_at"]
        and r["due_at"] < _now_like(r["due_at"])
    )


@router.get("/cases")
async def list_cases(
    ctx: CtxDep,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    assignee: str | None = None,
    requester: str | None = None,
    q: str | None = None,
    overdue: bool = False,
    unassigned: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "newest",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
):
    ctx.need("cases")
    found, total = await query_cases(
        ctx,
        status=status,
        priority=priority,
        category=category,
        assignee=assignee,
        requester=requester,
        q=q,
        overdue=overdue,
        unassigned=unassigned,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    counts = await fetch_all(
        "SELECT status, count(*) AS n FROM cases WHERE org_id = $1 GROUP BY status",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {
        "rows": found,
        "total": total,
        "page": page,
        "page_size": page_size,
        "status_counts": {r["status"]: r["n"] for r in counts},
    }


# ── one case ─────────────────────────────────────────────────────────────────


async def _routing_preview(ctx: Ctx, case: dict) -> dict | None:
    """Who the routing rules would send this case to today. Read only: the database
    function does the matching, nothing is assigned."""
    if not (ctx.caps.get("case_model") and case.get("category_id")):
        return None
    r = await fetch_one(
        "SELECT * FROM route_case($1, $2, $3::jsonb, NULL, $4)",
        ctx.org_id,
        case["category_id"],
        dump(case.get("custom_fields") or {}),
        case["priority"],
        source_key=ctx.source_key,
    )
    return await describe_route(ctx, r)


async def describe_route(ctx: Ctx, r) -> dict | None:
    """Turn a route_case() row into names."""
    if not r:
        return None
    ids = [i for i in [r["assignee_id"], *(r["level2_ids"] or [])] if i]
    names: dict = {}
    if ids:
        found = await fetch_all(
            "SELECT id, name FROM users WHERE id = ANY($1::uuid[])",
            ids,
            source_key=ctx.source_key,
        )
        names = {x["id"]: x["name"] for x in found}
    return {
        "rule_id": r["rule_id"],
        "rule_name": r["rule_name"],
        "assignee_id": r["assignee_id"],
        "assignee_name": names.get(r["assignee_id"]),
        "level2": [{"id": i, "name": names.get(i)} for i in (r["level2_ids"] or [])],
        "target_minutes": r["target_minutes"],
        "via": r["via"],
    }


@router.get("/cases/{case_id}")
async def case_detail(ctx: CtxDep, case_id: UUID):
    ctx.need("cases")
    cols, joins = case_columns(ctx)
    row = await fetch_one(
        f"SELECT {cols}, c.description, c.custom_fields FROM cases c {joins} "
        "WHERE c.org_id = $1 AND c.id = $2",
        ctx.org_id,
        case_id,
        source_key=ctx.source_key,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    case = dict(row)
    case["custom_fields"] = jb(case.get("custom_fields"), {})
    case["is_overdue"] = _is_overdue(ctx, case)

    timeline: list[dict] = []
    if ctx.caps.get("case_activity"):
        timeline = rows(
            await fetch_all(
                "SELECT a.id, a.activity_type, a.payload, a.created_at, a.actor_user_id, "
                "u.name AS actor_name FROM case_activity a "
                "LEFT JOIN users u ON u.id = a.actor_user_id "
                "WHERE a.case_id = $1 ORDER BY a.created_at ASC",
                case_id,
                source_key=ctx.source_key,
            )
        )
        for a in timeline:
            a["payload"] = jb(a["payload"], {})

    if ctx.caps.get("parties"):
        parties = rows(
            await fetch_all(
                "SELECT p.id, p.user_id, u.name, u.phone, p.party_role, p.added_at, "
                "p.ended_at, p.note FROM case_parties p JOIN users u ON u.id = p.user_id "
                "WHERE p.case_id = $1 ORDER BY (p.ended_at IS NOT NULL), p.added_at",
                case_id,
                source_key=ctx.source_key,
            )
        )
    else:  # no parties table: the two people the case row itself names
        parties = []
        for role, uid, name in (
            ("requester", case["complainant_id"], case["complainant_name"]),
            ("assignee", case["assigned_to_id"], case["assignee_name"]),
        ):
            if uid:
                parties.append(
                    {
                        "id": None,
                        "user_id": uid,
                        "name": name,
                        "phone": None,
                        "party_role": role,
                        "added_at": case["created_at"],
                        "ended_at": None,
                        "note": None,
                    }
                )
    for p in parties:
        p["reachable"] = bool(p.pop("phone", None))
    return {
        "case": case,
        "timeline": timeline,
        "parties": parties,
        "routing": await _routing_preview(ctx, case),
    }
