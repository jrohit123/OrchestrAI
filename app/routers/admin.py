import os
import json
import re
import hmac
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from app.config import required
from app.db import fetch_all, fetch_one, execute, get_all_source_keys
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)
router = APIRouter()

ADMIN_TOKEN = required("ADMIN_TOKEN")


def _parse_jsonb(val, default):
    """
    asyncpg returns jsonb columns as raw JSON text — there's no codec
    registered in app/db.py — so anything read via fetch_all/fetch_one and
    handed straight to a JSON API response reaches the frontend as a STRING,
    not the array/object it looks like. gates specifically broke on this
    (`gates.map is not a function`) because .map()/.length on a JSON-text
    string doesn't throw the way you'd expect until you actually call .map.
    """
    if val is None:
        return default
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default
    return val


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

async def _compute_dashboard_stats(cfg: dict, org_id: str, source_key: str) -> list | None:
    from app.services.step_interpreter import _load_schema_allowlist, _validate_identifier, StepError

    cards = cfg.get("cards") or []
    if not cards:
        return None

    allowlist = await _load_schema_allowlist(source_key)
    out: list = []
    for card in cards:
        try:
            table  = card["table"]
            key    = card["key"]
            agg    = card.get("agg", "count")
            column = card.get("column")
            where  = card.get("where") or {}

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

            where_cols   = list(where.keys())
            where_clause = " AND ".join(f"{c} = ${i+2}" for i, c in enumerate(where_cols))
            where_sql    = f"WHERE org_id = $1 AND {where_clause}" if where_clause else "WHERE org_id = $1"

            if agg == "sum" and column:
                sql = f"SELECT COALESCE(SUM({column}), 0) AS val FROM {table} {where_sql}"
            else:
                sql = f"SELECT COUNT(*) AS val FROM {table} {where_sql}"

            row = await fetch_one(sql, org_id, *where.values(), source_key=source_key)
            value = row["val"] if row else 0
            # Cards are returned as a self-describing list (key/label/value/
            # format/color), not a bare {key: value} dict — so the frontend
            # renders whatever cards this org configured with zero hardcoded
            # knowledge of what a "stat card" for this org looks like.
            out.append({
                "key":    key,
                "label":  card.get("label") or key.replace("_", " ").title(),
                "value":  value,
                "format": card.get("format", "number"),
                "color":  card.get("color"),
            })
        except (KeyError, StepError) as e:
            logger.warning(f"dashboard_stats: skipping malformed card {card}: {e}")
            continue

    return out or None


async def _compute_low_stock(cfg: dict, org_id: str, source_key: str) -> dict | None:
    from app.services.step_interpreter import _load_schema_allowlist, _validate_identifier, StepError

    ls = cfg.get("low_stock")
    if not ls:
        return None

    try:
        table        = ls["table"]
        qty_col      = ls["qty_column"]
        reorder_col  = ls["reorder_column"]
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
            org_id, source_key=source_key
        )
        # Row-shaped output the frontend renders generically: a title,
        # ordered {key, label} columns, and rows keyed by those same column
        # names — never a hardcoded "name/qty/reorder_level" assumption.
        return {
            "title":   ls.get("label", "Low Stock Alert"),
            "columns": [{"key": c, "label": c.replace("_", " ").title()} for c in display_cols],
            "rows":    [dict(r) for r in rows],
        }
    except (KeyError, StepError) as e:
        logger.warning(f"dashboard_stats.low_stock: skipping malformed config {ls}: {e}")
        return None


@router.get("/admin/{org_slug}/api/data")
async def admin_data(org_slug: str):
    source_key = await _resolve_source_key(org_slug)

    org = await fetch_one("SELECT id, name, settings FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key)
    if not org:
        return {"error": "No active org found"}

    org_dict = dict(org)
    org_settings = _parse_jsonb(org_dict.pop("settings", None), {})
    org_id = str(org["id"])

    workflows = await fetch_all("""
        SELECT id, name, intent_key, is_active, otp_required,
               otp_threshold, approval_threshold, gates, last_run, workflow_type
        FROM workflows WHERE org_id = $1
        ORDER BY created_at
    """, org_id, source_key=source_key)

    # Dashboard stat cards and the low-stock table are entirely config-driven
    # (orgs.settings->'dashboard_stats') — see the helpers above. An org that
    # hasn't configured this simply gets no cards, never a guess at what
    # tables it might have.
    dashboard_cfg = org_settings.get("dashboard_stats") or {}
    stats     = await _compute_dashboard_stats(dashboard_cfg, org_id, source_key)
    low_stock = await _compute_low_stock(dashboard_cfg, org_id, source_key)

    recent_logs = await fetch_all("""
        SELECT a.intent_key, a.outcome, a.otp_used,
               a.created_at, u.name as user_name
        FROM audit_log a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE a.org_id = $1
        ORDER BY a.created_at DESC LIMIT 8
    """, org_id, source_key=source_key)

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
        "recent_logs": [dict(r) for r in recent_logs]
    }


