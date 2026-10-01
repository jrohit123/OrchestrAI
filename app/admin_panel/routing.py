"""Routing: the categories a case can have and the rules that say who handles each kind.

These are rows an admin edits. The matching itself (which rule wins, who is available) is
done by the database function route_case(); nothing here decides it."""

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.admin_panel.cases import describe_route
from app.admin_panel.common import (
    Ctx,
    CtxDep,
    PanelRoute,
    check_choice,
    check_values,
    dump,
    jb,
    log_event,
    rows,
    tx,
)
from app.db import fetch_all, fetch_one

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


# ── categories ───────────────────────────────────────────────────────────────


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _clean_keywords(words: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for w in words:
        w = w.strip().lower()
        if w:
            seen[w[:40]] = None
    return list(seen)


def _clean_extra_fields(fields: list[dict]) -> list[dict]:
    """Questions a category asks on top of the usual ones. Only shape is checked here."""
    out = []
    for f in fields:
        key = str(f.get("key", "")).strip()
        label = str(f.get("label", "")).strip()
        if not re.fullmatch(r"[a-z0-9_]{1,40}", key) or not label:
            raise HTTPException(
                status_code=400,
                detail="Each extra question needs a short key (letters, digits, _) and a label.",
            )
        item = {
            "key": key,
            "label": label[:120],
            "type": str(f.get("type") or "text")[:20],
        }
        if isinstance(f.get("options"), list):
            item["options"] = [str(o)[:80] for o in f["options"] if str(o).strip()][:30]
        out.append(item)
    return out


class CategoryBody(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    parent_id: UUID | None = None
    default_priority: str | None = None
    target_minutes: int | None = Field(None, ge=1, le=525600)
    keywords: list[str] = Field(default_factory=list, max_length=40)
    extra_fields: list[dict] = Field(default_factory=list, max_length=12)
    is_active: bool = True


class CategoryPatch(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=80)
    parent_id: UUID | None = None
    default_priority: str | None = None
    target_minutes: int | None = Field(None, ge=1, le=525600)
    keywords: list[str] | None = Field(None, max_length=40)
    extra_fields: list[dict] | None = Field(None, max_length=12)
    is_active: bool | None = None


@router.get("/categories")
async def list_categories(ctx: CtxDep):
    ctx.need("case_model")
    cats = rows(
        await fetch_all(
            "SELECT id, parent_id, key, label, default_priority, target_minutes, keywords, "
            "extra_fields, is_active, sort_order FROM case_categories WHERE org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    counts = {
        r["category_id"]: r
        for r in await fetch_all(
            "SELECT category_id, count(*) AS total, "
            "count(*) FILTER (WHERE NOT (status = ANY($2::text[]))) AS open "
            "FROM cases WHERE org_id = $1 AND category_id IS NOT NULL GROUP BY 1",
            ctx.org_id,
            ctx.closed_values,
            source_key=ctx.source_key,
        )
    }
    rule_counts = {
        r["category_id"]: r["n"]
        for r in await fetch_all(
            "SELECT category_id, count(*) AS n FROM routing_rules "
            "WHERE org_id = $1 AND category_id IS NOT NULL GROUP BY 1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    }
    # has a catch-all rule? asked of the database function itself, not worked out here
    covered = {
        r["id"]: r["covered"]
        for r in await fetch_all(
            "SELECT k.id, EXISTS (SELECT 1 FROM route_case(k.org_id, k.id, '{}'::jsonb)) "
            "AS covered FROM case_categories k WHERE k.org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    }
    children: dict = {}
    for c in cats:
        c["keywords"] = list(c["keywords"] or [])
        c["extra_fields"] = jb(c["extra_fields"], [])
        children.setdefault(c["parent_id"], []).append(c)
    for kids in children.values():
        kids.sort(key=lambda c: (c["sort_order"], c["label"].lower()))

    ordered: list[dict] = []

    def walk(parent_id, depth: int) -> tuple[int, int]:
        total = open_ = 0
        for c in children.get(parent_id, []):
            idx = len(ordered)
            ordered.append(c)
            c["depth"] = depth
            own = counts.get(c["id"])
            c["cases_total_own"] = own["total"] if own else 0
            c["cases_open_own"] = own["open"] if own else 0
            c["rules"] = rule_counts.get(c["id"], 0)
            c["covered"] = covered.get(c["id"], False)
            sub_total, sub_open = walk(c["id"], depth + 1)
            c["cases_total"] = c["cases_total_own"] + sub_total
            c["cases_open"] = c["cases_open_own"] + sub_open
            c["children"] = len(children.get(c["id"], []))
            ordered[idx] = c
            total += c["cases_total"]
            open_ += c["cases_open"]
        return total, open_

    walk(None, 0)
    uncategorised = await fetch_one(
        "SELECT count(*) AS total, count(*) FILTER (WHERE NOT (status = ANY($2::text[]))) "
        "AS open FROM cases WHERE org_id = $1 AND category_id IS NULL",
        ctx.org_id,
        ctx.closed_values,
        source_key=ctx.source_key,
    )
    return {
        "rows": ordered,
        "uncategorised": dict(uncategorised) if uncategorised else {},
        "priorities": await check_values(ctx, "case_categories", "default_priority"),
    }


async def _check_priority(ctx: Ctx, value: str | None) -> None:
    if value:
        check_choice(
            value,
            await check_values(ctx, "case_categories", "default_priority"),
            "Priority",
        )


@router.post("/categories")
async def create_category(ctx: CtxDep, body: CategoryBody):
    ctx.need("case_model")
    await _check_priority(ctx, body.default_priority)
    slug = _slug(body.label)
    if not slug:
        raise HTTPException(
            status_code=400, detail="Give the category a name with letters."
        )
    async with tx(ctx) as conn:
        key = slug
        if body.parent_id:
            parent = await conn.fetchrow(
                "SELECT key FROM case_categories WHERE id = $1 AND org_id = $2",
                body.parent_id,
                ctx.org_id,
            )
            if not parent:
                raise HTTPException(
                    status_code=404, detail="Parent category not found."
                )
            key = f"{parent['key']}.{slug}"
        taken = await conn.fetchval(
            "SELECT 1 FROM case_categories WHERE org_id = $1 AND key = $2",
            ctx.org_id,
            key,
        )
        if taken:
            raise HTTPException(
                status_code=409,
                detail="A category with that name already exists there.",
            )
        order = await conn.fetchval(
            "SELECT COALESCE(max(sort_order), 0) + 10 FROM case_categories "
            "WHERE org_id = $1 AND parent_id IS NOT DISTINCT FROM $2",
            ctx.org_id,
            body.parent_id,
        )
        cat = await conn.fetchrow(
            "INSERT INTO case_categories (org_id, parent_id, key, label, default_priority, "
            "target_minutes, keywords, extra_fields, is_active, sort_order) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10) RETURNING id, key",
            ctx.org_id,
            body.parent_id,
            key,
            body.label.strip(),
            body.default_priority,
            body.target_minutes,
            _clean_keywords(body.keywords),
            dump(_clean_extra_fields(body.extra_fields)),
            body.is_active,
            order,
        )
        await log_event(
            ctx,
            "routing",
            "category_create",
            f"Created category '{body.label.strip()}'",
            target_type="category",
            target_id=cat["id"],
            conn=conn,
        )
    return {"ok": True, "id": cat["id"], "key": cat["key"]}


@router.patch("/categories/{category_id}")
async def update_category(ctx: CtxDep, category_id: UUID, body: CategoryPatch):
    ctx.need("case_model")
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    if changes.get("label") is None and "label" in changes:
        raise HTTPException(status_code=400, detail="A category needs a name.")
    if "is_active" in changes and changes["is_active"] is None:
        raise HTTPException(status_code=400, detail="Choose active or hidden.")
    await _check_priority(ctx, changes.get("default_priority"))
    if "keywords" in changes:
        changes["keywords"] = _clean_keywords(changes["keywords"] or [])
    if "extra_fields" in changes:
        changes["extra_fields"] = _clean_extra_fields(changes["extra_fields"] or [])
    if "label" in changes:
        changes["label"] = changes["label"].strip()
    async with tx(ctx) as conn:
        before = await conn.fetchrow(
            "SELECT label, parent_id, default_priority, target_minutes, is_active "
            "FROM case_categories WHERE id = $1 AND org_id = $2 FOR UPDATE",
            category_id,
            ctx.org_id,
        )
        if not before:
            raise HTTPException(status_code=404, detail="Category not found.")
        if changes.get("parent_id"):
            ok = await conn.fetchval(
                "SELECT 1 FROM case_categories WHERE id = $1 AND org_id = $2",
                changes["parent_id"],
                ctx.org_id,
            )
            if not ok:
                raise HTTPException(
                    status_code=404, detail="Parent category not found."
                )
        sets, args = [], []
        for col, val in changes.items():
            args.append(dump(val) if col == "extra_fields" else val)
            sets.append(
                f"{col} = ${len(args) + 1}"
                + ("::jsonb" if col == "extra_fields" else "")
            )
        await conn.execute(
            f"UPDATE case_categories SET {', '.join(sets)} WHERE id = $1",
            category_id,
            *args,
        )
        await log_event(
            ctx,
            "routing",
            "category_update",
            f"Changed category '{before['label']}'",
            target_type="category",
            target_id=category_id,
            before=dict(before),
            after=changes,
            conn=conn,
        )
    return {"ok": True}


@router.delete("/categories/{category_id}")
async def delete_category(ctx: CtxDep, category_id: UUID):
    ctx.need("case_model")
    async with tx(ctx) as conn:
        cat = await conn.fetchrow(
            "SELECT label FROM case_categories WHERE id = $1 AND org_id = $2",
            category_id,
            ctx.org_id,
        )
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found.")
        kids = await conn.fetchval(
            "SELECT count(*) FROM case_categories WHERE parent_id = $1", category_id
        )
        used = await conn.fetchval(
            "SELECT count(*) FROM cases WHERE category_id = $1", category_id
        )
        rules = await conn.fetchval(
            "SELECT count(*) FROM routing_rules WHERE category_id = $1", category_id
        )
        if kids or used or rules:
            parts = []
            if kids:
                parts.append(f"{kids} sub-categor{'y' if kids == 1 else 'ies'}")
            if used:
                parts.append(f"{used} case{'s' if used != 1 else ''}")
            if rules:
                parts.append(f"{rules} routing rule{'s' if rules != 1 else ''}")
            raise HTTPException(
                status_code=409,
                detail=f"'{cat['label']}' still has {', '.join(parts)}. "
                "Hide it instead, so history stays intact.",
            )
        await conn.execute("DELETE FROM case_categories WHERE id = $1", category_id)
        await log_event(
            ctx,
            "routing",
            "category_delete",
            f"Deleted category '{cat['label']}'",
            target_type="category",
            target_id=category_id,
            conn=conn,
        )
    return {"ok": True}


# ── routing rules ────────────────────────────────────────────────────────────


class Target(BaseModel):
    type: Literal["user", "seat", "role"]
    id: UUID


class RuleBody(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    category_id: UUID | None = None
    intent_key: str | None = Field(None, max_length=120)
    match: dict[str, str | int | float | bool] = Field(default_factory=dict)
    assign: Target
    backup: Target | None = None
    target_minutes: int | None = Field(None, ge=1, le=525600)
    is_active: bool = True


_TARGET_TABLES = {"user": "users", "seat": "committee_positions", "role": "roles"}


async def _target_columns(conn, ctx: Ctx, target: Target | None) -> tuple:
    """(user_id, position_id, role_id) for a rule's target, checking it exists here."""
    if target is None:
        return (None, None, None)
    found = await conn.fetchval(
        f"SELECT 1 FROM {_TARGET_TABLES[target.type]} WHERE id = $1 AND org_id = $2",
        target.id,
        ctx.org_id,
    )
    if not found:
        raise HTTPException(
            status_code=404, detail=f"That {target.type} no longer exists."
        )
    return (
        target.id if target.type == "user" else None,
        target.id if target.type == "seat" else None,
        target.id if target.type == "role" else None,
    )


@router.get("/rules")
async def list_rules(ctx: CtxDep):
    ctx.need("case_model")
    found = rows(
        await fetch_all(
            """
            SELECT ru.id, ru.name, ru.intent_key, ru.category_id, k.label AS category_label,
                   k.key AS category_key, ru.match, ru.target_minutes, ru.is_active,
                   ru.sort_order, ru.created_at,
                   CASE WHEN ru.assign_user_id IS NOT NULL THEN 'user'
                        WHEN ru.assign_position_id IS NOT NULL THEN 'seat' ELSE 'role' END AS assign_type,
                   COALESCE(ru.assign_user_id, ru.assign_position_id, ru.assign_role_id) AS assign_id,
                   COALESCE(au.name, ap.name, ar.name) AS assign_name,
                   CASE WHEN ru.backup_user_id IS NOT NULL THEN 'user'
                        WHEN ru.backup_position_id IS NOT NULL THEN 'seat'
                        WHEN ru.backup_role_id IS NOT NULL THEN 'role' END AS backup_type,
                   COALESCE(ru.backup_user_id, ru.backup_position_id, ru.backup_role_id) AS backup_id,
                   COALESCE(bu.name, bp.name, br.name) AS backup_name,
                   route_targets(ru.org_id, ru.assign_user_id, ru.assign_position_id, ru.assign_role_id) AS assign_ids,
                   route_targets(ru.org_id, ru.backup_user_id, ru.backup_position_id, ru.backup_role_id) AS backup_ids
              FROM routing_rules ru
              LEFT JOIN case_categories k ON k.id = ru.category_id
              LEFT JOIN users au ON au.id = ru.assign_user_id
              LEFT JOIN committee_positions ap ON ap.id = ru.assign_position_id
              LEFT JOIN roles ar ON ar.id = ru.assign_role_id
              LEFT JOIN users bu ON bu.id = ru.backup_user_id
              LEFT JOIN committee_positions bp ON bp.id = ru.backup_position_id
              LEFT JOIN roles br ON br.id = ru.backup_role_id
             WHERE ru.org_id = $1
            """,
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    cats = {
        r["id"]: r["parent_id"]
        for r in await fetch_all(
            "SELECT id, parent_id FROM case_categories WHERE org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    }

    def depth(cid) -> int:
        d, hops = 0, 0
        while cid and hops < 9:
            d += 1
            hops += 1
            cid = cats.get(cid)
        return d

    ids = {
        i for r in found for i in (*(r["assign_ids"] or []), *(r["backup_ids"] or []))
    }
    names = {}
    if ids:
        names = {
            u["id"]: u["name"]
            for u in await fetch_all(
                "SELECT id, name FROM users WHERE id = ANY($1::uuid[])",
                list(ids),
                source_key=ctx.source_key,
            )
        }
    for r in found:
        r["match"] = jb(r["match"], {})
        # same formula as route_case(), so this number explains the winner
        r["score"] = (
            depth(r["category_id"]) * 10
            + len(r["match"]) * 5
            + (3 if r["intent_key"] else 0)
        )
        r["assign_people"] = [names.get(i) for i in (r.pop("assign_ids") or [])]
        r["backup_people"] = [names.get(i) for i in (r.pop("backup_ids") or [])]
    found.sort(key=lambda r: (-r["score"], r["sort_order"], r["created_at"]))

    keys = {
        k
        for r in await fetch_all(
            "SELECT DISTINCT jsonb_object_keys(custom_fields) AS k FROM cases "
            "WHERE org_id = $1 AND jsonb_typeof(custom_fields) = 'object'",
            ctx.org_id,
            source_key=ctx.source_key,
        )
        for k in [r["k"]]
    }
    for r in await fetch_all(
        "SELECT extra_fields FROM case_categories WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    ):
        keys.update(f.get("key") for f in jb(r["extra_fields"], []) if f.get("key"))
    return {"rows": found, "context_keys": sorted(keys)}


@router.post("/rules")
async def create_rule(ctx: CtxDep, body: RuleBody):
    ctx.need("case_model")
    async with tx(ctx) as conn:
        if body.category_id:
            ok = await conn.fetchval(
                "SELECT 1 FROM case_categories WHERE id = $1 AND org_id = $2",
                body.category_id,
                ctx.org_id,
            )
            if not ok:
                raise HTTPException(status_code=404, detail="Category not found.")
        a = await _target_columns(conn, ctx, body.assign)
        b = await _target_columns(conn, ctx, body.backup)
        order = await conn.fetchval(
            "SELECT COALESCE(max(sort_order), 0) + 10 FROM routing_rules WHERE org_id = $1",
            ctx.org_id,
        )
        rule = await conn.fetchrow(
            "INSERT INTO routing_rules (org_id, name, intent_key, category_id, match, "
            "assign_user_id, assign_position_id, assign_role_id, backup_user_id, "
            "backup_position_id, backup_role_id, target_minutes, is_active, sort_order) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11, $12, $13, $14) "
            "RETURNING id",
            ctx.org_id,
            body.name.strip(),
            (body.intent_key or "").strip() or None,
            body.category_id,
            dump(body.match),
            *a,
            *b,
            body.target_minutes,
            body.is_active,
            order,
        )
        await log_event(
            ctx,
            "routing",
            "rule_create",
            f"Created routing rule '{body.name.strip()}'",
            target_type="rule",
            target_id=rule["id"],
            after=body.model_dump(mode="json"),
            conn=conn,
        )
    return {"ok": True, "id": rule["id"]}


@router.put("/rules/{rule_id}")
async def update_rule(ctx: CtxDep, rule_id: UUID, body: RuleBody):
    ctx.need("case_model")
    async with tx(ctx) as conn:
        before = await conn.fetchrow(
            "SELECT name FROM routing_rules WHERE id = $1 AND org_id = $2 FOR UPDATE",
            rule_id,
            ctx.org_id,
        )
        if not before:
            raise HTTPException(status_code=404, detail="Rule not found.")
        if body.category_id:
            ok = await conn.fetchval(
                "SELECT 1 FROM case_categories WHERE id = $1 AND org_id = $2",
                body.category_id,
                ctx.org_id,
            )
            if not ok:
                raise HTTPException(status_code=404, detail="Category not found.")
        a = await _target_columns(conn, ctx, body.assign)
        b = await _target_columns(conn, ctx, body.backup)
        await conn.execute(
            "UPDATE routing_rules SET name = $2, intent_key = $3, category_id = $4, "
            "match = $5::jsonb, assign_user_id = $6, assign_position_id = $7, "
            "assign_role_id = $8, backup_user_id = $9, backup_position_id = $10, "
            "backup_role_id = $11, target_minutes = $12, is_active = $13 WHERE id = $1",
            rule_id,
            body.name.strip(),
            (body.intent_key or "").strip() or None,
            body.category_id,
            dump(body.match),
            *a,
            *b,
            body.target_minutes,
            body.is_active,
        )
        await log_event(
            ctx,
            "routing",
            "rule_update",
            f"Changed routing rule '{before['name']}'",
            target_type="rule",
            target_id=rule_id,
            after=body.model_dump(mode="json"),
            conn=conn,
        )
    return {"ok": True}


class ActiveBody(BaseModel):
    is_active: bool


@router.post("/rules/{rule_id}/active")
async def set_rule_active(ctx: CtxDep, rule_id: UUID, body: ActiveBody):
    ctx.need("case_model")
    async with tx(ctx) as conn:
        rule = await conn.fetchrow(
            "UPDATE routing_rules SET is_active = $3 WHERE id = $1 AND org_id = $2 "
            "RETURNING name",
            rule_id,
            ctx.org_id,
            body.is_active,
        )
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found.")
        await log_event(
            ctx,
            "routing",
            "rule_on" if body.is_active else "rule_off",
            f"Turned routing rule '{rule['name']}' {'on' if body.is_active else 'off'}",
            target_type="rule",
            target_id=rule_id,
            conn=conn,
        )
    return {"ok": True}


@router.delete("/rules/{rule_id}")
async def delete_rule(ctx: CtxDep, rule_id: UUID):
    ctx.need("case_model")
    async with tx(ctx) as conn:
        rule = await conn.fetchrow(
            "DELETE FROM routing_rules WHERE id = $1 AND org_id = $2 RETURNING name",
            rule_id,
            ctx.org_id,
        )
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found.")
        await log_event(
            ctx,
            "routing",
            "rule_delete",
            f"Deleted routing rule '{rule['name']}'",
            target_type="rule",
            target_id=rule_id,
            conn=conn,
        )
    return {"ok": True}


class TestBody(BaseModel):
    category_id: UUID
    priority: str | None = None
    context: dict[str, str | int | float | bool] = Field(default_factory=dict)


@router.post("/rules/test")
async def test_rules(ctx: CtxDep, body: TestBody):
    """'Who would get this?' Asks the database function; assigns nothing."""
    ctx.need("case_model")
    r = await fetch_one(
        "SELECT * FROM route_case($1, $2, $3::jsonb, NULL, $4)",
        ctx.org_id,
        body.category_id,
        dump(body.context),
        body.priority,
        source_key=ctx.source_key,
    )
    return {"route": await describe_route(ctx, r)}
