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
from uuid import UUID

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


async def _execute(conn, ctx: Ctx, plan: Plan, ops: list, by: str):
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
    return await conn.fetchval(
        "INSERT INTO schema_changes (org_id, summary, ops, sql_up, sql_down, status, by_label) VALUES ($1,$2,$3::jsonb,$4,$5,'applied',$6) RETURNING id",
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
            "SELECT id, summary, ops, sql_up, sql_down, status, error, by_label, created_at FROM schema_changes WHERE org_id = $1 ORDER BY created_at DESC LIMIT 50",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    async with tx(ctx) as conn:
        for i, c in enumerate(history):
            ops = c["ops"] if isinstance(c["ops"], list) else json.loads(c["ops"] or "[]")
            if i < 20 and c["status"] == "applied" and not any(o.get("op") == "undo" for o in ops):
                why, _ = await _undo_plan(conn, ctx, c)
                c["undo"] = {"ok": not why, "why": " ".join(why), "done": why == ["It was undone already."]}
            c.pop("ops", None)
    # the tables the app itself keeps (people, residents, staff): shown so flows and new lists can be linked to them
    builtin = []
    hide = {"id", "org_id", "user_id", "role_id", "created_at", "updated_at", "custom_fields", "approved_by"}
    for table, label in (("users", "People (everyone who can use the chat bot)"), ("residents", "Residents and their flats"), ("staff", "Staff")):
        cols = [r["column_name"] for r in await fetch_all(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = $1 ORDER BY ordinal_position", table, source_key=ctx.source_key)]  # fmt: skip
        if cols:
            builtin.append({"table": table, "label": label, "columns": [c.replace("_", " ") for c in cols if c not in hide]})
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
        "builtin": builtin,
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
            change_id = await _execute(conn, ctx, fresh, ops, ctx.actor)
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
    return {"ok": True, "summary": plan.summary, "change_id": str(change_id)}


# ───────────────────────── undo a change ─────────────────────────
# A change is undone only while that is safe: what it made holds no data and no flow uses it. Nothing else is touched.
# The undo is written in the history as its own line ({"op": "undo", "of": <change id>}), so the history stays whole.


async def _flows_using(conn, org, needles: list[str]) -> list[str]:
    """The flows whose steps (or plain form) name any of these, in quotes."""
    pats = [f'%"{n}"%' for n in needles if n]
    if not pats:
        return []
    got = await conn.fetch(
        "SELECT name FROM workflows WHERE org_id = $1 AND (steps::text LIKE ANY($2::text[]) OR coalesce(settings::text, '') LIKE ANY($2::text[])) ORDER BY name",
        org, pats,
    )  # fmt: skip
    return [r["name"] for r in got]


async def _undo_plan(conn, ctx: Ctx, change: dict) -> tuple[list[str], list[tuple[str, list]]]:
    """(why it cannot be undone, the statements that undo it). Empty reasons: it is safe."""
    org, why, acts = ctx.org_id, [], []
    ops = change["ops"] if isinstance(change["ops"], list) else json.loads(change["ops"] or "[]")
    if change["status"] != "applied":
        return ["Only a change that was applied can be undone."], []
    if any(o.get("op") == "undo" for o in ops):
        return ["This line is itself an undo."], []
    done = await conn.fetchval(
        "SELECT 1 FROM schema_changes WHERE org_id = $1 AND ops @> $2::jsonb LIMIT 1", org, json.dumps([{"op": "undo", "of": str(change["id"])}])
    )  # fmt: skip
    if done:
        return ["It was undone already."], []
    for o in reversed(ops):
        kind = o.get("op")
        if kind == "create_record_type":
            key, table = slug(o.get("label", ""), "r"), slug(o.get("plural", ""), "t")
            t = await conn.fetchrow("SELECT table_name FROM record_types WHERE org_id = $1 AND key = $2", org, key)
            if not t:
                why.append(f"The list {o.get('plural')} is not there any more.")
                continue
            n = await conn.fetchval(f'SELECT count(*) FROM public."{table}" WHERE org_id = $1', org)
            if n:
                why.append(f"{o.get('plural')} holds {n} record{'s' if n != 1 else ''}.")
            used = await _flows_using(conn, org, [table, o.get("label"), o.get("plural")])
            used += [r["name"] for r in await conn.fetch(
                "SELECT w.name FROM workflows w JOIN usecases u ON u.id = w.usecase_id WHERE w.org_id = $1 AND u.record_type = $2", org, key)]  # fmt: skip
            if used:
                why.append("Flows use it: " + ", ".join(sorted(set(used))) + ".")
            acts += [
                (f'DROP TABLE public."{table}"', []),
                ("DELETE FROM record_fields WHERE org_id = $1 AND record_type = $2", [org, key]),
                ("DELETE FROM record_people_kinds WHERE org_id = $1 AND record_type = $2", [org, key]),
                ("DELETE FROM usecases WHERE org_id = $1 AND record_type = $2", [org, key]),
                ("UPDATE roles SET readable_tables = array_remove(readable_tables, $2) WHERE org_id = $1", [org, table]),
                ("DELETE FROM record_types WHERE org_id = $1 AND key = $2", [org, key]),
            ]  # fmt: skip
        elif kind == "add_field":
            rt = slug(o.get("record_type", ""), "r")
            label = ((o.get("field") or {}).get("label") or "").strip()
            f = await conn.fetchrow(
                "SELECT f.key, f.storage, t.table_name FROM record_fields f JOIN record_types t ON t.org_id = f.org_id AND t.key = f.record_type "
                "WHERE f.org_id = $1 AND f.record_type = $2 AND f.label = $3 ORDER BY f.created_at DESC LIMIT 1", org, rt, label,
            )  # fmt: skip
            if not f:
                why.append(f"The field “{label}” is not there any more.")
                continue
            fk, table = f["key"], f["table_name"]
            if f["storage"] == "column" and table:
                n = await conn.fetchval(
                    f'SELECT count(*) FROM public."{table}" WHERE org_id = $1 AND "{slug(fk, "f")}" IS NOT NULL AND "{slug(fk, "f")}"::text NOT IN (\'\', \'false\', \'[]\')', org)  # fmt: skip
                acts.append((f'ALTER TABLE public."{table}" DROP COLUMN "{slug(fk, "f")}"', []))
            elif table:
                n = await conn.fetchval(f'SELECT count(*) FROM public."{table}" WHERE org_id = $1 AND custom_fields ? $2', org, fk)
            else:
                n = 0
            if n:
                why.append(f"“{label}” is filled in on {n} record{'s' if n != 1 else ''}.")
            used = await _flows_using(conn, org, [fk]) if table and await _flows_using(conn, org, [table]) else []
            if used:
                why.append(f"Flows use “{label}”: " + ", ".join(used) + ".")
            acts.append(("DELETE FROM record_fields WHERE org_id = $1 AND record_type = $2 AND key = $3", [org, rt, fk]))
        elif kind == "add_status":
            rt = slug(o.get("record_type", ""), "r")
            skey = slug(((o.get("status") or {}).get("label") or ""), "s")
            t = await conn.fetchrow("SELECT table_name, statuses FROM record_types WHERE org_id = $1 AND key = $2", org, rt)
            if not t or not t["table_name"]:
                why.append("That list is not there any more.")
                continue
            n = await conn.fetchval(f'SELECT count(*) FROM public."{t["table_name"]}" WHERE org_id = $1 AND status = $2', org, skey)
            if n:
                why.append(f"{n} record{'s are' if n != 1 else ' is'} in that status.")
            st = t["statuses"] if isinstance(t["statuses"], list) else json.loads(t["statuses"] or "[]")
            keep = [s for s in st if s.get("key") != skey]
            acts += [(s, []) for s in (change["sql_down"] or "").split(";\n") if s.strip()]
            acts.append(("UPDATE record_types SET statuses = $3::jsonb WHERE org_id = $1 AND key = $2", [org, rt, json.dumps(keep)]))
        elif kind == "set_field_active":
            if ctx.level != "super":
                why.append("Only a super admin switches fields on and off.")
            acts.append(("UPDATE record_fields SET is_active = $4 WHERE org_id = $1 AND record_type = $2 AND key = $3",
                         [org, slug(o.get("record_type", ""), "r"), o.get("key"), not o.get("active")]))  # fmt: skip
        else:
            why.append("This kind of change cannot be undone here.")
    return why, acts


@router.post("/schema/undo/{change_id}")
async def schema_undo(change_id: UUID, ctx: CtxDep):
    """Undo one change from the history, only while it is safe; checked again inside the transaction."""
    _need(ctx)
    async with tx(ctx) as conn:
        await conn.execute(LOCKS)
        change = await conn.fetchrow("SELECT * FROM schema_changes WHERE id = $1 AND org_id = $2", change_id, ctx.org_id)
        if not change:
            raise HTTPException(404, "That change is not in the history.")
        why, acts = await _undo_plan(conn, ctx, dict(change))
        if why:
            raise HTTPException(409, "It cannot be undone: " + " ".join(why))
        try:
            for sql, args in acts:
                await conn.execute(sql, *args)
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as e:
            raise HTTPException(409, f"The database refused it, and nothing was changed: {str(e).splitlines()[0][:200]}")
        await conn.execute(
            "INSERT INTO schema_changes (org_id, summary, ops, status, by_label) VALUES ($1,$2,$3::jsonb,'applied',$4)",
            ctx.org_id, ("Undid: " + change["summary"])[:1000], json.dumps([{"op": "undo", "of": str(change_id)}]), ctx.actor,
        )  # fmt: skip
        await log_event(ctx, "schema", "undo", ("Undid: " + change["summary"])[:300], conn=conn)
    step_interpreter.invalidate_schema_allowlist(ctx.source_key)
    _caps_cache.pop(ctx.source_key, None)
    people_kinds.invalidate()
    return {"ok": True}


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