@router.post("/admin/{org_slug}/api/workflow/{workflow_id}/toggle")
async def toggle_otp(org_slug: str, workflow_id: str):
    source_key = await _resolve_source_key(org_slug)
    row = await fetch_one(
        "SELECT otp_required, org_id FROM workflows WHERE id = $1", workflow_id, source_key=source_key
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    new_val = not row["otp_required"]
    await execute(
        "UPDATE workflows SET otp_required = $1 WHERE id = $2",
        new_val, workflow_id, source_key=source_key
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
        threshold, workflow_id, source_key=source_key
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
        threshold, workflow_id, source_key=source_key
    )
    return {"approval_threshold": threshold}


@router.get("/admin/{org_slug}/api/roles")
async def get_roles(org_slug: str):
    source_key = await _resolve_source_key(org_slug)
    roles = await fetch_all("SELECT name FROM roles ORDER BY name", source_key=source_key)
    return [{"name": r["name"], "selected": r["name"] == "owner"} for r in roles]


@router.get("/admin/{org_slug}/api/security")
async def get_security_settings(org_slug: str):
    source_key = await _resolve_source_key(org_slug)
    org = await fetch_one(
        "SELECT id, session_ttl_minutes FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key
    )
    return {"session_ttl_minutes": org["session_ttl_minutes"] or 480, "org_id": str(org["id"])}


@router.post("/admin/{org_slug}/api/security/ttl")
async def update_session_ttl(org_slug: str, request: Request):
    body = await request.json()
    minutes = int(body.get("minutes", 480))
    if minutes < 5 or minutes > 10080:  # 5 min to 7 days
        raise HTTPException(status_code=400, detail="TTL must be between 5 and 10080 minutes")
    source_key = await _resolve_source_key(org_slug)
    org_id = body.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id required")
    await execute(
        "UPDATE orgs SET session_ttl_minutes = $1 WHERE id = $2", minutes, org_id, source_key=source_key
    )
    return {"session_ttl_minutes": minutes}


@router.post("/admin/{org_slug}/api/sessions/clear")
async def admin_clear_sessions(org_slug: str):
    from app.redis_client import clear_all_sessions
    source_key = await _resolve_source_key(org_slug)
    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key)
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
        "UPDATE orgs SET gst_rate = $1 WHERE id = $2", gst, org_id, source_key=source_key
    )
    return {"gst_rate": gst}


# â”€â”€ New endpoints: workflow detail, edit, delete, chat builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_JSONB_WORKFLOW_FIELDS = {
    "training_phrases": [], "entity_schema": {}, "calc_rules": {}, "steps": [],
    "sql_params_order": [], "business_glossary": {}, "pdf_config": None, "gates": [],
}


