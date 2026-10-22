"""Your databases and the AI change builder (Build > Data & schema). Super admins only.

  * GET  /db/schema              every table of a database with its columns, links and an estimate of its rows, and the
                                 migration history. Read-only. source=org (this organisation's database) or control.
  * GET  /db/builder/context     exactly what the AI is told about the database before it drafts anything.
  * POST /db/builder/chat        a client's need in plain words -> how the AI reads it against what exists, a few
                                 questions with choices, then a plan: summary, SQL, flows, who may use them, seed rows,
                                 and the way back. The AI drafts; it changes nothing.
  * POST /db/builder/validate    the (edited) plan is checked against the live database, then every statement is run in
                                 a transaction that is rolled back, so nothing is kept. Gives a fingerprint of what passed.
  * POST /db/builder/apply       only the exact plan that passed (same fingerprint), only after the super admin confirms
                                 a backup was taken: one transaction, written to schema_changes, schema_migrations and the
                                 change log. Flows are then made switched off, so nothing reaches anybody until checked.

What may be applied is additions only: new tables, new columns, indexes, comments, seed rows, and two extensions. Anything
that removes or rewrites data (DROP, DELETE, UPDATE, TRUNCATE, ALTER ... DROP/TYPE, GRANT, functions) is refused here; it
belongs in a reviewed migration."""

import hashlib
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.admin_panel.common import Ctx, CtxDep, PanelRoute, log_event, rows
from app.db import get_pool, routing_pool
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

MAX_SQL = 60_000
EXTENSIONS = {"btree_gist", "pg_trgm"}
_ALLOWED = re.compile(
    r"^(CREATE\s+TABLE|CREATE\s+(UNIQUE\s+)?INDEX|ALTER\s+TABLE|COMMENT\s+ON|INSERT\s+INTO|CREATE\s+EXTENSION)\b",
    re.IGNORECASE,
)
_FORBIDDEN = re.compile(
    r"\b(DROP|TRUNCATE|DELETE|UPDATE|GRANT|REVOKE|CREATE\s+(OR\s+REPLACE\s+)?(FUNCTION|PROCEDURE|TRIGGER|RULE)|DO\s+\$|COPY|VACUUM)\b",
    re.IGNORECASE,
)


# ───────────────────────── reading a database ─────────────────────────


async def _pool(ctx: Ctx, source: str):
    if source == "control":
        return routing_pool()
    return await get_pool(ctx.source_key)


async def _tables(conn) -> dict[str, dict]:
    tables: dict[str, dict] = {}
    for r in await conn.fetch(
        "SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
    ):
        t = tables.setdefault(
            r["table_name"],
            {"name": r["table_name"], "columns": [], "links": [], "rows": None},
        )
        t["columns"].append(
            {
                "name": r["column_name"],
                "type": r["data_type"],
                "null": r["is_nullable"] == "YES",
                "default": (r["column_default"] or "")[:60],
            }
        )
    for r in await conn.fetch(
        "SELECT c.relname, c.reltuples::bigint AS n FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace "
        "WHERE s.nspname = 'public' AND c.relkind = 'r'"
    ):
        if r["relname"] in tables:
            tables[r["relname"]]["rows"] = max(int(r["n"]), 0)
    for r in await conn.fetch(
        "SELECT conrelid::regclass::text AS t, confrelid::regclass::text AS f FROM pg_constraint "
        "WHERE contype = 'f' AND connamespace = 'public'::regnamespace"
    ):
        t = r["t"].replace("public.", "")
        if t in tables:
            tables[t]["links"].append(r["f"].replace("public.", ""))
    return tables


async def _count(conn, sql: str) -> int | None:
    try:
        return int(await conn.fetchval(sql))
    except Exception:
        return None


