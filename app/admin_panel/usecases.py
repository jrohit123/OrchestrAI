"""Use cases: what an organisation does with the chat bot (Tickets, Bookings, Visitors ...), and the kinds of people each
kind of record can have (Raised it, Handling it ...). Super admins only.

Where it lives (core-0027, filled for tickets by housing-0014):
  * usecases               name, icon, the kind of record it keeps (record_type), whether that record keeps photos
  * record_people_kinds    per kind of record: the kinds of people on it, with label, meaning, order, on/off
  * workflows.usecase_id   the use case a flow or building block is filed under (empty = shared)

A kind's key is what every record stores, so it never changes and is never deleted: a kind no longer wanted is switched
off. The kinds the system sets itself (who raised it, who handles it: added = false) keep their meaning and stay on;
their label and description can still change. Nothing here touches a record or anybody's access."""

import json
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.admin_panel.common import Ctx, CtxDep, PanelRoute, log_event, rows, tx
from app.db import fetch_all, fetch_one
from app.services import menu, people_kinds

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

MEANINGS = ("raiser", "handler", "backup", "informed", "other")
MAX_KINDS = 15
_KEY = re.compile(r"[^a-z0-9]+")


def _need(ctx: Ctx) -> None:
    if not ctx.caps.get("usecases"):
        raise HTTPException(
            409,
            "This organisation's database has no use cases yet. Run migration core-0027 first.",
        )


def _slug(text: str, prefix: str = "x") -> str:
    s = _KEY.sub("_", (text or "").lower()).strip("_")[:40]
    if not s or not s[0].isalpha():
        s = (prefix + "_" + s)[:40].rstrip("_")
    return s


# ───────────────────────── read ─────────────────────────


