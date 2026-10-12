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


async def menu_data(user: dict) -> tuple[str, dict] | None:
    """(first screen, its data) for the person's menu, from what their role may use. None when there is nothing."""
    allowed = await menu.get_menu_workflows(user["org_id"], user)
    grouped: dict[str, list] = {}
    for w in allowed:
        grouped.setdefault(w["menu_section"] or "other", []).append(w)
    keys = [k for k in menu.SECTION_ORDER if k in grouped] + sorted(
        k for k in grouped if k not in menu.SECTION_ORDER
    )
    if not keys:
        return None
    if len(keys) == 1:  # one section: no need to ask which, show its workflows
        return "SECTION", {"items": [_item(w) for w in grouped[keys[0]][:MAX_ITEMS]]}
    items = []
    for k in keys[:MAX_ITEMS]:
        flows = grouped[k][:MAX_ITEMS]
        items.append(
            {
                "id": k,
                "main-content": {
                    "title": _cut(
                        _words(menu.SECTION_LABELS.get(k, k.title())), TITLE_MAX
                    ),
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
    if not cfg:
        return False
    found = await menu_data(user)
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
    if not cfg:
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


async def _form_message(phone: str, data: dict) -> tuple[str, list[str]]:
    """The filled form as one message for the chat bot, like a person typing it all at once, plus its photos."""
    from app.services.identity import resolve_identity

    user = await resolve_identity(phone)
    if not user:
        return "", []
    settings = await config_store.org_settings(user["source_key"], user["org_id"])
    cfg = flow_of(settings, "complaint") or {}
    intent_key = str(cfg.get("workflow") or "file_a_complaint")
    schema = await _complaint_schema(user, intent_key)
    lines = []
    for answer_key, field in FORM_FIELDS.items():
        value = str(data.get(answer_key) or "").strip()
        if value:
            lines.append(
                f"{(schema.get(field) or {}).get('label') or field.title()}: {value}"
            )
    category = str(data.get("category") or "").strip()
    if category and category != NO_CATEGORY:
        row = await fetch_one(
            "SELECT label FROM case_categories WHERE org_id = $1 AND key = $2",
            user["org_id"],
            category,
            source_key=user["source_key"],
        )
        lines.append(
            f"{EXTRA_LABELS['category']}: {(row or {}).get('label') or category}"
        )
    if not lines:
        return "", []
    details = "\n".join(lines)
    command = next(
        (
            w.get("slash_command")
            for w in await menu.get_menu_workflows(user["org_id"], user)
            if w["intent_key"] == intent_key
        ),
        None,
    )
    limit = config_store.limit_of(settings, "photo_max")
    refs = [f"{photos.WHATSAPP}{i}" for i in _media_ids(data.get("photos"))][:limit]
    return (f"/{command} {details}" if command else details), refs


async def read_answer(phone: str, inter: dict) -> tuple[str, list[str]]:
    """What a person's finished Flow means as a message: (text, photo references). ("", []) leaves the answer alone.
    A chosen workflow is its key, handled like a tap on a menu row. A filled form is its details in one message."""
    try:
        data = json.loads((inter.get("nfm_reply") or {}).get("response_json") or "{}")
    except (TypeError, ValueError):
        return "", []
    if not isinstance(data, dict):
        return "", []
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
        return (choice, []) if re.fullmatch(r"[A-Za-z0-9_]{1,80}", choice) else ("", [])
    if "problem" in data or "location" in data:
        return await _form_message(phone, data)
    return "", []
