"""Build with AI: an admin builds a flow (and the lists it needs) by chatting, sees it as a simple chart, and saves it.

    GET  /build/context          the lists, roles and building blocks the flow can use
    GET  /build/{workflow_id}    a flow made here: the live plain form, the draft, the versions
    PUT  /build/{id}/draft       keep the draft (settings.plain_draft); people keep getting the live one
    DELETE /build/{id}/draft     throw the draft away
    POST /build/{id}/restore     copy an earlier version into the draft
    POST /build/{id}/convert     open a flow from the Flows editor here: its steps are kept exactly, shown in words
    POST /build/chat             one message: the AI changes the plain flow (and may propose new lists, ask questions)
    POST /build/check            the checker: what does not fit, and what each step needs and gives (for the Card)
    POST /build/try              a rehearsal on the real engine as one person: nothing is saved or sent
    POST /build/save             make it live: compile the plain flow (flow_plain.py) into steps, save through
                                 studio._save (a new version) and keep the plain form in the flow's history

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


async def _people(ctx) -> list[dict]:
    """People to try a flow as (Try it): name, role and flat."""
    sql = (
        "SELECT u.id, u.name, r.name AS role{flat} FROM users u LEFT JOIN roles r ON r.id = u.role_id "
        "WHERE u.org_id = $1 AND coalesce(u.is_active, true) ORDER BY u.name LIMIT 80"
    )
    flat = ", (SELECT concat_ws('-', x.wing, x.flat_no) FROM residents x WHERE x.user_id = u.id LIMIT 1) AS flat"
    for f in (flat, ""):
        try:
            found = await fetch_all(sql.replace("{flat}", f), ctx.org_id, source_key=ctx.source_key)
            return [{"id": str(p["id"]), "name": p["name"], "role": p["role"], "flat": p.get("flat") or ""} for p in found]
        except Exception as e:  # an organisation without flats
            logger.info(f"build: people without flats ({e!r})")
    return []


@router.get("/build/context")
async def build_context(ctx: CtxDep):
    c = await _context(ctx)
    return {"lists": c["lists"], "roles": c["roles"], "blocks": c["blocks"], "people": await _people(ctx),
            "block_info": _block_info(await _all_flows(ctx)), "can_add_lists": bool(ctx.caps.get("schema_editor"))}  # fmt: skip


def _calls(steps) -> list[str]:
    """The building blocks a list of engine steps runs."""
    return [
        str((s.get("params") or {}).get("workflow") or (s.get("params") or {}).get("intent_key"))
        for s in steps if isinstance(s, dict) and s.get("op") == "run_workflow"
    ]  # fmt: skip


def _block_info(flows: list[dict]) -> dict:
    """Each building block in words, for the Card: what it is for, its steps (and when each runs), how many flows use it."""
    names = {f["intent_key"]: f["name"] for f in flows}
    uses: dict = {}
    for f in flows:
        for k in set(_calls(jb(f.get("steps"), []) or [])):
            uses[k] = uses.get(k, 0) + 1
    out = {}
    for f in flows:
        if (f.get("kind") or "workflow") != "block":
            continue
        schema = jb(f.get("entity_schema"), {}) or {}
        labels = {k: v.get("label") or flow_plain._pretty(k) for k, v in schema.items() if isinstance(v, dict)}
        steps = [s for s in jb(f.get("steps"), []) or [] if isinstance(s, dict)]
        out[f["intent_key"]] = {
            "id": str(f["id"]), "name": f["name"], "about": f.get("description") or "", "used_by": uses.get(f["intent_key"], 0),
            "steps": [{"op": s.get("op"), "words": flow_plain.engine_words(s, names, labels)[0], "when_words": flow_plain.guard_words(s.get("when"), labels)} for s in steps],
        }  # fmt: skip
    return out


def _block_steps(flows: list[dict]) -> dict:
    return {f["intent_key"]: jb(f.get("steps"), []) or [] for f in flows if (f.get("kind") or "workflow") == "block"}


async def _all_flows(ctx) -> list[dict]:
    return [
        dict(r)
        for r in await fetch_all(
            "SELECT *, to_jsonb(w)->>'kind' AS kind FROM workflows w WHERE org_id = $1 ORDER BY name",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    ]


async def _schedule(ctx, workflow_id) -> dict | None:
    """The flow's timer, if it runs by itself, as the plain flow's start keeps it."""
    if not ctx.caps.get("flow_triggers"):
        return None
    row = await fetch_one("SELECT cadence FROM flow_schedules WHERE workflow_id = $1", workflow_id, source_key=ctx.source_key)
    return jb(row["cadence"], None) if row else None


@router.get("/build")
async def build_list(ctx: CtxDep):
    """The flows made or opened here (they keep a plain form), and every other flow with whether it can be opened here."""
    flows = await _all_flows(ctx)
    names = {f["intent_key"]: f["name"] for f in flows}
    rows, others = [], []
    for f in flows:
        st = jb(f.get("settings"), {}) or {}
        if st.get("plain"):
            if (f.get("kind") or "workflow") != "block" or ctx.level == "super":
                rows.append({"id": str(f["id"]), "name": f["name"], "is_active": f["is_active"], "version": f["version"], "start": st["plain"].get("start") or {}})
        elif (f.get("kind") or "workflow") != "block" or ctx.level == "super":
            plain, why = flow_plain.from_workflow(f, names)
            others.append({"id": str(f["id"]), "name": f["name"], "is_active": f["is_active"], "ok": plain is not None, "why": why})
    return {"rows": rows, "others": others}


def _need_block_rights(ctx, row) -> None:
    """A building block is used by many flows: only a super admin opens or changes one."""
    if (row.get("kind") or "workflow") == "block":
        ctx.need_super("change a building block")


@router.get("/build/{workflow_id}")
async def build_get(workflow_id: UUID, ctx: CtxDep):
    row = await fetch_one(
        "SELECT id, name, version, is_active, settings, to_jsonb(w)->>'kind' AS kind, workflow_type FROM workflows w WHERE id = $1 AND org_id = $2",
        workflow_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not row:
        raise HTTPException(404, "Flow not found")
    _need_block_rights(ctx, dict(row))
    st = jb(row["settings"], {}) or {}
    if not st.get("plain"):
        raise HTTPException(409, "This flow was not made with “Build with AI”. Open it in the editor.")
    names = {r["intent_key"]: r["name"] for r in await fetch_all("SELECT intent_key, name FROM workflows WHERE org_id = $1", ctx.org_id, source_key=ctx.source_key)}
    return {
        "id": str(row["id"]), "name": row["name"], "version": row["version"], "is_active": row["is_active"],
        "plain": flow_plain.refresh_words(st["plain"], names), "draft": flow_plain.refresh_words(st["plain_draft"], names) if st.get("plain_draft") else None,
        "history": [{"v": h.get("v"), "at": h.get("at"), "note": h.get("note")} for h in st.get("plain_history") or []],
    }  # fmt: skip


@router.post("/build/{workflow_id}/convert")
async def build_convert(workflow_id: UUID, ctx: CtxDep):
    """Open a flow from the Flows editor here. Nothing it does changes: its steps are kept exactly (shown in words),
    its questions keep their names, and the plain form is checked to give back the very same steps before it is kept."""
    flows = await _all_flows(ctx)
    row = next((f for f in flows if f["id"] == workflow_id), None)
    if not row:
        raise HTTPException(404, "Flow not found")
    _need_block_rights(ctx, row)
    st = jb(row.get("settings"), {}) or {}
    if st.get("plain"):
        return {"ok": True, "already": True}
    plain, why = flow_plain.from_workflow(row, {f["intent_key"]: f["name"] for f in flows}, await _schedule(ctx, workflow_id))
    if plain is None:
        raise HTTPException(409, why)
    history = [{"v": row["version"], "at": time.strftime("%Y-%m-%d %H:%M"), "note": "Opened in Build with AI (nothing changed)", "plain": plain}]
    done = await fetch_one(
        "UPDATE workflows SET settings = coalesce(settings, '{}'::jsonb) || jsonb_build_object('plain', $3::jsonb, 'plain_history', $4::jsonb) "
        "WHERE id = $1 AND org_id = $2 AND version = $5 AND NOT (coalesce(settings, '{}'::jsonb) ? 'plain') RETURNING id",
        workflow_id, ctx.org_id, json.dumps(plain), json.dumps(history), row["version"],
        source_key=ctx.source_key,
    )  # fmt: skip
    if not done:
        raise HTTPException(409, "Someone changed this flow just now. Try again.")
    logger.info(f"build: opened {row['intent_key']} here (version {row['version']}, steps unchanged)")
    return {"ok": True}


class DraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plain: dict


async def _set_draft(ctx, workflow_id: UUID, plain: dict | None) -> None:
    """The draft lives in the flow's settings: no new version, nothing changes for people."""
    sql = (
        "UPDATE workflows SET settings = jsonb_set(coalesce(settings, '{}'::jsonb), '{plain_draft}', $3::jsonb) "
        "WHERE id = $1 AND org_id = $2 AND settings ? 'plain' RETURNING id"
        if plain is not None
        else "UPDATE workflows SET settings = coalesce(settings, '{}'::jsonb) - 'plain_draft' "
        "WHERE id = $1 AND org_id = $2 AND settings ? 'plain' RETURNING id"
    )
    args = [workflow_id, ctx.org_id] + ([json.dumps(plain)] if plain is not None else [])
    if not await fetch_one(sql, *args, source_key=ctx.source_key):
        raise HTTPException(404, "Flow not found")


