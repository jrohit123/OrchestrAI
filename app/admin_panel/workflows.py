"""Workflows: which exist, who may use them, on/off, and where building blocks are used.
Editing what a workflow does lives in studio.py."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.admin_panel.common import (
    Ctx,
    CtxDep,
    PanelRoute,
    jb,
    log_event,
    rows,
    tx,
)
from app.db import execute, fetch_all, fetch_one
from app.services.step_catalog import aliases_made_by, normalize_steps, used_blocks

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


def _kind_columns(ctx: Ctx) -> str:
    if ctx.caps.get("workflow_kind"):
        return "w.kind, w.settings"
    return "'workflow'::text AS kind, '{}'::jsonb AS settings"


async def where_used(ctx: Ctx, intent_key: str, exclude_id=None) -> list[dict]:
    """Workflows (name, id, active) that run this one as a building block."""
    found = await fetch_all(
        "SELECT id, name, intent_key, is_active, steps FROM workflows WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return [
        {
            "id": w["id"],
            "name": w["name"],
            "intent_key": w["intent_key"],
            "is_active": w["is_active"],
        }
        for w in found
        if w["id"] != exclude_id and intent_key in used_blocks(jb(w["steps"], []))
    ]


@router.get("/workflows")
async def list_workflows(ctx: CtxDep):
    made = (
        "(SELECT count(*) FROM cases c WHERE c.workflow_id = w.id)"
        if ctx.caps.get("cases")
        else "0"
    )
    found = rows(
        await fetch_all(
            "SELECT w.id, w.name, w.intent_key, w.description, w.is_active, "
            "w.workflow_type, w.last_run, w.created_at, w.slash_command, w.menu_section, "
            f"w.version, w.steps, {_kind_columns(ctx)}, {made} AS cases_made "
            "FROM workflows w WHERE w.org_id = $1 ORDER BY w.created_at",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    roles = rows(
        await fetch_all(
            "SELECT id, name, permissions FROM roles WHERE org_id = $1 ORDER BY name",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    names = {w["intent_key"]: w["name"] for w in found}
    used_in: dict[str, list[dict]] = {}
    for w in found:
        steps = normalize_steps(jb(w.pop("steps"), []))
        w["step_count"] = len(steps)
        w["settings"] = jb(w["settings"], {})
        w["makes"] = aliases_made_by(steps)
        w["uses"] = [
            {"intent_key": k, "name": names.get(k, k)} for k in used_blocks(steps)
        ]
        for k in used_blocks(steps):
            used_in.setdefault(k, []).append({"id": w["id"], "name": w["name"]})
        # the live source of truth for access is "which roles list this intent_key"
        w["granted_roles"] = [
            r["name"] for r in roles if w["intent_key"] in (r["permissions"] or [])
        ]
    for w in found:
        w["used_in"] = used_in.get(w["intent_key"], [])
    return {
        "rows": found,
        "roles": [{"id": r["id"], "name": r["name"]} for r in roles],
    }


class ActiveBody(BaseModel):
    is_active: bool


@router.post("/workflows/{workflow_id}/active")
async def set_active(workflow_id: UUID, body: ActiveBody, ctx: CtxDep):
    """Switch a workflow on or off (off = hidden from the menu and the assistant). Uses the
    same function as the classic dashboard, so role grants are kept in step."""
    from app.services.workflow_publisher import set_workflow_active

    row = await fetch_one(
        "SELECT name, intent_key, is_active FROM workflows WHERE id = $1 AND org_id = $2",
        workflow_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not body.is_active:
        live = [
            u
            for u in await where_used(ctx, row["intent_key"], workflow_id)
            if u["is_active"]
        ]
        if live:
            raise HTTPException(
                status_code=409,
                detail=f"'{row['name']}' is a building block used by "
                f"{', '.join(u['name'] for u in live)}. Those would stop working. "
                "Change them first.",
            )
    if row["is_active"] != body.is_active:
        await set_workflow_active(str(workflow_id), body.is_active, ctx.source_key)
        await log_event(
            ctx,
            "workflows",
            "on" if body.is_active else "off",
            f"Turned workflow '{row['name']}' {'on' if body.is_active else 'off'}",
            target_type="workflow",
            target_id=workflow_id,
        )
    return {"ok": True, "is_active": body.is_active}


class RolesBody(BaseModel):
    roles: list[str]


@router.put("/workflows/{workflow_id}/roles")
async def set_roles(workflow_id: UUID, body: RolesBody, ctx: CtxDep):
    """Set exactly which roles may use a workflow (same function the classic dashboard
    uses, so the tables it reads are granted too)."""
    from app.services.workflow_publisher import sync_role_grants

    w = await fetch_one(
        "SELECT name, intent_key, entity_schema, steps FROM workflows "
        "WHERE id = $1 AND org_id = $2",
        workflow_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not w:
        raise HTTPException(status_code=404, detail="Workflow not found")
    known = {
        r["name"]
        for r in await fetch_all(
            "SELECT name FROM roles WHERE org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    }
    unknown = [r for r in body.roles if r not in known]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"Unknown role: {', '.join(unknown)}"
        )
    if body.roles and ctx.caps.get("workflow_kind"):
        kind = await fetch_one(
            "SELECT kind FROM workflows WHERE id = $1",
            workflow_id,
            source_key=ctx.source_key,
        )
        if kind and kind["kind"] == "block":
            raise HTTPException(
                status_code=400,
                detail="A building block is only used by other workflows, so it is not "
                "given to roles. Give the workflow that runs it instead.",
            )
    await sync_role_grants(
        w["intent_key"],
        ctx.org_id,
        body.roles,
        ctx.source_key,
        entity_schema=w["entity_schema"],
        steps=w["steps"],
    )
    await log_event(
        ctx,
        "workflows",
        "access",
        f"'{w['name']}' can now be used by: {', '.join(body.roles) or 'nobody'}",
        target_type="workflow",
        target_id=workflow_id,
        after={"roles": body.roles},
    )
    return {"ok": True}


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: UUID, ctx: CtxDep):
    from app.admin_panel.studio import _snapshot
    from app.services.workflow_publisher import sync_role_grants

    w = await fetch_one(
        "SELECT * FROM workflows WHERE id = $1 AND org_id = $2",
        workflow_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not w:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if w["is_active"]:
        raise HTTPException(
            status_code=409,
            detail=f"'{w['name']}' is switched on, so people can use it right now. "
            "Switch it off first. You can switch it back on if something goes wrong.",
        )
    users = await where_used(ctx, w["intent_key"], workflow_id)
    if users:
        raise HTTPException(
            status_code=409,
            detail=f"'{w['name']}' is a building block used by "
            f"{', '.join(u['name'] for u in users)}. Remove it from those first.",
        )
    if ctx.caps.get("cases"):
        made = await fetch_one(
            "SELECT count(*) AS n FROM cases WHERE workflow_id = $1",
            workflow_id,
            source_key=ctx.source_key,
        )
        if made["n"]:
            raise HTTPException(
                status_code=409,
                detail=f"{made['n']} case(s) were created by '{w['name']}', so it cannot "
                "be deleted. Turn it off instead.",
            )
    # keep a copy first: the history table has no link to workflows, so it outlives the delete
    async with tx(ctx) as conn:
        await _snapshot(conn, ctx, w, old=True)
    # revoke from every role first, the same way the classic dashboard does
    await sync_role_grants(
        w["intent_key"], ctx.org_id, [], ctx.source_key, steps=w["steps"]
    )
    await execute(
        "DELETE FROM workflows WHERE id = $1", workflow_id, source_key=ctx.source_key
    )
    await log_event(
        ctx,
        "workflows",
        "delete",
        f"Deleted workflow '{w['name']}'",
        target_type="workflow",
        target_id=workflow_id,
        before=dict(w),  # the whole row, so it can be recreated exactly
    )
    return {"ok": True}
