"""
case_ops.py — the workflow steps that know about cases.

  case.categorize   sort a complaint into a category from the words in it (each category lists its keywords)
  case.route        find who handles a case in that category, who is level 2, and how long it may take
  case.authorize    stop unless the person is on the case (people whose role covers every case pass)
  case.add_parties  put people on a case (level 2, helper, watcher)
  case.attach_photos  keep the photos sent with a request on the case's timeline
  notify.parties    tell everyone on the case

Each step is a small, exact piece of SQL or Python. Nothing here asks a language model anything.
The steps are registered in step_interpreter.PRIMITIVES and described in step_catalog.STEP_TYPES.
They need the case tables of migration godrej_002; on a database without them a step reports that
plainly (or, for the lookups, finds nothing) instead of failing the whole workflow.
"""

import re
import string
import time

import asyncpg

from app.db import execute, fetch_all, fetch_one
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

# who is told first when one person holds several roles on a case
_ROLE_ORDER = ["assignee", "level2", "helper", "requester", "watcher"]
_MAX_PHOTOS = 5
_CATEGORY_CACHE_SECONDS = 60
_category_cache: dict[str, tuple[float, list[dict]]] = {}


def _si():
    """step_interpreter, imported late: it imports this module to register the steps."""
    from app.services import step_interpreter

    return step_interpreter


class _Blank(dict):
    """Values missing from a message template read as empty instead of leaving {braces} in a chat."""

    def __missing__(self, key):
        logger.warning(f"message template used an unknown value '{{{key}}}'")
        return ""


def _fill(template: str, values: dict) -> str:
    si = _si()
    text = si._fix_stray_escapes(template or "")
    try:
        return string.Formatter().vformat(text, (), _Blank(values))
    except (ValueError, IndexError, KeyError):
        return text


def _preview(ctx: dict, sentence: str) -> None:
    ctx.setdefault("preview", []).append(sentence)


def _top_key(ctx: dict) -> str | None:
    top = ctx.get("top_workflow") or ctx.get("workflow") or {}
    return top.get("intent_key")


# ── categories ───────────────────────────────────────────────────────────────


async def _categories(ctx: dict) -> list[dict]:
    key = f"{ctx['source_key']}:{ctx['org_id']}"
    hit = _category_cache.get(key)
    if hit and time.monotonic() - hit[0] < _CATEGORY_CACHE_SECONDS:
        return hit[1]
    try:
        rows = await fetch_all(
            "SELECT id, parent_id, key, label, default_priority, target_minutes, keywords, sort_order "
            "FROM case_categories WHERE org_id = $1 AND is_active",
            ctx["org_id"],
            source_key=ctx["source_key"],
        )
    except asyncpg.exceptions.UndefinedTableError:
        rows = []
    cats = [dict(r) for r in rows]
    by_id = {c["id"]: c for c in cats}
    for c in cats:
        chain, cur, hops = [c["label"]], c, 0
        while cur.get("parent_id") in by_id and hops < 8:
            cur = by_id[cur["parent_id"]]
            chain.append(cur["label"])
            hops += 1
        c["depth"] = len(chain)
        c["path"] = " › ".join(reversed(chain))
    _category_cache[key] = (time.monotonic(), cats)
    return cats


def _hits(text: str, keywords) -> int:
    """How many of a category's keywords start a word in the text ('plumb' finds 'plumbing')."""
    found = 0
    for kw in keywords or []:
        word = (kw or "").strip().lower()
        if not word:
            continue
        pattern = r"(?<!\w)" + re.escape(word)
        if kw.endswith(
            " "
        ):  # a keyword written with a trailing space must end the word too
            pattern += r"(?!\w)"
        if re.search(pattern, text):
            found += 1
    return found


def pick_category(text: str, categories: list[dict]) -> dict | None:
    """The category whose keywords the text matches best; a sub-category beats its parent on a tie."""
    text = (text or "").lower()
    best, best_key = None, None
    for c in categories:
        n = _hits(text, c.get("keywords"))
        if not n:
            continue
        key = (n, c["depth"], -(c.get("sort_order") or 0))
        if best_key is None or key > best_key:
            best, best_key = c, key
    return best


