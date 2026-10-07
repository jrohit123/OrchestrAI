"""The AI notes screen: the written text the chat bot's AI follows, in three layers that are put
one after the other (see app/services/prompt_loader.py):

  1. agent.shared    how to behave, ask and answer; the same starting point for every client
  2. agent.industry  words and habits of this kind of business
  3. agent.client    local facts about this one organisation

and, on its own, the reply style (agent.reply_style): how the AI words a list of results.

What the AI is also told on every turn (today's date, the person's role, the flows they may start,
the tables it may read) is filled in by the system and is not written here.

The text in use is the strongest of these: the organisation's own (scope 'tenant'), its industry's
(scope 'pack'), the standard one stored in its database (scope 'global'), the one built into the
code. The dashboard changes only the first. A saved text is a new version of one row in `prompts`
(scope 'tenant'); older versions stay, so the history only grows and "go back" is just saving an
old text again. Going back to the standard text switches the saved versions off instead of deleting
them. The AI reads the newest active version (config_store.prompt), so a save applies at once on
the copy of the app that saved it, and within a minute on any other.
"""

import string
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
    0.3  # a new text this much shorter than the standard one is worth a warning
)

_OWN = "scope = 'tenant' AND scope_ref = ''"
# The text without the organisation's own version: its industry's, else the shared one that is
# stored in the database ($1 = the key, $2 = the industry).
_STANDARD = (
    "SELECT body FROM prompts WHERE key = $1 AND is_active AND ("
    "(scope = 'pack' AND scope_ref = $2 AND key = 'agent.industry') "
    "OR (scope = 'global' AND scope_ref = '')) "
    "ORDER BY CASE scope WHEN 'pack' THEN 0 ELSE 1 END, version DESC LIMIT 1"
)

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

# Texts that are not one of the layers: the AI is given them on their own, not in the order it reads
# the layers, so the screen shows them apart.
REPLY_STYLE = prompt_loader.REPLY_STYLE_KEY
EXTRAS: dict[str, tuple[str, str]] = {
    REPLY_STYLE: (
        "How lists and amounts are worded",
        (
            "How the AI words a list of results, like a stock list or a list of cases: amounts, "
            "bold text, how long a line may be. Keep {raw_data}: it is where the results go."
        ),
    ),
}
# what the reply style may use: name -> what it is (the same names agent._llm_format_report fills in)
REPLY_VALUES = {
    "workflow_name": "the name of the flow",
    "glossary_json": "the flow's own words",
    "raw_data": "the results to word",
}


def _layer(key: str) -> tuple[str, str]:
    if key in LAYERS:
        return LAYERS[key]
    if key in EXTRAS:
        return EXTRAS[key]
    raise HTTPException(404, "There is no such set of instructions.")


def _name(key: str, org: dict) -> str:
    """The text's name in this organisation's words, e.g. "About housing society"."""
    industry = (org.get("industry") or "this kind of business").lower()
    return _layer(key)[0].format(
        industry=industry.replace("_", " ").replace("-", " "),
        org=org.get("name") or "this organisation",
    )


def _check_reply_style(text: str, problems: list[str], warnings: list[str]) -> None:
    """The reply style is filled in with {names}: refuse what would not fill in, and a text that
    leaves out the results (the AI would have nothing to word)."""
    used: set[str] = set()
    bad = False
    try:
        for _, field, spec, conversion in string.Formatter().parse(text):
            if field is None:
                continue
            if spec or conversion:
                problems.append("Only plain names go between { and }, like {raw_data}.")
                bad = True
            elif field not in REPLY_VALUES:
                known = ", ".join("{" + n + "}" for n in REPLY_VALUES)
                problems.append(
                    f"{{{field}}} is not something this text knows. You can use: {known}."
                )
                bad = True
            else:
                used.add(field)
    except ValueError:
        problems.append(
            "A { or } is not closed. Write { and } only around a name, like {raw_data}."
        )
        return
    if bad:
        return
    if "raw_data" not in used:
        problems.append(
            "The text has to keep {raw_data}: it is where the results go, and without it the AI "
            "is never given them."
        )
    for name in ("workflow_name", "glossary_json"):
        if name not in used:
            warnings.append(
                f"This text does not use {{{name}}} ({REPLY_VALUES[name]}), so the AI will not see it."
            )


def check(key: str, text: str, standard: str) -> dict[str, Any]:
    """What is wrong with this text, in plain words. `problems` stop a save; `warnings` do not.
    `standard` is the text without the organisation's own version."""
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
            "This text cannot be empty. Use the standard text to go back to the original."
        )
    if text.strip() and len(standard) > 500 and len(text) < len(standard) * SHORT_AFTER:
        warnings.append(
            f"This is much shorter than the standard text ({len(text):,} against "
            f"{len(standard):,} characters). The chat bot will lose guidance it has today."
        )
    if key == REPLY_STYLE and text.strip():
        _check_reply_style(text, problems, warnings)
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