@router.put("/build/{workflow_id}/draft")
async def build_draft(workflow_id: UUID, body: DraftBody, ctx: CtxDep):
    await _set_draft(ctx, workflow_id, _clean(body.plain, None))
    return {"ok": True}


@router.delete("/build/{workflow_id}/draft")
async def build_draft_drop(workflow_id: UUID, ctx: CtxDep):
    await _set_draft(ctx, workflow_id, None)
    return {"ok": True}


class RestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: int


@router.post("/build/{workflow_id}/restore")
async def build_restore(workflow_id: UUID, body: RestoreBody, ctx: CtxDep):
    """An earlier version becomes the draft; making it live is a separate step."""
    row = await fetch_one("SELECT settings FROM workflows WHERE id = $1 AND org_id = $2", workflow_id, ctx.org_id, source_key=ctx.source_key)
    found = [h for h in ((jb(row["settings"], {}) or {}).get("plain_history") or []) if h.get("v") == body.v] if row else []
    if not found:
        raise HTTPException(404, "That version was not found")
    await _set_draft(ctx, workflow_id, found[0]["plain"])
    return {"ok": True, "plain": found[0]["plain"]}


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


def _engine_changed(flow: dict, current: dict) -> list[dict]:
    """A step kept from the Flows editor must come back exactly as it was (it may be moved or removed, never changed)."""
    import json as _json

    def engine(plain):
        out = []

        def walk(steps):
            for s in steps or []:
                if s.get("a") == "engine":
                    out.append(_json.dumps(s.get("step"), sort_keys=True, default=str))
                walk(s.get("yes"))
                walk(s.get("no"))

        walk((plain or {}).get("before"))
        walk((plain or {}).get("steps"))
        return out

    was = set(engine(current))
    return [
        {"path": "", "need": "", "text": "A step from the Flows editor was changed; keep those steps exactly as they are."}
        for x in engine(flow) if x not in was
    ][:1]


