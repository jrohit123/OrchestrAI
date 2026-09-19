import hmac
import json
import re
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import required
from app.db import execute, fetch_all, fetch_one, get_all_source_keys
from app.logging_config import get_context_logger
from app.services.json_utils import parse_jsonb as _parse_jsonb

logger = get_context_logger(__name__)
router = APIRouter()

ADMIN_TOKEN = required("ADMIN_TOKEN")


def _check_token(request: Request):
    # Currently unused — no auth on the admin panel for now (multiple orgs,
    # not yet production-facing). Left in place, not deleted, so it's a
    # one-line change to re-enable per-request auth later rather than
    # rebuilding the mechanism from scratch.
    token = request.headers.get("X-Admin-Token")
    if not token or not hmac.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _resolve_source_key(org_slug: str) -> str:
    """
    The URL path segment IS the source_key — data_sources is already the
    single source of truth for which orgs exist (routing_db), so there's no
    separate slug-to-org mapping to maintain. Adding a new org later means
    zero code changes here; it's just another row in data_sources.
    """
    valid_keys = await get_all_source_keys()
    if org_slug not in valid_keys:
        raise HTTPException(status_code=404, detail=f"Unknown org '{org_slug}'")
    return org_slug


@router.get("/admin/{org_slug}", response_class=HTMLResponse)
async def admin_page(org_slug: str):
    await _resolve_source_key(org_slug)  # 404s on an unknown org
    return HTMLResponse(content=_build_html(), media_type="text/html; charset=utf-8")


# ── Dashboard stat cards — config-driven, zero business-table hardcoding ──
#
# There is no code here that knows "jewellery orgs have invoices/customers"
# or "housing societies have cases/residents". A card is entirely described
# by orgs.settings->'dashboard_stats' (same JSONB config pattern already used
# by case_reminders in scheduler/jobs.py) and every table/column name in it
# is checked against the org's OWN live schema before it ever reaches SQL —
# same allowlist step_interpreter.py's write path already trusts, reused
# here rather than re-invented.
#
# Example config, set once per org as data (see backfill note below):
#   {"dashboard_stats": {
#     "cards": [
#       {"key": "total_invoices",  "label": "Paid Invoices",  "table": "invoices",
#        "agg": "count", "where": {"status": "paid"}},
#       {"key": "total_amount",    "label": "Total Revenue",  "table": "invoices",
#        "agg": "sum", "column": "amount", "where": {"status": "paid"},
#        "format": "currency_inr", "color": "#16a34a"},
#       {"key": "pending_invoices","label": "Pending Invoices","table": "invoices",
#        "agg": "count", "where": {"status": "pending"}, "color": "#f59e0b"},
#       {"key": "total_customers", "label": "Customers",       "table": "customers",
#        "agg": "count", "color": "#3b82f6"}
#     ],
#     "low_stock": {"label": "Low Stock Alert", "table": "inventory",
#                    "qty_column": "qty", "reorder_column": "reorder_level",
#                    "display_columns": ["name", "qty", "reorder_level"]}
#   }}
# label/format/color are cosmetic only (format: "currency_inr" | "number",
# default "number") — the frontend renders whatever cards/columns are given,
# it does not know their names in advance. An org with no dashboard_stats
# config simply gets no stat cards / no low stock table — same "null means
# not tracked, never a misleading fake zero" rule the frontend already
# honours.


async def _compute_dashboard_stats(
    cfg: dict, org_id: str, source_key: str
) -> list | None:
    from app.services.step_interpreter import (
        StepError,
        _load_schema_allowlist,
        _validate_identifier,
    )

    cards = cfg.get("cards") or []
    if not cards:
        return None

    allowlist = await _load_schema_allowlist(source_key)
    out: list = []
    for card in cards:
        try:
            table = card["table"]
            key = card["key"]
            agg = card.get("agg", "count")
            column = card.get("column")
            where = card.get("where") or {}

            _validate_identifier(table, "table name")
            if table not in allowlist:
                continue
            if column:
                _validate_identifier(column, "column name")
                if column not in allowlist[table]:
                    continue
            for col in where:
                _validate_identifier(col, "column name")
                if col not in allowlist[table]:
                    raise StepError(f"unknown column '{col}' on '{table}'")

            where_cols = list(where.keys())
            where_clause = " AND ".join(
                f"{c} = ${i + 2}" for i, c in enumerate(where_cols)
            )
            where_sql = (
                f"WHERE org_id = $1 AND {where_clause}"
                if where_clause
                else "WHERE org_id = $1"
            )

            if agg == "sum" and column:
                sql = (
                    f"SELECT COALESCE(SUM({column}), 0) AS val FROM {table} {where_sql}"
                )
            else:
                sql = f"SELECT COUNT(*) AS val FROM {table} {where_sql}"

            row = await fetch_one(sql, org_id, *where.values(), source_key=source_key)
            value = row["val"] if row else 0
            # Cards are returned as a self-describing list (key/label/value/
            # format/color), not a bare {key: value} dict — so the frontend
            # renders whatever cards this org configured with zero hardcoded
            # knowledge of what a "stat card" for this org looks like.
            out.append(
                {
                    "key": key,
                    "label": card.get("label") or key.replace("_", " ").title(),
                    "value": value,
                    "format": card.get("format", "number"),
                    "color": card.get("color"),
                }
            )
        except (KeyError, StepError) as e:
            logger.warning(f"dashboard_stats: skipping malformed card {card}: {e}")
            continue

    return out or None


async def _compute_low_stock(cfg: dict, org_id: str, source_key: str) -> dict | None:
    from app.services.step_interpreter import (
        StepError,
        _load_schema_allowlist,
        _validate_identifier,
    )

    ls = cfg.get("low_stock")
    if not ls:
        return None

    try:
        table = ls["table"]
        qty_col = ls["qty_column"]
        reorder_col = ls["reorder_column"]
        display_cols = ls.get("display_columns") or [qty_col, reorder_col]

        allowlist = await _load_schema_allowlist(source_key)
        _validate_identifier(table, "table name")
        if table not in allowlist:
            return None
        for c in {qty_col, reorder_col, *display_cols}:
            _validate_identifier(c, "column name")
            if c not in allowlist[table]:
                return None

        cols_sql = ", ".join(display_cols)
        rows = await fetch_all(
            f"SELECT {cols_sql} FROM {table} WHERE org_id = $1 AND {qty_col} <= {reorder_col}",
            org_id,
            source_key=source_key,
        )
        # Row-shaped output the frontend renders generically: a title,
        # ordered {key, label} columns, and rows keyed by those same column
        # names — never a hardcoded "name/qty/reorder_level" assumption.
        return {
            "title": ls.get("label", "Low Stock Alert"),
            "columns": [
                {"key": c, "label": c.replace("_", " ").title()} for c in display_cols
            ],
            "rows": [dict(r) for r in rows],
        }
    except (KeyError, StepError) as e:
        logger.warning(
            f"dashboard_stats.low_stock: skipping malformed config {ls}: {e}"
        )
        return None


@router.get("/admin/{org_slug}/api/data")
async def admin_data(org_slug: str):
    source_key = await _resolve_source_key(org_slug)

    org = await fetch_one(
        "SELECT id, name, settings FROM orgs WHERE is_active = true LIMIT 1",
        source_key=source_key,
    )
    if not org:
        return {"error": "No active org found"}

    org_dict = dict(org)
    org_settings = _parse_jsonb(org_dict.pop("settings", None), {})
    org_id = str(org["id"])

    workflows = await fetch_all(
        """
        SELECT id, name, intent_key, is_active, otp_required,
               otp_threshold, approval_threshold, gates, last_run, workflow_type
        FROM workflows WHERE org_id = $1
        ORDER BY created_at
    """,
        org_id,
        source_key=source_key,
    )

    # Dashboard stat cards and the low-stock table are entirely config-driven
    # (orgs.settings->'dashboard_stats') — see the helpers above. An org that
    # hasn't configured this simply gets no cards, never a guess at what
    # tables it might have.
    dashboard_cfg = org_settings.get("dashboard_stats") or {}
    stats = await _compute_dashboard_stats(dashboard_cfg, org_id, source_key)
    low_stock = await _compute_low_stock(dashboard_cfg, org_id, source_key)

    workflows_out = []
    for w in workflows:
        wd = dict(w)
        wd["gates"] = _parse_jsonb(wd.get("gates"), [])
        workflows_out.append(wd)

    return {
        "org": org_dict,
        "workflows": workflows_out,
        # null (not zeros) when this org has no dashboard_stats config —
        # "0 invoices" and "this org doesn't track invoices" are different
        # facts, and the frontend hides the stat cards entirely on null
        # instead of showing a misleading Rs.0 for an org that doesn't
        # track that metric at all.
        "stats": stats,
        "low_stock": low_stock,
        # Recent Activity has its own paginated/filtered endpoint now
        # (GET .../api/activity) — no longer bundled in here.
    }


@router.get("/admin/{org_slug}/api/activity")
async def admin_activity(
    org_slug: str,
    user_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    outcome: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 10,
):
    """
    Paginated, filterable Recent Activity feed. intent_key is only ever
    'agent'/'menu' for ordinary chat turns (the real content is input_text/
    response_text) — anything else is a genuine workflow name, shown as-is;
    'agent'/'menu' are relabelled "Chat" since they say nothing useful.
    """
    source_key = await _resolve_source_key(org_slug)
    org = await fetch_one(
        "SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key
    )
    if not org:
        return {"error": "No active org found"}
    org_id = str(org["id"])

    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    offset = (page - 1) * page_size

    where = "a.org_id = $1"
    params: list = [org_id]

    if user_id:
        params.append(user_id)
        where += f" AND a.user_id = ${len(params)}::uuid"
    if date_from:
        params.append(date_from)
        where += f" AND a.created_at >= ${len(params)}::date"
    if date_to:
        params.append(date_to)
        where += f" AND a.created_at < (${len(params)}::date + interval '1 day')"
    if outcome:
        params.append(outcome)
        where += f" AND a.outcome = ${len(params)}"
    if search:
        params.append(f"%{search}%")
        where += f" AND (a.input_text ILIKE ${len(params)} OR a.response_text ILIKE ${len(params)})"

    total_row = await fetch_one(
        f"SELECT COUNT(*) AS n FROM audit_log a WHERE {where}",
        *params,
        source_key=source_key,
    )

    rows = await fetch_all(
        f"""
        SELECT a.id, a.created_at, a.user_id, u.name AS user_name, a.intent_key,
               a.input_text, a.response_text, a.outcome, a.session_id
        FROM audit_log a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE {where}
        ORDER BY a.created_at DESC
        LIMIT {page_size} OFFSET {offset}
    """,
        *params,
        source_key=source_key,
    )

    users = await fetch_all(
        """
        SELECT DISTINCT u.id, u.name
        FROM audit_log a JOIN users u ON u.id = a.user_id
        WHERE a.org_id = $1
        ORDER BY u.name
    """,
        org_id,
        source_key=source_key,
    )

    out_rows = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["user_id"] = str(d["user_id"]) if d["user_id"] else None
        d["workflow"] = (
            d["intent_key"] if d["intent_key"] not in ("agent", "menu") else "Chat"
        )
        out_rows.append(d)

    return {
        "rows": out_rows,
        "total": total_row["n"] if total_row else 0,
        "page": page,
        "page_size": page_size,
        "users": [{"id": str(u["id"]), "name": u["name"]} for u in users],
    }


@router.get("/admin/{org_slug}/api/activity/session")
async def admin_activity_session(org_slug: str, session_id: str):
    """Full transcript for one conversation — every audit_log row sharing
    the same session_id (the exact key Redis already keys this chat's
    session by), oldest first so it reads top-to-bottom like a chat."""
    source_key = await _resolve_source_key(org_slug)
    rows = await fetch_all(
        """
        SELECT a.created_at, u.name AS user_name, a.input_text, a.response_text
        FROM audit_log a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE a.session_id = $1
        ORDER BY a.created_at ASC
    """,
        session_id,
        source_key=source_key,
    )
    return {"rows": [dict(r) for r in rows]}


@router.post("/admin/{org_slug}/api/workflow/{workflow_id}/toggle")
async def toggle_otp(org_slug: str, workflow_id: str):
    source_key = await _resolve_source_key(org_slug)
    row = await fetch_one(
        "SELECT otp_required, org_id FROM workflows WHERE id = $1",
        workflow_id,
        source_key=source_key,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    new_val = not row["otp_required"]
    await execute(
        "UPDATE workflows SET otp_required = $1 WHERE id = $2",
        new_val,
        workflow_id,
        source_key=source_key,
    )
    return {"otp_required": new_val}


@router.post("/admin/{org_slug}/api/workflow/{workflow_id}/threshold")
async def update_threshold(org_slug: str, workflow_id: str, request: Request):
    body = await request.json()
    if body.get("threshold") is None:
        raise HTTPException(status_code=400, detail="threshold required")
    threshold = float(body["threshold"])
    source_key = await _resolve_source_key(org_slug)
    await execute(
        "UPDATE workflows SET otp_threshold = $1 WHERE id = $2",
        threshold,
        workflow_id,
        source_key=source_key,
    )
    return {"otp_threshold": threshold}


@router.post("/admin/{org_slug}/api/workflow/{workflow_id}/approval_threshold")
async def update_approval_threshold(org_slug: str, workflow_id: str, request: Request):
    body = await request.json()
    if body.get("threshold") is None:
        raise HTTPException(status_code=400, detail="threshold required")
    threshold = float(body["threshold"])
    source_key = await _resolve_source_key(org_slug)
    await execute(
        "UPDATE workflows SET approval_threshold = $1 WHERE id = $2",
        threshold,
        workflow_id,
        source_key=source_key,
    )
    return {"approval_threshold": threshold}


@router.get("/admin/{org_slug}/api/roles")
async def get_roles(org_slug: str):
    source_key = await _resolve_source_key(org_slug)
    roles = await fetch_all(
        "SELECT name FROM roles ORDER BY name", source_key=source_key
    )
    return [{"name": r["name"], "selected": r["name"] == "owner"} for r in roles]


@router.get("/admin/{org_slug}/api/security")
async def get_security_settings(org_slug: str):
    source_key = await _resolve_source_key(org_slug)
    org = await fetch_one(
        "SELECT id, session_ttl_minutes FROM orgs WHERE is_active = true LIMIT 1",
        source_key=source_key,
    )
    return {
        "session_ttl_minutes": org["session_ttl_minutes"] or 480,
        "org_id": str(org["id"]),
    }


@router.post("/admin/{org_slug}/api/security/ttl")
async def update_session_ttl(org_slug: str, request: Request):
    body = await request.json()
    minutes = int(body.get("minutes", 480))
    if minutes < 5 or minutes > 10080:  # 5 min to 7 days
        raise HTTPException(
            status_code=400, detail="TTL must be between 5 and 10080 minutes"
        )
    source_key = await _resolve_source_key(org_slug)
    org_id = body.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id required")
    await execute(
        "UPDATE orgs SET session_ttl_minutes = $1 WHERE id = $2",
        minutes,
        org_id,
        source_key=source_key,
    )
    return {"session_ttl_minutes": minutes}


@router.get("/admin/{org_slug}/api/settings/logo")
async def get_org_logo(org_slug: str):
    source_key = await _resolve_source_key(org_slug)
    org = await fetch_one(
        "SELECT id, logo_url FROM orgs WHERE is_active = true LIMIT 1",
        source_key=source_key,
    )
    if not org:
        raise HTTPException(status_code=404, detail="No active org")
    return {"logo_url": org["logo_url"], "org_id": str(org["id"])}


@router.post("/admin/{org_slug}/api/settings/logo")
async def upload_org_logo(org_slug: str, request: Request):
    # Deliberately separate from the workflow-builder chat's PDF attach —
    # that upload is scoped to whichever single workflow is being built and
    # is ONLY ever a reference layout for pdf_engine.py, never persisted
    # data. A logo is an org-wide setting with nothing to do with any one
    # workflow, so it gets its own small endpoint here instead of being
    # bolted onto the chat's file-attach flow.
    source_key = await _resolve_source_key(org_slug)
    form = await request.form()
    upload = form.get("logo_file")
    if not upload:
        raise HTTPException(status_code=400, detail="logo_file is required")

    content_type = getattr(upload, "content_type", "") or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Logo must be an image file")

    image_bytes = await upload.read()
    if len(image_bytes) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Logo image is too large (max 2MB)")

    # No external file storage in this app — a logo is small enough (a few
    # KB, capped at 2MB above) to store inline as a data URI. pdf_engine.py
    # injects it via a plain <img src="..."> tag, which accepts a data URI
    # exactly the same as a real hosted URL — no other code needs to care
    # which kind of value is in this column.
    import base64

    data_uri = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode()}"

    org = await fetch_one(
        "SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key
    )
    if not org:
        raise HTTPException(status_code=404, detail="No active org")

    await execute(
        "UPDATE orgs SET logo_url = $1 WHERE id = $2",
        data_uri,
        str(org["id"]),
        source_key=source_key,
    )
    return {"logo_url": data_uri}


