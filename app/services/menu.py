from app.db import fetch_all

SECTION_LABELS = {"reports": "📊 Reports", "create": "✍️ Create", "other": "⚙️ More"}
SECTION_ORDER  = ["reports", "create", "other"]

async def get_menu_workflows(org_id: str, user: dict) -> list[dict]:
    rows = await fetch_all("""
        SELECT intent_key, name, command_description, menu_section, slash_command, workflow_type
        FROM workflows
        WHERE org_id = $1 AND is_active = true
        ORDER BY menu_section, name
    """, org_id, source_key=user["source_key"])
    perms = set(user.get("permissions", []))
    return [dict(r) for r in rows if r["intent_key"] in perms]

async def build_menu_sections(org_id: str, user: dict) -> list[dict]:
    allowed = await get_menu_workflows(org_id, user)
    grouped: dict[str, list] = {}
    for r in allowed:
        grouped.setdefault(r["menu_section"] or "other", []).append({
            "id": r["intent_key"],
            "title": r["name"][:24],
            "description": (r["command_description"] or "")[:72],
        })
    sections = [{"title": SECTION_LABELS.get(k, k.title()), "rows": grouped[k]}
                for k in SECTION_ORDER if k in grouped]
    # My Status / Cancel / Help used to be appended here as a fixed
    # non-DB "⚙️ More" section — always shown regardless of what's actually
    # configured for this org. Removed so the menu only ever lists what's
    # really in the workflows table; those three stay reachable exactly as
    # they were before (typing "status"/"cancel"/"help", or the sys:* row
    # id if a client still sends one — see handle_system_row in webhook.py),
    # just no longer force-listed as if they were workflows.
    # WhatsApp hard limit: 10 rows total across all sections.
    total = sum(len(s["rows"]) for s in sections)
    if total > 10:
        overflow = total - 10
        for s in reversed(sections):
            if overflow <= 0:
                break
            cut = min(overflow, len(s["rows"]))
            s["rows"] = s["rows"][:len(s["rows"]) - cut]
            overflow -= cut
        sections = [s for s in sections if s["rows"]]
    return sections

async def resolve_slash_command(org_id: str, user: dict, cmd: str) -> dict | None:
    """'/quo' → the quotation workflow. Exact match first, then unique prefix."""
    cmd = cmd.lstrip("/").lower().split()[0] if cmd.strip("/") else ""
    if not cmd:
        return None
    allowed = await get_menu_workflows(org_id, user)
    exact = [w for w in allowed if w["slash_command"] == cmd]
    if exact:
        return exact[0]
    prefix = [w for w in allowed if (w["slash_command"] or "").startswith(cmd)]
    return prefix[0] if len(prefix) == 1 else None
