"""
Shared plumbing for the redesigned admin panel (everything under /admin/{org}/api/v2).

Design rules for this package:
  * The panel only VIEWS data and edits CONFIGURATION (categories, routing rules, seats,
    access, roles, workflow on/off, resident status). It never decides what happens to a
    case: assigning, closing, commenting and telling people stay in the org's workflows.
    So there is no business wording and no case behaviour in this code.
  * Nothing assumes which tables an org has. A capability probe tells every endpoint and
    the page what this org's database supports; sections it cannot use do not appear.
  * Allowed values (case statuses, priorities, seat kinds, resident types...) are read
    from the database's own CHECK constraints, and "closed" statuses from the org's
    existing case_reminders setting, instead of being listed here.
"""

import json
import re
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import unquote

import asyncpg
from fastapi import Depends, HTTPException, Request
from fastapi.routing import APIRoute

from app.db import fetch_all, fetch_one, get_all_source_keys, get_pool
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

# ── capabilities ─────────────────────────────────────────────────────────────

_CAPS_TTL_SECONDS = 20
_caps_cache: dict[str, tuple[float, dict[str, bool]]] = {}

_CAPS_SQL = """
SELECT
  to_regclass('public.cases') IS NOT NULL                     AS cases,
  to_regclass('public.case_activity') IS NOT NULL             AS case_activity,
  to_regclass('public.case_categories') IS NOT NULL           AS categories,
  to_regclass('public.routing_rules') IS NOT NULL             AS routing,
  to_regclass('public.case_parties') IS NOT NULL              AS parties,
  to_regclass('public.access_grants') IS NOT NULL             AS grants,
  to_regclass('public.admin_events') IS NOT NULL              AS events,
  (to_regclass('public.committee_positions') IS NOT NULL
   AND to_regclass('public.committee_members') IS NOT NULL)   AS seats,
  to_regclass('public.residents') IS NOT NULL                 AS residents,
  to_regclass('public.audit_log') IS NOT NULL                 AS audit,
  to_regclass('public.priority_tat_rules') IS NOT NULL        AS targets,
  to_regproc('public.route_case') IS NOT NULL                 AS route_fn,
  EXISTS (SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'cases'
             AND column_name = 'category_id')                 AS case_category,
  EXISTS (SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'committee_positions'
             AND column_name = 'kind')                        AS seat_kind,
  EXISTS (SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'workflows'
             AND column_name = 'kind')                        AS workflow_kind
"""

# Everything the new case model adds. "case_model" is true only when all of it is there,
# so a half-applied migration never shows half a screen.
CASE_MODEL_PARTS = (
    "cases",
    "case_activity",
    "categories",
    "routing",
    "parties",
    "grants",
    "events",
    "seats",
    "case_category",
    "seat_kind",
    "route_fn",
)

_CAP_MESSAGES = {
    "cases": "This organisation does not track cases.",
    "case_model": (
        "The case model (categories, routing rules, seats, access) is not installed in "
        "this organisation's database yet. Run its case-model migration first."
    ),
    "seats": "This organisation's database has no seats (committee positions).",
    "residents": "This organisation does not keep a resident list.",
    "audit": "This organisation has no chat log.",
    "targets": "This organisation has no response-time table.",
}


async def get_caps(source_key: str) -> dict[str, bool]:
    now = time.monotonic()
    hit = _caps_cache.get(source_key)
    if hit and now - hit[0] < _CAPS_TTL_SECONDS:
        return hit[1]
    row = await fetch_one(_CAPS_SQL, source_key=source_key)
    caps = {k: bool(v) for k, v in dict(row).items()}
    caps["case_model"] = all(caps[k] for k in CASE_MODEL_PARTS)
    _caps_cache[source_key] = (now, caps)
    return caps


# ── request context ──────────────────────────────────────────────────────────


@dataclass
class Ctx:
    source_key: str
    org_id: str
    org_name: str
    caps: dict[str, bool]
    actor: str  # who to write in the change log
    closed_values: list[str]  # case statuses that mean "finished"

    def need(self, *caps: str) -> None:
        """Refuse politely when this org's database cannot do what was asked."""
        for cap in caps:
            if not self.caps.get(cap):
                raise HTTPException(
                    status_code=409,
                    detail=_CAP_MESSAGES.get(cap, f"'{cap}' is not available here."),
                )