_PLAIN_STEPS = {"say", "tell", "set", "find", "save", "if", "stop", "approve", "block", "engine"}


def _known_steps(steps) -> list[dict]:
    """Only the kinds of step the plain flow has, at every depth (an AI answer may carry a leftover or made-up one)."""
    out = []
    for s in steps if isinstance(steps, list) else []:
        if isinstance(s, dict) and s.get("a") in _PLAIN_STEPS:
            if s["a"] == "if":
                s = {**s, "yes": _known_steps(s.get("yes")), "no": _known_steps(s.get("no")),
                     "tests": [t for t in s.get("tests") or [] if isinstance(t, dict)]}  # fmt: skip
            out.append(s)
    return out


def _clean(flow: dict | None, current: dict | None) -> dict | None:
    if not isinstance(flow, dict):
        return None
    out = {
        "start": (current or {}).get("start") if ((current or {}).get("start") or {}).get("type") in ("block", "button")
        else flow.get("start") if isinstance(flow.get("start"), dict) else (current or {}).get("start") or {"type": "chat", "words": ""},
        "asks": [a for a in flow.get("asks") or [] if isinstance(a, dict) and a.get("label")],
        "steps": _known_steps(flow.get("steps")),
        "before": _known_steps(flow.get("before")),
    }  # fmt: skip
    report = flow.get("report") or (current or {}).get("report")
    if isinstance(report, dict):
        out["report"], out["steps"], out["before"] = report, [], []
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
    if current.get("report"):  # a report answers one saved question: the AI does not rewrite that question
        return {"info": {}, "flow": None, "new_lists": [], "problems": [], "changes": [], "questions": [],
                "reply": "This is a report: it looks up one saved question and replies with what it finds. Here you can change its "
                         "name, the words that start it and its questions (in the Card); what it looks up is changed in the "
                         "Advanced editor."}  # fmt: skip
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
    problems = (flow_plain.check(flow, lists, set(c["roles"]), set(c["blocks"])) + _engine_changed(flow, current)) if flow else []
    if flow and problems:  # one more go, with what does not fit in plain words
        again = await _ask_ai([*msgs, {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)},
                               {"role": "user", "content": "The flow you returned has problems:\n" + "\n".join("- " + p["text"] for p in problems)
                                + "\nFix only these: add the missing question or step, move a step, use a list or role that exists, "
                                "or propose a missing list in new_lists. Same JSON format."}])  # fmt: skip
        flow2 = _clean(again.get("flow"), current)
        if flow2:
            nl2 = [*new_lists, *[o for o in again.get("new_lists") or [] if isinstance(o, dict)]]
            _fill_pending(flow2, nl2)
            p2 = flow_plain.check(flow2, _lists_with(c["lists"], nl2), set(c["roles"]), set(c["blocks"])) + _engine_changed(flow2, current)
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
    info = flow_plain.analyse(flow, _lists_with(c["lists"], proposed), set(c["roles"]), set(c["blocks"]))[1] if flow else {}
    return {
        "info": info,
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
    note: str = Field(default="", max_length=200)


class CheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plain: dict
    pending_lists: list[dict] = Field(default_factory=list, max_length=5)


@router.post("/build/check")
async def build_check(body: CheckBody, ctx: CtxDep):
    c = await _context(ctx)
    plain = _clean(body.plain, None)
    problems, info = flow_plain.analyse(plain, _lists_with(c["lists"], body.pending_lists), set(c["roles"]), set(c["blocks"]))
    # notes do not stop it going live: a step that never does anything is harmless, only confusing
    return {"problems": problems, "info": info, "notes": flow_plain.never_runs(plain, _block_steps(await _all_flows(ctx)))}


class TryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plain: dict
    as_user: UUID
    fields: dict = Field(default_factory=dict)
    part: str = "all"  # "before": only the checks before the questions
    workflow_id: UUID | None = None  # a report: its saved question is read from the flow


@router.post("/build/try")
async def build_try(body: TryBody, ctx: CtxDep):
    """A rehearsal on the real engine, as one person: lists are really looked in; nothing is saved and nobody is
    messaged. Gives what would be said to them, what the others would get, and whether it stops."""
    from app.admin_panel.acting import chat_user
    from app.services.step_interpreter import run_workflow_steps

    c = await _context(ctx)
    plain = _clean(body.plain, None)
    problems = flow_plain.check(plain, c["lists"], set(c["roles"]), set(c["blocks"]))
    if problems:
        return {"status": "not_ready", "message": "Fix what is not ready first: " + problems[0]["text"]}
    user = await chat_user(ctx, user_id=body.as_user)
    if not user:
        raise HTTPException(404, "That person was not found, or has no role.")
    if plain.get("report"):
        return await _try_report(ctx, body, plain, user)
    out = flow_plain.compile_flow(plain, c["lists"])
    steps = out["precheck"] if body.part == "before" else out["steps"]
    keys = {a["label"]: flow_plain.ask_key(a) for a in plain.get("asks") or []}
    fields = {keys.get(k) or flow_plain._key(k): v for k, v in body.fields.items() if v not in (None, "")}
    wf = {"intent_key": "build_try", "name": "Try it", "steps": steps, "entity_schema": out["entity_schema"], "gates": [], "kind": "workflow"}
    try:
        res = await run_workflow_steps(wf, fields, user, user.get("phone") or "", dry_run=True)
    except Exception as e:
        logger.warning(f"build try failed: {e!r}")
        return {"status": "error", "message": "It could not be tried: " + str(e)[:300]}
    # what each step did, in order: looked in a list, would save (a rehearsal skips saving), replied, would tell
    facts = [str(t["detail"]) for t in res.get("trace") or [] if t.get("status") in ("ran", "would") and t.get("detail")]
    facts = facts or list(res.get("preview") or [])
    return {
        "status": res.get("status"), "message": res.get("message"), "facts": facts,
        "said": res.get("said") or [], "stopped": bool(res.get("stopped")),
    }  # fmt: skip


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
        row = await fetch_one("SELECT version, settings, to_jsonb(w)->>'kind' AS kind FROM workflows w WHERE id = $1 AND org_id = $2", wid, ctx.org_id, source_key=ctx.source_key)
        if not row:
            raise HTTPException(404, "Flow not found")
        _need_block_rights(ctx, dict(row))
        base = body.base_version if body.base_version is not None else row["version"]
    old = jb(row["settings"], {}) or {}
    note = body.note or ("First version" if body.workflow_id is None else "Changes")
    history = [*(old.get("plain_history") or []), {"v": base + 1, "at": time.strftime("%Y-%m-%d %H:%M"), "note": note, "plain": plain}][-20:]
    settings = {**old, "plain": plain, "precheck": out["precheck"], "plain_history": history}
    settings.pop("plain_draft", None)
    changes = {"name": body.name, "settings": settings}
    if body.workflow_id is not None:
        changes.update(entity_schema=out["entity_schema"], training_phrases=out["training_phrases"])
        if not plain.get("report"):  # a report keeps its saved question and has no steps
            changes["steps"] = out["steps"]
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


async def _try_report(ctx, body: "TryBody", plain: dict, user: dict) -> dict:
    """A report's answer, as this person would get it now (a report only reads)."""
    from app.services import agent

    if not body.workflow_id:
        return {"status": "error", "message": "Make it live once, then try it."}
    wf = await fetch_one("SELECT * FROM workflows WHERE id = $1 AND org_id = $2", body.workflow_id, ctx.org_id, source_key=ctx.source_key)
    if not wf or not wf["sql_template"]:
        return {"status": "error", "message": "This report has no saved question."}
    keys = {a["label"]: flow_plain.ask_key(a) for a in plain.get("asks") or []}
    fields = {keys.get(k) or flow_plain._key(k): v for k, v in body.fields.items() if v not in (None, "")}
    from app.services.query_engine import execute_query

    wf = dict(wf)
    try:  # the same as the chat bot's report (agent._run_report_by_code), without touching the person's chat draft
        raw = await execute_query(
            sql=wf["sql_template"],
            params=agent._resolve_sql_params(jb(wf.get("sql_params_order"), []) or [], user, fields),
            user=user,
            response_format="generic",
            business_glossary=jb(wf.get("business_glossary"), {}) or {},
            trusted=await agent._report_runs_with_its_own_data(user, wf["intent_key"]),
        )
        text = agent.format_list(wf["name"], raw) if (wf.get("response_format") or "") == "list" else await agent._llm_format_report(wf, raw, user["source_key"])
    except Exception as e:
        logger.warning(f"build try report failed: {e!r}")
        return {"status": "error", "message": "It could not be tried: " + str(e)[:300]}
    return {"status": "preview", "facts": ["🔎 Looked up: " + plain["report"].get("words", ""), "Reply: " + str(text)], "said": [str(text)], "stopped": False}


def add_only(ops: list) -> bool:
    """What an admin (not a super admin) may apply: only adding lists, columns and statuses."""
    return all(getattr(o, "op", None) in _ADD_ONLY for o in ops)
