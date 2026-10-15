"""How a flow can start without a person starting it: on a schedule, or after another flow.

A flow starts in one of three ways. Someone does it (the menu, a phrase, a /command, a button: this
file is not involved), it runs on a timer, or it runs when another flow finishes.

* On a schedule: one row in flow_schedules per flow (every day, week or month at a time, in the
  organisation's time zone, optionally only on working days). An every-minute job (jobs.py) calls
  run_due_schedules(). It moves next_run_at on BEFORE it runs the flow, with a compare-and-set, so a
  slot is never run twice even if two copies of the app race, and a slot that was missed (the app was
  down) runs once when it is back, not once per missed slot.
* After another flow: one row in flow_chains per flow ("this flow starts after that flow"). The engine
  calls after_done() when a flow finishes with success. A loop is refused when it is saved
  (chain_problem) and, whatever the data says, a flow that is already in the chain is never run
  again and a chain is cut at max_chain_depth.

A flow that starts by itself has nobody to ask, so it must need no input (unfit_reasons says why not).
It runs as a "System" actor that holds every right the organisation's roles hold, because nobody is
there to be checked. Every run, from either way and from "Run it now", is written to flow_runs.

Nothing here knows what a flow does: it only decides when to start it and records what happened."""

import calendar
import contextvars
import datetime as dt
import json
import time
from zoneinfo import ZoneInfo

from app.db import execute, fetch_all, fetch_one, get_all_source_keys
from app.logging_config import get_context_logger
from app.services import config_store

logger = get_context_logger(__name__)

NIL_ID = "00000000-0000-0000-0000-000000000000"
# Monday = 0 ... Sunday = 6, as Python counts. The organisation can change both in its settings
# (orgs.settings.working_days, orgs.settings.holidays); these are only the fallback.
DEFAULT_WORKING_DAYS = (0, 1, 2, 3, 4)
DEFAULT_MAX_CHAIN_DEPTH = 5  # orgs.settings.flows.max_chain_depth
DAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_EVERY = ("day", "week", "month")
_HALTING_STEPS = ("otp_gate", "approval_gate")

# how deep the chain of "after another flow" runs is right now, and which flows are in it: set while a
# flow runs, so the engine's hook knows where it is without every caller passing it along
_depth: contextvars.ContextVar[int] = contextvars.ContextVar("flow_depth", default=0)
_path: contextvars.ContextVar[tuple] = contextvars.ContextVar("flow_path", default=())
# databases that do not have the tables yet (source_key -> when we found out), so a finished flow does not
# ask a question that cannot work every time; looked at again after a minute, once the migration is applied
_no_tables: dict[str, float] = {}
_NO_TABLES_FOR = 60