async def get_ctx(org_slug: str, request: Request) -> Ctx:
    """FastAPI dependency. The URL's org segment IS the source_key (see admin.py)."""
    if org_slug not in await get_all_source_keys():
        raise HTTPException(status_code=404, detail=f"Unknown org '{org_slug}'")
    org = await fetch_one(
        "SELECT id, name, settings FROM orgs WHERE is_active = true LIMIT 1",
        source_key=org_slug,
    )
    if not org:
        raise HTTPException(status_code=404, detail="No active org found")
    settings = jb(org["settings"], {})
    # same setting, same default, that the case reminder job already uses
    closed = (settings.get("case_reminders") or {}).get("closed_values") or ["closed"]
    name = unquote(request.headers.get("X-Admin-Name") or "").strip()[:60]
    return Ctx(
        source_key=org_slug,
        org_id=str(org["id"]),
        org_name=org["name"],
        caps=await get_caps(org_slug),
        actor=f"dashboard · {name}" if name else "dashboard",
        closed_values=list(closed),
    )


CtxDep = Annotated[Ctx, Depends(get_ctx)]


# ── allowed values, read from the database's own rules ───────────────────────

_check_cache: dict[tuple[str, str, str], list[str]] = {}


async def check_values(ctx: Ctx, table: str, column: str) -> list[str]:
    """The values a column may hold, in declared order, read from the table's CHECK
    constraint. Empty when the column has no such constraint."""
    key = (ctx.source_key, table, column)
    if key in _check_cache:
        return _check_cache[key]
    found = await fetch_all(
        "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint "
        "WHERE conrelid = to_regclass($1) AND contype = 'c'",
        f"public.{table}",
        source_key=ctx.source_key,
    )
    pattern = re.compile(rf"\b{re.escape(column)}\)?(::text)?\s*=\s*ANY")
    for r in found:
        if pattern.search(r["d"]):
            values = re.findall(r"'([^']*)'::", r["d"])
            if values:
                _check_cache[key] = values
                return values
    return []


def check_choice(value: str, allowed: list[str], what: str) -> str:
    if allowed and value not in allowed:
        raise HTTPException(
            status_code=400, detail=f"{what} must be one of: {', '.join(allowed)}"
        )
    return value


# ── turning database refusals into plain sentences ───────────────────────────


def _pg_problem(e: asyncpg.PostgresError, reading: bool) -> tuple[int, str]:
    if isinstance(e, asyncpg.UniqueViolationError):
        return 409, "That already exists."
    if isinstance(e, asyncpg.ForeignKeyViolationError):
        return 409, "That is still in use somewhere else, so it cannot be removed."
    if isinstance(e, asyncpg.CheckViolationError):
        return 400, "One of the values is not allowed."
    if isinstance(e, asyncpg.RaiseError):  # RAISE EXCEPTION in a trigger or function
        return 400, e.message
    return 500, (
        "The database could not answer that."
        if reading
        else "The database refused that change."
    )


class PanelRoute(APIRoute):
    """Route class for every panel endpoint: a database refusal becomes a clear message
    for the admin instead of a bare 500."""

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except asyncpg.PostgresError as e:
                status, message = _pg_problem(e, request.method == "GET")
                if status == 500:
                    logger.error(f"admin panel database error: {e!r}")
                raise HTTPException(status_code=status, detail=message) from e

        return handler


# ── small helpers ────────────────────────────────────────────────────────────


def jb(value: Any, default: Any) -> Any:
    """asyncpg hands jsonb back as text; this gives the parsed value or a default."""
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value


def dump(value: Any) -> str | None:
    """JSON text for a jsonb parameter (cast the placeholder with ::jsonb)."""
    return None if value is None else json.dumps(value, default=str)


def rows(records) -> list[dict]:
    return [dict(r) for r in records]


def mask_phone(phone: str | None) -> str | None:
    """Enough to tell two people apart, not enough to message them."""
    return None if not phone else f"••••{phone[-4:]}"


@asynccontextmanager
async def tx(ctx: Ctx):
    """One connection, one transaction. db.py's helpers each take their own connection,
    so anything that must change several tables together goes through here."""
    pool = await get_pool(ctx.source_key)
    async with pool.acquire() as conn, conn.transaction():
        yield conn


async def log_event(
    ctx: Ctx,
    area: str,
    action: str,
    summary: str,
    *,
    target_type: str | None = None,
    target_id: Any = None,
    before: Any = None,
    after: Any = None,
    conn=None,
) -> None:
    """Write a line in admin_events. Pass `conn` to make it part of the caller's
    transaction. Without it the line is best effort (a missing log table never blocks
    a change)."""
    if not ctx.caps.get("events"):
        return
    sql = """
        INSERT INTO admin_events
            (org_id, actor_label, area, action, target_type, target_id, summary,
             before_state, after_state)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb)
    """
    args = (
        ctx.org_id,
        ctx.actor,
        area,
        action,
        target_type,
        None if target_id is None else str(target_id),
        summary,
        dump(before),
        dump(after),
    )
    if conn is not None:
        await conn.execute(sql, *args)
        return
    try:
        pool = await get_pool(ctx.source_key)
        async with pool.acquire() as c:
            await c.execute(sql, *args)
    except Exception as e:
        logger.warning(f"admin_events write failed: {e}")
