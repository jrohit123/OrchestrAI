"""People and access: who is who, which seat they hold, and what special access they have.

Everything here edits configuration rows (a person's role, a seat's holder, an access
grant, a resident's status). What those rows then mean to the bot is decided elsewhere."""

import re
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.admin_panel.cases import query_cases
from app.admin_panel.common import (
    Ctx,
    CtxDep,
    PanelRoute,
    check_choice,
    check_values,
    dump,
    jb,
    log_event,
    mask_phone,
    people_channel,
    rows,
    tx,
)
from app.db import fetch_all, fetch_one, routing_pool
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

# Same test route_targets() uses in the database, so "can be reached" means the same thing
# on this screen as it does when a routing rule picks someone.
_REACHABLE = (
    "((u.channel = 'telegram' AND u.phone LIKE 'tg:%') "
    "OR (COALESCE(u.channel, '') <> 'telegram' AND COALESCE(u.phone, '') <> ''))"
)


def _person_columns(ctx: Ctx) -> str:
    """Columns for one person. $2 (the org's 'closed' statuses) is always used through
    the cfg CTE the callers start with."""
    cols = [
        "u.id",
        "u.name",
        "u.email",
        "u.phone",
        "u.channel",
        "u.is_active",
        "u.created_at",
        "u.role_id",
        "r.name AS role",
        f"{_REACHABLE} AS reachable",
    ]
    if ctx.caps.get("cases"):
        cols.append(
            "(SELECT count(*) FROM cases c WHERE c.assigned_to_id = u.id "
            "AND NOT (c.status = ANY((SELECT closed FROM cfg)::text[]))) AS open_assigned"
        )
        cols.append(
            "(SELECT count(*) FROM cases c WHERE c.complainant_id = u.id) AS raised"
        )
    else:
        cols += ["0 AS open_assigned", "0 AS raised"]
    if ctx.caps.get("seats"):
        kind = "p.kind" if ctx.caps.get("seat_kind") else "NULL::text"
        cols.append(
            "(SELECT COALESCE(jsonb_agg(jsonb_build_object('id', p.id, 'name', p.name, "
            f"'kind', {kind}) ORDER BY p.name), '[]'::jsonb) "
            "FROM committee_members m JOIN committee_positions p ON p.id = m.position_id "
            "WHERE m.user_id = u.id AND m.status = 'active') AS seats"
        )
    else:
        cols.append("'[]'::jsonb AS seats")
    if ctx.caps.get("residents"):
        more = (
            ", 'relation', h.relation, 'is_primary', h.is_primary, 'lives_here', h.lives_here"
            if ctx.caps.get("flat_people")
            else ""
        )
        cols.append(
            "(SELECT COALESCE(jsonb_agg(jsonb_build_object('id', h.id, 'wing', h.wing, "
            "'flat_no', h.flat_no, 'residential_status', h.residential_status, "
            f"'status', h.status{more}) ORDER BY h.wing, h.flat_no), '[]'::jsonb) "
            "FROM residents h WHERE h.user_id = u.id) AS homes"
        )
    else:
        cols.append("'[]'::jsonb AS homes")
    if ctx.caps.get("grants"):
        cols.append(
            "(SELECT count(*) FROM access_grants g WHERE g.user_id = u.id "
            "AND g.revoked_at IS NULL AND (g.valid_to IS NULL OR g.valid_to >= CURRENT_DATE)"
            ") AS live_grants"
        )
    else:
        cols.append("0 AS live_grants")
    return ", ".join(cols)


_CFG = "WITH cfg AS (SELECT $2::text[] AS closed) "


async def _dashboard_access(ctx: Ctx, emails: list[str | None]) -> dict[str, dict]:
    """Which of these people can sign in to the dashboard, read from the sign-in accounts (they
    live in the routing database). A courtesy: a problem gives nothing here and never an error."""
    wanted = sorted({e.strip().lower() for e in emails if e})
    if not wanted:
        return {}
    try:
        found = await routing_pool().fetch(
            "SELECT id, email, level, status, source_keys FROM panel_accounts "
            "WHERE email = ANY($1::text[])",
            wanted,
        )
    except Exception as e:
        logger.warning(f"dashboard access not read: {e!r}")
        return {}
    out: dict[str, dict] = {}
    for r in found:
        if r["level"] == "admin" and ctx.source_key not in (r["source_keys"] or ()):
            continue
        out[r["email"]] = {"level": r["level"], "status": r["status"]}
        if ctx.level == "super":
            out[r["email"]]["account_id"] = str(r["id"])
    return out


def _shape_person(p: dict) -> dict:
    p["seats"] = jb(p["seats"], [])
    p["homes"] = jb(p["homes"], [])
    p["phone_hint"] = mask_phone(p.pop("phone", None))
    return p


