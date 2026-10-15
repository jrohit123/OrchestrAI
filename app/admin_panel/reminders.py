"""Reminders: the screen where a super admin sets when open tickets are chased, and the clock of one ticket.

Where each part lives (migration housing-0013):
  * orgs.settings.reminders          the on/off switch, the quiet hours, and the statuses that stop the clock
  * priority_tat_rules.tat_minutes   the time to fix of each urgency (for tickets raised from now on)
  * case_categories.no_time_limit    a kind whose tickets get no due time (changed on the Categories screen)
  * reminder_plans, reminder_plan_categories, reminder_plan_steps
                                     the plans, the kinds that have their own plan (one plan per kind), the steps
  * case_reminder_log                what each step did to each ticket (only read here; the job writes it)

The plans are run by app/services/reminder_plans.py. The clock of a ticket below is worked out with that job's own
functions (clock, due_steps, plan_for), so the screen and the job never disagree.

This screen edits configuration only. Nothing here assigns, closes or re-times a ticket: that stays with the
organisation's own workflows and with the reminder job."""

import math
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.admin_panel.common import (
    Ctx,
    CtxDep,
    PanelRoute,
    check_values,
    dump,
    jb,
    log_event,
    rows,
    tx,
)
from app.db import fetch_all, fetch_one
from app.services import config_store, reminder_plans
from app.services.messages import length_text

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

MAX_MINUTES = 525600  # one year, the same top as the other time boxes
MAX_STEPS = 20
TELL_TO = (
    "backup",
    "raiser",
    "also",
)  # the people on the ticket a step can tell (see reminder_plans.fire)
_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


def _available(ctx: Ctx) -> bool:
    """Reminder plans and the ticket clock come together with housing-0013."""
    return bool(ctx.caps.get("reminders") and ctx.caps.get("tat_clock"))


def _need(ctx: Ctx) -> None:
    ctx.need("reminders", "tat_clock")


def _own(settings: Any) -> dict:
    """orgs.settings.reminders as a dict ({} when it is missing or not an object)."""
    value = settings.get("reminders") if isinstance(settings, dict) else None
    return dict(value) if isinstance(value, dict) else {}


def _current(reminders: dict) -> dict:
    """The switch, quiet hours and pause statuses as the job and the database trigger read them: anything missing or
    malformed reads as off / no quiet hours / never paused."""
    quiet = reminders.get("quiet_hours")
    ok = isinstance(quiet, dict) and {"from", "to"} <= set(quiet)
    pause = reminders.get("pause_statuses")
    return {
        "enabled": reminders.get("enabled") is True,
        "quiet_hours": {"from": quiet["from"], "to": quiet["to"]} if ok else None,
        "pause_statuses": [p for p in pause if isinstance(p, str)]
        if isinstance(pause, list)
        else [],
    }


