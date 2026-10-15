"""The Message templates screen: list the WhatsApp message templates of the business account with their approval status, write a
new one in plain words, send it to Meta for approval, delete one, and say which approved template the chat bot uses to ask a
person to open their WhatsApp again (the 24-hour reminder, see app/services/reach.py).

Meta keeps the templates (see app/services/template_admin.py). Our database keeps only drafts not sent yet and the labels of the
blanks (core-0025), and the organisation's settings keep one choice: orgs.settings -> reach.template = {name, language}.
Nothing here knows what a template says."""

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.admin_panel.common import CtxDep, PanelRoute, dump, jb, log_event, tx
from app.admin_panel.whatsapp_flows import _account
from app.db import execute, fetch_all
from app.services import config_store, reach, template_admin
from app.services.template_admin import TemplateError

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


class SpecBody(BaseModel):
    """A template as written in the form. Checked by template_admin.clean_spec, which says what is wrong in plain words."""

    model_config = ConfigDict(extra="forbid")
    name: str = ""
    language: str = "en"
    category: str = "UTILITY"
    header: dict | None = None
    body: str = ""
    examples: list[str] = []
    footer: str = ""
    buttons: list[dict] = []
    labels: list[str] = []


class ReminderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    language: str = "en"


def _fail(e: TemplateError) -> HTTPException:
    return HTTPException(400, str(e))


async def _run(coro):
    try:
        return await coro
    except template_admin.MetaError as e:
        raise HTTPException(400, str(e)) from e


async def _need_account(ctx) -> str:
    account = await _account(ctx)
    if not account:
        raise HTTPException(
            400,
            "Meta needs the number of your WhatsApp business account. Paste it once on the WhatsApp Flows tab.",
        )
    return account


def _has_blanks(spec: dict) -> bool:
    return bool(
        template_admin.blanks_of(spec.get("body"))
        or (spec.get("header") and template_admin.blanks_of(spec["header"]["text"]))
        or any("{{" in (b.get("url") or "") for b in spec.get("buttons") or [])
    )


