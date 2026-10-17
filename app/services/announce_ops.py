"""The two steps a flow uses to send an announcement (the same sending as the Announcements screen, see
services/announcements.py):

    people.find   Find people by their flat (lives here, relation, primary member, wing) and role. Either name one of
                  the ready choices (announcement_audiences, for example "Everyone who lives here") or give the ticks.
                  Keeps the people under a name (default "people") with how many they are, for the steps after.
    notify.group  Send a message to the people found: saved as an announcement and sent in the background, with the
                  24-hour handling of WhatsApp, the approved template and the delivery report on the dashboard.

In a preview ("Try it", or the summary before someone says yes) people.find runs for real (it only reads), so the
person sees how many it goes to; notify.group only says what it would do."""

import json

from app.db import fetch_all, fetch_one, get_pool
from app.logging_config import get_context_logger
from app.services import announcements as ann

logger = get_context_logger(__name__)


def _si():
    from app.services import step_interpreter

    return step_interpreter


def _preview(ctx: dict, sentence: str) -> None:
    ctx.setdefault("preview", []).append(sentence)


async def _ready_choice(ctx: dict, name: str) -> dict | None:
    """A ready choice by its name: the same name first, else the only one whose name holds the words."""
    rows = await fetch_all(
        "SELECT name, filters FROM announcement_audiences WHERE org_id = $1 ORDER BY sort_order, name",
        ctx["org_id"],
        source_key=ctx["source_key"],
    )
    want = " ".join(str(name or "").lower().split())
    exact = [r for r in rows if r["name"].lower() == want]
    found = exact or [r for r in rows if want and want in r["name"].lower()]
    if len(found) != 1:
        return None
    f = found[0]["filters"]
    return {
        "name": found[0]["name"],
        "filters": f if isinstance(f, dict) else json.loads(f),
    }


async def _choice_names(ctx: dict) -> str:
    rows = await fetch_all(
        "SELECT name FROM announcement_audiences WHERE org_id = $1 ORDER BY sort_order, name",
        ctx["org_id"],
        source_key=ctx["source_key"],
    )
    return ", ".join(f"“{r['name']}”" for r in rows) or "(none yet)"


async def _op_find_people(params: dict, ctx: dict) -> dict:
    """
    params:
      audience   the name of a ready choice, or a $path to the field that holds it (for example $fields.audience)
      filters    the ticks instead: {"lives": [...], "relations": [...], "primary": ..., "wings": [...], "roles": [...]}
      into       the name the steps after use (default people)
    """
    si = _si()
    into = params.get("into") or "people"
    name, filters = "", params.get("filters")
    if params.get("audience"):
        asked = (
            si._resolve_path(ctx, params["audience"])
            if str(params["audience"]).startswith("$")
            else params["audience"]
        )
        hit = await _ready_choice(ctx, asked)
        if not hit:
            raise si.StepError(
                f"There is no ready choice called “{asked}”. Choose one of: {await _choice_names(ctx)}."
            )
        name, filters = hit["name"], hit["filters"]
    if not isinstance(filters, dict):
        raise si.StepError("Find people: name a ready choice, or tick who it is for.")
    try:
        clean = ann.clean_filters(filters)
    except ValueError as e:
        raise si.StepError(f"Find people: {e}") from e
    people = await ann.audience(ctx["source_key"], ctx["org_id"], clean)
    ctx[into] = {
        "count": len(people),
        "ids": [str(p["id"]) for p in people],
        "names": [p["name"] for p in people],
        "filters": clean,
        "audience_name": name,
    }
    ctx["fields"][f"{into}_count"] = len(people)
    shown = ", ".join(p["name"] for p in people[:8]) + (
        f" and {len(people) - 8} more" if len(people) > 8 else ""
    )
    _preview(
        ctx,
        f"Goes to {len(people)} {'person' if len(people) == 1 else 'people'}"
        + (f": {shown}" if people else ""),
    )
    return ctx


async def _op_send_to_group(params: dict, ctx: dict) -> dict:
    """
    params:
      people    the people found earlier (default $people)
      message   the message, or a $path to the field that holds it (for example $fields.message)
      title     a heading (optional), or a $path
      greet     start with "Dear <first name>" (default yes)
    """
    si = _si()
    found = si._resolve_path(ctx, params.get("people") or "$people")
    if not isinstance(found, dict) or "filters" not in found:
        raise si.StepError(
            "Send to a group: find the people first (a “Find people” step)."
        )
    raw = params.get("message")
    text = si._resolve_path(ctx, raw) if str(raw or "").startswith("$") else raw
    raw_title = params.get("title") or ""
    title = (
        si._resolve_path(ctx, raw_title)
        if str(raw_title).startswith("$")
        else raw_title
    )
    text, title = str(text or "").strip(), str(title or "").strip()
    if not text:
        raise si.StepError("Send to a group: there is no message to send.")
    if not found["count"]:
        raise si.StepError("Nobody matches, so there is nobody to send it to.")
    if ctx.get("dry_run"):
        _preview(
            ctx,
            f"It will be sent to {found['count']} people, and you can see who got it on the dashboard",
        )
        return ctx
    pool = await get_pool(ctx["source_key"])
    if not await pool.fetchval(
        "SELECT to_regclass('public.announcements') IS NOT NULL"
    ):
        raise si.StepError("This organisation cannot send announcements yet.")
    user = ctx.get("user") or {}
    words = found.get("audience_name") or ""
    new_id = await pool.fetchval(
        "INSERT INTO announcements (org_id, title, body, greet, filters, audience_text, audience_name, status, "
        "send_at, created_by) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, 'planned', now(), $8) RETURNING id",
        ctx["org_id"],
        title[:120],
        text[:3000],
        params.get("greet") is not False,
        json.dumps(found["filters"]),
        words,
        words,
        "chat bot · " + (user.get("user_name") or user.get("name") or "someone"),
    )
    org = await fetch_one(
        "SELECT name FROM orgs WHERE id = $1",
        ctx["org_id"],
        source_key=ctx["source_key"],
    )
    logger.info(
        f"announcement {new_id} from a flow for {found['count']} people ({org['name'] if org else ''})"
    )
    ann.start_now(ctx["source_key"], new_id)
    ctx["announcement"] = {"id": str(new_id), "people": found["count"]}
    ctx["fields"]["announcement_people"] = found["count"]
    return ctx


ANNOUNCE_PRIMITIVES = {
    "people.find": _op_find_people,
    "notify.group": _op_send_to_group,
}