async def _org(ctx: Ctx) -> tuple[dict, str]:
    """(orgs.settings, the organisation's time zone). The time zone is read through to_jsonb so a database without the
    column still answers."""
    org = await fetch_one(
        "SELECT o.settings, to_jsonb(o) ->> 'timezone' AS timezone FROM orgs o WHERE o.id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not org:
        raise HTTPException(status_code=404, detail="This organisation was not found.")
    settings = jb(org["settings"], {})
    return (settings if isinstance(settings, dict) else {}), (
        org["timezone"] or config_store.DEFAULT_TIMEZONE
    )


async def _priorities(ctx: Ctx) -> list[str]:
    return await check_values(
        ctx, "priority_tat_rules", "priority"
    ) or await check_values(ctx, "cases", "priority")


async def _by_urgency(ctx: Ctx) -> list[dict]:
    """Every urgency in its declared order with its time to fix in minutes (None when the organisation has not set one)."""
    if not ctx.caps.get("targets"):
        return []
    found = {
        r["priority"]: r["tat_minutes"]
        for r in await fetch_all(
            "SELECT priority, tat_minutes FROM priority_tat_rules WHERE org_id = $1",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    }
    allowed = await _priorities(ctx)
    order = allowed + [p for p in found if p not in allowed]
    return [{"priority": p, "tat_minutes": found.get(p)} for p in order]


def _step_out(s) -> dict:
    return {
        "id": s["id"],
        "sort_order": s["sort_order"],
        "at_percent": None if s["at_percent"] is None else float(s["at_percent"]),
        "every_minutes": s["every_minutes"],
        "only_if": s["only_if"],
        "actions": jb(s["actions"], []),
        "is_active": s["is_active"],
    }


async def _plans(ctx: Ctx) -> list[dict]:
    plans = rows(
        await fetch_all(
            "SELECT id, name, is_default, is_active FROM reminder_plans "
            "WHERE org_id = $1 AND record_type = 'cases' ORDER BY is_default DESC, lower(name)",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    kinds: dict = {}
    for r in await fetch_all(
        "SELECT pc.plan_id, k.id, k.label FROM reminder_plan_categories pc "
        "JOIN case_categories k ON k.id = pc.category_id WHERE pc.org_id = $1 ORDER BY lower(k.label)",
        ctx.org_id,
        source_key=ctx.source_key,
    ):
        kinds.setdefault(r["plan_id"], []).append({"id": r["id"], "label": r["label"]})
    steps: dict = {}
    for s in await fetch_all(
        "SELECT id, plan_id, sort_order, at_percent, every_minutes, only_if, actions, is_active "
        "FROM reminder_plan_steps WHERE org_id = $1 ORDER BY sort_order, at_percent NULLS LAST, every_minutes",
        ctx.org_id,
        source_key=ctx.source_key,
    ):
        steps.setdefault(s["plan_id"], []).append(_step_out(s))
    for p in plans:
        p["kinds"] = kinds.get(p["id"], [])
        p["steps"] = steps.get(p["id"], [])
    return plans


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


async def _named_people(ctx: Ctx, plans: list[dict]) -> list[dict]:
    """The people a step tells by name, so the screen can show their names (pick others from the People list)."""
    ids = {
        u
        for p in plans
        for s in p["steps"]
        for a in s["actions"]
        if isinstance(a, dict) and (u := _uuid(a.get("user_id"))) is not None
    }
    if not ids:
        return []
    return rows(
        await fetch_all(
            "SELECT id, name FROM users WHERE org_id = $1 AND id = ANY($2::uuid[]) ORDER BY lower(name)",
            ctx.org_id,
            list(ids),
            source_key=ctx.source_key,
        )
    )


# ── the screen ───────────────────────────────────────────────────────────────


@router.get("/reminders")
async def get_reminders(ctx: CtxDep):
    """Everything the Reminders screen shows. {"available": false} for an organisation without reminder plans."""
    if not _available(ctx):
        return {"available": False}
    settings, _ = await _org(ctx)
    plans = await _plans(ctx)
    return {
        "available": True,
        **_current(_own(settings)),
        "statuses": await check_values(ctx, "cases", "status"),
        "closed_statuses": ctx.closed_values,
        "conditions": await check_values(ctx, "reminder_plan_steps", "only_if"),
        "by_urgency": await _by_urgency(ctx),
        "plans": plans,
        "kinds": rows(
            await fetch_all(
                "SELECT id, label, parent_id, target_minutes, no_time_limit, is_active "
                "FROM case_categories WHERE org_id = $1 ORDER BY sort_order, lower(label)",
                ctx.org_id,
                source_key=ctx.source_key,
            )
        ),
        "roles": rows(
            await fetch_all(
                "SELECT id, name FROM roles WHERE org_id = $1 ORDER BY lower(name)",
                ctx.org_id,
                source_key=ctx.source_key,
            )
        ),
        "people": await _named_people(ctx, plans),
    }


# ── the switch, quiet hours and the statuses that stop the clock ─────────────


class ReminderSettingsBody(BaseModel):
    """A key left out stays as it is. quiet_hours null means no quiet hours."""

    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None = None
    quiet_hours: dict[str, str] | None = None
    pause_statuses: list[str] | None = Field(None, max_length=30)


def _clock_time(text: str) -> str:
    found = _TIME.match((text or "").strip())
    if not found or int(found.group(1)) > 23 or int(found.group(2)) > 59:
        raise HTTPException(
            status_code=400,
            detail=f"Write the quiet hours as HH:MM on a 24-hour clock, such as 22:00 and 07:00 ('{text}' is not).",
        )
    return f"{int(found.group(1)):02d}:{found.group(2)}"


def _quiet(value: dict | None) -> dict | None:
    if value is None:
        return None
    if set(value) != {"from", "to"}:
        raise HTTPException(
            status_code=400,
            detail="Quiet hours need a start ('from') and an end ('to'), such as 22:00 and 07:00.",
        )
    start, end = _clock_time(value["from"]), _clock_time(value["to"])
    if start == end:
        raise HTTPException(
            status_code=400,
            detail="Quiet hours must start and end at different times. To have none, switch them off.",
        )
    return {"from": start, "to": end}


async def _pause_statuses(ctx: Ctx, values: list[str]) -> list[str]:
    allowed = await check_values(ctx, "cases", "status")
    out = list(dict.fromkeys(v.strip() for v in values if v and v.strip()))
    for v in out:
        if allowed and v not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"'{v}' is not a ticket status. Use one of: {', '.join(allowed)}.",
            )
        if v in ctx.closed_values:
            raise HTTPException(
                status_code=400,
                detail=f"'{v}' means the ticket is finished, so it cannot also stop the clock.",
            )
    return out


def _settings_summary(old: dict, new: dict) -> str:
    """One line for the change log, in the screen's words."""
    before, after = _current(old), _current(new)
    parts = []
    if before["enabled"] != after["enabled"]:
        parts.append("reminder plans switched " + ("on" if after["enabled"] else "off"))
    if before["quiet_hours"] != after["quiet_hours"]:
        q = after["quiet_hours"]
        parts.append(f"quiet hours {q['from']} to {q['to']}" if q else "no quiet hours")
    if before["pause_statuses"] != after["pause_statuses"]:
        stops = after["pause_statuses"]
        parts.append(
            "the clock stops at: " + ", ".join(stops)
            if stops
            else "the clock never stops"
        )
    return "Reminders: " + "; ".join(parts) if parts else "Saved reminder settings"


@router.put("/reminders/settings")
async def put_reminder_settings(ctx: CtxDep, body: ReminderSettingsBody):
    """Switch the plans on or off, set quiet hours, and choose the statuses that stop a ticket's clock. The database
    trigger and the job read these at once."""
    _need(ctx)
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    changes: dict = {}
    if "enabled" in sent:
        if body.enabled is None:
            raise HTTPException(
                status_code=400, detail="Switch reminders on or off with true or false."
            )
        changes["enabled"] = body.enabled
    if "quiet_hours" in sent:
        changes["quiet_hours"] = _quiet(body.quiet_hours)
    if "pause_statuses" in sent:
        changes["pause_statuses"] = await _pause_statuses(
            ctx, body.pause_statuses or []
        )
    async with tx(ctx) as conn:
        org = await conn.fetchrow(
            "SELECT settings FROM orgs WHERE id = $1 FOR UPDATE", ctx.org_id
        )
        if not org:
            raise HTTPException(
                status_code=404, detail="This organisation was not found."
            )
        old = _own(jb(org["settings"], {}))
        new = {**old, **changes}
        # only the reminders key is touched; everything else in orgs.settings stays exactly as it was
        await conn.execute(
            "UPDATE orgs SET settings = COALESCE(settings, '{}'::jsonb) || jsonb_build_object('reminders', $1::jsonb) "
            "WHERE id = $2",
            dump(new),
            ctx.org_id,
        )
        await log_event(
            ctx,
            "reminders",
            "settings",
            _settings_summary(old, new),
            target_type="orgs",
            target_id=ctx.org_id,
            before=old,
            after=new,
            conn=conn,
        )
    config_store.invalidate(ctx.source_key)
    return {"ok": True, **_current(new)}


# ── the time to fix of each urgency ──────────────────────────────────────────


@router.put("/reminders/urgency")
async def put_urgency(ctx: CtxDep, body: Annotated[dict[str, StrictInt], Body()]):
    """{"urgent": 240, "high": 1440, ...}: the time to fix of each urgency, in minutes. It sets the due time of tickets
    raised from now on; a ticket already open keeps its due time. The older reminder (reminder_threshold_minutes) is
    kept, but never later than the new time to fix."""
    ctx.need("targets")
    if not body:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    allowed = await _priorities(ctx)
    for priority, minutes in body.items():
        if allowed and priority not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"'{priority}' is not an urgency. Use one of: {', '.join(allowed)}.",
            )
        if not 1 <= minutes <= MAX_MINUTES:
            raise HTTPException(
                status_code=400,
                detail=f"The time to fix for {priority} must be between 1 minute and one year ({MAX_MINUTES} minutes).",
            )
    async with tx(ctx) as conn:
        before = {
            r["priority"]: r["tat_minutes"]
            for r in await conn.fetch(
                "SELECT priority, tat_minutes FROM priority_tat_rules WHERE org_id = $1 FOR UPDATE",
                ctx.org_id,
            )
        }
        for priority, minutes in body.items():
            await conn.execute(
                "INSERT INTO priority_tat_rules (org_id, priority, tat_minutes, reminder_threshold_minutes) "
                "VALUES ($1, $2, $3, $3) ON CONFLICT (org_id, priority) DO UPDATE SET "
                "tat_minutes = EXCLUDED.tat_minutes, "
                "reminder_threshold_minutes = LEAST(priority_tat_rules.reminder_threshold_minutes, EXCLUDED.tat_minutes)",
                ctx.org_id,
                priority,
                minutes,
            )
        parts = [
            f"{p} {length_text(m)}"
            + (f" (was {length_text(before[p])})" if before.get(p) else "")
            for p, m in body.items()
            if before.get(p) != m
        ]
        await log_event(
            ctx,
            "reminders",
            "urgency",
            "Time to fix: " + "; ".join(parts) if parts else "Saved the times to fix",
            target_type="priority_tat_rules",
            before=before,
            after={**before, **body},
            conn=conn,
        )
    return {"ok": True, "by_urgency": await _by_urgency(ctx)}


# ── plans ────────────────────────────────────────────────────────────────────


class PlanNew(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=80)
    kind_ids: list[UUID] = Field(default_factory=list, max_length=300)


class PlanPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=80)
    is_active: StrictBool | None = None
    kind_ids: list[UUID] | None = Field(None, max_length=300)


def _plan_name(text: str | None) -> str:
    name = " ".join((text or "").split())
    if not name:
        raise HTTPException(status_code=400, detail="Give the plan a name.")
    return name


async def _name_free(conn, ctx: Ctx, name: str, plan_id=None) -> None:
    taken = await conn.fetchval(
        "SELECT 1 FROM reminder_plans WHERE org_id = $1 AND record_type = 'cases' "
        "AND lower(name) = lower($2) AND id IS DISTINCT FROM $3",
        ctx.org_id,
        name,
        plan_id,
    )
    if taken:
        raise HTTPException(
            status_code=409, detail=f"There is already a plan called '{name}'."
        )


async def _check_kinds(conn, ctx: Ctx, plan_id, kind_ids: list[UUID]) -> list[UUID]:
    """The kinds, without repeats, after checking each is this organisation's and has no other plan."""
    ids = list(dict.fromkeys(kind_ids))
    if not ids:
        return []
    labels = {
        r["id"]: r["label"]
        for r in await conn.fetch(
            "SELECT id, label FROM case_categories WHERE org_id = $1 AND id = ANY($2::uuid[])",
            ctx.org_id,
            ids,
        )
    }
    if len(labels) != len(ids):
        raise HTTPException(
            status_code=404, detail="One of those kinds of ticket no longer exists."
        )
    other = await conn.fetchrow(
        "SELECT pc.category_id, p.name FROM reminder_plan_categories pc "
        "JOIN reminder_plans p ON p.id = pc.plan_id "
        "WHERE pc.org_id = $1 AND pc.category_id = ANY($2::uuid[]) AND pc.plan_id IS DISTINCT FROM $3 "
        "ORDER BY p.name LIMIT 1",
        ctx.org_id,
        ids,
        plan_id,
    )
    if other:
        raise HTTPException(
            status_code=409,
            detail=f"'{labels[other['category_id']]}' already has its own plan, '{other['name']}'. "
            "Take it out of that plan first.",
        )
    return ids


async def _set_kinds(conn, ctx: Ctx, plan_id, ids: list[UUID]) -> None:
    await conn.execute(
        "DELETE FROM reminder_plan_categories WHERE plan_id = $1", plan_id
    )
    for kind in ids:
        await conn.execute(
            "INSERT INTO reminder_plan_categories (plan_id, category_id, org_id) VALUES ($1, $2, $3)",
            plan_id,
            kind,
            ctx.org_id,
        )


async def _plan_row(conn, ctx: Ctx, plan_id: UUID):
    plan = await conn.fetchrow(
        "SELECT id, name, is_default, is_active FROM reminder_plans "
        "WHERE id = $1 AND org_id = $2 FOR UPDATE",
        plan_id,
        ctx.org_id,
    )
    if not plan:
        raise HTTPException(status_code=404, detail="That plan no longer exists.")
    return plan


@router.post("/reminders/plans")
async def create_plan(ctx: CtxDep, body: PlanNew):
    """A plan of its own for some kinds of ticket. It starts with a copy of the default plan's steps, so those kinds
    keep the reminders they had until its steps are changed."""
    _need(ctx)
    name = _plan_name(body.name)
    async with tx(ctx) as conn:
        await _name_free(conn, ctx, name)
        kinds = await _check_kinds(conn, ctx, None, body.kind_ids)
        plan_id = await conn.fetchval(
            "INSERT INTO reminder_plans (org_id, name, is_default) VALUES ($1, $2, false) RETURNING id",
            ctx.org_id,
            name,
        )
        await _set_kinds(conn, ctx, plan_id, kinds)
        await conn.execute(
            "INSERT INTO reminder_plan_steps (org_id, plan_id, sort_order, at_percent, every_minutes, only_if, "
            "actions, is_active) "
            "SELECT s.org_id, $2, s.sort_order, s.at_percent, s.every_minutes, s.only_if, s.actions, s.is_active "
            "FROM reminder_plan_steps s JOIN reminder_plans p ON p.id = s.plan_id "
            "WHERE p.org_id = $1 AND p.record_type = 'cases' AND p.is_default",
            ctx.org_id,
            plan_id,
        )
        await log_event(
            ctx,
            "reminders",
            "plan_create",
            f"Created the reminder plan '{name}'",
            target_type="reminder_plan",
            target_id=plan_id,
            after={"name": name, "kind_ids": kinds},
            conn=conn,
        )
    return {"ok": True, "id": plan_id}


@router.patch("/reminders/plans/{plan_id}")
async def update_plan(ctx: CtxDep, plan_id: UUID, body: PlanPatch):
    """Rename a plan, switch it on or off, or choose its kinds (the list replaces the old one). A plan that is off is
    skipped: its kinds use their parent's plan or the default one."""
    _need(ctx)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    if "is_active" in changes and changes["is_active"] is None:
        raise HTTPException(status_code=400, detail="Switch the plan on or off.")
    async with tx(ctx) as conn:
        plan = await _plan_row(conn, ctx, plan_id)
        before_kinds = [
            r["category_id"]
            for r in await conn.fetch(
                "SELECT category_id FROM reminder_plan_categories WHERE plan_id = $1",
                plan_id,
            )
        ]
        name = plan["name"]
        if "name" in changes:
            name = _plan_name(changes["name"])
            await _name_free(conn, ctx, name, plan_id)
        active = (
            plan["is_active"]
            if changes.get("is_active") is None
            else changes["is_active"]
        )
        await conn.execute(
            "UPDATE reminder_plans SET name = $2, is_active = $3, updated_at = now() WHERE id = $1",
            plan_id,
            name,
            active,
        )
        after: dict = {"name": name, "is_active": active}
        if "kind_ids" in changes:
            kinds = await _check_kinds(conn, ctx, plan_id, changes["kind_ids"] or [])
            await _set_kinds(conn, ctx, plan_id, kinds)
            after["kind_ids"] = kinds
        await log_event(
            ctx,
            "reminders",
            "plan_update",
            f"Changed the reminder plan '{plan['name']}'",
            target_type="reminder_plan",
            target_id=plan_id,
            before={
                "name": plan["name"],
                "is_active": plan["is_active"],
                "kind_ids": before_kinds,
            },
            after=after,
            conn=conn,
        )
    return {"ok": True}


@router.delete("/reminders/plans/{plan_id}")
async def delete_plan(ctx: CtxDep, plan_id: UUID):
    """Delete a plan of its own. Its kinds go back to their parent's plan or the default one; what its steps already
    did stays in each ticket's history."""
    _need(ctx)
    async with tx(ctx) as conn:
        plan = await _plan_row(conn, ctx, plan_id)
        if plan["is_default"]:
            raise HTTPException(
                status_code=409,
                detail=f"'{plan['name']}' is the plan for every kind of ticket without its own, so it cannot be "
                "deleted. Switch it off instead if those tickets should not be chased.",
            )
        await conn.execute("DELETE FROM reminder_plans WHERE id = $1", plan_id)
        await log_event(
            ctx,
            "reminders",
            "plan_delete",
            f"Deleted the reminder plan '{plan['name']}'",
            target_type="reminder_plan",
            target_id=plan_id,
            conn=conn,
        )
    return {"ok": True}


# ── the steps of a plan ──────────────────────────────────────────────────────


class StepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # a step that is already in the plan: send its id back, so what it already did to each ticket stays linked to it
    # (a step without an id is new, and may run on tickets that are already past its share)
    id: UUID | None = None
    sort_order: int | None = None  # not used: the order of the list is the order
    at_percent: float | None = None
    every_minutes: StrictInt | None = None
    only_if: str = "always"
    actions: list[Any] = Field(..., max_length=10)
    is_active: StrictBool = True


class StepsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[StepIn] = Field(..., max_length=MAX_STEPS)


_WHAT_A_STEP_DOES = (
    "A step can remind the handler, tell the backup, the person who raised the ticket, the others on it, a role or "
    "a person, hand the ticket to the backup, or raise its urgency."
)


def _check_action(where: str, a: Any, repeating: bool) -> dict:
    """One action, in the shape the job reads (see reminder_plans.fire), or a 400 in plain words."""
    if not isinstance(a, dict):
        raise HTTPException(status_code=400, detail=f"{where}: {_WHAT_A_STEP_DOES}")
    do, keys = a.get("do"), set(a) - {"do"}
    if do in ("remind", "raise_priority") and not keys:
        return {"do": do}
    if do == "reassign" and keys == {"to"} and a["to"] == "backup":
        if repeating:
            raise HTTPException(
                status_code=400,
                detail=f"{where} repeats, so it cannot hand the ticket over: it would pass it back and forth.",
            )
        return {"do": "reassign", "to": "backup"}
    if do == "tell" and keys == {"to"} and a["to"] in TELL_TO:
        return {"do": "tell", "to": a["to"]}
    for key in ("role_id", "user_id"):
        if do == "tell" and keys == {key}:
            found = _uuid(a[key])
            if found is None:
                break
            return {"do": "tell", key: str(found)}
    raise HTTPException(
        status_code=400,
        detail=f"{where}: one of its actions is not understood. {_WHAT_A_STEP_DOES}",
    )


async def _check_steps(conn, ctx: Ctx, steps: list[StepIn]) -> list[dict]:
    """Every step checked, in the order given; refuses with the step's number and a plain sentence."""
    conditions = await check_values(ctx, "reminder_plan_steps", "only_if")
    shares, repeats, ids, roles, people = set(), set(), set(), set(), set()
    out = []
    for i, s in enumerate(steps, 1):
        where = f"Step {i}"
        if (s.at_percent is None) == (s.every_minutes is None):
            raise HTTPException(
                status_code=400,
                detail=f"{where}: choose either a share of the time to fix or a repeat every so many minutes "
                "(one of the two).",
            )
        if s.at_percent is not None:
            if not math.isfinite(s.at_percent) or not 0 < s.at_percent <= 1000:
                raise HTTPException(
                    status_code=400,
                    detail=f"{where}: the share must be more than 0% and at most 1000% of the time to fix.",
                )
            share = round(s.at_percent, 2)
            if share in shares:
                raise HTTPException(
                    status_code=400,
                    detail=f"{where}: another step is already at {share:g}%. Put what they do into one step.",
                )
            shares.add(share)
        else:
            if not 60 <= s.every_minutes <= MAX_MINUTES:
                raise HTTPException(
                    status_code=400,
                    detail=f"{where}: a repeat can come at most once an hour (60 minutes) and at least once a "
                    f"year ({MAX_MINUTES} minutes).",
                )
            if s.every_minutes in repeats:
                raise HTTPException(
                    status_code=400,
                    detail=f"{where}: another step already repeats every {length_text(s.every_minutes)}. "
                    "Put what they do into one step.",
                )
            repeats.add(s.every_minutes)
        if conditions and s.only_if not in conditions:
            raise HTTPException(
                status_code=400,
                detail=f"{where}: the condition must be one of: {', '.join(conditions)}.",
            )
        if not s.actions:
            raise HTTPException(
                status_code=400,
                detail=f"{where} does nothing. Give it at least one thing to do.",
            )
        actions: list[dict] = []
        for a in s.actions:
            clean = _check_action(where, a, s.every_minutes is not None)
            if clean not in actions:
                actions.append(clean)
            if "role_id" in clean:
                roles.add((i, clean["role_id"]))
            if "user_id" in clean:
                people.add((i, clean["user_id"]))
        if s.id is not None:
            if s.id in ids:
                raise HTTPException(
                    status_code=400, detail=f"{where} is in the list twice."
                )
            ids.add(s.id)
        out.append(
            {
                "id": s.id,
                "sort_order": i,
                "at_percent": None if s.at_percent is None else round(s.at_percent, 2),
                "every_minutes": s.every_minutes,
                "only_if": s.only_if,
                "actions": actions,
                "is_active": s.is_active,
            }
        )
    for table, named, word in (("roles", roles, "role"), ("users", people, "person")):
        if not named:
            continue
        known = {
            str(r["id"])
            for r in await conn.fetch(
                f"SELECT id FROM {table} WHERE org_id = $1 AND id = ANY($2::uuid[])",
                ctx.org_id,
                list({u for _, u in named}),
            )
        }
        for i, u in sorted(named):
            if u not in known:
                raise HTTPException(
                    status_code=400,
                    detail=f"Step {i} tells a {word} who is not in this organisation.",
                )
    return out


@router.put("/reminders/plans/{plan_id}/steps")
async def put_steps(ctx: CtxDep, plan_id: UUID, body: StepsBody):
    """The whole list of a plan's steps, in one go. A step sent with its id is changed in place (so it does not run
    again on tickets it already ran on); a step without an id is new; a step left out is removed."""
    _need(ctx)
    async with tx(ctx) as conn:
        plan = await _plan_row(conn, ctx, plan_id)
        steps = await _check_steps(conn, ctx, body.steps)
        # keyed by text: asyncpg's UUID and Python's uuid.UUID are equal but do not hash alike
        existing = {
            str(r["id"]): _step_out(r)
            for r in await conn.fetch(
                "SELECT * FROM reminder_plan_steps WHERE plan_id = $1 ORDER BY sort_order",
                plan_id,
            )
        }
        kept = {str(s["id"]) for s in steps if s["id"] is not None}
        if kept - existing.keys():
            raise HTTPException(
                status_code=409,
                detail="One of these steps is no longer in this plan (someone else changed it). "
                "Reload the page and try again.",
            )
        gone = [i for i in existing if i not in kept]
        if gone:
            await conn.execute(
                "DELETE FROM reminder_plan_steps WHERE plan_id = $1 AND id = ANY($2::uuid[])",
                plan_id,
                gone,
            )
        for s in steps:
            values = (
                s["sort_order"],
                None if s["at_percent"] is None else Decimal(str(s["at_percent"])),
                s["every_minutes"],
                s["only_if"],
                dump(s["actions"]),
                s["is_active"],
            )
            if s["id"] is not None:
                await conn.execute(
                    "UPDATE reminder_plan_steps SET sort_order = $2, at_percent = $3, every_minutes = $4, "
                    "only_if = $5, actions = $6::jsonb, is_active = $7, updated_at = now() WHERE id = $1",
                    s["id"],
                    *values,
                )
            else:
                await conn.execute(
                    "INSERT INTO reminder_plan_steps (org_id, plan_id, sort_order, at_percent, every_minutes, "
                    "only_if, actions, is_active) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)",
                    ctx.org_id,
                    plan_id,
                    *values,
                )
        now = [
            _step_out(r)
            for r in await conn.fetch(
                "SELECT * FROM reminder_plan_steps WHERE plan_id = $1 ORDER BY sort_order",
                plan_id,
            )
        ]
        await log_event(
            ctx,
            "reminders",
            "steps",
            f"Changed the steps of the reminder plan '{plan['name']}' "
            f"({len(now)} step{'' if len(now) == 1 else 's'}, was {len(existing)})",
            target_type="reminder_plan",
            target_id=plan_id,
            before=list(existing.values()),
            after=now,
            conn=conn,
        )
    return {"ok": True, "steps": now}


# ── the clock of one ticket ──────────────────────────────────────────────────


def _after_quiet(settings: dict, when: datetime, tz: ZoneInfo) -> datetime | None:
    """When `when` falls in the quiet hours: the end of them (a step that only sends messages waits for it)."""
    local = when.astimezone(tz)
    if not reminder_plans.in_quiet_hours(settings, local):
        return None
    quiet = config_store.setting(settings, "reminders.quiet_hours", None)
    hour, minute = (int(x) for x in str(quiet["to"]).split(":")[:2])
    end = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return end if end > local else end + timedelta(days=1)


def _base(step: dict, repeat_no: int = 0) -> dict:
    return {
        "id": step["id"],
        "at_percent": None
        if step.get("at_percent") is None
        else float(step["at_percent"]),
        "every_minutes": step.get("every_minutes"),
        "only_if": step.get("only_if"),
        "actions": step.get("actions") or [],
        "repeat_no": repeat_no,
    }


@router.get("/cases/{case_id}/clock")
async def case_clock(ctx: CtxDep, case_id: UUID):
    """How far one ticket is through its time to fix, which plan chases it, and each step: done, skipped or failed
    (with when and what it did), the next one, and the ones after it. Read only; worked out with the reminder job's
    own functions. Only the steps that apply are listed: shares for a ticket with a due time, repeats for one without."""
    ctx.need("cases")
    if not _available(ctx):
        return {"available": False}
    found = await fetch_one(
        "SELECT c.*, now() AS now FROM cases c WHERE c.org_id = $1 AND c.id = $2",
        ctx.org_id,
        case_id,
        source_key=ctx.source_key,
    )
    if not found:
        raise HTTPException(status_code=404, detail="Case not found")
    case = dict(found)
    now = case.pop("now")
    settings, zone = await _org(ctx)
    try:
        tz = ZoneInfo(zone)
    except (KeyError, ValueError):
        tz = ZoneInfo(config_store.DEFAULT_TIMEZONE)

    steps_by_plan, own, parents, default = await reminder_plans._plans(
        ctx.source_key, ctx.org_id
    )
    plan_id = reminder_plans.plan_for(case.get("category_id"), own, parents, default)
    plan = None
    if plan_id:
        name = await fetch_one(
            "SELECT name FROM reminder_plans WHERE id = $1",
            plan_id,
            source_key=ctx.source_key,
        )
        plan = {"id": plan_id, "name": name["name"] if name else None}
    steps = steps_by_plan.get(plan_id, []) if plan_id else []

    cycle = case.get("tat_cycle") or 0
    log = await fetch_all(
        "SELECT step_id, repeat_no, outcome, fired_at, detail FROM case_reminder_log "
        "WHERE case_id = $1 AND tat_cycle = $2 AND step_id IS NOT NULL ORDER BY fired_at",
        case_id,
        cycle,
        source_key=ctx.source_key,
    )
    done = {(r["step_id"], cycle, r["repeat_no"]) for r in log}
    logged = {(r["step_id"], r["repeat_no"]): r for r in log}

    paused = case.get("tat_paused_at") is not None
    closed = case.get("status") in ctx.closed_values
    stopped = case["tat_paused_at"] if paused else now  # a stopped clock stands still
    c = reminder_plans.clock(case, stopped)
    timed = c["total"] is not None
    start = case.get("tat_started_at") or case.get("created_at") or now
    paused_minutes = case.get("tat_paused_minutes") or 0

    # what the job's next pass does: of the shares reached together, only the furthest runs and the others are skipped
    skip = []
    if not paused and not closed:
        _, skip = reminder_plans.due_steps(case, steps, done, now)
    skipped_now = {s["id"] for s, _ in skip}

    def logged_entry(step: dict, row) -> dict:
        return {
            **_base(step, row["repeat_no"]),
            "state": row["outcome"],
            "when": row["fired_at"],
            "detail": jb(row["detail"], {}),
        }

    def pending(step: dict, n: int, minutes_in: float) -> dict:
        entry = {**_base(step, n), "state": "later", "when": None, "detail": None}
        if closed:
            entry["detail"] = {"why": "the ticket is closed"}
        elif paused:
            entry["detail"] = {"why": "the clock is stopped while the ticket waits"}
        else:
            when = max(start + timedelta(minutes=paused_minutes + minutes_in), now)
            kinds = {
                a.get("do") for a in step.get("actions") or [] if isinstance(a, dict)
            }
            later = (
                _after_quiet(settings, when, tz)
                if kinds <= reminder_plans.MESSAGE_ONLY
                else None
            )
            if later:
                when = later
                entry["detail"] = {"why": "waits for the end of the quiet hours"}
            entry["when"] = when
        entry["pending"] = True
        return entry

    entries: list[dict] = []
    if timed:
        for step in sorted(
            (s for s in steps if s.get("at_percent") is not None),
            key=lambda s: float(s["at_percent"]),
        ):
            row = logged.get((step["id"], 0))
            if row:
                entries.append(logged_entry(step, row))
            elif step["id"] in skipped_now:
                # the job will mark it so on its next pass: it was passed together with a later step
                entries.append(
                    {
                        **_base(step),
                        "state": "skipped",
                        "when": None,
                        "detail": {"why": "passed together with a later step"},
                    }
                )
            else:
                share = float(step["at_percent"]) / 100 * c["total"]
                entries.append(pending(step, 0, share))
    else:
        for step in (s for s in steps if s.get("every_minutes")):
            every = step["every_minutes"]
            for (step_id, _), row in sorted(logged.items(), key=lambda x: x[0][1]):
                if step_id == step["id"]:
                    entries.append(logged_entry(step, row))
            # the run the job makes next: the current period if it has not run yet, else the one after
            n = int(c["elapsed"] // every)
            if n < 1 or (step["id"], cycle, n) in done:
                n += 1
            entries.append(pending(step, n, n * every))
        entries.sort(
            key=lambda e: (e["when"] is None, e["when"].timestamp() if e["when"] else 0)
        )

    first = True
    for e in entries:
        if e.pop("pending", False):
            if first and not closed:
                e["state"] = "next"
            first = False

    percent = c["percent"]
    return {
        "available": True,
        "enabled": _current(_own(settings))["enabled"],
        "closed": closed,
        "cycle": cycle,
        "started_at": start,
        "due_at": case.get("due_date"),
        "paused": paused,
        "paused_since": case.get("tat_paused_at"),
        "paused_minutes": paused_minutes,
        "elapsed_minutes": int(c["elapsed"]),
        "total_minutes": None if not timed else max(round(c["total"]), 0),
        "percent": None
        if percent is None
        else (100.0 if math.isinf(percent) else round(percent, 1)),
        "plan": plan,
        "steps": entries,
    }
