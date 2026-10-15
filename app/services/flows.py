"""WhatsApp Flows: the menu and the complaint form shown as a panel inside WhatsApp.

A Flow is only a layout kept in Meta. What it shows is sent with each message, from the database: the sections and
workflows a person's role may use, the kinds of complaint, the urgency choices. So adding or removing a workflow, a
kind or an urgency on the dashboard changes what people see, and nothing is typed into Meta. Which Flow to use is
setting data (orgs.settings -> whatsapp_flows), not code:

    {"menu":      {"enabled": true, "flow_id": "123", "mode": "published"},
     "complaint": {"enabled": true, "flow_id": "456", "workflow": "file_a_complaint"}}

With no setting, a switch that is off, or any problem sending, the person gets today's list menu and the chat
questions, so nobody is left without a menu. The answer of a Flow comes back as an ordinary message
(see read_answer): a chosen workflow is handled like a tap on a menu row, a filled form like a complaint typed in
one message, with its photos."""

import json
import re
import uuid

from app.db import fetch_all, fetch_one
from app.logging_config import get_context_logger
from app.services import config_store, menu, photos, whatsapp

logger = get_context_logger(__name__)

MAX_ITEMS = 20  # what a Flow list shows
TITLE_MAX, DESCRIPTION_MAX = 30, 20  # what a Flow list item can hold
CTA_MAX = 20
# which answer of the form fills which field of the complaint workflow
FORM_FIELDS = {"problem": "title", "location": "location", "priority": "priority"}
EXTRA_LABELS = {"category": "Category"}
NO_CATEGORY = "none"


def is_whatsapp(phone: str) -> bool:
    return bool(phone) and not phone.startswith("tg:")


def flow_of(settings: dict | None, kind: str) -> dict | None:
    """The chosen Flow for 'menu' or 'complaint': settings.whatsapp_flows.<kind>. None unless it is switched on and has
    a Flow id."""
    chosen = config_store.setting(settings, f"whatsapp_flows.{kind}", None)
    if not isinstance(chosen, dict) or chosen.get("enabled") is not True:
        return None
    flow_id = str(chosen.get("flow_id") or "").strip()
    return {**chosen, "flow_id": flow_id} if flow_id else None


def _allowed(cfg: dict, phone: str) -> bool:
    """While a Flow is being tried, "only_phones" limits it to those numbers; everyone else keeps the old menu and questions.
    Empty or missing means everyone."""
    only = cfg.get("only_phones")
    return not (isinstance(only, list) and only) or phone in {str(p) for p in only}


