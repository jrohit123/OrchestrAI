"""Start-up facts for the page (which sections exist, allowed values), the lookup lists the
pickers use, system status, and the response-time table."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.admin_panel.cases import get_enums
from app.admin_panel.common import (
    CASE_MODEL_PARTS,
    CtxDep,
    PanelRoute,
    check_values,
    log_event,
    people_channel,
    rows,
    tx,
)
from app.db import fetch_all, fetch_one
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


def _sections(caps: dict[str, bool]) -> list[dict]:
    """Which screens this org gets. Driven by what its database can do, not by org name.
    The page puts Home, Cases, Conversations and People under "Every day" and the rest under
    "Set up": how cases are sent and timed, roles and seats, what the assistant says, settings."""
    sections: list[dict] = [{"key": "overview", "label": "Home"}]
    if caps.get("cases"):
        sections.append({"key": "cases", "label": "Cases"})
    if caps.get("audit"):
        sections.append({"key": "conversations", "label": "Conversations"})
    sections.append({"key": "people", "label": "People"})
    sections.append({"key": "workflows", "label": "Flows"})
    assistant_tabs = []
    if caps.get("texts"):
        assistant_tabs.append({"key": "messages", "label": "What it says"})
    if caps.get("prompts"):
        assistant_tabs.append({"key": "instructions", "label": "How it answers"})
    if assistant_tabs:
        sections.append(
            {"key": "assistant", "label": "Assistant", "tabs": assistant_tabs}
        )
    if caps.get("cases"):
        rule_tabs = []
        if caps.get("case_model"):
            rule_tabs += [
                {"key": "rules", "label": "Who gets them"},
                {"key": "categories", "label": "Kinds of complaint"},
            ]
        if caps.get("targets"):
            rule_tabs.append({"key": "times", "label": "Response times"})
        if rule_tabs:
            sections.append({"key": "rules", "label": "Case rules", "tabs": rule_tabs})
    access_tabs = [{"key": "roles", "label": "Roles"}]
    if caps.get("seats"):
        access_tabs.append({"key": "seats", "label": "Seats"})
    if caps.get("grants"):
        access_tabs.append({"key": "special", "label": "Special access"})
    sections.append({"key": "access", "label": "Roles & access", "tabs": access_tabs})
    settings: dict = {"key": "settings", "label": "Settings"}
    if caps.get("events") or caps.get("audit"):
        settings["tabs"] = [
            {"key": "general", "label": "Settings"},
            {"key": "history", "label": "History of changes"},
        ]
    sections.append(settings)
    return sections


@router.get("/bootstrap")
async def bootstrap(ctx: CtxDep):
    org = await fetch_one(
        "SELECT name, industry, COALESCE(logo_url, '') <> '' AS has_logo "
        "FROM orgs WHERE id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    enums = await get_enums(ctx)
    return {
        "org": {
            "name": org["name"],
            "industry": org["industry"],
            "slug": ctx.source_key,
            "has_logo": org["has_logo"],
            "channel": await people_channel(ctx.source_key),
        },
        "caps": ctx.caps,
        "enums": {**enums, "closed": ctx.closed_values},
        "sections": _sections(ctx.caps),
    }


@router.get("/nav-hints")
async def nav_hints(ctx: CtxDep):
    """Two small numbers for the menu: open cases nobody has yet, and kinds of complaint no rule
    sends anyone. They are a courtesy, so a problem gives nothing here and never an error."""
    out: dict = {"unassigned": None, "rule_gaps": None}
    try:
        if ctx.caps.get("cases"):
            found = await fetch_one(
                "SELECT count(*) AS n FROM cases WHERE org_id = $1 AND assigned_to_id IS NULL "
                "AND NOT (status = ANY($2::text[]))",
                ctx.org_id,
                ctx.closed_values,
                source_key=ctx.source_key,
            )
            out["unassigned"] = found["n"]
        if ctx.caps.get("case_model"):
            found = await fetch_one(
                "SELECT count(*) AS n FROM case_categories k WHERE k.org_id = $1 AND k.is_active "
                "AND NOT EXISTS (SELECT 1 FROM route_case(k.org_id, k.id, '{}'::jsonb))",
                ctx.org_id,
                source_key=ctx.source_key,
            )
            out["rule_gaps"] = found["n"]
    except Exception as e:
        logger.warning(f"menu numbers failed: {e!r}")
    return out


@router.get("/lookups")
async def lookups(ctx: CtxDep):
    """Short lists the pickers need. People are searched separately (GET /people)."""
    roles = rows(
        await fetch_all(
            "SELECT r.id, r.name, (SELECT count(*) FROM users u WHERE u.role_id = r.id) AS users "
            "FROM roles r WHERE r.org_id = $1 ORDER BY r.name",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    kind = "kind" if ctx.caps.get("workflow_kind") else "'workflow'::text AS kind"
    workflows = rows(
        await fetch_all(
            f"SELECT id, intent_key, name, is_active, {kind} FROM workflows "
            "WHERE org_id = $1 ORDER BY name",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    seats: list[dict] = []
    if ctx.caps.get("seats"):
        seat_kind = "kind" if ctx.caps.get("seat_kind") else "NULL::text AS kind"
        seats = rows(
            await fetch_all(
                f"SELECT id, name, {seat_kind} FROM committee_positions "
                "WHERE org_id = $1 ORDER BY name",
                ctx.org_id,
                source_key=ctx.source_key,
            )
        )
    categories: list[dict] = []
    if ctx.caps.get("categories"):
        categories = rows(
            await fetch_all(
                "SELECT id, key, label, parent_id, is_active, sort_order "
                "FROM case_categories WHERE org_id = $1",
                ctx.org_id,
                source_key=ctx.source_key,
            )
        )
    enums = await get_enums(ctx)
    if ctx.caps.get("residents"):
        enums["resident_types"] = await check_values(
            ctx, "residents", "residential_status"
        )
        enums["resident_statuses"] = await check_values(ctx, "residents", "status")
    if ctx.caps.get("seat_kind"):
        enums["seat_kinds"] = await check_values(ctx, "committee_positions", "kind")
    return {
        "roles": roles,
        "workflows": workflows,
        "seats": seats,
        "categories": categories,
        "enums": enums,
    }


@router.get("/status")
async def system_status(ctx: CtxDep):
    missing = [p for p in CASE_MODEL_PARTS if not ctx.caps.get(p)]
    counts = await fetch_one(
        "SELECT (SELECT count(*) FROM users WHERE org_id = $1) AS users, "
        "(SELECT count(*) FROM workflows WHERE org_id = $1) AS workflows",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {
        "org": ctx.org_name,
        "caps": ctx.caps,
        "case_model_installed": ctx.caps.get("case_model", False),
        "case_model_missing": missing if ctx.caps.get("cases") else [],
        "closed_values": ctx.closed_values,
        "counts": dict(counts),
    }


# ── response times (priority → how long, when to remind) ─────────────────────


class TargetRow(BaseModel):
    priority: str
    tat_minutes: int = Field(..., ge=1, le=525600)
    reminder_threshold_minutes: int = Field(..., ge=0, le=525600)


class TargetsBody(BaseModel):
    rows: list[TargetRow] = Field(..., min_length=1, max_length=20)


@router.get("/targets")
async def get_targets(ctx: CtxDep):
    ctx.need("targets")
    enums = await get_enums(ctx)
    found = rows(
        await fetch_all(
            "SELECT priority, tat_minutes, reminder_threshold_minutes "
            "FROM priority_tat_rules WHERE org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    order = {p: i for i, p in enumerate(enums["priorities"])}
    found.sort(key=lambda r: order.get(r["priority"], 99))
    have = {r["priority"] for r in found}
    return {
        "rows": found,
        "missing": [p for p in enums["priorities"] if p not in have],
    }


@router.put("/targets")
async def put_targets(ctx: CtxDep, body: TargetsBody):
    """How long each priority gets, and when the reminder goes. The reminder job reads
    this table, so a change here applies to open cases too."""
    ctx.need("targets")
    allowed = (await get_enums(ctx))["priorities"]
    for r in body.rows:
        if allowed and r.priority not in allowed:
            raise HTTPException(
                status_code=400, detail=f"Unknown priority '{r.priority}'."
            )
        if r.reminder_threshold_minutes > r.tat_minutes:
            raise HTTPException(
                status_code=400,
                detail=f"For {r.priority}, the reminder must come before the target time.",
            )
    async with tx(ctx) as conn:
        before = rows(
            await conn.fetch(
                "SELECT priority, tat_minutes, reminder_threshold_minutes "
                "FROM priority_tat_rules WHERE org_id = $1",
                ctx.org_id,
            )
        )
        for r in body.rows:
            await conn.execute(
                "INSERT INTO priority_tat_rules (org_id, priority, tat_minutes, "
                "reminder_threshold_minutes) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (org_id, priority) DO UPDATE SET "
                "tat_minutes = EXCLUDED.tat_minutes, "
                "reminder_threshold_minutes = EXCLUDED.reminder_threshold_minutes",
                ctx.org_id,
                r.priority,
                r.tat_minutes,
                r.reminder_threshold_minutes,
            )
        await log_event(
            ctx,
            "settings",
            "targets",
            "Changed response times",
            target_type="priority_tat_rules",
            before=before,
            after=[r.model_dump() for r in body.rows],
            conn=conn,
        )
    return {"ok": True}
