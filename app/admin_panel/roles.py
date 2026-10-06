"""Roles: a name, what the people who hold it may start (flows), what the assistant may look up
for them, and whether they may approve.

Everything here edits configuration rows of `roles`. What a role MEANS is decided where flows and
the assistant read it, so there is no business wording and no role name in this code. Two things
are asked of the database instead of being listed here:

  * a role is "built in" when a database function mentions it by name (for example a trigger that
    moves people between two roles), because renaming or deleting it would break that function;
  * a role cannot be deleted while people, special access or routing rules still point at it.
"""

import json
import re
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.admin_panel.common import Ctx, CtxDep, PanelRoute, jb, log_event, rows, tx
from app.db import fetch_all, fetch_one

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

_NAME = re.compile(r"^[^\x00-\x1f]{2,40}$")
_MAX_MONEY = Decimal("9999999999.99")
# tables that belong to the platform itself: never offered as "data the assistant may look up"
_PLATFORM_TABLES = {
    "access_grants",
    "admin_events",
    "orgs",
    "prompts",
    "roles",
    "schema_migrations",
    "system_messages",
    "user_drafts",
    "workflow_versions",
}


def clean_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if not _NAME.match(name):
        raise HTTPException(
            status_code=400, detail="Give the role a name of 2 to 40 characters."
        )
    return name


