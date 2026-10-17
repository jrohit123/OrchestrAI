"""WhatsApp forms for any workflow (the complaint form keeps its own code in flows.py).

Which form belongs to which workflow, and what fills its lists, is setting data (orgs.settings -> whatsapp_flows ->
forms), never code:

    "forms": {
      "send_announcement": {"enabled": true, "flow_id": "2023…", "screen": "ANNOUNCEMENT",
                            "data": {"audiences": "ready_choices"}},
      "preapprove_visitor": {"enabled": true, "flow_id": "2192…", "screen": "VISITOR",
                             "data": {"times": "times", "today": "today"},
                             "join": {"visit_time": ["visit_date", "visit_hour"]}}
    },
    "time_slots": ["07:00", "08:00", …]

"button" is the wording on the button that opens it (20 characters at most), else the workflow's name.
A bare tap or command for such a workflow sends its form instead of the chat questions, but only to someone allowed
to use the workflow. The form's answer names its workflow and carries the workflow's own field names, so it goes into
the workflow's draft and the usual summary ("Here's what I'll do… yes") is shown, the same as a typed request.

What fills a list (the value of a "data" entry):
    ready_choices         the ready choices of the Announcements screen (announcement_audiences)
    choices:<field>       the choices the workflow itself allows for that field
    times                 whatsapp_flows.time_slots (shown as 6:00 pm, sent as 18:00)
    today                 today's date, for a date picker that may not go back
    open_tickets          the open tickets, newest first
    my_tickets            the open tickets the person is on (all open ones for someone who may see every ticket)
    people:<workflow>     the active people whose role may use that workflow (for example who can work on tickets)
"""

import datetime as dt
import json
import re
import uuid
from zoneinfo import ZoneInfo

from app.db import fetch_all, fetch_one
from app.logging_config import get_context_logger
from app.services import config_store, whatsapp

logger = get_context_logger(__name__)

TITLE_MAX = 30  # what a list item of a form can show
LIST_MAX = 100
CTA_MAX = 20
TOKEN_PREFIX = "form:"
DEFAULT_SLOTS = [f"{h:02d}:00" for h in range(7, 22)]
SEE_ALL = "view_all_cases"  # the permission that lets someone see every ticket (it is a workflow of their role)


def _cut(text, size: int = TITLE_MAX) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


def forms_of(settings: dict | None) -> dict:
    found = config_store.setting(settings, "whatsapp_flows.forms", None)
    return found if isinstance(found, dict) else {}


def form_for(settings: dict | None, intent_key: str) -> dict | None:
    cfg = forms_of(settings).get(intent_key)
    if not isinstance(cfg, dict) or cfg.get("enabled") is False:
        return None
    if (
        not str(cfg.get("flow_id") or "").strip()
        or not str(cfg.get("screen") or "").strip()
    ):
        return None
    return cfg


def may_use(user: dict, intent_key: str) -> bool:
    return intent_key in (user.get("permissions") or [])


async def _workflow(user: dict, intent_key: str) -> dict | None:
    row = await fetch_one(
        "SELECT * FROM workflows WHERE org_id = $1 AND intent_key = $2 AND is_active",
        user["org_id"],
        intent_key,
        source_key=user["source_key"],
    )
    return dict(row) if row else None


def _schema(wf: dict) -> dict:
    s = wf.get("entity_schema")
    if isinstance(s, str):
        try:
            s = json.loads(s)
        except ValueError:
            s = {}
    return s if isinstance(s, dict) else {}


def _time_title(hhmm: str) -> str:
    try:
        t = dt.datetime.strptime(hhmm, "%H:%M")
    except ValueError:
        return hhmm
    return t.strftime("%I:%M %p").lstrip("0").lower()


async def _tickets(user: dict, mine: bool) -> list[dict]:
    closed = ["closed"]
    settings = await config_store.org_settings(user["source_key"], user["org_id"])
    closed = (settings.get("case_reminders") or {}).get("closed_values") or closed
    everyone = not mine or SEE_ALL in (user.get("permissions") or [])
    rows = await fetch_all(
        "SELECT c.case_number, c.title FROM cases c WHERE c.org_id = $1 AND NOT (c.status = ANY($2::text[])) "
        "AND ($3 OR c.assigned_to_id = $4 OR EXISTS (SELECT 1 FROM case_parties p WHERE p.case_id = c.id "
        "AND p.user_id = $4 AND p.ended_at IS NULL)) ORDER BY c.created_at DESC LIMIT $5",
        user["org_id"],
        list(closed),
        everyone,
        user["user_id"],
        LIST_MAX,
        source_key=user["source_key"],
    )
    return [
        {
            "id": r["case_number"],
            "title": _cut(f"{r['case_number']} · {r['title'] or ''}"),
        }
        for r in rows
    ]