@router.get("/db/schema")
async def db_schema(ctx: CtxDep, source: str = Query("org", pattern="^(org|control)$")):
    pool = await _pool(ctx, source)
    async with pool.acquire() as conn:
        tables = await _tables(conn)
        migrations = []
        if "schema_migrations" in tables:
            migrations = rows(
                await conn.fetch(
                    "SELECT version, applied_at, applied_by FROM schema_migrations ORDER BY applied_at DESC, version DESC LIMIT 60"
                )
            )
        changes = []
        if source == "org" and "schema_changes" in tables:
            changes = rows(
                await conn.fetch(
                    "SELECT summary, status, error, by_label, created_at, sql_up, sql_down FROM schema_changes "
                    "WHERE org_id = $1 ORDER BY created_at DESC LIMIT 30",
                    ctx.org_id,
                )
            )
        stats = {
            "tables": len(tables),
            "workflows": await _count(conn, "SELECT count(*) FROM workflows")
            if "workflows" in tables
            else None,
            "roles": await _count(conn, "SELECT count(*) FROM roles")
            if "roles" in tables
            else None,
            "migrations": await _count(conn, "SELECT count(*) FROM schema_migrations")
            if migrations
            else 0,
        }
    return {
        "source": source,
        "sources": [
            {"key": "org", "label": ctx.org_name + " (this organisation)"},
            {
                "key": "control",
                "label": "Control (sign-ins and the list of organisations)",
            },
        ],
        "stats": stats,
        "tables": sorted(tables.values(), key=lambda t: t["name"]),
        "migrations": migrations,
        "changes": changes,
    }


# ───────────────────────── what the AI is told ─────────────────────────


async def context_text(ctx: Ctx) -> str:
    """The database as the AI sees it: tables and columns, roles, flows, the steps the engine can run, use cases."""
    from app.services.step_catalog import STEP_TYPES

    pool = await get_pool(ctx.source_key)
    async with pool.acquire() as conn:
        tables = await _tables(conn)
        roles = [
            r["name"]
            for r in await conn.fetch(
                "SELECT name FROM roles WHERE org_id = $1 ORDER BY name", ctx.org_id
            )
        ]
        flows = [
            f"{r['intent_key']} ({r['name']})"
            for r in await conn.fetch(
                "SELECT intent_key, name FROM workflows WHERE org_id = $1 ORDER BY name",
                ctx.org_id,
            )
        ]
        usecases = []
        if "usecases" in tables:
            usecases = [
                f"{r['name']} keeps {r['record_type']}s"
                for r in await conn.fetch(
                    "SELECT name, record_type FROM usecases WHERE org_id = $1",
                    ctx.org_id,
                )
            ]
    platform = {
        "schema_migrations",
        "admin_events",
        "audit_log",
        "workflow_versions",
        "archived_rows",
    }
    lines = [
        f"Organisation: {ctx.org_name}. PostgreSQL. Every client table has org_id uuid REFERENCES orgs(id).",
        "",
        "Tables:",
    ]
    for t in sorted(tables.values(), key=lambda t: t["name"]):
        if t["name"] in platform:
            continue
        cols = ", ".join(f"{c['name']} {c['type']}" for c in t["columns"][:40])
        lines.append(f"  {t['name']}({cols})")
    lines += ["", "Roles: " + ", ".join(roles), "", "Flows: " + ", ".join(flows)]
    if usecases:
        lines += ["", "Use cases: " + ", ".join(usecases)]
    lines += [
        "",
        "Steps the engine can run: " + ", ".join(sorted({s["op"] for s in STEP_TYPES})),
    ]
    return "\n".join(lines)


@router.get("/db/builder/context")
async def builder_context(ctx: CtxDep):
    return {"text": await context_text(ctx)}


# ───────────────────────── the AI drafts ─────────────────────────


def _system_text() -> str:
    """The change builder's job (app/prompts/change_builder.txt)."""
    from app.services.prompt_loader import PROMPTS_DIR, _read

    return _read(PROMPTS_DIR / "change_builder.txt") or ""


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[dict] = Field(default_factory=list, max_length=40)


def _json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0) if m else text)