@router.get("/people")
async def list_people(
    ctx: CtxDep,
    q: str | None = None,
    role: UUID | None = None,
    status: Literal["active", "inactive"] | None = None,
    reachable: bool | None = None,
    seat: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
):
    params: list = [ctx.org_id, ctx.closed_values]
    where = ["u.org_id = $1"]

    def add(value) -> str:
        params.append(value)
        return f"${len(params)}"

    if q:
        like = add(f"%{q.strip()}%")
        clause = f"u.name ILIKE {like} OR u.email ILIKE {like} OR u.phone ILIKE {like}"
        if ctx.caps.get("residents"):
            clause += (
                " OR EXISTS (SELECT 1 FROM residents h WHERE h.user_id = u.id AND "
                f"(h.flat_no ILIKE {like} OR (COALESCE(h.wing, '') || '-' || h.flat_no) ILIKE {like}))"
            )
        where.append(f"({clause})")
    if role:
        where.append(f"u.role_id = {add(role)}")
    if status:
        where.append("u.is_active" if status == "active" else "NOT u.is_active")
    if reachable is not None:
        where.append(_REACHABLE if reachable else f"NOT {_REACHABLE}")
    if seat and ctx.caps.get("seats"):
        where.append(
            "EXISTS (SELECT 1 FROM committee_members m WHERE m.user_id = u.id "
            f"AND m.status = 'active' AND m.position_id = {add(seat)})"
        )
    base = f"FROM users u LEFT JOIN roles r ON r.id = u.role_id WHERE {' AND '.join(where)}"
    total = await fetch_one(
        f"{_CFG}SELECT count(*) AS n {base}", *params, source_key=ctx.source_key
    )
    found = await fetch_all(
        f"{_CFG}SELECT {_person_columns(ctx)} {base} ORDER BY u.name "
        f"LIMIT {page_size} OFFSET {(page - 1) * page_size}",
        *params,
        source_key=ctx.source_key,
    )
    people = [_shape_person(p) for p in rows(found)]
    access = await _dashboard_access(ctx, [p["email"] for p in people])
    for p in people:
        p["dashboard"] = access.get((p["email"] or "").lower())
    return {
        "rows": people,
        "total": total["n"],
        "page": page,
        "page_size": page_size,
    }