async def _drafts(ctx) -> list[dict]:
    if not ctx.caps.get("template_drafts"):
        return []
    found = await fetch_all(
        "SELECT id, name, language, category, spec, meta_template_id, submitted_at, updated_at "
        "FROM whatsapp_template_drafts WHERE org_id = $1 ORDER BY updated_at DESC",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    out = []
    for r in found:
        spec = jb(r["spec"], {})
        out.append(
            {
                "draft_id": str(r["id"]),
                "name": r["name"],
                "language": r["language"],
                "category": r["category"],
                "spec": spec if isinstance(spec, dict) else {},
                "submitted": r["submitted_at"] is not None,
            }
        )
    return out


def _reminder_of(ctx) -> dict | None:
    chosen = reach.template_of(ctx.settings)
    return {"name": chosen[0], "language": chosen[1]} if chosen else None


async def _write_reminder(ctx, chosen: dict | None, summary: str) -> None:
    """Set or clear orgs.settings -> reach.template in one step."""
    async with tx(ctx) as conn:
        org = await conn.fetchrow(
            "SELECT settings FROM orgs WHERE id = $1 FOR UPDATE", ctx.org_id
        )
        if not org:
            raise HTTPException(404, "This organisation was not found.")
        old = jb(org["settings"], {})
        old = old if isinstance(old, dict) else {}
        new = dict(old)
        mine = dict(new.get("reach") or {})
        if chosen:
            mine["template"] = chosen
        else:
            mine.pop("template", None)
        new["reach"] = mine
        await conn.execute(
            "UPDATE orgs SET settings = $1::jsonb WHERE id = $2", dump(new), ctx.org_id
        )
        await log_event(
            ctx,
            "settings",
            "whatsapp_templates",
            summary,
            target_type="orgs",
            target_id=ctx.org_id,
            before=old.get("reach"),
            after=mine,
            conn=conn,
        )
    config_store.invalidate(ctx.source_key)


@router.get("/whatsapp-templates")
async def list_templates(ctx: CtxDep):
    account = await _account(ctx)
    drafts = await _drafts(ctx)
    reminder = _reminder_of(ctx)
    metas = await _run(template_admin.list_templates(account)) if account else []
    labels = {(d["name"], d["language"]): d["spec"].get("labels") or [] for d in drafts}
    out = []
    for t in metas:
        mine = labels.get((t["name"], t["language"]))
        if mine and len(mine) == len(t["examples"]):
            t["labels"] = [str(x) for x in mine]
        t["source"] = "meta"
        t["reminder"] = bool(
            reminder
            and reminder["name"] == t["name"]
            and reminder["language"] == t["language"]
        )
        t["can_remind"] = t["status"] == "APPROVED" and not _has_blanks(t)
        out.append(t)
    for d in drafts:
        if d[
            "submitted"
        ]:  # sent to Meta: it is listed from Meta's side (this row only keeps the blanks' labels)
            continue
        out.append(
            {
                **d["spec"],
                "name": d["name"],
                "language": d["language"],
                "category": d["category"],
                "status": "DRAFT",
                "reason": "",
                "id": "",
                "extras": [],
                "source": "draft",
                "draft_id": d["draft_id"],
                "reminder": False,
                "can_remind": False,
            }
        )
    return {
        "account_known": bool(account),
        "drafts_available": bool(ctx.caps.get("template_drafts")),
        "templates": out,
        "reminder": reminder,
        "limits": template_admin.LIMITS,
    }


@router.post("/whatsapp-templates/drafts")
async def save_draft(ctx: CtxDep, body: SpecBody):
    """Keep a half-written template. Only the name has to be right."""
    ctx.need("template_drafts")
    name = template_admin.slug(body.name)
    if not name:
        raise HTTPException(400, "Give the template a name first.")
    spec = body.model_dump()
    spec["name"] = name
    await execute(
        "INSERT INTO whatsapp_template_drafts (org_id, name, language, category, spec, created_by) "
        "VALUES ($1, $2, $3, $4, $5::jsonb, $6) "
        "ON CONFLICT (org_id, name, language) DO UPDATE SET category = EXCLUDED.category, "
        "spec = EXCLUDED.spec, submitted_at = NULL, meta_template_id = NULL, updated_at = now()",
        ctx.org_id,
        name,
        body.language or "en",
        (body.category or "UTILITY").upper(),
        dump(spec),
        ctx.actor,
        source_key=ctx.source_key,
    )
    await log_event(
        ctx,
        "settings",
        "whatsapp_templates",
        f"Saved the draft of message template {name}",
        target_type="orgs",
        target_id=ctx.org_id,
    )
    return {"ok": True, "name": name}


@router.delete("/whatsapp-templates/drafts/{draft_id}")
async def delete_draft(ctx: CtxDep, draft_id: str):
    ctx.need("template_drafts")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", draft_id):
        raise HTTPException(400, "That is not a draft.")
    await execute(
        "DELETE FROM whatsapp_template_drafts WHERE id = $1::uuid AND org_id = $2 AND submitted_at IS NULL",
        draft_id,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {"ok": True}


@router.post("/whatsapp-templates")
async def send_for_approval(ctx: CtxDep, body: SpecBody):
    """Send a template to Meta. Meta answers at once with "pending"; the verdict comes later (a few minutes to a day) and is
    read with Refresh."""
    try:
        spec = template_admin.clean_spec(body.model_dump())
        template_admin.build_payload(spec)
    except TemplateError as e:
        raise _fail(e) from e
    account = await _need_account(ctx)
    made = await _run(template_admin.create(account, spec))
    if ctx.caps.get("template_drafts"):
        await execute(
            "INSERT INTO whatsapp_template_drafts "
            "(org_id, name, language, category, spec, meta_template_id, submitted_at, created_by) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6, now(), $7) "
            "ON CONFLICT (org_id, name, language) DO UPDATE SET category = EXCLUDED.category, "
            "spec = EXCLUDED.spec, meta_template_id = EXCLUDED.meta_template_id, "
            "submitted_at = now(), updated_at = now()",
            ctx.org_id,
            spec["name"],
            spec["language"],
            made["category"] or spec["category"],
            dump(spec),
            made["id"],
            ctx.actor,
            source_key=ctx.source_key,
        )
    await log_event(
        ctx,
        "settings",
        "whatsapp_templates",
        f"Sent message template {spec['name']} to Meta for approval",
        target_type="orgs",
        target_id=ctx.org_id,
    )
    return {"ok": True, **made, "name": spec["name"]}


@router.put("/whatsapp-templates/reminder")
async def use_for_reminder(ctx: CtxDep, body: ReminderBody):
    """Choose (or, with no name, stop choosing) the approved template that asks a person to open their WhatsApp again."""
    if not body.name:
        await _write_reminder(
            ctx,
            None,
            "The chat bot no longer sends a template for the 24-hour reminder",
        )
        return {"ok": True}
    account = await _need_account(ctx)
    found = [
        t
        for t in await _run(template_admin.list_templates(account))
        if t["name"] == body.name and t["language"] == body.language
    ]
    if not found:
        raise HTTPException(400, "Meta has no template with that name and language.")
    if found[0]["status"] != "APPROVED":
        raise HTTPException(
            400, "Only an approved template can be used. Wait for Meta to approve it."
        )
    if _has_blanks(found[0]):
        raise HTTPException(
            400,
            "This template has blanks, and the 24-hour reminder cannot fill them in. Use one without blanks.",
        )
    await _write_reminder(
        ctx,
        {"name": body.name, "language": body.language},
        f"The chat bot now uses message template {body.name} ({body.language}) for the 24-hour reminder",
    )
    return {"ok": True}


@router.delete("/whatsapp-templates/{name}")
async def delete_template(ctx: CtxDep, name: str, template_id: str | None = None):
    name = template_admin.slug(name)
    if not name:
        raise HTTPException(400, "That is not a template name.")
    reminder = _reminder_of(ctx)
    if reminder and reminder["name"] == name:
        raise HTTPException(
            400,
            "The 24-hour reminder uses this template. Choose another one (or none) first.",
        )
    if template_id is not None and not re.fullmatch(r"\d{5,25}", template_id):
        raise HTTPException(400, "That is not a template number.")
    account = await _need_account(ctx)
    await _run(template_admin.remove(account, name, template_id or None))
    if ctx.caps.get("template_drafts"):
        await execute(
            "DELETE FROM whatsapp_template_drafts WHERE org_id = $1 AND name = $2",
            ctx.org_id,
            name,
            source_key=ctx.source_key,
        )
    await log_event(
        ctx,
        "settings",
        "whatsapp_templates",
        f"Deleted message template {name}",
        target_type="orgs",
        target_id=ctx.org_id,
    )
    return {"ok": True}
