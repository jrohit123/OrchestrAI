"""Data & schema (super admins only): the kinds of record an organisation keeps, and how they change.

  GET  /schema           the kinds of record with their fields, statuses and record counts, and the history of changes
  POST /schema/plan      checks a list of changes (ops, app/services/schema_ops.py) and TRIES it: every statement runs in a
                         transaction that is rolled back. Nothing is kept.
  POST /schema/apply     the same checks, then it runs for real in one transaction and writes the history
  POST /schema/ai        the AI drafts ops from a description; it applies nothing
  GET  /records/{type}   the latest records of a kind kept in its own table, to look at

Changes only add (a new table, a new column, a new status); a field that is no longer wanted is switched off, never dropped.
A change runs with a short lock timeout, so it can never hold up the chat bot's own queries for long."""

import json
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.admin_panel.common import (
    Ctx,
    CtxDep,
    PanelRoute,
    _caps_cache,
    log_event,
    rows,
    tx,
)
from app.db import fetch_all, fetch_one
from app.logging_config import get_context_logger
from app.services import people_kinds, schema_ai, step_interpreter
from app.services.schema_ops import KIND_WORDS, Op, Plan, World, build_plan, slug

logger = get_context_logger(__name__)

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

_OPS = TypeAdapter(list[Op])
LOCKS = "SET LOCAL lock_timeout = '5s'; SET LOCAL statement_timeout = '30s'"


def _need(ctx: Ctx) -> None:
    if not ctx.caps.get("schema_editor"):
        raise HTTPException(
            409,
            "This organisation's database cannot keep record types yet. Run migration core-0028 first.",
        )