@router.get("/usecases")
async def list_usecases(ctx: CtxDep):
    if not ctx.caps.get("usecases"):
        return {"available": False, "usecases": [], "kinds": {}}
    found = rows(
        await fetch_all(
            "SELECT u.id, u.key, u.name, u.icon, u.description, u.record_type, u.keeps_photos, u.sort_order, u.is_active, "
            "(SELECT count(*) FROM workflows w WHERE w.usecase_id = u.id AND w.kind <> 'block') AS flows, "
            "(SELECT count(*) FROM workflows w WHERE w.usecase_id = u.id AND w.kind = 'block') AS blocks "
            "FROM usecases u WHERE u.org_id = $1 ORDER BY u.sort_order, u.name",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    kinds: dict[str, list] = {}
    for k in rows(
        await fetch_all(
            "SELECT record_type, key, label, description, meaning, added, sort_order, is_active, "
            "(SELECT count(*) FROM case_parties p WHERE p.party_role = k.key AND k.record_type = 'ticket' "
            " AND p.org_id = k.org_id) AS in_use "
            "FROM record_people_kinds k WHERE org_id = $1 ORDER BY record_type, sort_order, label",
            ctx.org_id,
            source_key=ctx.source_key,
        )
        if ctx.caps.get("parties")
        else await fetch_all(
            "SELECT record_type, key, label, description, meaning, added, sort_order, is_active, 0 AS in_use "
            "FROM record_people_kinds WHERE org_id = $1 ORDER BY record_type, sort_order, label",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    ):
        kinds.setdefault(k.pop("record_type"), []).append(k)
    return {
        "available": True,
        "usecases": found,
        "kinds": kinds,
        "meanings": list(MEANINGS),
    }


# ───────────────────────── use cases ─────────────────────────


class NewUsecase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    icon: str = Field(default="", max_length=8)
    description: str = Field(default="", max_length=200)
    record_type: str = Field(min_length=1, max_length=40)
    keeps_photos: StrictBool = False


class UsecasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=40)
    icon: str | None = Field(default=None, max_length=8)
    description: str | None = Field(default=None, max_length=200)
    keeps_photos: StrictBool | None = None
    is_active: StrictBool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=999)


@router.post("/usecases")
async def create_usecase(ctx: CtxDep, body: Annotated[NewUsecase, Body()]):
    _need(ctx)
    key, record = _slug(body.name, "u"), _slug(body.record_type, "r")
    async with tx(ctx) as conn:
        if await conn.fetchval(
            "SELECT 1 FROM usecases WHERE org_id = $1 AND key = $2", ctx.org_id, key
        ):
            raise HTTPException(
                409, f"There is already a use case called “{body.name.strip()}”."
            )
        order = await conn.fetchval(
            "SELECT coalesce(max(sort_order), 0) + 1 FROM usecases WHERE org_id = $1",
            ctx.org_id,
        )
        new_id = await conn.fetchval(
            "INSERT INTO usecases (org_id, key, name, icon, description, record_type, keeps_photos, sort_order) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
            ctx.org_id, key, body.name.strip(), body.icon.strip(), body.description.strip(), record,
            body.keeps_photos, order,
        )  # fmt: skip
        await log_event(
            ctx,
            "usecases",
            "create",
            f"Added the use case {body.name.strip()}",
            target_type="usecase",
            target_id=new_id,
            conn=conn,
        )
    return {"ok": True, "id": str(new_id), "key": key, "record_type": record}


@router.patch("/usecases/{usecase_id}")
async def update_usecase(
    ctx: CtxDep, usecase_id: UUID, body: Annotated[UsecasePatch, Body()]
):
    _need(ctx)
    changes = {
        k: (v.strip() if isinstance(v, str) else v)
        for k, v in body.model_dump(exclude_none=True).items()
    }
    if not changes:
        return {"ok": True}
    sets = ", ".join(f"{k} = ${i + 3}" for i, k in enumerate(changes))
    async with tx(ctx) as conn:
        done = await conn.fetchval(
            f"UPDATE usecases SET {sets} WHERE id = $1 AND org_id = $2 RETURNING name",
            usecase_id, ctx.org_id, *changes.values(),
        )  # fmt: skip
        if not done:
            raise HTTPException(404, "That use case is not here any more.")
        await log_event(
            ctx,
            "usecases",
            "update",
            f"Changed the use case {done}",
            target_type="usecase",
            target_id=usecase_id,
            after=changes,
            conn=conn,
        )
    return {"ok": True}


# ───────────────────────── kinds of people on a record ─────────────────────────


class Kind(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str | None = Field(default=None, max_length=40)
    label: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    meaning: str = "other"
    added: StrictBool = True
    is_active: StrictBool = True


class KindsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kinds: list[Kind] = Field(max_length=MAX_KINDS)


@router.put("/record-kinds/{record_type}")
async def save_kinds(ctx: CtxDep, record_type: str, body: Annotated[KindsBody, Body()]):
    """The whole list for one kind of record, in its order. Keys never change and are never deleted; the kinds the
    system sets itself keep their meaning and stay on."""
    _need(ctx)
    record = _slug(record_type, "r")
    for k in body.kinds:
        if k.meaning not in MEANINGS:
            raise HTTPException(
                422, f"“{k.label}”: its meaning must be one of {', '.join(MEANINGS)}."
            )
    labels = [k.label.strip().lower() for k in body.kinds]
    if len(set(labels)) != len(labels):
        raise HTTPException(422, "Two kinds of people have the same name.")
    async with tx(ctx) as conn:
        old = {
            r["key"]: dict(r)
            for r in await conn.fetch(
                "SELECT key, label, meaning, added, is_active FROM record_people_kinds WHERE org_id = $1 AND record_type = $2",
                ctx.org_id, record,
            )
        }  # fmt: skip
        sent = {k.key for k in body.kinds if k.key}
        missing = [o["label"] for key, o in old.items() if key not in sent]
        if missing:
            raise HTTPException(
                422,
                f"A kind is never deleted, only switched off: {', '.join(missing)} must stay in the list.",
            )
        used: set[str] = set()
        for i, k in enumerate(body.kinds, start=1):
            if k.key and k.key in old:
                was = old[k.key]
                if not was["added"] and (
                    k.meaning != was["meaning"] or not k.is_active or k.added
                ):
                    raise HTTPException(
                        422,
                        f"“{was['label']}” is set by the system, so only its name and description can change.",
                    )
                await conn.execute(
                    "UPDATE record_people_kinds SET label = $3, description = $4, meaning = $5, added = $6, is_active = $7, "
                    "sort_order = $8 WHERE org_id = $1 AND record_type = $2 AND key = $9",
                    ctx.org_id, record, k.label.strip(), k.description.strip(), k.meaning, k.added, k.is_active, i, k.key,
                )  # fmt: skip
                used.add(k.key)
                continue
            key = _slug(k.key or k.label, "k")
            while key in old or key in used:
                key = (key[:36] + "_" + str(len(used) + len(old) + 1))[:40]
            await conn.execute(
                "INSERT INTO record_people_kinds (org_id, record_type, key, label, description, meaning, added, is_active, sort_order) "
                "VALUES ($1, $2, $3, $4, $5, $6, true, $7, $8)",
                ctx.org_id, record, key, k.label.strip(), k.description.strip(), k.meaning, k.is_active, i,
            )  # fmt: skip
            used.add(key)
        await log_event(
            ctx,
            "usecases",
            "kinds",
            f"Changed the kinds of people on a {record}",
            target_type="record_type",
            target_id=None,
            after=[k.model_dump() for k in body.kinds],
            conn=conn,
        )
    people_kinds.invalidate()
    return {"ok": True}


# ───────────────────────── a flow's use case ─────────────────────────


class FlowUsecase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usecase_id: UUID | None = None


@router.put("/workflows/{workflow_id}/usecase")
async def set_flow_usecase(
    ctx: CtxDep, workflow_id: UUID, body: Annotated[FlowUsecase, Body()]
):
    _need(ctx)
    if body.usecase_id and not await fetch_one(
        "SELECT 1 FROM usecases WHERE id = $1 AND org_id = $2",
        body.usecase_id,
        ctx.org_id,
        source_key=ctx.source_key,
    ):
        raise HTTPException(404, "That use case is not here any more.")
    async with tx(ctx) as conn:
        name = await conn.fetchval(
            "UPDATE workflows SET usecase_id = $3 WHERE id = $1 AND org_id = $2 RETURNING name",
            workflow_id, ctx.org_id, body.usecase_id,
        )  # fmt: skip
        if not name:
            raise HTTPException(404, "That flow is not here any more.")
        await log_event(
            ctx,
            "workflows",
            "usecase",
            f"Filed {name} under another use case",
            target_type="workflow",
            target_id=workflow_id,
            after={"usecase_id": str(body.usecase_id) if body.usecase_id else None},
            conn=conn,
        )
    return {"ok": True}


# ───────────────────────── the chat menu, as one kind of person sees it ─────────────────────────


@router.get("/menu-preview")
async def menu_preview(ctx: CtxDep, role_id: UUID | None = None):
    """The chat menu the real code builds for someone with this role: the use cases that are on, with their flows that
    are on and that the role may use. It calls the same code the chat bot calls, so the preview cannot disagree."""
    roles = rows(
        await fetch_all(
            "SELECT id, name FROM roles WHERE org_id = $1 ORDER BY name",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    if not roles:
        return {"roles": [], "role_id": None, "groups": []}
    pick = next(
        (r for r in roles if role_id and str(r["id"]) == str(role_id)), roles[0]
    )
    got = await fetch_one(
        "SELECT permissions FROM roles WHERE id = $1 AND org_id = $2",
        pick["id"],
        ctx.org_id,
        source_key=ctx.source_key,
    )
    perms = got["permissions"] if got else []
    if isinstance(perms, str):
        try:
            perms = json.loads(perms)
        except ValueError:
            perms = []
    user = {
        "permissions": list(perms or []),
        "source_key": ctx.source_key,
        "org_id": ctx.org_id,
    }
    groups = await menu.menu_groups(ctx.org_id, user)
    return {
        "roles": roles,
        "role_id": str(pick["id"]),
        "groups": [
            {"title": g["title"], "flows": [w["name"] for w in g["flows"]]}
            for g in groups
        ],
    }
