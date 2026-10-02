"""The workflow editor's endpoints: the step catalog, checking steps, saving with a version
history, creating, and the chat assistant that proposes changes.

Nothing here decides what a workflow does. It stores what the admin wrote (by hand or through
the chat), after step_catalog.validate_steps and workflow_validator have checked it, and keeps
every earlier version so a change can be undone."""

import difflib
import json
import re
import time
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.admin_panel.common import (
    Ctx,
    CtxDep,
    PanelRoute,
    dump,
    jb,
    log_event,
    rows,
    tx,
)
from app.admin_panel.workflows import where_used
from app.db import fetch_all, fetch_one
from app.logging_config import get_context_logger
from app.services.step_catalog import (
    FIELD_TYPES,
    STEP_TYPES,
    catalog_for_ui,
    normalize_steps,
    slugify_key,
    used_blocks,
    validate_steps,
)
from app.services.step_sql import describe_step, sql_for_step, tag_for
from app.services.workflow_validator import validate_workflow_config

logger = get_context_logger(__name__)

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

_PROMPTS = Path(__file__).parent.parent / "prompts"
# the platform's own bookkeeping tables: not offered as places a workflow saves things
_PLATFORM_TABLES = {
    "workflows",
    "workflow_drafts",
    "workflow_versions",
    "audit_log",
    "otp_tokens",
    "pending_approvals",
    "user_drafts",
    "scheduled_reports",
    "data_sources",
}
_KEY = re.compile(r"^[a-z_][a-z0-9_]*$")


# ── shared lookups ────────────────────────────────────────────────────────────


async def load_schema(ctx: Ctx) -> dict[str, set[str]]:
    """The org's real tables and columns, read fresh so a new migration shows up at once."""
    found = await fetch_all(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'",
        source_key=ctx.source_key,
    )
    schema: dict[str, set[str]] = {}
    for r in found:
        schema.setdefault(r["table_name"], set()).add(r["column_name"])
    return schema


async def load_workflows(ctx: Ctx, exclude_id=None) -> dict[str, dict]:
    found = await fetch_all(
        "SELECT id, name, intent_key, is_active, steps, workflow_type, description, "
        "entity_schema"
        + (", kind" if ctx.caps.get("workflow_kind") else "")
        + " FROM workflows WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {
        w["intent_key"]: {
            "id": w["id"],
            "name": w["name"],
            "is_active": w["is_active"],
            "steps": normalize_steps(jb(w["steps"], [])),
            "entity_schema": jb(w["entity_schema"], {}),
            "type": w["workflow_type"],
            "description": w["description"],
            "kind": w["kind"] if ctx.caps.get("workflow_kind") else "workflow",
        }
        for w in found
        if w["id"] != exclude_id
    }


def _supported_ops() -> set[str]:
    from app.services.step_interpreter import PRIMITIVES

    return set(PRIMITIVES)


def _kinds(ctx: Ctx) -> list[str]:
    return ["workflow", "case_action", "block"] if ctx.caps.get("workflow_kind") else []