@router.get("/admin/{org_slug}/api/workflow/{workflow_id}/detail")
async def get_workflow_detail(org_slug: str, workflow_id: str):
    source_key = await _resolve_source_key(org_slug)
    row = await fetch_one("SELECT * FROM workflows WHERE id = $1", workflow_id, source_key=source_key)
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    wd = dict(row)
    for field, default in _JSONB_WORKFLOW_FIELDS.items():
        if field in wd:
            wd[field] = _parse_jsonb(wd[field], default)
    granted = await fetch_all(
        "SELECT name FROM roles WHERE org_id = $1 AND $2 = ANY(permissions)",
        wd["org_id"], wd["intent_key"], source_key=source_key
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

    existing = await fetch_one("SELECT * FROM workflows WHERE id = $1", workflow_id, source_key=source_key)
    if not existing:
        raise HTTPException(status_code=404, detail="Workflow not found")

    allowed = ["name", "description", "is_active", "gates", "slash_command"]
    jsonb_fields = {"gates"}

    if "gates" in body:
        from app.services.workflow_validator import validate_workflow_config
        problems = validate_workflow_config({
            "workflow_type": existing["workflow_type"], "gates": body["gates"],
        })
        if problems:
            raise HTTPException(status_code=400, detail={
                "error": "Constraints are inconsistent — not saved.",
                "problems": problems
            })

    if "slash_command" in body:
        cmd = (body.get("slash_command") or "").strip().lstrip("/").lower()
        if not re.fullmatch(r"[a-z0-9_]{2,32}", cmd):
            raise HTTPException(status_code=400, detail="Command: 2-32 chars, lowercase letters/digits/_")
        dupe = await fetch_one(
            "SELECT id FROM workflows WHERE org_id = $1 AND slash_command = $2 AND is_active = true AND id != $3",
            existing["org_id"], cmd, workflow_id, source_key=source_key
        )
        if dupe:
            raise HTTPException(status_code=409, detail=f"Command '/{cmd}' is already in use")
        body["slash_command"] = cmd

    sets, vals = [], []
    for field in allowed:
        if field in body:
            sets.append(f"{field} = ${len(vals)+2}")
            val = body[field]
            if field in jsonb_fields:
                val = json.dumps(val) if not isinstance(val, str) else val
                sets[-1] = f"{field} = ${len(vals)+2}::jsonb"
            vals.append(val)

    if sets:
        await execute(
            f"UPDATE workflows SET {', '.join(sets)} WHERE id = $1",
            workflow_id, *vals, source_key=source_key
        )
    elif "roles" not in body:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "roles" in body:
        from app.services.workflow_publisher import sync_role_grants
        await sync_role_grants(existing["intent_key"], str(existing["org_id"]), body["roles"] or [], source_key)

    return {"success": True}


@router.delete("/admin/{org_slug}/api/workflow/{workflow_id}")
async def delete_workflow(org_slug: str, workflow_id: str):
    source_key = await _resolve_source_key(org_slug)
    row = await fetch_one(
        "SELECT intent_key, org_id FROM workflows WHERE id = $1", workflow_id, source_key=source_key
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await execute("""
        UPDATE roles SET permissions = array_remove(permissions, $1)
        WHERE org_id = $2
    """, row["intent_key"], row["org_id"], source_key=source_key)
    await execute("DELETE FROM workflows WHERE id = $1", workflow_id, source_key=source_key)
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
    draft = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key)
    if not draft or not draft.get("pdf_config"):
        raise HTTPException(status_code=404, detail="Nothing to preview yet — compile first")
    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key)
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
    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key)
    if not org:
        raise HTTPException(status_code=404, detail="No active org found")
    rows = await fetch_all("""
        UPDATE workflow_drafts SET status = 'abandoned', updated_at = now()
        WHERE org_id = $1 AND status = 'chatting'
        RETURNING id
    """, str(org["id"]), source_key=source_key)
    return {"cleared": len(rows)}


