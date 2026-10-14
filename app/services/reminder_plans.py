"""Reminder plans: each open ticket is reminded, escalated or handed to its backup at a share of its time to fix.

A plan (reminder_plans, housing-0013) is a list of steps such as "at 25% remind the handler and tell the backup" or "at 40%, if
nobody has acted, give it to the backup". A share works for any ticket: 25% of 2 hours is 30 minutes, 25% of 3 months is about
three weeks. A kind of ticket may have its own plan (the nearest kind up its chain wins); every other ticket uses the default.
A step with every_minutes instead repeats, for tickets with no time limit (no due time).

The clock of a ticket is kept by the database (cases.tat_started_at, tat_paused_minutes, tat_cycle; see the trigger in
housing-0013), so this only reads it. Each step runs once per ticket and cycle: case_reminder_log has one row per step, and the
row is written before anything is sent, so two copies of the app never both act.

Switched on per organisation by orgs.settings -> reminders.enabled. While it is off, nothing here runs and the older
case_reminders job (app/scheduler/jobs.py) goes on as before; while it is on, that older job leaves the organisation alone.

Messages are the organisation's own words (group "reminder" in messages.py). They go out through reach.deliver_text, so a
closed WhatsApp chat is handled the same way as for any other message. In the organisation's quiet hours, a step that only
sends messages waits until morning; a step that hands the ticket over still runs (the new handler must know)."""

import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db import execute, fetch_all, fetch_one, get_all_source_keys, get_pool
from app.logging_config import get_context_logger
from app.services import config_store
from app.services.messages import length_text, say

logger = get_context_logger(__name__)

PRIORITY_UP = {"low": "medium", "medium": "high", "high": "urgent"}
ACTED = (
    "comment",
    "evidence",
    "status_change",
)  # what counts as the handler having done something
MESSAGE_ONLY = {"remind", "tell"}