@router.get("/studio/catalog")
async def catalog(ctx: CtxDep):
    schema = await load_schema(ctx)
    roles = await fetch_all(
        "SELECT permissions FROM roles WHERE org_id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    perms = sorted({p for r in roles for p in (r["permissions"] or [])})
    return {
        "steps": catalog_for_ui(_supported_ops()),
        "tables": {
            t: sorted(c) for t, c in sorted(schema.items()) if t not in _PLATFORM_TABLES
        },
        "permissions": perms,
        "field_types": FIELD_TYPES,
        "kinds": _kinds(ctx),
    }


class ValidateBody(BaseModel):
    steps: list[dict]
    entity_schema: dict = Field(default_factory=dict)
    kind: str = "workflow"
    intent_key: str | None = None


@router.post("/studio/validate")
async def validate(body: ValidateBody, ctx: CtxDep):
    """Plain-language problems with a list of steps, for the editor to show beside them."""
    return validate_steps(
        body.steps,
        schema=await load_schema(ctx),
        entity_schema=body.entity_schema,
        kind=body.kind,
        intent_key=body.intent_key,
        workflows=await load_workflows(ctx),
    )


class TechnicalBody(BaseModel):
    steps: list[dict]


@router.post("/studio/technical")
async def technical(body: TechnicalBody, ctx: CtxDep):
    """For the Technical view: each step as a sentence, whether code or the assistant does it,
    and the SQL it runs. Nothing is run and the database is not read for this."""
    names = {k: v["name"] for k, v in (await load_workflows(ctx)).items()}
    return {
        "steps": [
            {
                "sentence": describe_step(step, names),
                "tag": tag_for(step),
                "sql": sql_for_step(step),
            }
            for step in body.steps
        ]
    }


@router.get("/studio/people")
async def people(ctx: CtxDep):
    """Who 'Try it' can pretend to be: the people linked to the chat."""
    found = await fetch_all(
        "SELECT u.id, u.name, r.name AS role FROM users u JOIN roles r ON r.id = u.role_id "
        "WHERE u.org_id = $1 AND u.is_active AND COALESCE(u.phone, '') <> '' ORDER BY u.name",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {"people": rows(found)}


class TryBody(BaseModel):
    steps: list[dict]
    entity_schema: dict = Field(default_factory=dict)
    fields: dict = Field(default_factory=dict)
    as_user: UUID
    intent_key: str | None = None
    name: str | None = None
    kind: str = "workflow"


@router.post("/studio/try")
async def try_it(body: TryBody, ctx: CtxDep):
    """Run the steps as a rehearsal: everything that only looks things up runs for real, and
    everything that would save or send something is skipped and described. The result is what
    each step did, step by step. Nothing is saved and nobody is messaged."""
    from app.services.party_access import add_party_permissions
    from app.services.step_interpreter import run_workflow_steps

    who = await fetch_one(
        "SELECT u.id, u.name, u.email, u.phone, u.is_active, u.role_id, r.name AS role, "
        "r.permissions, r.readable_tables, r.readable_entity_types, o.name AS org_name "
        "FROM users u JOIN roles r ON r.id = u.role_id JOIN orgs o ON o.id = u.org_id "
        "WHERE u.id = $1 AND u.org_id = $2",
        body.as_user,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not who:
        raise HTTPException(status_code=404, detail="That person was not found")
    user = {
        "user_id": str(who["id"]),
        "user_name": who["name"],
        "email": who["email"],
        "phone": who["phone"],
        "is_active": who["is_active"],
        "role_id": str(who["role_id"]),
        "role": who["role"],
        "permissions": list(who["permissions"] or []),
        "readable_tables": list(who["readable_tables"] or []),
        "readable_entity_types": list(who["readable_entity_types"] or []),
        "org_id": str(ctx.org_id),
        "org_name": who["org_name"],
        "source_key": ctx.source_key,
    }
    user = await add_party_permissions(user)
    workflow = {
        "intent_key": body.intent_key or "try_it",
        "name": body.name or "This workflow",
        "steps": body.steps,
        "entity_schema": body.entity_schema,
        "gates": [],
        "kind": body.kind,
    }
    fields = {k: v for k, v in body.fields.items() if v not in (None, "")}
    try:
        result = await run_workflow_steps(
            workflow, fields, user, who["phone"] or "", dry_run=True
        )
    except Exception as e:
        logger.warning(f"try-it failed: {e}")
        return {
            "status": "error",
            "message": "It could not be tried: " + str(e)[:300],
            "trace": [],
        }
    out = {
        "status": result.get("status"),
        "trace": result.get("trace") or [],
        "facts": result.get("preview", []),
    }
    if result.get("status") == "error":
        out["message"] = result.get("message") or "It stopped."
    if result.get("status") == "ambiguous":
        out["message"] = (
            "More than one match was found, so the person would be asked which one."
        )
    return out


# ── one workflow, for the editor ─────────────────────────────────────────────


async def _granted_roles(ctx: Ctx, intent_key: str) -> list[str]:
    found = await fetch_all(
        "SELECT name FROM roles WHERE org_id = $1 AND $2 = ANY(permissions) ORDER BY name",
        ctx.org_id,
        intent_key,
        source_key=ctx.source_key,
    )
    return [r["name"] for r in found]


@router.get("/workflows/{workflow_id}")
async def workflow_detail(workflow_id: UUID, ctx: CtxDep):
    w = await fetch_one(
        "SELECT * FROM workflows WHERE id = $1 AND org_id = $2",
        workflow_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not w:
        raise HTTPException(status_code=404, detail="Workflow not found")
    d = dict(w)
    steps = normalize_steps(jb(d["steps"], []))
    names = {k: v["name"] for k, v in (await load_workflows(ctx)).items()}
    versions = await fetch_all(
        "SELECT version, name, published_at, jsonb_array_length(COALESCE(steps, '[]'::jsonb)) AS step_count "
        "FROM workflow_versions WHERE workflow_id = $1 ORDER BY version DESC LIMIT 40",
        workflow_id,
        source_key=ctx.source_key,
    )
    return {
        "id": d["id"],
        "name": d["name"],
        "intent_key": d["intent_key"],
        "description": d["description"],
        "workflow_type": d["workflow_type"],
        "version": d["version"],
        "is_active": d["is_active"],
        "slash_command": d["slash_command"],
        "menu_section": d["menu_section"],
        "kind": d.get("kind") or "workflow",
        "settings": jb(d.get("settings"), {}),
        "steps": steps,
        "entity_schema": jb(d["entity_schema"], {}),
        "gates": jb(d["gates"], []),
        "training_phrases": jb(d["training_phrases"], []),
        "sql_template": d["sql_template"] if d["workflow_type"] == "read" else None,
        "response_format": d.get("response_format") or "generic",
        "granted_roles": await _granted_roles(ctx, d["intent_key"]),
        "uses": [
            {"intent_key": k, "name": names.get(k, k)} for k in used_blocks(steps)
        ],
        "used_in": await where_used(ctx, d["intent_key"], workflow_id),
        "versions": rows(versions),
    }


# ── saving ───────────────────────────────────────────────────────────────────

_VERSION_COLS = (
    "workflow_id, org_id, version, intent_key, name, entity_schema, gates, "
    "granted_roles, steps, calc_rules, sql_template, slash_command"
)


async def _snapshot(conn, ctx: Ctx, row, *, old: bool = False) -> None:
    """Keep a copy of a workflow as it stands, so this version can be restored later."""
    exists = await conn.fetchval(
        "SELECT 1 FROM workflow_versions WHERE workflow_id = $1 AND version = $2",
        row["id"],
        row["version"],
    )
    if exists:
        return
    granted = [
        r["name"]
        for r in await conn.fetch(
            "SELECT name FROM roles WHERE org_id = $1 AND $2 = ANY(permissions)",
            ctx.org_id,
            row["intent_key"],
        )
    ]
    cols = _VERSION_COLS + ", published_at"
    vals = [
        row["id"],
        row["org_id"],
        row["version"],
        row["intent_key"],
        row["name"],
        row["entity_schema"],
        row["gates"],
        granted,
        row["steps"],
        row["calc_rules"],
        row["sql_template"],
        row["slash_command"],
        row["created_at"] if old else None,
    ]
    placeholders = [
        "$1", "$2", "$3", "$4", "$5", "$6::jsonb", "$7::jsonb", "$8", "$9::jsonb",
        "$10::jsonb", "$11", "$12", "COALESCE($13, now())",
    ]  # fmt: skip
    if ctx.caps.get("workflow_kind"):
        cols += ", kind, settings"
        vals += [row["kind"], row["settings"]]
        placeholders += ["$14", "$15::jsonb"]
    await conn.execute(
        f"INSERT INTO workflow_versions ({cols}) VALUES ({', '.join(placeholders)})",
        *vals,
    )


class DefinitionBody(BaseModel):
    base_version: int
    name: str | None = Field(None, min_length=2, max_length=120)
    description: str | None = Field(None, max_length=1500)
    steps: list[dict] | None = None
    entity_schema: dict | None = None
    gates: list[dict] | None = None
    training_phrases: list[str] | None = Field(None, max_length=40)
    slash_command: str | None = None
    kind: str | None = None
    settings: dict | None = None
    response_format: str | None = None


def _check_entity_schema(schema: dict) -> list[str]:
    problems = []
    for key, spec in schema.items():
        if not _KEY.match(str(key)):
            problems.append(
                f"The field name '{key}' should be lowercase letters, digits and underscores."
            )
        if not isinstance(spec, dict):
            problems.append(f"The field '{key}' is not set up correctly.")
    return problems


async def _save(
    ctx: Ctx, workflow_id: UUID, base_version: int, changes: dict, how: str
):
    from app.services import step_interpreter
    from app.services.workflow_publisher import sync_role_grants

    schema = await load_schema(ctx)
    others = await load_workflows(ctx, exclude_id=workflow_id)
    async with tx(ctx) as conn:
        row = await conn.fetchrow(
            "SELECT * FROM workflows WHERE id = $1 AND org_id = $2 FOR UPDATE",
            workflow_id,
            ctx.org_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Workflow not found")
        if row["version"] != base_version:
            raise HTTPException(
                status_code=409,
                detail=f"Someone saved '{row['name']}' while you were editing; it is now "
                f"version {row['version']}. Reload to see their change.",
            )
        if "kind" in changes and not ctx.caps.get("workflow_kind"):
            raise HTTPException(
                status_code=409,
                detail="This organisation's database has no workflow kinds yet.",
            )
        kind = changes.get("kind") or (
            row["kind"] if ctx.caps.get("workflow_kind") else "workflow"
        )
        steps = changes.get("steps", normalize_steps(jb(row["steps"], [])))
        entity_schema = changes.get("entity_schema", jb(row["entity_schema"], {}))
        gates = changes.get("gates", jb(row["gates"], []))
        if row["workflow_type"] == "read" and changes.get("steps"):
            raise HTTPException(
                status_code=400,
                detail="This workflow answers with a saved report query, so it has no steps "
                "to edit here. Change it in the classic builder.",
            )

        problems: list[str] = []
        warnings: list[str] = []
        if row["workflow_type"] != "read":
            check = validate_steps(
                steps,
                schema=schema,
                entity_schema=entity_schema,
                kind=kind,
                intent_key=row["intent_key"],
                workflows=others,
            )
            problems += check["errors"]
            warnings += check["warnings"]
        problems += _check_entity_schema(entity_schema)
        problems += validate_workflow_config(
            {
                "workflow_type": row["workflow_type"],
                "gates": gates,
                "steps": steps,
                "entity_schema": entity_schema,
                "calc_rules": jb(row["calc_rules"], {}),
            }
        )
        if "response_format" in changes and changes["response_format"] not in (
            "generic",
            "list",
        ):
            problems.append(
                "How the answer is worded: choose the assistant or the code list."
            )
        if "slash_command" in changes:
            cmd = (changes["slash_command"] or "").strip().lstrip("/").lower()
            if cmd and not re.fullmatch(r"[a-z0-9_]{2,32}", cmd):
                problems.append("The command: 2-32 letters, digits or underscores.")
            elif cmd and await conn.fetchval(
                "SELECT 1 FROM workflows WHERE org_id = $1 AND slash_command = $2 "
                "AND is_active AND id != $3",
                ctx.org_id,
                cmd,
                workflow_id,
            ):
                problems.append(
                    f"The command /{cmd} is already used by another workflow."
                )
            changes["slash_command"] = cmd or None
        if kind == "block" and await _granted_roles(ctx, row["intent_key"]):
            problems.append(
                "A building block is only run by other workflows, so no role may be given "
                "it. Remove its access under 'Who can use it' first."
            )
        if problems:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "These need fixing before it can be saved:",
                    "problems": problems,
                    "warnings": warnings,
                },
            )

        await _snapshot(conn, ctx, row, old=True)
        new_version = row["version"] + 1
        sets, args = ["version = $2"], [workflow_id, new_version]
        for col in (
            "name",
            "description",
            "steps",
            "entity_schema",
            "gates",
            "training_phrases",
            "slash_command",
            "kind",
            "settings",
            "response_format",
        ):
            if col not in changes:
                continue
            args.append(
                dump(changes[col])
                if col
                in ("steps", "entity_schema", "gates", "training_phrases", "settings")
                else changes[col]
            )
            cast = (
                "::jsonb"
                if col
                in ("steps", "entity_schema", "gates", "training_phrases", "settings")
                else ""
            )
            sets.append(f"{col} = ${len(args)}{cast}")
        new_row = await conn.fetchrow(
            f"UPDATE workflows SET {', '.join(sets)} WHERE id = $1 RETURNING *", *args
        )
        await _snapshot(conn, ctx, new_row)
        what = ", ".join(
            {
                "steps": "steps",
                "entity_schema": "what it asks for",
                "gates": "safeguards",
            }.get(k, k.replace("_", " "))
            for k in changes
        )
        await log_event(
            ctx,
            "workflows",
            how,
            f"{'Restored' if how == 'restore' else 'Edited'} '{row['name']}' "
            f"(version {row['version']} → {new_version}): {what}",
            target_type="workflow",
            target_id=workflow_id,
            before={"version": row["version"]},
            after={"version": new_version, "changed": list(changes)},
            conn=conn,
        )
    # keep what roles may touch in step with the steps, as publishing does
    await sync_role_grants(
        new_row["intent_key"],
        ctx.org_id,
        await _granted_roles(ctx, new_row["intent_key"]),
        ctx.source_key,
        entity_schema=new_row["entity_schema"],
        steps=new_row["steps"],
    )
    step_interpreter.invalidate_schema_allowlist(ctx.source_key)
    return {"ok": True, "version": new_version, "warnings": warnings}


@router.put("/workflows/{workflow_id}/definition")
async def save_definition(workflow_id: UUID, body: DefinitionBody, ctx: CtxDep):
    changes = body.model_dump(exclude_unset=True)
    base = changes.pop("base_version")
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to save.")
    for key in ("name", "steps", "entity_schema", "gates", "training_phrases"):
        if key in changes and changes[key] is None:
            raise HTTPException(status_code=400, detail=f"'{key}' cannot be empty.")
    return await _save(ctx, workflow_id, base, changes, "edit")


@router.get("/workflows/{workflow_id}/versions/{version}")
async def get_version(workflow_id: UUID, version: int, ctx: CtxDep):
    v = await fetch_one(
        "SELECT version, name, steps, entity_schema, gates, published_at "
        "FROM workflow_versions WHERE workflow_id = $1 AND org_id = $2 AND version = $3",
        workflow_id,
        ctx.org_id,
        version,
        source_key=ctx.source_key,
    )
    if not v:
        raise HTTPException(status_code=404, detail="That version was not kept.")
    d = dict(v)
    d["steps"] = normalize_steps(jb(d["steps"], []))
    d["entity_schema"] = jb(d["entity_schema"], {})
    d["gates"] = jb(d["gates"], [])
    return d


class RestoreBody(BaseModel):
    version: int
    base_version: int


@router.post("/workflows/{workflow_id}/restore")
async def restore_version(workflow_id: UUID, body: RestoreBody, ctx: CtxDep):
    """Go back to an earlier version. It is saved as a new version, so nothing is lost."""
    v = await get_version(workflow_id, body.version, ctx)
    changes = {
        "name": v["name"],
        "steps": v["steps"],
        "entity_schema": v["entity_schema"],
        "gates": v["gates"],
    }
    return await _save(ctx, workflow_id, body.base_version, changes, "restore")


# ── creating ─────────────────────────────────────────────────────────────────


class NewWorkflow(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    kind: str = "workflow"
    description: str | None = Field(None, max_length=1500)
    copy_from: UUID | None = None
    steps: list[dict] | None = None
    entity_schema: dict | None = None
    training_phrases: list[str] | None = Field(None, max_length=40)


@router.post("/workflows")
async def create_workflow(body: NewWorkflow, ctx: CtxDep):
    """A new workflow: blank, a copy of another, or what the chat drafted. A workflow people
    start is created switched OFF with nobody allowed to use it, so nothing reaches the menu
    until the admin has looked at it. A building block is created on (it has no menu)."""
    if body.kind != "workflow" and body.kind not in _kinds(ctx):
        raise HTTPException(
            status_code=409,
            detail="This organisation's database has no workflow kinds yet.",
        )
    steps = body.steps or []
    entity_schema = body.entity_schema or {}
    description = body.description
    training = body.training_phrases or []
    if body.copy_from:
        src = await fetch_one(
            "SELECT * FROM workflows WHERE id = $1 AND org_id = $2",
            body.copy_from,
            ctx.org_id,
            source_key=ctx.source_key,
        )
        if not src:
            raise HTTPException(
                status_code=404, detail="Workflow to copy was not found"
            )
        if src["workflow_type"] == "read":
            raise HTTPException(
                status_code=400,
                detail="Reports are built in the classic builder, so they cannot be copied here.",
            )
        steps = normalize_steps(jb(src["steps"], []))
        entity_schema = jb(src["entity_schema"], {})
        description = description or src["description"]
        training = jb(src["training_phrases"], [])
    schema = await load_schema(ctx)
    check = validate_steps(
        steps,
        schema=schema,
        entity_schema=entity_schema,
        kind=body.kind,
        workflows=await load_workflows(ctx),
    )
    problems = check["errors"] + _check_entity_schema(entity_schema)
    if problems:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "These need fixing before it can be created:",
                "problems": problems,
                "warnings": check["warnings"],
            },
        )
    async with tx(ctx) as conn:
        base = slugify_key(body.name)
        key, n = base, 1
        while await conn.fetchval(
            "SELECT 1 FROM workflows WHERE org_id = $1 AND intent_key = $2",
            ctx.org_id,
            key,
        ):
            n += 1
            key = f"{base}_{n}"
        cols = [
            "org_id", "intent_key", "name", "description", "workflow_type", "steps",
            "entity_schema", "training_phrases", "version", "is_active", "menu_section",
        ]  # fmt: skip
        vals = [
            ctx.org_id, key, body.name.strip(), description or "", "action", dump(steps),
            dump(entity_schema), dump(training), 1, body.kind == "block", "other",
        ]  # fmt: skip
        casts = ["", "", "", "", "", "::jsonb", "::jsonb", "::jsonb", "", "", ""]
        if ctx.caps.get("workflow_kind"):
            cols.append("kind")
            vals.append(body.kind)
            casts.append("")
        placeholders = ", ".join(f"${i + 1}{c}" for i, c in enumerate(casts))
        new_row = await conn.fetchrow(
            f"INSERT INTO workflows ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *",
            *vals,
        )
        await _snapshot(conn, ctx, new_row)
        await log_event(
            ctx,
            "workflows",
            "create",
            f"Created {'a copy as ' if body.copy_from else ''}workflow '{body.name.strip()}'",
            target_type="workflow",
            target_id=new_row["id"],
            conn=conn,
        )
    return {
        "ok": True,
        "id": new_row["id"],
        "intent_key": key,
        "warnings": check["warnings"],
    }


# ── the chat assistant ───────────────────────────────────────────────────────

_chat_calls: dict[str, list[float]] = {}
_CHAT_LIMIT = (
    30,
    600.0,
)  # calls, seconds: the chat spends money, and the panel has no login yet


def _rate_limit(source_key: str) -> None:
    now = time.monotonic()
    recent = [t for t in _chat_calls.get(source_key, []) if now - t < _CHAT_LIMIT[1]]
    if len(recent) >= _CHAT_LIMIT[0]:
        raise HTTPException(
            status_code=429,
            detail="That is a lot of chat messages in a short time. Try again in a few minutes.",
        )
    recent.append(now)
    _chat_calls[source_key] = recent


def _step_types_text() -> str:
    lines = []
    for t in STEP_TYPES:
        params = ", ".join(
            f"{p['key']} ({p['kind']}{', required' if p.get('required') else ''})"
            for p in t["params"]
        )
        lines.append(f"- {t['op']}: {t['help']} Settings: {params or 'none'}.")
    return "\n".join(lines)


def _prompt(name: str) -> str:
    dsl = (_PROMPTS / "workflow_dsl.txt").read_text(encoding="utf-8")
    dsl = dsl.replace("{step_types}", _step_types_text())
    return (_PROMPTS / name).read_text(encoding="utf-8").replace("{dsl}", dsl)


# Now and then the assistant writes the special date values without quotes (NOW() instead of
# "NOW()"), which is not valid JSON. That is the only slip repaired, and only when the answer
# does not parse as it is, so a valid answer is never touched.
_BARE_DATE = re.compile(
    r"(?<=[:\[,])(\s*)(NOW\(\)|TODAY\+30|TODAY\+7|TODAY)(?=\s*[,}\]])"
)


def _json_object(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    body = text[start : end + 1]
    for candidate in (body, _BARE_DATE.sub(r'\1"\2"', body)):
        try:
            out = json.loads(candidate)
        except ValueError:
            continue
        return out if isinstance(out, dict) else None
    return None


def _situation_warnings(check: dict) -> list[str]:
    """A record used outside the situation that finds it is a real mistake in a proposal, so
    it is sent back to the assistant to fix (for a human editing by hand it stays a warning)."""
    return [w for w in check["warnings"] if " only finds it when " in w]


def diff_steps(old: list, new: list) -> list[dict]:
    """Line the new steps up against the old ones: same, changed, added or removed."""
    a = [json.dumps(s, sort_keys=True) for s in old]
    b = [json.dumps(s, sort_keys=True) for s in new]
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, a, b, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            out += [
                {"type": "same", "old": old[i], "new": new[j]}
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            ]
        elif tag == "replace":
            pairs = min(i2 - i1, j2 - j1)
            out += [
                {"type": "changed", "old": old[i1 + k], "new": new[j1 + k]}
                for k in range(pairs)
            ]
            out += [
                {"type": "removed", "old": old[i], "new": None}
                for i in range(i1 + pairs, i2)
            ]
            out += [
                {"type": "added", "old": None, "new": new[j]}
                for j in range(j1 + pairs, j2)
            ]
        elif tag == "delete":
            out += [
                {"type": "removed", "old": old[i], "new": None} for i in range(i1, i2)
            ]
        else:
            out += [
                {"type": "added", "old": None, "new": new[j]} for j in range(j1, j2)
            ]
    return out


class ChatBody(BaseModel):
    message: str = Field(..., min_length=2, max_length=2000)
    workflow_id: UUID | None = None  # none = design a new workflow
    working: dict | None = (
        None  # what is on screen right now: name, description, steps, entity_schema
    )
    kind: str = "workflow"
    history: list[dict] = Field(default_factory=list, max_length=12)


async def _ask(system: str, user_payload: dict, history: list[dict], extra: str | None):
    from app.services.llm_router import AllProvidersFailed, chat_completion

    messages = [{"role": "system", "content": system}]
    for h in history[-6:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            messages.append({"role": h["role"], "content": h["content"][:1500]})
    messages.append(
        {
            "role": "user",
            "content": json.dumps(user_payload, default=str, ensure_ascii=False),
        }
    )
    if extra:
        messages.append({"role": "user", "content": extra})
    try:
        res = await chat_completion(messages=messages, max_tokens=8192, temperature=0.1)
    except AllProvidersFailed as e:
        logger.error(f"studio chat: every AI provider failed: {e.errors}")
        raise HTTPException(
            status_code=503,
            detail="The assistant is not available right now. Try again in a minute.",
        ) from e
    return res.choices[0].message.content or ""


@router.post("/studio/chat")
async def studio_chat(body: ChatBody, ctx: CtxDep):
    _rate_limit(ctx.source_key)
    schema = await load_schema(ctx)
    workflows = await load_workflows(ctx, exclude_id=body.workflow_id)
    blocks = [
        {"key": k, "name": w["name"], "what_it_does": w["description"]}
        for k, w in workflows.items()
        if w["kind"] == "block" and w["is_active"]
    ]
    tables = {t: sorted(c) for t, c in schema.items() if t not in _PLATFORM_TABLES}

    if body.workflow_id:
        current = body.working or {}
        w = await fetch_one(
            "SELECT name, description, entity_schema, steps, intent_key"
            + (", kind" if ctx.caps.get("workflow_kind") else "")
            + " FROM workflows WHERE id = $1 AND org_id = $2",
            body.workflow_id,
            ctx.org_id,
            source_key=ctx.source_key,
        )
        if not w:
            raise HTTPException(status_code=404, detail="Workflow not found")
        kind = w["kind"] if ctx.caps.get("workflow_kind") else "workflow"
        old_steps = normalize_steps(current.get("steps", jb(w["steps"], [])))
        entity_schema = current.get("entity_schema") or jb(w["entity_schema"], {})
        payload = {
            "workflow": {
                "name": current.get("name") or w["name"],
                "kind": kind,
                "description": current.get("description") or w["description"],
                "fields": {
                    k: (v or {}).get("description", "")
                    for k, v in entity_schema.items()
                },
                "steps": old_steps,
            },
            "schema": tables,
            "building_blocks": [b for b in blocks if b["key"] != w["intent_key"]],
            "request": body.message,
        }
        system = _prompt("workflow_editor.txt")
        reply_text, problems = "", []
        extra = None
        for attempt in (1, 2):
            raw = await _ask(system, payload, body.history, extra)
            out = _json_object(raw)
            if out is None:
                logger.warning(
                    f"studio chat: answer was not valid JSON ({len(raw)} chars): ...{raw[-120:]!r}"
                )
                extra = "Your answer was cut off or was not valid JSON. Answer again with only the JSON object described above."
                reply_text = ""
                continue
            reply_text = str(out.get("reply") or "").strip()
            new_steps = out.get("steps")
            if new_steps is None:
                return {"reply": reply_text or "No change needed.", "proposal": None}
            check = validate_steps(
                new_steps,
                schema=schema,
                entity_schema=entity_schema,
                kind=kind,
                intent_key=w["intent_key"],
                workflows=workflows,
            )
            problems = check["errors"] + _situation_warnings(check)
            if not problems:
                return {
                    "reply": reply_text,
                    "proposal": {
                        "steps": normalize_steps(new_steps),
                        "diff": diff_steps(old_steps, normalize_steps(new_steps)),
                        "warnings": check["warnings"],
                    },
                }
            extra = (
                "Those steps have problems: "
                + "; ".join(problems)
                + ". Fix them and answer again with the full JSON object."
            )
        return {
            "reply": (reply_text + " " if reply_text else "")
            + "I could not make that change cleanly. Try describing it a different way.",
            "proposal": None,
            "problems": problems,
        }

    # a new workflow
    payload = {
        "request": body.message,
        "schema": tables,
        "building_blocks": blocks,
        "allowed_kinds": _kinds(ctx) or ["workflow"],
    }
    system = _prompt("workflow_creator.txt")
    extra = None
    problems = []
    reply_text = ""
    for attempt in (1, 2):
        raw = await _ask(system, payload, body.history, extra)
        out = _json_object(raw)
        spec = (out or {}).get("workflow")
        if not isinstance(spec, dict):
            logger.warning(
                f"studio chat: no usable draft ({'valid JSON without a workflow' if out else 'not valid JSON'}, "
                f"{len(raw)} chars): {raw[:160]!r} ... {raw[-120:]!r}"
            )
            extra = "Your answer was cut off, was not valid JSON, or had no 'workflow' object. Answer again with only the JSON object described above."
            reply_text = ""
            continue
        reply_text = str(out.get("reply") or "").strip()
        kind = (
            spec.get("kind")
            if spec.get("kind") in (_kinds(ctx) or ["workflow"])
            else "workflow"
        )
        fields = spec.get("fields") if isinstance(spec.get("fields"), dict) else {}
        steps = normalize_steps(spec.get("steps") or [])
        check = validate_steps(
            steps, schema=schema, entity_schema=fields, kind=kind, workflows=workflows
        )
        problems = check["errors"] + _check_entity_schema(fields)
        if not problems:
            return {
                "reply": reply_text,
                "proposal": {
                    "name": str(spec.get("name") or "New workflow")[:120],
                    "kind": kind,
                    "description": str(spec.get("description") or "")[:1500],
                    "entity_schema": fields,
                    "training_phrases": [
                        str(p)
                        for p in (spec.get("example_phrases") or [])
                        if str(p).strip()
                    ][:12],
                    "steps": steps,
                    "warnings": check["warnings"],
                },
            }
        extra = (
            "That workflow has problems: "
            + "; ".join(problems)
            + ". Fix them and answer again with the full JSON object."
        )
    return {
        "reply": (reply_text + " " if reply_text else "")
        + "I could not draft that cleanly. Try describing it a different way.",
        "proposal": None,
        "problems": problems,
    }