async def _flows(ctx: Ctx) -> list[dict]:
    kind = "kind" if ctx.caps.get("workflow_kind") else "'workflow'::text AS kind"
    found = rows(
        await fetch_all(
            "SELECT id, intent_key, name, description, is_active, entity_schema, steps, "
            f"{kind} FROM workflows WHERE org_id = $1 ORDER BY created_at",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    for f in found:
        f["entity_schema"] = jb(f["entity_schema"], {})
        f["steps"] = jb(f["steps"], [])
    return found


async def _database_rules(ctx: Ctx) -> list[tuple[str, str]]:
    """(function name, its text) for every database function that works with the roles table."""
    found = await fetch_all(
        "SELECT p.proname, p.prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.prosrc ~* '\\mroles\\M'",
        source_key=ctx.source_key,
    )
    return [(r["proname"], r["prosrc"]) for r in found]


def _built_in_by(name: str, rules: list[tuple[str, str]]) -> str | None:
    for fn, src in rules:
        if f"'{name}'" in src:
            return fn
    return None


async def _gate_users(ctx: Ctx, name: str) -> list[str]:
    """Flows whose safeguards (gates) name this role."""
    found = await fetch_all(
        "SELECT name FROM workflows WHERE org_id = $1 AND position($2 in gates::text) > 0",
        ctx.org_id,
        json.dumps(name, ensure_ascii=False),
        source_key=ctx.source_key,
    )
    return [r["name"] for r in found]


async def _in_use(ctx: Ctx, role_id) -> dict:
    """What still points at a role: people, special access, routing rules."""
    users = await fetch_one(
        "SELECT count(*) AS n FROM users WHERE role_id = $1",
        role_id,
        source_key=ctx.source_key,
    )
    grants = rules = 0
    if ctx.caps.get("grants"):
        grants = (
            await fetch_one(
                "SELECT count(*) AS n FROM access_grants WHERE role_id = $1",
                role_id,
                source_key=ctx.source_key,
            )
        )["n"]
    if ctx.caps.get("routing"):
        rules = (
            await fetch_one(
                "SELECT count(*) AS n FROM routing_rules "
                "WHERE assign_role_id = $1 OR backup_role_id = $1",
                role_id,
                source_key=ctx.source_key,
            )
        )["n"]
    return {"people": users["n"], "grants": grants, "rules": rules}


def _delete_reason(use: dict) -> str | None:
    bits = []
    if use["people"]:
        bits.append(
            f"{use['people']} {'person has' if use['people'] == 1 else 'people have'} this role"
        )
    if use["grants"]:
        bits.append(
            f"{use['grants']} special access entr{'y uses' if use['grants'] == 1 else 'ies use'} it"
        )
    if use["rules"]:
        bits.append(
            f"{use['rules']} routing rule{' uses' if use['rules'] == 1 else 's use'} it"
        )
    return ("; ".join(bits) + ".") if bits else None


async def _tables_available(ctx: Ctx) -> list[str]:
    from app.services.schema_utils import get_business_schema

    schema = await get_business_schema(ctx.source_key)
    return sorted(t for t in schema if t not in _PLATFORM_TABLES)


def _tables_needed(flow: dict) -> set[str]:
    from app.services.workflow_publisher import (
        _referenced_entity_types,
        _referenced_tables,
    )

    need = set(_referenced_tables(flow["entity_schema"]))
    if _referenced_entity_types(flow["entity_schema"]):
        need.add("entity_records")
    return need


@router.get("/roles")
async def list_roles(ctx: CtxDep):
    ctx.need("role_editor")
    found = rows(
        await fetch_all(
            "SELECT id, name, permissions, readable_tables, readable_entity_types, is_approver, "
            "approval_max_amount, created_at FROM roles WHERE org_id = $1 ORDER BY name",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    flows = [f for f in await _flows(ctx) if f["kind"] != "block"]
    flow_keys = {f["intent_key"] for f in flows}
    rules = await _database_rules(ctx)
    people: dict = {}
    for p in await fetch_all(
        "SELECT role_id, name FROM users WHERE org_id = $1 ORDER BY name",
        ctx.org_id,
        source_key=ctx.source_key,
    ):
        people.setdefault(p["role_id"], []).append(p["name"])
    shaped = []
    for r in found:
        held = list(r["permissions"] or [])
        use = await _in_use(ctx, r["id"])
        built_in = _built_in_by(r["name"], rules)
        shaped.append(
            {
                "id": r["id"],
                "name": r["name"],
                "can": [k for k in held if k in flow_keys],
                "other_permissions": [k for k in held if k not in flow_keys],
                "tables": list(r["readable_tables"] or []),
                "entity_types": list(r["readable_entity_types"] or []),
                "is_approver": r["is_approver"],
                "approval_max_amount": (
                    float(r["approval_max_amount"])
                    if r["approval_max_amount"] is not None
                    else None
                ),
                "people_count": use["people"],
                "people": people.get(r["id"], [])[:8],
                "built_in": built_in is not None,
                "built_in_by": built_in,
                "delete_blocked": (
                    "A database rule uses this role by its name."
                    if built_in
                    else _delete_reason(use)
                ),
            }
        )
    return {
        "roles": shaped,
        "flows": [
            {
                "id": f["id"],
                "intent_key": f["intent_key"],
                "name": f["name"],
                "description": f["description"],
                "is_active": f["is_active"],
                "needs_tables": sorted(_tables_needed(f)),
            }
            for f in flows
        ],
        "tables": await _tables_available(ctx),
    }


# ── changing roles ───────────────────────────────────────────────────────────


class RoleBody(BaseModel):
    name: str
    copy_from: UUID | None = None
    flows: list[str] | None = None
    tables: list[str] | None = None
    is_approver: bool | None = None
    approval_max_amount: Decimal | None = Field(None, ge=0)


class RolePatch(BaseModel):
    name: str | None = None
    flows: list[str] | None = None
    tables: list[str] | None = None
    is_approver: bool | None = None
    approval_max_amount: Decimal | None = Field(None, ge=0)


def _check_amount(value: Decimal | None) -> Decimal | None:
    if value is not None and value > _MAX_MONEY:
        raise HTTPException(status_code=400, detail="That amount is too large.")
    return value


async def _check_flows(ctx: Ctx, keys: list[str] | None) -> set[str] | None:
    if keys is None:
        return None
    known = {f["intent_key"] for f in await _flows(ctx) if f["kind"] != "block"}
    unknown = sorted(set(keys) - known)
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"Unknown flow: {', '.join(unknown)}."
        )
    return set(keys)


async def _check_tables(ctx: Ctx, names: list[str] | None) -> list[str] | None:
    if names is None:
        return None
    from app.services.schema_utils import get_business_schema

    known = set(await get_business_schema(ctx.source_key))
    unknown = sorted(set(names) - known)
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"Unknown data: {', '.join(unknown)}."
        )
    return sorted(set(names))


async def _name_taken(ctx: Ctx, name: str, except_id=None) -> bool:
    found = await fetch_one(
        "SELECT id FROM roles WHERE org_id = $1 AND lower(name) = lower($2) "
        "AND ($3::uuid IS NULL OR id <> $3)",
        ctx.org_id,
        name,
        except_id,
        source_key=ctx.source_key,
    )
    return bool(found)


async def _apply_flows(ctx: Ctx, role_id, wanted: set[str]) -> None:
    """Make the role able to start exactly these flows, the same way ticking a box on a flow does:
    what each flow needs along the way (finer permissions, the data it reads) comes with it."""
    from app.services.workflow_publisher import sync_role_grants

    for f in [f for f in await _flows(ctx) if f["kind"] != "block"]:
        roles = await fetch_all(
            "SELECT id, name, permissions FROM roles WHERE org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
        mine = next(r for r in roles if r["id"] == role_id)
        has = f["intent_key"] in (mine["permissions"] or [])
        want = f["intent_key"] in wanted
        if has == want:
            continue
        names = [
            r["name"] for r in roles if f["intent_key"] in (r["permissions"] or [])
        ]
        desired = (
            names + [mine["name"]] if want else [n for n in names if n != mine["name"]]
        )
        await sync_role_grants(
            f["intent_key"],
            ctx.org_id,
            desired,
            ctx.source_key,
            entity_schema=f["entity_schema"],
            steps=f["steps"],
        )


async def _settle_tables(ctx: Ctx, role_id, requested: list[str] | None) -> None:
    """The data the role may look up: what was asked for, plus whatever the flows it can start read."""
    mine = await fetch_one(
        "SELECT permissions, readable_tables FROM roles WHERE id = $1",
        role_id,
        source_key=ctx.source_key,
    )
    held = set(mine["permissions"] or [])
    needed: set[str] = set()
    for f in await _flows(ctx):
        if f["kind"] != "block" and f["intent_key"] in held:
            needed |= _tables_needed(f)
    base = (
        set(requested) if requested is not None else set(mine["readable_tables"] or [])
    )
    final = sorted(base | needed)
    if final != sorted(mine["readable_tables"] or []):
        async with tx(ctx) as conn:
            await conn.execute(
                "UPDATE roles SET readable_tables = $1::text[] WHERE id = $2",
                final,
                role_id,
            )


async def _summary(ctx: Ctx, role_id) -> dict:
    r = await fetch_one(
        "SELECT name, permissions, readable_tables, is_approver, approval_max_amount "
        "FROM roles WHERE id = $1",
        role_id,
        source_key=ctx.source_key,
    )
    flow_keys = {f["intent_key"] for f in await _flows(ctx) if f["kind"] != "block"}
    return {
        "name": r["name"],
        "flows": sorted(k for k in (r["permissions"] or []) if k in flow_keys),
        "tables": list(r["readable_tables"] or []),
        "is_approver": r["is_approver"],
        "approval_max_amount": (
            float(r["approval_max_amount"])
            if r["approval_max_amount"] is not None
            else None
        ),
    }


@router.post("/roles")
async def create_role(ctx: CtxDep, body: RoleBody):
    ctx.need("role_editor")
    name = clean_name(body.name)
    if await _name_taken(ctx, name):
        raise HTTPException(
            status_code=409, detail=f"There is already a role called “{name}”."
        )
    wanted = await _check_flows(ctx, body.flows)
    tables = await _check_tables(ctx, body.tables)
    _check_amount(body.approval_max_amount)
    base = None
    if body.copy_from:
        base = await fetch_one(
            "SELECT permissions, readable_tables, readable_entity_types, is_approver, "
            "approval_max_amount FROM roles WHERE id = $1 AND org_id = $2",
            body.copy_from,
            ctx.org_id,
            source_key=ctx.source_key,
        )
        if not base:
            raise HTTPException(
                status_code=404, detail="The role to copy from is gone."
            )
    approver = (
        body.is_approver
        if body.is_approver is not None
        else (base["is_approver"] if base else False)
    )
    amount = (
        body.approval_max_amount
        if body.is_approver is not None or body.approval_max_amount is not None
        else (base["approval_max_amount"] if base else None)
    )
    async with tx(ctx) as conn:
        new_id = await conn.fetchval(
            "INSERT INTO roles (org_id, name, permissions, readable_tables, "
            "readable_entity_types, is_approver, approval_max_amount) "
            "VALUES ($1, $2, $3::text[], $4::text[], $5::text[], $6, $7) RETURNING id",
            ctx.org_id,
            name,
            list(base["permissions"] or []) if base else [],
            list(base["readable_tables"] or []) if base else [],
            list(base["readable_entity_types"] or []) if base else [],
            bool(approver),
            amount if approver else None,
        )
    if wanted is not None:
        await _apply_flows(ctx, new_id, wanted)
    await _settle_tables(ctx, new_id, tables)
    after = await _summary(ctx, new_id)
    await log_event(
        ctx,
        "roles",
        "create",
        f"Made the role “{name}”"
        + (" as a copy of another role" if body.copy_from else ""),
        target_type="role",
        target_id=new_id,
        after=after,
    )
    return {"ok": True, "id": new_id}


@router.patch("/roles/{role_id}")
async def update_role(ctx: CtxDep, role_id: UUID, body: RolePatch):
    ctx.need("role_editor")
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    role = await fetch_one(
        "SELECT id, name FROM roles WHERE id = $1 AND org_id = $2",
        role_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    before = await _summary(ctx, role_id)
    wanted = await _check_flows(ctx, changes.get("flows"))
    tables = await _check_tables(ctx, changes.get("tables"))
    _check_amount(changes.get("approval_max_amount"))
    new_name = clean_name(changes["name"]) if "name" in changes else role["name"]
    if new_name != role["name"]:
        built_in = _built_in_by(role["name"], await _database_rules(ctx))
        if built_in:
            raise HTTPException(
                status_code=409,
                detail=f"“{role['name']}” cannot be renamed: a database rule moves people "
                "into and out of it by that name.",
            )
        if await _name_taken(ctx, new_name, role_id):
            raise HTTPException(
                status_code=409, detail=f"There is already a role called “{new_name}”."
            )
        used = await _gate_users(ctx, role["name"])
        if used:
            raise HTTPException(
                status_code=409,
                detail=f"{', '.join(used)} name{'s' if len(used) == 1 else ''} this role in "
                "its safeguards, so renaming it would break "
                f"{'that flow' if len(used) == 1 else 'those flows'}. Change that first.",
            )
        async with tx(ctx) as conn:
            await conn.execute(
                "UPDATE roles SET name = $1 WHERE id = $2", new_name, role_id
            )
    if "is_approver" in changes or "approval_max_amount" in changes:
        cur = await fetch_one(
            "SELECT is_approver, approval_max_amount FROM roles WHERE id = $1",
            role_id,
            source_key=ctx.source_key,
        )
        approver = (
            changes["is_approver"]
            if changes.get("is_approver") is not None
            else cur["is_approver"]
        )
        amount = (
            changes["approval_max_amount"]
            if "approval_max_amount" in changes
            else cur["approval_max_amount"]
        )
        async with tx(ctx) as conn:
            await conn.execute(
                "UPDATE roles SET is_approver = $1, approval_max_amount = $2 WHERE id = $3",
                bool(approver),
                amount if approver else None,
                role_id,
            )
    if wanted is not None:
        await _apply_flows(ctx, role_id, wanted)
    if tables is not None or wanted is not None:
        await _settle_tables(ctx, role_id, tables)
    after = await _summary(ctx, role_id)
    await log_event(
        ctx,
        "roles",
        "update",
        f"Changed the role “{new_name}”",
        target_type="role",
        target_id=role_id,
        before=before,
        after=after,
    )
    return {"ok": True}


@router.delete("/roles/{role_id}")
async def delete_role(ctx: CtxDep, role_id: UUID):
    ctx.need("role_editor")
    role = await fetch_one(
        "SELECT id, name FROM roles WHERE id = $1 AND org_id = $2",
        role_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if _built_in_by(role["name"], await _database_rules(ctx)):
        raise HTTPException(
            status_code=409,
            detail=f"“{role['name']}” cannot be deleted: a database rule uses it by its name.",
        )
    reason = _delete_reason(await _in_use(ctx, role_id))
    if reason:
        raise HTTPException(
            status_code=409,
            detail=f"“{role['name']}” cannot be deleted yet. {reason} Move them first.",
        )
    used = await _gate_users(ctx, role["name"])
    if used:
        raise HTTPException(
            status_code=409,
            detail=f"“{role['name']}” is named in the safeguards of {', '.join(used)}. "
            "Change that first.",
        )
    before = await _summary(ctx, role_id)
    async with tx(ctx) as conn:
        await conn.execute("DELETE FROM roles WHERE id = $1", role_id)
    await log_event(
        ctx,
        "roles",
        "delete",
        f"Deleted the role “{role['name']}”",
        target_type="role",
        target_id=role_id,
        before=before,
    )
    return {"ok": True}
