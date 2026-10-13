"""The WhatsApp Flows screen: list the Flows of the business account, write or paste a Flow's JSON, save it as a draft, send a
test to a phone, publish it, and say which Flow the chat bot uses for its menu and its complaint form.

The layouts live in Meta (see app/services/flow_admin.py); the only thing kept in the organisation's settings is which Flow id
the chat bot uses for what: orgs.settings -> whatsapp_flows.menu / .complaint -> flow_id. Nothing here knows what a Flow says."""

import json
import re
import uuid

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.admin_panel.common import CtxDep, PanelRoute, dump, jb, log_event, tx
from app.db import fetch_one
from app.services import config_store, flow_admin, whatsapp

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)
KINDS = ("menu", "complaint")


class NewFlow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    start: str = "sample"  # sample | blank


class JsonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    json_text: str


class SendTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str
    message: str = "Testing a WhatsApp Flow"
    button: str = "Open"
    screen: str
    data: dict | None = None


class UseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    flow_id: str


class AccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str


def _id(value: str) -> str:
    if not re.fullmatch(r"\d{5,25}", value or ""):
        raise HTTPException(400, "That is not a Flow number.")
    return value


async def _settings(ctx) -> dict:
    row = await fetch_one(
        "SELECT settings FROM orgs WHERE id = $1", ctx.org_id, source_key=ctx.source_key
    )
    found = jb((row or {}).get("settings"), {})
    return found if isinstance(found, dict) else {}


def _cfg(settings: dict, kind: str) -> dict:
    flows_cfg = settings.get("whatsapp_flows")
    mine = flows_cfg.get(kind) if isinstance(flows_cfg, dict) else None
    return mine if isinstance(mine, dict) else {}


async def _account(ctx) -> str | None:
    settings = await _settings(ctx)
    configured = (
        settings.get("whatsapp_flows", {}).get("waba_id")
        if isinstance(settings.get("whatsapp_flows"), dict)
        else None
    )
    return await flow_admin.find_account(configured)


async def _need_account(ctx) -> str:
    account = await _account(ctx)
    if not account:
        raise HTTPException(
            400,
            "Meta needs the number of your WhatsApp business account. Paste it in the box on the Flows list once.",
        )
    return account


async def _write(ctx, change, summary: str):
    """Change orgs.settings -> whatsapp_flows in one step. `change(whatsapp_flows)` edits it in place."""
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
        change(wf)
        new["whatsapp_flows"] = wf
        await conn.execute(
            "UPDATE orgs SET settings = $1::jsonb WHERE id = $2", dump(new), ctx.org_id
        )
        await log_event(
            ctx,
            "settings",
            "whatsapp_flows",
            summary,
            target_type="orgs",
            target_id=ctx.org_id,
            before=old.get("whatsapp_flows"),
            after=wf,
            conn=conn,
        )
    config_store.invalidate(ctx.source_key)


async def _run(coro):
    try:
        return await coro
    except flow_admin.MetaError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/whatsapp-flows")
async def list_flows(ctx: CtxDep):
    settings = await _settings(ctx)
    account = await _account(ctx)
    used = {k: str(_cfg(settings, k).get("flow_id") or "") for k in KINDS}
    flows = await _run(flow_admin.list_flows(account)) if account else []
    return {"account_known": bool(account), "flows": flows, "used": used}


@router.put("/whatsapp-flows/account")
async def save_account(ctx: CtxDep, body: AccountBody):
    account = body.account_id.strip()
    if not account.isdigit():
        raise HTTPException(400, "The business account number is only digits.")
    await _write(
        ctx,
        lambda wf: wf.__setitem__("waba_id", account),
        "Saved the WhatsApp business account number",
    )
    return {"ok": True}


@router.put("/whatsapp-flows/use")
async def use_flow(ctx: CtxDep, body: UseBody):
    if body.kind not in KINDS:
        raise HTTPException(400, "Unknown use.")
    flow_id = _id(body.flow_id)
    found = await _run(flow_admin.details(flow_id))
    if found["status"] != "PUBLISHED":
        raise HTTPException(
            400, "Only a published Flow can be used by the chat bot. Publish it first."
        )

    def change(wf: dict):
        mine = dict(wf.get(body.kind) or {})
        mine.update({"flow_id": flow_id, "enabled": True, "mode": "published"})
        if body.kind == "complaint":
            mine.setdefault("workflow", "file_a_complaint")
        wf[body.kind] = mine

    await _write(
        ctx, change, f"The chat bot now uses Flow {flow_id} for its {body.kind}"
    )
    return {"ok": True}


@router.post("/whatsapp-flows")
async def new_flow(ctx: CtxDep, body: NewFlow):
    name = re.sub(r"[^A-Za-z0-9_ -]", "", body.name).strip().replace(" ", "_")
    if not name:
        raise HTTPException(400, "Give the Flow a name (letters, digits and _).")
    account = await _need_account(ctx)
    layout = flow_admin.SAMPLE if body.start == "sample" else flow_admin.BLANK
    flow_id, errors = await _run(flow_admin.create(account, name, layout))
    return {"id": flow_id, "errors": errors}