async def _op_categorize(params: dict, ctx: dict) -> dict:
    """
    Sort the complaint into a category from its words.
    params: text_from (list of $paths, default title and description), into (default "category")
    Sets the field category_id and category_label and keeps the category as $<into>.
    A category already chosen (field category_id) is kept.
    """
    si = _si()
    into = params.get("into") or "category"
    cats = await _categories(ctx)
    chosen = None
    if ctx["fields"].get("category_id"):
        chosen = next(
            (c for c in cats if str(c["id"]) == str(ctx["fields"]["category_id"])), None
        )
    if not chosen:
        sources = params.get("text_from") or ["$fields.title", "$fields.description"]
        text = " ".join(
            str(v) for v in (si._resolve_path(ctx, p) for p in sources) if v
        )
        chosen = pick_category(text, cats)
    if chosen:
        ctx[into] = {
            "id": str(chosen["id"]),
            "key": chosen["key"],
            "label": chosen["label"],
            "path": chosen["path"],
            "default_priority": chosen["default_priority"],
            "target_minutes": chosen["target_minutes"],
        }
        ctx["fields"]["category_id"] = str(chosen["id"])
        ctx["fields"]["category_label"] = chosen["path"]
        _preview(ctx, f"Filed under: {chosen['path']}")
    else:
        ctx["fields"]["category_label"] = "not sorted yet"
    return ctx


# ── routing ──────────────────────────────────────────────────────────────────


async def _op_route(params: dict, ctx: dict) -> dict:
    """
    Find who handles a case in this category, from the routing rules (the SQL function route_case).
    params: category_from (default $fields.category_id), priority_from (default $fields.priority),
            into (default "route")
    Keeps $<into> = {assignee_id, assignee_name, assignee_phone, level2_ids, level2_names,
    target_minutes, rule_name, via} and sets the fields assigned_name and, when a time is known,
    route_minutes. Finds nobody (and says so) when the category has no rule.
    """
    si = _si()
    into = params.get("into") or "route"
    category_id = si._resolve_path(
        ctx, params.get("category_from") or "$fields.category_id"
    )
    priority = si._resolve_path(ctx, params.get("priority_from") or "$fields.priority")
    route = {
        "assignee_id": None,
        "assignee_name": None,
        "assignee_phone": None,
        "level2_ids": [],
        "level2_names": [],
        "target_minutes": None,
        "rule_name": None,
        "via": None,
    }
    row = None
    if category_id:
        try:
            row = await fetch_one(
                "SELECT * FROM route_case($1::uuid, $2::uuid, '{}'::jsonb, $3, $4)",
                ctx["org_id"],
                str(category_id),
                _top_key(ctx),
                priority,
                source_key=ctx["source_key"],
            )
        except (
            asyncpg.exceptions.UndefinedFunctionError,
            asyncpg.exceptions.UndefinedTableError,
        ):
            row = None
    if row:
        ids = [x for x in [row["assignee_id"], *(row["level2_ids"] or [])] if x]
        people = {}
        if ids:
            people = {
                r["id"]: r
                for r in await fetch_all(
                    "SELECT id, name, phone FROM users WHERE id = ANY($1::uuid[])",
                    ids,
                    source_key=ctx["source_key"],
                )
            }
        boss = people.get(row["assignee_id"])
        route.update(
            assignee_id=str(row["assignee_id"]) if row["assignee_id"] else None,
            assignee_name=boss["name"] if boss else None,
            assignee_phone=boss["phone"] if boss else None,
            level2_ids=[str(x) for x in (row["level2_ids"] or [])],
            level2_names=[
                people[x]["name"] for x in (row["level2_ids"] or []) if x in people
            ],
            target_minutes=row["target_minutes"],
            rule_name=row["rule_name"],
            via=row["via"],
        )
    ctx[into] = route
    ctx["fields"]["assigned_name"] = route["assignee_name"] or "not assigned yet"
    if route["target_minutes"]:
        ctx["fields"]["route_minutes"] = route["target_minutes"]

    if route["assignee_name"]:
        sentence = f"It goes to {route['assignee_name']}"
        if route["level2_names"]:
            sentence += f", with {', '.join(route['level2_names'])} as level 2"
        _preview(ctx, sentence)
    elif category_id:
        _preview(
            ctx, "No one is set up to handle this category yet, so it starts unassigned"
        )
    return ctx


