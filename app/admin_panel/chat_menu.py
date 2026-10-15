"""Chat bot > Menu: the chat menu organised by use case (Tickets, later Bookings, Visitors ...), edited here and shown by the chat
bot (app/services/chat_menu.py). Only a super admin changes it.

The tree is kept in orgs.settings -> chat_menu; nothing in this file names a use case, a group or a flow. What a person sees in
the chat is worked out by the same code the chat bot runs (chat_menu.resolve / view), so the preview here cannot say something
else. Making the layout for a WhatsApp Flow only produces JSON to copy: nothing is sent to Meta from here (publishing stays on the
WhatsApp Flows screen)."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.admin_panel.common import (
    Ctx,
    CtxDep,
    PanelRoute,
    dump,
    jb,
    log_event,
    rows,
    tx,
)
from app.db import fetch_all
from app.services import chat_menu, config_store, menu
from app.services.messages import say

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


class MenuBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict
    role_id: str | None = None


def _empty() -> dict:
    return {"enabled": False, "nodes": [], "show_unplaced": True}


async def _flows(ctx: Ctx) -> list[dict]:
    """The organisation's flows (not building blocks), as the editor offers them."""
    kind = (
        "AND COALESCE(kind, 'workflow') <> 'block'"
        if ctx.caps.get("workflow_kind")
        else ""
    )
    found = rows(
        await fetch_all(
            "SELECT intent_key, name, command_description, menu_section, is_active "
            f"FROM workflows WHERE org_id = $1 {kind} ORDER BY name",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    return [
        {
            "intent_key": w["intent_key"],
            "name": w["name"],
            "command_description": w["command_description"] or "",
            "menu_section": w["menu_section"] or "other",
            "is_active": bool(w["is_active"]),
        }
        for w in found
    ]


def _bad(e: ValueError) -> HTTPException:
    return HTTPException(400, str(e))


@router.get("/chat-menu")
async def read_menu(ctx: CtxDep):
    stored = config_store.setting(ctx.settings, "chat_menu", None)
    saved = stored if isinstance(stored, dict) else _empty()
    saved = {
        "enabled": saved.get("enabled") is True,
        "nodes": saved.get("nodes") if isinstance(saved.get("nodes"), list) else [],
        "show_unplaced": saved.get("show_unplaced") is not False,
        **{k: saved[k] for k in chat_menu.WORD_MAX if saved.get(k)},
    }
    roles = rows(
        await fetch_all(
            "SELECT id, name FROM roles WHERE org_id = $1 ORDER BY name",
            ctx.org_id,
            source_key=ctx.source_key,
        )
    )
    return {
        "configured": isinstance(stored, dict),
        "config": saved,
        "flows": await _flows(ctx),
        "roles": [{"id": str(r["id"]), "name": r["name"]} for r in roles],
        "words": chat_menu.DEFAULT_WORDS,
        "word_max": chat_menu.WORD_MAX,
        "limits": {
            "use_cases": chat_menu.MAX_USE_CASES,
            "entries": chat_menu.MAX_CHILDREN,
            "label": chat_menu.LABEL_MAX,
            "description": chat_menu.ROW_DESCRIPTION,
            "rows_per_message": chat_menu.PAGE_ROWS,
        },
    }


@router.put("/chat-menu")
async def save_menu(ctx: CtxDep, body: MenuBody):
    ctx.need_super("change the chat menu")
    known = {w["intent_key"] for w in await _flows(ctx)}
    try:
        new_cfg = chat_menu.clean(body.config, known)
    except ValueError as e:
        raise _bad(e) from e
    async with tx(ctx) as conn:
        org = await conn.fetchrow(
            "SELECT settings FROM orgs WHERE id = $1 FOR UPDATE", ctx.org_id
        )
        if not org:
            raise HTTPException(404, "This organisation was not found.")
        old = jb(org["settings"], {})
        old = old if isinstance(old, dict) else {}
        new = dict(old)
        new["chat_menu"] = new_cfg
        await conn.execute(
            "UPDATE orgs SET settings = $1::jsonb WHERE id = $2", dump(new), ctx.org_id
        )
        await log_event(
            ctx,
            "settings",
            "chat_menu",
            "Changed the chat menu"
            + (" (switched on)" if new_cfg["enabled"] else " (switched off)"),
            target_type="orgs",
            target_id=ctx.org_id,
            before=old.get("chat_menu"),
            after=new_cfg,
            conn=conn,
        )
    config_store.invalidate(ctx.source_key)
    return {"ok": True, "config": new_cfg}


@router.post("/chat-menu/suggest")
async def suggest_menu(ctx: CtxDep):
    """A starting tree made from today's menu: one use case per section the flows are filed under. Nothing is saved."""
    flows = [w for w in await _flows(ctx) if w["is_active"]]
    order = menu.SECTION_ORDER + sorted(
        {w["menu_section"] for w in flows} - set(menu.SECTION_ORDER)
    )
    nodes = []
    for section in order:
        mine = [w for w in flows if w["menu_section"] == section]
        if not mine:
            continue
        label = menu.SECTION_LABELS.get(section, section.title())
        label = (
            label.lstrip("".join(c for c in label if not c.isalnum())).strip() or label
        )
        nodes.append(
            {
                "id": "".join(c for c in section.lower() if c.isalnum() or c == "_")[
                    :20
                ]
                or "other",
                "label": label[: chat_menu.LABEL_MAX],
                "children": [{"flow": w["intent_key"]} for w in mine][
                    : chat_menu.MAX_CHILDREN
                ],
            }
        )
    try:
        cfg = chat_menu.clean(
            {"enabled": False, "nodes": nodes[: chat_menu.MAX_USE_CASES]}
        )
    except ValueError as e:
        raise _bad(e) from e
    return {"config": cfg}


@router.post("/chat-menu/preview")
async def preview_menu(ctx: CtxDep, body: PreviewBody):
    """What a person would see in the chat for this (unsaved) menu: every list message with its rows, and the layout of the
    WhatsApp Flow. `role_id` shows it as someone with that role; without it, as someone allowed to use every active flow."""
    ctx.need_super("see the chat menu")
    flows = await _flows(ctx)
    try:
        cfg = chat_menu.clean(
            {**body.config, "enabled": bool(body.config.get("nodes"))}
        )
    except ValueError as e:
        raise _bad(e) from e
    active = [
        {
            "intent_key": w["intent_key"],
            "name": w["name"],
            "command_description": w["command_description"],
            "menu_section": w["menu_section"],
        }
        for w in flows
        if w["is_active"]
    ]
    allowed = active
    if body.role_id:
        role = rows(
            await fetch_all(
                "SELECT permissions FROM roles WHERE org_id = $1 AND id::text = $2",
                ctx.org_id,
                body.role_id,
                source_key=ctx.source_key,
            )
        )
        if not role:
            raise HTTPException(404, "That role was not found.")
        perms = set(role[0]["permissions"] or [])
        allowed = [w for w in active if w["intent_key"] in perms]
    tree = chat_menu.resolve(cfg, allowed)
    intro = await say(ctx.source_key, "menu.intro")
    screens: list[dict] = []

    def walk(node_id: str, path: str):
        first = chat_menu.view(tree, cfg, node_id, 1)
        if not first:
            return
        pages = [first]
        for p in range(2, first["pages"] + 1):
            pages.append(chat_menu.view(tree, cfg, node_id, p))
        screens.append(
            {
                "id": first["node"],
                "path": path,
                "pages": [
                    {
                        "page": v["page"],
                        "body": v["description"] or v["title"] or intro,
                        "button": v["button"],
                        "rows": v["rows"],
                    }
                    for v in pages
                ],
            }
        )

    def groups(nodes: list[dict], trail: str):
        for n in nodes:
            if n["kind"] == "group":
                here = f"{trail} › {n['title']}" if trail else n["title"]
                walk(n["id"], here)
                groups(n["children"], here)

    walk(chat_menu.TOP, "Menu")
    top_id = screens[0]["id"] if screens else ""
    groups(tree, "")
    # a lone use case is the top itself: do not list it twice
    screens = [s for i, s in enumerate(screens) if i == 0 or s["id"] != top_id]
    layout = chat_menu.flow_layout(cfg, active)
    text = json.dumps(layout, indent=2, ensure_ascii=False)
    first_screen, data = chat_menu.flow_data_for(tree)
    return {
        "screens": screens,
        "empty": not tree,
        "flow_json": text,
        "panel": {
            "first_screen": first_screen,
            "bytes": len(json.dumps(data, ensure_ascii=False)),
            "max_bytes": chat_menu.FLOW_DATA_MAX_BYTES,
            "fits": bool(first_screen),
        },
    }
