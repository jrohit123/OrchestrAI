"""The Settings screen: the numbers an organisation can change, each with the number the app
uses when nothing is set.

Every number lives in one of three places and is read by the code through config_store:
  * orgs.session_ttl_minutes    how long a conversation lasts
  * orgs.settings.limits        drafts, re-asks and photos
  * orgs.settings.retention     how long old leftovers are kept before the nightly cleanup

A value that is not set means "use the built-in number" (config_store.LIMITS / RETENTION), so the
screen can always offer to go back to it. Saving is checked against the smallest and largest
allowed number, written to the change log, and applies at once.
"""

import base64
import copy
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt

from app.admin_panel.common import CtxDep, PanelRoute, dump, jb, log_event, tx
from app.db import execute, fetch_one
from app.services import config_store

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

SESSION = (480, 5, 10080)  # orgs.session_ttl_minutes: built-in, smallest, largest

# What the screen shows. section is where the number lives; unit is the word after the box.
GROUPS: list[dict[str, Any]] = [
    {
        "key": "sessions",
        "label": "Chat sessions",
        "intro": "How long the assistant waits for people before it lets go.",
        "fields": [
            {
                "section": "column",
                "key": "session_ttl_minutes",
                "label": "Forget a conversation after",
                "unit": "minutes of silence",
                "help": "After this long without a message, the next message starts a new conversation.",
            },
            {
                "section": "limits",
                "key": "draft_stale_minutes",
                "label": "Drop an unfinished request after",
                "unit": "minutes",
                "help": "Someone started a request (a complaint, an update) and went quiet. After this long it is dropped, so it cannot come back by surprise.",
            },
            {
                "section": "limits",
                "key": "confirm_stale_minutes",
                "label": "Drop an unanswered “save this?” after",
                "unit": "minutes",
                "help": "The assistant showed a summary and asked for a yes. With no answer for this long it forgets it. Shorter on purpose: saving something stale is riskier.",
            },
            {
                "section": "limits",
                "key": "reprompt_max",
                "label": "Ask again at most",
                "unit": "times",
                "help": "When the assistant keeps getting answers it cannot use, it starts over after this many tries.",
            },
        ],
    },
    {
        "key": "photos",
        "label": "Photos",
        "intro": "Photos people send with a request.",
        "fields": [
            {
                "section": "limits",
                "key": "photo_max",
                "label": "Photos kept on one request",
                "unit": "photos",
                "help": "Anything beyond this is ignored.",
            },
            {
                "section": "limits",
                "key": "photo_hold_minutes",
                "label": "Keep a photo that came first for",
                "unit": "minutes",
                "help": "A photo sent before saying what it is for waits this long for its request to start.",
            },
        ],
    },
    {
        "key": "retention",
        "label": "Keeping old records",
        "intro": "Every night at 03:30 the assistant clears out leftovers nobody needs. Each one is copied to a safe place first, and can be put back by whoever looks after the database.",
        "fields": [
            {
                "section": "retention",
                "key": "drafts_days",
                "label": "Finished drafts",
                "unit": "days",
                "help": "Requests that were saved or cancelled. Cleared this long after they ended.",
            },
            {
                "section": "retention",
                "key": "otp_days",
                "label": "Expired one-time codes",
                "unit": "days",
                "help": "Codes people were sent to approve something. Cleared this long after they expired.",
            },
            {
                "section": "retention",
                "key": "workflow_drafts_days",
                "label": "Abandoned flow drafts",
                "unit": "days",
                "help": "Flows someone started building and gave up on. Cleared this long after the last change.",
            },
            {
                "section": "retention",
                "key": "archive_days",
                "label": "The safe copies themselves",
                "unit": "days",
                "help": "How long the copy of everything cleared is kept before it too is removed.",
            },
        ],
    },
]

# every editable number: (section, key) -> (built-in, smallest, largest)
RANGES: dict[tuple[str, str], tuple[int, int, int]] = {
    ("column", "session_ttl_minutes"): SESSION,
    **{("limits", k): v for k, v in config_store.LIMITS.items()},
    **{("retention", k): v for k, v in config_store.RETENTION.items()},
}