# ── who may act on a case ────────────────────────────────────────────────────


async def _op_authorize(params: dict, ctx: dict) -> dict:
    """
    Stop unless the person may act on this case.
    People whose role covers every case (admin, committee) always pass. Anyone else was given the
    workflow only because they are on a case (workflows.settings.who_can_use lists the roles), so
    they must be on THIS case in one of those roles.
    params: case (default $case), denied_message
    """
    si = _si()
    user = ctx["user"]
    allowed_roles = (user.get("party_access") or {}).get(_top_key(ctx))
    if allowed_roles is None:
        return ctx
    case = si._resolve_path(ctx, params.get("case") or "$case")
    if not isinstance(case, dict) or not case.get("id"):
        raise si.StepError("case.authorize: no case has been found yet")
    rows = await fetch_all(
        "SELECT party_role FROM case_parties "
        "WHERE case_id = $1 AND user_id = $2 AND ended_at IS NULL",
        case["id"],
        user["user_id"],
        source_key=ctx["source_key"],
    )
    if {r["party_role"] for r in rows} & set(allowed_roles):
        return ctx
    raise si.UserFacingStepError(
        params.get("denied_message")
        or "You can only do that on a case you are part of."
    )


# ── people and photos on a case ──────────────────────────────────────────────


def _as_ids(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v]
    return [str(value)]


async def _op_add_parties(params: dict, ctx: dict) -> dict:
    """
    Put people on a case.
    params: case_id (a $path), users_from (a $path to one id or a list of ids),
            role (level2 | helper | watcher)
    """
    si = _si()
    role = params.get("role")
    if role not in ("level2", "helper", "watcher"):
        raise si.StepError(
            "case.add_parties: the role must be level2, helper or watcher"
        )
    case_id = si._resolve_path(ctx, params.get("case_id"))
    ids = _as_ids(si._resolve_path(ctx, params.get("users_from")))
    if not case_id or not ids:
        return ctx
    if ctx.get("dry_run"):
        return ctx
    for uid in ids:
        await execute(
            "INSERT INTO case_parties (org_id, case_id, user_id, party_role, added_by) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (case_id, user_id, party_role) WHERE ended_at IS NULL DO NOTHING",
            ctx["org_id"],
            case_id,
            uid,
            role,
            ctx["user"]["user_id"],
            source_key=ctx["source_key"],
        )
    return ctx


async def _op_attach_photos(params: dict, ctx: dict) -> dict:
    """
    Keep the photos sent with the request on the case's timeline (Telegram file ids).
    params: case_id (a $path), photos_from (default $fields._photos)
    """
    si = _si()
    case_id = si._resolve_path(ctx, params.get("case_id"))
    photos = _as_ids(
        si._resolve_path(ctx, params.get("photos_from") or "$fields._photos")
    )
    if not case_id or not photos or ctx.get("dry_run"):
        return ctx
    import json

    for file_id in photos[:_MAX_PHOTOS]:
        await execute(
            "INSERT INTO case_activity (org_id, case_id, activity_type, actor_user_id, payload) "
            "VALUES ($1, $2, 'evidence', $3, $4::jsonb)",
            ctx["org_id"],
            case_id,
            ctx["user"]["user_id"],
            json.dumps({"telegram_file_id": file_id}),
            source_key=ctx["source_key"],
        )
    return ctx


# ── telling everyone on the case ─────────────────────────────────────────────