def _plan_out(p: dict) -> dict:
    def text(v):
        return v if isinstance(v, str) else ""

    def strs(v):
        return [str(x)[:300] for x in v][:20] if isinstance(v, list) else []

    return {
        "intro": text(p.get("intro"))[:2000],
        "new": strs(p.get("new")),
        "reuse": strs(p.get("reuse")),
        "engine": strs(p.get("engine")),
        "notes": strs(p.get("notes")),
        "sql": text(p.get("sql"))[:MAX_SQL],
        "seed": text(p.get("seed"))[:MAX_SQL],
        "rollback": text(p.get("rollback"))[:MAX_SQL],
        "workflows": json.dumps(
            p.get("workflows") if isinstance(p.get("workflows"), list) else [],
            indent=2,
            ensure_ascii=False,
        ),
        "permissions": json.dumps(
            p.get("permissions") if isinstance(p.get("permissions"), dict) else {},
            indent=2,
            ensure_ascii=False,
        ),
    }


@router.post("/db/builder/chat")
async def builder_chat(ctx: CtxDep, body: ChatBody):
    from app.services import platform_prompt
    from app.services.llm_router import chat_completion

    convo = [
        {
            "role": "system",
            "content": await platform_prompt.preamble(getattr(ctx, "source_key", None))
            + "\n\n"
            + _system_text(),
        },
        {"role": "system", "content": "The database:\n" + await context_text(ctx)},
    ]
    for m in body.messages[-20:]:
        role = "assistant" if m.get("role") == "assistant" else "user"
        convo.append({"role": role, "content": str(m.get("content") or "")[:4000]})
    try:
        resp = await chat_completion(messages=convo, max_tokens=4000, temperature=0.2)
        data = _json(resp.choices[0].message.content)
    except Exception as e:
        logger.warning(f"db builder: the AI could not draft ({e!r})")
        return {
            "say": "I could not draft that just now. Try again, or write the plan yourself in the tabs.",
            "questions": [],
            "reading": [],
            "plan": None,
        }
    reading = [
        [
            str(r[0])[:200],
            str(r[1])[:300],
            r[2] if r[2] in ("new", "reuse", "engine") else "new",
        ]
        for r in (data.get("reading") or [])
        if isinstance(r, list) and len(r) >= 3
    ][:12]
    questions = [
        {
            "text": str(q.get("text"))[:200],
            "options": [str(o)[:80] for o in (q.get("options") or [])][:5],
        }
        for q in (data.get("questions") or [])
        if isinstance(q, dict) and q.get("text")
    ][:3]
    plan = _plan_out(data["plan"]) if isinstance(data.get("plan"), dict) else None
    return {
        "say": str(data.get("say") or "")[:1000],
        "reading": reading,
        "questions": questions,
        "plan": plan,
    }


# ───────────────────────── checking a plan ─────────────────────────


class PlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str = Field("", max_length=MAX_SQL)
    seed: str = Field("", max_length=MAX_SQL)
    rollback: str = Field("", max_length=MAX_SQL)
    workflows: str = Field("[]", max_length=MAX_SQL)
    permissions: str = Field("{}", max_length=20_000)
    summary: str = Field("", max_length=2000)


def split_sql(text: str) -> list[str]:
    """Statements, split on ; outside quotes and $$ bodies; comments dropped."""
    out, cur, i, n = [], [], 0, len(text or "")
    quote, dollar = None, None
    while i < n:
        ch = text[i]
        if dollar:
            if text.startswith(dollar, i):
                cur.append(dollar)
                i += len(dollar)
                dollar = None
                continue
        elif quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "-" and text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif ch == "$":
            m = re.match(r"\$[A-Za-z_]*\$", text[i:])
            if m:
                dollar = m.group(0)
                cur.append(dollar)
                i += len(dollar)
                continue
        elif ch == ";":
            s = "".join(cur).strip()
            if s:
                out.append(s)
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    s = "".join(cur).strip()
    if s:
        out.append(s)
    return out


