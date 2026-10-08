"""Small helpers shared by the QA tests."""

import asyncio


async def count(w, sql: str, *args, kind: str | None = None) -> int:
    row = await w.one(sql, *args, kind=kind)
    return int(row["n"])


async def notes(w, title: str) -> int:
    """How many rows the qa_note workflows wrote with this title."""
    return await count(
        w, "SELECT count(*) AS n FROM routing_rules WHERE name = $1", title
    )


async def open_drafts(w, name: str) -> int:
    u = await w.user(name)
    return await count(
        w,
        "SELECT count(*) AS n FROM user_drafts WHERE user_id = $1 AND stage NOT IN ('done', 'cancelled')",
        u["user_id"],
    )


async def pending_approval_ids(w) -> list[str]:
    rows = await w.sql(
        "SELECT id FROM pending_approvals WHERE status = 'pending' ORDER BY created_at"
    )
    return [str(r["id"]) for r in rows]


def phone_of(w, name: str) -> str:
    return getattr(w.ids, f"phone_{name}")


async def say_all(w, *turns):
    """Several chat turns at the same moment: (phone, text) pairs, or (phone, text, msg_type)."""
    return await asyncio.gather(*[w.say(*t) for t in turns])