async def _op_notify_parties(params: dict, ctx: dict) -> dict:
    """
    Tell everyone on the case. A person is told once, however many roles they hold.
    params:
      case             the case ($case, or $inserted.cases for one just saved)
      message_template the message; {case_case_number}, {case_title}, {actor_name}, {recipient_name}
                       and any field are filled in. It may also be a $path to a field that holds
                       the message, so a building block can be given the wording by its caller.
      roles            who to tell (default requester, assignee, level2, helper, watcher)
      role_templates   a different message for some roles, e.g. {"assignee": "Case ... is now with you"};
                       a role whose message comes out empty gets the default one
      include_actor    also tell the person doing this (default no)
      buttons          {"Button text": "/command {case_case_number}"} shown under the message (Telegram)
      button_roles     who gets the buttons (default assignee, level2, helper)
      with_photos      also send the photos that came with the request
    """
    si = _si()
    case = si._resolve_path(ctx, params.get("case") or "$case")
    if not isinstance(case, dict) or not case.get("id"):
        raise si.StepError("notify.parties: there is no case to tell people about")
    if str(case.get("id")) == "(new)":
        _preview(ctx, "Everyone on the case will be told")
        return ctx
    roles = list(params.get("roles") or _ROLE_ORDER)
    rows = await fetch_all(
        "SELECT u.id, u.name, u.phone, p.party_role FROM case_parties p "
        "JOIN users u ON u.id = p.user_id "
        "WHERE p.case_id = $1 AND p.ended_at IS NULL AND p.party_role = ANY($2) "
        "AND u.is_active AND u.phone IS NOT NULL AND u.phone <> ''",
        case["id"],
        roles,
        source_key=ctx["source_key"],
    )
    people: dict[str, dict] = {}
    for r in rows:
        who = people.setdefault(
            str(r["id"]), {"name": r["name"], "phone": r["phone"], "roles": set()}
        )
        who["roles"].add(r["party_role"])

    actor_id = str(ctx["user"]["user_id"])
    if not params.get("include_actor"):
        people.pop(actor_id, None)
    if ctx.get("dry_run"):
        if people:
            _preview(ctx, "Everyone on the case will be told")
        return ctx

    values = {
        **ctx.get("fields", {}),
        **ctx.get("computed", {}),
        **ctx.get("generated", {}),
        **{f"case_{k}": v for k, v in case.items()},
        "actor_name": ctx["user"].get("user_name") or "",
    }
    for key in ("assignee", "route"):
        found = ctx.get(key)
        if isinstance(found, dict):
            values.setdefault(
                "assignee_name", found.get("name") or found.get("assignee_name") or ""
            )
    templates = {
        role: si._resolve_path(ctx, text)
        for role, text in (params.get("role_templates") or {}).items()
    }
    default_template = si._resolve_path(ctx, params.get("message_template"))
    button_roles = set(params.get("button_roles") or ["assignee", "level2", "helper"])
    buttons = [
        {"title": title, "command": command}
        for title, command in (params.get("buttons") or {}).items()
    ]
    photos = (
        _as_ids(ctx["fields"].get("_photos"))[:_MAX_PHOTOS]
        if params.get("with_photos")
        else []
    )

    from app.services import messaging

    told = []
    for who in people.values():
        template = next(
            (
                templates[r]
                for r in _ROLE_ORDER
                if r in who["roles"] and templates.get(r)
            ),
            default_template,
        )
        if not template:
            continue
        local = {**values, "recipient_name": who["name"]}
        text = _fill(template, local)
        try:
            if (
                buttons
                and who["phone"].startswith("tg:")
                and who["roles"] & button_roles
            ):
                await messaging.send_buttons(
                    who["phone"],
                    text,
                    [
                        {"id": _fill(b["command"], local)[:64], "title": b["title"]}
                        for b in buttons
                    ],
                )
            else:
                await messaging.send_text(who["phone"], text)
            for file_id in photos:
                await messaging.send_photo(who["phone"], file_id, "")
            told.append(who["name"])
        except (
            Exception
        ) as e:  # one person who cannot be reached must not stop the rest
            logger.warning(f"notify.parties: could not tell {who['name']}: {e}")
    ctx["notified"] = told
    return ctx


CASE_PRIMITIVES = {
    "case.categorize": _op_categorize,
    "case.route": _op_route,
    "case.authorize": _op_authorize,
    "case.add_parties": _op_add_parties,
    "case.attach_photos": _op_attach_photos,
    "notify.parties": _op_notify_parties,
}