@router.get("/people/{user_id}")
async def person_detail(ctx: CtxDep, user_id: UUID):
    row = await fetch_one(
        f"{_CFG}SELECT {_person_columns(ctx)} FROM users u "
        "LEFT JOIN roles r ON r.id = u.role_id WHERE u.org_id = $1 AND u.id = $3",
        ctx.org_id,
        ctx.closed_values,
        user_id,
        source_key=ctx.source_key,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    person = _shape_person(dict(row))
    person["dashboard"] = (await _dashboard_access(ctx, [person["email"]])).get(
        (person["email"] or "").lower()
    )

    homes: list[dict] = []
    if ctx.caps.get("residents"):
        more = (
            ", relation, is_primary, lives_here" if ctx.caps.get("flat_people") else ""
        )
        homes = rows(
            await fetch_all(
                f"SELECT id, name, wing, flat_no, residential_status, status{more}, "
                "registration_date, suspension_date FROM residents "
                "WHERE org_id = $1 AND user_id = $2 ORDER BY wing, flat_no",
                ctx.org_id,
                user_id,
                source_key=ctx.source_key,
            )
        )

    seat_history: list[dict] = []
    if ctx.caps.get("seats"):
        seat_history = rows(
            await fetch_all(
                "SELECT m.id, p.name AS seat, m.status, m.start_date, m.end_date "
                "FROM committee_members m JOIN committee_positions p ON p.id = m.position_id "
                "WHERE m.user_id = $1 ORDER BY (m.status = 'active') DESC, m.start_date DESC",
                user_id,
                source_key=ctx.source_key,
            )
        )

    grants: list[dict] = []
    if ctx.caps.get("grants"):
        grants = await list_grants_sql(ctx, "g.user_id = $2", user_id)

    cases: dict = {"handling": [], "raised": []}
    if ctx.caps.get("cases"):
        cases["handling"], _ = await query_cases(
            ctx, assignee=str(user_id), sort="newest", limit=8
        )
        cases["raised"], _ = await query_cases(
            ctx, requester=str(user_id), sort="newest", limit=8
        )

    chats = None
    if ctx.caps.get("audit"):
        c = await fetch_one(
            "SELECT count(*) AS turns, count(DISTINCT session_id) AS sessions, "
            "max(created_at) AS last_at FROM audit_log WHERE org_id = $1 AND user_id = $2",
            ctx.org_id,
            user_id,
            source_key=ctx.source_key,
        )
        chats = dict(c) if c else None

    return {
        "person": person,
        "homes": homes,
        "seat_history": seat_history,
        "grants": grants,
        "cases": cases,
        "chats": chats,
    }


class PersonPatch(BaseModel):
    role_id: UUID | None = None
    is_active: bool | None = None


@router.patch("/people/{user_id}")
async def update_person(ctx: CtxDep, user_id: UUID, body: PersonPatch):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    if "role_id" in changes and changes["role_id"] is None:
        raise HTTPException(status_code=400, detail="Pick a role.")
    if ctx.level != "super" and set(changes) - {"role_id"}:
        raise HTTPException(
            status_code=403,
            detail="Only a super admin can switch a person on or off. You can change a role.",
        )
    async with tx(ctx) as conn:
        before = await conn.fetchrow(
            "SELECT u.name, u.email, u.role_id, u.is_active, r.name AS role FROM users u "
            "LEFT JOIN roles r ON r.id = u.role_id WHERE u.id = $1 AND u.org_id = $2",
            user_id,
            ctx.org_id,
        )
        if not before:
            raise HTTPException(status_code=404, detail="Person not found")
        if (
            ctx.level != "super"
            and ctx.account_email
            and (before["email"] or "").lower() == ctx.account_email.lower()
        ):
            raise HTTPException(
                status_code=403,
                detail="You cannot change your own role. Ask a super admin.",
            )
        notes = []
        if "role_id" in changes:
            role = await conn.fetchrow(
                "SELECT id, name FROM roles WHERE id = $1 AND org_id = $2",
                changes["role_id"],
                ctx.org_id,
            )
            if not role:
                raise HTTPException(status_code=404, detail="Role not found")
            await conn.execute(
                "UPDATE users SET role_id = $1 WHERE id = $2", role["id"], user_id
            )
            notes.append(f"role {before['role'] or 'none'} → {role['name']}")
        if "is_active" in changes and changes["is_active"] is not None:
            await conn.execute(
                "UPDATE users SET is_active = $1 WHERE id = $2",
                changes["is_active"],
                user_id,
            )
            notes.append("made active" if changes["is_active"] else "made inactive")
        await log_event(
            ctx,
            "people",
            "update",
            f"{before['name']}: {', '.join(notes)}",
            target_type="user",
            target_id=user_id,
            before={"role_id": before["role_id"], "is_active": before["is_active"]},
            after=changes,
            conn=conn,
        )
    return {"ok": True}


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_phone(raw: str | None) -> str:
    """A number written the way people write it, kept the way the bot knows it: + and digits."""
    text = re.sub(r"[\s().-]", "", raw or "")
    if text.startswith("00"):
        text = "+" + text[2:]
    if not re.fullmatch(r"\+\d{8,15}", text):
        raise HTTPException(
            status_code=400,
            detail="Write the number with its country code, like +91 98765 43210.",
        )
    return text


class PersonNew(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., max_length=160)
    role_id: UUID
    phone: str | None = Field(None, max_length=40)


@router.post("/people")
async def add_person(ctx: CtxDep, body: PersonNew):
    """Add someone before they have ever written to the assistant. Their chat is linked by their email the
    first time they write (with a code emailed to them), so the email is enough, on Telegram and on WhatsApp.
    Where people are reached by number (WhatsApp) a number may be given as well; if it is, the assistant knows
    them by it from the start. Which of the two this organisation does is read from its database."""
    name = " ".join(body.name.split())
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Write the person's name.")
    email = body.email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(
            status_code=400, detail="That does not look like an email address."
        )
    phone = (
        None
        if await people_channel(ctx.source_key) == "telegram"
        or not (body.phone or "").strip()
        else clean_phone(body.phone)
    )
    role = await fetch_one(
        "SELECT id, name FROM roles WHERE id = $1 AND org_id = $2",
        body.role_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    clash = await fetch_one(
        "SELECT name FROM users WHERE org_id = $1 AND (lower(email) = $2 "
        "OR ($3::text IS NOT NULL AND phone = $3))",
        ctx.org_id,
        email,
        phone,
        source_key=ctx.source_key,
    )
    if clash:
        raise HTTPException(
            status_code=409,
            detail=f"{clash['name']} is already here with that email"
            + (" or number." if phone else "."),
        )
    async with tx(ctx) as conn:
        new_id = await conn.fetchval(
            "INSERT INTO users (org_id, role_id, name, email, phone) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            ctx.org_id,
            role["id"],
            name,
            email,
            phone,
        )
        await log_event(
            ctx,
            "people",
            "create",
            f"Added {name} as {role['name']}",
            target_type="user",
            target_id=new_id,
            after={"name": name, "role_id": role["id"], "has_number": bool(phone)},
            conn=conn,
        )
    return {"ok": True, "id": new_id}


class HomePatch(BaseModel):
    residential_status: str | None = None
    status: str | None = None
    wing: str | None = Field(None, max_length=40)
    flat_no: str | None = Field(None, min_length=1, max_length=40)
    relation: str | None = None
    is_primary: bool | None = None
    lives_here: bool | None = None


class HomeNew(BaseModel):
    wing: str | None = Field(None, max_length=40)
    flat_no: str = Field(..., min_length=1, max_length=40)
    relation: str
    is_primary: bool = False
    lives_here: bool = True


async def _check_home(ctx: Ctx, changes: dict) -> dict:
    """Checks the values of a home and puts the flat the way it is saved (trimmed, in capitals)."""
    for key in ("residential_status", "status", "flat_no", "relation"):
        if key in changes and not changes[key]:
            raise HTTPException(status_code=400, detail=f"{key} cannot be empty.")
    for key, what in (
        ("residential_status", "Resident type"),
        ("status", "Status"),
        ("relation", "Relation"),
    ):
        if key in changes:
            check_choice(changes[key], await check_values(ctx, "residents", key), what)
    if "wing" in changes or "flat_no" in changes:
        from app.admin_panel.people_import import flat_parts

        wing, flat = flat_parts(changes.get("wing") or "", changes.get("flat_no") or "")
        if "wing" in changes or wing:
            changes["wing"] = wing
        if "flat_no" in changes:
            changes["flat_no"] = flat
    return changes


async def _save_home(conn, sql: str, *args):
    """Runs one change of a home and turns the database's refusals into sentences."""
    import asyncpg

    try:
        return await conn.fetchval(sql, *args)
    except asyncpg.UniqueViolationError as e:
        if "primary" in str(e):
            raise HTTPException(
                status_code=409,
                detail="That flat already has a primary member. Untick it there first.",
            ) from e
        raise HTTPException(
            status_code=409, detail="This person is already linked to that flat."
        ) from e
    except asyncpg.CheckViolationError as e:
        raise HTTPException(
            status_code=400, detail="A tenant cannot be the primary member of a flat."
        ) from e


async def _clear_primary(conn, ctx: Ctx, wing, flat, keep_id) -> list[str]:
    """Takes "primary member" away from anyone else in the flat; returns their names for the log."""
    gone = await conn.fetch(
        "UPDATE residents h SET is_primary = false FROM users u WHERE u.id = h.user_id "
        "AND h.org_id = $1 AND COALESCE(h.wing, '') = $2 AND h.flat_no = $3 AND h.is_primary "
        "AND h.id IS DISTINCT FROM $4 RETURNING u.name",
        ctx.org_id,
        wing or "",
        flat,
        keep_id,
    )
    return [g["name"] for g in gone]


def _where(wing, flat) -> str:
    return (wing + "-" if wing else "") + flat


@router.patch("/people/{user_id}/homes/{resident_id}")
async def update_home(ctx: CtxDep, user_id: UUID, resident_id: UUID, body: HomePatch):
    """Change how a person is linked to a flat (relation, primary member, lives here), the flat itself, or the
    status of that home. Making someone the primary member takes it from whoever had it in that flat. The
    database's own trigger keeps the person's active flag in step with the status."""
    ctx.need("residents")
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    if set(changes) & {"relation", "is_primary", "lives_here"}:
        ctx.need("flat_people")
    changes = await _check_home(ctx, changes)
    async with tx(ctx) as conn:
        before = await conn.fetchrow(
            "SELECT * FROM residents WHERE id = $1 AND user_id = $2 AND org_id = $3 "
            "FOR UPDATE",
            resident_id,
            user_id,
            ctx.org_id,
        )
        if not before:
            raise HTTPException(status_code=404, detail="Home not found")
        changes = {k: v for k, v in changes.items() if before[k] != v}
        who = await conn.fetchrow(
            "SELECT name, is_active FROM users WHERE id = $1", user_id
        )
        if not changes:
            return {
                "ok": True,
                "user_is_active": who["is_active"],
                "took_primary_from": [],
            }
        took = []
        if changes.get("is_primary"):
            took = await _clear_primary(
                conn,
                ctx,
                changes.get("wing", before["wing"]),
                changes.get("flat_no", before["flat_no"]),
                resident_id,
            )
        sets = [f"{col} = ${i + 2}" for i, col in enumerate(changes)]
        if changes.get("status") and changes["status"] != before["status"]:
            sets.append("suspension_date = CURRENT_DATE")
        await _save_home(
            conn,
            f"UPDATE residents SET {', '.join(sets)} WHERE id = $1 RETURNING id",
            resident_id,
            *changes.values(),
        )
        who = await conn.fetchrow(
            "SELECT name, is_active FROM users WHERE id = $1", user_id
        )
        await log_event(
            ctx,
            "people",
            "home",
            f"{who['name']}: "
            + ", ".join(f"{k} {before[k]} → {v}" for k, v in changes.items())
            + (f" (no longer primary: {', '.join(took)})" if took else ""),
            target_type="resident",
            target_id=resident_id,
            before={k: before[k] for k in changes},
            after=changes,
            conn=conn,
        )
    return {"ok": True, "user_is_active": who["is_active"], "took_primary_from": took}


@router.post("/people/{user_id}/homes")
async def add_home(ctx: CtxDep, user_id: UUID, body: HomeNew):
    """Link a person to a flat."""
    ctx.need("residents", "flat_people")
    changes = await _check_home(ctx, body.model_dump())
    async with tx(ctx) as conn:
        who = await conn.fetchrow(
            "SELECT name FROM users WHERE id = $1 AND org_id = $2", user_id, ctx.org_id
        )
        if not who:
            raise HTTPException(status_code=404, detail="Person not found")
        took = (
            await _clear_primary(conn, ctx, changes["wing"], changes["flat_no"], None)
            if changes["is_primary"]
            else []
        )
        new_id = await _save_home(
            conn,
            "INSERT INTO residents (org_id, user_id, wing, flat_no, relation, is_primary, lives_here, "
            "status, residential_status) VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', NULL) RETURNING id",
            ctx.org_id,
            user_id,
            changes["wing"],
            changes["flat_no"],
            changes["relation"],
            changes["is_primary"],
            changes["lives_here"],
        )
        await log_event(
            ctx,
            "people",
            "home",
            f"{who['name']}: added to {_where(changes['wing'], changes['flat_no'])} as {changes['relation']}"
            + (f" (no longer primary: {', '.join(took)})" if took else ""),
            target_type="resident",
            target_id=new_id,
            after=changes,
            conn=conn,
        )
    return {"ok": True, "id": new_id, "took_primary_from": took}


@router.delete("/people/{user_id}/homes/{resident_id}")
async def remove_home(ctx: CtxDep, user_id: UUID, resident_id: UUID):
    """Unlink a person from a flat (they sold it or moved away for good). The person stays; what the link said
    is kept in the change log."""
    ctx.need("residents")
    async with tx(ctx) as conn:
        gone = await conn.fetchrow(
            "DELETE FROM residents WHERE id = $1 AND user_id = $2 AND org_id = $3 RETURNING *",
            resident_id,
            user_id,
            ctx.org_id,
        )
        if not gone:
            raise HTTPException(status_code=404, detail="Home not found")
        who = await conn.fetchval("SELECT name FROM users WHERE id = $1", user_id)
        await log_event(
            ctx,
            "people",
            "home",
            f"{who}: removed from {_where(gone['wing'], gone['flat_no'])}",
            target_type="resident",
            target_id=resident_id,
            before=dict(gone),
            conn=conn,
        )
    return {"ok": True}


@router.get("/flats")
async def list_flats(ctx: CtxDep, q: str | None = None):
    """Every flat and who is in it, for the Flats view of the People screen."""
    ctx.need("residents", "flat_people")
    found = await fetch_all(
        "SELECT h.id, h.wing, h.flat_no, h.relation, h.is_primary, h.lives_here, h.status, "
        "u.id AS user_id, u.name, u.is_active FROM residents h LEFT JOIN users u ON u.id = h.user_id "
        "WHERE h.org_id = $1 ORDER BY h.wing NULLS FIRST, h.flat_no, h.is_primary DESC, h.relation, u.name",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    flats: dict = {}
    for r in found:
        f = flats.setdefault(
            (r["wing"] or "", r["flat_no"]),
            {"wing": r["wing"], "flat_no": r["flat_no"], "people": []},
        )
        f["people"].append(
            {
                "id": str(r["id"]),
                "user_id": str(r["user_id"]) if r["user_id"] else None,
                "name": r["name"],
                "relation": r["relation"],
                "is_primary": r["is_primary"],
                "lives_here": r["lives_here"],
                "status": r["status"],
                "is_active": r["is_active"],
            }
        )
    out = list(flats.values())
    if q:
        t = q.strip().lower()
        out = [
            f
            for f in out
            if t in _where(f["wing"], f["flat_no"]).lower()
            or any(t in (p["name"] or "").lower() for p in f["people"])
        ]
    return {
        "rows": out,
        "total": len(out),
        "no_primary": sum(
            1 for f in out if not any(p["is_primary"] for p in f["people"])
        ),
        "unlinked": sum(1 for f in out for p in f["people"] if not p["user_id"]),
    }


# ── seats (a named job: Chairman, Lift in-charge...) ─────────────────────────


def _seat_select(ctx: Ctx) -> str:
    kind = "p.kind" if ctx.caps.get("seat_kind") else "NULL::text"
    descr = "p.description" if ctx.caps.get("seat_kind") else "NULL::text"
    slug = "p.slug" if ctx.caps.get("seat_kind") else "NULL::text"
    rules = (
        "(SELECT count(*) FROM routing_rules ru WHERE ru.org_id = p.org_id AND "
        "(ru.assign_position_id = p.id OR ru.backup_position_id = p.id))"
        if ctx.caps.get("routing")
        else "0"
    )
    grants = (
        "(SELECT count(*) FROM access_grants g WHERE g.position_id = p.id "
        "AND g.revoked_at IS NULL)"
        if ctx.caps.get("grants")
        else "0"
    )
    return (
        f"SELECT p.id, p.name, {slug} AS slug, {kind} AS kind, {descr} AS description, "
        "h.user_id AS holder_id, hu.name AS holder_name, h.start_date AS holder_since, "
        "hu.is_active AS holder_active, "
        f"{rules} AS rules_using, {grants} AS grants_using, "
        "(SELECT count(*) FROM committee_members m2 WHERE m2.position_id = p.id) AS holders_ever "
        "FROM committee_positions p "
        "LEFT JOIN committee_members h ON h.position_id = p.id AND h.status = 'active' "
        "LEFT JOIN users hu ON hu.id = h.user_id "
    )


@router.get("/seats")
async def list_seats(ctx: CtxDep):
    ctx.need("seats")
    found = await fetch_all(
        f"{_seat_select(ctx)} WHERE p.org_id = $1 ORDER BY {'p.kind,' if ctx.caps.get('seat_kind') else ''} p.name",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {
        "rows": rows(found),
        "kinds": await check_values(ctx, "committee_positions", "kind"),
    }


@router.get("/seats/{seat_id}/history")
async def seat_history(ctx: CtxDep, seat_id: UUID):
    ctx.need("seats")
    found = await fetch_all(
        "SELECT m.id, m.user_id, u.name, m.status, m.start_date, m.end_date "
        "FROM committee_members m JOIN users u ON u.id = m.user_id "
        "WHERE m.org_id = $1 AND m.position_id = $2 "
        "ORDER BY (m.status = 'active') DESC, m.start_date DESC, m.created_at DESC",
        ctx.org_id,
        seat_id,
        source_key=ctx.source_key,
    )
    return {"rows": rows(found)}


class SeatBody(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    kind: str
    description: str | None = Field(None, max_length=400)


class SeatPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=80)
    kind: str | None = None
    description: str | None = Field(None, max_length=400)


@router.post("/seats")
async def create_seat(ctx: CtxDep, body: SeatBody):
    ctx.need("seats", "seat_kind")
    check_choice(
        body.kind, await check_values(ctx, "committee_positions", "kind"), "Kind"
    )
    async with tx(ctx) as conn:
        seat = await conn.fetchrow(
            "INSERT INTO committee_positions (org_id, name, kind, description, default_permissions) "
            "VALUES ($1, $2, $3, $4, '{}') RETURNING id",
            ctx.org_id,
            body.name.strip(),
            body.kind,
            body.description,
        )
        await log_event(
            ctx,
            "people",
            "seat_create",
            f"Created seat '{body.name.strip()}'",
            target_type="seat",
            target_id=seat["id"],
            conn=conn,
        )
    return {"ok": True, "id": seat["id"]}


@router.patch("/seats/{seat_id}")
async def update_seat(ctx: CtxDep, seat_id: UUID, body: SeatPatch):
    ctx.need("seats", "seat_kind")
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if v is not None or k == "description"
    }
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    if changes.get("kind"):
        check_choice(
            changes["kind"],
            await check_values(ctx, "committee_positions", "kind"),
            "Kind",
        )
    async with tx(ctx) as conn:
        before = await conn.fetchrow(
            "SELECT name, kind, description FROM committee_positions "
            "WHERE id = $1 AND org_id = $2 FOR UPDATE",
            seat_id,
            ctx.org_id,
        )
        if not before:
            raise HTTPException(status_code=404, detail="Seat not found")
        sets = [f"{col} = ${i + 2}" for i, col in enumerate(changes)]
        await conn.execute(
            f"UPDATE committee_positions SET {', '.join(sets)} WHERE id = $1",
            seat_id,
            *changes.values(),
        )
        await log_event(
            ctx,
            "people",
            "seat_update",
            f"Changed seat '{before['name']}'",
            target_type="seat",
            target_id=seat_id,
            before=dict(before),
            after=changes,
            conn=conn,
        )
    return {"ok": True}


@router.delete("/seats/{seat_id}")
async def delete_seat(ctx: CtxDep, seat_id: UUID):
    ctx.need("seats")
    async with tx(ctx) as conn:
        seat = await conn.fetchrow(
            "SELECT name FROM committee_positions WHERE id = $1 AND org_id = $2",
            seat_id,
            ctx.org_id,
        )
        if not seat:
            raise HTTPException(status_code=404, detail="Seat not found")
        ever = await conn.fetchval(
            "SELECT count(*) FROM committee_members WHERE position_id = $1", seat_id
        )
        if ever:
            raise HTTPException(
                status_code=409,
                detail=f"'{seat['name']}' has been held by someone, so it is kept for the "
                "record. Rename it instead.",
            )
        if ctx.caps.get("routing"):
            used = await conn.fetchval(
                "SELECT count(*) FROM routing_rules WHERE assign_position_id = $1 "
                "OR backup_position_id = $1",
                seat_id,
            )
            if used:
                raise HTTPException(
                    status_code=409,
                    detail=f"{used} routing rule(s) use '{seat['name']}'. Change those first.",
                )
        await conn.execute("DELETE FROM committee_positions WHERE id = $1", seat_id)
        await log_event(
            ctx,
            "people",
            "seat_delete",
            f"Deleted seat '{seat['name']}'",
            target_type="seat",
            target_id=seat_id,
            conn=conn,
        )
    return {"ok": True}


class HolderBody(BaseModel):
    user_id: UUID | None = None  # null = leave the seat empty


@router.put("/seats/{seat_id}/holder")
async def set_holder(ctx: CtxDep, seat_id: UUID, body: HolderBody):
    """Put someone in a seat (or empty it). The earlier holder's row is ended, not deleted.
    Note: for a committee seat the database itself also switches the person's role."""
    ctx.need("seats")
    async with tx(ctx) as conn:
        seat = await conn.fetchrow(
            "SELECT name FROM committee_positions WHERE id = $1 AND org_id = $2 FOR UPDATE",
            seat_id,
            ctx.org_id,
        )
        if not seat:
            raise HTTPException(status_code=404, detail="Seat not found")
        current = await conn.fetchrow(
            "SELECT user_id FROM committee_members WHERE position_id = $1 "
            "AND status = 'active'",
            seat_id,
        )
        if (current["user_id"] if current else None) == body.user_id:
            raise HTTPException(
                status_code=400,
                detail="That is already the holder."
                if body.user_id
                else "The seat is already empty.",
            )
        person = None
        if body.user_id:
            person = await conn.fetchrow(
                "SELECT id, name, is_active FROM users WHERE id = $1 AND org_id = $2",
                body.user_id,
                ctx.org_id,
            )
            if not person:
                raise HTTPException(status_code=404, detail="Person not found")
            if not person["is_active"]:
                raise HTTPException(
                    status_code=400, detail=f"{person['name']} is not active."
                )
        await conn.execute(
            "UPDATE committee_members SET status = 'ended', end_date = CURRENT_DATE "
            "WHERE position_id = $1 AND status = 'active'",
            seat_id,
        )
        if person:
            await conn.execute(
                "INSERT INTO committee_members (org_id, user_id, position_id, status, start_date) "
                "VALUES ($1, $2, $3, 'active', CURRENT_DATE)",
                ctx.org_id,
                person["id"],
                seat_id,
            )
        await log_event(
            ctx,
            "people",
            "seat_holder",
            f"'{seat['name']}' is now held by {person['name'] if person else 'nobody'}",
            target_type="seat",
            target_id=seat_id,
            before={"user_id": current["user_id"] if current else None},
            after={"user_id": person["id"] if person else None},
            conn=conn,
        )
        role = None
        if person:
            role = await conn.fetchval(
                "SELECT r.name FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = $1",
                person["id"],
            )
    return {"ok": True, "role_now": role}


# ── special access (beyond a person's role) ──────────────────────────────────

_GRANT_SELECT = """
    SELECT g.id,
           CASE WHEN g.user_id IS NOT NULL THEN 'user'
                WHEN g.role_id IS NOT NULL THEN 'role' ELSE 'seat' END AS subject_type,
           COALESCE(g.user_id, g.role_id, g.position_id) AS subject_id,
           COALESCE(u.name, r.name, p.name) AS subject_name,
           g.workflow_key, w.name AS workflow_name,
           g.level, g.scope, g.valid_from, g.valid_to, g.note,
           g.created_at, g.revoked_at, gb.name AS granted_by_name,
           CASE WHEN g.revoked_at IS NOT NULL THEN 'revoked'
                WHEN g.valid_to IS NOT NULL AND g.valid_to < CURRENT_DATE THEN 'expired'
                WHEN g.valid_from IS NOT NULL AND g.valid_from > CURRENT_DATE THEN 'scheduled'
                ELSE 'live' END AS state
      FROM access_grants g
      LEFT JOIN users u ON u.id = g.user_id
      LEFT JOIN roles r ON r.id = g.role_id
      LEFT JOIN committee_positions p ON p.id = g.position_id
      LEFT JOIN users gb ON gb.id = g.granted_by
      LEFT JOIN workflows w ON w.org_id = g.org_id AND w.intent_key = g.workflow_key
     WHERE g.org_id = $1
"""


async def list_grants_sql(ctx: Ctx, extra_where: str = "", *args) -> list[dict]:
    sql = _GRANT_SELECT + (f" AND {extra_where}" if extra_where else "")
    found = await fetch_all(
        sql + " ORDER BY (g.revoked_at IS NOT NULL), g.created_at DESC",
        ctx.org_id,
        *args,
        source_key=ctx.source_key,
    )
    out = rows(found)
    for g in out:
        g["scope"] = jb(g["scope"], {})
    return out


@router.get("/grants")
async def list_grants(ctx: CtxDep, state: Literal["live", "all"] = "live"):
    ctx.need("grants")
    found = await list_grants_sql(ctx)
    if state == "live":
        found = [g for g in found if g["state"] in ("live", "scheduled")]
    return {"rows": found}


class GrantBody(BaseModel):
    subject_type: Literal["user", "role", "seat"]
    subject_id: UUID
    workflow_key: str = Field("*", min_length=1, max_length=120)
    level: int = Field(..., ge=1, le=4)
    scope: dict = Field(default_factory=dict)
    valid_from: date | None = None
    valid_to: date | None = None
    note: str | None = Field(None, max_length=400)


@router.post("/grants")
async def create_grant(ctx: CtxDep, body: GrantBody):
    ctx.need("grants")
    if body.valid_from and body.valid_to and body.valid_to < body.valid_from:
        raise HTTPException(status_code=400, detail="'Until' is before 'from'.")
    table = {"user": "users", "role": "roles", "seat": "committee_positions"}[
        body.subject_type
    ]
    column = {"user": "user_id", "role": "role_id", "seat": "position_id"}[
        body.subject_type
    ]
    async with tx(ctx) as conn:
        subject = await conn.fetchrow(
            f"SELECT name FROM {table} WHERE id = $1 AND org_id = $2",
            body.subject_id,
            ctx.org_id,
        )
        if not subject:
            raise HTTPException(
                status_code=404, detail="That person, role or seat is gone."
            )
        if body.workflow_key != "*":
            ok = await conn.fetchval(
                "SELECT 1 FROM workflows WHERE org_id = $1 AND intent_key = $2",
                ctx.org_id,
                body.workflow_key,
            )
            if not ok:
                raise HTTPException(status_code=404, detail="Unknown workflow.")
        grant = await conn.fetchrow(
            f"INSERT INTO access_grants (org_id, {column}, workflow_key, level, scope, "
            "valid_from, valid_to, note) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8) "
            "RETURNING id",
            ctx.org_id,
            body.subject_id,
            body.workflow_key,
            body.level,
            dump(body.scope),
            body.valid_from,
            body.valid_to,
            body.note,
        )
        await log_event(
            ctx,
            "access",
            "grant",
            f"Gave {subject['name']} level {body.level} access to "
            f"{'everything' if body.workflow_key == '*' else body.workflow_key}",
            target_type="grant",
            target_id=grant["id"],
            after=body.model_dump(mode="json"),
            conn=conn,
        )
    return {"ok": True, "id": grant["id"]}


@router.post("/grants/{grant_id}/revoke")
async def revoke_grant(ctx: CtxDep, grant_id: UUID):
    ctx.need("grants")
    async with tx(ctx) as conn:
        g = await conn.fetchrow(
            "UPDATE access_grants SET revoked_at = now() WHERE id = $1 AND org_id = $2 "
            "AND revoked_at IS NULL RETURNING workflow_key, level",
            grant_id,
            ctx.org_id,
        )
        if not g:
            raise HTTPException(
                status_code=404, detail="That access is already gone or does not exist."
            )
        await log_event(
            ctx,
            "access",
            "revoke",
            f"Revoked level {g['level']} access to {g['workflow_key']}",
            target_type="grant",
            target_id=grant_id,
            conn=conn,
        )
    return {"ok": True}
