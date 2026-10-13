"""The WhatsApp form screen: edit the complaint form that opens inside WhatsApp, see it as it will look in the chat, save it,
and publish it to WhatsApp from here.

The description of the form lives in orgs.settings -> whatsapp_flows.complaint.form (see app/services/flow_form.py). The
Flow layout is made from it and sent to Meta; the Flow that people get is whichever one whatsapp_flows.complaint.flow_id
names. What the dropdown and urgency buttons offer is never typed here: it comes from the kinds of complaint and the
complaint flow's own urgency choices, so this screen only shows them in the preview."""

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.admin_panel.common import CtxDep, PanelRoute, dump, jb, log_event, tx
from app.db import fetch_one
from app.services import config_store, flow_admin, flow_form, flows
from app.services.messages import say

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


class FormBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    button: str
    photos_max: int
    fields: list[dict]


class AccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str


async def _settings(ctx) -> dict:
    row = await fetch_one(
        "SELECT settings FROM orgs WHERE id = $1", ctx.org_id, source_key=ctx.source_key
    )
    found = jb((row or {}).get("settings"), {})
    return found if isinstance(found, dict) else {}


def _complaint(settings: dict) -> dict:
    flows_cfg = settings.get("whatsapp_flows")
    mine = flows_cfg.get("complaint") if isinstance(flows_cfg, dict) else None
    return mine if isinstance(mine, dict) else {}


async def _choices(ctx, cfg: dict) -> dict:
    """What the form's dropdown and urgency buttons will offer, for the preview."""
    user = {"org_id": ctx.org_id, "source_key": ctx.source_key}
    try:
        schema = await flows._complaint_schema(
            user, str(cfg.get("workflow") or "file_a_complaint")
        )
        data = await flows.form_data(user, schema)
    except Exception:  # a client without the complaint flow: the preview shows examples
        data = {}
    return {
        "categories": [c["title"] for c in data.get("categories", [])]
        or ["Plumbing", "Electrical", "Lift"],
        "priorities": [p["title"] for p in data.get("priorities", [])]
        or ["Low", "Medium", "Urgent"],
    }


def _read(cfg: dict) -> dict:
    """The saved description, or the one that ships (also when what is saved no longer passes the checks)."""
    try:
        return flow_form.normalise(cfg.get("form"))
    except ValueError:
        return flow_form.normalise(None)


@router.get("/whatsapp-form")
async def get_form(ctx: CtxDep):
    settings = await _settings(ctx)
    cfg = _complaint(settings)
    form = _read(cfg)
    published = cfg.get("published_form")
    flow_id = str(cfg.get("flow_id") or "")
    account = await flow_admin.find_account(cfg.get("waba_id") or None)
    return {
        "form": form,
        "published": flow_form.normalise(published) if published else None,
        "limits": {
            "title": flow_form.TITLE_MAX,
            "button": flow_form.BUTTON_MAX,
            "help": flow_form.HELP_MAX,
            "label": flow_form.LABEL_MAX,
            "photos": flow_form.PHOTOS_MAX,
            "always": sorted(flow_form.ALWAYS),
        },
        "choices": await _choices(ctx, cfg),
        "flow_id": flow_id,
        "flow_status": await flow_admin.status_of(flow_id) if flow_id else None,
        "enabled": cfg.get("enabled") is True,
        "published_at": cfg.get("published_at"),
        "account_known": bool(account),
        "intro": await say(ctx.source_key, "flow.complaint_intro"),
        "button": await say(ctx.source_key, "flow.complaint_button"),
    }


async def _write(ctx, change, what: str, summary: str):
    """Change orgs.settings -> whatsapp_flows.complaint in one step. `change(complaint)` edits it in place."""
    async with tx(ctx) as conn:
        org = await conn.fetchrow(
            "SELECT settings FROM orgs WHERE id = $1 FOR UPDATE", ctx.org_id
        )
        if not org:
            raise HTTPException(404, "This organisation was not found.")
        old = jb(org["settings"], {})
        old = old if isinstance(old, dict) else {}
        new = dict(old)
        wf = dict(new.get("whatsapp_flows") or {})
        cfg = dict(wf.get("complaint") or {})
        change(cfg)
        wf["complaint"] = cfg
        new["whatsapp_flows"] = wf
        await conn.execute(
            "UPDATE orgs SET settings = $1::jsonb WHERE id = $2", dump(new), ctx.org_id
        )
        await log_event(
            ctx,
            "settings",
            what,
            summary,
            target_type="orgs",
            target_id=ctx.org_id,
            before=_complaint(old).get("form"),
            after=cfg.get("form"),
            conn=conn,
        )
    config_store.invalidate(ctx.source_key)


@router.put("/whatsapp-form")
async def save_form(ctx: CtxDep, body: FormBody):
    try:
        form = flow_form.normalise(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await _write(
        ctx,
        lambda cfg: cfg.__setitem__("form", form),
        "whatsapp_form",
        "Saved the WhatsApp complaint form (not published yet)",
    )
    return {"ok": True, "form": form}


@router.put("/whatsapp-form/account")
async def save_account(ctx: CtxDep, body: AccountBody):
    account = body.account_id.strip()
    if not account.isdigit():
        raise HTTPException(400, "The business account number is only digits.")
    await _write(
        ctx,
        lambda cfg: cfg.__setitem__("waba_id", account),
        "whatsapp_form",
        "Saved the WhatsApp business account number",
    )
    return {"ok": True}


@router.post("/whatsapp-form/publish")
async def publish_form(ctx: CtxDep, body: FormBody):
    """Save what is on screen, make it a new Flow in Meta, publish it, and start using it. If Meta refuses anything, the old
    form keeps working and the reasons come back."""
    try:
        form = flow_form.normalise(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    cfg = _complaint(await _settings(ctx))
    account = await flow_admin.find_account(cfg.get("waba_id") or None)
    if not account:
        raise HTTPException(
            400,
            "Meta needs the number of your WhatsApp business account. Paste it in the box on this screen once.",
        )
    old_id = str(cfg.get("flow_id") or "")
    try:
        new_id = await flow_admin.publish_new(
            account, "complaint_form", flow_form.build(form)
        )
    except flow_admin.MetaError as e:
        raise HTTPException(400, str(e)) from e

    def switch(c: dict):
        c.update(
            {
                "form": form,
                "published_form": form,
                "flow_id": new_id,
                "previous_flow_id": old_id or None,
                "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "mode": "published",
                "enabled": True,
            }
        )
        c.setdefault("workflow", "file_a_complaint")

    await _write(
        ctx,
        switch,
        "whatsapp_form",
        "Published the WhatsApp complaint form to WhatsApp",
    )
    if old_id and old_id != new_id:
        await flow_admin.retire(old_id)
    return {"ok": True, "flow_id": new_id}