@router.get("/whatsapp-flows/{flow_id}")
async def get_flow(ctx: CtxDep, flow_id: str):
    flow_id = _id(flow_id)
    found = await _run(flow_admin.details(flow_id))
    text = await _run(flow_admin.read_json(flow_id))
    try:  # shown the way a person would write it
        text = (
            json.dumps(json.loads(text), indent=2, ensure_ascii=False) if text else ""
        )
    except ValueError:
        pass
    settings = await _settings(ctx)
    return {
        **found,
        "json_text": text,
        "used_for": [
            k for k in KINDS if str(_cfg(settings, k).get("flow_id") or "") == flow_id
        ],
    }


@router.put("/whatsapp-flows/{flow_id}/json")
async def save_json(ctx: CtxDep, flow_id: str, body: JsonBody):
    flow_id = _id(flow_id)
    try:
        json.loads(body.json_text)
    except ValueError as e:
        raise HTTPException(400, f"This is not valid JSON yet: {e}") from e
    errors = await _run(flow_admin.save_json(flow_id, body.json_text))
    await log_event(
        ctx,
        "settings",
        "whatsapp_flows",
        f"Saved the draft of WhatsApp Flow {flow_id}",
        target_type="orgs",
        target_id=ctx.org_id,
    )
    return {"ok": True, "errors": errors}


@router.post("/whatsapp-flows/{flow_id}/send-test")
async def send_test(ctx: CtxDep, flow_id: str, body: SendTest):
    """Send the Flow to one phone, as a draft when it is not published yet, the way Meta's own "Send" does. The phone must
    have written to the number in the last 24 hours (WhatsApp's rule for anything that is not an approved template)."""
    flow_id = _id(flow_id)
    phone = re.sub(r"\D", "", body.phone)
    if not 8 <= len(phone) <= 15:
        raise HTTPException(
            400,
            "Type the phone number with its country code, for example 919876543210.",
        )
    found = await _run(flow_admin.details(flow_id))
    try:
        await whatsapp.send_flow(
            phone,
            body=body.message[:1024] or "Testing a WhatsApp Flow",
            flow_id=flow_id,
            cta=(body.button or "Open")[:20],
            screen=body.screen,
            data=body.data or {},
            flow_token=f"test-{uuid.uuid4().hex[:12]}",
            draft=found["status"] != "PUBLISHED",
        )
    except httpx.HTTPStatusError as e:
        try:
            err = e.response.json().get("error") or {}
        except ValueError:
            err = {}
        text = (
            err.get("error_user_msg")
            or err.get("message")
            or "Meta refused the message."
        )
        if err.get("code") == 131047:
            text = "That number has not written to the bot in the last 24 hours, so WhatsApp will not take a free message. Ask them to send “hi” first."
        raise HTTPException(400, str(text)[:400]) from e
    return {"ok": True}


@router.post("/whatsapp-flows/{flow_id}/publish")
async def publish(ctx: CtxDep, flow_id: str):
    flow_id = _id(flow_id)
    await _run(flow_admin.publish(flow_id))
    await log_event(
        ctx,
        "settings",
        "whatsapp_flows",
        f"Published WhatsApp Flow {flow_id}",
        target_type="orgs",
        target_id=ctx.org_id,
    )
    return {"ok": True}


@router.post("/whatsapp-flows/{flow_id}/copy")
async def copy_flow(ctx: CtxDep, flow_id: str, body: JsonBody | None = None):
    """A new draft made from this Flow, with the edited layout when one is sent, else the Flow's own. Meta does not let a
    published Flow be changed, so changing one means a new draft that is then published and used instead."""
    flow_id = _id(flow_id)
    account = await _need_account(ctx)
    found = await _run(flow_admin.details(flow_id))
    text = body.json_text if body else await _run(flow_admin.read_json(flow_id))
    try:
        layout = json.loads(text)
    except ValueError as e:
        raise HTTPException(
            400, "The layout is not valid JSON yet, so it cannot be saved."
        ) from e
    base = re.sub(r"_v\d+$", "", found["name"] or "flow")
    new_id, errors = await _run(
        flow_admin.create(account, f"{base}_v{uuid.uuid4().hex[:4]}", layout)
    )
    return {"id": new_id, "errors": errors}


@router.delete("/whatsapp-flows/{flow_id}")
async def delete_flow(ctx: CtxDep, flow_id: str):
    flow_id = _id(flow_id)
    settings = await _settings(ctx)
    if any(str(_cfg(settings, k).get("flow_id") or "") == flow_id for k in KINDS):
        raise HTTPException(
            400, "The chat bot uses this Flow. Point it at another one first."
        )
    found = await _run(flow_admin.details(flow_id))
    if found["status"] == "PUBLISHED":
        await flow_admin.retire(flow_id)  # a published Flow is retired, not deleted
    else:
        await _run(flow_admin.discard(flow_id))
    await log_event(
        ctx,
        "settings",
        "whatsapp_flows",
        f"Removed WhatsApp Flow {flow_id}",
        target_type="orgs",
        target_id=ctx.org_id,
    )
    return {"ok": True}
