"""The steps the "Build with AI" builder compiles a plain flow into (see flow_plain.py), next to the older steps.

    flow.decide   Works out a check ONCE and keeps the answer as yes / no under a name. The steps of each lane carry a
                  "when" on that name, so nothing a lane does later can move the flow into the other lane.
    flow.say      Says something to the person who asked. All that was said becomes the reply to them, in their own chat.
    flow.tell     Sends a message to everyone with a role (Committee, Facility manager ...), each in their own chat.
    flow.set      Keeps a value made from a text with values in it, for example "Wing [Wing], flat [Flat]".
    flow.lookup   Looks in a list (a table) for a row matching some values, and keeps whether one was found (yes / no).
    flow.my_flat  Finds the flat of the person who asked (their residents row), kept as fields._flat, like "B-1204".
    flow.stop     Ends the flow here. What was said so far is the reply.

Texts use {$path} for a value, for example "Booked {$fields.place} for {$fields.date}"; flow_plain.py writes them."""

import datetime as _dt
import re

from app.db import fetch_all, fetch_one
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

_TOKEN = re.compile(r"\{(\$[A-Za-z0-9_.]+)\}")


def _si():
    from app.services import step_interpreter

    return step_interpreter


def fill(text: str, ctx: dict) -> str:
    """The text with each {$path} replaced by its value, written the way a person reads it."""

    def one(m):
        v = _si()._resolve_path(ctx, m.group(1))
        if v is None or v == "":
            return "—"
        return _si()._nice(v) if hasattr(v, "isoformat") else str(v)

    return _TOKEN.sub(one, str(text or ""))


def _preview(ctx: dict, sentence: str) -> None:
    ctx.setdefault("preview", []).append(sentence)


async def _op_decide(params: dict, ctx: dict) -> dict:
    """{"into": "_if_1", "when": {guard}}: the guard is checked now, once."""
    ok = _si()._eval_guard(params.get("when") or {}, ctx)
    ctx["fields"][params["into"]] = "yes" if ok else "no"
    return ctx


async def _op_say(params: dict, ctx: dict) -> dict:
    text = fill(params.get("text"), ctx).strip()
    if text:
        ctx.setdefault("_say", []).append(text)
        if ctx.get("dry_run"):
            _preview(ctx, "Reply: " + text)
    return ctx


async def _role_people(ctx: dict, role: str) -> list[dict]:
    return [
        dict(r)
        for r in await fetch_all(
            "SELECT u.name, u.phone FROM users u JOIN roles r ON r.id = u.role_id "
            "WHERE u.org_id = $1 AND lower(r.name) = lower($2) AND coalesce(u.phone, '') <> '' "
            "AND coalesce(u.is_active, true)",
            ctx["org_id"],
            role,
            source_key=ctx["source_key"],
        )
    ]


async def _op_tell(params: dict, ctx: dict) -> dict:
    """{"role": "Committee", "text": "..."}: a message to everyone with that role, each in their own chat."""
    from app.services import reach

    role = str(params.get("role") or "").strip()
    text = fill(params.get("text"), ctx).strip()
    people = await _role_people(ctx, role) if role and text else []
    if ctx.get("dry_run"):
        _preview(ctx, f"Would tell {role} ({len(people)}): {text}")
        return ctx
    user = ctx.get("user") or {}
    for p in people:
        outcome = await reach.deliver_text(
            p["phone"],
            text,
            source_key=ctx.get("source_key"),
            org_id=ctx.get("org_id"),
            org_name=user.get("org_name") or "",
            sender=user,
        )
        if outcome.get("note"):
            ctx.setdefault("_notes", []).append(outcome["note"])
    if not people:
        logger.info(f"flow.tell: nobody has the role {role!r}")
    return ctx


async def _op_set(params: dict, ctx: dict) -> dict:
    """{"field": "where", "value": "Wing {$fields.wing}"}"""
    ctx["fields"][params["field"]] = fill(params.get("value"), ctx)
    return ctx


async def _op_lookup(params: dict, ctx: dict) -> dict:
    """{"table": "bookings", "match": {"place": "$fields.place", ...}, "into": "booking"}: keeps the row found (or
    None) as ctx[into], and fields[into + "_found"] = yes / no. Words are compared without minding capitals."""
    si = _si()
    table, into = params["table"], params.get("into") or "found"
    match = si._resolve_values(params.get("match") or {}, ctx)
    await si._load_schema_allowlist(ctx["source_key"])
    si._validate_table_and_columns(table, set(match), ctx["source_key"])
    await si._normalize_enum_values(table, match, ctx["source_key"])
    await si._normalize_date_values(table, match, ctx["source_key"])
    args, where = [ctx["org_id"]], []
    for col, val in match.items():
        if val is None or val == "":
            ctx[into], ctx["fields"][into + "_found"] = None, "no"
            return ctx
        args.append(val)
        where.append(
            f"lower({col}::text) = lower(${len(args)}::text)"
            if isinstance(val, str)
            else f"{col} = ${len(args)}"
        )
    sql = f"SELECT * FROM {table} WHERE org_id = $1" + "".join(" AND " + w for w in where) + " LIMIT 1"
    row = await fetch_one(sql, *args, source_key=ctx["source_key"])
    ctx[into] = dict(row) if row else None
    ctx["fields"][into + "_found"] = "yes" if row else "no"
    if ctx.get("dry_run"):
        _preview(ctx, f"Looked in {table}: {'found one' if row else 'none found'}")
    return ctx


async def _op_my_flat(params: dict, ctx: dict) -> dict:
    flat = ""
    args = (ctx["org_id"], str((ctx.get("user") or {}).get("user_id")))
    # the flat they live in first, when the database knows that (housing-0016); else any flat of theirs
    for order in ("ORDER BY coalesce(lives_here, true) DESC, coalesce(is_primary, false) DESC ", ""):
        try:
            row = await fetch_one(
                "SELECT wing, flat_no FROM residents WHERE org_id = $1 AND user_id = $2::uuid " + order + "LIMIT 1",
                *args,
                source_key=ctx["source_key"],
            )
            if row:
                flat = "-".join(x for x in (row["wing"], row["flat_no"]) if x)
            break
        except Exception as e:  # no such columns, or an organisation without flats
            logger.info(f"flow.my_flat: {e!r}")
    ctx["fields"]["_flat"] = flat
    return ctx


async def _op_stop(params: dict, ctx: dict) -> dict:
    ctx["_stop"] = True
    return ctx


FLOW_PRIMITIVES = {
    "flow.decide": _op_decide,
    "flow.say": _op_say,
    "flow.tell": _op_tell,
    "flow.set": _op_set,
    "flow.lookup": _op_lookup,
    "flow.my_flat": _op_my_flat,
    "flow.stop": _op_stop,
}


def parse_time(text: str) -> _dt.time | None:
    """'6 pm', '6:30pm', '18:00' -> a time, else None."""
    t = re.sub(r"\s+", "", str(text or "").lower()).replace(".", ":")
    for fmt in ("%I%p", "%I:%M%p", "%H:%M", "%H:%M:%S", "%H"):
        try:
            return _dt.datetime.strptime(t, fmt).time()
        except ValueError:
            continue
    return None
