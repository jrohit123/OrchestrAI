"""Workflows: which exist, who may use them, on/off. What a workflow DOES is still edited
through the chat builder; this screen never rewrites steps."""

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
)
from app.db import execute, fetch_all, fetch_one

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


def _kind_columns(ctx: Ctx) -> str:
    if ctx.caps.get("workflow_kind"):
        return "w.kind, w.settings"
    return "'workflow'::text AS kind, '{}'::jsonb AS settings"


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
    for w in found:
        steps = jb(w.pop("steps"), []) or []
        w["step_count"] = len(steps)
        w["settings"] = jb(w["settings"], {})
        # the live source of truth for access is "which roles list this intent_key"
        w["granted_roles"] = [
            r["name"] for r in roles if w["intent_key"] in (r["permissions"] or [])
        ]
    return {
        "rows": found,
        "roles": [{"id": r["id"], "name": r["name"]} for r in roles],
    }


@router.get("/workflows/{workflow_id}")
async def workflow_detail(ctx: CtxDep, workflow_id: UUID):
    w = await fetch_one(
        "SELECT id, name, intent_key, description, workflow_type, steps, gates, "
        "entity_schema, training_phrases FROM workflows WHERE id = $1 AND org_id = $2",
        workflow_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not w:
        raise HTTPException(status_code=404, detail="Workflow not found")
    d = dict(w)
    for col, default in (
        ("steps", []),
        ("gates", []),
        ("entity_schema", {}),
        ("training_phrases", []),
    ):
        d[col] = jb(d[col], default)
    return d


class ActiveBody(BaseModel):
    is_active: bool


@router.post("/workflows/{workflow_id}/active")
async def set_active(ctx: CtxDep, workflow_id: UUID, body: ActiveBody):
    """Switch a workflow on or off (off = hidden from the menu and the assistant). Uses the
    same function as the classic dashboard, so role grants are kept in step."""
    from app.services.workflow_publisher import set_workflow_active

    row = await fetch_one(
        "SELECT name, is_active FROM workflows WHERE id = $1 AND org_id = $2",
        workflow_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
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
async def set_roles(ctx: CtxDep, workflow_id: UUID, body: RolesBody):
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
async def delete_workflow(ctx: CtxDep, workflow_id: UUID):
    from app.services.workflow_publisher import sync_role_grants

    w = await fetch_one(
        "SELECT name, intent_key, steps FROM workflows WHERE id = $1 AND org_id = $2",
        workflow_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not w:
        raise HTTPException(status_code=404, detail="Workflow not found")
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
    )
    return {"ok": True}
