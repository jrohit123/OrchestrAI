"""Settings > Footer note: the common footer for every organisation (routing database, control-0002) and this
organisation's choice (orgs.settings.footer: the common one, its own, or none). Super admins only. See services/footer.py."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.admin_panel.common import CtxDep, PanelRoute, log_event, people_channel
from app.db import execute, fetch_one, routing_pool
from app.services import config_store, footer

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)


async def _org_footer(ctx) -> dict:
    row = await fetch_one(
        "SELECT settings FROM orgs WHERE id = $1", ctx.org_id, source_key=ctx.source_key
    )
    settings = row["settings"] if row else {}
    settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
    mine = settings.get("footer") if isinstance(settings.get("footer"), dict) else {}
    return {
        "mode": mine.get("mode") if mine.get("mode") in footer.MODES else "common",
        "text": footer.clean(mine.get("text")),
        "plain": mine.get("plain") is True,
    }


@router.get("/footer")
async def get_footer(ctx: CtxDep):
    footer.invalidate()
    common = await footer.common()
    mine = await _org_footer(ctx)
    return {
        "org": mine,
        "common": common,
        "shown": footer.effective(mine, common),
        "max": footer.MAX,
        "whatsapp": await people_channel(ctx.source_key) == "whatsapp",
    }


class OrgFooter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = Field(pattern="^(common|own|off)$")
    text: str = Field("", max_length=200)
    plain: StrictBool = False


@router.put("/footer")
async def save_footer(ctx: CtxDep, body: OrgFooter):
    text = footer.clean(body.text)
    if body.mode == "own" and not text:
        raise HTTPException(
            422, "Write the footer text, or choose the common footer or no footer."
        )
    value = {"mode": body.mode, "text": text, "plain": body.plain}
    await execute(
        "UPDATE orgs SET settings = COALESCE(settings, '{}'::jsonb) || jsonb_build_object('footer', $2::jsonb) WHERE id = $1",
        ctx.org_id, json.dumps(value), source_key=ctx.source_key,
    )  # fmt: skip
    config_store.invalidate(ctx.source_key)
    footer.invalidate()
    await log_event(
        ctx,
        "settings",
        "footer",
        f"Footer note: {body.mode}" + (f" “{text}”" if body.mode == "own" else ""),
        after=value,
    )
    return {"ok": True}


class CommonFooter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field("", max_length=200)
    plain: StrictBool = False


@router.put("/footer/common")
async def save_common_footer(ctx: CtxDep, body: CommonFooter):
    if not (await footer.common())["available"]:
        raise HTTPException(
            409,
            "The shared settings are not set up yet. Run migration control-0002 on the routing database first.",
        )
    value = {"text": footer.clean(body.text), "plain": body.plain}
    await routing_pool().execute(
        "INSERT INTO platform_settings (key, value, updated_by, updated_at) VALUES ('footer', $1::jsonb, $2, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = now()",
        json.dumps(value), ctx.actor or "",
    )  # fmt: skip
    footer.invalidate()
    await log_event(
        ctx,
        "settings",
        "footer_common",
        f"Common footer note: “{value['text']}”"
        if value["text"]
        else "Common footer note removed",
        after=value,
    )
    return {"ok": True}