def _jb(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value


def _minutes(td) -> float:
    return td.total_seconds() / 60


def clock(case: dict, now: datetime) -> dict:
    """How far a ticket is: {"elapsed": minutes the clock ran, "total": its time to fix in minutes (None = no limit),
    "percent": share used (None = no limit)}. Paused time does not count."""
    start = case.get("tat_started_at") or case.get("created_at") or now
    paused = case.get("tat_paused_minutes") or 0
    elapsed = max(_minutes(now - start) - paused, 0)
    due = case.get("due_date")
    if not due:
        return {"elapsed": elapsed, "total": None, "percent": None}
    total = _minutes(due - start) - paused
    percent = math.inf if total <= 0 else elapsed / total * 100
    return {"elapsed": elapsed, "total": total, "percent": percent}


def due_steps(
    case: dict, steps: list[dict], done: set, now: datetime
) -> tuple[list, list]:
    """(steps to run now, steps to mark skipped) for one ticket. A share step runs once its share is reached. When several
    were reached at once (the plan was just switched on, or the app was down), only the furthest runs and the others are
    marked skipped, so nobody gets three messages at once. A repeating step runs once per period, for tickets with no
    time limit."""
    c = clock(case, now)
    cycle = case.get("tat_cycle") or 0
    reached, run, skip = [], [], []
    if c["percent"] is not None:
        for s in steps:
            if s.get("at_percent") is None:
                continue
            if (
                c["percent"] >= float(s["at_percent"])
                and (s["id"], cycle, 0) not in done
            ):
                reached.append(s)
        reached.sort(key=lambda s: float(s["at_percent"]))
        if reached:
            run = [(reached[-1], 0)]
            skip = [(s, 0) for s in reached[:-1]]
    else:
        for s in steps:
            every = s.get("every_minutes")
            if not every:
                continue
            n = int(c["elapsed"] // every)
            if n >= 1 and (s["id"], cycle, n) not in done:
                run.append((s, n))
    return run, skip


def in_quiet_hours(settings: dict, now_local: datetime) -> bool:
    quiet = config_store.setting(settings, "reminders.quiet_hours", None)
    if not isinstance(quiet, dict):
        return False
    try:
        a = [int(x) for x in str(quiet["from"]).split(":")[:2]]
        b = [int(x) for x in str(quiet["to"]).split(":")[:2]]
    except (KeyError, ValueError, IndexError):
        return False
    start, end, t = (
        a[0] * 60 + a[1],
        b[0] * 60 + b[1],
        now_local.hour * 60 + now_local.minute,
    )
    if start == end:
        return False
    return (t >= start or t < end) if start > end else (start <= t < end)


async def run_reminder_plans():
    """Every minute: every organisation that switched its plans on."""
    for source_key in await get_all_source_keys():
        try:
            ready = await fetch_one(
                "SELECT to_regclass('public.reminder_plan_steps') IS NOT NULL AS ok",
                source_key=source_key,
            )
            if not ready or not ready["ok"]:
                continue
            orgs = await fetch_all(
                "SELECT id, name, settings, timezone FROM orgs WHERE is_active",
                source_key=source_key,
            )
        except Exception as e:
            logger.warning(f"reminder plans: could not read {source_key}: {e}")
            continue
        for org in orgs:
            settings = _jb(org["settings"], {}) or {}
            if config_store.setting(settings, "reminders.enabled", False) is not True:
                continue
            try:
                await run_org(source_key, dict(org), settings)
            except Exception as e:
                logger.error(
                    f"reminder plans: {source_key} stopped: {e}", exc_info=True
                )


async def _plans(source_key: str, org_id) -> tuple[dict, dict, dict, dict | None]:
    """(steps by plan, the plan a kind has of its own, each kind's parent, the default plan id)"""
    plans = await fetch_all(
        "SELECT id, is_default FROM reminder_plans WHERE org_id = $1 AND record_type = 'cases' AND is_active",
        org_id,
        source_key=source_key,
    )
    default = next((p["id"] for p in plans if p["is_default"]), None)
    steps: dict = {p["id"]: [] for p in plans}
    for s in await fetch_all(
        "SELECT * FROM reminder_plan_steps WHERE org_id = $1 AND is_active ORDER BY sort_order",
        org_id,
        source_key=source_key,
    ):
        if s["plan_id"] in steps:
            steps[s["plan_id"]].append({**dict(s), "actions": _jb(s["actions"], [])})
    own = {
        r["category_id"]: r["plan_id"]
        for r in await fetch_all(
            "SELECT category_id, plan_id FROM reminder_plan_categories WHERE org_id = $1",
            org_id,
            source_key=source_key,
        )
        if r["plan_id"] in steps
    }
    parents = {
        r["id"]: r["parent_id"]
        for r in await fetch_all(
            "SELECT id, parent_id FROM case_categories WHERE org_id = $1",
            org_id,
            source_key=source_key,
        )
    }
    return steps, own, parents, default


def plan_for(category_id, own: dict, parents: dict, default):
    """The nearest kind up the chain (itself first) that has its own plan, else the default plan."""
    seen = set()
    while category_id and category_id not in seen:
        seen.add(category_id)
        if category_id in own:
            return own[category_id]
        category_id = parents.get(category_id)
    return default


async def run_org(source_key: str, org: dict, settings: dict) -> None:
    org_id = org["id"]
    steps, own, parents, default = await _plans(source_key, org_id)
    if not any(steps.values()):
        return
    closed = config_store.setting(settings, "case_reminders.closed_values", None) or [
        "closed"
    ]
    cases = await fetch_all(
        "SELECT c.*, now() AS now FROM cases c WHERE c.org_id = $1 AND NOT (c.status = ANY($2::text[])) "
        "AND c.tat_paused_at IS NULL",
        org_id,
        list(closed),
        source_key=source_key,
    )
    if not cases:
        return
    done = {}
    for r in await fetch_all(
        "SELECT case_id, step_id, tat_cycle, repeat_no FROM case_reminder_log WHERE case_id = ANY($1::uuid[]) AND step_id IS NOT NULL",
        [c["id"] for c in cases],
        source_key=source_key,
    ):
        done.setdefault(r["case_id"], set()).add(
            (r["step_id"], r["tat_cycle"], r["repeat_no"])
        )
    tz = ZoneInfo(org.get("timezone") or config_store.DEFAULT_TIMEZONE)
    start_status = await _start_status(source_key)
    for case in cases:
        case = dict(case)
        now = case.pop("now")
        plan = plan_for(case.get("category_id"), own, parents, default)
        if not plan or not steps.get(plan):
            continue
        run, skip = due_steps(case, steps[plan], done.get(case["id"], set()), now)
        quiet = in_quiet_hours(settings, now.astimezone(tz))
        for step, n in skip:
            await _claim(
                source_key,
                org_id,
                case,
                step,
                n,
                "skipped",
                {"why": "passed together with a later step"},
            )
        for step, n in run:
            kinds = {a.get("do") for a in step["actions"]}
            if quiet and kinds <= MESSAGE_ONLY:
                continue  # only messages: they wait for the morning (nothing is written, so the next pass tries again)
            try:
                await fire(
                    source_key, org, settings, case, step, n, now, tz, start_status
                )
            except Exception as e:
                logger.error(
                    f"reminder plans: case {case.get('case_number')} step failed: {e}",
                    exc_info=True,
                )


async def _start_status(source_key: str) -> str | None:
    """The status a new ticket gets (the column's default), for "only if it is still not started"."""
    row = await fetch_one(
        "SELECT column_default FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name = 'cases' AND column_name = 'status'",
        source_key=source_key,
    )
    text = (row or {}).get("column_default") or ""
    return text.split("'")[1] if text.count("'") >= 2 else None


async def _claim(source_key, org_id, case, step, n, outcome, detail) -> bool:
    """Write the step's row for this ticket first. False when it was already there (another copy of the app ran it)."""
    row = await fetch_one(
        "INSERT INTO case_reminder_log (org_id, case_id, step_id, tat_cycle, repeat_no, outcome, detail) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb) "
        "ON CONFLICT (case_id, step_id, tat_cycle, repeat_no) WHERE step_id IS NOT NULL DO NOTHING RETURNING id",
        org_id,
        case["id"],
        step["id"],
        case.get("tat_cycle") or 0,
        n,
        outcome,
        json.dumps(detail),
        source_key=source_key,
    )
    return bool(row)


async def _people(source_key, case) -> dict:
    """Who is on the ticket now: handler, backups, watchers, raiser (active people only, each a dict)."""
    rows = await fetch_all(
        "SELECT u.id, u.name, u.phone, p.party_role, p.added_at FROM case_parties p JOIN users u ON u.id = p.user_id "
        "WHERE p.case_id = $1 AND p.ended_at IS NULL AND u.is_active ORDER BY p.added_at",
        case["id"],
        source_key=source_key,
    )
    by = {"assignee": [], "level2": [], "watcher": [], "requester": []}
    for r in rows:
        if r["party_role"] in by:
            by[r["party_role"]].append(dict(r))
    handler = next(
        (p for p in by["assignee"] if p["id"] == case.get("assigned_to_id")), None
    )
    if handler is None and case.get("assigned_to_id"):
        handler = await fetch_one(
            "SELECT id, name, phone FROM users WHERE id = $1 AND is_active",
            case["assigned_to_id"],
            source_key=source_key,
        )
        handler = dict(handler) if handler else None
    hid = handler["id"] if handler else None
    raiser = next(iter(by["requester"]), None)
    return {
        "handler": handler,
        "backups": [p for p in by["level2"] if p["id"] != hid],
        "watchers": [p for p in by["watcher"] if p["id"] != hid],
        "raiser": raiser if raiser and raiser["id"] != hid else None,
    }


async def _acted(source_key, case) -> bool:
    """Has the current handler done anything on the ticket since they got it?"""
    if not case.get("assigned_to_id"):
        return False
    row = await fetch_one(
        "SELECT 1 AS yes FROM case_activity WHERE case_id = $1 AND actor_user_id = $2 "
        "AND activity_type = ANY($3::text[]) AND created_at >= COALESCE($4, created_at) LIMIT 1",
        case["id"],
        case["assigned_to_id"],
        list(ACTED),
        case.get("assigned_at"),
        source_key=source_key,
    )
    return bool(row)


async def fire(source_key, org, settings, case, step, n, now, tz, start_status) -> None:
    """Run one step on one ticket: check its condition, hand over if asked, then tell people, and write it all down."""
    org_id = org["id"]
    if not await _claim(source_key, org_id, case, step, n, "done", {}):
        return
    only = step.get("only_if") or "always"
    reason = None
    if only == "no_action" and await _acted(source_key, case):
        reason = "the handler had already acted"
    elif only == "not_started" and start_status and case.get("status") != start_status:
        reason = "it had already started"
    if reason:
        await _finish(source_key, org_id, case, step, n, "skipped", {"why": reason})
        return

    people = await _people(source_key, case)
    c = clock(case, now)
    percent = (
        None
        if c["percent"] is None
        else (math.floor(c["percent"]) if c["percent"] != math.inf else 100)
    )
    moved_from = moved_to = None
    detail: dict = {"percent": percent, "told": [], "not_reached": []}

    acts = step["actions"]
    if any(a.get("do") == "reassign" for a in acts):
        target = next(iter(people["backups"]), None)
        if target:
            moved_from, moved_to = people["handler"], target
            await _hand_over(source_key, org_id, case, moved_from, target, percent)
            people = await _people(source_key, {**case, "assigned_to_id": target["id"]})
            detail["moved_to"] = target["name"]
        else:
            detail["no_backup"] = True
    if any(a.get("do") == "raise_priority" for a in acts) and PRIORITY_UP.get(
        case.get("priority") or ""
    ):
        higher = PRIORITY_UP[case["priority"]]
        await execute(
            "UPDATE cases SET priority = $1 WHERE id = $2",
            higher,
            case["id"],
            source_key=source_key,
        )
        await _activity(
            source_key,
            org_id,
            case,
            "priority_change",
            {"from": case["priority"], "to": higher, "by": "reminder plan"},
        )
        detail["priority"] = higher

    handler = people["handler"]
    values = {
        "ticket": _ticket_words(case),
        "percent": str(percent if percent is not None else ""),
        "due": case["due_date"].astimezone(tz).strftime("%d/%m %H:%M")
        if case.get("due_date")
        else "",
        "handler": (handler or {}).get("name") or "nobody yet",
        "open_for": length_text(int(c["elapsed"])),
    }
    timed = c["percent"] is not None
    late = timed and c["percent"] >= 100
    # one message per person per step: the first reason to tell them wins
    send: dict = {}

    def add(person, key):
        if person and person.get("phone") and person["id"] not in send:
            send[person["id"]] = (person, key)

    if moved_to:
        add(
            moved_to,
            "reminder.handed_to_you" if timed else "reminder.handed_to_you_open",
        )
        add(moved_from, "reminder.handed_away")
    for a in acts:
        do, to = a.get("do"), a.get("to")
        if do == "remind":
            add(
                handler,
                ("reminder.overdue" if late else "reminder.remind")
                if timed
                else "reminder.open_nudge",
            )
        elif do == "tell" and to == "backup":
            for p in people["backups"]:
                add(p, "reminder.backup" if timed else "reminder.backup_open")
        elif do == "tell" and to == "raiser":
            add(people["raiser"], "reminder.raiser_late" if late else "reminder.raiser")
        elif do == "tell" and to == "also":
            for p in people["watchers"]:
                add(p, "reminder.watcher" if timed else "reminder.watcher_open")
        elif do == "tell" and (a.get("role_id") or a.get("user_id")):
            for p in await _members(source_key, org_id, a):
                add(p, "reminder.role" if timed else "reminder.role_open")

    from app.services import reach

    for person, key in send.values():
        text = await say(source_key, key, **{k: values[k] for k in _needs(key)})
        try:
            await reach.deliver_text(
                person["phone"],
                text,
                source_key=source_key,
                org_id=org_id,
                org_name=org.get("name") or "",
            )
            detail["told"].append(person["name"])
        except Exception as e:
            logger.warning(
                f"reminder for {case.get('case_number')} not delivered to one person: {e}"
            )
            detail["not_reached"].append(person["name"])

    outcome = (
        "done" if detail["told"] or moved_to or detail.get("priority") else "failed"
    )
    await _finish(source_key, org_id, case, step, n, outcome, detail)
    await _activity(source_key, org_id, case, "reminder", {
        "percent": percent, "open_for": None if timed else values["open_for"], "step_id": str(step["id"]),
        "told": detail["told"], "moved_to": detail.get("moved_to"),
    })  # fmt: skip


def _needs(key: str) -> list[str]:
    from app.services.messages import MESSAGES

    return list(MESSAGES[key].values)


def _ticket_words(case: dict) -> str:
    bits = [b for b in [case.get("title"), case.get("location")] if b]
    return (
        f"{case.get('case_number')} ({', '.join(bits)})"
        if bits
        else str(case.get("case_number"))
    )


async def _members(source_key, org_id, action: dict) -> list[dict]:
    if action.get("user_id"):
        rows = await fetch_all(
            "SELECT id, name, phone FROM users WHERE org_id = $1 AND id = $2 AND is_active",
            org_id, action["user_id"], source_key=source_key,
        )  # fmt: skip
    else:
        rows = await fetch_all(
            "SELECT id, name, phone FROM users WHERE org_id = $1 AND role_id = $2 AND is_active",
            org_id, action["role_id"], source_key=source_key,
        )  # fmt: skip
    return [dict(r) for r in rows]


async def _hand_over(source_key, org_id, case, old, new, percent) -> None:
    """Give the ticket to its backup, the way a hand-over on the dashboard does: the database trigger moves the parties;
    the old handler stays on the ticket as a backup, so they keep hearing about it."""
    pool = await get_pool(source_key)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE cases SET assigned_to_id = $1 WHERE id = $2", new["id"], case["id"]
        )
        if old:
            await conn.execute(
                "INSERT INTO case_parties (org_id, case_id, user_id, party_role) VALUES ($1, $2, $3, 'level2') "
                "ON CONFLICT (case_id, user_id, party_role) WHERE ended_at IS NULL DO NOTHING",
                org_id, case["id"], old["id"],
            )  # fmt: skip
        await conn.execute(
            "INSERT INTO case_activity (org_id, case_id, activity_type, payload) VALUES ($1, $2, 'escalation', $3::jsonb)",
            org_id, case["id"],
            json.dumps({"from": str(old["id"]) if old else None, "to": str(new["id"]), "to_name": new["name"],
                        "why": "nobody acted in time", "percent": percent, "by": "reminder plan"}),
        )  # fmt: skip


async def _activity(source_key, org_id, case, kind, payload) -> None:
    await execute(
        "INSERT INTO case_activity (org_id, case_id, activity_type, payload) VALUES ($1, $2, $3, $4::jsonb)",
        org_id, case["id"], kind, json.dumps(payload, default=str), source_key=source_key,
    )  # fmt: skip


async def _finish(source_key, org_id, case, step, n, outcome, detail) -> None:
    await execute(
        "UPDATE case_reminder_log SET outcome = $1, detail = $2::jsonb, fired_at = now() "
        "WHERE case_id = $3 AND step_id = $4 AND tat_cycle = $5 AND repeat_no = $6",
        outcome, json.dumps(detail, default=str), case["id"], step["id"], case.get("tat_cycle") or 0, n,
        source_key=source_key,
    )  # fmt: skip
