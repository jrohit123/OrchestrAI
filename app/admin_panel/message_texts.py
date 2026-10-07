"""The Messages screen: every text the chat bot sends by itself (app/services/messages.py), with the
organisation's own wording where it wrote one.

The wording in use is the strongest of: the organisation's own (scope 'tenant'), the standard
wording stored in its database (scope 'global'), the one built into the code. The dashboard changes
only the first. A saved wording is a new version of one row in system_messages (scope 'tenant');
older versions stay, so the history only grows and "restore" is just saving an old wording again.
Going back to the standard wording switches the saved versions off instead of deleting them. The
chat bot reads the newest active version (config_store.message), so a save applies at once on the
copy of the app that saved it, and within a minute on any other.
"""

import string
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.admin_panel.common import CtxDep, PanelRoute, dump, log_event, rows, tx
from app.db import fetch_all
from app.services import config_store
from app.services.messages import GROUPS, MESSAGES, Msg

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

LOCALE = "en-IN"  # every text is English for now; the table already has a locale column
MAX_LENGTH = 3000  # WhatsApp refuses a message of about 4000 characters

_OWN = "scope = 'tenant' AND scope_ref = ''"
# the standard wording stored in the database ($1 = the key, $2 = the locale)
_STANDARD = (
    "SELECT body FROM system_messages WHERE key = $1 AND locale = $2 AND scope = 'global' "
    "AND scope_ref = '' AND is_active ORDER BY version DESC LIMIT 1"
)


def _message(key: str) -> Msg:
    if key not in MESSAGES:
        raise HTTPException(404, "There is no such message.")
    return MESSAGES[key]


def check(msg: Msg, text: str) -> dict[str, Any]:
    """What is wrong with this wording, in plain words, and what it would look like to a person.
    `problems` stop a save; `warnings` do not."""
    problems: list[str] = []
    warnings: list[str] = []
    used: set[str] = set()
    if not text.strip():
        problems.append("The text is empty.")
    if len(text) > MAX_LENGTH:
        problems.append(
            f"The text is too long ({len(text)} characters; the most is {MAX_LENGTH})."
        )
    try:
        for _, field, spec, conversion in string.Formatter().parse(text):
            if field is None:
                continue
            if spec or conversion:
                problems.append("Only plain names go between { and }, like {name}.")
            elif field not in msg.values:
                known = ", ".join("{" + n + "}" for n in msg.values) or "none"
                problems.append(
                    f"{{{field}}} is not something this message knows. You can use: {known}."
                )
            else:
                used.add(field)
    except ValueError:
        problems.append(
            "A { or } is not closed. Write { and } only around a name, like {name}."
        )
    if not problems:
        for name in msg.values:
            if name not in used:
                warnings.append(
                    f"This text does not show {{{name}}} ({msg.values[name]}), so people will not see it."
                )
    preview = None
    if not problems:
        try:
            preview = config_store.fill(text, msg.example)
        except ValueError:
            problems.append("That text cannot be filled in.")
    return {
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "preview": preview,
    }


# ---- the database part: small functions so they can be tried against a plain connection


async def newest_own(conn, key: str):
    """The organisation's current wording of one message (newest active version), or None."""
    return await conn.fetchrow(
        f"SELECT version, body FROM system_messages WHERE key = $1 AND locale = $2 AND {_OWN} "
        "AND is_active ORDER BY version DESC LIMIT 1",
        key,
        LOCALE,
    )


async def standard_text(conn, msg: Msg) -> str:
    """The wording without the organisation's own version: the standard one stored in the database,
    else the one built into the code."""
    row = await conn.fetchrow(_STANDARD, msg.key, LOCALE)
    return row["body"] if row else msg.text


async def save_version(
    conn, msg: Msg, text: str, note: str | None, actor: str
) -> int | None:
    """Save `text` as the newest version. Returns its number, or None when nothing changed
    (the text is what is already in use). Saving the standard wording goes back to it."""
    current = await newest_own(conn, msg.key)
    standard = await standard_text(conn, msg)
    if text == (current["body"] if current else standard):
        return None
    if text == standard:
        await reset_to_built_in(conn, msg.key)
        return 0
    version = await conn.fetchval(
        "SELECT coalesce(max(version), 0) + 1 FROM system_messages "
        f"WHERE key = $1 AND locale = $2 AND {_OWN}",
        msg.key,
        LOCALE,
    )
    await conn.execute(
        "INSERT INTO system_messages (key, locale, scope, scope_ref, version, body, variables, "
        "is_active, note, created_by) VALUES ($1, $2, 'tenant', '', $3, $4, $5::jsonb, true, $6, $7)",
        msg.key,
        LOCALE,
        version,
        text,
        dump(sorted(msg.values)),
        note,
        actor,
    )
    return version