def _cut(text, size: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


def _plural(n: int) -> str:
    return f"{n} option" + ("" if n == 1 else "s")


def _words(label: str) -> str:
    """The label of a menu section without its picture (the list menu has one, the panel does not need it)."""
    return re.sub(r"^[^\w]+", "", label or "").strip() or label


def _item(workflow: dict) -> dict:
    return {
        "id": workflow["intent_key"],
        "main-content": {
            "title": _cut(workflow["name"], TITLE_MAX),
            "description": _cut(workflow.get("command_description"), DESCRIPTION_MAX),
        },
        "on-click-action": {
            "name": "navigate",
            "next": {"type": "screen", "name": "DONE"},
            "payload": {"workflow": workflow["intent_key"]},
        },
    }


async def menu_data(
    user: dict, settings: dict | None = None
) -> tuple[str, dict] | None:
    """(first screen, its data) for the person's menu: the groups (use cases first) of switched-on flows they may use,
    the same as the list menu (menu.menu_groups). The look of the panel is the organisation's own Flow JSON; this only
    fills it. None when there is nothing."""
    groups = await menu.menu_groups(user["org_id"], user)
    if not groups:
        return None
    if len(groups) == 1:  # one group: no need to ask which, show its flows
        return "SECTION", {"items": [_item(w) for w in groups[0]["flows"][:MAX_ITEMS]]}
    items = []
    for g in groups[:MAX_ITEMS]:
        flows = g["flows"][:MAX_ITEMS]
        items.append(
            {
                "id": g["key"],
                "main-content": {
                    "title": _cut(_words(g["title"]), TITLE_MAX),
                    "description": _plural(len(flows)),
                },
                "on-click-action": {
                    "name": "navigate",
                    "next": {"type": "screen", "name": "SECTION"},
                    "payload": {"items": [_item(w) for w in flows]},
                },
            }
        )
    return "MENU", {"items": items}


async def _send(
    phone: str, cfg: dict, kind: str, body: str, cta: str, screen: str, data: dict
) -> bool:
    try:
        await whatsapp.send_flow(
            phone,
            body=body,
            flow_id=cfg["flow_id"],
            cta=_cut(cta, CTA_MAX),
            screen=screen,
            data=data,
            flow_token=f"{kind}:{uuid.uuid4().hex[:12]}",
            draft=cfg.get("mode") == "draft",
        )
        return True
    except Exception as e:  # the old menu is the fallback
        logger.warning(
            f"flows: the {kind} panel could not be sent ({type(e).__name__}): {e}"
        )
        return False


async def send_menu(user: dict, phone: str, body: str, say) -> bool:
    """The menu as a panel. False (and nothing sent) when it is not set up or fails: the caller sends the list menu."""
    if not is_whatsapp(phone):
        return False
    settings = await config_store.org_settings(user["source_key"], user["org_id"])
    cfg = flow_of(settings, "menu")
    if not cfg or not _allowed(cfg, phone):
        return False
    found = await menu_data(user, settings)
    if not found:
        return False
    screen, data = found
    cta = await say(user["source_key"], "flow.menu_button")
    return await _send(phone, cfg, "menu", body, cta, screen, data)


async def _complaint_schema(user: dict, intent_key: str) -> dict:
    row = await fetch_one(
        "SELECT entity_schema FROM workflows WHERE org_id = $1 AND intent_key = $2 AND is_active",
        user["org_id"],
        intent_key,
        source_key=user["source_key"],
    )
    schema = (row or {}).get("entity_schema")
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except ValueError:
            schema = {}
    return schema if isinstance(schema, dict) else {}


async def form_data(user: dict, schema: dict) -> dict:
    """What the form offers: the urgency choices the workflow knows, and the areas of complaint (optional)."""
    priorities = [
        {"id": str(v), "title": _cut(str(v).title(), TITLE_MAX)}
        for v in (schema.get("priority") or {}).get("enum") or []
    ]
    categories = []
    try:
        for c in await fetch_all(
            "SELECT key, label FROM case_categories WHERE org_id = $1 AND is_active AND parent_id IS NULL "
            "ORDER BY sort_order, label",
            user["org_id"],
            source_key=user["source_key"],
        ):
            categories.append({"id": c["key"], "title": _cut(c["label"], TITLE_MAX)})
    except Exception as e:  # a client without the case model has no kinds
        logger.debug(f"flows: no kinds of complaint to offer: {e}")
    return {
        "categories": categories or [{"id": NO_CATEGORY, "title": "Not sure"}],
        "priorities": priorities,
    }


async def start_form(user: dict, phone: str, text: str, command_args, say) -> bool:
    """A bare tap or command for the complaint workflow starts the form instead of the questions. True when the form
    was sent (the caller stops there); False to carry on with the chat questions."""
    if not is_whatsapp(phone) or command_args:
        return False
    settings = await config_store.org_settings(user["source_key"], user["org_id"])
    cfg = flow_of(settings, "complaint")
    if not cfg or not _allowed(cfg, phone):
        return False
    intent_key = str(cfg.get("workflow") or "file_a_complaint")
    if text.strip() != intent_key:
        return False
    schema = await _complaint_schema(user, intent_key)
    data = await form_data(user, schema)
    if not data["priorities"]:
        return False
    body = await say(user["source_key"], "flow.complaint_intro")
    cta = await say(user["source_key"], "flow.complaint_button")
    return await _send(phone, cfg, "complaint", body, cta, "COMPLAINT", data)


def _media_ids(photos_answer) -> list[str]:
    """The ids of the photos in a form's answer (Meta gives a list; each has an id)."""
    found = []
    for p in photos_answer if isinstance(photos_answer, list) else [photos_answer]:
        pid = (p.get("id") or p.get("media_id")) if isinstance(p, dict) else p
        if isinstance(pid, str | int) and str(pid).strip():
            found.append(str(pid).strip())
    return found


async def _form_details(user: dict, data: dict, schema: dict) -> str:
    """The filled form as plain labelled lines (Problem: ..., Where: ...), the way a person would type it."""
    lines = []
    for answer_key, field in FORM_FIELDS.items():
        value = str(data.get(answer_key) or "").strip()
        if value:
            lines.append(
                f"{(schema.get(field) or {}).get('label') or field.title()}: {value}"
            )
    category = await _category_label(user, data)
    if category:
        lines.append(f"{EXTRA_LABELS['category']}: {category}")
    return chr(10).join(lines)


async def _category_label(user: dict, data: dict) -> str:
    key = str(data.get("category") or "").strip()
    if not key or key == NO_CATEGORY:
        return ""
    row = await fetch_one(
        "SELECT label FROM case_categories WHERE org_id = $1 AND key = $2",
        user["org_id"],
        key,
        source_key=user["source_key"],
    )
    return (row or {}).get("label") or key


async def use_form(
    user: dict, phone: str, form: dict, session: dict, session_id: str, ttl: int
):
    """A filled form: its answers go straight into the complaint workflow's draft and the usual summary ("Here's what
    I'll save... yes") is shown, with no language model reading anything. Returns (done, details): done is True when the
    summary was sent; otherwise details is what the chat bot should be told instead, as if typed after the command."""
    from app.redis_client import set_session
    from app.services import agent
    from app.services.draft_store import close_draft
    from app.services.messaging import send_text

    data = form.get("data") or {}
    settings = await config_store.org_settings(user["source_key"], user["org_id"])
    intent_key = str(
        (flow_of(settings, "complaint") or {}).get("workflow") or "file_a_complaint"
    )
    wf = await fetch_one(
        "SELECT * FROM workflows WHERE org_id = $1 AND intent_key = $2 AND is_active",
        user["org_id"],
        intent_key,
        source_key=user["source_key"],
    )
    schema = (
        (await _complaint_schema(user, intent_key))
        if not wf
        else agent._parse_jsonb(wf.get("entity_schema"), {}) or {}
    )
    details = await _form_details(user, data, schema)
    if not wf:
        return False, details
    fields = {
        field: str(data.get(answer_key) or "").strip()
        for answer_key, field in FORM_FIELDS.items()
        if str(data.get(answer_key) or "").strip()
    }
    allowed = (schema.get("priority") or {}).get("enum")
    if allowed and fields.get("priority") not in allowed:
        fields.pop("priority", None)
    category = await _category_label(user, data)
    if category and "description" in schema:
        fields["description"] = f"{EXTRA_LABELS['category']}: {category}"
    if not fields.get("title") or not fields.get("location"):
        return False, details
    await close_draft(
        user["org_id"], user["user_id"], "cancelled", source_key=user["source_key"]
    )
    try:
        result = await agent._confirm_by_code(
            dict(user),
            dict(wf),
            fields,
            {},
            message=details,
            history=session.get("conversation_history"),
            limit=user.get("context_message_limit") or 12,
        )
    except Exception as e:  # the chat bot reads it instead
        logger.warning(
            f"flows: the form could not be confirmed by code ({type(e).__name__}): {e}"
        )
        return False, details
    if not result:
        return False, details
    reply, history, patch = result
    patch.pop("_buttons", None)
    session.update(patch)
    session["conversation_history"] = history
    session["last_message"] = details
    await set_session(session_id, session, ttl=ttl)
    await send_text(phone, reply)
    return True, None


async def _form_answer(phone: str, data: dict) -> tuple[str, list[str], dict | None]:
    from app.services.identity import resolve_identity

    user = await resolve_identity(phone)
    if not user or not any(str(data.get(k) or "").strip() for k in FORM_FIELDS):
        return "", [], None
    settings = await config_store.org_settings(user["source_key"], user["org_id"])
    intent_key = str(
        (flow_of(settings, "complaint") or {}).get("workflow") or "file_a_complaint"
    )
    limit = config_store.limit_of(settings, "photo_max")
    refs = [f"{photos.WHATSAPP}{i}" for i in _media_ids(data.get("photos"))][:limit]
    return intent_key, refs, {"data": data}


async def read_answer(phone: str, inter: dict) -> tuple[str, list[str], dict | None]:
    """What a person's finished Flow means: (text, photo references, form). ("", [], None) leaves the answer alone.
    A chosen workflow is its key, handled like a tap on a menu row. A filled form is the complaint workflow's key with
    the form's answers (see use_form) and its photos."""
    try:
        data = json.loads((inter.get("nfm_reply") or {}).get("response_json") or "{}")
    except (TypeError, ValueError):
        return "", [], None
    if not isinstance(data, dict):
        return "", [], None
    logger.info(f"WhatsApp Flow answer with: {sorted(data)}")
    if data.get("photos"):  # only the shape of what came back, never its content
        first = (
            data["photos"][0]
            if isinstance(data["photos"], list) and data["photos"]
            else data["photos"]
        )
        shape = sorted(first) if isinstance(first, dict) else type(first).__name__
        logger.info(
            f"WhatsApp Flow answer photos: {len(_media_ids(data['photos']))} of shape {shape}"
        )
    choice = str(data.get("workflow") or "").strip()
    if choice:
        return (
            (choice, [], None)
            if re.fullmatch(r"[A-Za-z0-9_]{1,80}", choice)
            else ("", [], None)
        )
    if "problem" in data or "location" in data:
        return await _form_answer(phone, data)
    return "", [], None
