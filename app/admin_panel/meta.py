"""Start-up facts for the page (which sections exist, allowed values), the lookup lists the
pickers use, system status, and the response-time table."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.admin_panel.case_buttons import assign_state
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


ADMIN_SECTIONS = {
    "overview",
    "cases",
    "conversations",
    "people",
}  # what an admin (not a super admin) sees
# the tabs an admin sees inside those screens (a screen not listed here keeps all its tabs)
ADMIN_TABS = {"cases": {"list", "teams", "reminders"}}


def _sections(caps: dict[str, bool], level: str = "super") -> list[dict]:
    """Which screens this org gets. Driven by what its database can do, not by org name.
    The page groups them (js_boot.NAV): Home; Your work (Tickets, Conversations); Your team (People, Roles & access);
    Chat bot; Build (Flows); Settings. Tickets holds everything about tickets: the list, who handles which kind,
    the kinds, the rules in detail and the response times. An admin gets the day-to-day screens only (see the plan in
    docs/plan/dashboard-v2.md)."""
    sections: list[dict] = [{"key": "overview", "label": "Home"}]
    if caps.get("cases"):
        tabs = [{"key": "list", "label": "All tickets"}]
        if caps.get("case_model"):
            tabs += [
                {"key": "teams", "label": "Who handles what"},
                *(
                    [{"key": "reminders", "label": "Reminders"}]
                    if caps.get("tat_clock")
                    else []
                ),
                {"key": "categories", "label": "Kinds of ticket"},
                {"key": "rules", "label": "Rules in detail"},
            ]
        if caps.get("targets"):
            tabs.append({"key": "times", "label": "Response times"})
        sections.append({"key": "cases", "label": "Tickets", "tabs": tabs})
    if caps.get("audit"):
        sections.append({"key": "conversations", "label": "Conversations"})
    sections.append({"key": "people", "label": "People"})
    access_tabs = [{"key": "roles", "label": "Roles"}]
    if caps.get("seats"):
        access_tabs.append({"key": "seats", "label": "Seats"})
    if caps.get("grants"):
        access_tabs.append({"key": "special", "label": "Special access"})
    sections.append({"key": "access", "label": "Roles & access", "tabs": access_tabs})
    assistant_tabs = []
    if caps.get("texts"):
        assistant_tabs.append({"key": "messages", "label": "Messages"})
    if caps.get("prompts"):
        assistant_tabs.append({"key": "instructions", "label": "AI notes"})
    if caps.get("cases"):
        assistant_tabs.append({"key": "whatsapp", "label": "WhatsApp Flows"})
        assistant_tabs.append({"key": "templates", "label": "Message templates"})
    assistant_tabs.append({"key": "menu", "label": "Menu"})
    if assistant_tabs:
        sections.append(
            {"key": "assistant", "label": "Chat bot", "tabs": assistant_tabs}
        )
    sections.append({"key": "workflows", "label": "Flows"})
    if caps.get("workflow_kind"):
        sections.append({"key": "blocks", "label": "Building blocks"})
    if caps.get("usecases"):
        sections.append({"key": "usecases", "label": "Use cases"})
    settings: dict = {"key": "settings", "label": "Settings"}
    if caps.get("events") or caps.get("audit"):
        settings["tabs"] = [
            {"key": "general", "label": "Settings"},
            {"key": "history", "label": "History of changes"},
        ]
    sections.append(settings)
    if level != "super":
        sections = [dict(s) for s in sections if s["key"] in ADMIN_SECTIONS]
        for s in sections:
            if s.get("tabs") and s["key"] in ADMIN_TABS:
                s["tabs"] = [t for t in s["tabs"] if t["key"] in ADMIN_TABS[s["key"]]]
    return sections


async def _labels(ctx) -> dict[str, str]:
    """The organisation's own word for a stored value, from orgs.settings -> labels, for example
    {"not_residing": "Moved out"}. The dashboard shows these instead of the stored value made readable.
    They are a courtesy: a missing or odd setting, or a database without settings, gives nothing."""
    try:
        row = await fetch_one(
            "SELECT settings FROM orgs WHERE id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    except Exception as e:
        logger.warning(f"labels not read: {e!r}")
        return {}
    settings = row["settings"] if row else None
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except ValueError:
            return {}
    found = settings.get("labels") if isinstance(settings, dict) else None
    if not isinstance(found, dict):
        return {}
    return {
        str(k): v.strip()
        for k, v in list(found.items())[:200]
        if isinstance(v, str) and v.strip() and len(v.strip()) <= 80
    }


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
        "sections": _sections(ctx.caps, ctx.level),
        "me": {
            "name": ctx.account_name,
            "email": ctx.account_email,
            "level": ctx.level,
        },
        "buttons": {"assign": await assign_state(ctx)},
        "labels": await _labels(ctx),
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
    usecases: list[dict] = []
    people: dict[str, list] = {}
    if ctx.caps.get(
        "usecases"
    ):  # the use cases and the kinds of people on each kind of record (all data)
        usecases = rows(
            await fetch_all(
                "SELECT id, key, name, icon, record_type, keeps_photos, is_active FROM usecases "
                "WHERE org_id = $1 ORDER BY sort_order, name",
                ctx.org_id,
                source_key=ctx.source_key,
            )
        )
        for k in rows(
            await fetch_all(
                "SELECT record_type, key, label, description, meaning, added FROM record_people_kinds "
                "WHERE org_id = $1 AND is_active ORDER BY record_type, sort_order, label",
                ctx.org_id,
                source_key=ctx.source_key,
            )
        ):
            people.setdefault(k.pop("record_type"), []).append(k)
    return {
        "roles": roles,
        "workflows": workflows,
        "seats": seats,
        "categories": categories,
        "enums": enums,
        "usecases": usecases,
        "people_kinds": people,
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