async def reset_to_built_in(conn, key: str) -> int:
    """Switch off every saved version of one message, so the standard wording is used again.
    Nothing is deleted. Returns how many were switched off."""
    return await conn.fetchval(
        "WITH off AS (UPDATE system_messages SET is_active = false "
        f"WHERE key = $1 AND locale = $2 AND {_OWN} AND is_active RETURNING 1) "
        "SELECT count(*) FROM off",
        key,
        LOCALE,
    )


# ---- the screen


class TextBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    note: str | None = Field(None, max_length=200)


@router.get("/messages")
async def list_messages(ctx: CtxDep):
    ready = bool(ctx.caps.get("texts"))
    saved: dict[tuple[str, str], dict] = {}
    if ready:
        # the newest wording of each message that is in the database: the organisation's own and
        # the standard one
        found = rows(
            await fetch_all(
                "SELECT DISTINCT ON (key, scope) key, scope, version, body, created_at, created_by "
                "FROM system_messages WHERE locale = $1 AND scope_ref = '' "
                "AND scope IN ('tenant', 'global') AND is_active "
                "ORDER BY key, scope, version DESC",
                LOCALE,
                source_key=ctx.source_key,
            )
        )
        saved = {(r["key"], r["scope"]): r for r in found}
    groups = []
    for group_key, (label, about) in GROUPS.items():
        items = []
        for m in MESSAGES.values():
            if m.group != group_key:
                continue
            own = saved.get((m.key, "tenant"))
            standard = saved.get((m.key, "global"))
            s = own or standard
            if own:
                source = "own"
            elif standard:
                source = "shared"
            else:
                source = "built_in"
            items.append(
                {
                    "key": m.key,
                    "name": m.name,
                    "when": m.when,
                    "default": m.text,
                    "standard": standard["body"] if standard else m.text,
                    "text": s["body"] if s else m.text,
                    "source": source,
                    "version": s["version"] if s else None,
                    "updated_at": s["created_at"] if s else None,
                    "updated_by": s["created_by"] if s else None,
                    "values": m.values,
                    "example": m.example,
                }
            )
        groups.append(
            {"key": group_key, "label": label, "about": about, "messages": items}
        )
    return {"ready": ready, "locale": LOCALE, "groups": groups}


@router.post("/messages/{key}/check")
async def check_text(key: str, body: TextBody, ctx: CtxDep):
    """What a wording would look like, and what is wrong with it, before it is saved."""
    return check(_message(key), body.text.strip())


@router.get("/messages/{key}/history")
async def history(key: str, ctx: CtxDep):
    ctx.need("texts")
    _message(key)
    found = rows(
        await fetch_all(
            "SELECT version, body, is_active, note, created_at, created_by FROM system_messages "
            f"WHERE key = $1 AND locale = $2 AND {_OWN} ORDER BY version DESC",
            key,
            LOCALE,
            source_key=ctx.source_key,
        )
    )
    return {
        "versions": [
            {
                "version": r["version"],
                "text": r["body"],
                "active": r["is_active"],
                "note": r["note"],
                "created_at": r["created_at"],
                "created_by": r["created_by"],
            }
            for r in found
        ]
    }


@router.put("/messages/{key}")
async def save_text(key: str, body: TextBody, ctx: CtxDep):
    ctx.need("texts")
    msg = _message(key)
    text = body.text.strip()
    found = check(msg, text)
    if found["problems"]:
        raise HTTPException(400, " ".join(found["problems"]))
    async with tx(ctx) as conn:
        was = await newest_own(conn, key)
        standard = await standard_text(conn, msg)
        version = await save_version(conn, msg, text, body.note, ctx.actor)
        if version is not None:
            await log_event(
                ctx,
                "messages",
                "text",
                f"Changed the message “{msg.name}”"
                if version
                else f"Went back to the standard wording of “{msg.name}”",
                target_type="system_messages",
                target_id=key,
                before={"text": was["body"] if was else standard},
                after={"text": text},
                conn=conn,
            )
    config_store.invalidate(ctx.source_key)
    return {"ok": True, "changed": version is not None, "version": version}


@router.delete("/messages/{key}")
async def use_built_in(key: str, ctx: CtxDep):
    ctx.need("texts")
    msg = _message(key)
    async with tx(ctx) as conn:
        was = await newest_own(conn, key)
        standard = await standard_text(conn, msg)
        n = await reset_to_built_in(conn, key)
        if n:
            await log_event(
                ctx,
                "messages",
                "text",
                f"Went back to the standard wording of “{msg.name}”",
                target_type="system_messages",
                target_id=key,
                before={"text": was["body"] if was else None},
                after={"text": standard},
                conn=conn,
            )
    config_store.invalidate(ctx.source_key)
    return {"ok": True, "changed": bool(n)}
