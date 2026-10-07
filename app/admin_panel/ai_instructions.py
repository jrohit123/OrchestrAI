"""The AI instructions screen: the written text the assistant follows, in three layers that are put
one after the other (see app/services/prompt_loader.py):

  1. agent.shared    how to behave, ask and answer; the same starting point for every client
  2. agent.industry  words and habits of this kind of business
  3. agent.client    local facts about this one organisation

What the assistant is also told on every turn (today's date, the person's role, the flows they may
start, the tables it may read) is filled in by the system and is not written here.

A saved text is a new version of one row in `prompts` (scope 'tenant'); older versions stay, so the
history only grows and "go back" is just saving an old text again. Going back to the built-in text
(the prompt files in the code) switches the saved versions off instead of deleting them. The
assistant reads the newest active version (config_store.prompt), so a save applies at once on the
copy of the app that saved it, and within a minute on any other.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.admin_panel.common import CtxDep, PanelRoute, dump, log_event, rows, tx
from app.db import fetch_all, fetch_one
from app.services import config_store, prompt_loader

router = APIRouter(
    prefix="/admin/{org_slug}/api/v2", tags=["admin-panel"], route_class=PanelRoute
)

MAX_LENGTH = 100_000
SHORT_AFTER = (
    0.3  # a new text this much shorter than the built-in one is worth a warning
)

_OWN = "scope = 'tenant' AND scope_ref = ''"

# key -> (name, what it is). {industry} and {org} are filled in with this organisation's words.
LAYERS: dict[str, tuple[str, str]] = {
    "agent.shared": (
        "Shared rules",
        (
            "How the chat bot behaves, how it asks, and when it says it is not sure. The same "
            "starting point for every client, so change it with care."
        ),
    ),
    "agent.industry": (
        "About {industry}",
        "Words and habits of this kind of business. Shared by clients of the same kind.",
    ),
    "agent.client": (
        "Notes for {org}",
        "Local facts: names of buildings, house rules, how people say things here.",
    ),
}
CAN_BE_EMPTY = {
    "agent.client"
}  # a client with no notes is normal; the other two must say something


def _layer(key: str) -> tuple[str, str]:
    if key not in LAYERS:
        raise HTTPException(404, "There is no such set of instructions.")
    return LAYERS[key]


def _name(key: str, org: dict) -> str:
    """The layer's name in this organisation's words, e.g. "About housing society"."""
    industry = (org.get("industry") or "this kind of business").lower()
    return LAYERS[key][0].format(
        industry=industry.replace("_", " ").replace("-", " "),
        org=org.get("name") or "this organisation",
    )


def check(key: str, text: str, built_in: str) -> dict[str, Any]:
    """What is wrong with this text, in plain words. `problems` stop a save; `warnings` do not."""
    problems: list[str] = []
    warnings: list[str] = []
    if "\x00" in text:
        problems.append("The text has a character that cannot be saved.")
    if len(text) > MAX_LENGTH:
        problems.append(
            f"The text is too long ({len(text):,} characters; the most is {MAX_LENGTH:,})."
        )
    if not text.strip() and key not in CAN_BE_EMPTY:
        problems.append(
            "This text cannot be empty. Use the built-in text to go back to the original."
        )
    if text.strip() and len(built_in) > 500 and len(text) < len(built_in) * SHORT_AFTER:
        warnings.append(
            f"This is much shorter than the built-in text ({len(text):,} against "
            f"{len(built_in):,} characters). The chat bot will lose guidance it has today."
        )
    return {
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "characters": len(text),
        "lines": len(text.splitlines()),
    }


# ---- the database part: small functions so they can be tried against a plain connection


async def newest_own(conn, key: str):
    """The organisation's current text of one layer (newest active version), or None."""
    return await conn.fetchrow(
        f"SELECT version, body FROM prompts WHERE key = $1 AND {_OWN} "
        "AND is_active ORDER BY version DESC LIMIT 1",
        key,
    )


async def save_version(
    conn, key: str, text: str, built_in: str, note: str | None, actor: str
) -> int | None:
    """Save `text` as the newest version. Returns its number, 0 when it went back to the
    built-in text, or None when nothing changed (the text is what is already in use)."""
    current = await newest_own(conn, key)
    if text == (current["body"] if current else built_in):
        return None
    if text == built_in:  # the same words as the built-in text: just use that again
        await reset_to_built_in(conn, key)
        return 0
    version = await conn.fetchval(
        f"SELECT coalesce(max(version), 0) + 1 FROM prompts WHERE key = $1 AND {_OWN}",
        key,
    )
    await conn.execute(
        "INSERT INTO prompts (key, scope, scope_ref, version, body, variables, is_active, note, "
        "created_by) VALUES ($1, 'tenant', '', $2, $3, $4::jsonb, true, $5, $6)",
        key,
        version,
        text,
        dump([]),
        note,
        actor,
    )
    return version