def _jb(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value


# ── the cadence: what the admin picks, checked and turned into words and times ─────────────


def clean_cadence(raw) -> tuple[dict | None, list[str]]:
    """The cadence as it will be stored, and the problems in plain words (empty when fine)."""
    if not isinstance(raw, dict):
        return None, ["Choose how often it should run."]
    problems: list[str] = []
    every = raw.get("every")
    if every not in _EVERY:
        problems.append("Choose how often it should run: every day, week or month.")
    at = str(raw.get("time") or "")
    hour = minute = 0
    try:
        hour, minute = (int(x) for x in at.split(":")[:2])
        if not (0 <= hour <= 23 and 0 <= minute <= 59) or len(at.split(":")) != 2:
            raise ValueError
    except ValueError:
        problems.append("Choose the time of day, for example 09:00.")
    out: dict = {"every": every, "time": f"{hour:02d}:{minute:02d}"}
    if every == "week":
        days = raw.get("days")
        days = sorted(
            {d for d in days if isinstance(d, int) and 0 <= d <= 6}
            if isinstance(days, list)
            else set()
        )
        if not days:
            problems.append("Choose at least one day of the week.")
        out["days"] = days
    if every == "month":
        dom = raw.get("day_of_month")
        if not isinstance(dom, int) or isinstance(dom, bool) or not 1 <= dom <= 31:
            problems.append("Choose the day of the month, from 1 to 31.")
            dom = 1
        out["day_of_month"] = dom
    out["working_days_only"] = bool(raw.get("working_days_only"))
    return (None if problems else out), problems


def _ordinal(n: int) -> str:
    suffix = (
        "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    )
    return f"{n}{suffix}"


def _clock(text: str) -> str:
    hour, minute = (int(x) for x in text.split(":"))
    return f"{hour % 12 or 12}:{minute:02d} {'pm' if hour >= 12 else 'am'}"


def cadence_words(c: dict) -> str:
    """'Every Monday and Friday at 9:00 am, on working days only'."""
    when = _clock(c["time"])
    if c["every"] == "day":
        text = f"Every day at {when}"
    elif c["every"] == "week":
        names = [DAY_NAMES[d] for d in c.get("days") or []]
        text = (
            "Every "
            + (
                ", ".join(names[:-1]) + " and " + names[-1]
                if len(names) > 1
                else names[0]
            )
            + f" at {when}"
        )
    else:
        dom = c["day_of_month"]
        text = f"On the {_ordinal(dom)} of every month at {when}"
        if dom > 28:
            text += " (the last day in a shorter month)"
    if c.get("working_days_only"):
        text += (
            ", the next working day if it is a day off"
            if c["every"] == "month"
            else ", on working days only"
        )
    return text


def zone_of(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or config_store.DEFAULT_TIMEZONE)
    except Exception:
        return ZoneInfo(config_store.DEFAULT_TIMEZONE)


def _working(settings: dict | None) -> tuple[set[int], set[str]]:
    s = settings or {}
    days = s.get("working_days")
    days = (
        {d for d in days if isinstance(d, int) and 0 <= d <= 6}
        if isinstance(days, list)
        else set()
    )
    holidays = s.get("holidays")
    return (
        days or set(DEFAULT_WORKING_DAYS),
        {str(h) for h in holidays} if isinstance(holidays, list) else set(),
    )


def next_run(
    c: dict, after: dt.datetime, tz: ZoneInfo, settings: dict | None = None
) -> dt.datetime:
    """The first moment after `after` (aware) the cadence says to run, as UTC. The time of day is in
    the organisation's time zone. 'Working days only' skips a day off for a daily or weekly flow and
    moves a monthly flow to the next working day."""
    work, holidays = _working(settings)

    def is_work(day: dt.date) -> bool:
        return day.weekday() in work and day.isoformat() not in holidays

    hour, minute = (int(x) for x in c["time"].split(":"))
    first = after.astimezone(tz).date()
    for add in range(800):
        day = first + dt.timedelta(days=add)
        if c["every"] == "week" and day.weekday() not in (c.get("days") or []):
            continue
        if c["every"] == "month":
            last = calendar.monthrange(day.year, day.month)[1]
            if day.day != min(c["day_of_month"], last):
                continue
        if c.get("working_days_only"):
            if c["every"] == "month":
                for _ in range(14):  # a day off moves it to the next working day
                    if is_work(day):
                        break
                    day += dt.timedelta(days=1)
            elif not is_work(day):
                continue
        at = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz).astimezone(
            dt.timezone.utc
        )
        if at > after:
            return at
    # a valid cadence always has a run time within a few years
    raise ValueError("no run time found")


# ── can this flow start by itself? ───────────────────────────────────────────────────────────


def unfit_reasons(w: dict) -> list[str]:
    """Why this flow cannot start on its own, in plain words (empty when it can). w holds name, kind,
    workflow_type, steps, entity_schema and gates as the database or the editor has them."""
    name = w.get("name") or "This flow"
    kind = w.get("kind") or "workflow"
    if kind == "block":
        return [
            f"“{name}” is a building block. Other flows run it, so it cannot start by itself."
        ]
    if kind == "case_action":
        return [
            f"“{name}” is a button on a ticket, so it needs a ticket to work on and cannot start by itself."
        ]
    if w.get("workflow_type") == "read":
        return [
            f"“{name}” answers with a saved report for a person who asks, so it cannot start by itself."
        ]
    problems = []
    steps = [s for s in _jb(w.get("steps"), []) if isinstance(s, dict)]
    if not steps:
        problems.append(f"“{name}” has no steps yet, so there is nothing to run.")
    asked = [
        (
            spec.get("label")
            if isinstance(spec, dict) and spec.get("label")
            else key.replace("_", " ")
        )
        for key, spec in _jb(w.get("entity_schema"), {}).items()
        if isinstance(spec, dict) and (spec.get("required") or spec.get("required_if"))
    ]
    if asked:
        problems.append(
            f"“{name}” has to ask for {', '.join(asked)}. A flow that starts by itself has nobody to "
            "ask, so make those optional or take them out first."
        )
    if any(s.get("op") in _HALTING_STEPS for s in steps):
        problems.append(
            f"“{name}” waits for a code or an approval from a person, which a flow that starts by "
            "itself cannot get."
        )
    return problems


async def chain_problem(
    source_key: str, org_id: str, workflow_id, after_id, names: dict | None = None
) -> str | None:
    """Why `workflow_id` may not start after `after_id`, or None. Each flow has one 'after' flow, so
    following those from `after_id` upwards finds a loop: if it reaches `workflow_id`, it would go round."""
    if str(workflow_id) == str(after_id):
        return "A flow cannot start after itself."
    links = {
        str(r["workflow_id"]): str(r["after_workflow_id"])
        for r in await fetch_all(
            "SELECT workflow_id, after_workflow_id FROM flow_chains WHERE org_id = $1",
            org_id,
            source_key=source_key,
        )
    }
    links.pop(str(workflow_id), None)  # whatever it followed before is being replaced
    seen, here = [], str(after_id)
    while here in links and here not in seen:
        seen.append(here)
        here = links[here]
        if here == str(workflow_id):
            break
    if here == str(workflow_id):
        both = {
            str(r["id"]): r["name"]
            for r in await fetch_all(
                "SELECT id, name FROM workflows WHERE id = ANY($1::uuid[])",
                [workflow_id, after_id],
                source_key=source_key,
            )
        }
        a, b = (
            both.get(str(workflow_id), "This flow"),
            both.get(str(after_id), "that flow"),
        )
        return (
            f"“{b}” already runs after “{a}” (directly or through other flows), so “{a}” cannot "
            f"run after “{b}”. That would go round in circles."
        )
    return None


# ── who runs it ──────────────────────────────────────────────────────────────────────────────


async def system_actor(source_key: str, org_id: str) -> dict:
    """The 'person' a flow runs as when nobody started it: it holds every right any role holds,
    because the admin who set the flow up chose to run it and nobody is there to be checked. It is
    not a row in the people list."""
    org = await fetch_one(
        "SELECT name FROM orgs WHERE id = $1", org_id, source_key=source_key
    )
    perms: set[str] = set()
    tables: set[str] = set()
    entities: set[str] = set()
    for r in await fetch_all(
        "SELECT to_jsonb(r) AS j FROM roles r WHERE org_id = $1",
        org_id,
        source_key=source_key,
    ):
        j = _jb(r["j"], {})
        perms.update(j.get("permissions") or [])
        tables.update(j.get("readable_tables") or [])
        entities.update(j.get("readable_entity_types") or [])
    perms.update(
        r["intent_key"]
        for r in await fetch_all(
            "SELECT intent_key FROM workflows WHERE org_id = $1",
            org_id,
            source_key=source_key,
        )
    )
    return {
        "user_id": NIL_ID,
        "user_name": "System",
        "email": "",
        "phone": "",
        "is_active": True,
        "role_id": NIL_ID,
        "role": "system",
        "permissions": sorted(perms),
        "readable_tables": sorted(tables),
        "readable_entity_types": sorted(entities),
        "org_id": str(org_id),
        "org_name": (org or {}).get("name") or "",
        "source_key": source_key,
    }


async def _org_settings(source_key: str, org_id: str) -> tuple[dict, ZoneInfo]:
    row = await fetch_one(
        "SELECT settings, to_jsonb(o)->>'timezone' AS tz FROM orgs o WHERE id = $1",
        org_id,
        source_key=source_key,
    )
    return _jb(row["settings"] if row else None, {}), zone_of(
        row["tz"] if row else None
    )


# ── running a flow and writing down what happened ────────────────────────────────────────────


async def log_run(
    source_key: str,
    org_id: str,
    workflow_id,
    how: str,
    status: str,
    message: str,
    *,
    caused_by=None,
    depth: int = 0,
    started: dt.datetime | None = None,
) -> None:
    try:
        await execute(
            "INSERT INTO flow_runs (org_id, workflow_id, how_started, status, message, "
            "caused_by_id, depth, started_at, finished_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, COALESCE($8, now()), now())",
            org_id,
            workflow_id,
            how,
            status,
            (message or "")[:500],
            caused_by,
            depth,
            started,
            source_key=source_key,
        )
    except Exception as e:  # the log is never worth stopping a flow for
        logger.warning(f"flow_runs write failed: {e}")


def _outcome(result: dict) -> tuple[str, str]:
    """('success' | 'failed', plain words) from what the engine answered."""
    status = result.get("status")
    if status == "done":
        return "success", result.get("message") or "Done."
    if status == "ambiguous":
        return "failed", "It found more than one match and had nobody to ask which."
    if status in ("awaiting_otp", "awaiting_approval"):
        return "failed", "It stopped to wait for a code or an approval from a person."
    return "failed", result.get("message") or "It stopped before it finished."


async def run_flow(
    source_key: str,
    org_id: str,
    w: dict,
    *,
    how: str,
    caused_by=None,
    depth: int = 0,
) -> dict:
    """Run one flow as the System actor and write it in flow_runs. Never raises: the answer is
    {'status': 'success' | 'failed' | 'skipped', 'message': words}."""
    from app.services.step_interpreter import run_workflow_steps

    started = dt.datetime.now(dt.timezone.utc)
    wid = str(w["id"])

    async def done(status: str, message: str) -> dict:
        await log_run(
            source_key, org_id, wid, how, status, message,
            caused_by=caused_by, depth=depth, started=started,
        )  # fmt: skip
        return {"status": status, "message": message}

    if not w.get("is_active"):
        return await done(
            "skipped",
            "The flow is switched off, so it was not run. Switch it on first.",
        )
    path = _path.get()
    if wid in path:
        return await done("failed", "Stopped: it would have run itself again.")
    reasons = unfit_reasons(w)
    if reasons:
        return await done("failed", " ".join(reasons))
    tok_d, tok_p = _depth.set(depth), _path.set((*path, wid))
    try:
        actor = await system_actor(source_key, org_id)
        result = await run_workflow_steps(dict(w), {}, actor, "")
        status, message = _outcome(result)
    except Exception as e:
        logger.error(f"flow {w.get('intent_key')} crashed when started by {how}: {e!r}")
        status, message = "failed", "It could not run: " + str(e)[:300]
    finally:
        _depth.reset(tok_d)
        _path.reset(tok_p)
    return await done(status, message)


async def run_due_schedules(now: dt.datetime | None = None) -> int:
    """The every-minute job: run every flow whose time has come, once. Returns how many were started."""
    now = now or dt.datetime.now(dt.timezone.utc)
    started = 0
    for source_key in await get_all_source_keys():
        try:
            due = await fetch_all(
                "SELECT s.id, s.org_id, s.workflow_id, s.cadence, s.next_run_at "
                "FROM flow_schedules s WHERE s.is_active AND s.next_run_at <= $1 "
                "ORDER BY s.next_run_at LIMIT 50",
                now,
                source_key=source_key,
            )
        except Exception as e:
            # no such table in this database yet, or it cannot be reached
            logger.debug(f"flow schedules: nothing read for {source_key}: {e}")
            continue
        for s in due:
            try:
                started += await _claim_and_run(source_key, s, now)
            except Exception as e:  # one flow must not stop the others
                logger.error(f"flow schedule {s['id']} failed: {e!r}")
    return started


async def _claim_and_run(source_key: str, s, now: dt.datetime) -> int:
    settings, tz = await _org_settings(source_key, s["org_id"])
    cadence = _jb(s["cadence"], {})
    # the next slot is counted from NOW, so a slot that was missed runs once and not once per slot;
    # the update only wins when next_run_at is still what we read, so a second copy of the app that
    # read the same row loses and does nothing
    try:
        following = next_run(cadence, now, tz, settings)
    except (KeyError, ValueError):
        # a cadence that cannot be read: switch it off rather than loop on it
        following = None
    claimed = await fetch_one(
        "UPDATE flow_schedules SET next_run_at = $3, last_run_at = $4, updated_at = now(), "
        "is_active = (is_active AND $3::timestamptz IS NOT NULL) "
        "WHERE id = $1 AND next_run_at = $2 AND is_active RETURNING id",
        s["id"],
        s["next_run_at"],
        following,
        now,
        source_key=source_key,
    )
    if not claimed:
        return 0
    w = await fetch_one(
        "SELECT * FROM workflows WHERE id = $1 AND org_id = $2",
        s["workflow_id"],
        s["org_id"],
        source_key=source_key,
    )
    if not w:
        return 0
    await run_flow(source_key, str(s["org_id"]), dict(w), how="schedule")
    return 1


async def after_done(workflow: dict, user: dict) -> None:
    """Called by the engine when a flow finished with success: start the flows that follow it. Never
    raises, and never changes what the finished flow answered."""
    try:
        wid = workflow.get("id")
        source_key, org_id = user.get("source_key"), user.get("org_id")
        if not (wid and source_key and org_id):
            return
        if (
            time.monotonic() - _no_tables.get(source_key, -_NO_TABLES_FOR)
            < _NO_TABLES_FOR
        ):
            return
        try:
            kids = await fetch_all(
                "SELECT w.* FROM flow_chains c JOIN workflows w ON w.id = c.workflow_id "
                "WHERE c.after_workflow_id = $1 AND c.org_id = $2 ORDER BY w.name",
                wid,
                org_id,
                source_key=source_key,
            )
        except Exception:  # an older database without the tables: nothing follows
            _no_tables[source_key] = time.monotonic()
            return
        if not kids:
            return
        settings, _ = await _org_settings(source_key, org_id)
        cap = (settings.get("flows") or {}).get("max_chain_depth")
        cap = cap if isinstance(cap, int) and cap > 0 else DEFAULT_MAX_CHAIN_DEPTH
        depth = _depth.get() + 1
        # the finished flow counts as part of the chain even when a person started it from the chat
        token = _path.set((*_path.get(), str(wid)))
        try:
            for kid in kids:
                if depth > cap:
                    await log_run(
                        source_key, org_id, kid["id"], "after_flow", "failed",
                        f"Stopped: more than {cap} flows would have run one after the other.",
                        caused_by=wid, depth=depth,
                    )  # fmt: skip
                    continue
                await run_flow(
                    source_key,
                    str(org_id),
                    dict(kid),
                    how="after_flow",
                    caused_by=wid,
                    depth=depth,
                )
        finally:
            _path.reset(token)
    except Exception as e:
        logger.error(
            f"flows that follow {workflow.get('intent_key')} were not started: {e!r}"
        )