_CREATE = re.compile(
    r"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?(public\.)?\"?([a-z_][a-z0-9_]*)\"?\s*\((.*)\)",
    re.IGNORECASE | re.DOTALL,
)
_ALTER = re.compile(
    r"ALTER\s+TABLE\s+(IF\s+EXISTS\s+)?(ONLY\s+)?(public\.)?\"?([a-z_][a-z0-9_]*)\"?\s+(.*)",
    re.IGNORECASE | re.DOTALL,
)


def lint(
    plan: PlanBody, tables: dict[str, set[str]], roles: set[str], flows: dict
) -> tuple[list[dict], dict[str, set[str]]]:
    """Problems with a plan, as [{level, tab, msg}], and the tables it would add (for checking its flows)."""
    from app.services.step_catalog import validate_steps

    issues: list[dict] = []
    made: dict[str, set[str]] = {}

    def add(level, tab, msg):
        issues.append({"level": level, "tab": tab, "msg": msg})

    for tab, text in (("sql", plan.sql), ("seed", plan.seed)):
        for st in split_sql(text):
            head = " ".join(st.split())[:90]
            bare = re.sub(
                r"'(?:[^']|'')*'", "''", st
            )  # words inside text values do not count
            bare = re.sub(
                r"ON\s+(DELETE|UPDATE)\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION)",
                "",
                bare,
                flags=re.IGNORECASE,
            )
            if _FORBIDDEN.search(bare):
                add("error", tab, f"Not allowed here (it removes or rewrites): {head}")
                continue
            if not _ALLOWED.match(st):
                add(
                    "error",
                    tab,
                    f"Only new tables, columns, indexes, comments and rows can be applied here: {head}",
                )
                continue
            if tab == "seed" and not re.match(r"^INSERT\s+INTO", st, re.IGNORECASE):
                add("error", tab, f"Seed rows are INSERT statements only: {head}")
            m = _CREATE.match(st)
            if m:
                name, if_not = m.group(3).lower(), bool(m.group(1))
                if name in tables and not if_not:
                    add("error", "sql", f"The table {name} already exists.")
                cols = set()
                for part in re.split(r",(?![^(]*\))", m.group(4)):
                    word = part.strip().split()
                    if word and word[0].upper() not in (
                        "CONSTRAINT",
                        "PRIMARY",
                        "UNIQUE",
                        "CHECK",
                        "FOREIGN",
                        "EXCLUDE",
                    ):
                        cols.add(word[0].strip('"').lower())
                made[name] = cols
                if "org_id" not in cols:
                    add(
                        "warn",
                        "sql",
                        f"{name} has no org_id: every client table should belong to an organisation.",
                    )
                continue
            m = _ALTER.match(st)
            if m:
                name, rest = m.group(4).lower(), m.group(5)
                if name not in tables and name not in made:
                    add("error", "sql", f"There is no table {name} to change.")
                if re.search(
                    r"\b(DROP|ALTER\s+COLUMN|RENAME|TYPE)\b", rest, re.IGNORECASE
                ):
                    add("error", "sql", f"Only adding is allowed when changing {name}.")
                for c in re.findall(
                    r"ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?\"?([a-z_][a-z0-9_]*)",
                    rest,
                    re.IGNORECASE,
                ):
                    if c.upper() not in ("CONSTRAINT",):
                        made.setdefault(name, set()).add(c.lower())
                continue
            m = re.match(
                r"^CREATE\s+EXTENSION\s+(IF\s+NOT\s+EXISTS\s+)?\"?([a-z_]+)",
                st,
                re.IGNORECASE,
            )
            if m and m.group(2).lower() not in EXTENSIONS:
                add(
                    "error",
                    "sql",
                    f"Only these extensions may be added: {', '.join(sorted(EXTENSIONS))}.",
                )
    if not split_sql(plan.sql) and not split_sql(plan.seed):
        add(
            "error", "sql", "There is nothing to apply: the SQL and the seed are empty."
        )
    if not split_sql(plan.rollback):
        add(
            "warn",
            "rollback",
            "There is no way back. Always keep the SQL that undoes the change.",
        )

    schema = {t: set(c) for t, c in tables.items()}
    for t, cols in made.items():
        schema.setdefault(t, set()).update(cols)
    try:
        wfs = json.loads(plan.workflows or "[]")
        if not isinstance(wfs, list):
            raise TypeError
    except (ValueError, TypeError):
        add("error", "workflows", "The flows are not valid JSON (a list of flows).")
        wfs = []
    names = set()
    for w in wfs:
        if not isinstance(w, dict) or not str(w.get("name") or "").strip():
            add("error", "workflows", "Every flow needs a name.")
            continue
        names.add(w["name"].strip())
        check = validate_steps(
            w.get("steps") or [],
            schema=schema,
            entity_schema=w.get("entity_schema") or {},
            workflows=flows,
        )
        for e in check["errors"]:
            add("error", "workflows", f"{w['name']}: {e}")
        for e in check["warnings"]:
            add("warn", "workflows", f"{w['name']}: {e}")
    try:
        perms = json.loads(plan.permissions or "{}")
        if not isinstance(perms, dict):
            raise TypeError
    except (ValueError, TypeError):
        add(
            "error",
            "permissions",
            'Who may use the flows is not valid JSON ({"flow name": ["role"]}).',
        )
        perms = {}
    for flow, rs in perms.items():
        if flow not in names:
            add(
                "warn", "permissions", f"“{flow}” is not one of the flows in this plan."
            )
        for r in rs if isinstance(rs, list) else []:
            if r not in roles:
                add("error", "permissions", f"There is no role called “{r}”.")
    return issues, made