async def standard_text(conn, key: str, pack: str, built_in: str) -> str:
    """What the text is without the organisation's own version: its industry's or the shared one
    stored in the database, else the one built into the code."""
    row = await conn.fetchrow(_STANDARD, key, pack)
    return row["body"] if row else built_in


async def save_version(
    conn, key: str, text: str, standard: str, note: str | None, actor: str
) -> int | None:
    """Save `text` as the newest version. Returns its number, 0 when it went back to the standard
    text, or None when nothing changed (the text is what is already in use)."""
    current = await newest_own(conn, key)
    if text == (current["body"] if current else standard):
        return None
    if text == standard:  # the same words as the standard text: just use that again
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
        dump(sorted(REPLY_VALUES) if key == REPLY_STYLE else []),
        note,
        actor,
    )
    return version


async def reset_to_built_in(conn, key: str) -> int:
    """Switch off every saved version of one text, so the standard text is used again. Nothing is
    deleted. Returns how many were switched off."""
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


async def _standard(ctx, org: dict, key: str) -> str:
    """The text without the organisation's own version, read outside a transaction."""
    built_in = prompt_loader.built_in(org).get(key, "")
    if not ctx.caps.get("prompts"):
        return built_in
    row = await fetch_one(
        _STANDARD, key, prompt_loader.industry_of(org), source_key=ctx.source_key
    )
    return row["body"] if row else built_in


@router.get("/instructions")
async def list_instructions(ctx: CtxDep):
    org = await _org(ctx)
    ready = bool(ctx.caps.get("prompts"))
    pack = prompt_loader.industry_of(org)
    built_in = prompt_loader.built_in(org)
    found: dict[tuple[str, str], dict] = {}
    if ready:
        got = rows(
            await fetch_all(
                "SELECT DISTINCT ON (key, scope) key, scope, version, body, created_at, created_by "
                "FROM prompts WHERE is_active AND key = ANY($1) AND ("
                "(scope = 'tenant' AND scope_ref = '') "
                "OR (scope = 'pack' AND scope_ref = $2 AND key = 'agent.industry') "
                "OR (scope = 'global' AND scope_ref = '')) "
                "ORDER BY key, scope, version DESC",
                [*LAYERS, *EXTRAS],
                pack or "",
                source_key=ctx.source_key,
            )
        )
        found = {(r["key"], r["scope"]): r for r in got}

    def item(key: str, about: str) -> dict:
        own = found.get((key, "tenant"))
        pack_row = found.get((key, "pack"))
        standard = pack_row or found.get((key, "global"))
        used = own or standard
        if own:
            source = "own"
        elif pack_row:
            source = "industry"
        elif standard:
            source = "shared"
        else:
            source = "built_in"
        return {
            "key": key,
            "name": _name(key, org),
            "about": about,
            "text": used["body"] if used else built_in.get(key, ""),
            "built_in": built_in.get(key, ""),
            "standard": standard["body"] if standard else built_in.get(key, ""),
            "source": source,
            "version": used["version"] if used else None,
            "updated_at": used["created_at"] if used else None,
            "updated_by": used["created_by"] if used else None,
            "can_be_empty": key in CAN_BE_EMPTY,
        }

    return {
        "ready": ready,
        "layers": [item(key, about) for key, (_, about) in LAYERS.items()],
        "extras": [
            item(key, about) | {"values": REPLY_VALUES}
            for key, (_, about) in EXTRAS.items()
        ],
    }


@router.get("/instructions/assembled")
async def assembled(ctx: CtxDep):
    """The layers put together, exactly as the chat bot's AI receives them."""
    org = await _org(ctx)
    text = await prompt_loader.load_domain_prompt(org, ctx.source_key)
    return {"text": text, "characters": len(text), "lines": len(text.splitlines())}


@router.post("/instructions/{key}/check")
async def check_text(key: str, body: TextBody, ctx: CtxDep):
    _layer(key)
    org = await _org(ctx)
    return check(key, body.text, await _standard(ctx, org, key))


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
    standard = await _standard(ctx, org, key)
    text = body.text.strip()
    found = check(key, text, standard)
    if found["problems"]:
        raise HTTPException(400, " ".join(found["problems"]))
    async with tx(ctx) as conn:
        was = await newest_own(conn, key)
        version = await save_version(conn, key, text, standard, body.note, ctx.actor)
        if version is not None:
            await log_event(
                ctx,
                "instructions",
                "text",
                f"Changed the AI notes: {name}"
                if version
                else f"Went back to the standard text: {name}",
                target_type="prompts",
                target_id=key,
                before={"characters": len(was["body"] if was else standard)},
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
                f"Went back to the standard text: {name}",
                target_type="prompts",
                target_id=key,
                conn=conn,
            )
    config_store.invalidate(ctx.source_key)
    return {"ok": True, "changed": bool(n)}