@router.post("/admin/{org_slug}/api/sessions/clear")
async def admin_clear_sessions(org_slug: str):
    from app.redis_client import clear_all_sessions

    source_key = await _resolve_source_key(org_slug)
    org = await fetch_one(
        "SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key
    )
    await clear_all_sessions(str(org["id"]))
    return {"cleared": True, "message": "All sessions cleared"}


@router.post("/admin/{org_slug}/api/gst-rate")
async def update_gst_rate(org_slug: str, request: Request):
    body = await request.json()
    if body.get("gst_rate") is None:
        raise HTTPException(status_code=400, detail="gst_rate required")
    gst = float(body["gst_rate"])
    source_key = await _resolve_source_key(org_slug)
    org_id = body.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id required")
    await execute(
        "UPDATE orgs SET gst_rate = $1 WHERE id = $2",
        gst,
        org_id,
        source_key=source_key,
    )
    return {"gst_rate": gst}


# â”€â”€ New endpoints: workflow detail, edit, delete, chat builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_JSONB_WORKFLOW_FIELDS = {
    "training_phrases": [],
    "entity_schema": {},
    "calc_rules": {},
    "steps": [],
    "sql_params_order": [],
    "business_glossary": {},
    "pdf_config": None,
    "gates": [],
}


@router.get("/admin/{org_slug}/api/workflow/{workflow_id}/detail")
async def get_workflow_detail(org_slug: str, workflow_id: str):
    source_key = await _resolve_source_key(org_slug)
    row = await fetch_one(
        "SELECT * FROM workflows WHERE id = $1", workflow_id, source_key=source_key
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    wd = dict(row)
    for field, default in _JSONB_WORKFLOW_FIELDS.items():
        if field in wd:
            wd[field] = _parse_jsonb(wd[field], default)
    granted = await fetch_all(
        "SELECT name FROM roles WHERE org_id = $1 AND $2 = ANY(permissions)",
        wd["org_id"],
        wd["intent_key"],
        source_key=source_key,
    )
    wd["granted_roles"] = [r["name"] for r in granted]
    return wd


@router.put("/admin/{org_slug}/api/workflow/{workflow_id}")
async def update_workflow(org_slug: str, workflow_id: str, request: Request):
    """
    Structural settings ONLY — name, description, active/inactive, gates
    (constraints), roles, trigger command. What the workflow actually DOES —
    steps, entity_schema, calc_rules — is edited exclusively through the
    chat builder now (see /workflow-builder/edit/{workflow_id}), never
    through this form-style endpoint: that's logic, not a setting, and
    editing it later is the same problem as authoring it, which chat already
    solves.
    """
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)

    existing = await fetch_one(
        "SELECT * FROM workflows WHERE id = $1", workflow_id, source_key=source_key
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Workflow not found")

    allowed = ["name", "description", "is_active", "gates", "slash_command"]
    jsonb_fields = {"gates"}

    if "gates" in body:
        from app.services.workflow_validator import validate_workflow_config

        problems = validate_workflow_config(
            {
                "workflow_type": existing["workflow_type"],
                "gates": body["gates"],
                # Same fix as the publish endpoint below: omitting steps here
                # reads as steps=[] every time, false-positiving on every
                # action-type workflow regardless of what it actually has.
                "steps": existing.get("steps"),
            }
        )
        if problems:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Constraints are inconsistent — not saved.",
                    "problems": problems,
                },
            )

    if "slash_command" in body:
        cmd = (body.get("slash_command") or "").strip().lstrip("/").lower()
        if not re.fullmatch(r"[a-z0-9_]{2,32}", cmd):
            raise HTTPException(
                status_code=400,
                detail="Command: 2-32 chars, lowercase letters/digits/_",
            )
        dupe = await fetch_one(
            "SELECT id FROM workflows WHERE org_id = $1 AND slash_command = $2 AND is_active = true AND id != $3",
            existing["org_id"],
            cmd,
            workflow_id,
            source_key=source_key,
        )
        if dupe:
            raise HTTPException(
                status_code=409, detail=f"Command '/{cmd}' is already in use"
            )
        body["slash_command"] = cmd

    sets, vals = [], []
    for field in allowed:
        if field in body:
            sets.append(f"{field} = ${len(vals) + 2}")
            val = body[field]
            if field in jsonb_fields:
                val = json.dumps(val) if not isinstance(val, str) else val
                sets[-1] = f"{field} = ${len(vals) + 2}::jsonb"
            vals.append(val)

    if sets:
        await execute(
            f"UPDATE workflows SET {', '.join(sets)} WHERE id = $1",
            workflow_id,
            *vals,
            source_key=source_key,
        )
    elif "roles" not in body:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "roles" in body:
        from app.services.workflow_publisher import sync_role_grants

        # Same readable_tables sync the publish endpoint does — ticking a
        # role checkbox here is a second, separate path to granting a
        # workflow (not just the chat builder's publish flow), and it needs
        # the same "also grant the tables this workflow touches" behavior
        # or a role ticked on here hits the exact same silent failure a
        # role granted via publish did before that fix.
        await sync_role_grants(
            existing["intent_key"],
            str(existing["org_id"]),
            body["roles"] or [],
            source_key,
            entity_schema=existing.get("entity_schema"),
            steps=existing.get("steps"),
        )

    return {"success": True}