def _label(section: str, key: str) -> str:
    for group in GROUPS:
        for f in group["fields"]:
            if (f["section"], f["key"]) == (section, key):
                return f["label"]
    return key


def _own_number(settings: dict, section: str, key: str) -> int | None:
    """The organisation's own number when it set a usable one, else None."""
    value = config_store.setting(settings, f"{section}.{key}")
    ok = isinstance(value, int | float) and not isinstance(value, bool) and value > 0
    return int(value) if ok else None


def describe(settings: dict, session_ttl: int | None) -> dict[str, Any]:
    """The groups of the screen with each number's current value, and the built-in number."""
    groups = []
    for group in GROUPS:
        fields = []
        for f in group["fields"]:
            default, smallest, largest = RANGES[(f["section"], f["key"])]
            if f["section"] == "column":
                own = session_ttl if session_ttl and session_ttl != default else None
                value = session_ttl or default
            else:
                own = _own_number(settings, f["section"], f["key"])
                value = own if own is not None else default
            fields.append(
                {
                    **f,
                    "default": default,
                    "min": smallest,
                    "max": largest,
                    "value": value,
                    "custom": own is not None,
                }
            )
        out = {**group, "fields": fields}
        if group["key"] == "retention":
            out["enabled"] = (
                config_store.setting(settings, "retention.enabled", True) is not False
            )
        groups.append(out)
    return {"groups": groups}


class SettingsBody(BaseModel):
    """What the screen sends. A key left out stays as it is; null goes back to the built-in
    number."""

    model_config = ConfigDict(extra="forbid")
    session_ttl_minutes: StrictInt | None = None
    limits: dict[str, StrictInt | None] = {}
    retention: dict[str, StrictInt | StrictBool | None] = {}


def check(body: SettingsBody) -> None:
    """Refuse an unknown name or a number outside its allowed range, in plain words."""
    for section, changes in (("limits", body.limits), ("retention", body.retention)):
        for key, value in changes.items():
            if section == "retention" and key == "enabled":
                if value is not None and not isinstance(value, bool):
                    raise HTTPException(
                        400, "Switch the clean-up on or off with true or false."
                    )
                continue
            if (section, key) not in RANGES:
                raise HTTPException(400, f"'{key}' is not a setting.")
            if value is None:
                continue
            if isinstance(value, bool):
                raise HTTPException(400, f"{_label(section, key)} must be a number.")
            _, smallest, largest = RANGES[(section, key)]
            if not smallest <= value <= largest:
                raise HTTPException(
                    400,
                    f"{_label(section, key)} must be between {smallest} and {largest}.",
                )
    if body.session_ttl_minutes is not None:
        _, smallest, largest = SESSION
        if not smallest <= body.session_ttl_minutes <= largest:
            raise HTTPException(
                400,
                f"{_label('column', 'session_ttl_minutes')} must be between {smallest} and {largest}.",
            )


def merged(settings: dict, body: SettingsBody) -> dict:
    """orgs.settings with the changes applied. Everything else in it is left exactly as it was."""
    out = copy.deepcopy(settings)
    for section, changes in (("limits", body.limits), ("retention", body.retention)):
        current = out.get(section)
        current = dict(current) if isinstance(current, dict) else {}
        for key, value in changes.items():
            # switching the clean-up back on is the built-in state, so it needs no key
            if value is None or (section == "retention" and key == "enabled" and value):
                current.pop(key, None)
            else:
                current[key] = value
        if current:
            out[section] = current
        else:
            out.pop(section, None)
    return out


def summary(settings: dict, new: dict, old_ttl: int | None, new_ttl: int | None) -> str:
    """One line for the change log: what is now different, in the screen's own words."""
    parts = []
    for (section, key), (default, _, _) in RANGES.items():
        if section == "column":
            before, after = old_ttl or default, new_ttl or old_ttl or default
        else:
            before = _own_number(settings, section, key) or default
            after = _own_number(new, section, key) or default
        if before != after:
            parts.append(f"{_label(section, key)} {after} (was {before})")
    was_on = config_store.setting(settings, "retention.enabled", True) is not False
    now_on = config_store.setting(new, "retention.enabled", True) is not False
    if was_on != now_on:
        parts.append("Nightly clean-up " + ("on" if now_on else "off"))
    return "Changed settings: " + "; ".join(parts) if parts else "Saved settings"