def fingerprint(plan: PlanBody) -> str:
    raw = json.dumps(
        [plan.sql, plan.seed, plan.workflows, plan.permissions], ensure_ascii=False
    )
    return hashlib.sha256(raw.encode()).hexdigest()


async def _check(ctx: Ctx, plan: PlanBody) -> dict:
    from app.admin_panel.studio import load_schema, load_workflows

    tables = await load_schema(ctx)
    pool = await get_pool(ctx.source_key)
    async with pool.acquire() as conn:
        roles = {
            r["name"]
            for r in await conn.fetch(
                "SELECT name FROM roles WHERE org_id = $1", ctx.org_id
            )
        }
    issues, made = lint(plan, tables, roles, await load_workflows(ctx))
    ran: list[str] = []
    tried = False
    if not any(i["level"] == "error" for i in issues):
        tried = True
        async with pool.acquire() as conn:
            tr = conn.transaction()
            await tr.start()
            try:
                await conn.execute(
                    "SET LOCAL lock_timeout = '3s'; SET LOCAL statement_timeout = '20s'"
                )
                for st in split_sql(plan.sql) + split_sql(plan.seed):
                    try:
                        await conn.execute(st)
                        ran.append(" ".join(st.split())[:110])
                    except Exception as e:
                        issues.append(
                            {
                                "level": "error",
                                "tab": "sql",
                                "msg": f"The database refused: {' '.join(st.split())[:80]} → {e}",
                            }
                        )
                        break
            finally:
                await tr.rollback()  # nothing is kept
    ok = not any(i["level"] == "error" for i in issues)
    return {
        "ok": ok,
        "issues": issues,
        "ran": ran,
        "tried": tried,
        "new_tables": sorted(made),
        "fingerprint": fingerprint(plan) if ok else None,
    }


@router.post("/db/builder/validate")
async def builder_validate(ctx: CtxDep, body: PlanBody):
    return await _check(ctx, body)


class ApplyBody(PlanBody):
    fingerprint: str = Field(min_length=64, max_length=64)
    backup_taken: bool = False