@router.delete("/admin/{org_slug}/api/workflow/{workflow_id}")
async def delete_workflow(org_slug: str, workflow_id: str):
    source_key = await _resolve_source_key(org_slug)
    row = await fetch_one(
        "SELECT intent_key, org_id, steps FROM workflows WHERE id = $1",
        workflow_id,
        source_key=source_key,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    from app.services.workflow_publisher import sync_role_grants

    # desired_roles=[] revokes from every role — via sync_role_grants rather
    # than a bare array_remove so the sub-permissions this workflow's steps
    # required (see extract_required_permissions) get cleaned up too, not
    # just intent_key, while still protecting any of them still needed by
    # another active workflow.
    await sync_role_grants(
        row["intent_key"],
        str(row["org_id"]),
        [],
        source_key,
        steps=row.get("steps"),
    )
    await execute(
        "DELETE FROM workflows WHERE id = $1", workflow_id, source_key=source_key
    )
    return {"success": True, "deleted": row["intent_key"]}


@router.post("/admin/{org_slug}/api/workflow/validate")
async def validate_workflow_endpoint(org_slug: str, request: Request):
    """Lint a workflow config without saving — used by the Edit modal Validate button."""
    body = await request.json()
    from app.services.workflow_validator import validate_workflow_config

    problems = validate_workflow_config(body)
    return {"valid": len(problems) == 0, "problems": problems}


@router.get("/admin/{org_slug}/api/workflow-builder/preview-pdf/{draft_id}")
async def preview_workflow_pdf(org_slug: str, draft_id: str):
    """Generate a sample PDF from a compiled draft using placeholder data."""
    from fastapi.responses import Response as FastAPIResponse

    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft or not draft.get("pdf_config"):
        raise HTTPException(
            status_code=404, detail="Nothing to preview yet — compile first"
        )
    org = await fetch_one(
        "SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key
    )
    if not org:
        raise HTTPException(status_code=404, detail="No active org")
    from app.services.workflow_previewer import generate_preview_pdf

    try:
        pdf_bytes = await generate_preview_pdf(dict(draft), str(org["id"]), source_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {e}")
    return FastAPIResponse(content=pdf_bytes, media_type="application/pdf")


@router.post("/admin/{org_slug}/api/workflow-builder/clear-drafts")
async def clear_unfinished_drafts(org_slug: str):
    """
    Marks every 'chatting' (unfinished/stuck) workflow_drafts row for this
    org as 'abandoned' — the escape hatch for a draft left mid-conversation
    (a closed tab, a crashed session, an experiment that went nowhere) that
    would otherwise sit in list_existing_workflows' unfinished_drafts list
    forever and get offered back to the admin on every new chat. A status
    change, not a hard delete — workflow_drafts already has 'abandoned' in
    its own status enum for exactly this, so this stays consistent with the
    table's existing state machine instead of destroying rows.
    """
    source_key = await _resolve_source_key(org_slug)
    org = await fetch_one(
        "SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key
    )
    if not org:
        raise HTTPException(status_code=404, detail="No active org found")
    rows = await fetch_all(
        """
        UPDATE workflow_drafts SET status = 'abandoned', updated_at = now()
        WHERE org_id = $1 AND status = 'chatting'
        RETURNING id
    """,
        str(org["id"]),
        source_key=source_key,
    )
    return {"cleared": len(rows)}


@router.post("/admin/{org_slug}/api/workflow-builder/chat")
async def workflow_builder_chat(org_slug: str, request: Request):
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)
    org = await fetch_one(
        "SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key
    )
    if not org:
        raise HTTPException(status_code=404, detail="No active org found")
    org_id = str(org["id"])

    from app.services.workflow_builder_agent import run_builder_agent

    result = await run_builder_agent(
        message=body.get("message", ""),
        org_id=org_id,
        draft_id=body.get("draft_id"),
        attachment_b64=body.get("attachment"),
        pre_extracted_pdf=body.get("pdf_analysis"),  # pre-extracted from browser
        source_key=source_key,
    )
    return result


@router.post("/admin/{org_slug}/api/workflow-builder/edit/{workflow_id}")
async def start_edit_via_chat(org_slug: str, workflow_id: str):
    """
    Deterministic entry point for the "Edit the logic" button on a workflow's
    settings — creates a fresh draft pre-loaded from THIS specific workflow
    (by id, never guessed by an LLM matching on name) and returns a greeting
    so the builder chat can open already primed with the current state.
    """
    source_key = await _resolve_source_key(org_slug)
    wf = await fetch_one(
        "SELECT * FROM workflows WHERE id = $1", workflow_id, source_key=source_key
    )
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    from app.services.workflow_builder_agent import start_edit_draft

    result = await start_edit_draft(dict(wf), str(wf["org_id"]), source_key)
    return result


@router.post("/admin/{org_slug}/api/workflow-builder/pdf-extract")
async def extract_pdf_template_endpoint(org_slug: str, request: Request):
    form = await request.form()
    upload = form.get("pdf_file")
    doc_type_hint = form.get("doc_type_hint", "")
    if not upload:
        raise HTTPException(status_code=400, detail="pdf_file is required")
    pdf_bytes = await upload.read()
    from app.services.pdf_template_extractor import extract_pdf_template

    try:
        spec = await extract_pdf_template(pdf_bytes, doc_type_hint)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not analyze PDF: {e}")
    return spec


@router.get("/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/publish-info")
async def get_draft_publish_info(org_slug: str, draft_id: str):
    """Return data needed for the publish panel: summary, roles, prefill values, suggested command."""
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    org = await fetch_one(
        "SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key
    )
    if not org:
        raise HTTPException(status_code=404, detail="No active org")

    roles = await fetch_all(
        "SELECT name FROM roles WHERE org_id = $1 ORDER BY name",
        str(org["id"]),
        source_key=source_key,
    )

    # Suggest command from intent_key if not set
    suggested_cmd = (
        draft.get("slash_command") or draft.get("intent_key", "").replace("_", "")[:32]
    )

    gates = draft.get("gates") or []
    if isinstance(gates, str):
        try:
            gates = json.loads(gates)
        except (json.JSONDecodeError, TypeError):
            gates = []

    return {
        "draft_id": str(draft["id"]),
        "summary": draft.get("plain_english_summary"),
        "intent_key": draft.get("intent_key"),
        "workflow_type": draft.get("workflow_type"),
        "roles": [r["name"] for r in roles],
        "gates": gates,
        "prefill": {
            "slash_command": suggested_cmd,
        },
    }


@router.post("/admin/{org_slug}/api/workflow-builder/publish/{draft_id}")
async def publish_workflow_endpoint(org_slug: str, draft_id: str):
    """
    Publish a draft to live workflows. No request body — fields, constraints,
    who can use it, and the trigger command were all already gathered
    conversationally (see workflow_builder_agent.py). This click is the only
    thing that ever writes to the live `workflows` table; the LLM can't
    trigger it on its own (there's no publish tool in _TOOLS).

    Also the single path for republishing an EDITED existing workflow (the
    "Edit the logic" chat flow) — publish_draft's ON CONFLICT DO UPDATE
    upserts on intent_key, so this doubles as create-or-update.
    """
    source_key = await _resolve_source_key(org_slug)

    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft or draft["status"] != "ready_for_review":
        raise HTTPException(status_code=409, detail="Draft is not ready for review")

    org_id = str(draft["org_id"])
    gates = _parse_jsonb(draft.get("gates"), [])
    # Defense-in-depth: a malformed/corrupted gates value (e.g. from a stale
    # double-encoded row) must never crash this endpoint with a raw 500 —
    # iterating it below assumes a list of dicts. validate_workflow_config
    # already guards this same way; mirror it here since this loop runs
    # before that function ever sees the value.
    if not isinstance(gates, list):
        gates = []
    roles = draft.get("granted_roles") or []
    slash_command = draft.get("slash_command")

    valid_roles = {
        r["name"]
        for r in await fetch_all(
            "SELECT name FROM roles WHERE org_id = $1", org_id, source_key=source_key
        )
    }
    if not roles or not set(roles) <= valid_roles:
        raise HTTPException(
            422,
            f"Who can use this must be a non-empty subset of {sorted(valid_roles)} — "
            f"go back to chat and say who should be able to use it.",
        )

    # Structural gate validation (types, level ordering, etc.) — same checker
    # used at every other write path to workflows (see workflow_validator.py).
    from app.services.workflow_validator import validate_workflow_config

    gate_problems = validate_workflow_config(
        {
            "workflow_type": draft.get("workflow_type") or "action",
            "gates": gates,
            # steps must come along too — validate_workflow_config's action/steps
            # consistency check has no way to know steps[] is actually populated
            # if it's never in the spec it's given, and reads the omission as
            # "empty steps" every time, false-positiving on every action-type
            # publish regardless of what the draft actually contains. Found live:
            # this rejected a from-scratch action workflow (create_resident_record)
            # with a fully valid, non-empty steps[] already saved on the draft.
            "steps": draft.get("steps"),
        }
    )
    if gate_problems:
        raise HTTPException(
            422, {"error": "Constraints are inconsistent", "problems": gate_problems}
        )

    # Every role a gate names (approval level, or permission role_any_of) must
    # actually exist in this org — the structural checker above has no DB
    # access, so that reference check lives here instead.
    referenced_roles: set[str] = set()
    for g in gates:
        for lvl in g.get("levels") or []:
            if lvl.get("role"):
                referenced_roles.add(lvl["role"])
        for r in g.get("role_any_of") or []:
            referenced_roles.add(r)
    unknown_roles = referenced_roles - valid_roles
    if unknown_roles:
        raise HTTPException(
            422, f"Constraints reference unknown role(s): {sorted(unknown_roles)}"
        )

    if not slash_command:
        raise HTTPException(
            422,
            "No trigger command set yet — go back to chat and say what it should be.",
        )
    cmd = slash_command.strip().lstrip("/").lower()
    if not re.fullmatch(r"[a-z0-9_]{2,32}", cmd):
        raise HTTPException(422, "Command: 2-32 chars, lowercase letters/digits/_")

    # Check command uniqueness (excluding this same workflow, since editing
    # it via chat and republishing under the same command is expected)
    dupe = await fetch_one(
        "SELECT id FROM workflows WHERE org_id = $1 AND slash_command = $2 AND is_active = true AND intent_key != $3",
        org_id,
        cmd,
        draft.get("intent_key") or "",
        source_key=source_key,
    )
    if dupe:
        raise HTTPException(409, f"Command '/{cmd}' is already in use")

    from app.services.workflow_publisher import PublishConflict, publish_draft

    draft_dict = dict(draft)
    draft_dict["slash_command"] = cmd
    try:
        result = await publish_draft(draft_dict, org_id, source_key)
    except PublishConflict as e:
        # Someone else published a change to this same workflow while this
        # draft was being edited — see PublishConflict's docstring for why
        # this refuses instead of silently overwriting. 409, not 422: the
        # draft itself is fine, it's just stale relative to what's live now.
        from app.services.workflow_builder_agent import get_live_snapshot

        raise HTTPException(
            409,
            {
                "error": str(e),
                "current_version": e.current_version,
                "based_on_version": e.based_on_version,
                "live_snapshot": await get_live_snapshot(
                    org_id, e.intent_key, source_key
                ),
            },
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        # A bare 500 with no detail here means the admin (and whoever's
        # debugging this) has no idea what actually broke — log the full
        # traceback server-side and surface the real error message instead
        # of Starlette's generic "Internal Server Error".
        logger.error(f"publish_draft failed for draft {draft_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Publish failed: {type(e).__name__}: {e}")

    return {"ok": True, "workflow_id": result["workflow_id"]}


@router.get("/admin/{org_slug}/api/workflow-builder/drafts")
async def list_unfinished_drafts(org_slug: str):
    """
    Backs the dashboard's "Continue a draft" list — the fix for the gap
    that let "add a resident" get attempted from scratch four separate
    times: previously the only way to see an unfinished draft was an LLM
    happening to mention it mid-conversation, with no way to actually
    resume it. is_edit is based on based_on_version, not intent_key — a
    brand-new draft also gets an intent_key on its first compile, so
    intent_key alone can't tell "editing something live" apart from
    "already compiled once, still from scratch".
    """
    source_key = await _resolve_source_key(org_slug)
    org = await fetch_one(
        "SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key
    )
    if not org:
        raise HTTPException(status_code=404, detail="No active org found")
    rows = await fetch_all(
        """
        SELECT id, name, purpose, status, updated_at, raw_fields, granted_roles,
               gates, based_on_version
        FROM workflow_drafts
        WHERE org_id = $1 AND status IN ('chatting', 'ready_for_review')
        ORDER BY updated_at DESC
    """,
        str(org["id"]),
        source_key=source_key,
    )

    def _summarize(r):
        raw_fields = _parse_jsonb(r["raw_fields"], [])
        gates = _parse_jsonb(r["gates"], [])
        return {
            "id": str(r["id"]),
            "name": r["name"] or r["purpose"] or "(untitled)",
            "status": r["status"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "field_count": len(raw_fields),
            "has_roles": bool(r["granted_roles"]),
            "gate_count": len(gates),
            "is_edit": r["based_on_version"] is not None,
        }

    return {"drafts": [_summarize(r) for r in rows]}


@router.post("/admin/{org_slug}/api/workflow-builder/resume/{draft_id}")
async def resume_draft_endpoint(org_slug: str, draft_id: str):
    """Deterministic entry point for clicking "Continue" on a drafts-list row."""
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft or draft["status"] not in ("chatting", "ready_for_review"):
        raise HTTPException(
            status_code=404, detail="Draft not found or no longer active"
        )

    from app.services.workflow_builder_agent import resume_draft

    return await resume_draft(dict(draft), str(draft["org_id"]), source_key)


@router.post("/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/abandon")
async def abandon_one_draft(org_slug: str, draft_id: str):
    """
    Per-draft delete, backing the 🗑️ button in the drafts modal — same
    'abandoned' status change clear-drafts already does in bulk, just
    scoped to one row instead of every 'chatting' draft in the org. A
    status change, not a hard delete, consistent with how this table
    treats removal everywhere else (see clear_unfinished_drafts' own
    comment) — nothing here touches any live workflow.
    """
    source_key = await _resolve_source_key(org_slug)
    row = await fetch_one(
        "UPDATE workflow_drafts SET status = 'abandoned', updated_at = now() "
        "WHERE id = $1 AND status IN ('chatting', 'ready_for_review') RETURNING id",
        draft_id,
        source_key=source_key,
    )
    if not row:
        raise HTTPException(
            status_code=404, detail="Draft not found or already inactive"
        )
    return {"success": True}


async def _save_and_maybe_recompile(
    draft_id: str, org_id: str, source_key: str, was_compiled: bool, note: str
) -> dict:
    """
    Shared by the field and gate direct-edit endpoints below. If the draft
    had already been compiled once (status was 'ready_for_review'), the
    edit just invalidated that compile — gates/fields feed directly into
    the compiled steps[]/sql_template (see workflow_compiler.txt RULE 14;
    otp_gate/approval_gate are literal steps the compiler inserts, not
    independently enforced), so silently leaving the old compiled output in
    place would ship logic that doesn't match what the panel now shows.
    Recompiling here — synchronously, in the same request — means the admin
    never has to go back to chat to keep them in sync; the tradeoff is this
    call takes as long as any other compile (a few seconds), same as
    hitting compile_and_summarize from chat already does today.
    """
    from app.services.workflow_builder_agent import (
        append_draft_note,
        build_draft_recap,
        build_draft_state,
        compile_and_save,
    )

    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    draft = dict(draft)
    await append_draft_note(draft, note, source_key)

    result = {
        "draft_recap": build_draft_recap(draft),
        "draft_state": build_draft_state(draft),
        "ready_for_review": False,
        "summary_card": None,
    }
    if was_compiled:
        compiled = await compile_and_save(draft_id, org_id, source_key)
        fresh = dict(
            await fetch_one(
                "SELECT * FROM workflow_drafts WHERE id = $1",
                draft_id,
                source_key=source_key,
            )
        )
        result["draft_recap"] = build_draft_recap(fresh)
        result["draft_state"] = build_draft_state(fresh)
        if "error" in compiled:
            result["error"] = compiled["error"]
        else:
            result["summary_card"] = compiled["summary"]
            result["ready_for_review"] = True
    return result


@router.post("/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/field")
async def edit_draft_field(org_slug: str, draft_id: str, request: Request):
    """
    Direct panel edit — add/remove/rename a field, or flip required/optional
    — without going back to the chat box. Always writes through raw_fields
    (even post-compile: compile_workflow_spec always reads raw_fields as its
    field list on every recompile, never entity_schema — see
    workflow_compiler.py — so a change that only touched entity_schema would
    get silently reverted the next time anything triggers a recompile).
    required/optional is communicated as a business-rule note rather than a
    direct entity_schema patch for the same reason: required-ness is
    re-derived from the description on every compile, so it has to be
    something the compiler is told, not a value patched around it.
    """
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft = dict(draft)
    org_id = str(draft["org_id"])

    from app.services.workflow_builder_agent import _merge_raw_fields

    action = body.get("action")
    existing_fields = _parse_jsonb(draft.get("raw_fields"), [])
    name = (body.get("name") or "").strip()
    updates: dict = {}

    if action == "add":
        if not name:
            raise HTTPException(status_code=400, detail="Field name is required")
        updates["raw_fields"] = json.dumps(
            _merge_raw_fields(existing_fields, [name], None)
        )
        note = f'directly added a field to the draft: "{name}"'
    elif action == "remove":
        updates["raw_fields"] = json.dumps(
            _merge_raw_fields(existing_fields, None, [name])
        )
        note = f'directly removed the field "{name}" from the draft'
    elif action == "rename":
        new_name = (body.get("new_name") or "").strip()
        if not name or not new_name:
            raise HTTPException(
                status_code=400, detail="name and new_name are required"
            )
        updates["raw_fields"] = json.dumps(
            _merge_raw_fields(existing_fields, [new_name], [name])
        )
        note = f'directly renamed the field "{name}" to "{new_name}"'
    elif action == "toggle_required":
        required = bool(body.get("required"))
        existing_rules = draft.get("business_rules") or ""
        updates["business_rules"] = (
            f"{existing_rules}\n{name} should be {'required' if required else 'optional'}.".strip()
        )
        note = f'directly marked "{name}" as {"required" if required else "optional"}'
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")

    was_compiled = draft.get("status") == "ready_for_review"
    if was_compiled:
        updates["status"] = "chatting"

    set_parts = [f"{k} = ${i + 2}" for i, k in enumerate(updates)]
    await execute(
        f"UPDATE workflow_drafts SET {', '.join(set_parts)}, updated_at = now() WHERE id = $1",
        draft_id,
        *updates.values(),
        source_key=source_key,
    )
    return await _save_and_maybe_recompile(
        draft_id, org_id, source_key, was_compiled, note
    )


@router.post("/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/gate")
async def edit_draft_gate(org_slug: str, draft_id: str, request: Request):
    """Direct panel edit for constraints — add or remove a gate. Unlike
    fields, gates ARE the authoritative source (the compiler is told to
    match them verbatim, never invent its own), so this writes straight to
    workflow_drafts.gates; recompiling afterward (if already compiled) is
    still required to regenerate the matching otp_gate/approval_gate steps."""
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft = dict(draft)
    org_id = str(draft["org_id"])

    from app.services.workflow_builder_agent import _backfill_gate_ids, _describe_gate

    gates = _parse_jsonb(draft.get("gates"), [])
    action = body.get("action")

    if action == "add":
        gate = body.get("gate") or {}
        gates = _backfill_gate_ids(gates + [gate])
        note = f"directly added a constraint to the draft: {_describe_gate(gate)}"
    elif action == "remove":
        gate_id = body.get("gate_id")
        gates = [g for g in gates if g.get("id") != gate_id]
        note = "directly removed a constraint from the draft"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")

    was_compiled = draft.get("status") == "ready_for_review"
    set_parts = ["gates = $2::jsonb"]
    vals = [json.dumps(gates)]
    if was_compiled:
        set_parts.append("status = 'chatting'")
    await execute(
        f"UPDATE workflow_drafts SET {', '.join(set_parts)}, updated_at = now() WHERE id = $1",
        draft_id,
        *vals,
        source_key=source_key,
    )
    return await _save_and_maybe_recompile(
        draft_id, org_id, source_key, was_compiled, note
    )


@router.post("/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/roles")
async def edit_draft_roles(org_slug: str, draft_id: str, request: Request):
    """
    Direct panel edit for who can use it. Unlike fields/gates, roles never
    touch steps/entity_schema/sql_template — freely editable with no
    recompile and no status change, even on an already-compiled draft.
    """
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft = dict(draft)
    org_id = str(draft["org_id"])

    from app.services.workflow_builder_agent import (
        append_draft_note,
        build_draft_recap,
        build_draft_state,
        resolve_roles,
    )

    requested = body.get("roles") or []
    resolved, unknown = await resolve_roles(requested, org_id, source_key)
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"Not real roles in this org: {unknown}"
        )

    await execute(
        "UPDATE workflow_drafts SET granted_roles = $1, updated_at = now() WHERE id = $2",
        resolved,
        draft_id,
        source_key=source_key,
    )
    draft["granted_roles"] = resolved
    await append_draft_note(
        draft,
        f"directly set who can use this to: {', '.join(resolved) or '(no one yet)'}",
        source_key,
    )
    return {
        "draft_recap": build_draft_recap(draft),
        "draft_state": build_draft_state(draft),
    }


@router.post(
    "/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/discard-and-reload"
)
async def discard_and_reload_draft(org_slug: str, draft_id: str):
    """
    The "discard mine & reload latest" side of the publish-conflict screen.
    Self-contained on purpose — abandons this draft and starts a fresh edit
    copy of whatever's live now, both server-side, rather than the frontend
    reusing whatever workflow id happens to still be sitting in a hidden
    input from earlier in the session. That hidden field is reliably set
    when this draft was reached via "Edit the logic", but a draft reached
    via the drafts-list resume flow (Part 2) might have no such field set
    at all, or a stale one — a conflict is exactly the moment a stale id
    would silently reload the WRONG workflow.
    """
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft or not draft.get("intent_key"):
        raise HTTPException(
            status_code=404, detail="Draft not found or was never linked to a workflow"
        )

    org_id = str(draft["org_id"])
    wf = await fetch_one(
        "SELECT * FROM workflows WHERE org_id = $1 AND intent_key = $2",
        org_id,
        draft["intent_key"],
        source_key=source_key,
    )
    if not wf:
        raise HTTPException(
            status_code=404, detail="That workflow no longer exists live"
        )

    await execute(
        "UPDATE workflow_drafts SET status = 'abandoned', updated_at = now() WHERE id = $1",
        draft_id,
        source_key=source_key,
    )

    from app.services.workflow_builder_agent import start_edit_draft

    return await start_edit_draft(dict(wf), org_id, source_key)


@router.post("/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/trigger")
async def edit_draft_trigger(org_slug: str, draft_id: str, request: Request):
    """Direct panel edit for the trigger command — same validation rule as
    the live-workflow settings form (update_workflow), and just as safe to
    change with no recompile: it's a routing label, not execution logic."""
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft = dict(draft)
    org_id = str(draft["org_id"])

    cmd = (body.get("slash_command") or "").strip().lstrip("/").lower()
    if not re.fullmatch(r"[a-z0-9_]{2,32}", cmd):
        raise HTTPException(
            status_code=400, detail="Command: 2-32 chars, lowercase letters/digits/_"
        )
    dupe = await fetch_one(
        "SELECT id FROM workflows WHERE org_id = $1 AND slash_command = $2 AND is_active = true AND intent_key != $3",
        org_id,
        cmd,
        draft.get("intent_key") or "",
        source_key=source_key,
    )
    if dupe:
        raise HTTPException(
            status_code=409, detail=f"Command '/{cmd}' is already in use"
        )

    from app.services.workflow_builder_agent import (
        append_draft_note,
        build_draft_recap,
        build_draft_state,
    )

    await execute(
        "UPDATE workflow_drafts SET slash_command = $1, updated_at = now() WHERE id = $2",
        cmd,
        draft_id,
        source_key=source_key,
    )
    draft["slash_command"] = cmd
    await append_draft_note(
        draft, f"directly changed the trigger command to /{cmd}", source_key
    )
    return {
        "draft_recap": build_draft_recap(draft),
        "draft_state": build_draft_state(draft),
    }


@router.post("/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/description")
async def edit_draft_description(org_slug: str, draft_id: str, request: Request):
    """Direct panel edit for the description — moved here from the old
    settings-modal form. Purely descriptive text with no execution-logic
    impact, so safe to change with no recompile, same as roles/trigger."""
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft = dict(draft)

    description = (body.get("description") or "").strip()
    from app.services.workflow_builder_agent import (
        append_draft_note,
        build_draft_recap,
        build_draft_state,
    )

    await execute(
        "UPDATE workflow_drafts SET description = $1, updated_at = now() WHERE id = $2",
        description,
        draft_id,
        source_key=source_key,
    )
    draft["description"] = description
    await append_draft_note(draft, "directly edited the description", source_key)
    return {
        "draft_recap": build_draft_recap(draft),
        "draft_state": build_draft_state(draft),
    }


@router.post("/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/title")
async def edit_draft_title(org_slug: str, draft_id: str, request: Request):
    """
    Direct panel edit for the workflow's display name — purely descriptive,
    no execution-logic impact, safe with no recompile.

    Previously the only way to rename a draft was asking the assistant via
    chat, which routed through revise_draft + a full recompile — fragile
    for something this simple, and reproduced live on Godrej: a
    rename-only request caused the compiler to regenerate entity_schema
    WORSE than the original (content/pdf_url lost their table/column
    mapping entirely) and fail all 3 critic retries, over a change that
    never needed the compiler involved at all.
    """
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft = dict(draft)

    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    from app.services.workflow_builder_agent import (
        append_draft_note,
        build_draft_recap,
        build_draft_state,
    )

    await execute(
        "UPDATE workflow_drafts SET name = $1, updated_at = now() WHERE id = $2",
        name,
        draft_id,
        source_key=source_key,
    )
    draft["name"] = name
    await append_draft_note(
        draft, f'directly renamed the workflow to "{name}"', source_key
    )
    return {
        "draft_recap": build_draft_recap(draft),
        "draft_state": build_draft_state(draft),
    }


@router.post("/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/type")
async def edit_draft_type(org_slug: str, draft_id: str, request: Request):
    """
    Direct panel edit for workflow_type (read/action). Unlike title, this
    genuinely changes what steps[]/sql_template should look like — same
    category as fields/gates — so it flips the draft back to 'chatting'
    and recompiles immediately rather than being a safe no-op change.
    """
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft = dict(draft)
    org_id = str(draft["org_id"])

    wtype = body.get("workflow_type")
    if wtype not in ("read", "action"):
        raise HTTPException(
            status_code=400, detail="workflow_type must be 'read' or 'action'"
        )

    was_compiled = draft.get("status") == "ready_for_review"
    set_parts = ["workflow_type = $2"]
    vals = [wtype]
    if was_compiled:
        set_parts.append("status = 'chatting'")
    await execute(
        f"UPDATE workflow_drafts SET {', '.join(set_parts)}, updated_at = now() WHERE id = $1",
        draft_id,
        *vals,
        source_key=source_key,
    )
    return await _save_and_maybe_recompile(
        draft_id,
        org_id,
        source_key,
        was_compiled,
        f"directly changed the type to {wtype}",
    )


@router.post("/admin/{org_slug}/api/workflow-builder/draft/{draft_id}/business-rule")
async def edit_draft_business_rule(org_slug: str, draft_id: str, request: Request):
    """
    Direct panel edit for the raw business-rules text the compiler reads.
    Unlike chat's revise_draft (which always appends a "Requested change:
    ..." line, appropriate for narrating a new request mid-conversation),
    this REPLACES the text outright — a panel edit is the admin looking at
    and correcting the actual current instructions, not adding another one
    on top. Affects compiled output same as fields/gates, so this
    recompiles immediately too.
    """
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)
    draft = await fetch_one(
        "SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft = dict(draft)
    org_id = str(draft["org_id"])

    business_rules = (body.get("business_rules") or "").strip()
    was_compiled = draft.get("status") == "ready_for_review"
    set_parts = ["business_rules = $2"]
    vals = [business_rules]
    if was_compiled:
        set_parts.append("status = 'chatting'")
    await execute(
        f"UPDATE workflow_drafts SET {', '.join(set_parts)}, updated_at = now() WHERE id = $1",
        draft_id,
        *vals,
        source_key=source_key,
    )
    return await _save_and_maybe_recompile(
        draft_id, org_id, source_key, was_compiled, "directly edited the business rules"
    )


def _build_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OrchestrAI Admin</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f4f8;color:#1a1a2e;font-size:14px}
.header{background:#185FA5;color:#fff;padding:16px 28px;display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:20px;font-weight:600}
.container{max-width:1200px;margin:0 auto;padding:24px 20px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}
.stat-card{background:#fff;border-radius:10px;padding:18px 20px;border-left:4px solid #185FA5;box-shadow:0 1px 4px rgba(0,0,0,0.08)}
.stat-label{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:6px}
.stat-value{font-size:26px;font-weight:600;color:#185FA5}
.stat-sub{font-size:11px;color:#aaa;margin-top:3px}
.card{background:#fff;border-radius:10px;padding:20px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,0.08)}
.card-title{font-size:14px;font-weight:600;color:#185FA5;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid #e8edf5}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.6px;color:#888;padding:0 0 10px 0;font-weight:500}
td{padding:10px 0;border-bottom:1px solid #f0f4f8;font-size:13px;vertical-align:middle}
tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500}
.badge-active{background:#dcfce7;color:#16a34a}
.badge-inactive{background:#fee2e2;color:#dc2626}
.badge-read{background:#dbeafe;color:#185FA5}
.badge-action{background:#fef3c7;color:#d97706}
.toggle{position:relative;width:42px;height:24px;display:inline-block}
.toggle input{opacity:0;width:0;height:0}
.slider{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:#ccc;border-radius:24px;transition:.3s}
.slider:before{position:absolute;content:"";height:18px;width:18px;left:3px;bottom:3px;background:white;border-radius:50%;transition:.3s}
input:checked+.slider{background:#185FA5}
input:checked+.slider:before{transform:translateX(18px)}
.threshold-input{border:1px solid #e8edf5;border-radius:6px;padding:4px 8px;font-size:12px;color:#1a1a2e}
.threshold-input:focus{outline:none;border-color:#185FA5}
.btn{border:none;border-radius:6px;padding:6px 14px;font-size:12px;cursor:pointer;font-weight:500}
.btn-primary{background:#185FA5;color:#fff}
.btn-purple{background:#8b5cf6;color:#fff}
.btn-danger{background:#dc2626;color:#fff}
.btn-gray{background:#e5e7eb;color:#374151}
.btn:hover{opacity:0.88}
.loading{text-align:center;padding:40px;color:#888}
/* Modal */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100;align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:#fff;border-radius:12px;padding:24px;width:90%;max-width:800px;max-height:90vh;overflow-y:auto}
.modal-title{font-size:16px;font-weight:600;margin-bottom:16px;color:#185FA5}
.field-row{margin-bottom:12px}
.field-label{font-size:11px;color:#888;text-transform:uppercase;margin-bottom:4px}
.field-input{width:100%;border:1px solid #e8edf5;border-radius:6px;padding:7px 10px;font-size:13px;font-family:inherit}
.field-input:focus{outline:none;border-color:#8b5cf6}
.json-editor{width:100%;border:1px solid #e8edf5;border-radius:6px;padding:8px;font-size:12px;font-family:monospace;min-height:120px;resize:vertical}
.jv-key{color:#8b5cf6}
.jv-str{color:#1a7f37}
.jv-num{color:#185FA5}
.jv-bool{color:#b45309}
.jv-null{color:#999}
/* Chat builder */
.chat-messages{height:320px;overflow-y:auto;border:1px solid #e8edf5;border-radius:8px;padding:12px;background:#fafbfc;margin-bottom:10px}
.chat-msg{margin-bottom:10px;display:flex}
.chat-msg.user{justify-content:flex-end}
.chat-bubble{max-width:80%;padding:9px 13px;border-radius:10px;font-size:13px;white-space:pre-wrap;line-height:1.5}
.chat-msg.user .chat-bubble{background:#8b5cf6;color:#fff}
.chat-msg.bot .chat-bubble{background:#fff;border:1px solid #e8edf5;color:#1a1a2e}
.summary-card{background:#f0fdf4;border:2px solid #16a34a;border-radius:8px;padding:14px;margin:10px 0;font-size:13px;line-height:1.6}
.chat-input-row{display:flex;gap:8px}
/* Drafts list ("Continue a draft") */
.draft-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid #f0f4f8}
.draft-row:last-child{border-bottom:none}
.draft-row .meta{font-size:11px;color:#aaa;margin-top:2px}
/* Editable draft panel */
.panel-box{background:#fafbfc;border:1px solid #e8edf5;border-radius:8px;padding:10px;height:320px;overflow-y:auto;font-size:12px}
.panel-section{margin-bottom:14px}
.panel-section:last-child{margin-bottom:0}
.panel-section-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#aaa;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center}
.panel-field-row{display:flex;align-items:center;gap:6px;padding:4px 0}
.panel-field-row .fname{flex:1}
.req-pill{font-size:10px;font-weight:600;padding:2px 6px;border-radius:4px;cursor:pointer;border:none}
.req-yes{background:#dbeafe;color:#185FA5}
.req-no{background:#f0f4f8;color:#888}
.icon-btn-sm{background:none;border:none;color:#bbb;cursor:pointer;font-size:12px;padding:2px 4px}
.icon-btn-sm:hover{color:#dc2626}
.gate-row{border:1px solid #e8edf5;border-radius:6px;padding:6px 9px;margin-bottom:5px;display:flex;justify-content:space-between;gap:6px;align-items:flex-start}
.gate-row.is-new{border-color:#8b5cf6;background:#f5f3ff}
.role-chip-sm{border:1px solid #e8edf5;background:#fff;border-radius:12px;padding:3px 9px;font-size:11px;cursor:pointer;margin:2px}
.role-chip-sm.on{background:#185FA5;border-color:#185FA5;color:#fff}
.mini-form-sm{background:#fff;border:1px dashed #e8edf5;border-radius:6px;padding:8px;margin-top:6px}
.mini-form-sm input,.mini-form-sm select{width:100%;border:1px solid #e8edf5;border-radius:5px;padding:5px 7px;font-size:12px;margin-bottom:6px;font-family:inherit}
.link-btn-sm{background:none;border:none;color:#185FA5;font-weight:600;font-size:11px;cursor:pointer;padding:0}
.diff-pill{font-size:10px;font-weight:700;padding:3px 8px;border-radius:10px;background:#fef3c7;color:#d97706}
.diff-box{background:#fef3c7;border:1px solid #fde68a;border-radius:6px;padding:8px 10px;font-size:11px;margin-top:6px}
.diff-box div{padding:2px 0}
.conflict-box{background:#fee2e2;border:1px solid #fecaca;color:#991b1b;border-radius:8px;padding:12px;font-size:13px;line-height:1.5}
</style>
</head>
<body>
<div class="header">
  <h1>🎛 OrchestrAI Admin</h1>
  <span id="orgName">Loading...</span>
</div>
<div class="container">
  <div id="loading" class="loading"></div>
  <div id="content" style="display:none">

    <div class="stats" id="statsGrid"></div>

    <!-- ── LOW STOCK ALERT — title/columns filled in from dashboard_stats config ── -->
    <div class="card" id="lowStockCard" style="display:none;border-left:4px solid #f59e0b">
      <div class="card-title" style="color:#f59e0b" id="lowStockTitle">⚠️ Low Stock Alert</div>
      <table>
        <thead><tr id="lowStockHead"></tr></thead>
        <tbody id="lowStockTable"></tbody>
      </table>
    </div>

    <!-- ── WORKFLOW LIST ─────────────────────────────────────────── -->
    <div class="card">
      <div class="card-title" style="display:flex;justify-content:space-between;align-items:center">
        <span>⚙️ Workflows</span>
        <span>
          <button class="btn btn-gray" id="draftsBtn" style="margin-right:6px;display:none" onclick="openDraftsModal()">📝 Drafts</button>
          <button class="btn btn-purple" onclick="openBuilderChat()">✨ Build New Workflow</button>
        </span>
      </div>
      <table style="table-layout:fixed">
        <thead><tr>
          <th style="width:46%">Name</th><th style="width:16%">Type</th>
          <th style="width:16%">Active</th><th style="width:22%">Actions</th>
        </tr></thead>
        <tbody id="workflowsTable"></tbody>
      </table>
    </div>

    <!-- ── SECURITY ──────────────────────────────────────────────── -->
    <div class="card" style="border-left:4px solid #dc2626">
      <div class="card-title" style="color:#dc2626">🔒 Security — Session Management</div>
      <div style="display:flex;align-items:flex-start;gap:32px;flex-wrap:wrap">
        <div>
          <div class="stat-label">Session Timeout</div>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px">
            <input class="threshold-input" type="number" id="ttl_value" value="8" min="1" style="width:70px">
            <select id="ttl_unit" style="border:1px solid #e8edf5;border-radius:6px;padding:4px 8px;font-size:12px;background:#fff">
              <option value="hours">hours</option>
              <option value="minutes">minutes</option>
            </select>
            <button class="btn btn-primary" onclick="saveTTL()">Save</button>
          </div>
        </div>
        <div style="margin-left:auto">
          <button class="btn btn-danger" onclick="clearSessions()">🔒 Clear All Sessions</button>
          <div style="font-size:11px;color:#aaa;margin-top:4px">Forces all users to re-authenticate</div>
        </div>
      </div>
    </div>

    <!-- ── BRANDING ──────────────────────────────────────────────── -->
    <div class="card">
      <div class="card-title">🖼️ Branding — Org Logo</div>
      <div style="display:flex;align-items:center;gap:16px">
        <img id="orgLogoPreview" src="" alt="" style="display:none;max-height:60px;max-width:160px;border:1px solid #e8edf5;border-radius:6px;padding:4px">
        <span id="orgLogoEmpty" style="font-size:12px;color:#aaa">No logo uploaded yet</span>
        <input type="file" id="logoFile" accept="image/*" style="display:none" onchange="uploadLogo(this)">
        <button class="btn btn-gray" onclick="document.getElementById('logoFile').click()">📎 Upload Logo</button>
        <span id="logoStatus" style="font-size:11px;color:#888"></span>
      </div>
      <div style="font-size:11px;color:#aaa;margin-top:8px">
        Shown in the same fixed position on every generated PDF (invoices, meeting minutes, etc.) — image only, up to 2MB.
      </div>
    </div>

    <!-- ── RECENT ACTIVITY ───────────────────────────────────────── -->
    <div class="card">
      <div class="card-title">📋 Recent Activity</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px">
        <select class="field-input" id="actUser" style="width:160px">
          <option value="">All users</option>
        </select>
        <input class="field-input" type="date" id="actFrom" style="width:150px" title="From date">
        <input class="field-input" type="date" id="actTo" style="width:150px" title="To date">
        <select class="field-input" id="actOutcome" style="width:130px">
          <option value="">All status</option>
          <option value="success">success</option>
          <option value="error">error</option>
        </select>
        <input class="field-input" type="text" id="actSearch" placeholder="Search message or reply" style="flex:1;min-width:180px">
        <button class="btn btn-gray" onclick="resetActivityFilters()">Reset</button>
      </div>
      <table style="table-layout:fixed">
        <thead><tr>
          <th style="width:14%">Timestamp</th><th style="width:13%">User</th>
          <th style="width:23%">Message</th><th style="width:23%">Reply</th>
          <th style="width:12%">Workflow</th><th style="width:8%">Status</th><th style="width:7%"></th>
        </tr></thead>
        <tbody id="activityTable"></tbody>
      </table>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;font-size:12px;color:#888">
        <span id="activityInfo"></span>
        <div style="display:flex;gap:8px;align-items:center">
          <button class="btn btn-gray" id="activityPrev" onclick="changeActivityPage(-1)">Prev</button>
          <span id="activityPageNum"></span>
          <button class="btn btn-gray" id="activityNext" onclick="changeActivityPage(1)">Next</button>
        </div>
      </div>
    </div>

  </div><!-- /content -->
</div><!-- /container -->

<!-- ── WORKFLOW SETTINGS MODAL (structural only — see PUT /workflow/{id}) ── -->
<!-- ── RAW JSON VIEW (read-only — the real saved data, formatted for readability) ── -->
<div class="modal-bg" id="jsonViewModal">
  <div class="modal" style="max-width:700px">
    <div class="modal-title" style="display:flex;justify-content:space-between">
      <span>🔍 Workflow JSON (read-only)</span>
      <button class="btn btn-gray" onclick="closeModal('jsonViewModal')" style="padding:4px 10px">✕</button>
    </div>
    <div id="jsonViewContent" class="json-editor" style="min-height:400px;max-height:70vh;overflow-y:auto;background:#fafbfc"></div>
  </div>
</div>

<!-- ── ACTIVITY CONVERSATION MODAL ──────────────────────────────── -->
<div class="modal-bg" id="activityConvoModal">
  <div class="modal" style="max-width:520px">
    <div class="modal-title" style="display:flex;justify-content:space-between">
      <span id="activityConvoTitle">Conversation</span>
      <button class="btn btn-gray" onclick="closeModal('activityConvoModal')" style="padding:4px 10px">✕</button>
    </div>
    <div id="activityConvoThread" style="display:flex;flex-direction:column;gap:8px;max-height:60vh;overflow-y:auto"></div>
  </div>
</div>

<!-- ── DRAFTS — unfinished workflow_drafts rows, opened on demand instead of
     sitting as a permanent card above the workflow list. Continue any one,
     delete any one, or clear all from here. ──────────────────────────── -->
<div class="modal-bg" id="draftsModal">
  <div class="modal" style="max-width:600px">
    <div class="modal-title" style="display:flex;justify-content:space-between">
      <span>📝 Drafts in progress</span>
      <button class="btn btn-gray" onclick="closeModal('draftsModal')" style="padding:4px 10px">✕</button>
    </div>
    <div id="draftsModalList"></div>
    <div style="border-top:1px solid #e8edf5;margin-top:14px;padding-top:14px;text-align:right">
      <button class="btn btn-danger" onclick="clearUnfinishedDrafts()">🧹 Clear all</button>
    </div>
  </div>
</div>

<!-- ── WORKFLOW CHAT BUILDER MODAL ──────────────────────────────── -->
<div class="modal-bg" id="builderModal">
  <div class="modal" style="max-width:920px">
    <div class="modal-title" style="display:flex;justify-content:space-between;align-items:center">
      <span id="builderTitle">💬 Build / Edit a Workflow</span>
      <span>
        <button class="btn btn-gray" id="viewJsonBtn" onclick="viewRawJson()" style="display:none;padding:4px 10px;font-size:11px;margin-right:6px">🔍 View JSON</button>
        <button class="btn btn-gray" onclick="closeModal('builderModal')" style="padding:4px 10px">✕</button>
      </span>
    </div>
    <div style="display:grid;grid-template-columns:1fr 300px;gap:14px">
      <div>
        <div id="chatMessages" class="chat-messages"></div>
        <div class="chat-input-row">
          <input type="file" id="chatAttachment" accept="application/pdf" style="display:none"
                 onchange="onPdfSelected(this)">
          <button class="btn btn-gray" onclick="document.getElementById('chatAttachment').click()" title="Attach sample PDF">📎</button>
          <span id="attachLabel" style="font-size:11px;color:#888;align-self:center;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
          <input id="chatInput" class="field-input" placeholder="Describe your workflow..."
                 style="flex:1" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendChatMsg()}">
          <button class="btn btn-purple" onclick="sendChatMsg()">Send</button>
        </div>
        <div style="margin-top:8px;text-align:right">
          <button class="btn btn-primary" id="manualPublishBtn" onclick="manualPublish()">🚀 Publish</button>
        </div>
        <div id="builderStatus" style="font-size:11px;color:#888;margin-top:6px;text-align:center"></div>
      </div>
      <div>
        <div class="field-label" style="display:flex;justify-content:space-between;align-items:center">
          <span>Draft so far</span>
          <span id="diffPill" class="diff-pill" style="display:none"></span>
        </div>
        <div id="draftPanel" class="panel-box">Tell me what you want to build...</div>
      </div>
    </div>
  </div>
</div>

<!-- ── PUBLISH CONFLICT — someone else published a change to this same
     workflow while this draft was open; never auto-merged, see
     PublishConflict's docstring ──────────────────────────────────────── -->
<div class="modal-bg" id="conflictModal">
  <div class="modal" style="max-width:480px">
    <div class="modal-title">⚠️ Can't save</div>
    <input type="hidden" id="conflictDraftId">
    <div id="conflictBody" class="conflict-box"></div>
    <div style="display:flex;gap:8px;margin-top:16px">
      <button class="btn btn-gray" onclick="closeModal('conflictModal');openModal('publishModal')">Keep editing here</button>
      <button class="btn btn-danger" onclick="discardAndReloadLatest()">Discard mine &amp; reload latest</button>
    </div>
  </div>
</div>

<!-- ── CONFIRM & PUBLISH — appears once the draft is ready; nothing left to
     fill in, everything above was already gathered by chatting ──────────── -->
<div class="modal-bg" id="publishModal">
  <div class="modal" style="max-width:520px">
    <div class="modal-title">🚀 Publish this workflow?</div>
    <input type="hidden" id="publishDraftId">
    <pre id="publishRecap" style="background:#f0fdf4;border:2px solid #16a34a;border-radius:8px;padding:14px;
         font-size:13px;line-height:1.7;white-space:pre-wrap;font-family:inherit;margin:0 0 14px 0"></pre>
    <div style="display:flex;gap:8px">
      <button class="btn btn-primary" onclick="publishDraft()">✅ Publish</button>
      <button class="btn btn-gray" onclick="backToChat()">✏️ Change something</button>
    </div>
    <div id="publishStatus" style="font-size:11px;color:#888;margin-top:6px"></div>
  </div>
</div>

<script>
// Org is whatever comes after /admin/ in the URL — /admin/baanganga,
// /admin/godrej_emerald, etc. — so every API call this page makes is
// automatically scoped to that org with no other change needed.
const ORG_SLUG = window.location.pathname.split('/')[2] || '';
const API = path => `/admin/${ORG_SLUG}/api${path}`;
let chatDraftId = null;
let chatTyping  = false;
let chatPdfAnalysis = null;  // pre-extracted PDF layout spec
let chatIsEditingExisting = false;  // true only when this draft was loaded from an already-published workflow
let chatLiveSnapshot = null; // {version,fields,gates,granted_roles,slash_command} captured once when an
                              // edit draft is opened/resumed — the FIXED baseline the diff pill compares
                              // against for the rest of this session; never refreshed mid-session (see
                              // resume_draft's docstring on why that would hide a real conflict)
let chatDraftState   = null; // last draft_state payload — structured mirror of draftRecap the panel renders from
let chatLastRecapText = '';  // last build_draft_recap() text — only used for the read-only publish-confirm screen

// No auth for now — see _check_token in admin.py for how to re-enable it.
async function authenticatedFetch(url, options = {}) {
  const res = await fetch(url, options);
  return res;
}

// ── Utility ───────────────────────────────────────────────────────
function closeModal(id) { document.getElementById(id).classList.remove('open'); }
function openModal(id)  { document.getElementById(id).classList.add('open'); }
function fmtRs(v) { return v ? 'Rs.' + Number(v).toLocaleString('en-IN') : '—'; }
function fmtDate(d) { return d ? new Date(d).toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short'}) : '—'; }

// ── Security ──────────────────────────────────────────────────────
async function saveTTL() {
  const val = parseInt(document.getElementById('ttl_value').value);
  const unit = document.getElementById('ttl_unit').value;
  const mins = unit === 'hours' ? val * 60 : val;
  const res = await authenticatedFetch(API('/security/ttl'), {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({minutes:mins})});
  if (res && res.ok) alert('✅ Session timeout updated');
}
async function clearSessions() {
  if (!confirm('⚠️ Log out ALL users immediately?')) return;
  const res = await authenticatedFetch(API('/sessions/clear'), {method:'POST'});
  if (res && res.ok) alert('🔒 All sessions cleared');
}

// ── Branding ──────────────────────────────────────────────────────
function _renderLogoPreview(logoUrl) {
  const img = document.getElementById('orgLogoPreview');
  const empty = document.getElementById('orgLogoEmpty');
  if (logoUrl) {
    img.src = logoUrl;
    img.style.display = '';
    empty.style.display = 'none';
  } else {
    img.style.display = 'none';
    empty.style.display = '';
  }
}
async function uploadLogo(input) {
  if (!input.files.length) return;
  const file = input.files[0];
  const status = document.getElementById('logoStatus');
  status.textContent = '⏳ Uploading...';
  const fd = new FormData();
  fd.append('logo_file', file);
  const res = await authenticatedFetch(API('/settings/logo'), {method:'POST', body:fd});
  if (res && res.ok) {
    const { logo_url } = await res.json();
    _renderLogoPreview(logo_url);
    status.textContent = '✅ Logo updated';
  } else {
    const err = res ? (await res.json().catch(()=>({}))).detail : null;
    status.textContent = '⚠️ ' + (err || 'Upload failed');
  }
  input.value = '';
}

// ── Workflow List ─────────────────────────────────────────────────
function renderWorkflows(workflows) {
  const tbody = document.getElementById('workflowsTable');
  if (!workflows.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#aaa;padding:20px">No workflows yet — click Build New Workflow to add one</td></tr>';
    return;
  }
  tbody.innerHTML = workflows.map(w => `
    <tr>
      <td><strong>${w.name}</strong><br><span style="font-size:11px;color:#888">${w.intent_key}</span></td>
      <td><span class="badge badge-${w.workflow_type}">${w.workflow_type}</span></td>
      <td>
        <label class="toggle">
          <input type="checkbox" ${w.is_active ? 'checked' : ''} onchange="toggleActive('${w.id}',this.checked)">
          <span class="slider"></span>
        </label>
      </td>
      <td style="white-space:nowrap">
        <button class="btn btn-gray" onclick="openEditLogic('${w.id}')" style="margin-right:4px">✏️ Edit</button>
        <button class="btn btn-danger" onclick="deleteWorkflow('${w.id}','${w.name}')">🗑️</button>
      </td>
    </tr>
  `).join('');
}

async function toggleActive(id, active) {
  await authenticatedFetch(API(`/workflow/${id}/toggle`), {method:'POST'});
}

async function deleteWorkflow(id, name) {
  if (!confirm(`Delete workflow "${name}"?\nThis cannot be undone.`)) return;
  const r = await authenticatedFetch(API(`/workflow/${id}`), {method:'DELETE'});
  if (r) {
    const d = await r.json();
    if (d.success) { alert('✅ Deleted'); loadData(); }
    else alert('Error: ' + (d.detail || 'unknown'));
  }
}

// ── Gate (constraint) editor — shared by Edit modal and Publish panel ──────
// Two independent stores so editing an existing workflow and publishing a
// fresh draft never share state. Each gate is a plain object matching
// workflows.gates[] exactly (see migrations/011_*_gates_schema.sql):
//   {id, type: 'otp'|'approval_chain'|'permission', when:{...}, levels:[...], role_any_of:[...]}
let orgRolesList = [];

async function refreshOrgRoles() {
  const r = await authenticatedFetch(API('/roles'));
  if (r && r.ok) orgRolesList = (await r.json()).map(x => x.name);
}

// Structural settings (name/description/trigger/roles) now live entirely
// inside the chat builder panel (renderDraftPanel) — editing a workflow no
// longer opens a separate settings modal first, it goes straight into
// openEditLogic below. The old form-based editModal and its save path
// (PUT /workflow/{id}) were removed; that endpoint is still on the server
// but nothing in this UI calls it anymore.

// Same raw data as before (training_phrases, entity_schema, calc_rules,
// steps, sql_template, business_glossary, pdf_config, response_template,
// llm_system_prompt) — just laid out as labeled, indented sections with
// syntax-colored JSON per field instead of one undifferentiated blob, so
// it's actually readable without changing what's shown.
function _escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _highlightJson(value) {
  const json = _escapeHtml(JSON.stringify(value, null, 2));
  return json.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\\s*:)?|\b(true|false|null)\b|-?\\d+(?:\\.\\d*)?(?:[eE][+\\-]?\\d+)?)/g,
    (match) => {
      let cls = 'jv-num';
      if (/^"/.test(match)) cls = /:$/.test(match) ? 'jv-key' : 'jv-str';
      else if (/true|false/.test(match)) cls = 'jv-bool';
      else if (/null/.test(match)) cls = 'jv-null';
      return `<span class="${cls}">${match}</span>`;
    }
  );
}

// Plain-text fields (already strings, not JSON structures) — shown as-is,
// not JSON.stringify'd, so a SQL query doesn't show up wrapped in quotes
// with its line breaks escaped.
const _JSON_VIEW_TEXT_FIELDS = new Set(['sql_template', 'response_template', 'llm_system_prompt']);

const _JSON_VIEW_FIELDS = [
  ['sql_template',        'SQL query'],
  ['entity_schema',       'Fields (entity_schema)'],
  ['calc_rules',          'Calculations (calc_rules)'],
  ['steps',               'Execution steps'],
  ['training_phrases',    'Training phrases'],
  ['business_glossary',   'Business glossary'],
  ['pdf_config',          'PDF config'],
  ['response_template',   'Response template'],
  ['llm_system_prompt',   'LLM system prompt'],
];

async function viewRawJson() {
  const id = chatLiveSnapshot && chatLiveSnapshot.id;
  if (!id) { alert("Nothing published yet — there's no live workflow to show JSON for."); return; }
  const r = await authenticatedFetch(API(`/workflow/${id}/detail`));
  if (!r) return;
  const w = await r.json();

  const html = _JSON_VIEW_FIELDS.map(([field, label]) => {
    const val = w[field];
    const isEmpty = val === null || val === undefined ||
      (Array.isArray(val) && val.length === 0) ||
      (typeof val === 'object' && !Array.isArray(val) && Object.keys(val).length === 0) ||
      val === '';
    let body;
    if (isEmpty) {
      body = '<span style="color:#aaa">(none)</span>';
    } else if (_JSON_VIEW_TEXT_FIELDS.has(field)) {
      body = `<pre style="margin:4px 0 0;white-space:pre-wrap;font-family:monospace">${_escapeHtml(String(val))}</pre>`;
    } else {
      body = `<pre style="margin:4px 0 0;white-space:pre-wrap;font-family:monospace">${_highlightJson(val)}</pre>`;
    }
    return `<div style="margin-bottom:14px">
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:#888;font-weight:600">${label}</div>
      ${body}
    </div>`;
  }).join('');

  document.getElementById('jsonViewContent').innerHTML = html;
  openModal('jsonViewModal');
}

// ── Chat Builder ─────────────────────────────────────────────────
function _updateManualPublishLabel() {
  // Send is always available in both modes — it's how you actually make
  // changes, whether describing a brand-new workflow or asking for a fix to
  // an existing one. Only this second button's label/intent should differ:
  // for a never-published draft there's nothing live yet to "update", so it
  // reads as the first-time creation action; once editing something that's
  // already published, it reads as what it actually does to that workflow.
  const btn = document.getElementById('manualPublishBtn');
  if (!btn) return;
  if (chatIsEditingExisting) {
    btn.textContent = '💾 Save changes';
    btn.title = "Open the publish screen with whatever's in Draft so far right now — updates the existing live workflow, you don't have to wait for the assistant to say it's ready";
  } else {
    btn.textContent = '🚀 Publish';
    btn.title = "Open the publish screen with whatever's in Draft so far right now — creates this as a new live workflow, you don't have to wait for the assistant to say it's ready";
  }
}

function _resetBuilderModal() {
  chatDraftId = null;
  chatPdfAnalysis = null;
  chatIsEditingExisting = false;
  chatLiveSnapshot = null;
  chatDraftState = null;
  document.getElementById('chatMessages').innerHTML = '';
  document.getElementById('chatInput').value = '';
  document.getElementById('attachLabel').textContent = '';
  document.getElementById('builderStatus').textContent = '';
  document.getElementById('draftPanel').textContent = 'Tell me what you want to build...';
  document.getElementById('diffPill').style.display = 'none';
  document.getElementById('builderTitle').textContent = '💬 Build a New Workflow';
  _updateManualPublishLabel();
  _updateViewJsonBtn();
}

// Shows "View JSON" only once there's an actual live workflow behind this
// draft (chatLiveSnapshot set) — a from-scratch draft has nothing live yet
// to show, same as the original button's meaning when it lived in the
// settings modal.
function _updateViewJsonBtn() {
  const btn = document.getElementById('viewJsonBtn');
  if (btn) btn.style.display = chatLiveSnapshot ? 'inline-block' : 'none';
}

function openBuilderChat() {
  _resetBuilderModal();
  openModal('builderModal');
  appendBotMsg('Hi! Tell me about the workflow you want to build — what should it do?');
}

// Bulk-clear still exists (now lives inside draftsModal, not the
// workflow-list header) — confirms once, abandons every 'chatting' draft
// for the org, then refreshes whichever view is currently showing counts.
async function clearUnfinishedDrafts() {
  if (!confirm('Clear all unfinished workflow drafts for this org?\\nThis abandons every in-progress draft that was never published — it does not touch any live workflow.')) return;
  const r = await authenticatedFetch(API('/workflow-builder/clear-drafts'), {method: 'POST'});
  if (!r) return;
  const d = await r.json();
  alert(d.cleared > 0 ? `✅ Cleared ${d.cleared} unfinished draft(s).` : 'No unfinished drafts to clear.');
  closeModal('draftsModal');
  loadDrafts();
}

// ── Drafts ────────────────────────────────────────────────────────
// Only updates the "📝 Drafts" button's count badge — no longer renders an
// always-visible card, which just sat there taking up space above the
// workflow list whether there was one draft or none. The actual list only
// renders when the admin opens it (openDraftsModal).
async function loadDrafts() {
  const r = await authenticatedFetch(API('/workflow-builder/drafts'));
  if (!r || !r.ok) return;
  const { drafts } = await r.json();
  const btn = document.getElementById('draftsBtn');
  if (!drafts.length) { btn.style.display = 'none'; return; }
  btn.style.display = 'inline-block';
  btn.textContent = `📝 Drafts (${drafts.length})`;
}

function _renderDraftsModalList(drafts) {
  document.getElementById('draftsModalList').innerHTML = drafts.length ? drafts.map(d => `
    <div class="draft-row">
      <div>
        <strong>${d.name}</strong>
        <div class="meta">${d.is_edit ? 'editing a live workflow' : 'new workflow'} · ${d.status.replace('_',' ')} ·
          ${d.field_count} field(s) · ${d.gate_count} constraint(s) · roles ${d.has_roles ? 'set' : 'not set'} ·
          updated ${fmtDate(d.updated_at)}</div>
      </div>
      <span style="white-space:nowrap">
        <button class="btn btn-purple" style="margin-right:4px" onclick="resumeDraft('${d.id}')">Continue →</button>
        <button class="btn btn-danger" onclick="deleteDraft('${d.id}','${escAttr(d.name)}')" title="Delete this draft">🗑️</button>
      </span>
    </div>
  `).join('') : '<div style="text-align:center;color:#aaa;padding:20px">No drafts in progress.</div>';
}

async function openDraftsModal() {
  const r = await authenticatedFetch(API('/workflow-builder/drafts'));
  if (!r || !r.ok) return;
  const { drafts } = await r.json();
  _renderDraftsModalList(drafts);
  openModal('draftsModal');
}

async function deleteDraft(id, name) {
  if (!confirm(`Delete draft "${name}"?\\nThis abandons this specific draft — it does not touch any live workflow, and doesn't affect any other draft.`)) return;
  const r = await authenticatedFetch(API(`/workflow-builder/draft/${id}/abandon`), {method: 'POST'});
  if (!r || !r.ok) { alert('Could not delete that draft.'); return; }
  const rr = await authenticatedFetch(API('/workflow-builder/drafts'));
  const { drafts } = await rr.json();
  _renderDraftsModalList(drafts);
  loadDrafts();
}

async function resumeDraft(draftId) {
  const r = await authenticatedFetch(API(`/workflow-builder/resume/${draftId}`), {method: 'POST'});
  if (!r || !r.ok) { alert('Could not resume that draft.'); return; }
  const data = await r.json();
  closeModal('draftsModal');
  _resetBuilderModal();
  chatDraftId = data.draft_id;
  chatIsEditingExisting = !!data.live_snapshot;
  chatLiveSnapshot = data.live_snapshot || null;
  chatLastRecapText = data.draft_recap || '';
  document.getElementById('builderTitle').textContent = `💬 ${data.name || 'Workflow'}`;
  renderChatHistory(data.chat_history || []);
  renderDraftPanel(data.draft_state);
  _updateManualPublishLabel();
  _updateViewJsonBtn();
  openModal('builderModal');
}

// Replays a stored transcript on resume. Bracketed entries are synthetic
// annotations (PDF-upload notes, the resume nudge itself, direct-panel-edit
// notes — see append_draft_note) meant only for the model's context, never
// shown as if the admin typed them.
function renderChatHistory(history) {
  document.getElementById('chatMessages').innerHTML = '';
  for (const m of history) {
    if (m.role === 'user' && m.content.trim().startsWith('[')) continue;
    if (m.role === 'user') appendUserMsg(m.content);
    else if (m.role === 'assistant' && m.content) appendBotMsg(m.content);
  }
}

// Single entry point into editing a workflow — the "✏️ Edit" button on the
// workflows list calls this directly with the workflow's id, opening the
// chat builder immediately. There's no separate settings-modal step
// anymore; everything that used to live there (name, description, trigger
// command, roles, View JSON) is now in the builder panel itself.
async function openEditLogic(id) {
  const r = await authenticatedFetch(API(`/workflow-builder/edit/${id}`), {method: 'POST'});
  if (!r || !r.ok) { alert('Could not start edit.'); return; }
  const data = await r.json();
  _resetBuilderModal();
  chatDraftId = data.draft_id;
  chatIsEditingExisting = true;
  chatLiveSnapshot = data.live_snapshot || null;
  chatLastRecapText = data.draft_recap || '';
  renderDraftPanel(data.draft_state);
  document.getElementById('builderTitle').textContent = `💬 Editing: ${data.name || 'Workflow'}`;
  _updateManualPublishLabel();
  _updateViewJsonBtn();
  openModal('builderModal');
  if (data.chat_history) renderChatHistory(data.chat_history);
  else appendBotMsg(data.greeting);
}

// ── Editable draft panel ─────────────────────────────────────────
// Structured sibling of the old read-only <pre> recap — chat and direct
// panel edits write through the exact same workflow_drafts row, so
// whichever one the admin used, the other sees it on its next render.
let diffExpanded = false;

function renderDraftPanel(state) {
  chatDraftState = state;
  const el = document.getElementById('draftPanel');
  if (!state) { el.textContent = 'Tell me what you want to build...'; return; }

  const diffs = chatLiveSnapshot ? computeDraftDiff(state, chatLiveSnapshot) : [];
  const pill = document.getElementById('diffPill');
  if (diffs.length) {
    pill.style.display = 'inline-block';
    pill.textContent = `${diffs.length} change${diffs.length > 1 ? 's' : ''} vs live v${chatLiveSnapshot.version}`;
    pill.onclick = () => { diffExpanded = !diffExpanded; renderDraftPanel(state); };
  } else {
    pill.style.display = 'none';
  }

  let html = '';
  html += panelSection('Title', state.title ? escHtml(state.title) : '<span style="color:#bbb">(untitled)</span>',
    '<button class="link-btn-sm" onclick="showEditTitleForm()">edit</button>') + '<div id="editTitleMount"></div>';
  if (state.intent_key) html += panelSection('Intent key', `<code style="font-size:11px">${escHtml(state.intent_key)}</code>`);
  html += panelSection('Type', state.workflow_type || '<span style="color:#bbb">not set yet</span>',
    '<button class="link-btn-sm" onclick="showEditTypeForm()">edit</button>') + '<div id="editTypeMount"></div>';

  const descHtml = state.description
    ? escHtml(state.description).replace(/\\n/g, '<br>')
    : '<span style="color:#bbb">(none)</span>';
  html += panelSection('Description', descHtml, '<button class="link-btn-sm" onclick="showEditDescriptionForm()">edit</button>') +
          '<div id="editDescriptionMount"></div>';

  const bizRuleHtml = state.business_rule
    ? escHtml(state.business_rule).replace(/\\n/g, '<br>')
    : '<span style="color:#bbb">(none)</span>';
  html += panelSection('Business rule', bizRuleHtml, '<button class="link-btn-sm" onclick="showEditBizRuleForm()">edit</button>') +
          '<div id="editBizRuleMount"></div>';

  const fieldsHtml = state.fields.length ? state.fields.map(f => `
    <div class="panel-field-row">
      <span class="fname">${escHtml(f.name)}</span>
      ${f.computed ? '<span style="font-size:10px;color:#aaa">calculated automatically</span>' :
        f.required === null ? '<span style="font-size:10px;color:#aaa">not compiled yet</span>' :
        `<span class="req-pill ${f.required ? 'req-yes' : 'req-no'}" onclick="toggleFieldRequired('${escAttr(f.name)}', ${!f.required})">${f.required ? 'required' : 'optional'}</span>`}
      ${f.computed ? '' : `<button class="icon-btn-sm" onclick="showRenameFieldForm('${escAttr(f.name)}')" title="Rename">✎</button><button class="icon-btn-sm" onclick="deleteDraftField('${escAttr(f.name)}')" title="Remove">🗑</button>`}
    </div>`).join('') : '<div style="color:#bbb">No fields yet.</div>';
  html += panelSection('Fields', fieldsHtml, '<button class="link-btn-sm" onclick="showAddFieldForm()">+ Add field</button>') +
          '<div id="addFieldMount"></div>';

  const gatesHtml = state.gates.length ? state.gates.map(g => `
    <div class="gate-row ${diffs.some(d => d.kind === 'gate_added' && d.id === g.id) ? 'is-new' : ''}">
      <span>${describeGateJs(g)}</span>
      <button class="icon-btn-sm" onclick="deleteDraftGate('${escAttr(g.id)}')" title="Remove">🗑</button>
    </div>`).join('') : '<div style="color:#bbb">None — no extra safety checks.</div>';
  html += panelSection('Constraints', gatesHtml, '<button class="link-btn-sm" onclick="showAddGateForm()">+ Add constraint</button>') +
          '<div id="addGateMount"></div>';

  const rolesHtml = `<div>${(orgRolesList || []).map(r => `
    <button class="role-chip-sm ${state.granted_roles.includes(r) ? 'on' : ''}" onclick="toggleDraftRole('${escAttr(r)}')">${escHtml(r)}</button>`).join('')}</div>`;
  html += panelSection('Who can use it', rolesHtml);

  const trigHtml = state.slash_command
    ? `<code>/${escHtml(state.slash_command)}</code> <button class="link-btn-sm" onclick="showEditTriggerForm()">edit</button>`
    : '<span style="color:#bbb">assigned automatically once compiled</span>';
  html += panelSection('Trigger command', trigHtml) + '<div id="editTriggerMount"></div>';

  if (diffs.length && diffExpanded) {
    html += `<div class="diff-box">${diffs.map(d => `<div>${escHtml(d.text)}</div>`).join('')}</div>`;
  }

  el.innerHTML = html;
}

function panelSection(title, valueHtml, actionHtml) {
  return `<div class="panel-section"><div class="panel-section-title"><span>${title}</span>${actionHtml || ''}</div>${valueHtml}</div>`;
}

// Escapes a value for safe use inside onclick="fn('VALUE')" — HTML-entity
// escapes first (& must go first, or its own &amp;/&lt;/&gt;/&quot; would
// get double-escaped), then the JS single-quote the inline handler uses.
function escAttr(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    .replace(/'/g, "\\\\'");
}

function describeGateJs(g) {
  const when = g.when || {};
  const cond = when.gte != null ? `above ₹${Number(when.gte).toLocaleString('en-IN')}`
    : when.field && when.equals != null ? `${when.field.split('.').pop()} = ${when.equals}` : '';
  if (g.type === 'otp') return `🔐 OTP required${cond ? ' ' + cond : ''}`;
  if (g.type === 'approval_chain') {
    const lvls = (g.levels || []).map(l =>
      `${l.role || '(role not set)'}${l.max_amount ? ' (up to ₹' + Number(l.max_amount).toLocaleString('en-IN') + ')' : ' (no ceiling)'}`
    ).join(' → ');
    return `👤 Approval${cond ? ' — ' + cond : ''}: ${lvls}`;
  }
  if (g.type === 'permission') return `🔒 Only ${(g.role_any_of || []).join(', ') || '(no role set)'} can use this`;
  return '• constraint';
}

// Diffs the CURRENT draft against the FIXED snapshot captured once when
// this edit session started (chatLiveSnapshot) — never against "live now",
// which would hide a real conflict the moment someone else published a
// change. Field/gate identity uses name/id respectively, matching how the
// backend already keys them.
function computeDraftDiff(state, snap) {
  const diffs = [];
  const curNames = state.fields.filter(f => !f.computed).map(f => f.name);
  const oldNames = snap.fields.map(f => f.name);
  curNames.filter(n => !oldNames.includes(n)).forEach(n => diffs.push({text: `+ Added field: ${n}`, kind: 'field_added'}));
  oldNames.filter(n => !curNames.includes(n)).forEach(n => diffs.push({text: `− Removed field: ${n}`, kind: 'field_removed'}));

  const curGateIds = state.gates.map(g => g.id);
  const oldGateIds = snap.gates.map(g => g.id);
  state.gates.filter(g => !oldGateIds.includes(g.id)).forEach(g => diffs.push({text: `+ Added constraint: ${describeGateJs(g)}`, kind: 'gate_added', id: g.id}));
  snap.gates.filter(g => !curGateIds.includes(g.id)).forEach(g => diffs.push({text: `− Removed constraint: ${describeGateJs(g)}`, kind: 'gate_removed', id: g.id}));

  const addedRoles = state.granted_roles.filter(r => !snap.granted_roles.includes(r));
  const removedRoles = snap.granted_roles.filter(r => !state.granted_roles.includes(r));
  if (addedRoles.length) diffs.push({text: `+ Added role(s): ${addedRoles.join(', ')}`, kind: 'roles'});
  if (removedRoles.length) diffs.push({text: `− Removed role(s): ${removedRoles.join(', ')}`, kind: 'roles'});

  if (state.slash_command !== snap.slash_command) diffs.push({text: `Trigger command changed: /${snap.slash_command} → /${state.slash_command}`, kind: 'trigger'});

  return diffs;
}

// Shared by every direct-panel-edit action below — same response shape
// (draft_recap/draft_state always, summary_card/error only from field/gate
// edits that triggered a recompile) regardless of which endpoint answered.
async function callDraftEdit(kind, body) {
  document.getElementById('builderStatus').textContent = 'Updating…';
  const r = await authenticatedFetch(API(`/workflow-builder/draft/${chatDraftId}/${kind}`), {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  document.getElementById('builderStatus').textContent = '';
  if (!r) return;
  const data = await r.json();
  if (!r.ok) { alert('Error: ' + (data.detail || 'could not save that change')); return; }
  if (data.draft_recap) chatLastRecapText = data.draft_recap;
  if (data.draft_state) renderDraftPanel(data.draft_state);
  if (data.error) appendBotMsg(`⚠️ Recompiling after that change hit a snag: ${data.error}`);
  else if (data.summary_card) appendSummaryCard(data.summary_card);
  _updateManualPublishLabel();
}

function toggleFieldRequired(name, newRequired) {
  callDraftEdit('field', {action: 'toggle_required', name, required: newRequired});
}
function deleteDraftField(name) {
  if (!confirm(`Remove field "${name}"?`)) return;
  callDraftEdit('field', {action: 'remove', name});
}
function showAddFieldForm() {
  document.getElementById('addFieldMount').innerHTML = `
    <div class="mini-form-sm">
      <input type="text" id="newFieldName" placeholder="e.g. Vehicle number">
      <button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="confirmAddField()">Add</button>
      <button class="btn btn-gray" style="padding:4px 10px;font-size:11px" onclick="document.getElementById('addFieldMount').innerHTML=''">Cancel</button>
    </div>`;
  document.getElementById('newFieldName').focus();
}
function confirmAddField() {
  const name = document.getElementById('newFieldName').value.trim();
  if (!name) return;
  document.getElementById('addFieldMount').innerHTML = '';
  callDraftEdit('field', {action: 'add', name});
}

function deleteDraftGate(id) {
  if (!confirm('Remove this constraint?')) return;
  callDraftEdit('gate', {action: 'remove', gate_id: id});
}
function showAddGateForm() {
  document.getElementById('addGateMount').innerHTML = `
    <div class="mini-form-sm">
      <select id="gateTypeSel" onchange="_toggleGateSub()">
        <option value="otp">OTP above an amount</option>
        <option value="approval_chain">Approval required</option>
        <option value="permission">Only specific roles can use this</option>
      </select>
      <div id="gateSubOtp">
        <input type="number" id="gateOtpAmount" placeholder="Amount, e.g. 50000">
      </div>
      <div id="gateSubApproval" style="display:none">
        <select id="gateApprovalCond">
          <option value="always">Always required</option>
          <option value="amount">When amount is above ₹</option>
          <option value="field">When a field equals a value</option>
        </select>
        <input type="number" id="gateApprovalAmount" placeholder="Amount" style="display:none">
        <input type="text" id="gateApprovalField" placeholder="Field name, e.g. priority" style="display:none">
        <input type="text" id="gateApprovalValue" placeholder="Value, e.g. urgent" style="display:none">
        <input type="text" id="gateApprovalRole" placeholder="Approver role, e.g. committee">
        <input type="number" id="gateApprovalCeiling" placeholder="Ceiling ₹ (optional)">
      </div>
      <div id="gateSubPermission" style="display:none">
        <div id="gatePermRoles"></div>
      </div>
      <button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="confirmAddGate()">Add</button>
      <button class="btn btn-gray" style="padding:4px 10px;font-size:11px" onclick="document.getElementById('addGateMount').innerHTML=''">Cancel</button>
    </div>`;
  document.getElementById('gatePermRoles').innerHTML = (orgRolesList || []).map(r =>
    `<button type="button" class="role-chip-sm" data-perm-role="${escAttr(r)}" onclick="this.classList.toggle('on')">${escHtml(r)}</button>`).join('');
  document.getElementById('gateApprovalCond').addEventListener('change', function () {
    document.getElementById('gateApprovalAmount').style.display = this.value === 'amount' ? 'block' : 'none';
    document.getElementById('gateApprovalField').style.display = this.value === 'field' ? 'block' : 'none';
    document.getElementById('gateApprovalValue').style.display = this.value === 'field' ? 'block' : 'none';
  });
}
function _toggleGateSub() {
  const v = document.getElementById('gateTypeSel').value;
  document.getElementById('gateSubOtp').style.display = v === 'otp' ? 'block' : 'none';
  document.getElementById('gateSubApproval').style.display = v === 'approval_chain' ? 'block' : 'none';
  document.getElementById('gateSubPermission').style.display = v === 'permission' ? 'block' : 'none';
}
function confirmAddGate() {
  const type = document.getElementById('gateTypeSel').value;
  let gate;
  if (type === 'otp') {
    gate = {type: 'otp', when: {field: '$computed.total_amount', gte: Number(document.getElementById('gateOtpAmount').value || 0)}};
  } else if (type === 'approval_chain') {
    const cond = document.getElementById('gateApprovalCond').value;
    let when = null;
    if (cond === 'amount') when = {field: '$computed.total_amount', gte: Number(document.getElementById('gateApprovalAmount').value || 0)};
    else if (cond === 'field') when = {field: '$fields.' + document.getElementById('gateApprovalField').value.trim(), equals: document.getElementById('gateApprovalValue').value.trim()};
    const role = document.getElementById('gateApprovalRole').value.trim() || 'admin';
    const ceiling = document.getElementById('gateApprovalCeiling').value;
    gate = {type: 'approval_chain', levels: [{level: 1, role, max_amount: ceiling ? Number(ceiling) : null}]};
    if (when) gate.when = when;
  } else {
    const roles = Array.from(document.querySelectorAll('#gatePermRoles .role-chip-sm.on')).map(el => el.getAttribute('data-perm-role'));
    gate = {type: 'permission', role_any_of: roles.length ? roles : ['admin']};
  }
  document.getElementById('addGateMount').innerHTML = '';
  callDraftEdit('gate', {action: 'add', gate});
}

function toggleDraftRole(role) {
  const roles = chatDraftState.granted_roles.includes(role)
    ? chatDraftState.granted_roles.filter(r => r !== role)
    : [...chatDraftState.granted_roles, role];
  callDraftEdit('roles', {roles});
}

function showEditTriggerForm() {
  document.getElementById('editTriggerMount').innerHTML = `
    <div class="mini-form-sm">
      <input type="text" id="newTrigger" value="${escAttr(chatDraftState.slash_command || '')}">
      <button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="confirmEditTrigger()">Save</button>
      <button class="btn btn-gray" style="padding:4px 10px;font-size:11px" onclick="document.getElementById('editTriggerMount').innerHTML=''">Cancel</button>
    </div>`;
}
function confirmEditTrigger() {
  const cmd = document.getElementById('newTrigger').value.trim();
  document.getElementById('editTriggerMount').innerHTML = '';
  callDraftEdit('trigger', {slash_command: cmd});
}

function showEditDescriptionForm() {
  document.getElementById('editDescriptionMount').innerHTML = `
    <div class="mini-form-sm">
      <textarea id="newDescription" rows="2" style="width:100%;font-family:inherit;font-size:12px;padding:5px 7px;border:1px solid #e8edf5;border-radius:5px">${escHtml(chatDraftState.description || '')}</textarea>
      <button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="confirmEditDescription()">Save</button>
      <button class="btn btn-gray" style="padding:4px 10px;font-size:11px" onclick="document.getElementById('editDescriptionMount').innerHTML=''">Cancel</button>
    </div>`;
}
function confirmEditDescription() {
  const desc = document.getElementById('newDescription').value.trim();
  document.getElementById('editDescriptionMount').innerHTML = '';
  callDraftEdit('description', {description: desc});
}

function showEditTitleForm() {
  document.getElementById('editTitleMount').innerHTML = `
    <div class="mini-form-sm">
      <input type="text" id="newTitle" value="${escAttr(chatDraftState.title || '')}">
      <button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="confirmEditTitle()">Save</button>
      <button class="btn btn-gray" style="padding:4px 10px;font-size:11px" onclick="document.getElementById('editTitleMount').innerHTML=''">Cancel</button>
    </div>`;
}
function confirmEditTitle() {
  const name = document.getElementById('newTitle').value.trim();
  if (!name) return;
  document.getElementById('editTitleMount').innerHTML = '';
  callDraftEdit('title', {name});
}

function showEditTypeForm() {
  document.getElementById('editTypeMount').innerHTML = `
    <div class="mini-form-sm">
      <select id="newType">
        <option value="action" ${chatDraftState.workflow_type === 'action' ? 'selected' : ''}>action</option>
        <option value="read" ${chatDraftState.workflow_type === 'read' ? 'selected' : ''}>read</option>
      </select>
      <button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="confirmEditType()">Save (recompiles)</button>
      <button class="btn btn-gray" style="padding:4px 10px;font-size:11px" onclick="document.getElementById('editTypeMount').innerHTML=''">Cancel</button>
    </div>`;
}
function confirmEditType() {
  const wtype = document.getElementById('newType').value;
  document.getElementById('editTypeMount').innerHTML = '';
  callDraftEdit('type', {workflow_type: wtype});
}

function showEditBizRuleForm() {
  document.getElementById('editBizRuleMount').innerHTML = `
    <div class="mini-form-sm">
      <textarea id="newBizRule" rows="3" style="width:100%;font-family:inherit;font-size:12px;padding:5px 7px;border:1px solid #e8edf5;border-radius:5px">${escHtml(chatDraftState.business_rule || '')}</textarea>
      <button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="confirmEditBizRule()">Save (recompiles)</button>
      <button class="btn btn-gray" style="padding:4px 10px;font-size:11px" onclick="document.getElementById('editBizRuleMount').innerHTML=''">Cancel</button>
    </div>`;
}
function confirmEditBizRule() {
  const rules = document.getElementById('newBizRule').value.trim();
  document.getElementById('editBizRuleMount').innerHTML = '';
  callDraftEdit('business-rule', {business_rules: rules});
}

function showRenameFieldForm(oldName) {
  document.getElementById('addFieldMount').innerHTML = `
    <div class="mini-form-sm">
      <label style="font-size:11px;color:#888;display:block;margin-bottom:3px">Rename "${escHtml(oldName)}" to:</label>
      <input type="text" id="renameFieldNew" value="${escAttr(oldName)}">
      <button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="confirmRenameField('${escAttr(oldName)}')">Save</button>
      <button class="btn btn-gray" style="padding:4px 10px;font-size:11px" onclick="document.getElementById('addFieldMount').innerHTML=''">Cancel</button>
    </div>`;
  document.getElementById('renameFieldNew').focus();
}
function confirmRenameField(oldName) {
  const newName = document.getElementById('renameFieldNew').value.trim();
  document.getElementById('addFieldMount').innerHTML = '';
  if (!newName || newName === oldName) return;
  callDraftEdit('field', {action: 'rename', name: oldName, new_name: newName});
}

async function onPdfSelected(input) {
  if (!input.files.length) return;
  const file = input.files[0];
  document.getElementById('attachLabel').textContent = file.name;
  document.getElementById('builderStatus').textContent = '⏳ Analyzing PDF layout...';

  try {
    const fd = new FormData();
    fd.append('pdf_file', file);
    fd.append('doc_type_hint', 'invoice');
    const resp = await authenticatedFetch(API('/workflow-builder/pdf-extract'), {method:'POST', body:fd});
    if (resp && resp.ok) {
      chatPdfAnalysis = await resp.json();
      document.getElementById('builderStatus').textContent = '✅ PDF layout extracted — send your message to continue.';
    } else {
      document.getElementById('builderStatus').textContent = '⚠️ Could not analyze PDF — will proceed without it.';
    }
  } catch(e) {
    document.getElementById('builderStatus').textContent = '⚠️ PDF analysis failed — will proceed without it.';
  }
}

function appendBotMsg(text) {
  const el = document.createElement('div');
  el.className = 'chat-msg bot';
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.innerHTML = text.split('\\n').join('<br>');
  el.appendChild(bubble);
  document.getElementById('chatMessages').appendChild(el);
  el.scrollIntoView({behavior:'smooth'});
}
function appendUserMsg(text) {
  const el = document.createElement('div');
  el.className = 'chat-msg user';
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.textContent = text;
  el.appendChild(bubble);
  document.getElementById('chatMessages').appendChild(el);
  el.scrollIntoView({behavior:'smooth'});
}
function appendSummaryCard(text) {
  const el = document.createElement('div');
  el.className = 'summary-card';
  el.innerHTML = '&#x1F4CB; <strong>Summary</strong><br><br>' + text.split('\\n').join('<br>');
  document.getElementById('chatMessages').appendChild(el);
  el.scrollIntoView({behavior:'smooth'});
}

async function sendChatMsg() {
  if (chatTyping) return;
  const input = document.getElementById('chatInput');
  const msg   = input.value.trim();
  if (!msg) return;

  appendUserMsg(msg);
  input.value = '';

  chatTyping = true;
  document.getElementById('builderStatus').textContent = 'Thinking...';

  try {
    const body = {
      message:      msg,
      draft_id:     chatDraftId,
      pdf_analysis: chatPdfAnalysis  // pre-extracted, null if no PDF
    };
    // Clear pdf analysis after sending so it's not re-sent on every turn
    chatPdfAnalysis = null;
    document.getElementById('attachLabel').textContent = '';
    document.getElementById('chatAttachment').value = '';

    const resp = await authenticatedFetch(API('/workflow-builder/chat'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    if (!resp) {
      chatTyping = false;
      return;
    }
    const data = await resp.json();
    chatDraftId = data.draft_id;

    // Deterministic, server-rendered — always reflects what's actually
    // saved, not what the LLM's reply claims (see build_draft_recap).
    if (data.draft_recap) chatLastRecapText = data.draft_recap;
    if (data.draft_state) renderDraftPanel(data.draft_state);

    if (data.summary_card) appendSummaryCard(data.summary_card);
    if (data.reply) appendBotMsg(data.reply);

    if (data.ready_for_publish) {
      document.getElementById('builderStatus').textContent = '';
      showPublishConfirm(data.draft_id, data.draft_recap);
    } else {
      document.getElementById('builderStatus').textContent = '';
    }
  } catch(e) {
    appendBotMsg('Something went wrong — please try again.');
    document.getElementById('builderStatus').textContent = '';
  }
  chatTyping = false;
}

// Lets the admin open the publish screen on demand instead of waiting for
// the assistant to decide the draft is "ready" — the chat has no explicit
// save/update button otherwise, which read as broken when editing an
// existing workflow's logic and just wanting to commit a small change.
function manualPublish() {
  if (!chatDraftId) { alert("Nothing to save yet — describe the workflow first."); return; }
  showPublishConfirm(chatDraftId, chatLastRecapText);
}

// ── Confirm & Publish ───────────────────────────────────────────────
// Nothing to fill in here — roles, constraints, and the trigger command
// were all gathered by chatting. This is the one explicit, human click that
// actually writes to the live workflows table; the LLM can never trigger it.
function showPublishConfirm(draftId, recap) {
  document.getElementById('publishDraftId').value = draftId;
  document.getElementById('publishRecap').textContent = recap || '';
  document.getElementById('publishStatus').textContent = '';
  closeModal('builderModal');
  openModal('publishModal');
}

function backToChat() {
  closeModal('publishModal');
  openModal('builderModal');
}

async function publishDraft() {
  const draftId = document.getElementById('publishDraftId').value;
  document.getElementById('publishStatus').textContent = 'Publishing...';
  const r = await authenticatedFetch(API(`/workflow-builder/publish/${draftId}`), {method: 'POST'});
  if (!r) { document.getElementById('publishStatus').textContent = ''; return; }
  const d = await r.json();
  if (r.ok) {
    alert('✅ Workflow published!');
    closeModal('publishModal');
    loadData();
    loadDrafts();
  } else if (r.status === 409) {
    // Someone else published a change to this same workflow while this
    // draft was open — never auto-merged, see PublishConflict's docstring.
    document.getElementById('publishStatus').textContent = '';
    document.getElementById('conflictDraftId').value = draftId;
    document.getElementById('conflictBody').innerHTML =
      escHtml(d.detail.error) + '<br><br>Your changes are still safe in this draft — they just haven\\'t been saved over the live workflow yet.';
    closeModal('publishModal');
    openModal('conflictModal');
  } else {
    const detail = d.detail;
    const msg = typeof detail === 'object' ? (detail.error + (detail.problems ? '\\n• ' + detail.problems.join('\\n• ') : '')) : detail;
    alert('Error: ' + msg);
    document.getElementById('publishStatus').textContent = '';
  }
}

async function discardAndReloadLatest() {
  const draftId = document.getElementById('conflictDraftId').value;
  closeModal('conflictModal');
  const r = await authenticatedFetch(API(`/workflow-builder/draft/${draftId}/discard-and-reload`), {method: 'POST'});
  if (!r || !r.ok) { alert('Could not reload the latest version — try "Edit the logic" again from the workflow list.'); return; }
  const data = await r.json();
  _resetBuilderModal();
  chatDraftId = data.draft_id;
  chatIsEditingExisting = true;
  chatLiveSnapshot = data.live_snapshot || null;
  chatLastRecapText = data.draft_recap || '';
  renderDraftPanel(data.draft_state);
  document.getElementById('builderTitle').textContent = `💬 Editing: ${data.name || 'Workflow'}`;
  _updateManualPublishLabel();
  _updateViewJsonBtn();
  openModal('builderModal');
  appendBotMsg("This is a fresh copy of the current live version — your change from the discarded draft was NOT carried over, since automatically re-applying it risks silently producing something incorrect. Tell me (or use the panel) to make that change again.");
}

// ── Load Data ─────────────────────────────────────────────────────
async function loadData() {
  const resp = await authenticatedFetch(API('/data'));
  if (!resp || !resp.ok) {
    document.getElementById('loading').textContent = resp && resp.status === 404
      ? `⚠️ Unknown org '${ORG_SLUG}'.`
      : '⚠️ Could not load admin data.';
    return;
  }
  try {
    const data = await resp.json();

    if (data.error) {
      document.getElementById('loading').textContent = '❌ ' + data.error;
      return;
    }

    document.getElementById('orgName').textContent = data.org.name;
    refreshOrgRoles();  // fire-and-forget — populates the "Who can use it" role checkboxes
    loadDrafts();       // fire-and-forget — populates "Continue a draft"

    try {
      const sec = await authenticatedFetch(API('/security'));
      if (sec) {
        const mins = (await sec.json()).session_ttl_minutes || 480;
        if (mins >= 60 && mins % 60 === 0) {
          document.getElementById('ttl_value').value = mins / 60;
          document.getElementById('ttl_unit').value = 'hours';
        } else {
          document.getElementById('ttl_value').value = mins;
          document.getElementById('ttl_unit').value = 'minutes';
        }
      }
    } catch(e) {}

    try {
      const logoResp = await authenticatedFetch(API('/settings/logo'));
      if (logoResp && logoResp.ok) {
        const { logo_url } = await logoResp.json();
        _renderLogoPreview(logo_url);
      }
    } catch(e) {}

    // stats is null when this org has no dashboard_stats config set (e.g. no
    // one has configured cards for it yet) — hide the grid entirely rather
    // than show a meaningless Rs.0 / 0 that looks like real data. Cards are
    // a self-describing list (key/label/value/format/color) from the
    // backend — this renders whatever the org's config says, nothing here
    // knows in advance what a "stat card" for this org looks like.
    const fmtStat = (value, format) => {
      const n = Number(value || 0);
      return format === 'currency_inr' ? 'Rs.' + n.toLocaleString('en-IN') : n.toLocaleString('en-IN');
    };
    const s = data.stats;
    document.getElementById('statsGrid').innerHTML = (s && s.length) ? s.map(card => `
      <div class="stat-card" ${card.color ? `style="border-color:${card.color}"` : ''}>
        <div class="stat-label">${card.label}</div>
        <div class="stat-value" ${card.color ? `style="color:${card.color}"` : ''}>${fmtStat(card.value, card.format)}</div>
      </div>
    `).join('') : '';

    renderWorkflows(data.workflows || []);

    // Low stock alert — title/columns come from the same config-driven
    // low_stock block; nothing here assumes a fixed name/qty/reorder shape.
    const lowStock = data.low_stock;
    if (lowStock && lowStock.rows && lowStock.rows.length > 0) {
      document.getElementById('lowStockCard').style.display = 'block';
      document.getElementById('lowStockTitle').textContent = '⚠️ ' + lowStock.title;
      document.getElementById('lowStockHead').innerHTML =
        lowStock.columns.map(c => `<th>${c.label}</th>`).join('');
      document.getElementById('lowStockTable').innerHTML = lowStock.rows.map(row => `
        <tr>${lowStock.columns.map(c => `<td>${row[c.key]}</td>`).join('')}</tr>
      `).join('');
    } else {
      document.getElementById('lowStockCard').style.display = 'none';
    }

    document.getElementById('loading').style.display = 'none';
    document.getElementById('content').style.display = 'block';
  } catch(e) {
    document.getElementById('loading').textContent = 'Error loading data: ' + e.message;
  }
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

let activityPage = 1;
let activityTotalPages = 1;
let activityUsersLoaded = false;
let activityRows = [];

function viewActivityConvoByIndex(idx) {
  const r = activityRows[idx];
  if (r) viewActivityConvo(r.session_id, r);
}

function activityParams(page) {
  const p = new URLSearchParams({ page: page, page_size: 10 });
  const user = document.getElementById('actUser').value;
  const from = document.getElementById('actFrom').value;
  const to = document.getElementById('actTo').value;
  const outcome = document.getElementById('actOutcome').value;
  const search = document.getElementById('actSearch').value.trim();
  if (user) p.set('user_id', user);
  if (from) p.set('date_from', from);
  if (to) p.set('date_to', to);
  if (outcome) p.set('outcome', outcome);
  if (search) p.set('search', search);
  return p;
}

async function loadActivity(page = 1) {
  activityPage = page;
  const res = await authenticatedFetch(API('/activity?' + activityParams(page).toString()));
  if (!res || !res.ok) return;
  const data = await res.json();

  if (!activityUsersLoaded) {
    const sel = document.getElementById('actUser');
    (data.users || []).forEach(u => {
      const opt = document.createElement('option');
      opt.value = u.id; opt.textContent = u.name;
      sel.appendChild(opt);
    });
    activityUsersLoaded = true;
  }

  activityRows = data.rows || [];
  document.getElementById('activityTable').innerHTML = activityRows.map((r, idx) => `
    <tr>
      <td style="color:#888;font-size:12px">${fmtDate(r.created_at)}</td>
      <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(r.user_name) || '—'}</td>
      <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(r.input_text)}">${escHtml(r.input_text) || '—'}</td>
      <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#888" title="${escHtml(r.response_text)}">${escHtml(r.response_text) || '—'}</td>
      <td><span class="badge badge-read">${escHtml(r.workflow)}</span></td>
      <td><span class="badge ${r.outcome==='success'?'badge-active':'badge-inactive'}">${escHtml(r.outcome)}</span></td>
      <td><button class="btn btn-gray" style="padding:4px 10px" onclick="viewActivityConvoByIndex(${idx})">View</button></td>
    </tr>
  `).join('') || '<tr><td colspan="7" style="color:#aaa">No activity matches these filters</td></tr>';

  const total = data.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / (data.page_size || 10)));
  activityTotalPages = totalPages;
  const start = total ? (page - 1) * (data.page_size || 10) + 1 : 0;
  const end = Math.min(page * (data.page_size || 10), total);
  document.getElementById('activityInfo').textContent = total ? `Showing ${start}-${end} of ${total}` : '';
  document.getElementById('activityPageNum').textContent = `Page ${page} of ${totalPages}`;
  document.getElementById('activityPrev').disabled = page <= 1;
  document.getElementById('activityNext').disabled = page >= totalPages;
}

function changeActivityPage(delta) {
  const next = activityPage + delta;
  if (next < 1 || next > activityTotalPages) return;
  loadActivity(next);
}

function resetActivityFilters() {
  ['actUser','actFrom','actTo','actOutcome','actSearch'].forEach(id => document.getElementById(id).value = '');
  loadActivity(1);
}

async function viewActivityConvo(sessionId, fallbackRow) {
  document.getElementById('activityConvoTitle').textContent =
    (fallbackRow.user_name || 'Conversation') + ' — ' + fmtDate(fallbackRow.created_at);
  let thread;
  if (sessionId) {
    const res = await authenticatedFetch(API('/activity/session?session_id=' + encodeURIComponent(sessionId)));
    thread = res && res.ok ? (await res.json()).rows : [];
  } else {
    thread = [];
  }
  if (!thread.length) {
    // Legacy row logged before session_id/response_text existed, or a
    // one-off with nothing else in that session — fall back to just this
    // row's own message/reply instead of showing an empty modal.
    thread = [{ input_text: fallbackRow.input_text, response_text: fallbackRow.response_text }];
  }
  const bubbles = [];
  thread.forEach(turn => {
    if (turn.input_text) bubbles.push(['user', turn.input_text]);
    bubbles.push(['bot', turn.response_text || '(no reply recorded)']);
  });
  document.getElementById('activityConvoThread').innerHTML = bubbles.map(([who, text]) => `
    <div style="align-self:${who==='bot'?'flex-end':'flex-start'};max-width:80%;background:${who==='bot'?'#e6f1fb':'#f0f4f8'};color:#1a1a2e;padding:8px 12px;border-radius:8px;font-size:13px">${escHtml(text)}</div>
  `).join('');
  openModal('activityConvoModal');
}

['actUser','actFrom','actTo','actOutcome'].forEach(id =>
  document.getElementById(id).addEventListener('change', () => loadActivity(1)));
document.getElementById('actSearch').addEventListener('input', () => loadActivity(1));

loadData();
loadActivity();
setInterval(loadData, 30000);
</script>
</body>
</html>"""