async def reset_to_built_in(conn, key: str) -> int:
    """Switch off every saved version of one layer, so the built-in text is used again. Nothing
    is deleted. Returns how many were switched off."""
    return await conn.fetchval(
        "WITH off AS (UPDATE prompts SET is_active = false "
        f"WHERE key = $1 AND {_OWN} AND is_active RETURNING 1) SELECT count(*) FROM off",
        key,
    )


# ---- the screen


class TextBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    note: str | None = Field(None, max_length=200)


async def _org(ctx) -> dict:
    org = await fetch_one(
        "SELECT name, industry, slug FROM orgs WHERE id = $1",
        ctx.org_id,
        source_key=ctx.source_key,
    )
    if not org:
        raise HTTPException(404, "This organisation was not found.")
    return dict(org)


@router.get("/instructions")
async def list_instructions(ctx: CtxDep):
    org = await _org(ctx)
    ready = bool(ctx.caps.get("prompts"))
    pack = prompt_loader.industry_of(org)
    built_in = prompt_loader.built_in(org)
    saved: dict[str, dict] = {}
    if ready:
        found = rows(
            await fetch_all(
                "SELECT DISTINCT ON (key) key, scope, version, body, created_at, created_by "
                "FROM prompts WHERE is_active AND key = ANY($1) AND ("
                "(scope = 'tenant' AND scope_ref = '') "
                "OR (scope = 'pack' AND scope_ref = $2 AND key = 'agent.industry') "
                "OR (scope = 'global' AND scope_ref = '')) "
                "ORDER BY key, CASE scope WHEN 'tenant' THEN 0 WHEN 'pack' THEN 1 ELSE 2 END, "
                "version DESC",
                list(LAYERS),
                pack or "",
                source_key=ctx.source_key,
            )
        )
        saved = {r["key"]: r for r in found}
    layers = []
    for key, (_, about) in LAYERS.items():
        s = saved.get(key)
        source = (
            {"tenant": "own", "pack": "industry", "global": "shared"}[s["scope"]]
            if s
            else "built_in"
        )
        layers.append(
            {
                "key": key,
                "name": _name(key, org),
                "about": about,
                "text": s["body"] if s else built_in.get(key, ""),
                "built_in": built_in.get(key, ""),
                "source": source,
                "version": s["version"] if s else None,
                "updated_at": s["created_at"] if s else None,
                "updated_by": s["created_by"] if s else None,
                "can_be_empty": key in CAN_BE_EMPTY,
            }
        )
    return {"ready": ready, "layers": layers}


@router.get("/instructions/assembled")
async def assembled(ctx: CtxDep):
    """The layers put together, exactly as the assistant receives them."""
    org = await _org(ctx)
    text = await prompt_loader.load_domain_prompt(org, ctx.source_key)
    return {"text": text, "characters": len(text), "lines": len(text.splitlines())}


@router.post("/instructions/{key}/check")
async def check_text(key: str, body: TextBody, ctx: CtxDep):
    _layer(key)
    org = await _org(ctx)
    return check(key, body.text, prompt_loader.built_in(org).get(key, ""))


@router.get("/instructions/{key}/history")
async def history(key: str, ctx: CtxDep):
    ctx.need("prompts")
    _layer(key)
    found = rows(
        await fetch_all(
            "SELECT version, body, is_active, note, created_at, created_by FROM prompts "
            f"WHERE key = $1 AND {_OWN} ORDER BY version DESC",
            key,
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


@router.put("/instructions/{key}")
async def save_text(key: str, body: TextBody, ctx: CtxDep):
    ctx.need("prompts")
    _layer(key)
    org = await _org(ctx)
    name = _name(key, org)
    built_in = prompt_loader.built_in(org).get(key, "")
    text = body.text.strip()
    found = check(key, text, built_in)
    if found["problems"]:
        raise HTTPException(400, " ".join(found["problems"]))
    async with tx(ctx) as conn:
        was = await newest_own(conn, key)
        version = await save_version(conn, key, text, built_in, body.note, ctx.actor)
        if version is not None:
            await log_event(
                ctx,
                "instructions",
                "text",
                f"Changed the AI notes: {name}"
                if version
                else f"Went back to the built-in AI notes: {name}",
                target_type="prompts",
                target_id=key,
                before={"characters": len(was["body"] if was else built_in)},
                after={"characters": len(text), "version": version},
                conn=conn,
            )
    config_store.invalidate(ctx.source_key)
    return {"ok": True, "changed": version is not None, "version": version}


@router.delete("/instructions/{key}")
async def use_built_in(key: str, ctx: CtxDep):
    ctx.need("prompts")
    _layer(key)
    name = _name(key, await _org(ctx))
    async with tx(ctx) as conn:
        n = await reset_to_built_in(conn, key)
        if n:
            await log_event(
                ctx,
                "instructions",
                "text",
                f"Went back to the built-in AI notes: {name}",
                target_type="prompts",
                target_id=key,
                conn=conn,
            )
    config_store.invalidate(ctx.source_key)
    return {"ok": True, "changed": bool(n)}
