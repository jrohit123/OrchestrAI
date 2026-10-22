"""Build with AI: an admin builds a flow (and the lists it needs) by chatting, sees it as a simple chart, and saves it.

    GET  /build/context          the lists, roles and building blocks the flow can use
    GET  /build/{workflow_id}    a flow made here: its plain form (workflows.settings.plain) and version
    POST /build/chat             one message: the AI changes the plain flow (and may propose new lists, ask questions)
    POST /build/save             compile the plain flow (flow_plain.py) into steps and save it through studio._save

The plain flow is the source; the engine steps are made from it on every save. The AI is told about the organisation
(platform.txt, then flow_builder.txt) and its answer is checked (flow_plain.check); when something does not fit it
gets one more go with the problems in plain words."""

import json
import time
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.admin_panel.common import CtxDep, PanelRoute, jb
from app.db import fetch_all, fetch_one
from app.logging_config import get_context_logger
from app.services import flow_plain
from app.services.schema_ops import Op, build_plan

logger = get_context_logger(__name__)

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)
_PROMPT = Path(__file__).parent.parent / "prompts" / "flow_builder.txt"
_OPS = TypeAdapter(list[Op])
_ADD_ONLY = {"create_record_type", "add_field", "add_status"}


async def _context(ctx) -> dict:
    from app.admin_panel.schema import _world

    lists, world = {}, None
    if ctx.caps.get("schema_editor"):
        world = await _world(ctx)
        lists = flow_plain.lists_from_world(world)
    roles = [r["name"] for r in await fetch_all("SELECT name FROM roles WHERE org_id = $1 ORDER BY name", ctx.org_id, source_key=ctx.source_key)]  # fmt: skip
    blocks = await fetch_all(
        "SELECT intent_key, name FROM workflows WHERE org_id = $1 AND to_jsonb(workflows)->>'kind' = 'block' ORDER BY name",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {"lists": lists, "roles": roles, "blocks": {b["intent_key"]: b["name"] for b in blocks}, "world": world}


@router.get("/build/context")
async def build_context(ctx: CtxDep):
    c = await _context(ctx)
    return {"lists": c["lists"], "roles": c["roles"], "blocks": c["blocks"], "can_add_lists": bool(ctx.caps.get("schema_editor"))}


@router.get("/build")
async def build_list(ctx: CtxDep):
    """The flows made with Build with AI (the ones that keep a plain form)."""
    found = await fetch_all(
        "SELECT id, name, is_active, version, settings->'plain'->'start' AS start, "
        "jsonb_array_length(coalesce(settings->'plain'->'steps', '[]'::jsonb)) AS steps "
        "FROM workflows WHERE org_id = $1 AND settings ? 'plain' ORDER BY name",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {"rows": [{**dict(r), "id": str(r["id"]), "start": jb(r["start"], {})} for r in found]}


@router.get("/build/{workflow_id}")
async def build_get(workflow_id: UUID, ctx: CtxDep):
    row = await fetch_one(
        "SELECT id, name, version, is_active, settings FROM workflows WHERE id = $1 AND org_id = $2",
        workflow_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not row:
        raise HTTPException(404, "Flow not found")
    plain = (jb(row["settings"], {}) or {}).get("plain")
    if not plain:
        raise HTTPException(409, "This flow was not made with “Build with AI”. Open it in the editor.")
    return {"id": str(row["id"]), "name": row["name"], "version": row["version"], "is_active": row["is_active"], "plain": plain}


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=40)
    flow: dict | None = None
    pending_lists: list[dict] = Field(default_factory=list, max_length=5)


def _lists_with(lists: dict, new_ops: list[dict]) -> dict:
    """The lists, plus the ones the AI proposed and the admin has not created yet (so the flow can use them)."""
    out = dict(lists)
    for op in new_ops:
        if op.get("op") != "create_record_type" or not op.get("label"):
            continue
        key = flow_plain._key(op["label"])
        out.setdefault(key, {
            "label": op["label"], "plural": op.get("plural") or op["label"] + "s", "table_name": "", "pending": True,
            "fields": {flow_plain._key(f.get("label", "")): {"label": f.get("label"), "kind": f.get("kind")} for f in op.get("fields") or []},
        })  # fmt: skip
    return out


def _fill_pending(flow: dict | None, ops: list[dict]) -> None:
    """A list the admin has not created yet gets every column the steps use (the AI often forgets one it added later)."""
    if not flow:
        return
    kinds = {a["label"]: a.get("kind") for a in flow.get("asks") or []}
    by = {flow_plain._key(o.get("label") or ""): o for o in ops if o.get("op") == "create_record_type"}
    by.update({flow_plain._key(o.get("plural") or ""): o for o in ops if o.get("op") == "create_record_type"})

    def walk(steps):
        for s in steps or []:
            if s.get("a") in ("find", "save"):
                op = by.get(flow_plain._key(str(s.get("list") or "")))
                if op is not None:
                    have = {flow_plain._key(f.get("label") or "") for f in op.setdefault("fields", [])}
                    for col, val in ((s.get("match") if s["a"] == "find" else s.get("values")) or {}).items():
                        if flow_plain._key(col) not in have:
                            r = flow_plain.refs(val)
                            kind = kinds.get(r[0]) if len(r) == 1 else None
                            op["fields"].append({"label": col, "kind": kind if kind in ("text", "number", "date", "time", "yesno") else "text"})
                            have.add(flow_plain._key(col))
            walk(s.get("yes"))
            walk(s.get("no"))

    walk(flow.get("before"))
    walk(flow.get("steps"))


def _clean(flow: dict | None, current: dict | None) -> dict | None:
    if not isinstance(flow, dict):
        return None
    out = {
        "start": flow.get("start") if isinstance(flow.get("start"), dict) else (current or {}).get("start") or {"type": "chat", "words": ""},
        "asks": [a for a in flow.get("asks") or [] if isinstance(a, dict) and a.get("label")],
        "steps": [s for s in flow.get("steps") or [] if isinstance(s, dict) and s.get("a")],
        "before": [s for s in flow.get("before") or [] if isinstance(s, dict) and s.get("a")],
    }  # fmt: skip
    for a in out["asks"]:
        a["label"] = str(a["label"])[:40]
        if a.get("kind") not in flow_plain.KINDS:
            a["kind"] = "text"
    return out


async def _ask_ai(messages: list[dict]) -> dict:
    from app.services.llm_router import AllProvidersFailed, chat_completion

    try:
        res = await chat_completion(
            messages=messages, max_tokens=6000, temperature=0.2, job="builder", response_format={"type": "json_object"}
        )
    except AllProvidersFailed as e:
        logger.error(f"build chat: every AI provider failed: {e.errors}")
        raise HTTPException(503, "The AI is not available right now. Try again in a minute.") from e
    from app.admin_panel.studio import _json_object

    return _json_object(res.choices[0].message.content or "") or {}


@router.post("/build/chat")
async def build_chat(body: ChatBody, ctx: CtxDep):
    from app.services import platform_prompt

    c = await _context(ctx)
    system = (await platform_prompt.preamble(ctx.source_key)) + "\n\n" + (
        _PROMPT.read_text(encoding="utf-8")
        .replace("{lists}", flow_plain.lists_text(_lists_with(c["lists"], body.pending_lists)))
        .replace("{roles}", ", ".join(c["roles"]) or "(none)")
        .replace("{blocks}", ", ".join(f"{k} ({n})" for k, n in c["blocks"].items()) or "(none)")
        .replace("{today}", time.strftime("%Y-%m-%d"))
    )
    current = body.flow or {"start": {"type": "chat", "words": ""}, "asks": [], "steps": []}
    talk = [
        {"role": h["role"], "content": str(h.get("content") or "")[:1500]}
        for h in body.history[-12:]
        if h.get("role") in ("user", "assistant")
    ]
    msgs = [{"role": "system", "content": system}, *talk,
            {"role": "user", "content": f"CURRENT FLOW:\n{json.dumps(current, ensure_ascii=False)}\n\nADMIN SAYS: {body.message}"}]  # fmt: skip
    out = await _ask_ai(msgs)
    new_lists = [*body.pending_lists, *[o for o in out.get("new_lists") or [] if isinstance(o, dict)]]
    flow = _clean(out.get("flow"), current)
    _fill_pending(flow, new_lists)
    lists = _lists_with(c["lists"], new_lists)
    problems = flow_plain.check(flow, lists, set(c["roles"]), set(c["blocks"])) if flow else []
    if flow and problems:  # one more go, with what does not fit in plain words
        again = await _ask_ai([*msgs, {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)},
                               {"role": "user", "content": "The flow you returned has problems:\n" + "\n".join("- " + p["text"] for p in problems)
                                + "\nFix only these: add the missing question or step, move a step, use a list or role that exists, "
                                "or propose a missing list in new_lists. Same JSON format."}])  # fmt: skip
        flow2 = _clean(again.get("flow"), current)
        if flow2:
            nl2 = [*new_lists, *[o for o in again.get("new_lists") or [] if isinstance(o, dict)]]
            _fill_pending(flow2, nl2)
            p2 = flow_plain.check(flow2, _lists_with(c["lists"], nl2), set(c["roles"]), set(c["blocks"]))
            if len(p2) < len(problems):
                out = {**again, "changes": [*(out.get("changes") or []), *(again.get("changes") or [])], "reply": again.get("reply") or out.get("reply")}
                flow, problems, new_lists = flow2, p2, nl2
    # one card per list (the AI may propose the same list again with changes: the newest wins)
    by_name: dict = {}
    for op in new_lists:
        by_name[str(op.get("plural") or op.get("label") or "").strip().lower()] = op
    new_lists = list(by_name.values())
    # the new lists, checked the way "Create it" will check them; a "choice" with fewer than two options is just words
    for op in new_lists:
        for f in op.get("fields") or []:
            if isinstance(f, dict) and f.get("kind") == "choice" and len([o for o in f.get("options") or [] if str(o).strip()]) < 2:
                f["kind"], f["options"] = "text", []
    proposed = []
    for op in new_lists:
        name = op.get("plural") or op.get("label") or "list"
        try:
            plan = build_plan(_OPS.validate_python([op]), c["world"]) if c["world"] else None
        except ValidationError as e:
            first = e.errors()[0]
            logger.info(f"build chat: a proposed list is not complete: {e.errors()[:2]}")
            problems.append({"path": "", "need": name, "text": f"The new list {name} is not complete: {first.get('msg')}."})
            continue
        if plan is None or plan.ok:
            proposed.append(op)
        else:
            logger.info(f"build chat: a proposed list cannot be made: {plan.issues}")
            problems.append({"path": "", "need": name, "text": f"The new list {name} cannot be made: " + " ".join(plan.issues)})
    questions = []
    for q in out.get("questions") or []:
        if isinstance(q, str):
            questions.append({"text": q, "options": []})
        elif isinstance(q, dict) and (q.get("text") or q.get("question")):
            questions.append({"text": str(q.get("text") or q.get("question")), "options": [str(o) for o in q.get("options") or []][:4]})
    return {
        "reply": str(out.get("reply") or "").strip(),
        "changes": [str(x) for x in out.get("changes") or []][:12],
        "questions": questions[:3],
        "flow": flow,
        "new_lists": proposed,
        "problems": problems,
    }


class SaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    plain: dict
    workflow_id: UUID | None = None
    base_version: int | None = None


@router.post("/build/save")
async def build_save(body: SaveBody, ctx: CtxDep):
    from app.admin_panel.studio import NewWorkflow, _save, create_workflow

    c = await _context(ctx)
    plain = _clean(body.plain, None)
    problems = flow_plain.check(plain, c["lists"], set(c["roles"]), set(c["blocks"]))
    if problems:
        raise HTTPException(422, {"error": "These need fixing before it can be saved:", "problems": [p["text"] for p in problems]})
    out = flow_plain.compile_flow(plain, c["lists"])
    if body.workflow_id is None:
        made = await create_workflow(
            NewWorkflow(name=body.name, kind="workflow", steps=out["steps"], entity_schema=out["entity_schema"],
                        training_phrases=out["training_phrases"], description="Made with Build with AI"),
            ctx,
        )  # fmt: skip
        wid = UUID(str(made["id"]))
        row = await fetch_one("SELECT version, settings FROM workflows WHERE id = $1", wid, source_key=ctx.source_key)
        base = row["version"]
    else:
        wid = body.workflow_id
        row = await fetch_one("SELECT version, settings FROM workflows WHERE id = $1 AND org_id = $2", wid, ctx.org_id, source_key=ctx.source_key)
        if not row:
            raise HTTPException(404, "Flow not found")
        base = body.base_version if body.base_version is not None else row["version"]
    settings = {**(jb(row["settings"], {}) or {}), "plain": plain, "precheck": out["precheck"]}
    changes = {"name": body.name, "settings": settings}
    if body.workflow_id is not None:
        changes.update(steps=out["steps"], entity_schema=out["entity_schema"], training_phrases=out["training_phrases"])
    saved = await _save(ctx, wid, base, changes, "build")
    start = plain.get("start") or {}
    if start.get("type") == "time" and ctx.caps.get("flow_triggers"):
        from app.admin_panel.triggers import CadenceBody, set_schedule

        cad = {k: start.get(k) for k in ("every", "time", "days", "day_of_month", "working_days_only") if start.get(k) is not None}
        try:
            await set_schedule(wid, CadenceBody(**cad), ctx)
        except (HTTPException, ValidationError) as e:
            detail = getattr(e, "detail", None) or str(e)
            raise HTTPException(422, {"error": "Saved, but the time it runs could not be set:", "problems": detail.get("problems", [str(detail)]) if isinstance(detail, dict) else [str(detail)]}) from e
    return {"id": str(wid), "version": saved.get("version"), "warnings": saved.get("warnings", [])}


def add_only(ops: list) -> bool:
    """What an admin (not a super admin) may apply: only adding lists, columns and statuses."""
    return all(getattr(o, "op", None) in _ADD_ONLY for o in ops)
