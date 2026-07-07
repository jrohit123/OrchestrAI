from app.db import fetch_all

SECTION_LABELS = {"reports": "📊 Reports", "create": "✍️ Create", "other": "⚙️ More"}
SECTION_ORDER  = ["reports", "create", "other"]

SYSTEM_ROWS = [  # the only non-DB rows; always last section
    {"id": "sys:status", "title": "My Status",  "description": "Pending draft & approvals"},
    {"id": "sys:cancel", "title": "Cancel",     "description": "Cancel current draft"},
    {"id": "sys:help",   "title": "Help",       "description": "How to use this"},
]

async def get_menu_workflows(org_id: str, user: dict) -> list[dict]:
    rows = await fetch_all("""
        SELECT intent_key, name, command_description, menu_section, slash_command, workflow_type
        FROM workflows
        WHERE org_id = $1 AND is_active = true
        ORDER BY menu_section, name
    """, org_id)
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
    # WhatsApp hard limit: 10 rows total. Reserve slots for system rows.
    used = sum(len(s["rows"]) for s in sections)
    budget = 10 - used
    sys_rows = SYSTEM_ROWS[:max(budget, 1)]
    sections.append({"title": "⚙️ More", "rows": sys_rows})
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
