"""How a flow starts: on a schedule, or after another flow. (A flow people start from the menu, a
phrase, a /command or a button is the plain case and needs nothing stored here.)

A flow is started in exactly one of the three ways, so choosing one takes the others away. The
rules, the times and the running of it live in app/services/flow_triggers.py; this file is the
dashboard's door to them. Only a super admin may use these calls (access_rules.py)."""

import datetime as dt
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.admin_panel.common import Ctx, CtxDep, PanelRoute, dump, jb, log_event, rows
from app.db import execute, fetch_all, fetch_one
from app.services import flow_triggers as ft

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


async def _flow(ctx: Ctx, workflow_id: UUID) -> dict:
    w = await fetch_one(
        "SELECT * FROM workflows WHERE id = $1 AND org_id = $2",
        workflow_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not w:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return dict(w)


async def how_flows_start(ctx: Ctx) -> dict[str, dict]:
    """For the Flows list: {workflow id: {kind, words}} for every flow that does not simply wait for
    a person. A flow that is not in it is started by a person."""
    if not ctx.caps.get("flow_triggers"):
        return {}
    out: dict[str, dict] = {}
    names = {
        str(r["id"]): r["name"]
        for r in await fetch_all(
            "SELECT id, name FROM workflows WHERE org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    }
    for s in await fetch_all(
        "SELECT workflow_id, cadence, is_active FROM flow_schedules WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    ):
        words = ft.cadence_words(jb(s["cadence"], {}))
        out[str(s["workflow_id"])] = {
            "kind": "schedule",
            "words": words if s["is_active"] else words + " (paused)",
        }
    for c in await fetch_all(
        "SELECT workflow_id, after_workflow_id FROM flow_chains WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    ):
        out[str(c["workflow_id"])] = {
            "kind": "after_flow",
            "words": "After “"
            + names.get(str(c["after_workflow_id"]), "another flow")
            + "”",
        }
    return out


async def _descendants(ctx: Ctx, workflow_id) -> set[str]:
    """The flows that run, directly or through others, after this one."""
    links = await fetch_all(
        "SELECT workflow_id, after_workflow_id FROM flow_chains WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    found: set[str] = set()
    todo = [str(workflow_id)]
    while todo:
        here = todo.pop()
        for r in links:
            if (
                str(r["after_workflow_id"]) == here
                and str(r["workflow_id"]) not in found
            ):
                found.add(str(r["workflow_id"]))
                todo.append(str(r["workflow_id"]))
    return found


@router.get("/workflows/{workflow_id}/schedule")
async def start_state(workflow_id: UUID, ctx: CtxDep):
    """Everything the 'How does it start' card shows for one flow."""
    w = await _flow(ctx, workflow_id)
    if not ctx.caps.get("flow_triggers"):
        return {"available": False, "kind": "people"}
    settings, tz = await ft._org_settings(ctx.source_key, ctx.org_id)
    sched = await fetch_one(
        "SELECT cadence, is_active, next_run_at, last_run_at FROM flow_schedules "
        "WHERE workflow_id = $1",
        workflow_id,
        source_key=ctx.source_key,
    )
    chain = await fetch_one(
        "SELECT a.id, a.name, a.intent_key, a.is_active FROM flow_chains c "
        "JOIN workflows a ON a.id = c.after_workflow_id WHERE c.workflow_id = $1",
        workflow_id,
        source_key=ctx.source_key,
    )
    skip = await _descendants(ctx, workflow_id)
    others = await fetch_all(
        "SELECT id, name, kind, workflow_type FROM workflows WHERE org_id = $1 AND id <> $2 "
        "ORDER BY name",
        ctx.org_id,
        workflow_id,
        source_key=ctx.source_key,
    )
    followers = await fetch_all(
        "SELECT w.id, w.name FROM flow_chains c JOIN workflows w ON w.id = c.workflow_id "
        "WHERE c.after_workflow_id = $1 ORDER BY w.name",
        workflow_id,
        source_key=ctx.source_key,
    )
    runs = await fetch_all(
        "SELECT how_started, status, message, started_at FROM flow_runs "
        "WHERE workflow_id = $1 ORDER BY started_at DESC LIMIT 10",
        workflow_id,
        source_key=ctx.source_key,
    )
    return {
        "available": True,
        "kind": "schedule" if sched else "after_flow" if chain else "people",
        "schedule": {
            "cadence": jb(sched["cadence"], {}),
            "words": ft.cadence_words(jb(sched["cadence"], {})),
            "is_active": sched["is_active"],
            "next_run_at": sched["next_run_at"],
            "last_run_at": sched["last_run_at"],
        }
        if sched
        else None,
        "after": rows([chain])[0] if chain else None,
        "followers": rows(followers),
        # the flows this one could follow: not itself, not a flow that already follows it, and only
        # flows that finish on their own (a building block never finishes by itself)
        "can_follow": [
            {"id": str(o["id"]), "name": o["name"]}
            for o in others
            if str(o["id"]) not in skip and (o["kind"] or "workflow") != "block"
        ],
        "problems": ft.unfit_reasons(w),
        "is_active": w["is_active"],
        "timezone": str(tz),
        "working_days": sorted(ft._working(settings)[0]),
        "runs": rows(runs),
    }


class CadenceBody(BaseModel):
    every: str
    time: str
    days: list[int] | None = Field(None, max_length=7)
    day_of_month: int | None = None
    working_days_only: bool = False


@router.put("/workflows/{workflow_id}/schedule")
async def set_schedule(workflow_id: UUID, body: CadenceBody, ctx: CtxDep):
    """Run this flow on a timer. It replaces 'after another flow' if that was chosen."""
    ctx.need("flow_triggers")
    w = await _flow(ctx, workflow_id)
    problems = ft.unfit_reasons(w)
    cadence, bad = ft.clean_cadence(body.model_dump())
    if problems or bad:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "It cannot run on a schedule yet:",
                "problems": problems + bad,
            },
        )
    settings, tz = await ft._org_settings(ctx.source_key, ctx.org_id)
    nxt = ft.next_run(cadence, dt.datetime.now(dt.timezone.utc), tz, settings)
    await execute(
        "DELETE FROM flow_chains WHERE workflow_id = $1",
        workflow_id,
        source_key=ctx.source_key,
    )
    await execute(
        "INSERT INTO flow_schedules (org_id, workflow_id, cadence, is_active, next_run_at, created_by) "
        "VALUES ($1, $2, $3::jsonb, true, $4, $5) "
        "ON CONFLICT (workflow_id) DO UPDATE SET cadence = EXCLUDED.cadence, is_active = true, "
        "next_run_at = EXCLUDED.next_run_at, updated_at = now()",
        ctx.org_id,
        workflow_id,
        dump(cadence),
        nxt,
        ctx.actor,
        source_key=ctx.source_key,
    )
    await log_event(
        ctx,
        "workflows",
        "schedule",
        f"'{w['name']}' now runs by itself: {ft.cadence_words(cadence)}",
        target_type="workflow",
        target_id=workflow_id,
        after={"cadence": cadence},
    )
    return {
        "ok": True,
        "words": ft.cadence_words(cadence),
        "next_run_at": nxt,
        "switched_off": not w["is_active"],
    }


@router.delete("/workflows/{workflow_id}/schedule")
async def remove_schedule(workflow_id: UUID, ctx: CtxDep):
    ctx.need("flow_triggers")
    w = await _flow(ctx, workflow_id)
    gone = await fetch_one(
        "DELETE FROM flow_schedules WHERE workflow_id = $1 RETURNING cadence",
        workflow_id,
        source_key=ctx.source_key,
    )
    if gone:
        await log_event(
            ctx,
            "workflows",
            "schedule",
            f"'{w['name']}' no longer runs on a schedule",
            target_type="workflow",
            target_id=workflow_id,
            before={"cadence": jb(gone["cadence"], {})},
        )
    return {"ok": True}


@router.post("/workflows/{workflow_id}/schedule/run")
async def run_now(workflow_id: UUID, ctx: CtxDep):
    """Run the flow once, now, as the System actor. The schedule is not moved."""
    ctx.need("flow_triggers")
    w = await _flow(ctx, workflow_id)
    if not await fetch_one(
        "SELECT 1 AS x FROM flow_schedules WHERE workflow_id = $1",
        workflow_id,
        source_key=ctx.source_key,
    ):
        raise HTTPException(
            status_code=409,
            detail="Set a schedule first. “Run it now” is for flows that run on a schedule.",
        )
    if not w["is_active"]:
        raise HTTPException(
            status_code=409,
            detail=f"“{w['name']}” is switched off. Switch it on first, then run it.",
        )
    result = await ft.run_flow(ctx.source_key, ctx.org_id, w, how="manual")
    await log_event(
        ctx,
        "workflows",
        "run",
        f"Ran '{w['name']}' now: {result['status']}",
        target_type="workflow",
        target_id=workflow_id,
        after=result,
    )
    return {"ok": True, **result}


class AfterBody(BaseModel):
    after_id: UUID


@router.put("/workflows/{workflow_id}/after")
async def set_after(workflow_id: UUID, body: AfterBody, ctx: CtxDep):
    """Start this flow when another flow finishes. It replaces a schedule if that was chosen."""
    ctx.need("flow_triggers")
    w = await _flow(ctx, workflow_id)
    parent = await _flow(ctx, body.after_id)
    problems = ft.unfit_reasons(w)
    if (parent.get("kind") or "workflow") == "block":
        problems.append(
            f"“{parent['name']}” is a building block. It never finishes on its own, so nothing can "
            "start after it. Choose the flow that runs it."
        )
    loop = await ft.chain_problem(
        ctx.source_key, ctx.org_id, workflow_id, body.after_id
    )
    if loop:
        problems.append(loop)
    if problems:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "It cannot start after that flow:",
                "problems": problems,
            },
        )
    await execute(
        "DELETE FROM flow_schedules WHERE workflow_id = $1",
        workflow_id,
        source_key=ctx.source_key,
    )
    await execute(
        "INSERT INTO flow_chains (org_id, workflow_id, after_workflow_id, created_by) "
        "VALUES ($1, $2, $3, $4) ON CONFLICT (workflow_id) DO UPDATE SET "
        "after_workflow_id = EXCLUDED.after_workflow_id",
        ctx.org_id,
        workflow_id,
        body.after_id,
        ctx.actor,
        source_key=ctx.source_key,
    )
    await log_event(
        ctx,
        "workflows",
        "after",
        f"'{w['name']}' now starts after '{parent['name']}' finishes",
        target_type="workflow",
        target_id=workflow_id,
        after={"after": parent["intent_key"]},
    )
    return {
        "ok": True,
        "words": "After “" + parent["name"] + "”",
        "switched_off": not w["is_active"],
    }


@router.delete("/workflows/{workflow_id}/after")
async def remove_after(workflow_id: UUID, ctx: CtxDep):
    ctx.need("flow_triggers")
    w = await _flow(ctx, workflow_id)
    gone = await fetch_one(
        "DELETE FROM flow_chains WHERE workflow_id = $1 RETURNING after_workflow_id",
        workflow_id,
        source_key=ctx.source_key,
    )
    if gone:
        await log_event(
            ctx,
            "workflows",
            "after",
            f"'{w['name']}' no longer starts after another flow",
            target_type="workflow",
            target_id=workflow_id,
        )
    return {"ok": True}