@router.post("/db/builder/apply")
async def builder_apply(ctx: CtxDep, body: ApplyBody):
    if not body.backup_taken:
        raise HTTPException(
            409, "Take a backup of this database first, then tick “A backup was taken”."
        )
    plan = PlanBody(**body.model_dump(exclude={"fingerprint", "backup_taken"}))
    if fingerprint(plan) != body.fingerprint:
        raise HTTPException(
            409,
            "The plan changed after it was checked. Check it again before applying.",
        )
    checked = await _check(ctx, plan)  # again, against the database as it is now
    if not checked["ok"]:
        raise HTTPException(
            409,
            "The plan no longer passes the checks: "
            + "; ".join(i["msg"] for i in checked["issues"] if i["level"] == "error")[
                :600
            ],
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    pool = await get_pool(ctx.source_key)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL lock_timeout = '5s'")
        for st in split_sql(plan.sql) + split_sql(plan.seed):
            await conn.execute(st)
        has = await conn.fetchval(
            "SELECT to_regclass('public.schema_changes') IS NOT NULL"
        )
        if has:
            await conn.execute(
                "INSERT INTO schema_changes (org_id, summary, ops, sql_up, sql_down, status, by_label) VALUES ($1, $2, '[]'::jsonb, $3, $4, 'applied', $5)",
                ctx.org_id, (plan.summary or "A change from the AI change builder")[:2000],
                (plan.sql + "\n\n" + plan.seed).strip(), plan.rollback, ctx.actor or "",
            )  # fmt: skip
        if await conn.fetchval(
            "SELECT to_regclass('public.schema_migrations') IS NOT NULL"
        ):
            await conn.execute(
                "INSERT INTO schema_migrations (version, checksum, applied_by) VALUES ($1, $2, $3) ON CONFLICT (version) DO NOTHING",
                f"builder-{stamp}", body.fingerprint, (ctx.actor or "dashboard")[:120],
            )  # fmt: skip
        await log_event(ctx, "schema", "apply", (plan.summary or "Applied a change from the AI change builder")[:500],
                        target_type="schema", target_id=None, after={"version": f"builder-{stamp}"}, conn=conn)  # fmt: skip
    # the new tables are now real: everything that remembers the schema reads it again
    from app.admin_panel import common
    from app.services import step_interpreter

    common._caps_cache.clear()
    step_interpreter._schema_allowlist.pop(ctx.source_key, None)
    made_flows, flow_problems = await _make_flows(ctx, plan)
    return {
        "ok": True,
        "version": f"builder-{stamp}",
        "flows": made_flows,
        "flow_problems": flow_problems,
    }


async def _make_flows(ctx: Ctx, plan: PlanBody) -> tuple[list[str], list[str]]:
    """Each flow of the plan, made switched off with its roles; one that fails does not stop the others."""
    from app.admin_panel import studio, workflows

    made, problems = [], []
    try:
        wfs = json.loads(plan.workflows or "[]")
        perms = json.loads(plan.permissions or "{}")
    except ValueError:
        return made, ["The flows could not be read."]
    for w in wfs if isinstance(wfs, list) else []:
        try:
            r = await studio.create_workflow(
                studio.NewWorkflow(
                    name=str(w.get("name"))[:120], kind="workflow", description=str(w.get("description") or "")[:1500] or None,
                    steps=w.get("steps") or [], entity_schema=w.get("entity_schema") or {},
                    training_phrases=[str(x)[:200] for x in (w.get("training_phrases") or [])][:40],
                ),
                ctx,
            )  # fmt: skip
            roles = perms.get(w.get("name")) if isinstance(perms, dict) else None
            if roles:
                await workflows.set_roles(
                    r["id"], workflows.RolesBody(roles=list(roles)), ctx
                )
            made.append(str(w.get("name")))
        except HTTPException as e:
            problems.append(f"{w.get('name')}: {e.detail}")
        except Exception as e:
            problems.append(f"{w.get('name')}: {e}")
    return made, problems