@router.get("/org-settings")
async def get_org_settings(ctx: CtxDep):
    org = await fetch_one(
        "SELECT name, settings, session_ttl_minutes FROM orgs WHERE id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not org:
        raise HTTPException(404, "This organisation was not found.")
    settings = jb(org["settings"], {})
    return {
        "org": {"name": org["name"], "timezone": config_store.DEFAULT_TIMEZONE},
        **describe(
            settings if isinstance(settings, dict) else {}, org["session_ttl_minutes"]
        ),
    }


@router.put("/org-settings")
async def put_org_settings(ctx: CtxDep, body: SettingsBody):
    check(body)
    async with tx(ctx) as conn:
        org = await conn.fetchrow(
            "SELECT settings, session_ttl_minutes FROM orgs WHERE id = $1 FOR UPDATE",
            ctx.org_id,
        )
        if not org:
            raise HTTPException(404, "This organisation was not found.")
        old = jb(org["settings"], {})
        old = old if isinstance(old, dict) else {}
        new = merged(old, body)
        ttl = body.session_ttl_minutes
        await conn.execute(
            "UPDATE orgs SET settings = $1::jsonb, "
            "session_ttl_minutes = COALESCE($2, session_ttl_minutes) WHERE id = $3",
            dump(new),
            ttl,
            ctx.org_id,
        )
        await log_event(
            ctx,
            "settings",
            "numbers",
            summary(old, new, org["session_ttl_minutes"], ttl),
            target_type="orgs",
            target_id=ctx.org_id,
            before={
                "limits": old.get("limits"),
                "retention": old.get("retention"),
                "session_ttl_minutes": org["session_ttl_minutes"],
            },
            after={
                "limits": new.get("limits"),
                "retention": new.get("retention"),
                "session_ttl_minutes": ttl or org["session_ttl_minutes"],
            },
            conn=conn,
        )
    config_store.invalidate(
        ctx.source_key
    )  # the assistant sees it at once on this copy
    return {"ok": True}


# ── the logo, and ending every ongoing conversation ──────────────────────────

LOGO_MAX_BYTES = 2 * 1024 * 1024


@router.get("/logo")
async def get_logo(ctx: CtxDep):
    org = await fetch_one(
        "SELECT logo_url FROM orgs WHERE id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    return {"logo_url": org["logo_url"] if org else None}


@router.post("/logo")
async def upload_logo(ctx: CtxDep, request: Request):
    """The organisation's logo, kept in orgs.logo_url as a small inline picture (there is no file
    storage in this app). The PDFs the flows make show it with a plain <img src="...">, which takes
    this kind of address exactly like a hosted one."""
    form = await request.form()
    upload = form.get("logo_file")
    if not upload:
        raise HTTPException(status_code=400, detail="logo_file is required")
    content_type = getattr(upload, "content_type", "") or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Logo must be an image file")
    image = await upload.read()
    if len(image) > LOGO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Logo image is too large (max 2MB)")
    data_uri = f"data:{content_type};base64,{base64.b64encode(image).decode()}"
    await execute(
        "UPDATE orgs SET logo_url = $1 WHERE id = $2",
        data_uri,
        ctx.org_id,
        source_key=ctx.source_key,
    )
    await log_event(
        ctx,
        "settings",
        "logo",
        "Changed the logo",
        target_type="orgs",
        target_id=ctx.org_id,
    )
    return {"logo_url": data_uri}


@router.post("/sessions/clear")
async def clear_sessions(ctx: CtxDep):
    """Ends every ongoing conversation: the next message from anyone starts a new one."""
    from app.redis_client import clear_all_sessions

    await clear_all_sessions(ctx.org_id)
    await log_event(
        ctx,
        "settings",
        "sessions",
        "Ended every ongoing conversation",
        target_type="orgs",
        target_id=ctx.org_id,
    )
    return {"cleared": True}