async def _source(user: dict, wf: dict, settings: dict, spec: str):
    spec = str(spec or "")
    if spec == "today":
        tz = ZoneInfo(config_store.DEFAULT_TIMEZONE)
        return dt.datetime.now(tz).date().isoformat()
    if spec == "times":
        slots = config_store.setting(settings, "whatsapp_flows.time_slots", None)
        slots = slots if isinstance(slots, list) and slots else DEFAULT_SLOTS
        return [{"id": str(s), "title": _time_title(str(s))} for s in slots[:LIST_MAX]]
    if spec == "ready_choices":
        rows = await fetch_all(
            "SELECT name FROM announcement_audiences WHERE org_id = $1 ORDER BY sort_order, name",
            user["org_id"],
            source_key=user["source_key"],
        )
        return [{"id": r["name"], "title": _cut(r["name"])} for r in rows]
    if spec.startswith("choices:"):
        field = spec.split(":", 1)[1]
        return [
            {"id": str(v), "title": _cut(v)}
            for v in (_schema(wf).get(field) or {}).get("enum") or []
        ]
    if spec in ("open_tickets", "my_tickets"):
        return await _tickets(user, spec == "my_tickets")
    if spec.startswith("people:"):
        key = spec.split(":", 1)[1]
        rows = await fetch_all(
            "SELECT DISTINCT u.name FROM users u JOIN roles r ON r.id = u.role_id WHERE u.org_id = $1 AND u.is_active "
            "AND $2 = ANY(r.permissions) ORDER BY u.name LIMIT $3",
            user["org_id"],
            key,
            LIST_MAX,
            source_key=user["source_key"],
        )
        return [{"id": r["name"], "title": _cut(r["name"])} for r in rows]
    raise ValueError(f"unknown list source '{spec}'")


async def start(user: dict, phone: str, text: str, command_args) -> bool:
    """A bare tap or command for a workflow that has a form: send the form. True when sent; False carries on with the
    chat questions (no form, not allowed, a list came out empty, or the send failed)."""
    if not phone or phone.startswith("tg:") or command_args:
        return False
    intent_key = text.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,80}", intent_key):
        return False
    settings = await config_store.org_settings(user["source_key"], user["org_id"])
    cfg = form_for(settings, intent_key)
    if not cfg or not may_use(user, intent_key):
        return False
    wf = await _workflow(user, intent_key)
    if not wf:
        return False
    data = {}
    try:
        for name, spec in (cfg.get("data") or {}).items():
            data[name] = await _source(user, wf, settings, spec)
            if isinstance(data[name], list) and not data[name]:
                logger.info(
                    f"forms: '{name}' of {intent_key} is empty, so the questions are asked instead"
                )
                return False
    except Exception as e:
        logger.warning(
            f"forms: the lists of {intent_key} could not be filled ({type(e).__name__}): {e}"
        )
        return False
    try:
        await whatsapp.send_flow(
            phone,
            body=wf.get("description") or wf.get("name") or intent_key,
            flow_id=str(cfg["flow_id"]),
            cta=_cut(cfg.get("button") or wf.get("name") or intent_key, CTA_MAX),
            screen=str(cfg["screen"]),
            data=data,
            flow_token=f"{TOKEN_PREFIX}{intent_key}:{uuid.uuid4().hex[:10]}",
            draft=cfg.get("mode") == "draft",
        )
        return True
    except Exception as e:
        logger.warning(
            f"forms: the form of {intent_key} could not be sent ({type(e).__name__}): {e}"
        )
        return False


def is_form_answer(data: dict) -> bool:
    """A filled form (not a tap on the menu panel, which only names a workflow)."""
    if str(data.get("flow_token") or "").startswith(TOKEN_PREFIX):
        return True
    return bool(data.get("workflow")) and bool(set(data) - {"workflow", "flow_token"})


async def fields_of(user: dict, data: dict) -> tuple[str, dict, str, dict | None]:
    """(workflow key, fields, the answers as labelled lines, the workflow) of a filled form. The workflow is the one
    the form names, if it has a form in the settings; fields are the workflow's own, and "join" puts two answers
    into one field (a date and a time into a visit time)."""
    intent_key = str(data.get("workflow") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,80}", intent_key):
        return "", {}, "", None
    settings = await config_store.org_settings(user["source_key"], user["org_id"])
    cfg = form_for(settings, intent_key)
    wf = await _workflow(user, intent_key) if cfg else None
    if not wf:
        return intent_key, {}, "", None
    answers = {
        k: str(v).strip()
        for k, v in data.items()
        if isinstance(v, str | int | float) and str(v).strip()
    }
    for field, parts in (cfg.get("join") or {}).items():
        joined = " ".join(answers.get(p, "") for p in parts).strip()
        if joined:
            answers[field] = joined
    schema = _schema(wf)
    fields = {k: answers[k] for k in schema if k in answers}
    lines = [
        f"{(schema.get(k) or {}).get('label') or k.replace('_', ' ').capitalize()}: {v}"
        for k, v in fields.items()
    ]
    return intent_key, fields, "\n".join(lines), wf