@router.post("/admin/{org_slug}/api/workflow-builder/chat")
async def workflow_builder_chat(org_slug: str, request: Request):
    body = await request.json()
    source_key = await _resolve_source_key(org_slug)
    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key)
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
    wf = await fetch_one("SELECT * FROM workflows WHERE id = $1", workflow_id, source_key=source_key)
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
    draft = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    org = await fetch_one("SELECT id FROM orgs WHERE is_active = true LIMIT 1", source_key=source_key)
    if not org:
        raise HTTPException(status_code=404, detail="No active org")
    
    roles = await fetch_all("SELECT name FROM roles WHERE org_id = $1 ORDER BY name", str(org["id"]), source_key=source_key)

    # Suggest command from intent_key if not set
    suggested_cmd = draft.get("slash_command") or draft.get("intent_key", "").replace("_", "")[:32]

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
        }
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

    draft = await fetch_one("SELECT * FROM workflow_drafts WHERE id = $1", draft_id, source_key=source_key)
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

    valid_roles = {r["name"] for r in await fetch_all(
        "SELECT name FROM roles WHERE org_id = $1", org_id, source_key=source_key
    )}
    if not roles or not set(roles) <= valid_roles:
        raise HTTPException(422, f"Who can use this must be a non-empty subset of {sorted(valid_roles)} — "
                                  f"go back to chat and say who should be able to use it.")

    # Structural gate validation (types, level ordering, etc.) — same checker
    # used at every other write path to workflows (see workflow_validator.py).
    from app.services.workflow_validator import validate_workflow_config
    gate_problems = validate_workflow_config({
        "workflow_type": draft.get("workflow_type") or "action",
        "gates": gates,
    })
    if gate_problems:
        raise HTTPException(422, {"error": "Constraints are inconsistent", "problems": gate_problems})

    # Every role a gate names (approval level, or permission role_any_of) must
    # actually exist in this org — the structural checker above has no DB
    # access, so that reference check lives here instead.
    referenced_roles: set[str] = set()
    for g in gates:
        for lvl in (g.get("levels") or []):
            if lvl.get("role"):
                referenced_roles.add(lvl["role"])
        for r in (g.get("role_any_of") or []):
            referenced_roles.add(r)
    unknown_roles = referenced_roles - valid_roles
    if unknown_roles:
        raise HTTPException(422, f"Constraints reference unknown role(s): {sorted(unknown_roles)}")

    if not slash_command:
        raise HTTPException(422, "No trigger command set yet — go back to chat and say what it should be.")
    cmd = slash_command.strip().lstrip("/").lower()
    if not re.fullmatch(r"[a-z0-9_]{2,32}", cmd):
        raise HTTPException(422, "Command: 2-32 chars, lowercase letters/digits/_")

    # Check command uniqueness (excluding this same workflow, since editing
    # it via chat and republishing under the same command is expected)
    dupe = await fetch_one(
        "SELECT id FROM workflows WHERE org_id = $1 AND slash_command = $2 AND is_active = true AND intent_key != $3",
        org_id, cmd, draft.get("intent_key") or "", source_key=source_key
    )
    if dupe:
        raise HTTPException(409, f"Command '/{cmd}' is already in use")

    from app.services.workflow_publisher import publish_draft
    draft_dict = dict(draft)
    draft_dict["slash_command"] = cmd
    try:
        result = await publish_draft(draft_dict, org_id, source_key)
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
/* Chat builder */
.chat-messages{height:320px;overflow-y:auto;border:1px solid #e8edf5;border-radius:8px;padding:12px;background:#fafbfc;margin-bottom:10px}
.chat-msg{margin-bottom:10px;display:flex}
.chat-msg.user{justify-content:flex-end}
.chat-bubble{max-width:80%;padding:9px 13px;border-radius:10px;font-size:13px;white-space:pre-wrap;line-height:1.5}
.chat-msg.user .chat-bubble{background:#8b5cf6;color:#fff}
.chat-msg.bot .chat-bubble{background:#fff;border:1px solid #e8edf5;color:#1a1a2e}
.summary-card{background:#f0fdf4;border:2px solid #16a34a;border-radius:8px;padding:14px;margin:10px 0;font-size:13px;line-height:1.6}
.chat-input-row{display:flex;gap:8px}
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
          <button class="btn btn-gray" style="margin-right:6px" onclick="clearUnfinishedDrafts()">🧹 Clear unfinished drafts</button>
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

    <!-- ── RECENT ACTIVITY ───────────────────────────────────────── -->
    <div class="card">
      <div class="card-title">📋 Recent Activity</div>
      <table style="table-layout:fixed">
        <thead><tr>
          <th style="width:18%">User</th><th style="width:34%">Action</th>
          <th style="width:28%">Timestamp</th><th style="width:20%">Status</th>
        </tr></thead>
        <tbody id="activityTable"></tbody>
      </table>
    </div>

  </div><!-- /content -->
</div><!-- /container -->

<!-- ── WORKFLOW SETTINGS MODAL (structural only — see PUT /workflow/{id}) ── -->
<div class="modal-bg" id="editModal">
  <div class="modal">
    <div class="modal-title">⚙️ Workflow Settings</div>
    <input type="hidden" id="editId">
    <input type="hidden" id="editWorkflowIdForLogic">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div class="field-row">
        <div class="field-label">Name</div>
        <input class="field-input" id="editName">
      </div>
      <div class="field-row">
        <div class="field-label">Intent Key (read-only)</div>
        <input class="field-input" id="editIntentKey" readonly style="background:#f9f9f9">
      </div>
    </div>
    <div class="field-row">
      <div class="field-label">Description</div>
      <textarea class="field-input" id="editDescription" rows="2"></textarea>
    </div>
    <div class="field-row">
      <div class="field-label">Trigger command</div>
      <input class="field-input" id="editSlashCommand" placeholder="e.g. stock" style="max-width:200px">
    </div>
    <div class="field-row">
      <div class="field-label">Who can use it</div>
      <div id="editRolesContainer" style="display:flex;flex-wrap:wrap;gap:14px"></div>
    </div>

    <div style="border-top:1px solid #e8edf5;margin-top:16px;padding-top:14px">
      <div class="field-label">What this workflow actually does — fields it collects, calculations, constraints (OTP / approval / permission), the step pipeline</div>
      <div style="font-size:12px;color:#888;margin-bottom:8px">
        That's logic, not a setting — it's edited by talking, same as building a new workflow.
      </div>
      <button class="btn btn-purple" onclick="openEditLogic()">💬 Edit the logic for this workflow</button>
      <button class="btn btn-gray" onclick="viewRawJson()">🔍 View raw JSON (read-only)</button>
    </div>

    <div style="display:flex;gap:8px;margin-top:16px">
      <button class="btn btn-primary" onclick="saveWorkflowEdit()">💾 Save Settings</button>
      <button class="btn btn-gray" onclick="closeModal('editModal')">Cancel</button>
    </div>
  </div>
</div>

<!-- ── RAW JSON VIEW (read-only — debugging only, not an editing surface) ── -->
<div class="modal-bg" id="jsonViewModal">
  <div class="modal" style="max-width:700px">
    <div class="modal-title" style="display:flex;justify-content:space-between">
      <span>🔍 Raw workflow JSON (read-only)</span>
      <button class="btn btn-gray" onclick="closeModal('jsonViewModal')" style="padding:4px 10px">✕</button>
    </div>
    <pre id="jsonViewContent" class="json-editor" style="min-height:400px;background:#fafbfc"></pre>
  </div>
</div>

<!-- ── WORKFLOW CHAT BUILDER MODAL ──────────────────────────────── -->
<div class="modal-bg" id="builderModal">
  <div class="modal" style="max-width:920px">
    <div class="modal-title" style="display:flex;justify-content:space-between">
      <span id="builderTitle">💬 Build / Edit a Workflow</span>
      <button class="btn btn-gray" onclick="closeModal('builderModal')" style="padding:4px 10px">✕</button>
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
        <div id="builderStatus" style="font-size:11px;color:#888;margin-top:6px;text-align:center"></div>
      </div>
      <div>
        <div class="field-label">Draft so far</div>
        <pre id="draftRecap" style="background:#fafbfc;border:1px solid #e8edf5;border-radius:8px;padding:10px;
             font-size:12px;line-height:1.6;white-space:pre-wrap;font-family:inherit;height:320px;overflow-y:auto;margin:0">Tell me what you want to build...</pre>
      </div>
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
        <button class="btn btn-gray" onclick="openEdit('${w.id}')" style="margin-right:4px">✏️ Edit</button>
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

// ── Edit Modal ────────────────────────────────────────────────────
async function openEdit(id) {
  const r = await authenticatedFetch(API(`/workflow/${id}/detail`));
  if (!r) return;
  const w = await r.json();
  document.getElementById('editId').value = id;
  document.getElementById('editWorkflowIdForLogic').value = id;
  document.getElementById('editName').value = w.name || '';
  document.getElementById('editIntentKey').value = w.intent_key || '';
  document.getElementById('editDescription').value = w.description || '';
  document.getElementById('editSlashCommand').value = w.slash_command || '';

  const granted = w.granted_roles || [];
  document.getElementById('editRolesContainer').innerHTML = (orgRolesList || []).map(r => `
    <label style="display:flex;align-items:center;gap:6px;font-size:12px">
      <input type="checkbox" value="${r}" class="edit-role-cb" ${granted.includes(r) ? 'checked' : ''}> ${r}
    </label>`).join('');

  openModal('editModal');
}

async function saveWorkflowEdit() {
  const id = document.getElementById('editId').value;
  const roles = Array.from(document.querySelectorAll('.edit-role-cb:checked')).map(cb => cb.value);
  const body = {
    name:          document.getElementById('editName').value,
    description:   document.getElementById('editDescription').value,
    slash_command: document.getElementById('editSlashCommand').value,
    roles,
  };
  const r = await authenticatedFetch(API(`/workflow/${id}`), {
    method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  });
  if (r) {
    const d = await r.json();
    if (d.success) { alert('✅ Saved'); closeModal('editModal'); loadData(); }
    else {
      const detail = d.detail;
      const msg = typeof detail === 'object' ? (detail.error + (detail.problems ? '\\n• ' + detail.problems.join('\\n• ') : '')) : detail;
      alert('Error: ' + msg);
    }
  }
}

async function viewRawJson() {
  const id = document.getElementById('editWorkflowIdForLogic').value;
  const r = await authenticatedFetch(API(`/workflow/${id}/detail`));
  if (!r) return;
  const w = await r.json();
  const view = {
    training_phrases: w.training_phrases, entity_schema: w.entity_schema,
    calc_rules: w.calc_rules, steps: w.steps, sql_template: w.sql_template,
    business_glossary: w.business_glossary, pdf_config: w.pdf_config,
    response_template: w.response_template, llm_system_prompt: w.llm_system_prompt,
  };
  document.getElementById('jsonViewContent').textContent = JSON.stringify(view, null, 2);
  openModal('jsonViewModal');
}

// ── Chat Builder ─────────────────────────────────────────────────
function _resetBuilderModal() {
  chatDraftId = null;
  chatPdfAnalysis = null;
  document.getElementById('chatMessages').innerHTML = '';
  document.getElementById('chatInput').value = '';
  document.getElementById('attachLabel').textContent = '';
  document.getElementById('builderStatus').textContent = '';
  document.getElementById('draftRecap').textContent = 'Tell me what you want to build...';
  document.getElementById('builderTitle').textContent = '💬 Build / Edit a Workflow';
}

function openBuilderChat() {
  _resetBuilderModal();
  openModal('builderModal');
  appendBotMsg('Hi! Tell me about the workflow you want to build — what should it do?');
}

async function clearUnfinishedDrafts() {
  if (!confirm('Clear all unfinished workflow drafts for this org?\\nThis abandons every in-progress "Build New Workflow" chat that was never published — it does not touch any live workflow.')) return;
  const r = await authenticatedFetch(API('/workflow-builder/clear-drafts'), {method: 'POST'});
  if (!r) return;
  const d = await r.json();
  alert(d.cleared > 0 ? `✅ Cleared ${d.cleared} unfinished draft(s).` : 'No unfinished drafts to clear.');
}

async function openEditLogic() {
  const id = document.getElementById('editWorkflowIdForLogic').value;
  const r = await authenticatedFetch(API(`/workflow-builder/edit/${id}`), {method: 'POST'});
  if (!r || !r.ok) { alert('Could not start edit.'); return; }
  const data = await r.json();
  _resetBuilderModal();
  chatDraftId = data.draft_id;
  document.getElementById('draftRecap').textContent = data.draft_recap || '';
  document.getElementById('builderTitle').textContent = '💬 Edit Workflow';
  closeModal('editModal');
  openModal('builderModal');
  appendBotMsg(data.greeting);
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
    if (data.draft_recap) document.getElementById('draftRecap').textContent = data.draft_recap;

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
  } else {
    const detail = d.detail;
    const msg = typeof detail === 'object' ? (detail.error + (detail.problems ? '\\n• ' + detail.problems.join('\\n• ') : '')) : detail;
    alert('Error: ' + msg);
    document.getElementById('publishStatus').textContent = '';
  }
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

    const logs = data.recent_logs || [];
    document.getElementById('activityTable').innerHTML = logs.map(l => `
      <tr>
        <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${l.user_name || '—'}</td>
        <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${l.intent_key}">${l.intent_key}</td>
        <td style="color:#888;font-size:12px">${fmtDate(l.created_at)}</td>
        <td><span class="badge ${l.outcome==='success'?'badge-active':l.outcome==='pending'?'badge-inactive':'badge-inactive'}">${l.outcome}</span></td>
      </tr>
    `).join('') || '<tr><td colspan="4" style="color:#aaa">No recent activity</td></tr>';

    document.getElementById('loading').style.display = 'none';
    document.getElementById('content').style.display = 'block';
  } catch(e) {
    document.getElementById('loading').textContent = 'Error loading data: ' + e.message;
  }
}

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""
