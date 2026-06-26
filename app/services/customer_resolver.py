"""
Customer DB lookup for read agent tools — no keyword lists.
"""
from app.db import fetch_all


async def search_customers(org_id: str, hint: str, limit: int = 10) -> list[dict]:
    if not hint or len(hint.strip()) < 2:
        return []
    hint = hint.strip()
    rows = await fetch_all("""
        SELECT id, name, city, credit_limit
        FROM customers
        WHERE org_id = $1 AND name ILIKE $2
        ORDER BY name
        LIMIT $3
    """, org_id, f"%{hint}%", limit)
    return [dict(r) for r in rows]


def format_disambiguation_prompt(hint: str, matches: list[dict]) -> str:
    lines = [
        f"🤔 *{len(matches)} customers* match *{hint}*. Which one?",
        "",
    ]
    for i, c in enumerate(matches, 1):
        city = f" ({c['city']})" if c.get("city") else ""
        lines.append(f"*{i}.* {c['name']}{city}")
    lines.append("")
    lines.append("_Reply with a number, full name, or ask for all matching customers._")
    return "\n".join(lines)