async def _world(ctx: Ctx, conn=None) -> World:
    async def all_(sql, *args):
        if conn is not None:
            return [dict(r) for r in await conn.fetch(sql, *args)]
        return rows(await fetch_all(sql, *args, source_key=ctx.source_key))

    w = World(
        can_use_cases=bool(ctx.caps.get("usecases")),
        can_role_tables=bool(ctx.caps.get("role_editor")),
    )
    w.tables = {
        r["table_name"]
        for r in await all_(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
    }
    for r in await all_(
        "SELECT key, label, plural, table_name, is_system, statuses FROM record_types WHERE org_id = $1",
        ctx.org_id,
    ):
        st = r["statuses"]
        r["statuses"] = json.loads(st) if isinstance(st, str) else (st or [])
        w.types[r.pop("key")] = r
    for r in await all_(
        "SELECT record_type, key, label, kind, required, is_system, is_active, storage FROM record_fields WHERE org_id = $1 ORDER BY sort_order",
        ctx.org_id,
    ):
        w.fields.setdefault(r.pop("record_type"), {})[r["key"]] = r
    if w.can_use_cases:
        w.usecase_keys = {
            r["key"]
            for r in await all_(
                "SELECT key FROM usecases WHERE org_id = $1", ctx.org_id
            )
        }
    if w.can_role_tables:
        w.roles = {
            r["name"].lower(): str(r["id"])
            for r in await all_(
                "SELECT id, name FROM roles WHERE org_id = $1", ctx.org_id
            )
        }
    return w


def _parse(body: "OpsBody") -> list:
    try:
        return _OPS.validate_python(body.ops)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", []) if x != "op")
        raise HTTPException(
            422, f"A change is not complete ({where}): {first.get('msg')}."
        )


def _show(plan: Plan) -> dict:
    return {
        "ok": plan.ok,
        "issues": plan.issues,
        "warnings": plan.warnings,
        "summary": plan.summary,
        "sql": ";\n".join(plan.sql_up) + (";" if plan.sql_up else ""),
        "way_back": ";\n".join(plan.sql_down) + (";" if plan.sql_down else ""),
    }


class _Undo(Exception):
    """Raised on purpose to roll a transaction back."""


async def _execute(conn, ctx: Ctx, plan: Plan, ops: list, by: str) -> None:
    await conn.execute(LOCKS)
    for sql in plan.sql_up:
        await conn.execute(sql)
    org = ctx.org_id
    for wr in plan.writes:
        what = wr["what"]
        if what == "record_type":
            await conn.execute(
                "INSERT INTO record_types (org_id, key, label, plural, table_name, number_prefix, statuses) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)",
                org, wr["key"], wr["label"], wr["plural"], wr["table"], wr["prefix"], json.dumps(wr["statuses"]),
            )  # fmt: skip
        elif what == "field":
            await conn.execute(
                "INSERT INTO record_fields (org_id, record_type, key, label, kind, required, options, storage, sort_order) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9)",
                org, wr["record_type"], wr["key"], wr["label"], wr["kind"], wr["required"], json.dumps(wr["options"]), wr["storage"], wr["sort_order"],
            )  # fmt: skip
        elif what == "usecase":
            await conn.execute(
                "INSERT INTO usecases (org_id, key, name, icon, description, record_type, keeps_photos, sort_order) "
                "VALUES ($1,$2,$3,$4,$5,$6,false,(SELECT coalesce(max(sort_order),0)+1 FROM usecases WHERE org_id = $1))",
                org, wr["key"], wr["name"], wr["icon"], wr["about"], wr["record_type"],
            )  # fmt: skip
        elif what == "people":
            await conn.execute(
                "INSERT INTO record_people_kinds (org_id, record_type, key, label, meaning, added, sort_order) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                org, wr["record_type"], wr["key"], wr["label"], wr["meaning"], wr["added"], wr["sort_order"],
            )  # fmt: skip
        elif what == "role_reads":
            await conn.execute(
                "UPDATE roles SET readable_tables = (SELECT coalesce(array_agg(DISTINCT x), '{}') "
                "FROM unnest(coalesce(readable_tables, '{}') || ARRAY[$2::text]) x) WHERE id = $1::uuid AND org_id = $3",
                wr["role_id"], wr["table"], org,
            )  # fmt: skip
        elif what == "statuses":
            await conn.execute(
                "UPDATE record_types SET statuses = $3::jsonb WHERE org_id = $1 AND key = $2",
                org, wr["record_type"], json.dumps(wr["statuses"]),
            )  # fmt: skip
        elif what == "field_active":
            await conn.execute(
                "UPDATE record_fields SET is_active = $4 WHERE org_id = $1 AND record_type = $2 AND key = $3",
                org, wr["record_type"], wr["key"], wr["active"],
            )  # fmt: skip
    await conn.execute(
        "INSERT INTO schema_changes (org_id, summary, ops, sql_up, sql_down, status, by_label) VALUES ($1,$2,$3::jsonb,$4,$5,'applied',$6)",
        org, " ".join(plan.summary)[:1000], json.dumps([o.model_dump() for o in ops]), ";\n".join(plan.sql_up), ";\n".join(plan.sql_down), by,
    )  # fmt: skip


async def _try(ctx: Ctx, ops: list) -> tuple[Plan, str]:
    """(the plan, the database's complaint when it could not be run). Runs everything and undoes it."""
    plan = build_plan(ops, await _world(ctx))
    if not plan.ok:
        return plan, ""
    try:
        async with tx(ctx) as conn:
            await _execute(conn, ctx, plan, ops, "dry run")
            raise _Undo
    except _Undo:
        return plan, ""
    except (asyncpg.PostgresError, asyncpg.InterfaceError) as e:
        return plan, str(e).splitlines()[0][:300]


# ───────────────────────── read ─────────────────────────


@router.get("/schema")
async def schema_overview(ctx: CtxDep):
    if not ctx.caps.get("schema_editor"):
        return {"available": False}
    types = rows(
        await fetch_all(
            "SELECT key, label, plural, table_name, number_prefix, statuses, is_system, is_active FROM record_types WHERE org_id = $1 ORDER BY is_system DESC, plural",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    fields: dict[str, list] = {}
    for r in rows(
        await fetch_all(
            "SELECT record_type, key, label, kind, required, options, storage, is_system, is_active FROM record_fields WHERE org_id = $1 ORDER BY sort_order, created_at",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    ):
        if isinstance(
            r["options"], str
        ):  # jsonb comes back as text: the screens need a list
            r["options"] = json.loads(r["options"])
        r["options"] = r["options"] if isinstance(r["options"], list) else []
        fields.setdefault(r.pop("record_type"), []).append(r)
    uses: dict[str, list] = {}
    if ctx.caps.get("usecases"):
        for r in rows(
            await fetch_all(
                "SELECT record_type, name, icon FROM usecases WHERE org_id = $1",
                ctx.org_id,
                source_key=ctx.source_key,
            )
        ):
            uses.setdefault(r["record_type"], []).append(
                f"{r['icon']} {r['name']}".strip()
            )
    for t in types:
        if isinstance(t["statuses"], str):
            t["statuses"] = json.loads(t["statuses"])
        t["fields"] = fields.get(t["key"], [])
        t["usecases"] = uses.get(t["key"], [])
        t["count"] = None
        if t["table_name"]:
            try:
                got = await fetch_one(
                    f'SELECT count(*) AS n FROM public."{slug(t["table_name"], "t")}" WHERE org_id = $1',
                    ctx.org_id,
                    source_key=ctx.source_key,
                )
                t["count"] = got["n"] if got else 0
            except Exception:
                t["count"] = None
    history = rows(
        await fetch_all(
            "SELECT id, summary, sql_up, sql_down, status, error, by_label, created_at FROM schema_changes WHERE org_id = $1 ORDER BY created_at DESC LIMIT 50",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    roles = (
        rows(
            await fetch_all(
                "SELECT name FROM roles WHERE org_id = $1 ORDER BY name",
                ctx.org_id,
                source_key=ctx.source_key,
            )
        )
        if ctx.caps.get("role_editor")
        else []
    )
    return {
        "available": True,
        "types": types,
        "history": history,
        "kinds": KIND_WORDS,
        "roles": [r["name"] for r in roles],
    }


@router.get("/records/{record_type}")
async def records_of(ctx: CtxDep, record_type: str, limit: int = 20):
    """The latest records of a kind that lives in its own table (never tickets: they have their own screen)."""
    _need(ctx)
    t = await fetch_one(
        "SELECT table_name, is_system FROM record_types WHERE org_id = $1 AND key = $2",
        ctx.org_id,
        slug(record_type, "r"),
        source_key=ctx.source_key,
    )
    if not t or not t["table_name"] or t["is_system"]:
        raise HTTPException(404, "There are no records of that kind to show here.")
    cols = rows(
        await fetch_all(
            "SELECT key, label, kind FROM record_fields WHERE org_id = $1 AND record_type = $2 AND is_active AND storage = 'column' ORDER BY sort_order",
            ctx.org_id,
            slug(record_type, "r"),
            source_key=ctx.source_key,
        )
    )
    names = ", ".join(f'"{slug(c["key"], "f")}"' for c in cols)
    got = await fetch_all(
        f"SELECT id::text, status, {names + ', ' if names else ''}created_at "
        f'FROM public."{slug(t["table_name"], "t")}" WHERE org_id = $1 ORDER BY created_at DESC LIMIT $2',
        ctx.org_id,
        max(1, min(limit, 100)),
        source_key=ctx.source_key,
    )
    return {"columns": cols, "rows": rows(got)}


# ───────────────────────── change ─────────────────────────


class OpsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ops: list[dict] = Field(max_length=20)


@router.post("/schema/plan")
async def schema_plan(ctx: CtxDep, body: Annotated[OpsBody, Body()]):
    """Check the changes and try them in a transaction that is rolled back. Nothing is kept."""
    _need(ctx)
    ops = _parse(body)
    plan, complaint = await _try(ctx, ops)
    out = _show(plan)
    out["tried"] = plan.ok and not complaint
    if complaint:
        out["ok"] = False
        out["issues"] = out["issues"] + [
            f"The database refused it when tried: {complaint}"
        ]
    return out


@router.post("/schema/apply")
async def schema_apply(ctx: CtxDep, body: Annotated[OpsBody, Body()]):
    """Check, try, then apply in one transaction. The history gets a line whether or not it worked."""
    _need(ctx)
    ops = _parse(body)
    from app.admin_panel.build import add_only

    if ctx.level != "super" and not add_only(ops):  # an admin may add lists, columns and statuses to their own organisation
        ctx.need_super("change or hide what exists")
    plan, complaint = await _try(ctx, ops)
    if not plan.ok or complaint:
        raise HTTPException(
            422, "; ".join(plan.issues + ([complaint] if complaint else []))
        )
    try:
        async with tx(ctx) as conn:
            fresh = build_plan(
                ops, await _world(ctx, conn)
            )  # nothing changed while the person was looking
            if not fresh.ok:
                raise HTTPException(409, "; ".join(fresh.issues))
            await _execute(conn, ctx, fresh, ops, ctx.actor)
            await log_event(
                ctx, "schema", "apply", " ".join(fresh.summary)[:300], conn=conn
            )
    except HTTPException:
        raise
    except (asyncpg.PostgresError, asyncpg.InterfaceError) as e:
        msg = str(e).splitlines()[0][:300]
        try:
            await fetch_all(
                "INSERT INTO schema_changes (org_id, summary, ops, status, error, by_label) VALUES ($1,$2,$3::jsonb,'failed',$4,$5) RETURNING id",
                ctx.org_id,
                " ".join(plan.summary)[:1000],
                json.dumps([o.model_dump() for o in ops]),
                msg,
                ctx.actor,
                source_key=ctx.source_key,
            )
        except Exception:
            logger.warning("could not write the failed change to the history")
        raise HTTPException(
            409, f"The database refused it, and nothing was changed: {msg}"
        )
    step_interpreter.invalidate_schema_allowlist(ctx.source_key)
    _caps_cache.pop(ctx.source_key, None)
    people_kinds.invalidate()
    return {"ok": True, "summary": plan.summary}


class AiBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[dict] = Field(min_length=1, max_length=30)


@router.post("/schema/ai")
async def schema_ai_draft(ctx: CtxDep, body: Annotated[AiBody, Body()]):
    _need(ctx)
    world = await _world(ctx)
    out = await schema_ai.draft(body.messages, world, ctx.source_key)
    if out["ops"]:
        plan = build_plan(_OPS.validate_python(out["ops"]), world)
        out["plan"] = _show(plan)
    return out
